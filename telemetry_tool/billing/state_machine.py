"""Subscription state machine — validates and executes state transitions.

States: free → trialing → active → past_due/canceled/paused
Each transition is validated, recorded in audit_log, and triggers
appropriate email notifications.

Stripe webhook handlers delegate to ``transition_subscription()``
instead of raw SQL updates, ensuring all transitions are validated
and side-effects are consistent.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SUBSCRIPTION_STATES: dict[str, dict] = {
    "free": {"allowed_transitions": ["trialing", "active"], "grace_days": 0},
    "trialing": {"allowed_transitions": ["active", "canceled"], "grace_days": 0},
    "active": {"allowed_transitions": ["past_due", "canceled", "paused", "unpaid"], "grace_days": 0},
    "past_due": {"allowed_transitions": ["active", "canceled", "unpaid"], "grace_days": 7},
    "unpaid": {"allowed_transitions": ["active", "canceled"], "grace_days": 0},
    "canceled": {"allowed_transitions": ["active", "free"], "grace_days": 30},
    "paused": {"allowed_transitions": ["active", "canceled"], "grace_days": 0},
}

# Map Stripe subscription.status values to our billing states.
# Stripe statuses: incomplete, incomplete_expired, trialing, active,
# past_due, canceled, unpaid, paused.
STRIPE_STATUS_MAP: dict[str, str] = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    "unpaid": "unpaid",
    "paused": "paused",
    "incomplete": "free",           # payment not yet confirmed
    "incomplete_expired": "canceled",
}


def map_stripe_status(stripe_status: str) -> str:
    """Convert a Stripe subscription status to our billing state."""
    return STRIPE_STATUS_MAP.get(stripe_status, "free")

# Email event types mapped to state transitions
_TRANSITION_EMAILS: dict[str, str] = {
    "active": "payment_recovered",      # recovery from past_due/canceled
    "past_due": "payment_failed",
    "canceled": "subscription_canceled",
    "paused": "subscription_paused",
    "trialing": "trial_started",
}


def validate_transition(current_status: str, new_status: str) -> bool:
    """Check if a state transition is allowed."""
    state = SUBSCRIPTION_STATES.get(current_status)
    if state is None:
        return False
    return new_status in state["allowed_transitions"]


def get_grace_days(status: str) -> int:
    """Return the number of grace days for a subscription status."""
    return SUBSCRIPTION_STATES.get(status, {}).get("grace_days", 0)


def transition_subscription(
    conn,
    user_id: int,
    new_status: str,
    *,
    metadata: dict | None = None,
    plan_tier: str | None = None,
    ip_address: str | None = None,
) -> bool:
    """Transition a user's subscription state. Validates allowed transitions.

    Records in audit_log. Sends appropriate emails.
    Sets grace_period_end when transitioning to a state with grace days.

    Args:
        conn: Database connection
        user_id: The user to transition
        new_status: Target subscription state
        metadata: Optional metadata for audit log
        plan_tier: Optional plan tier update (for checkout/upgrade)
        ip_address: For audit logging

    Returns:
        True if transition succeeded, False if invalid.
    """
    # Get current state
    row = conn.execute(
        "SELECT email, subscription_status, plan_tier FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if row is None:
        logger.warning("transition_subscription: user %s not found", user_id)
        return False

    user = dict(row) if not isinstance(row, dict) else row
    current_status = user.get("subscription_status") or "free"
    email = user.get("email")

    # Validate transition
    if not validate_transition(current_status, new_status):
        logger.warning(
            "Invalid subscription transition for user %s: %s → %s",
            user_id, current_status, new_status,
        )
        return False

    # Build update query
    updates = ["subscription_status = %(new_status)s"]
    params: dict = {"new_status": new_status, "uid": user_id}

    # Set plan_tier if provided (e.g., checkout completed)
    if plan_tier is not None:
        updates.append("plan_tier = %(tier)s")
        params["tier"] = plan_tier

    # Set grace_period_end for states with grace days
    grace_days = get_grace_days(new_status)
    if grace_days > 0:
        grace_end = datetime.now(timezone.utc) + timedelta(days=grace_days)
        updates.append("grace_period_end = %(grace_end)s")
        params["grace_end"] = grace_end
    else:
        # Clear grace period when transitioning to a non-grace state
        updates.append("grace_period_end = NULL")

    conn.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id = %(uid)s",
        params,
    )

    # Audit log
    details = {
        "from": current_status,
        "to": new_status,
        "grace_days": grace_days,
    }
    if plan_tier:
        details["plan_tier"] = plan_tier
    if metadata:
        details["metadata"] = metadata

    try:
        conn.execute(
            "INSERT INTO audit_log (user_id, action, details, ip_address) "
            "VALUES (%(uid)s, %(action)s, %(details)s, %(ip)s)",
            {
                "uid": user_id,
                "action": f"subscription_transition:{current_status}:{new_status}",
                "details": json.dumps(details),
                "ip": (ip_address or "")[:45] or None,
            },
        )
    except Exception:
        logger.exception("Failed to write audit log for subscription transition")

    conn.commit()

    logger.info(
        "Subscription transition: user=%s %s → %s (grace=%d days)",
        user_id, current_status, new_status, grace_days,
    )

    # Send email notification (best-effort)
    email_type = _TRANSITION_EMAILS.get(new_status)
    if email and email_type:
        try:
            from web.routes.billing import _send_billing_email
            _send_billing_email(email, email_type)
        except Exception:
            logger.exception("Failed to send %s email to %s", email_type, email)

    return True
