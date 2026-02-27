"""Stripe webhook handler for subscription lifecycle events."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("billing", __name__, url_prefix="/api/v1/billing")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

_PLAN_FROM_PRICE_ENV = {
    os.environ.get("STRIPE_PRICE_PERFORMANCE_MONTHLY", ""): "racer",
    os.environ.get("STRIPE_PRICE_PERFORMANCE_ANNUAL", ""): "racer",
    os.environ.get("STRIPE_PRICE_PRO_RACER_MONTHLY", ""): "world_class",
    os.environ.get("STRIPE_PRICE_PRO_RACER_ANNUAL", ""): "world_class",
}

_PLAN_FROM_PRODUCT_ENV = {
    os.environ.get("STRIPE_PRODUCT_RACER", ""): "racer",
    os.environ.get("STRIPE_PRODUCT_WORLD_CLASS", ""): "world_class",
}

_STATUS_TO_TIER = {
    "active": "paid",
    "trialing": "paid",
    "past_due": "paid",
    "unpaid": "free",
    "canceled": "free",
    "incomplete": "free",
    "incomplete_expired": "free",
}


def _get_conn():
    from flask import current_app
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    from web.db import get_db_connection
    return get_db_connection()


def _from_unix(value):
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _resolve_plan_tier(payload: dict, status: str | None = None) -> str:
    metadata = payload.get("metadata") or {}
    explicit_tier = (metadata.get("plan_tier") or "").strip().lower()
    if explicit_tier:
        return explicit_tier

    line_items = (payload.get("items") or {}).get("data") or []
    first_item = line_items[0] if line_items else {}
    price = first_item.get("price") or payload.get("price") or {}
    if isinstance(price, str):
        price_id = price
        product_id = payload.get("product")
    else:
        price_id = price.get("id") or payload.get("price")
        product_id = price.get("product") or payload.get("product")

    if price_id and _PLAN_FROM_PRICE_ENV.get(price_id):
        return _PLAN_FROM_PRICE_ENV[price_id]
    if product_id and _PLAN_FROM_PRODUCT_ENV.get(product_id):
        return _PLAN_FROM_PRODUCT_ENV[product_id]

    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status in _STATUS_TO_TIER:
        return _STATUS_TO_TIER[normalized_status]
    return "free"


@bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events.

    Verifies the Stripe-Signature header, then processes:
    - checkout.session.completed  → activate subscription
    - customer.subscription.updated → update plan tier
    - customer.subscription.deleted → downgrade to free
    - invoice.payment_failed → mark subscription past-due
    """
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        logger.warning("Stripe keys not configured — ignoring webhook")
        return jsonify({"error": "Stripe not configured"}), 503

    import stripe
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
    data = event["data"]["object"]
    logger.info("Stripe event: %s (id=%s)", event_type, event.get("id"))

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(data)
        elif event_type == "customer.subscription.updated":
            _handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(data)
        elif event_type == "invoice.payment_failed":
            _handle_payment_failed(data)
        else:
            logger.debug("Unhandled Stripe event type: %s", event_type)
    except Exception:
        logger.exception("Error processing Stripe event %s", event_type)
        # Return 200 anyway so Stripe doesn't retry endlessly
        return jsonify({"status": "error_logged"}), 200

    return jsonify({"status": "ok"}), 200


def _handle_checkout_completed(session: dict):
    """Activate subscription after successful checkout."""
    customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")
    plan_tier = _resolve_plan_tier(session, status="active")

    if not customer_email:
        logger.warning("Checkout completed but no email found: %s", session.get("id"))
        return

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET stripe_customer_id = %(cid)s, "
        "stripe_subscription_id = %(sid)s, plan_tier = %(plan_tier)s, "
        "billing_status = %(billing_status)s, stripe_price_id = %(stripe_price_id)s "
        "WHERE email = %(email)s",
        {
            "cid": customer_id,
            "sid": subscription_id,
            "plan_tier": plan_tier,
            "billing_status": "active",
            "stripe_price_id": session.get("price"),
            "email": customer_email,
        },
    )
    conn.commit()
    logger.info("Subscription activated for %s (customer=%s)", customer_email, customer_id)


def _handle_subscription_updated(subscription: dict):
    """Update plan tier when subscription changes."""
    customer_id = subscription.get("customer")
    status = subscription.get("status")  # active, past_due, canceled, etc.
    plan_tier = _resolve_plan_tier(subscription, status=status)
    price_id = None
    items = (subscription.get("items") or {}).get("data") or []
    if items:
        price_id = (items[0].get("price") or {}).get("id")
    period_end = _from_unix(subscription.get("current_period_end"))
    cancel_at = _from_unix(subscription.get("cancel_at"))

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET billing_status = %(billing_status)s, "
        "plan_tier = %(plan_tier)s, stripe_subscription_id = %(sid)s, "
        "stripe_price_id = %(stripe_price_id)s, period_end = %(period_end)s, "
        "cancel_at = %(cancel_at)s "
        "WHERE stripe_customer_id = %(cid)s",
        {
            "billing_status": status,
            "plan_tier": plan_tier,
            "sid": subscription.get("id"),
            "stripe_price_id": price_id,
            "period_end": period_end,
            "cancel_at": cancel_at,
            "cid": customer_id,
        },
    )
    conn.commit()
    logger.info("Subscription updated for customer %s: status=%s", customer_id, status)


def _handle_subscription_deleted(subscription: dict):
    """Downgrade to free when subscription is canceled."""
    customer_id = subscription.get("customer")

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET plan_tier = %(plan_tier)s, billing_status = %(billing_status)s, "
        "stripe_subscription_id = NULL, stripe_price_id = NULL, period_end = %(period_end)s, "
        "cancel_at = %(cancel_at)s "
        "WHERE stripe_customer_id = %(cid)s",
        {
            "plan_tier": "free",
            "billing_status": "canceled",
            "period_end": _from_unix(subscription.get("current_period_end")),
            "cancel_at": _from_unix(subscription.get("canceled_at")),
            "cid": customer_id,
        },
    )
    conn.commit()
    logger.info("Subscription canceled for customer %s — downgraded to free", customer_id)


def _handle_payment_failed(invoice: dict):
    """Mark subscription as past-due on payment failure."""
    customer_id = invoice.get("customer")

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET billing_status = %(billing_status)s "
        "WHERE stripe_customer_id = %(cid)s",
        {"billing_status": "past_due", "cid": customer_id},
    )
    conn.commit()
    logger.info("Payment failed for customer %s — marked past_due", customer_id)
