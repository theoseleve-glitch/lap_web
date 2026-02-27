"""Stripe reconciliation Celery task.

Runs hourly via Celery beat. Compares local subscription state with
Stripe API and heals mismatches. Stripe is the source of truth.
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
# Register as Celery tasks (or plain functions when Celery unavailable)
# ---------------------------------------------------------------------------

if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(name="tasks.billing_tasks.reconcile_stripe")
    def reconcile_stripe() -> dict[str, Any]:
        return _reconcile_stripe_impl()
else:
    def reconcile_stripe() -> dict[str, Any]:  # type: ignore[misc]
        return _reconcile_stripe_impl()
