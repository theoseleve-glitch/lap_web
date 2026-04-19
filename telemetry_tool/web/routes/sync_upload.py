"""Sync upload endpoint — receives session CSVs from the Lap Coach Logger.

POST /api/v1/sessions/sync-upload
    Auth: DeviceToken header (not JWT)
    Body: multipart/form-data with telemetry (CSV) + manifest (JSON string)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response
from web.middleware.device_auth import require_device_token
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("sync_upload", __name__, url_prefix="/api/v1")


@bp.route("/sessions/sync-upload", methods=["POST"])
@require_device_token
@rate_limit("sync_upload")
def sync_upload():
    """Receive a session CSV from the logger and store it."""
    from web.db_pg import get_pg_connection
    from auth.entitlements import (
        authorize_feature,
        check_and_record_quota,
        get_plan_entitlements,
        get_user_plan_tier,
    )

    conn = get_pg_connection()
    user_id = g.current_user_id
    workspace_id = g.workspace_id

    # 1. Check device_sync entitlement
    allowed, ctx = authorize_feature(conn, user_id, "device_sync")
    if not allowed:
        return api_error(ErrorCode.FORBIDDEN, ctx.get("reason", "Sync not available"), status=403)

    # 2. Parse inputs
    telemetry_file = request.files.get("telemetry")
    manifest_raw = request.form.get("manifest", "{}")

    if telemetry_file is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "telemetry file is required", status=400)

    try:
        manifest = json.loads(manifest_raw)
    except (json.JSONDecodeError, TypeError):
        return api_error(ErrorCode.VALIDATION_ERROR, "manifest must be valid JSON", status=400)

    bundle_hash = manifest.get("bundle_hash", "")

    # 3. Idempotency check
    if bundle_hash:
        cur = conn.execute(
            "SELECT id FROM sessions "
            "WHERE workspace_id = %(wsid)s AND source_bundle_hash = %(hash)s",
            {"wsid": workspace_id, "hash": bundle_hash},
        )
        existing = cur.fetchone()
        if existing:
            r = dict(existing) if not isinstance(existing, dict) else existing
            return api_response({
                "session_id": r["id"],
                "status": "already_uploaded",
                "analyze_triggered": False,
            })

    # 4. Check upload volume quota
    telemetry_file.seek(0, 2)
    file_size = telemetry_file.tell()
    telemetry_file.seek(0)
    file_size_mb = max(1, file_size // (1024 * 1024))

    allowed, ctx = check_and_record_quota(
        conn, user_id, workspace_id, "upload_volume_mb", cost=file_size_mb,
    )
    if not allowed:
        return api_error(
            ErrorCode.QUOTA_EXCEEDED,
            f"Monthly upload volume exceeded ({ctx.get('used', 0)} MB / {ctx.get('limit', 0)} MB)",
            status=429,
        )

    # 5. Save CSV to upload directory
    upload_dir = Path(os.environ.get("UPLOAD_DIR", tempfile.gettempdir())) / "sync_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    csv_path = upload_dir / f"{job_id}.csv"
    telemetry_file.save(str(csv_path))

    # 6. Insert session row
    session_id = _insert_session(conn, workspace_id, user_id, manifest, bundle_hash, csv_path, job_id)

    # 7. Check auto-analyze
    tier = get_user_plan_tier(conn, user_id)
    plan = get_plan_entitlements(tier)
    auto_analyze = plan.get("auto_analyze_on_sync", False)

    if auto_analyze:
        # Check analyses quota
        allowed, ctx = check_and_record_quota(
            conn, user_id, workspace_id, "analyses", cost=1,
        )
        if allowed:
            # Dispatch Celery pipeline
            _dispatch_pipeline(conn, session_id, job_id, csv_path, manifest, workspace_id)
            return api_response({
                "session_id": session_id,
                "job_id": job_id,
                "status": "analyzing",
                "analyze_triggered": True,
            })
        else:
            logger.warning("World-class user %s hit analyses quota — uploading without auto-analyze", user_id)

    return api_response({
        "session_id": session_id,
        "status": "pending_analysis",
        "analyze_triggered": False,
    })


def _insert_session(conn, workspace_id, user_id, manifest, bundle_hash, csv_path, job_id):
    """Insert a session row from logger manifest data."""
    cur = conn.execute(
        "INSERT INTO sessions "
        "(workspace_id, driver_id, track_id, session_type, source, "
        " source_bundle_hash, status, file_path, created_by) "
        "VALUES (%(wsid)s, NULL, NULL, %(stype)s, 'logger', "
        "%(hash)s, 'uploaded', %(fpath)s, %(uid)s) "
        "RETURNING id",
        {
            "wsid": workspace_id,
            "stype": manifest.get("session_type", "practice"),
            "hash": bundle_hash,
            "fpath": str(csv_path),
            "uid": user_id,
        },
    )
    row = cur.fetchone()
    return (dict(row) if not isinstance(row, dict) else row)["id"]


def _dispatch_pipeline(conn, session_id, job_id, csv_path, manifest, workspace_id):
    """Dispatch the Celery analysis pipeline.

    Mirrors sessions_v2.py: seed PipelineContext in Redis, then call
    build_pipeline_chain(job_id).apply_async().
    """
    try:
        import json as _json

        import redis as _redis

        from pipeline_context import PipelineContext
        from tasks.pipeline_tasks import build_pipeline_chain

        # 1. Create ingestion_jobs row (worker expects it)
        conn.execute(
            """INSERT INTO ingestion_jobs
               (job_id, workspace_id, file_path, file_size, sha256_partial,
                status, stage_name, stage_index, stage_total, updated_at)
               VALUES (%(job_id)s, %(ws)s, %(fpath)s, %(fsize)s, '',
                       'pending', 'Queued', 0, 14, NOW())""",
            {
                "job_id": job_id,
                "ws": str(workspace_id),
                "fpath": str(csv_path),
                "fsize": csv_path.stat().st_size if isinstance(csv_path, Path) else 0,
            },
        )
        conn.commit()

        # 2. Seed PipelineContext in Redis
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _r = _redis.from_url(redis_url)
        PipelineContext.create_in_redis(
            _r,
            job_id=job_id,
            workspace_id=str(workspace_id),
            session_id=job_id,
            file_path=str(csv_path),
        )
        session_meta = {
            "session_type": manifest.get("session_type", "practice"),
            "driver_name": manifest.get("driver_name", "Unknown"),
            "source_filename": manifest.get("session_id", "logger_upload"),
        }
        _r.set(f"pipeline:meta:{job_id}", _json.dumps(session_meta), ex=7200)

        # 3. Dispatch Celery chain
        build_pipeline_chain(job_id).apply_async()
        logger.info("Dispatched pipeline for sync session %s (job %s)", session_id, job_id)
    except Exception:
        logger.exception("Failed to dispatch pipeline for sync session %s", session_id)
