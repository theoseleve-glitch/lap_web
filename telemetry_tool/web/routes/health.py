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
    import redis as redis_lib
    redis_url = current_app.config.get("REDIS_URL", "")
    if not redis_url:
        return "not_configured"
    r = redis_lib.from_url(redis_url, socket_timeout=2)
    r.ping()
    return "ok"


@bp.route("/healthz")
def healthz():
    """Return service health with DB and Redis checks.

    Returns 200 when core services are healthy, 503 when degraded.
    """
    checks: dict = {"status": "ok", "db": "unknown", "redis": "unknown"}

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

    status_code = 200 if checks["status"] == "ok" else 503
    return jsonify(checks), status_code
