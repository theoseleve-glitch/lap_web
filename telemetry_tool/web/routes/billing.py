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

from flask import Blueprint, g, jsonify, request

from web.api_utils import ErrorCode, api_error, api_response
from web.idempotency import idempotent
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
    # Founding-50 launch model: ONE membership. Both the standard (€19.90) and
    # founding (€14.90) prices grant the SAME full-access entitlement (internally
    # the 'world-class' tier — kept intact to avoid a risky entitlement-engine
    # rewrite days from launch). These canonical env names are read IDENTICALLY by
    # frontend (stripe-billing.ts), backend, and the Worker — the converged naming
    # that kills the old PERFORMANCE/PRO_RACER vs RACER/WORLDCLASS split-brain.
    _env_map = {
        "STRIPE_PRICE_STANDARD_MONTHLY": "world-class",
        "STRIPE_PRICE_FOUNDING_MONTHLY": "world-class",
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


def _redis_event_is_seen(event_id: str) -> bool:
    """Fast-path Redis dedup READ: returns True if event key already exists.

    Does NOT set the key — use _redis_event_mark_seen() after successful
    processing so that a handler failure leaves the key absent and Stripe
    can retry.
    """
    try:
        from web.rate_limit import get_redis
        r = get_redis()
        if r is None:
            return False
        return r.get(f"stripe_event:{event_id}") is not None
    except Exception:
        return False  # Fail open to DB check


def _redis_event_mark_seen(event_id: str) -> None:
    """Set the Redis dedup key for a successfully-processed event (24hr TTL).

    Called ONLY after the handler succeeds so that a failure leaves no key
    and Stripe retries.
    """
    try:
        from web.rate_limit import get_redis
        r = get_redis()
        if r is None:
            return
        r.set(f"stripe_event:{event_id}", "1", ex=86400)
    except Exception:
        pass  # Non-fatal: DB dedup still guards idempotency


def _redis_event_clear(event_id: str) -> None:
    """Delete the Redis dedup key so a retried delivery can be reprocessed."""
    try:
        from web.rate_limit import get_redis
        r = get_redis()
        if r is None:
            return
        r.delete(f"stripe_event:{event_id}")
    except Exception:
        pass


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


def _invalidate_cache_for_event(customer_id: str):
    """Invalidate entitlement cache when a billing event is processed."""
    if not customer_id:
        return
    try:
        from web.entitlement_cache import invalidate_by_stripe_customer
        invalidate_by_stripe_customer(customer_id)
    except Exception:
        logger.debug("Failed to invalidate entitlement cache", exc_info=True)


def _schedule_webhook_retry(conn, stripe_event_id: str):
    """Schedule a failed webhook for retry with exponential backoff."""
    try:
        from datetime import datetime, timedelta, timezone

        # Read current attempt count
        cur = conn.execute(
            "SELECT attempt_count FROM stripe_webhook_log "
            "WHERE stripe_event_id = %(eid)s",
            {"eid": stripe_event_id},
        )
        row = cur.fetchone()
        if not row:
            return
        attempt = (dict(row) if not isinstance(row, dict) else row).get("attempt_count", 1)
        backoff = [60, 300, 900, 3600, 21600, 86400]
        max_attempts = len(backoff) + 1
        if attempt >= max_attempts:
            conn.execute(
                "UPDATE stripe_webhook_log SET processing_status = 'deadletter' "
                "WHERE stripe_event_id = %(eid)s",
                {"eid": stripe_event_id},
            )
        else:
            idx = min(attempt - 1, len(backoff) - 1)
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=backoff[idx])
            conn.execute(
                "UPDATE stripe_webhook_log SET next_retry_at = %(next)s "
                "WHERE stripe_event_id = %(eid)s",
                {"eid": stripe_event_id, "next": next_retry},
            )
        conn.commit()
    except Exception:
        logger.debug("Failed to schedule webhook retry", exc_info=True)


def _resolve_tier_from_checkout(session: dict) -> str:
    """Resolve plan tier from a Stripe checkout session.

    Checks in order:
    1. session.metadata.plan_tier (set by our checkout route) — must be in
       the known-paid-tier allowlist.
    2. Line items price ID → STRIPE_PRICE_TO_TIER allowlist mapping.
    3. Subscription items price ID → STRIPE_PRICE_TO_TIER (fetched from Stripe).

    STRICT: an unmapped / unknown price or invalid metadata falls through to
    'locked', never to a paid default.  Emits logger.error + Sentry alert.
    """
    # Check metadata first (our checkout route should set this)
    metadata = session.get("metadata", {}) or {}
    tier = metadata.get("plan_tier")
    if tier in ("racer", "world-class", "b2b"):
        return tier

    # Fallback: check line items price IDs against strict allowlist
    line_items = session.get("line_items", {}).get("data", [])
    for item in line_items:
        price_id = item.get("price", {}).get("id") if isinstance(item.get("price"), dict) else item.get("price")
        if price_id and price_id in STRIPE_PRICE_TO_TIER:
            return STRIPE_PRICE_TO_TIER[price_id]

    # Last resort: check subscription items if available
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

    # No recognised price found — fail closed to 'locked', never grant a paid tier.
    _unmapped_alert(
        "checkout session",
        session.get("id"),
        extra={"metadata_tier": tier, "sub_id": sub_id},
    )
    return "locked"


def _unmapped_alert(context: str, identifier: str | None, extra: dict | None = None) -> None:
    """Emit a loud alert for an unmapped/unrecognised Stripe price or session."""
    msg = "Unmapped Stripe price in %s (id=%s) — resolving to locked%s"
    extra_str = f": {extra}" if extra else ""
    logger.error(msg, context, identifier, extra_str)
    try:
        import sentry_sdk
        sentry_sdk.capture_message(
            f"Unmapped Stripe price in {context} id={identifier}{extra_str}",
            level="error",
        )
    except Exception:
        pass


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
    if stripe is None:
        logger.warning("Stripe library not installed — ignoring webhook")
        return api_error(ErrorCode.SERVICE_UNAVAILABLE, "Stripe not available", status=503)
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        logger.warning("Stripe keys not configured — ignoring webhook")
        return api_error(ErrorCode.SERVICE_UNAVAILABLE, "Stripe not configured", status=503)

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
        return api_error(ErrorCode.VALIDATION_ERROR, "Invalid signature", status=400)
    except Exception:
        logger.exception("Stripe webhook construction failed")
        return api_error(ErrorCode.VALIDATION_ERROR, "Bad request", status=400)

    # stripe.Webhook.construct_event returns a StripeObject whose .get() raises
    # (StripeObject intercepts .get via __getattr__). Re-parse the SAME, already
    # signature-verified payload into a plain dict so every downstream .get()/[]
    # access — here and inside the _handle_* handlers (data = event[...][...]) —
    # works. Without this, EVERY real webhook 500s on event.get("id").
    # (isinstance guard leaves unit tests that mock construct_event->dict intact.)
    if not isinstance(event, dict):
        import json as _ev_json
        event = _ev_json.loads(payload)

    event_type = event["type"]
    event_id = event.get("id", "")
    event_created = event.get("created", 0)
    data = event["data"]["object"]
    logger.info("Stripe event: %s (id=%s)", event_type, event_id)

    # ── Fast-path Redis dedup (READ ONLY — do NOT set key yet) ──────────
    if _redis_event_is_seen(event_id):
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

    # Log webhook to stripe_webhook_log (pending).  This insert is best-effort:
    # a logging failure must not prevent event processing, but we do log the
    # error so it is visible in the audit trail.
    _webhook_log_ok = False
    try:
        from admin.audit import _sanitize_payload, log_stripe_webhook
        sanitized = _sanitize_payload(event.get("data", {}).get("object", {}))
        log_stripe_webhook(conn, event_id, event_type, sanitized,
                           signature_valid=True, processing_status="pending")
        conn.commit()
        _webhook_log_ok = True
    except Exception:
        logger.warning("Failed to log webhook %s to stripe_webhook_log — continuing",
                       event_id, exc_info=True)

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

        # ── Handler succeeded — mark as processed ───────────────────────
        # Record in DB first (persistent dedup), then Redis (fast-path).
        try:
            _record_event(conn, event_id, event_type, payload_hash)
        except Exception:
            logger.warning("Failed to record event %s in stripe_events (processing succeeded)",
                           event_id)
        # Only mark Redis seen AFTER successful processing so a crashed handler
        # leaves the key absent and Stripe can retry.
        _redis_event_mark_seen(event_id)

        if _webhook_log_ok:
            _update_webhook_status(conn, event_id, "processed")
            try:
                from datetime import datetime, timezone
                conn.execute(
                    "UPDATE stripe_webhook_log SET processed_at = %(now)s "
                    "WHERE stripe_event_id = %(eid)s",
                    {"now": datetime.now(timezone.utc), "eid": event_id},
                )
                conn.commit()
            except Exception:
                pass
        try:
            from web.metrics import incr_counter, record_histogram
            incr_counter("webhook_processed")
            if event_created:
                import time
                latency_ms = (time.time() - event_created) * 1000
                record_histogram("webhook_latency_ms", latency_ms)
        except Exception:
            pass
        # Invalidate entitlement cache for affected user
        _invalidate_cache_for_event(customer_id)

    except Exception:
        logger.exception("Error processing Stripe event %s (id=%s)", event_type, event_id)
        error_str = str(sys.exc_info()[1])[:500]

        # Clear the Redis key so a Stripe retry can reprocess this event.
        _redis_event_clear(event_id)

        if _webhook_log_ok:
            _update_webhook_status(conn, event_id, "failed", error_str)
            _schedule_webhook_retry(conn, event_id)
        try:
            from web.metrics import incr_counter
            incr_counter("webhook_failed")
        except Exception:
            pass
        # Return non-2xx so Stripe retries the delivery.
        return jsonify({"status": "handler_error", "event_id": event_id}), 500

    return jsonify({"status": "ok"}), 200


def _handle_checkout_completed(session: dict):
    """Activate subscription after successful checkout.

    Sets both plan_tier (the actual tier) and subscription_status (active).
    Uses the state machine for the status transition.

    User lookup order (A4):
    1. client_reference_id / metadata.user_id (explicit user binding)
    2. stripe_customer_id match (handles repeat buyers / updated customer)
    3. customer_email fallback (initial purchase path)

    On NO match: records a pending entitlement keyed by stripe_customer_id,
    emits logger.error + Sentry, and still confirms the founding-50 slot so
    the ≤50 cap stays accurate.
    """
    customer_email = session.get("customer_email") or (session.get("customer_details") or {}).get("email")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")
    session_id = session.get("id")

    plan_tier = _resolve_tier_from_checkout(session)

    conn = _get_conn()

    # ── Resolve user row — strict priority order ──────────────────
    user_row = None
    match_method = None

    # 1. client_reference_id or metadata.user_id (most explicit)
    meta_uid = (session.get("metadata") or {}).get("user_id")
    client_ref = session.get("client_reference_id")
    uid_hint = meta_uid or client_ref
    if uid_hint:
        try:
            cur = conn.execute(
                "SELECT id, email FROM users WHERE id = %(uid)s",
                {"uid": int(uid_hint)},
            )
            user_row = cur.fetchone()
            if user_row:
                match_method = "client_reference_id"
        except Exception:
            pass

    # 2. stripe_customer_id (handles re-purchases and updated customer objects)
    if user_row is None and customer_id:
        cur = conn.execute(
            "SELECT id, email FROM users WHERE stripe_customer_id = %(cid)s",
            {"cid": customer_id},
        )
        user_row = cur.fetchone()
        if user_row:
            match_method = "stripe_customer_id"

    # 3. customer_email fallback
    if user_row is None and customer_email:
        cur = conn.execute(
            "SELECT id, email FROM users WHERE email = %(email)s",
            {"email": customer_email},
        )
        user_row = cur.fetchone()
        if user_row:
            match_method = "customer_email"

    # ── Founding-50 slot confirmation — happens regardless of user match ──
    slot_raw = (session.get("metadata") or {}).get("founding_slot_no")
    if slot_raw:
        try:
            from web.founding import confirm_slot
            confirm_slot(conn, int(slot_raw), subscription_id)
            conn.commit()
        except Exception:
            logger.warning("Failed to confirm founding slot %s", slot_raw, exc_info=True)

    if user_row is None:
        # No matching user — record a pending/unmatched entitlement so it can
        # be reconciled later.  This is loud: money arrived but no account found.
        msg = (
            "Checkout completed but NO user found for stripe_customer_id=%s "
            "email=%s session=%s — recording pending entitlement for reconciliation"
        )
        logger.error(msg, customer_id, customer_email, session_id)
        try:
            import sentry_sdk
            sentry_sdk.capture_message(
                f"Unmatched checkout: customer_id={customer_id} email={customer_email} session={session_id}",
                level="error",
            )
        except Exception:
            pass
        # Store pending entitlement keyed by stripe_customer_id for later reconciliation.
        try:
            import json as _json
            conn.execute(
                "INSERT INTO stripe_pending_entitlements "
                "(stripe_customer_id, stripe_session_id, stripe_subscription_id, "
                "customer_email, plan_tier, payload_json) "
                "VALUES (%(cid)s, %(sid)s, %(sub)s, %(email)s, %(tier)s, %(payload)s) "
                "ON CONFLICT (stripe_session_id) DO NOTHING",
                {
                    "cid": customer_id,
                    "sid": session_id,
                    "sub": subscription_id,
                    "email": customer_email,
                    "tier": plan_tier,
                    "payload": _json.dumps({
                        "session_id": session_id,
                        "customer_id": customer_id,
                        "subscription_id": subscription_id,
                        "email": customer_email,
                        "plan_tier": plan_tier,
                    }),
                },
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.error(
                "Failed to record pending entitlement for customer=%s session=%s",
                customer_id, session_id, exc_info=True,
            )
        return

    user = dict(user_row) if not isinstance(user_row, dict) else user_row
    uid = user["id"]
    logger.info("Checkout matched user %s via %s", uid, match_method)

    # ── Persist Stripe IDs on the user row (so future events match by customer_id) ──
    conn.execute(
        "UPDATE users SET stripe_customer_id = %(cid)s, "
        "stripe_subscription_id = %(sid)s "
        "WHERE id = %(uid)s",
        {"cid": customer_id, "sid": subscription_id, "uid": uid},
    )
    conn.commit()

    from billing.state_machine import transition_subscription
    transition_subscription(
        conn, uid, "active",
        plan_tier=plan_tier,
        metadata={"checkout_session": session_id, "customer": customer_id},
    )
    audit_log(conn, "billing_checkout_completed", {"user_id": uid, "tier": plan_tier})


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

    # Strict tier resolution: unmapped price → 'locked', never a paid default (B4).
    if plan_tier is None:
        _unmapped_alert(
            "customer.subscription.created",
            sub_id,
            extra={"customer": customer_id, "items": [
                i.get("price", {}).get("id") for i in items
            ]},
        )
        plan_tier = "locked"

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
        plan_tier=plan_tier,
        metadata={"subscription": sub_id, "customer": customer_id},
    )
    audit_log(conn, "billing_subscription_created", {"user_id": uid, "status": new_status})
    logger.info("Subscription created for customer %s: status=%s tier=%s",
                customer_id, new_status, plan_tier)


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

    # Founding-50: free the capacity slot so it's offered to the next buyer.
    try:
        from web.founding import release_slot_by_subscription
        freed = release_slot_by_subscription(conn, subscription.get("id"))
        if freed is not None:
            conn.commit()
            logger.info("Released founding slot %s on subscription cancel", freed)
    except Exception:
        logger.warning("Failed to release founding slot on cancel", exc_info=True)

    # Send cancellation confirmation email
    email_row = conn.execute(
        "SELECT email FROM users WHERE id = %(uid)s", {"uid": uid},
    ).fetchone()
    if email_row:
        _email = (dict(email_row) if not isinstance(email_row, dict) else email_row).get("email")
        if _email:
            _send_billing_email(_email, "subscription_canceled")

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

    # Send payment failed email
    email_row = conn.execute(
        "SELECT email FROM users WHERE id = %(uid)s", {"uid": uid},
    ).fetchone()
    if email_row:
        _email = (dict(email_row) if not isinstance(email_row, dict) else email_row).get("email")
        if _email:
            _send_billing_email(_email, "payment_failed")

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

        # Send payment recovered email
        email_row = conn.execute(
            "SELECT email FROM users WHERE id = %(uid)s", {"uid": user["id"]},
        ).fetchone()
        if email_row:
            _email = (dict(email_row) if not isinstance(email_row, dict) else email_row).get("email")
            if _email:
                _send_billing_email(_email, "payment_recovered")

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
            "INSERT INTO audit_log (user_id, action, new_value) "
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
        from auth.email import FRONTEND_URL, _send
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
    After your 30-day trial ends, access pauses unless you subscribe — your
    data stays saved, so you can pick up where you left off anytime.
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
    Stripe will automatically retry the payment. If it keeps failing, your
    subscription will be canceled and access will pause — your data stays saved.
  </p>
</div>""",
        ),
        "subscription_canceled": (
            "Your LAP subscription has been canceled",
            f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Subscription canceled</h2>
  <p style="color: #8A8F98;">
    Your LAP subscription has been canceled. You'll keep full access until the
    end of your current billing period.
  </p>
  <p style="color: #8A8F98;">
    After that, your LAP access will pause and your data is kept safe —
    resubscribe anytime to restore full access and pick up where you left off.
  </p>
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
        "plan_tier": user.get("plan_tier") or "locked",
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
@idempotent
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

    # Validate return_url to prevent open redirect via Stripe portal.
    # Only allow URLs under our own frontend domain.
    from urllib.parse import urlparse
    parsed = urlparse(return_url)
    frontend_parsed = urlparse(FRONTEND_URL)
    if parsed.scheme not in ("https", "http") or parsed.netloc != frontend_parsed.netloc:
        return_url = f"{FRONTEND_URL}/app/account/billing"

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
@idempotent
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


# ---------------------------------------------------------------------------
# POST /checkout/upgrade — create Stripe Checkout Session (authenticated, reuses customer)
#
# NOTE: The public guest checkout (Founding-50) lives in api_v1_billing.py at
# POST /api/v1/billing/checkout.  This handler is for authenticated in-app
# upgrades only; it is intentionally placed at a distinct path to avoid the
# Flask blueprint registration collision that previously shadowed the founding
# handler.
# ---------------------------------------------------------------------------

# Allowlisted price IDs — only these can be selected via the API.
# Populated from environment at startup via _init_price_mapping().
# STRIPE_PRICE_TO_TIER already contains the allowlist.

@bp.route("/checkout/upgrade", methods=["POST"])
@rate_limit(tier="write")
@idempotent
def create_checkout_session():
    """Create a Stripe Checkout Session for subscription upgrade.

    Reuses existing stripe_customer_id when available. Sets plan_tier
    metadata so the webhook can resolve the tier without price ID lookup.

    Accepts ``{plan, billing_cycle, success_url, cancel_url}``.
    ``plan`` must be one of: racer, world-class.
    ``billing_cycle`` must be: monthly or annual.
    Returns ``{checkout_url}``.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    if not STRIPE_SECRET_KEY or stripe is None:
        return api_error(ErrorCode.SERVICE_UNAVAILABLE, "Stripe not configured", status=503)

    body = request.get_json(silent=True) or {}
    plan = (body.get("plan") or "").lower()
    billing_cycle = (body.get("billing_cycle") or "annual").lower()

    if plan not in ("racer", "world-class"):
        return api_error(ErrorCode.VALIDATION_ERROR, "plan must be 'racer' or 'world-class'", status=400)
    if billing_cycle not in ("monthly", "annual"):
        return api_error(ErrorCode.VALIDATION_ERROR, "billing_cycle must be 'monthly' or 'annual'", status=400)

    # Resolve price ID from allowlist
    env_key = f"STRIPE_PRICE_{'WORLDCLASS' if plan == 'world-class' else 'RACER'}_{billing_cycle.upper()}"
    price_id = os.environ.get(env_key)
    if not price_id or price_id not in STRIPE_PRICE_TO_TIER:
        return api_error(ErrorCode.VALIDATION_ERROR, f"Price not configured for {plan}/{billing_cycle}", status=400)

    stripe.api_key = STRIPE_SECRET_KEY

    conn = _get_conn()
    row = conn.execute(
        "SELECT email, stripe_customer_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    customer_id = user.get("stripe_customer_id")
    email = user.get("email")

    # Validate redirect URLs to prevent open redirect via Stripe checkout.
    from urllib.parse import urlparse as _urlparse
    _frontend_host = _urlparse(FRONTEND_URL).netloc
    _success = body.get("success_url", f"{FRONTEND_URL}/thank-you/book")
    _cancel = body.get("cancel_url", f"{FRONTEND_URL}/pricing?checkout=cancelled")
    _sp = _urlparse(_success)
    if _sp.scheme not in ("https", "http") or _sp.netloc != _frontend_host:
        _success = f"{FRONTEND_URL}/thank-you/book"
    _cp = _urlparse(_cancel)
    if _cp.scheme not in ("https", "http") or _cp.netloc != _frontend_host:
        _cancel = f"{FRONTEND_URL}/pricing?checkout=cancelled"

    # Build checkout session params
    session_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": _success,
        "cancel_url": _cancel,
        "metadata": {"plan_tier": plan, "plan": plan.upper()},
        "allow_promotion_codes": True,
        "tax_id_collection": {"enabled": True},
    }

    if customer_id:
        session_params["customer"] = customer_id
    elif email:
        session_params["customer_email"] = email

    try:
        session = stripe.checkout.Session.create(**session_params)
        try:
            from web.metrics import incr_counter
            incr_counter("checkout_session_created")
        except Exception:
            pass
        return api_response({"checkout_url": session.url})
    except Exception:
        logger.exception("Failed to create Stripe checkout session")
        return api_error(ErrorCode.INTERNAL_ERROR, "Could not create checkout session", status=500)
