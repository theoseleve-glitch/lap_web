"""Health check endpoint for load balancers and monitoring."""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("health", __name__)


def _check_db() -> str:
    """Check database connectivity. Returns 'ok' or 'error'."""
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()
    else:
        from web.db import get_db_connection
        conn = get_db_connection()
    conn.execute("SELECT 1")
    return "ok"


def _check_redis() -> str:
    """Check Redis connectivity. Returns 'ok', 'not_configured', or 'unavailable'."""
    r = current_app.extensions.get("redis")
    if r is None:
        redis_url = current_app.config.get("REDIS_URL", "")
        if not redis_url:
            return "not_configured"
        import redis as redis_lib
        r = redis_lib.from_url(redis_url, socket_timeout=2)
    r.ping()
    return "ok"


def _check_celery() -> str:
    """Check if Celery workers are responsive."""
    celery_inst = current_app.extensions.get("celery")
    if celery_inst is None:
        return "not_configured"
    inspector = celery_inst.control.inspect(timeout=2)
    active = inspector.active()
    if active:
        return "ok"
    return "no_workers"


def _get_db_stats() -> dict:
    """Return database performance stats (PG only)."""
    if not current_app.config.get("USE_PG"):
        return {}
    try:
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()

        # Active connection count
        cur = conn.execute(
            "SELECT count(*) AS cnt FROM pg_stat_activity "
            "WHERE datname = current_database()"
        )
        row = cur.fetchone()
        conn_count = row["cnt"] if row else 0

        # Database size
        cur = conn.execute(
            "SELECT pg_database_size(current_database()) AS db_size"
        )
        row = cur.fetchone()
        db_size_mb = round((row["db_size"] or 0) / (1024 * 1024), 1) if row else 0

        # Top tables by size
        cur = conn.execute(
            "SELECT relname, pg_total_relation_size(c.oid) AS total_bytes "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 5"
        )
        top_tables = [
            {"table": r["relname"], "size_mb": round(r["total_bytes"] / (1024 * 1024), 2)}
            for r in cur.fetchall()
        ]

        return {
            "connections": conn_count,
            "database_size_mb": db_size_mb,
            "top_tables": top_tables,
        }
    except Exception as exc:
        logger.warning("DB stats error: %s", exc)
        return {"error": str(exc)}


@bp.route("/healthz")
def healthz():
    """Return service health with DB, Redis, and Celery checks.

    Returns 200 when core services are healthy, 503 when degraded.
    """
    checks: dict = {"status": "ok", "db": "unknown", "redis": "unknown", "celery": "unknown"}

    try:
        checks["db"] = _check_db()
    except Exception as exc:
        logger.warning("Health check DB failure: %s", exc)
        checks["db"] = "error"
        checks["status"] = "degraded"

    try:
        checks["redis"] = _check_redis()
    except Exception:
        checks["redis"] = "unavailable"

    try:
        checks["celery"] = _check_celery()
    except Exception:
        checks["celery"] = "unavailable"

    # Include DB stats when running on PG
    try:
        db_stats = _get_db_stats()
        if db_stats:
            checks["db_stats"] = db_stats
    except Exception:
        pass

    status_code = 200 if checks["status"] == "ok" else 503
    return jsonify(checks), status_code


@bp.route("/healthz/startup")
def startup_diagnostics():
    """Return startup hardening diagnostics without secret values."""
    summary = dict(current_app.config.get("HARDENING_SUMMARY", {}))
    status = "hardened"

    if summary.get("env") == "production":
        required = (
            summary.get("auth_required"),
            summary.get("auth_required_explicit"),
            summary.get("secret_key_strong"),
            summary.get("jwt_secret_strong"),
        )
        if not all(required):
            status = "not_hardened"

    return jsonify({"status": status, "hardening": summary}), 200
