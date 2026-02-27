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

from flask import Blueprint, request, jsonify

try:
    import stripe
except ImportError:
    stripe = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

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
        return jsonify({"error": "Invalid signature"}), 400
    except Exception:
        logger.exception("Stripe webhook construction failed")
        return jsonify({"error": "Bad request"}), 400

    event_type = event["type"]
    event_id = event.get("id", "")
    data = event["data"]["object"]
    logger.info("Stripe event: %s (id=%s)", event_type, event_id)

    # ── Dedup check ──────────────────────────────────────────────
    conn = _get_conn()
    if _is_event_processed(conn, event_id):
        logger.info("Duplicate Stripe event %s — skipping", event_id)
        return jsonify({"status": "ok", "skipped": True}), 200

    payload_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(data)
        elif event_type == "customer.subscription.updated":
            _handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(data)
        elif event_type == "invoice.payment_failed":
            _handle_payment_failed(data)
        elif event_type == "invoice.paid":
            _handle_payment_succeeded(data)
        else:
            logger.debug("Unhandled Stripe event type: %s", event_type)
    except Exception:
        logger.exception("Error processing Stripe event %s", event_type)
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
    """
    customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")

    if not customer_email:
        logger.warning("Checkout completed but no email found: %s", session.get("id"))
        return

    plan_tier = _resolve_tier_from_checkout(session)

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET stripe_customer_id = %(cid)s, "
        "stripe_subscription_id = %(sid)s, "
        "subscription_status = %(status)s, "
        "plan_tier = %(tier)s "
        "WHERE email = %(email)s",
        {"cid": customer_id, "sid": subscription_id,
         "status": "active", "tier": plan_tier,
         "email": customer_email},
    )
    conn.commit()
    logger.info("Subscription activated for %s: tier=%s (customer=%s)",
                customer_email, plan_tier, customer_id)


def _handle_subscription_updated(subscription: dict):
    """Update subscription status when Stripe subscription changes.

    Fetches CURRENT status from Stripe API to handle out-of-order events.
    Only updates subscription_status — plan_tier changes come from
    checkout (upgrade) or explicit plan switch events.
    """
    customer_id = subscription.get("customer")
    sub_id = subscription.get("id")

    # Fetch current status from Stripe to handle out-of-order events
    try:
        current_sub = stripe.Subscription.retrieve(sub_id)
        status = current_sub.status
    except Exception:
        logger.warning("Could not fetch sub %s from Stripe — using event data", sub_id)
        status = subscription.get("status")

    # Check if the plan itself changed (price ID changed)
    items = subscription.get("items", {}).get("data", [])
    tier_update = ""
    tier_params = {}
    for item in items:
        price_id = item.get("price", {}).get("id")
        if price_id and price_id in STRIPE_PRICE_TO_TIER:
            tier_update = ", plan_tier = %(tier)s"
            tier_params["tier"] = STRIPE_PRICE_TO_TIER[price_id]
            break

    conn = _get_conn()
    conn.execute(
        f"UPDATE users SET subscription_status = %(status)s{tier_update} "
        "WHERE stripe_customer_id = %(cid)s",
        {"status": status, "cid": customer_id, **tier_params},
    )
    conn.commit()
    logger.info("Subscription updated for customer %s: status=%s%s",
                customer_id, status,
                f" tier={tier_params.get('tier')}" if tier_params else "")


def _handle_subscription_deleted(subscription: dict):
    """Handle subscription cancellation.

    Sets subscription_status to 'canceled' but keeps plan_tier
    during the grace period. A daily Celery task will downgrade
    to 'demo' after the period ends.
    """
    customer_id = subscription.get("customer")

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET subscription_status = %(status)s, "
        "stripe_subscription_id = NULL "
        "WHERE stripe_customer_id = %(cid)s",
        {"status": "canceled", "cid": customer_id},
    )
    conn.commit()
    logger.info("Subscription canceled for customer %s — grace period started", customer_id)


def _handle_payment_failed(invoice: dict):
    """Mark subscription as past_due on payment failure."""
    customer_id = invoice.get("customer")

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET subscription_status = %(status)s "
        "WHERE stripe_customer_id = %(cid)s",
        {"status": "past_due", "cid": customer_id},
    )
    conn.commit()
    logger.info("Payment failed for customer %s — marked past_due", customer_id)


def _handle_payment_succeeded(invoice: dict):
    """Clear past_due status when payment succeeds.

    Handles the past_due → active recovery path.
    """
    customer_id = invoice.get("customer")

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET subscription_status = %(status)s "
        "WHERE stripe_customer_id = %(cid)s "
        "AND subscription_status = %(prev_status)s",
        {"status": "active", "cid": customer_id, "prev_status": "past_due"},
    )
    conn.commit()
    logger.info("Payment recovered for customer %s — active again", customer_id)
