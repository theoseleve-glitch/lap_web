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
