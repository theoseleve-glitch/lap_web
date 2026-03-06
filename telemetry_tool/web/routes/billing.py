"""Stripe webhook handler for subscription lifecycle events.

Updated for the entitlements system (migration 019):
- billing_plan renamed to subscription_status (Stripe state)
- plan_tier added (actual tier: demo/racer/world-class/b2b)
- Checkout resolves tier from Stripe price ID metadata
- Subscription updates only change status, not tier
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys

from flask import Blueprint, g, request, jsonify

from web.api_utils import ErrorCode, api_error, api_response
from web.middleware.audit import audit_log

try:
    import stripe
except ImportError:
    stripe = None  # type: ignore[assignment]

# ---- Rate limit import (graceful fallback) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        def decorator(fn):
            return fn
        return decorator

logger = logging.getLogger(__name__)


def log_security_event(*args, **kwargs):
    """Lazy proxy to avoid circular imports."""
    try:
        from admin.audit import log_security_event as _log
        _log(*args, **kwargs)
    except Exception:
        logger.debug("Failed to log security event", exc_info=True)


bp = Blueprint("billing", __name__, url_prefix="/api/v1/billing")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# ── Stripe Price ID → Plan Tier mapping ──────────────────────────────
# Populated from environment variables set in .env.production.
# Keys are Stripe price IDs, values are plan tier slugs.
STRIPE_PRICE_TO_TIER: dict[str, str] = {}

def _init_price_mapping():
    """Build price→tier mapping from environment variables."""
    _env_map = {
        "STRIPE_PRICE_RACER_MONTHLY": "racer",
        "STRIPE_PRICE_RACER_ANNUAL": "racer",
        "STRIPE_PRICE_WORLDCLASS_MONTHLY": "world-class",
        "STRIPE_PRICE_WORLDCLASS_ANNUAL": "world-class",
    }
    for env_key, tier in _env_map.items():
        price_id = os.environ.get(env_key)
        if price_id:
            STRIPE_PRICE_TO_TIER[price_id] = tier

_init_price_mapping()


def _get_conn():
    from flask import current_app
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    from web.db import get_db_connection
    return get_db_connection()


def _redis_event_check(event_id: str) -> bool:
    """Fast-path Redis dedup: returns True if event already processed.

    Uses SETNX with 24hr TTL. If Redis is unavailable, falls through
    to the DB dedup check.
    """
    try:
        from web.rate_limit import get_redis
        r = get_redis()
        if r is None:
            return False
        # SET NX returns True if key was set (new event), None if already exists
        was_set = r.set(f"stripe_event:{event_id}", "1", nx=True, ex=86400)
        return was_set is None  # Already existed = already processed
    except Exception:
        return False  # Fail open to DB check


def _check_event_ordering(customer_id: str, event_timestamp: int) -> bool:
    """Check if this event is newer than the last processed event for this customer.

    Returns True if event should be processed, False if out-of-order.
    """
    if not customer_id or not event_timestamp:
        return True  # Can't check — process anyway

    try:
        from web.rate_limit import get_redis
        r = get_redis()
        if r is None:
            return True

        key = f"stripe_last_event:{customer_id}"
        last_ts = r.get(key)

        if last_ts is not None and int(last_ts) > event_timestamp:
            logger.warning(
                "Out-of-order Stripe event for customer %s: event_ts=%d < last_ts=%s",
                customer_id, event_timestamp, last_ts,
            )
            return False

        # Update the timestamp
        r.set(key, str(event_timestamp), ex=86400 * 7)  # 7-day TTL
        return True
    except Exception:
        return True  # Fail open


def _is_event_processed(conn, stripe_event_id: str) -> bool:
    """Check if a Stripe event has already been processed."""
    row = conn.execute(
        "SELECT 1 FROM stripe_events WHERE stripe_event_id = %(eid)s",
        {"eid": stripe_event_id},
    ).fetchone()
    return row is not None


def _record_event(conn, stripe_event_id: str, event_type: str, payload_hash: str):
    """Record a processed Stripe event for deduplication."""
    conn.execute(
        "INSERT INTO stripe_events (stripe_event_id, event_type, payload_hash) "
        "VALUES (%(eid)s, %(etype)s, %(phash)s) "
        "ON CONFLICT (stripe_event_id) DO NOTHING",
        {"eid": stripe_event_id, "etype": event_type, "phash": payload_hash},
    )
    conn.commit()


def _update_webhook_status(conn, stripe_event_id: str, status: str, error: str | None = None):
    """Update the processing status of a webhook in stripe_webhook_log."""
    try:
        conn.execute(
            "UPDATE stripe_webhook_log SET processing_status = %(s)s, "
            "error_message = %(e)s WHERE stripe_event_id = %(id)s",
            {"s": status, "e": error, "id": stripe_event_id},
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to update webhook status", exc_info=True)


def _resolve_tier_from_checkout(session: dict) -> str:
    """Resolve plan tier from a Stripe checkout session.

    Checks in order:
    1. session.metadata.plan_tier (set by our checkout route)
    2. Line items price ID → STRIPE_PRICE_TO_TIER mapping
    3. Fallback: 'racer' (most common paid plan)
    """
    # Check metadata first (our checkout route should set this)
    metadata = session.get("metadata", {}) or {}
    tier = metadata.get("plan_tier")
    if tier in ("racer", "world-class", "b2b"):
        return tier

    # Fallback: check line items price IDs
    line_items = session.get("line_items", {}).get("data", [])
    for item in line_items:
        price_id = item.get("price", {}).get("id") if isinstance(item.get("price"), dict) else item.get("price")
        if price_id and price_id in STRIPE_PRICE_TO_TIER:
            return STRIPE_PRICE_TO_TIER[price_id]

    # Last resort: check subscription metadata if available
    sub_id = session.get("subscription")
    if sub_id and STRIPE_SECRET_KEY:
        try:
            stripe.api_key = STRIPE_SECRET_KEY
            sub = stripe.Subscription.retrieve(sub_id, expand=["items.data.price"])
            for item in sub.get("items", {}).get("data", []):
                price_id = item.get("price", {}).get("id")
                if price_id and price_id in STRIPE_PRICE_TO_TIER:
                    return STRIPE_PRICE_TO_TIER[price_id]
        except Exception:
            logger.warning("Could not fetch subscription %s to resolve tier", sub_id)

    logger.warning("Could not resolve tier from checkout session %s — defaulting to racer",
                   session.get("id"))
    return "racer"


@bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events.

    Verifies the Stripe-Signature header, then processes:
    - checkout.session.completed  → activate subscription + set plan_tier
    - customer.subscription.updated → update subscription_status
    - customer.subscription.deleted → set canceled status
    - invoice.payment_failed → mark subscription past_due
    - invoice.paid → clear past_due status
    """
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        logger.warning("Stripe keys not configured — ignoring webhook")
        return jsonify({"error": "Stripe not configured"}), 503

    stripe.api_key = STRIPE_SECRET_KEY

    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature")
        log_security_event("webhook_signature_invalid",
                           ip_address=request.remote_addr,
                           details={"sig_header_len": len(sig_header)},
                           severity="warning")
        return jsonify({"error": "Invalid signature"}), 400
    except Exception:
        logger.exception("Stripe webhook construction failed")
        return jsonify({"error": "Bad request"}), 400

    event_type = event["type"]
    event_id = event.get("id", "")
    event_created = event.get("created", 0)
    data = event["data"]["object"]
    logger.info("Stripe event: %s (id=%s)", event_type, event_id)

    # ── Fast-path Redis dedup ────────────────────────────────────
    if _redis_event_check(event_id):
        logger.info("Duplicate Stripe event %s (Redis) — skipping", event_id)
        return jsonify({"status": "ok", "skipped": True}), 200

    # ── DB dedup fallback ────────────────────────────────────────
    conn = _get_conn()
    if _is_event_processed(conn, event_id):
        logger.info("Duplicate Stripe event %s (DB) — skipping", event_id)
        return jsonify({"status": "ok", "skipped": True}), 200

    # ── Event ordering check ─────────────────────────────────────
    customer_id = data.get("customer") or ""
    if not _check_event_ordering(customer_id, event_created):
        logger.info("Out-of-order Stripe event %s — skipping", event_id)
        return jsonify({"status": "ok", "skipped_ordering": True}), 200

    payload_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]

    # Log webhook to stripe_webhook_log (pending)
    try:
        from admin.audit import log_stripe_webhook, _sanitize_payload
        sanitized = _sanitize_payload(event.get("data", {}).get("object", {}))
        log_stripe_webhook(conn, event_id, event_type, sanitized,
                           signature_valid=True, processing_status="pending")
        conn.commit()
    except Exception:
        logger.debug("Failed to log webhook to stripe_webhook_log", exc_info=True)

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(data)
        elif event_type == "customer.subscription.created":
            _handle_subscription_created(data)
        elif event_type == "customer.subscription.updated":
            _handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(data)
        elif event_type == "customer.subscription.paused":
            _handle_subscription_paused(data)
        elif event_type == "customer.subscription.resumed":
            _handle_subscription_resumed(data)
        elif event_type == "customer.subscription.trial_will_end":
            _handle_trial_will_end(data)
        elif event_type == "invoice.payment_failed":
            _handle_payment_failed(data)
        elif event_type == "invoice.paid":
            _handle_payment_succeeded(data)
        elif event_type == "charge.refunded":
            _handle_charge_refunded(data)
        else:
            logger.debug("Unhandled Stripe event type: %s", event_type)
        # Track successful webhook processing
        _update_webhook_status(conn, event_id, "processed")
        try:
            from web.metrics import incr_counter
            incr_counter("webhook_processed")
        except Exception:
            pass
    except Exception:
        logger.exception("Error processing Stripe event %s", event_type)
        _update_webhook_status(conn, event_id, "failed", str(sys.exc_info()[1]))
        try:
            from web.metrics import incr_counter
            incr_counter("webhook_failed")
        except Exception:
            pass
        return jsonify({"status": "error_logged"}), 200

    # Record event after successful processing
    try:
        _record_event(conn, event_id, event_type, payload_hash)
    except Exception:
        logger.warning("Failed to record event %s (processing succeeded)", event_id)

    return jsonify({"status": "ok"}), 200


def _handle_checkout_completed(session: dict):
    """Activate subscription after successful checkout.

    Sets both plan_tier (the actual tier) and subscription_status (active).
    Uses the state machine for the status transition.
    """
    customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")

    if not customer_email:
        logger.warning("Checkout completed but no email found: %s", session.get("id"))
        return

    plan_tier = _resolve_tier_from_checkout(session)

    conn = _get_conn()

    # First update Stripe IDs (these aren't state-machine concerns)
    conn.execute(
        "UPDATE users SET stripe_customer_id = %(cid)s, "
        "stripe_subscription_id = %(sid)s "
        "WHERE email = %(email)s",
        {"cid": customer_id, "sid": subscription_id, "email": customer_email},
    )
    conn.commit()

    # Get user ID for state machine
    cur = conn.execute(
        "SELECT id FROM users WHERE email = %(email)s",
        {"email": customer_email},
    )
    user_row = cur.fetchone()
    if user_row:
        uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]
        from billing.state_machine import transition_subscription
        transition_subscription(
            conn, uid, "active",
            plan_tier=plan_tier,
            metadata={"checkout_session": session.get("id"), "customer": customer_id},
        )
        audit_log(conn, "billing_checkout_completed", {"user_id": uid, "tier": plan_tier})
    else:
        logger.warning("Checkout completed but user not found: %s", customer_email)


def _handle_subscription_created(subscription: dict):
    """Handle new subscription creation.

    Sets stripe_subscription_id, resolves plan_tier from price IDs,
    and transitions to the appropriate billing state via state machine.
    Covers subscriptions created outside checkout (API, Stripe dashboard).
    """
    customer_id = subscription.get("customer")
    sub_id = subscription.get("id")
    stripe_status = subscription.get("status", "active")

    from billing.state_machine import map_stripe_status
    new_status = map_stripe_status(stripe_status)

    # Resolve tier from subscription items
    items = subscription.get("items", {}).get("data", [])
    plan_tier = None
    for item in items:
        price_id = item.get("price", {}).get("id")
        if price_id and price_id in STRIPE_PRICE_TO_TIER:
            plan_tier = STRIPE_PRICE_TO_TIER[price_id]
            break

    conn = _get_conn()

    # Set stripe IDs
    conn.execute(
        "UPDATE users SET stripe_customer_id = COALESCE(stripe_customer_id, %(cid)s), "
        "stripe_subscription_id = %(sid)s "
        "WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id, "sid": sub_id},
    )
    conn.commit()

    cur = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        logger.warning("Subscription created but no user for customer %s", customer_id)
        return

    uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]
    from billing.state_machine import transition_subscription
    transition_subscription(
        conn, uid, new_status,
        plan_tier=plan_tier or "racer",
        metadata={"subscription": sub_id, "customer": customer_id},
    )
    audit_log(conn, "billing_subscription_created", {"user_id": uid, "status": new_status})
    logger.info("Subscription created for customer %s: status=%s tier=%s",
                customer_id, new_status, plan_tier or "racer")


def _handle_subscription_updated(subscription: dict):
    """Update subscription status when Stripe subscription changes.

    Uses the state machine for status transitions. Resolves plan_tier
    from price IDs if the plan changed.
    """
    customer_id = subscription.get("customer")
    sub_id = subscription.get("id")

    # Fetch current status from Stripe to handle out-of-order events
    try:
        current_sub = stripe.Subscription.retrieve(sub_id)
        stripe_status = current_sub.status
    except Exception:
        logger.warning("Could not fetch sub %s from Stripe — using event data", sub_id)
        stripe_status = subscription.get("status")

    from billing.state_machine import map_stripe_status
    new_status = map_stripe_status(stripe_status)

    # Check if the plan itself changed (price ID changed)
    items = subscription.get("items", {}).get("data", [])
    plan_tier = None
    for item in items:
        price_id = item.get("price", {}).get("id")
        if price_id and price_id in STRIPE_PRICE_TO_TIER:
            plan_tier = STRIPE_PRICE_TO_TIER[price_id]
            break

    conn = _get_conn()

    # Also ensure stripe IDs are set (handles edge cases)
    conn.execute(
        "UPDATE users SET stripe_subscription_id = %(sid)s "
        "WHERE stripe_customer_id = %(cid)s AND "
        "(stripe_subscription_id IS NULL OR stripe_subscription_id != %(sid)s)",
        {"sid": sub_id, "cid": customer_id},
    )
    conn.commit()

    # Use state machine for the transition
    cur = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        logger.warning("Subscription updated but no user for customer %s", customer_id)
        return

    uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]
    from billing.state_machine import transition_subscription
    transition_subscription(
        conn, uid, new_status,
        plan_tier=plan_tier,
        metadata={"stripe_status": stripe_status, "subscription": sub_id, "customer": customer_id},
    )
    audit_log(conn, "billing_subscription_updated", {"user_id": uid, "status": new_status})
    logger.info("Subscription updated for customer %s: status=%s%s",
                customer_id, new_status,
                f" tier={plan_tier}" if plan_tier else "")


def _handle_subscription_deleted(subscription: dict):
    """Handle subscription cancellation via state machine.

    Transitions to 'canceled' (NOT immediate downgrade). The state machine
    sets grace_period_end. A daily Celery task downgrades after grace expires.
    """
    customer_id = subscription.get("customer")

    conn = _get_conn()

    cur = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        logger.warning("Subscription deleted but no user for customer %s", customer_id)
        return

    uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]

    # Clear Stripe sub ID
    conn.execute(
        "UPDATE users SET stripe_subscription_id = NULL "
        "WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    conn.commit()

    from billing.state_machine import transition_subscription
    transition_subscription(
        conn, uid, "canceled",
        metadata={"customer": customer_id, "subscription": subscription.get("id")},
    )
    audit_log(conn, "billing_subscription_deleted", {"user_id": uid})
    logger.info("Subscription canceled for customer %s — grace period started", customer_id)


def _handle_payment_failed(invoice: dict):
    """Mark subscription as past_due via state machine."""
    customer_id = invoice.get("customer")

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        logger.warning("Payment failed but no user for customer %s", customer_id)
        return

    uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]
    from billing.state_machine import transition_subscription
    transition_subscription(
        conn, uid, "past_due",
        metadata={"invoice": invoice.get("id"), "customer": customer_id},
    )
    audit_log(conn, "billing_invoice_failed", {"user_id": uid})
    logger.info("Payment failed for customer %s — marked past_due", customer_id)


def _handle_payment_succeeded(invoice: dict):
    """Clear past_due status when payment succeeds via state machine.

    Handles the past_due → active recovery path.
    """
    customer_id = invoice.get("customer")

    conn = _get_conn()

    cur = conn.execute(
        "SELECT id, subscription_status FROM users "
        "WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        return

    user = dict(user_row) if not isinstance(user_row, dict) else user_row

    # Only transition if currently past_due (state machine validates this)
    if user.get("subscription_status") == "past_due":
        from billing.state_machine import transition_subscription
        transition_subscription(
            conn, user["id"], "active",
            metadata={"invoice": invoice.get("id"), "customer": customer_id},
        )
        logger.info("Payment recovered for customer %s — active again", customer_id)


def _handle_subscription_paused(subscription: dict):
    """Handle subscription pause via state machine."""
    customer_id = subscription.get("customer")

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        logger.warning("Subscription paused but no user for customer %s", customer_id)
        return

    uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]
    from billing.state_machine import transition_subscription
    transition_subscription(conn, uid, "paused", metadata={"customer": customer_id})
    logger.info("Subscription paused for customer %s", customer_id)


def _handle_trial_will_end(subscription: dict):
    """Send trial ending notification (3 days before expiry)."""
    customer_id = subscription.get("customer")

    conn = _get_conn()
    cur = conn.execute(
        "SELECT email FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user = cur.fetchone()
    if user:
        email = (dict(user) if not isinstance(user, dict) else user).get("email")
        if email:
            _send_billing_email(email, "trial_ending")

    logger.info("Trial ending notification sent for customer %s", customer_id)


def _handle_subscription_resumed(subscription: dict):
    """Handle subscription resume (from paused state) via state machine."""
    customer_id = subscription.get("customer")

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        logger.warning("Subscription resumed but no user for customer %s", customer_id)
        return

    uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]
    from billing.state_machine import transition_subscription
    transition_subscription(conn, uid, "active", metadata={"customer": customer_id})
    logger.info("Subscription resumed for customer %s", customer_id)


def _handle_charge_refunded(charge: dict):
    """Log refund to audit_log (informational — no status change)."""
    customer_id = charge.get("customer")
    amount = charge.get("amount_refunded", 0)
    currency = charge.get("currency", "usd")

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
        {"cid": customer_id},
    )
    user_row = cur.fetchone()
    if not user_row:
        logger.warning("Charge refunded but no user for customer %s", customer_id)
        return

    uid = (dict(user_row) if not isinstance(user_row, dict) else user_row)["id"]
    import json
    try:
        conn.execute(
            "INSERT INTO audit_log (user_id, action, details) "
            "VALUES (%(uid)s, %(action)s, %(details)s)",
            {
                "uid": uid,
                "action": "charge_refunded",
                "details": json.dumps({
                    "amount_refunded": amount,
                    "currency": currency,
                    "charge_id": charge.get("id"),
                }),
            },
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to log refund for user %s", uid)

    logger.info("Charge refunded for customer %s: %d %s", customer_id, amount, currency)


# -- Billing email notifications -----------------------------------------------

def _send_billing_email(email: str, event_type: str):
    """Send billing-related email notifications via Resend."""
    try:
        from auth.email import _send, FRONTEND_URL
    except ImportError:
        logger.warning("Email module not available — skipping billing email")
        return

    templates = {
        "trial_ending": (
            "Your LAP trial ends in 3 days",
            f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Your trial ends in 3 days</h2>
  <p style="color: #8A8F98;">
    Your free trial of LAP is ending soon. Subscribe to keep access to all
    your telemetry analysis features and data.
  </p>
  <a href="{FRONTEND_URL}/pricing"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    View Plans
  </a>
  <p style="color: #8A8F98; font-size: 12px;">
    After the trial, your account will revert to the free plan with limited
    features and 30-day data retention.
  </p>
</div>""",
        ),
        "payment_failed": (
            "Payment failed — update your payment method",
            f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Payment failed</h2>
  <p style="color: #8A8F98;">
    We couldn't process your latest payment. Your subscription is still active
    during the retry period, but please update your payment method to avoid
    service interruption.
  </p>
  <a href="{FRONTEND_URL}/app/account/billing"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Update Payment Method
  </a>
  <p style="color: #8A8F98; font-size: 12px;">
    Stripe will automatically retry the payment. If it continues to fail,
    your plan will be downgraded.
  </p>
</div>""",
        ),
        "subscription_canceled": (
            "Your LAP subscription has been canceled",
            f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Subscription canceled</h2>
  <p style="color: #8A8F98;">
    Your LAP subscription has been canceled. You'll retain access to your
    current plan features until the end of your billing period.
  </p>
  <p style="color: #8A8F98;">
    After that, your account will revert to the free plan:
  </p>
  <ul style="color: #8A8F98; font-size: 14px;">
    <li>1 report per month</li>
    <li>30-day data retention</li>
    <li>Basic features only</li>
  </ul>
  <a href="{FRONTEND_URL}/pricing"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Resubscribe
  </a>
</div>""",
        ),
        "payment_recovered": (
            "Payment successful — your LAP subscription is active again",
            f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Payment successful</h2>
  <p style="color: #8A8F98;">
    Great news! Your payment has been processed successfully and your
    subscription is active again. All features are restored.
  </p>
  <a href="{FRONTEND_URL}/app"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Go to Dashboard
  </a>
</div>""",
        ),
    }

    template = templates.get(event_type)
    if template is None:
        logger.warning("Unknown billing email type: %s", event_type)
        return

    subject, html = template
    _send(email, subject, html)


FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://www.lap-coach.racing")


# ---------------------------------------------------------------------------
# GET /status — billing snapshot (plan, subscription, Stripe details)
# ---------------------------------------------------------------------------

@bp.route("/status", methods=["GET"])
@rate_limit(tier="read")
def billing_status():
    """Return a billing snapshot for the current user.

    Includes plan_tier, subscription_status, and (when Stripe is configured)
    live details: billing_cycle, current_period_end, cancel_at_period_end,
    and payment method last4/brand.
    """
    from datetime import datetime, timezone

    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = _get_conn()
    row = conn.execute(
        "SELECT plan_tier, subscription_status, stripe_customer_id, "
        "stripe_subscription_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row

    result = {
        "plan_tier": user.get("plan_tier") or "demo",
        "subscription_status": user.get("subscription_status") or "free",
        "stripe_customer_id": user.get("stripe_customer_id"),
        "billing_cycle": None,
        "current_period_end": None,
        "cancel_at_period_end": False,
        "payment_method": None,
    }

    sub_id = user.get("stripe_subscription_id")
    if sub_id and STRIPE_SECRET_KEY and stripe is not None:
        try:
            stripe.api_key = STRIPE_SECRET_KEY
            sub = stripe.Subscription.retrieve(
                sub_id,
                expand=["default_payment_method"],
            )
            result["billing_cycle"] = sub.get("plan", {}).get("interval", "month")
            if sub.get("current_period_end"):
                result["current_period_end"] = datetime.fromtimestamp(
                    sub["current_period_end"], tz=timezone.utc
                ).isoformat()
            result["cancel_at_period_end"] = bool(sub.get("cancel_at_period_end"))

            pm = sub.get("default_payment_method")
            if pm and hasattr(pm, "card") and pm.card:
                result["payment_method"] = {
                    "brand": pm.card.brand,
                    "last4": pm.card.last4,
                }
        except Exception:
            logger.warning("Failed to fetch Stripe subscription %s for billing status", sub_id)

    return api_response(result)


# ---------------------------------------------------------------------------
# POST /portal — create Stripe billing portal session
# ---------------------------------------------------------------------------

@bp.route("/portal", methods=["POST"])
@rate_limit(tier="write")
def billing_portal():
    """Create a Stripe billing portal session.

    Accepts ``{return_url}`` in body (default: frontend billing page).
    Returns ``{url}`` for the portal session redirect.

    Returns 400 if user has no Stripe customer.
    Returns 503 if Stripe is not configured.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = _get_conn()
    row = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    customer_id = (dict(row) if not isinstance(row, dict) else row).get("stripe_customer_id")
    if not customer_id:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No Stripe customer found. Subscribe to a plan first.",
            status=400,
            details=[{"code": "NO_CUSTOMER"}],
        )

    if not STRIPE_SECRET_KEY or stripe is None:
        return api_error(ErrorCode.SERVICE_UNAVAILABLE, "Stripe not configured", status=503)

    stripe.api_key = STRIPE_SECRET_KEY
    body = request.get_json(silent=True) or {}
    return_url = body.get("return_url", f"{FRONTEND_URL}/app/account/billing")

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return api_response({"url": session.url})
    except Exception:
        logger.exception("Failed to create Stripe portal session")
        return api_error(ErrorCode.INTERNAL_ERROR, "Could not create portal session", status=500)


# ---------------------------------------------------------------------------
# PATCH /email — update Stripe customer email
# ---------------------------------------------------------------------------

@bp.route("/email", methods=["PATCH"])
@rate_limit(tier="write")
def billing_email():
    """Update the email on the user's Stripe customer record.

    Accepts ``{email}`` in body.  Requires an existing Stripe customer.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    body = request.get_json(silent=True) or {}
    new_email = (body.get("email") or "").strip()
    if not new_email:
        return api_error(ErrorCode.VALIDATION_ERROR, "email is required", status=400)

    conn = _get_conn()
    row = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    customer_id = (dict(row) if not isinstance(row, dict) else row).get("stripe_customer_id")
    if not customer_id:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No Stripe customer found.",
            status=400,
            details=[{"code": "NO_CUSTOMER"}],
        )

    if not STRIPE_SECRET_KEY or stripe is None:
        return api_error(ErrorCode.SERVICE_UNAVAILABLE, "Stripe not configured", status=503)

    stripe.api_key = STRIPE_SECRET_KEY
    try:
        stripe.Customer.modify(customer_id, email=new_email)
        return api_response({"email": new_email, "updated": True})
    except Exception:
        logger.exception("Failed to update Stripe customer email")
        return api_error(ErrorCode.INTERNAL_ERROR, "Could not update billing email", status=500)
