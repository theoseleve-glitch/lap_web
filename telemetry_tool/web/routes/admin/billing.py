"""Admin billing routes — subscriptions, webhooks, revenue, reconciliation.

Endpoints:
- GET  /admin/billing/subscriptions — list subscriptions with DB state
- GET  /admin/billing/webhooks — webhook log
- GET  /admin/billing/revenue — MRR/ARR snapshot
- GET  /admin/billing/reconciliation — tier mismatches
- POST /admin/billing/reconciliation/:id/heal — fix mismatch
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_billing", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@bp.route("/billing/subscriptions", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "billing_admin")
def list_subscriptions():
    """List users with subscription data."""
    conn = _get_conn()
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)

    conditions = ["stripe_subscription_id IS NOT NULL"]
    params = {"limit": limit}

    if status:
        conditions.append("subscription_status = %(status)s")
        params["status"] = status

    where = " AND ".join(conditions)

    rows = conn.execute(
        f"SELECT id, email, plan_tier, stripe_subscription_id, "
        f"stripe_customer_id, subscription_status, created_at "
        f"FROM users WHERE {where} "
        f"ORDER BY created_at DESC LIMIT %(limit)s",
        params,
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/billing/webhooks", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "billing_admin")
def list_webhooks():
    """Query stripe_webhook_log. Filters: event_type, processing_status."""
    conn = _get_conn()
    event_type = request.args.get("event_type")
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)

    conditions = []
    params = {"limit": limit}

    if event_type:
        conditions.append("event_type = %(event_type)s")
        params["event_type"] = event_type

    if status:
        conditions.append("processing_status = %(status)s")
        params["status"] = status

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = conn.execute(
        f"SELECT id, stripe_event_id, event_type, processing_status, "
        f"error_message, created_at "
        f"FROM stripe_webhook_log {where} "
        f"ORDER BY created_at DESC LIMIT %(limit)s",
        params,
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/billing/revenue", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "billing_admin")
def revenue_snapshot():
    """MRR/ARR snapshot with tier breakdown."""
    conn = _get_conn()

    # Tier breakdown
    tier_rows = conn.execute(
        "SELECT plan_tier, COUNT(*) AS cnt "
        "FROM users "
        "WHERE subscription_status = 'active' AND deleted_at IS NULL "
        "GROUP BY plan_tier ORDER BY cnt DESC"
    ).fetchall()

    tier_breakdown = [_serialize_row(r) for r in tier_rows]
    total_active = sum(r.get("cnt", 0) for r in tier_breakdown)

    # Churn (cancelled in last 30 days)
    churn_row = conn.execute(
        "SELECT COUNT(*) AS churned FROM users "
        "WHERE subscription_status = 'canceled' "
        "AND updated_at > NOW() - INTERVAL '30 days'"
    ).fetchone()
    cr = dict(churn_row) if not isinstance(churn_row, dict) else churn_row
    churned = cr.get("churned", 0) or 0

    return api_response({
        "tier_breakdown": tier_breakdown,
        "total_active": total_active,
        "churned_30d": churned,
    })


@bp.route("/billing/reconciliation", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "billing_admin")
def list_mismatches():
    """Detect subscription/tier mismatches."""
    conn = _get_conn()

    rows = conn.execute(
        "SELECT id, email, plan_tier, subscription_status, "
        "stripe_subscription_id "
        "FROM users "
        "WHERE subscription_status = 'active' "
        "AND (plan_tier = 'demo' OR plan_tier IS NULL) "
        "AND deleted_at IS NULL"
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/billing/deadletter", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "billing_admin")
def list_deadletter():
    """List dead-lettered webhook events."""
    conn = _get_conn()
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)

    rows = conn.execute(
        "SELECT id, stripe_event_id, event_type, error_message, "
        "attempt_count, created_at "
        "FROM stripe_webhook_log "
        "WHERE processing_status = 'deadletter' "
        "ORDER BY created_at DESC LIMIT %(limit)s",
        {"limit": limit},
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/billing/deadletter/<int:event_id>/reprocess", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin")
def reprocess_deadletter(event_id: int):
    """Reprocess a dead-lettered webhook event.

    Resets attempt_count to 0 and sets processing_status back to 'failed'
    with a near-future next_retry_at so the retry task picks it up.
    """
    from datetime import datetime, timedelta, timezone

    conn = _get_conn()
    row = conn.execute(
        "SELECT id, stripe_event_id, processing_status FROM stripe_webhook_log "
        "WHERE id = %(id)s",
        {"id": event_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Webhook event not found", status=404)

    event = dict(row) if not isinstance(row, dict) else row
    if event.get("processing_status") != "deadletter":
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Event status is '{event.get('processing_status')}', not 'deadletter'",
            status=400,
        )

    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE stripe_webhook_log SET processing_status = 'failed', "
        "attempt_count = 0, next_retry_at = %(next)s, "
        "error_message = 'Admin reprocessed' "
        "WHERE id = %(id)s",
        {"id": event_id, "next": now + timedelta(seconds=5)},
    )
    conn.commit()

    admin_id = getattr(g, "current_user_id", None)
    logger.info(
        "Dead-letter event %s requeued by admin %s",
        event.get("stripe_event_id"), admin_id,
    )

    return api_response({
        "reprocessed": True,
        "stripe_event_id": event.get("stripe_event_id"),
    })


@bp.route("/billing/reconciliation/<int:user_id>/heal", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin")
def heal_mismatch(user_id: int):
    """Fix a tier mismatch by re-deriving from subscription. Audited."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "Admin reconciliation")

    from admin.entitlements import refresh_user_tier
    result = refresh_user_tier(conn, user_id, getattr(g, "current_user_id", 0))

    if "error" in result:
        return api_error(ErrorCode.NOT_FOUND, result["error"], status=404)

    return api_response(result)
