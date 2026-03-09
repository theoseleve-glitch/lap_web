"""Admin monitoring routes — system-wide usage totals, per-user resources.

Endpoints:
- GET  /admin/monitoring/totals                — system-wide aggregate totals
- GET  /admin/monitoring/users                 — per-user resource aggregation
- GET  /admin/monitoring/users/<id>/timeseries — daily usage time series for a user
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from web.api_utils import ErrorCode, api_error, api_response

from .middleware import require_admin_role, require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_monitoring", __name__)

# Allowlist of sort columns to prevent SQL injection
_VALID_SORT_COLUMNS = {
    "total_storage_bytes",
    "total_compute_seconds",
    "session_count",
    "last_upload",
    "email",
}


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


# ---------------------------------------------------------------------------
# Helper functions (exposed for testing)
# ---------------------------------------------------------------------------


def _get_totals() -> dict:
    """System-wide totals: users, sessions, storage, compute."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT "
        "  (SELECT COUNT(*) FROM users) AS total_users, "
        "  (SELECT COUNT(*) FROM sessions) AS total_sessions, "
        "  COALESCE((SELECT SUM(file_size) FROM ingestion_jobs), 0) AS total_storage_bytes, "
        "  COALESCE((SELECT SUM(EXTRACT(EPOCH FROM (completed_at - started_at))) "
        "    FROM ingestion_jobs WHERE completed_at IS NOT NULL), 0) AS total_compute_seconds"
    ).fetchone()
    return _serialize_row(row)


def _get_user_resources(sort_by: str, limit: int) -> list[dict]:
    """Per-user resource aggregation.

    Joins users -> workspaces (personal) -> ingestion_jobs via workspace_id.
    """
    if sort_by not in _VALID_SORT_COLUMNS:
        sort_by = "total_storage_bytes"

    conn = _get_conn()

    # Use a safe ORDER BY via allowlisted column name
    sql = (
        "SELECT "
        "  u.id AS user_id, "
        "  u.email, "
        "  u.display_name, "
        "  u.created_at AS user_created_at, "
        "  COUNT(DISTINCT j.job_id) AS session_count, "
        "  COALESCE(SUM(j.file_size), 0) AS total_storage_bytes, "
        "  COALESCE(SUM(EXTRACT(EPOCH FROM (j.completed_at - j.started_at))), 0) "
        "    AS total_compute_seconds, "
        "  MAX(j.started_at) AS last_upload "
        "FROM users u "
        "LEFT JOIN workspaces w ON w.owner_user_id = u.id AND w.type = 'personal' "
        "LEFT JOIN ingestion_jobs j ON j.workspace_id = w.id "
        "GROUP BY u.id, u.email, u.display_name, u.created_at "
        f"ORDER BY {sort_by} DESC NULLS LAST "
        "LIMIT %(limit)s"
    )

    rows = conn.execute(sql, {"limit": limit}).fetchall()
    return [_serialize_row(r) for r in rows]


def _get_user_timeseries(user_id: int, days: int) -> list[dict]:
    """Daily usage time series for a specific user over the last N days.

    Groups ingestion_jobs by day via workspace ownership.
    """
    conn = _get_conn()
    sql = (
        "SELECT "
        "  date_trunc('day', j.started_at) AS day, "
        "  COUNT(*) AS job_count, "
        "  COALESCE(SUM(j.file_size), 0) AS storage_bytes, "
        "  COALESCE(SUM(EXTRACT(EPOCH FROM (j.completed_at - j.started_at))), 0) "
        "    AS compute_seconds "
        "FROM ingestion_jobs j "
        "JOIN workspaces w ON w.id = j.workspace_id AND w.type = 'personal' "
        "WHERE w.owner_user_id = %(user_id)s "
        "  AND j.started_at >= NOW() - INTERVAL '1 day' * %(days)s "
        "GROUP BY date_trunc('day', j.started_at) "
        "ORDER BY day ASC"
    )

    rows = conn.execute(sql, {"user_id": user_id, "days": days}).fetchall()
    return [_serialize_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/monitoring/totals", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def monitoring_totals():
    """System-wide usage totals."""
    data = _get_totals()
    return api_response(data)


@bp.route("/monitoring/users", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def monitoring_users():
    """Per-user resource aggregation with sorting."""
    sort_by = request.args.get("sort", "total_storage_bytes")
    if sort_by not in _VALID_SORT_COLUMNS:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid sort column. Allowed: {', '.join(sorted(_VALID_SORT_COLUMNS))}",
        )

    try:
        limit = int(request.args.get("limit", "100"))
    except (ValueError, TypeError):
        limit = 100
    limit = max(1, min(limit, 1000))

    data = _get_user_resources(sort_by, limit)
    return api_response({"users": data, "count": len(data)})


@bp.route("/monitoring/users/<int:user_id>/timeseries", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def monitoring_user_timeseries(user_id: int):
    """Daily usage time series for a specific user."""
    try:
        days = int(request.args.get("days", "30"))
    except (ValueError, TypeError):
        days = 30
    days = max(1, min(days, 365))

    data = _get_user_timeseries(user_id, days)
    return api_response({"user_id": user_id, "days": days, "timeseries": data})
