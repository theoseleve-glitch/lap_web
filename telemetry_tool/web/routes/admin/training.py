"""Admin training routes — status, config, trigger.

Endpoints:
- GET  /admin/training/status  — latest audit manifest
- GET  /admin/training/history — all past training manifests
- POST /admin/training/trigger — dispatch weekly retrain task
- GET  /admin/training/config  — read training config from Redis
- PUT  /admin/training/config  — update training config in Redis
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_training", __name__)

_AUDIT_DIR = Path("/data/models/kart_envelope/audit")
_TRAINING_CONFIG_KEY = "lap:training:config"
_DEFAULT_CONFIG = {
    "schedule_day_of_week": 0,
    "schedule_hour": 0,
    "schedule_minute": 0,
    "min_sessions_per_group": 3,
    "reprocess_batch_size": 10,
    "reprocess_pause_s": 5,
}


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


# ---------------------------------------------------------------------------
# Helper functions (exposed for testing)
# ---------------------------------------------------------------------------


def _list_audit_manifests() -> list[str]:
    """Return sorted list of audit manifest filenames (newest first)."""
    if not _AUDIT_DIR.exists():
        return []
    manifests = sorted(
        _AUDIT_DIR.glob("training_*.json"),
        key=lambda p: p.name,
        reverse=True,
    )
    return [p.name for p in manifests]


def _get_training_status() -> dict:
    """Read the latest audit manifest JSON."""
    manifests = _list_audit_manifests()
    if not manifests:
        return {"status": "no_training_runs", "latest": None}

    latest_path = _AUDIT_DIR / manifests[0]
    try:
        with open(latest_path, "r") as fh:
            data = json.load(fh)
        return {"status": "ok", "latest": data, "manifest_file": manifests[0]}
    except Exception as exc:
        logger.warning("Failed to read audit manifest %s", latest_path, exc_info=True)
        return {"status": "error", "error": str(exc)}


def _get_training_config() -> dict:
    """Read training config from Redis, falling back to defaults."""
    r = _get_redis()
    if not r:
        return dict(_DEFAULT_CONFIG)

    try:
        stored = r.hgetall(_TRAINING_CONFIG_KEY)
        if not stored:
            return dict(_DEFAULT_CONFIG)

        config = dict(_DEFAULT_CONFIG)
        for key in _DEFAULT_CONFIG:
            if key in stored:
                config[key] = int(stored[key])
        return config
    except Exception:
        logger.debug("Failed to read training config from Redis", exc_info=True)
        return dict(_DEFAULT_CONFIG)


def _trigger_training() -> dict:
    """Dispatch the weekly retrain task via Celery."""
    from tasks.training_tasks import weekly_retrain_and_reprocess

    result = weekly_retrain_and_reprocess.apply_async()
    return {"task_id": result.id, "status": "dispatched"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/training/status", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def training_status():
    """Return the latest training audit manifest."""
    data = _get_training_status()
    return api_response(data)


@bp.route("/training/history", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def training_history():
    """Return list of all past training manifest filenames."""
    manifests = _list_audit_manifests()
    return api_response({"manifests": manifests, "count": len(manifests)})


@bp.route("/training/trigger", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def training_trigger():
    """Dispatch weekly retrain task. Audited."""
    try:
        result = _trigger_training()
    except Exception as exc:
        logger.exception("Failed to dispatch training task")
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            f"Failed to dispatch training task: {exc}",
            status=503,
        )

    # Audit
    try:
        conn = _get_conn()
        from admin.audit import log_admin_action
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="training_triggered",
            details={"task_id": result.get("task_id")},
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log training trigger", exc_info=True)

    return api_response(result)


@bp.route("/training/config", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def training_config_get():
    """Read training config from Redis (with defaults fallback)."""
    config = _get_training_config()
    return api_response(config)


@bp.route("/training/config", methods=["PUT"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def training_config_update():
    """Update training config in Redis. Audited."""
    r = _get_redis()
    if not r:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Redis not available",
            status=503,
        )

    body = request.get_json(silent=True) or {}

    # Validate: only known keys, all values must be non-negative integers
    errors = []
    updates = {}
    for key in body:
        if key not in _DEFAULT_CONFIG:
            errors.append({"field": key, "message": f"Unknown config key: {key}"})
            continue
        val = body[key]
        if not isinstance(val, int) or val < 0:
            errors.append({"field": key, "message": f"Must be a non-negative integer, got: {val}"})
            continue
        updates[key] = val

    if errors:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid config values",
            details=errors,
        )

    if not updates:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No valid config keys provided",
        )

    # Write to Redis hash
    r.hset(_TRAINING_CONFIG_KEY, mapping={k: str(v) for k, v in updates.items()})

    # Audit
    try:
        conn = _get_conn()
        from admin.audit import log_admin_action
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="training_config_updated",
            details=updates,
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log config update", exc_info=True)

    # Return updated config
    config = _get_training_config()
    return api_response(config)
