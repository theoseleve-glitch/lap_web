"""Stripe webhook handler for subscription lifecycle events."""
from __future__ import annotations

import logging
import os
from hashlib import sha256

from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("billing", __name__, url_prefix="/api/v1/billing")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


class TransientWebhookError(Exception):
    """Errors that should return 5xx so Stripe retries delivery."""


class PermanentWebhookError(Exception):
    """Errors that should be recorded as failures without Stripe retries."""


def _get_conn():
    from flask import current_app
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    from web.db import get_db_connection
    return get_db_connection()


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

    event_id = event.get("id")
    event_type = event["type"]
    data = event["data"]["object"]
    payload_hash = sha256(payload.encode("utf-8")).hexdigest()
    logger.info("Stripe event: %s (id=%s)", event_type, event_id)

    conn = _get_conn()
    try:
        _insert_event(conn, event_id, event_type, payload_hash)
    except PermanentWebhookError:
        conn.rollback()
        return jsonify({"status": "already_processed"}), 200
    except Exception:
        conn.rollback()
        logger.exception("Failed to lock Stripe event id=%s", event_id)
        return jsonify({"error": "Failed to persist webhook event"}), 500

    try:
        _process_event(conn, event_type, data)
        _mark_event_status(conn, event_id, "success")
        conn.commit()
        return jsonify({"status": "ok"}), 200
    except TransientWebhookError:
        conn.rollback()
        logger.exception("Transient error processing Stripe event %s", event_type)
        return jsonify({"error": "Transient webhook processing failure"}), 500
    except PermanentWebhookError:
        logger.exception("Permanent error processing Stripe event %s", event_type)
        _mark_event_status(conn, event_id, "failure")
        conn.commit()
        return jsonify({"status": "failed"}), 200
    except Exception:
        logger.exception("Unhandled error processing Stripe event %s", event_type)
        _mark_event_status(conn, event_id, "failure")
        conn.commit()
        return jsonify({"status": "failed"}), 200


def _insert_event(conn, event_id: str | None, event_type: str, payload_hash: str) -> None:
    """Insert event id for idempotency; raise PermanentWebhookError on duplicates."""
    try:
        conn.execute(
            "INSERT INTO stripe_events (event_id, type, status, payload_hash) "
            "VALUES (%(event_id)s, %(event_type)s, %(status)s, %(payload_hash)s)",
            {
                "event_id": event_id,
                "event_type": event_type,
                "status": "processing",
                "payload_hash": payload_hash,
            },
        )
    except Exception as exc:
        if _is_unique_violation(exc):
            raise PermanentWebhookError("Duplicate Stripe event") from exc
        raise


def _mark_event_status(conn, event_id: str | None, status: str) -> None:
    conn.execute(
        "UPDATE stripe_events "
        "SET status = %(status)s, processed_at = CURRENT_TIMESTAMP "
        "WHERE event_id = %(event_id)s",
        {"status": status, "event_id": event_id},
    )


def _process_event(conn, event_type: str, data: dict) -> None:
    if event_type == "checkout.session.completed":
        _handle_checkout_completed(conn, data)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(conn, data)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(conn, data)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(conn, data)
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)


def _is_unique_violation(exc: Exception) -> bool:
    raw_message = str(exc).lower()
    if "unique" in raw_message and "stripe_events" in raw_message:
        return True
    cause = getattr(exc, "__cause__", None)
    while cause is not None:
        cause_message = str(cause).lower()
        if "unique" in cause_message and "stripe_events" in cause_message:
            return True
        cause = getattr(cause, "__cause__", None)
    return False


def _handle_checkout_completed(conn, session: dict):
    """Activate subscription after successful checkout."""
    customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")

    if not customer_email:
        logger.warning("Checkout completed but no email found: %s", session.get("id"))
        return

    conn.execute(
        "UPDATE users SET stripe_customer_id = %(cid)s, "
        "stripe_subscription_id = %(sid)s, billing_plan = %(plan)s "
        "WHERE email = %(email)s",
        {"cid": customer_id, "sid": subscription_id,
         "plan": "active", "email": customer_email},
    )
    logger.info("Subscription activated for %s (customer=%s)", customer_email, customer_id)


def _handle_subscription_updated(conn, subscription: dict):
    """Update plan tier when subscription changes."""
    customer_id = subscription.get("customer")
    status = subscription.get("status")  # active, past_due, canceled, etc.

    conn.execute(
        "UPDATE users SET billing_plan = %(plan)s "
        "WHERE stripe_customer_id = %(cid)s "
        "AND stripe_subscription_id IS NOT NULL",
        {"plan": status, "cid": customer_id},
    )
    logger.info("Subscription updated for customer %s: status=%s", customer_id, status)


def _handle_subscription_deleted(conn, subscription: dict):
    """Downgrade to free when subscription is canceled."""
    customer_id = subscription.get("customer")

    conn.execute(
        "UPDATE users SET billing_plan = %(plan)s, "
        "stripe_subscription_id = NULL "
        "WHERE stripe_customer_id = %(cid)s",
        {"plan": "free", "cid": customer_id},
    )
    logger.info("Subscription canceled for customer %s — downgraded to free", customer_id)


def _handle_payment_failed(conn, invoice: dict):
    """Mark subscription as past-due on payment failure."""
    customer_id = invoice.get("customer")

    conn.execute(
        "UPDATE users SET billing_plan = %(plan)s "
        "WHERE stripe_customer_id = %(cid)s "
        "AND stripe_subscription_id IS NOT NULL",
        {"plan": "past_due", "cid": customer_id},
    )
    logger.info("Payment failed for customer %s — marked past_due", customer_id)
