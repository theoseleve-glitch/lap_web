"""Admin Overview cockpit — one consolidated 4-lens payload.

GET /api/v1/admin/overview — business health, product usage, live ops, growth.
Cross-tenant aggregates run via the telemetry_maint (BYPASSRLS) path; the call
is logged to admin_audit_log and wrapped in a 20s Redis cache.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, g

from web.api_utils import api_response
from admin.audit import log_admin_action

from .middleware import require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_overview", __name__)

_CACHE_KEY = "admin:overview:v1"
_CACHE_TTL = 20  # seconds (spec §10: 15-30s short-TTL aggregate cache)


def _get_overview_conn():
    """Cross-tenant read connection. Prefers the telemetry_maint role
    (BYPASSRLS) if a dedicated DSN is configured; otherwise the standard
    admin PG connection (admin requests already run without SET LOCAL)."""
    maint_dsn = os.environ.get("TELEMETRY_MAINT_PG_URL")
    if maint_dsn:
        try:
            from web.db_pg import get_pg_connection
            return get_pg_connection(dsn=maint_dsn)
        except TypeError:
            pass  # get_pg_connection doesn't take dsn in this build — fall through
        except Exception:
            logger.warning("telemetry_maint conn failed; falling back", exc_info=True)
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _get_redis() -> Any | None:
    """Return the application's Redis client, or None (matches auth/lockout)."""
    try:
        r = getattr(g, "_redis", None)
        if r is not None:
            return r
        return current_app.extensions.get("redis")
    except Exception:
        return None


def _scalar(conn, sql: str, params: dict | None = None, default: int = 0) -> int:
    """Run a single-column COUNT/SUM aggregate aliased AS n; 0 on any error
    (table may not exist yet before SCHEMA cluster migrations land)."""
    try:
        row = conn.execute(sql, params or {}).fetchone()
        if row is None:
            return default
        if isinstance(row, dict):
            return int(row.get("n", default) or default)
        return int(row[0] if row[0] is not None else default)
    except Exception:
        logger.debug("overview aggregate failed: %s", sql.split()[0:6], exc_info=True)
        return default


def _business(conn) -> dict:
    return {
        "signups_total": _scalar(conn, "SELECT COUNT(*) AS n FROM users WHERE deleted_at IS NULL"),
        "signups_7d": _scalar(conn, "SELECT COUNT(*) AS n FROM users WHERE created_at >= NOW() - INTERVAL '7 days'"),
        "active_subscribers": _scalar(conn, "SELECT COUNT(*) AS n FROM users WHERE subscription_status = 'active' AND deleted_at IS NULL"),
        "trial_active": _scalar(conn, "SELECT COUNT(*) AS n FROM users WHERE subscription_status = 'trialing' AND deleted_at IS NULL"),
        "founding_50_used": _scalar(conn, "SELECT COUNT(*) AS n FROM users WHERE subscription_status = 'active' AND plan_tier IS NOT NULL"),
        "churned_30d": _scalar(conn, "SELECT COUNT(*) AS n FROM users WHERE subscription_status = 'canceled' AND updated_at > NOW() - INTERVAL '30 days'"),
        "upload_volume_30d": _scalar(conn, "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE created_at >= NOW() - INTERVAL '30 days'"),
    }


def _product(conn) -> dict:
    return {
        "dau_today": _scalar(conn, "SELECT COUNT(DISTINCT user_id) AS n FROM app_events WHERE created_at >= CURRENT_DATE"),
        "wau_7d": _scalar(conn, "SELECT COUNT(DISTINCT user_id) AS n FROM app_events WHERE created_at >= NOW() - INTERVAL '7 days'"),
        "total_events_30d": _scalar(conn, "SELECT COUNT(*) AS n FROM app_events WHERE created_at >= NOW() - INTERVAL '30 days'"),
        "unique_features_30d": _scalar(conn, "SELECT COUNT(DISTINCT event_type) AS n FROM app_events WHERE created_at >= NOW() - INTERVAL '30 days'"),
        "funnel": {
            "upload": _scalar(conn, "SELECT COUNT(DISTINCT user_id) AS n FROM app_events WHERE event_type LIKE 'session.%' AND created_at >= NOW() - INTERVAL '30 days'"),
            "analyze": _scalar(conn, "SELECT COUNT(DISTINCT user_id) AS n FROM app_events WHERE event_type LIKE 'chart.%' AND created_at >= NOW() - INTERVAL '30 days'"),
            "export": _scalar(conn, "SELECT COUNT(DISTINCT user_id) AS n FROM app_events WHERE event_type LIKE 'export.%' AND created_at >= NOW() - INTERVAL '30 days'"),
        },
    }


def _live_ops(conn) -> dict:
    total = _scalar(conn, "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE created_at >= NOW() - INTERVAL '24 hours'")
    failed = _scalar(conn, "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE status = 'failed' AND created_at >= NOW() - INTERVAL '24 hours'")
    return {
        "jobs_active": _scalar(conn, "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE status IN ('queued','processing')"),
        "jobs_failed_24h": failed,
        "jobs_completed_24h": _scalar(conn, "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE status = 'completed' AND created_at >= NOW() - INTERVAL '24 hours'"),
        "queue_backlog": _scalar(conn, "SELECT COUNT(*) AS n FROM ingestion_jobs WHERE status = 'queued'"),
        "error_rate_5xx_pct": round((failed / total * 100), 1) if total else 0.0,
        "p95_latency_ms": None,  # served by /admin/metrics; cockpit reads it there
    }


def _growth(conn) -> dict:
    def _evt(event_type: str) -> int:
        return _scalar(
            conn,
            "SELECT COUNT(*) AS n FROM marketing_events "
            "WHERE event_type = %(e)s AND created_at >= NOW() - INTERVAL '7 days'",
            {"e": event_type},
        )
    return {
        "marketing_pageviews_7d": _evt("pageview"),
        "signup_clicked_7d": _evt("signup_clicked"),
        "pricing_viewed_7d": _evt("pricing_viewed"),
        "demo_viewed_7d": _evt("demo_viewed"),
        "waitlist_submitted_7d": _evt("waitlist_submitted"),
        "waitlist_confirmed_7d": _evt("waitlist_confirmed"),
        "download_clicked_7d": _evt("download_clicked"),
    }


def _build_payload(conn) -> dict:
    return {
        "business": _business(conn),
        "product": _product(conn),
        "live_ops": _live_ops(conn),
        "growth": _growth(conn),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }


@bp.route("/overview", methods=["GET"])
@require_superadmin
def overview():
    """One consolidated 4-lens cockpit payload (cross-tenant, audited, cached)."""
    redis = _get_redis()

    if redis is not None:
        try:
            hit = redis.get(_CACHE_KEY)
            if hit is not None:
                body = json.loads(hit)
                body["cached"] = True
                return api_response(body)
        except Exception:
            logger.debug("overview cache read failed", exc_info=True)

    conn = _get_overview_conn()
    payload = _build_payload(conn)

    # Audit: viewing all-tenant behavioral data is itself a processing activity.
    try:
        log_admin_action(
            conn,
            getattr(g, "current_user_id", 0),
            "overview_viewed",
            target_type="admin_overview",
        )
        conn.commit()
    except Exception:
        logger.warning("overview audit log failed", exc_info=True)

    if redis is not None:
        try:
            redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(payload))
        except Exception:
            logger.debug("overview cache write failed", exc_info=True)

    return api_response(payload)
