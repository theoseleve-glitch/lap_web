"""Admin infrastructure routes — storage, maintenance mode.

Endpoints:
- GET  /admin/infra/storage — storage breakdown
- GET  /admin/infra/maintenance — maintenance mode status
- POST /admin/infra/maintenance — toggle maintenance mode
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_infra", __name__)

MAINTENANCE_KEY = "lap:maintenance_mode"


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


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@bp.route("/infra/storage", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def storage_breakdown():
    """Storage breakdown: DB size, table sizes."""
    conn = _get_conn()

    row = conn.execute(
        "SELECT pg_database_size(current_database()) AS size"
    ).fetchone()
    r = dict(row) if not isinstance(row, dict) else row

    return api_response({
        "db_size_bytes": r.get("size", 0),
    })


@bp.route("/infra/maintenance", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def get_maintenance_status():
    """Get current maintenance mode status."""
    r = _get_redis()
    if not r:
        return api_response({"enabled": False, "redis_available": False})

    raw = r.get(MAINTENANCE_KEY)
    if not raw:
        return api_response({"enabled": False})

    data = json.loads(raw)
    return api_response(data)


@bp.route("/infra/maintenance", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def toggle_maintenance():
    """Toggle maintenance mode. Audited."""
    r = _get_redis()
    if not r:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Redis not available",
            status=503,
        )

    body = request.get_json(silent=True) or {}
    enabled = body.get("enabled", True)
    message = body.get("message", "Maintenance in progress")

    if enabled:
        data = {
            "enabled": True,
            "message": message,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "admin_user_id": getattr(g, "current_user_id", None),
        }
        r.set(MAINTENANCE_KEY, json.dumps(data))
    else:
        r.delete(MAINTENANCE_KEY)

    # Audit
    try:
        conn = _get_conn()
        from admin.audit import log_admin_action
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="maintenance_toggled",
            details={"enabled": enabled, "message": message},
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log maintenance toggle", exc_info=True)

    return api_response({
        "enabled": enabled,
        "message": message if enabled else None,
    })
