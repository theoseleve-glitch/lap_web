"""Endurance upload flow — quick detect + per-stint processing."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from flask import Blueprint, g, request

from web.api_utils import api_error, api_response, ErrorCode
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)
bp = Blueprint("endurance_upload", __name__, url_prefix="/api/v1/endurance")


@bp.route("/detect", methods=["POST"])
@rate_limit(tier="write")
def detect_stints():
    """Upload CSV + quick detect lap times and pit stops."""
    try:
        return _detect_stints_inner()
    except Exception as exc:
        logger.exception("endurance/detect failed: %s", exc)
        # Don't echo the raw exception to the client (internal-detail disclosure);
        # the full traceback is in the server log above.
        return api_error(ErrorCode.INTERNAL_ERROR, "Detection failed", status=500)


def _detect_stints_inner():
    f = request.files.get("file")
    if not f or not f.filename:
        return api_error(ErrorCode.VALIDATION_ERROR, "No file provided", status=400)

    pit_threshold = float(request.form.get("pit_threshold_s", 120))
    drivers_json = request.form.get("drivers", "[]")
    try:
        drivers = json.loads(drivers_json)
    except (json.JSONDecodeError, TypeError):
        drivers = []

    # Save file to temp location
    job_id = uuid.uuid4().hex[:24]
    upload_dir = Path(f"/data/uploads/endurance_{job_id}")
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(f.filename).name  # strip directory traversal
    file_path = upload_dir / safe_name
    f.save(str(file_path))

    # Quick detect
    from endurance_ingest import detect_laps_quick
    result = detect_laps_quick(str(file_path), pit_threshold)

    if result.get("error"):
        return api_error(ErrorCode.VALIDATION_ERROR, result["error"], status=400)

    # Cache metadata in Redis for the process step
    import redis as _redis
    from web.config import Config
    _r = _redis.Redis.from_url(Config.REDIS_URL)
    _r.set(f"endurance:meta:{job_id}", json.dumps({
        "file_path": str(file_path),
        "file_name": safe_name,
        "drivers": drivers,
        "pit_threshold_s": pit_threshold,
        "workspace_id": str(getattr(g, "workspace_id", 1)),
        "session_meta": {
            "session_type": "endurance",
            "track_state": request.form.get("track_state", "dry"),
            "kart_name": request.form.get("kart_name", ""),
            "track_name": request.form.get("track_name", ""),
            "session_date": request.form.get("session_date", ""),
        },
    }), ex=7200)

    result["job_id"] = job_id
    return api_response(result)


@bp.route("/process", methods=["POST"])
@rate_limit(tier="write")
def process_stints():
    """Start per-stint processing with user-confirmed configuration."""
    try:
        body = request.get_json(silent=True) or {}
        job_id = body.get("job_id")
        stint_configs = body.get("stints")

        if not job_id or not stint_configs:
            return api_error(ErrorCode.VALIDATION_ERROR, "job_id and stints required", status=400)

        import redis as _redis
        from web.config import Config
        _r = _redis.Redis.from_url(Config.REDIS_URL)
        raw = _r.get(f"endurance:meta:{job_id}")
        if not raw:
            return api_error(ErrorCode.NOT_FOUND, "Job expired or not found", status=404)

        meta = json.loads(raw)

        # Write initial status BEFORE dispatching
        _r.set(f"endurance:status:{job_id}", json.dumps({
            "status": "queued",
            "total_stints": len(stint_configs),
            "stints": [{"stint_number": s.get("stint_number"), "driver_name": s.get("driver_name", ""), "status": "queued"} for s in stint_configs],
        }), ex=7200)

        # Shared per-tier compute budget (analysis + export + surface pool).
        # Fail-open: never block a legitimate endurance run on a metering error.
        try:
            from web.compute_budget import check_shared_compute_budget
            from web.db import get_conn
            _ws = int(meta.get("workspace_id") or 0)
            _uid = getattr(g, "current_user_id", 0) or 0
            allowed, info = check_shared_compute_budget(
                get_conn(), _uid, _ws, getattr(g, "plan_tier", None)
            )
            if not allowed:
                return api_error(
                    ErrorCode.RATE_LIMITED,
                    f"Compute budget exceeded: {info['running_jobs']}/{info['max_jobs']} jobs running",
                    status=429,
                )
        except Exception:
            logger.warning("Shared compute budget check failed — allowing endurance", exc_info=True)

        from tasks.endurance_tasks import process_endurance_session
        process_endurance_session.delay(job_id, meta, stint_configs)

        return api_response({"job_id": job_id, "stints_queued": len(stint_configs)})
    except Exception as exc:
        logger.exception("endurance/process failed: %s", exc)
        # Don't echo the raw exception to the client; traceback is logged above.
        return api_error(ErrorCode.INTERNAL_ERROR, "Processing failed", status=500)


@bp.route("/status/<job_id>", methods=["GET"])
def endurance_status(job_id: str):
    """Poll endpoint for endurance job status."""
    import redis as _redis
    from web.config import Config
    _r = _redis.Redis.from_url(Config.REDIS_URL)
    raw = _r.get(f"endurance:status:{job_id}")
    if not raw:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)
    return api_response(json.loads(raw))


@bp.route("/report/<job_id>", methods=["GET"])
def endurance_report(job_id: str):
    """Get the full endurance report after processing."""
    import redis as _redis
    from web.config import Config
    _r = _redis.Redis.from_url(Config.REDIS_URL)
    raw = _r.get(f"endurance:report:{job_id}")
    if not raw:
        return api_error(ErrorCode.NOT_FOUND, "Report not ready or expired", status=404)
    return api_response(json.loads(raw))
