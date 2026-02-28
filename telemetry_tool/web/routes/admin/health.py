"""Admin health routes — system overview and metrics time-series.

Endpoints:
- GET /admin/health/overview — aggregated system health
- GET /admin/health/metrics — time-series snapshots
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_health", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _get_redis():
    try:
        import redis
        from web.config import Config
        return redis.Redis.from_url(Config.REDIS_URL, socket_timeout=2, decode_responses=True)
    except Exception:
        return None


@bp.route("/health/overview", methods=["GET"])
@require_superadmin
def health_overview():
    """Aggregated system health dashboard."""
    conn = _get_conn()

    result = {}

    # Services status
    services = {"api": "ok", "db": "unknown", "redis": "unknown", "celery": "unknown"}
    try:
        conn.execute("SELECT 1")
        services["db"] = "ok"
    except Exception:
        services["db"] = "error"

    r = _get_redis()
    if r:
        try:
            r.ping()
            services["redis"] = "ok"
        except Exception:
            services["redis"] = "error"
    else:
        services["redis"] = "unavailable"

    result["services"] = services

    # Jobs
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE status = 'failed') AS failed, "
            "COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS queue_depth, "
            "AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) "
            "  FILTER (WHERE completed_at IS NOT NULL) AS avg_duration "
            "FROM ingestion_jobs "
            "WHERE created_at > NOW() - INTERVAL '24 hours'"
        ).fetchone()
        jr = dict(row) if not isinstance(row, dict) else row
        total = jr.get("total", 0) or 0
        failed = jr.get("failed", 0) or 0
        result["jobs"] = {
            "total_24h": total,
            "failed_24h": failed,
            "queue_depth": jr.get("queue_depth", 0) or 0,
            "failure_rate_pct": round((failed / total * 100) if total > 0 else 0, 1),
            "avg_duration_s": round(jr.get("avg_duration") or 0, 1),
        }
    except Exception:
        result["jobs"] = {"error": "query failed"}

    # Billing
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE processing_status = 'processed') AS success "
            "FROM stripe_webhook_log "
            "WHERE created_at > NOW() - INTERVAL '24 hours'"
        ).fetchone()
        br = dict(row) if not isinstance(row, dict) else row
        total = br.get("total", 0) or 0
        success = br.get("success", 0) or 0
        result["billing"] = {
            "webhook_total_24h": total,
            "webhook_success_rate_pct": round((success / total * 100) if total > 0 else 100, 1),
        }
    except Exception:
        result["billing"] = {"error": "query failed"}

    # Security
    try:
        row = conn.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE event_type = 'login_failed') AS login_failures, "
            "COUNT(*) FILTER (WHERE event_type = 'rate_limited') AS rate_limits "
            "FROM security_events "
            "WHERE created_at > NOW() - INTERVAL '24 hours'"
        ).fetchone()
        sr = dict(row) if not isinstance(row, dict) else row
        result["security"] = {
            "login_failures_24h": sr.get("login_failures", 0) or 0,
            "rate_limits_24h": sr.get("rate_limits", 0) or 0,
        }
    except Exception:
        result["security"] = {"error": "query failed"}

    return api_response(result)


@bp.route("/health/metrics", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def health_metrics():
    """Time-series metrics snapshots."""
    hours = request.args.get("hours", 6, type=int)
    hours = min(hours, 168)  # Cap at 7 days

    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, collected_at, metrics_json "
        "FROM system_metrics_snapshots "
        "WHERE collected_at > NOW() - INTERVAL '1 hour' * %(hours)s "
        "ORDER BY collected_at DESC",
        {"hours": hours},
    ).fetchall()

    snapshots = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        metrics = r.get("metrics_json", "{}")
        if isinstance(metrics, str):
            metrics = json.loads(metrics)
        snapshots.append({
            "id": r["id"],
            "collected_at": str(r["collected_at"]),
            "metrics": metrics,
        })

    return api_response(snapshots)
