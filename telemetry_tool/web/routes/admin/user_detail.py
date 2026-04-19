"""Admin per-user detail routes — activity summary and storage breakdown.

Endpoints:
- GET /admin/users/<id>/activity — 30-day activity, top features, recent events
- GET /admin/users/<id>/storage  — storage usage + plan entitlement comparison
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from web.api_utils import ErrorCode, api_error, api_response

from .middleware import require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_user_detail", __name__)


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


def _user_exists(conn, uid: int) -> bool:
    """Return True if user exists and is not deleted."""
    row = conn.execute(
        "SELECT 1 FROM users WHERE id = %(uid)s AND deleted_at IS NULL",
        {"uid": uid},
    ).fetchone()
    return row is not None


@bp.route("/users/<int:user_id>/activity", methods=["GET"])
@require_superadmin
def user_activity(user_id: int):
    """Per-user activity summary: counts, last active, top features, recent events."""
    conn = _get_conn()

    if not _user_exists(conn, user_id):
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    # Aggregate counters over last 30 days
    agg_row = conn.execute(
        "SELECT "
        "  COUNT(*) AS events_30d, "
        "  MAX(created_at) AS last_active, "
        "  COUNT(*) FILTER (WHERE event_type = 'session.view') AS sessions_viewed, "
        "  COUNT(*) FILTER (WHERE event_type = 'session.upload') AS uploads_30d "
        "FROM app_events "
        "WHERE user_id = %(uid)s "
        "  AND created_at >= NOW() - make_interval(days => 30)",
        {"uid": user_id},
    ).fetchone()
    summary = _serialize_row(agg_row)

    # Top 5 features
    feature_rows = conn.execute(
        "SELECT event_type, COUNT(*) AS count "
        "FROM app_events "
        "WHERE user_id = %(uid)s "
        "GROUP BY event_type "
        "ORDER BY count DESC "
        "LIMIT 5",
        {"uid": user_id},
    ).fetchall()
    top_features = [_serialize_row(r) for r in feature_rows]

    # Recent 20 events
    event_rows = conn.execute(
        "SELECT id, event_type, created_at "
        "FROM app_events "
        "WHERE user_id = %(uid)s "
        "ORDER BY created_at DESC "
        "LIMIT 20",
        {"uid": user_id},
    ).fetchall()
    recent_events = [_serialize_row(r) for r in event_rows]

    return api_response({
        "user_id": user_id,
        "summary": summary,
        "top_features": top_features,
        "recent_events": recent_events,
    })


@bp.route("/users/<int:user_id>/storage", methods=["GET"])
@require_superadmin
def user_storage(user_id: int):
    """Per-user storage usage vs plan entitlements."""
    conn = _get_conn()

    if not _user_exists(conn, user_id):
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    # Storage aggregates from completed ingestion jobs
    storage_row = conn.execute(
        "SELECT "
        "  COUNT(*) AS total_reports, "
        "  COUNT(*) FILTER "
        "    (WHERE started_at >= date_trunc('month', NOW())) AS reports_this_month, "
        "  COALESCE(SUM(file_size), 0) AS total_storage_bytes, "
        "  COALESCE(AVG(file_size), 0) AS avg_storage_per_session_bytes "
        "FROM ingestion_jobs "
        "WHERE user_id = %(uid)s AND status = 'completed'",
        {"uid": user_id},
    ).fetchone()
    storage = _serialize_row(storage_row)

    # Entitlements — fail gracefully if the module doesn't exist
    plan_tier = "unknown"
    analyses_per_month = 0
    analyses_used = 0
    max_upload_size_mb = 0
    plan_storage_limit_bytes = 0

    try:
        from auth.entitlements import get_user_entitlements
        ent = get_user_entitlements(user_id, conn)
        plan_tier = ent.get("plan_tier", "unknown")
        analyses_per_month = ent.get("analyses_per_month", 0)
        analyses_used = ent.get("analyses_used", 0)
        max_upload_size_mb = ent.get("max_upload_size_mb", 0)
        plan_storage_limit_bytes = max_upload_size_mb * 1024 * 1024
    except Exception:
        logger.debug("Entitlements unavailable for user %d", user_id, exc_info=True)
        # Defaults already set above

    total_bytes = storage.get("total_storage_bytes", 0) or 0
    storage_pct = (
        round(total_bytes / plan_storage_limit_bytes * 100, 1)
        if plan_storage_limit_bytes > 0
        else 0.0
    )

    return api_response({
        "user_id": user_id,
        "storage": storage,
        "entitlements": {
            "plan_tier": plan_tier,
            "analyses_per_month": analyses_per_month,
            "analyses_used": analyses_used,
            "max_upload_size_mb": max_upload_size_mb,
            "plan_storage_limit_bytes": plan_storage_limit_bytes,
        },
        "storage_pct": storage_pct,
    })
