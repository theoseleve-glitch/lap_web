"""Billing Celery tasks: Stripe reconciliation + grace period enforcement.

- reconcile_stripe: Hourly — compares local state with Stripe API.
- enforce_subscription_grace_periods: Daily — downgrades expired grace periods.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery app import (graceful fallback for testing)
# ---------------------------------------------------------------------------

_USE_CELERY = False
try:
    from celery_app import celery as _celery_app
    _USE_CELERY = True
except Exception:
    _celery_app = None

# ---------------------------------------------------------------------------
# Stripe SDK import
# ---------------------------------------------------------------------------

try:
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
except ImportError:
    stripe = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# PG connection helper
# ---------------------------------------------------------------------------


def get_pg_connection():
    """Get a PostgreSQL connection. Tests patch this."""
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---------------------------------------------------------------------------
# Task: reconcile_stripe
# ---------------------------------------------------------------------------


def _reconcile_stripe_impl() -> dict[str, Any]:
    """Compare local subscription state with Stripe and heal mismatches.

    Steps:
        1. Query all users with a stripe_subscription_id
        2. For each, retrieve the subscription from Stripe
        3. If local status differs from Stripe status, update local
        4. If subscription not found in Stripe, mark as canceled

    Returns:
        Dict with ``{"checked": N, "healed": N}``
    """
    conn = get_pg_connection()

    rows = conn.execute(
        "SELECT id, stripe_subscription_id, subscription_status, plan_tier "
        "FROM users WHERE stripe_subscription_id IS NOT NULL",
    ).fetchall()
    users = [dict(r) if not isinstance(r, dict) else r for r in rows]

    if not users:
        logger.info("Stripe reconciliation: 0 subscribers to check")
        return {"checked": 0, "healed": 0}

    healed = 0
    for user in users:
        uid = user["id"]
        sub_id = user["stripe_subscription_id"]
        local_status = user["subscription_status"]

        try:
            stripe_sub = stripe.Subscription.retrieve(sub_id)
            stripe_status = stripe_sub.status
        except Exception:
            logger.warning(
                "Subscription %s not found in Stripe for user %s — marking canceled",
                sub_id, uid,
            )
            stripe_status = "canceled"

        if local_status != stripe_status:
            conn.execute(
                "UPDATE users SET subscription_status = %(status)s "
                "WHERE id = %(uid)s",
                {"status": stripe_status, "uid": uid},
            )
            conn.commit()
            healed += 1
            logger.warning(
                "Stripe reconciliation healed user %s: %s -> %s",
                uid, local_status, stripe_status,
            )

    logger.info(
        "Stripe reconciliation complete: checked=%d, healed=%d",
        len(users), healed,
    )
    return {"checked": len(users), "healed": healed}


# ---------------------------------------------------------------------------
# Task: enforce_subscription_grace_periods
# ---------------------------------------------------------------------------


def _enforce_grace_periods_impl() -> dict[str, Any]:
    """Check for expired grace periods and downgrade to demo tier.

    Rules:
        - canceled + grace_period_end passed → plan_tier = 'demo', status = 'free'
        - past_due > 7 days (grace_period_end passed) → send final warning
        - past_due > 14 days → plan_tier = 'demo', status = 'free'

    Returns:
        Dict with ``{"checked": N, "downgraded": N, "warned": N}``
    """
    from datetime import datetime, timedelta, timezone

    conn = get_pg_connection()
    now = datetime.now(timezone.utc)
    downgraded = 0
    warned = 0

    # 1. Canceled users past grace period → downgrade to demo
    rows = conn.execute(
        "SELECT id, email, plan_tier FROM users "
        "WHERE subscription_status = 'canceled' "
        "AND grace_period_end IS NOT NULL "
        "AND grace_period_end < %(now)s",
        {"now": now},
    ).fetchall()
    canceled_users = [dict(r) if not isinstance(r, dict) else r for r in rows]

    for user in canceled_users:
        conn.execute(
            "UPDATE users SET plan_tier = 'demo', subscription_status = 'free', "
            "grace_period_end = NULL, stripe_subscription_id = NULL "
            "WHERE id = %(uid)s",
            {"uid": user["id"]},
        )
        conn.commit()
        downgraded += 1
        logger.info(
            "Grace period expired: user %s downgraded from %s to demo",
            user["id"], user.get("plan_tier"),
        )
        if user.get("email"):
            try:
                from auth.email import _send, FRONTEND_URL
                _send(
                    user["email"],
                    "Your LAP plan has been downgraded",
                    f'<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">'
                    f'<h2 style="color: #F3F0E8;">Your plan has been downgraded</h2>'
                    f'<p style="color: #8A8F98;">Your subscription grace period has ended and your account has been moved to the free tier. '
                    f'Your data is preserved but some features are now limited.</p>'
                    f'<a href="{FRONTEND_URL}/pricing" '
                    f'style="display: inline-block; background: #B6FF2E; color: #0B0C0F; '
                    f'padding: 12px 24px; border-radius: 6px; text-decoration: none; '
                    f'font-weight: 600; margin: 16px 0;">Resubscribe</a></div>',
                )
            except Exception:
                logger.exception("Failed to send downgrade email to %s", user["email"])

    # 2. Past-due users: warn at 7 days, downgrade at 14 days
    past_due_rows = conn.execute(
        "SELECT id, email, plan_tier, grace_period_end FROM users "
        "WHERE subscription_status = 'past_due' "
        "AND grace_period_end IS NOT NULL",
    ).fetchall()
    past_due_users = [dict(r) if not isinstance(r, dict) else r for r in past_due_rows]

    for user in past_due_users:
        grace_end = user["grace_period_end"]
        if hasattr(grace_end, "replace"):
            grace_end = grace_end.replace(tzinfo=timezone.utc) if grace_end.tzinfo is None else grace_end

        days_past = (now - grace_end).days if now > grace_end else 0

        if days_past >= 7:
            # 14 days total past-due (7 grace + 7 more) → hard downgrade
            conn.execute(
                "UPDATE users SET plan_tier = 'demo', subscription_status = 'free', "
                "grace_period_end = NULL "
                "WHERE id = %(uid)s",
                {"uid": user["id"]},
            )
            conn.commit()
            downgraded += 1
            logger.info("Past-due hard downgrade: user %s", user["id"])
        elif days_past >= 0:
            # Grace period just expired → send final warning
            if user.get("email"):
                try:
                    from auth.email import _send, FRONTEND_URL
                    _send(
                        user["email"],
                        "Final warning: update your payment method",
                        f'<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">'
                        f'<h2 style="color: #F3F0E8;">Payment overdue — action required</h2>'
                        f'<p style="color: #8A8F98;">Your payment is overdue. Please update your payment method '
                        f'within 7 days to avoid losing access to your plan features.</p>'
                        f'<a href="{FRONTEND_URL}/app/settings/billing" '
                        f'style="display: inline-block; background: #FF6A00; color: #0B0C0F; '
                        f'padding: 12px 24px; border-radius: 6px; text-decoration: none; '
                        f'font-weight: 600; margin: 16px 0;">Update Payment</a></div>',
                    )
                    warned += 1
                except Exception:
                    logger.exception("Failed to send past-due warning to %s", user["email"])

    total = len(canceled_users) + len(past_due_users)
    logger.info(
        "Grace period enforcement: checked=%d, downgraded=%d, warned=%d",
        total, downgraded, warned,
    )
    return {"checked": total, "downgraded": downgraded, "warned": warned}


# ---------------------------------------------------------------------------
# Register as Celery tasks (or plain functions when Celery unavailable)
# ---------------------------------------------------------------------------

if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(name="tasks.billing_tasks.reconcile_stripe")
    def reconcile_stripe() -> dict[str, Any]:
        return _reconcile_stripe_impl()

    @_celery_app.task(name="tasks.billing_tasks.enforce_subscription_grace_periods")
    def enforce_subscription_grace_periods() -> dict[str, Any]:
        return _enforce_grace_periods_impl()
else:
    def reconcile_stripe() -> dict[str, Any]:  # type: ignore[misc]
        return _reconcile_stripe_impl()

    def enforce_subscription_grace_periods() -> dict[str, Any]:  # type: ignore[misc]
        return _enforce_grace_periods_impl()
