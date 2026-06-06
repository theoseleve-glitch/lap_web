"""Health check endpoint for load balancers and monitoring."""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request
from web.api_utils import api_error, ErrorCode

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
        # Log the detail server-side; don't return the raw exception text in the
        # JSON body (internal-detail disclosure, even on the auth-gated /detail).
        logger.warning("DB stats error: %s", exc)
        return {"error": "db stats unavailable"}


@bp.route("/healthz")
def healthz():
    """Load-balancer liveness probe with DB, Redis, and Celery checks.

    The response body reports every component (db/redis/celery) and an overall
    ``status`` that is "degraded" whenever ANY component is unhealthy — so a
    down Celery worker is now VISIBLE here (previously the worker result was
    discarded and this always returned {"status":"ok"}).

    HTTP 503 is returned ONLY for a HARD dependency failure — the database.
    The API still serves reads/analysis views when the async worker is down
    (uploads queue; Docker restarts dead workers), so a missing worker yields
    status="degraded" with HTTP 200 rather than pulling the node out of LB
    rotation. For a worker-specific hard signal (503 on no workers), point
    monitoring at /healthz/celery.
    """
    checks: dict = {"status": "ok", "db": "unknown", "redis": "unknown", "celery": "unknown"}
    db_down = False

    try:
        checks["db"] = _check_db()
    except Exception as exc:
        logger.warning("Health check DB failure: %s", exc)
        checks["db"] = "error"
        db_down = True

    try:
        checks["redis"] = _check_redis()
    except Exception:
        checks["redis"] = "unavailable"

    try:
        checks["celery"] = _check_celery()
    except Exception:
        checks["celery"] = "unavailable"

    _ok = ("ok", "not_configured")
    if db_down or checks["redis"] not in _ok or checks["celery"] not in _ok:
        checks["status"] = "degraded"
    status_code = 503 if db_down else 200
    return jsonify(checks), status_code


@bp.route("/healthz/detail")
def healthz_detail():
    """Return detailed health with DB stats. Requires auth in production."""
    if current_app.config.get("AUTH_REQUIRED"):
        try:
            from web.middleware.auth import _extract_token
            from auth.service import decode_access_token
            token = _extract_token()
            if not token:
                return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)
            secret = current_app.config.get("JWT_SECRET", "")
            decode_access_token(token, secret)
        except Exception:
            return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    checks: dict = {"status": "ok", "db": "unknown", "redis": "unknown", "celery": "unknown"}
    _hard_down = False

    try:
        checks["db"] = _check_db()
    except Exception as exc:
        logger.warning("Health check DB failure: %s", exc)
        checks["db"] = "error"
        _hard_down = True

    try:
        checks["redis"] = _check_redis()
    except Exception:
        checks["redis"] = "unavailable"

    try:
        checks["celery"] = _check_celery()
    except Exception:
        checks["celery"] = "unavailable"

    try:
        db_stats = _get_db_stats()
        if db_stats:
            checks["db_stats"] = db_stats
    except Exception:
        pass

    # Circuit breaker status
    try:
        from web.middleware.circuit_breaker import get_circuit_status
        circuits = get_circuit_status()
        if circuits:
            checks["circuits"] = circuits
    except ImportError:
        pass

    # Disk space
    try:
        import shutil
        usage = shutil.disk_usage("/")
        checks["disk"] = {
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "free_gb": round(usage.free / (1024 ** 3), 1),
            "used_pct": round((usage.used / usage.total) * 100, 1),
        }
        if checks["disk"]["used_pct"] > 90:
            _hard_down = True
    except Exception:
        pass

    # status reflects ANY unhealthy component (visibility); HTTP 503 only for
    # HARD dependencies (DB / disk). A down worker/redis → "degraded" + 200,
    # consistent with /healthz (this endpoint is auth-gated ops detail, not
    # the LB probe, but uses the same hard/soft model to avoid confusion).
    _ok = ("ok", "not_configured")
    if _hard_down or checks["redis"] not in _ok or checks["celery"] not in _ok:
        checks["status"] = "degraded"
    status_code = 503 if _hard_down else 200
    return jsonify(checks), status_code


@bp.route("/healthz/db")
def healthz_db():
    """Check database connectivity only."""
    try:
        status = _check_db()
        return jsonify({"db": status}), 200
    except Exception as exc:
        logger.warning("Health check DB failure: %s", exc)
        return jsonify({"db": "error"}), 503


@bp.route("/healthz/redis")
def healthz_redis():
    """Check Redis connectivity only."""
    try:
        status = _check_redis()
        code = 200 if status == "ok" else 503
        return jsonify({"redis": status}), code
    except Exception as exc:
        logger.warning("Health check Redis failure: %s", exc)
        return jsonify({"redis": "unavailable"}), 503


@bp.route("/healthz/celery")
def healthz_celery():
    """Check Celery worker availability only."""
    try:
        status = _check_celery()
        code = 200 if status == "ok" else 503
        return jsonify({"celery": status}), code
    except Exception as exc:
        logger.warning("Health check Celery failure: %s", exc)
        return jsonify({"celery": "unavailable"}), 503


@bp.route("/healthz/startup")
def startup_diagnostics():
    """Return startup hardening diagnostics without secret values.

    Requires authentication in production to avoid leaking security posture.
    """
    if current_app.config.get("AUTH_REQUIRED"):
        try:
            from web.middleware.auth import _extract_token
            from auth.service import decode_access_token
            token = _extract_token()
            if not token:
                return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)
            secret = current_app.config.get("JWT_SECRET", "")
            decode_access_token(token, secret)
        except Exception:
            return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

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


@bp.route("/csp-report", methods=["POST"])
def csp_report():
    """Receive CSP violation reports from browsers.

    Browsers POST JSON when Content-Security-Policy is violated.
    We log the violation for monitoring and return 204 No Content.
    """
    report = request.get_json(silent=True, force=True)
    if report:
        violation = report.get("csp-report", report)
        logger.warning(
            "CSP violation: directive=%s blocked=%s document=%s",
            violation.get("violated-directive", "?"),
            violation.get("blocked-uri", "?"),
            violation.get("document-uri", "?"),
        )
    return "", 204
