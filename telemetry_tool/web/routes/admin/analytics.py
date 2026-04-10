"""Admin analytics routes — DAU, feature usage, retention, event timeline, storage.

Endpoints:
- GET /admin/analytics/dau       — daily active users + summary
- GET /admin/analytics/features  — top feature/event_type usage
- GET /admin/analytics/retention — weekly cohort retention
- GET /admin/analytics/timeline  — recent event timeline with user info
- GET /admin/analytics/storage   — ingestion storage aggregates
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from web.api_utils import api_response

from .middleware import require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_analytics", __name__)


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


@bp.route("/analytics/dau", methods=["GET"])
@require_superadmin
def analytics_dau():
    """Daily active users over N days, plus summary metrics."""
    try:
        days = int(request.args.get("days", 30))
    except (ValueError, TypeError):
        days = 30
    days = max(1, min(days, 365))

    conn = _get_conn()

    # Daily breakdown
    rows = conn.execute(
        "SELECT date_trunc('day', created_at)::date AS day, "
        "  COUNT(DISTINCT user_id) AS active_users, "
        "  COUNT(*) AS event_count "
        "FROM app_events "
        "WHERE created_at >= NOW() - make_interval(days => %(days)s) "
        "GROUP BY date_trunc('day', created_at)::date "
        "ORDER BY 1",
        {"days": days},
    ).fetchall()
    daily = [_serialize_row(r) for r in rows]

    # Summary subqueries
    summary_row = conn.execute(
        "SELECT "
        "  (SELECT COUNT(DISTINCT user_id) FROM app_events "
        "     WHERE created_at >= CURRENT_DATE) AS dau_today, "
        "  (SELECT COUNT(DISTINCT user_id) FROM app_events "
        "     WHERE created_at >= NOW() - make_interval(days => 7)) AS wau_7d, "
        "  (SELECT COUNT(*) FROM app_events "
        "     WHERE created_at >= NOW() - make_interval(days => 30)) AS total_events_30d, "
        "  (SELECT COUNT(DISTINCT event_type) FROM app_events "
        "     WHERE created_at >= NOW() - make_interval(days => 30)) AS unique_features"
    ).fetchone()
    summary = _serialize_row(summary_row)

    return api_response({"days": daily, "summary": summary})


@bp.route("/analytics/features", methods=["GET"])
@require_superadmin
def analytics_features():
    """Top 15 features by event_type usage over N days."""
    try:
        days = int(request.args.get("days", 30))
    except (ValueError, TypeError):
        days = 30
    days = max(1, min(days, 365))

    conn = _get_conn()

    rows = conn.execute(
        "SELECT event_type, "
        "  COUNT(*) AS count, "
        "  COUNT(DISTINCT user_id) AS unique_users "
        "FROM app_events "
        "WHERE created_at >= NOW() - make_interval(days => %(days)s) "
        "GROUP BY event_type "
        "ORDER BY count DESC "
        "LIMIT 15",
        {"days": days},
    ).fetchall()

    return api_response({"features": [_serialize_row(r) for r in rows]})


@bp.route("/analytics/retention", methods=["GET"])
@require_superadmin
def analytics_retention():
    """Weekly cohort retention for N weeks.

    Buckets users by their signup week, then checks whether they had any
    app_events activity in each subsequent week offset (0..weeks-1).
    """
    try:
        weeks = int(request.args.get("weeks", 8))
    except (ValueError, TypeError):
        weeks = 8
    weeks = max(1, min(weeks, 26))

    conn = _get_conn()

    rows = conn.execute(
        """
        WITH cohorts AS (
            SELECT
                id AS user_id,
                date_trunc('week', created_at)::date AS cohort_week
            FROM users
            WHERE deleted_at IS NULL
              AND created_at >= NOW() - make_interval(weeks => %(weeks)s)
        ),
        offsets AS (
            SELECT generate_series(0, %(weeks)s - 1) AS week_offset
        ),
        activity AS (
            SELECT
                c.cohort_week,
                o.week_offset,
                COUNT(DISTINCT c.user_id) AS cohort_size,
                COUNT(DISTINCT e.user_id) AS retained_users
            FROM cohorts c
            CROSS JOIN offsets o
            LEFT JOIN app_events e
                ON e.user_id = c.user_id
                AND e.created_at >= c.cohort_week + make_interval(weeks => o.week_offset)
                AND e.created_at <  c.cohort_week + make_interval(weeks => o.week_offset + 1)
            GROUP BY c.cohort_week, o.week_offset
        )
        SELECT
            cohort_week,
            week_offset,
            cohort_size,
            retained_users,
            CASE WHEN cohort_size = 0 THEN 0.0
                 ELSE ROUND(retained_users::numeric / cohort_size * 100, 1)
            END AS retention_pct
        FROM activity
        ORDER BY cohort_week, week_offset
        """,
        {"weeks": weeks},
    ).fetchall()

    # Organise into cohort objects
    cohorts: dict[str, dict] = {}
    for r in rows:
        row = _serialize_row(r)
        key = str(row["cohort_week"])
        if key not in cohorts:
            cohorts[key] = {
                "cohort_week": row["cohort_week"],
                "cohort_size": row["cohort_size"],
                "weeks": [],
            }
        cohorts[key]["weeks"].append({
            "week_offset": row["week_offset"],
            "retained_users": row["retained_users"],
            "retention_pct": row["retention_pct"],
        })

    return api_response({"cohorts": list(cohorts.values())})


@bp.route("/analytics/timeline", methods=["GET"])
@require_superadmin
def analytics_timeline():
    """Recent app events with user info."""
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    limit = max(1, min(limit, 200))

    conn = _get_conn()

    rows = conn.execute(
        "SELECT e.id, e.event_type, e.created_at, "
        "  e.user_id, u.email AS user_email "
        "FROM app_events e "
        "JOIN users u ON e.user_id = u.id "
        "ORDER BY e.created_at DESC "
        "LIMIT %(limit)s",
        {"limit": limit},
    ).fetchall()

    return api_response({"events": [_serialize_row(r) for r in rows]})


@bp.route("/analytics/storage", methods=["GET"])
@require_superadmin
def analytics_storage():
    """Aggregate storage stats from completed ingestion jobs."""
    conn = _get_conn()

    row = conn.execute(
        "SELECT "
        "  COALESCE(SUM(file_size), 0) AS total_storage_bytes, "
        "  COALESCE(AVG(file_size), 0) AS avg_file_size_bytes, "
        "  COUNT(*) AS total_jobs, "
        "  COUNT(DISTINCT user_id) AS unique_uploaders "
        "FROM ingestion_jobs "
        "WHERE status = 'completed'",
    ).fetchone()

    return api_response(_serialize_row(row))
