"""Job management API routes — status, cancel, resume, SSE streaming.

Provides endpoints for monitoring and controlling pipeline processing jobs.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import PurePosixPath
from typing import Generator

from flask import Blueprint, Response, g
from sqlalchemy import text

from tasks.job_registry import cancel_job, get_job, list_jobs
from web.api_utils import ErrorCode, api_error, api_response
from web.rate_limit import rate_limit
from web.schemas.jobs import JobListParams, ResumeJobSchema
from web.validation import validate_body, validate_params

logger = logging.getLogger(__name__)

bp = Blueprint("jobs", __name__, url_prefix="/api/v1/jobs")

# Terminal statuses — SSE stream closes when job reaches one of these.
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# SSE polling interval (seconds).
_SSE_POLL_INTERVAL = 2

# SSE stream timeout (seconds) — 30 minutes.
_SSE_TIMEOUT = 30 * 60

# SSE staleness threshold (seconds) — emit "stale" event if updated_at
# hasn't changed for this long (likely a stuck/crashed worker).
_SSE_STALE_SECONDS = 5 * 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_pg_connection():
    """Return a PG connection via the web.db_pg module."""
    from web.db_pg import get_pg_connection as _get_pg

    return _get_pg()


def _get_redis():
    """Create a Redis client from the app config."""
    import redis

    from web.config import Config

    return redis.Redis.from_url(Config.REDIS_URL)


def _sanitize_job(job: dict) -> dict:
    """Prepare a job dict for the API response.

    - Derives ``file_name`` from ``file_path`` (basename only, never expose
      full server paths).
    - Removes ``file_path`` from the output.
    - Adds ``session_id`` (equal to ``job_id`` — set at upload time).
    - Sanitises ``error_message`` to avoid leaking internal details
      (file paths, connection strings, module names).
    """
    out = dict(job)
    fp = out.pop("file_path", None)
    if fp:
        out["file_name"] = PurePosixPath(fp).name
    else:
        out.setdefault("file_name", None)
    # session_id is the same as job_id (set in sessions_v2.py upload).
    out.setdefault("session_id", out.get("job_id"))
    # Sanitise error_message: map known error classes to user-safe messages,
    # fall back to a generic message for unrecognised errors.
    raw_err = out.get("error_message")
    if raw_err:
        err_class = out.get("error_class", "")
        _USER_MESSAGES = {
            "fatal": "Analysis failed. The file may be corrupted or in an unsupported format.",
            "transient": "A temporary error occurred. Please retry.",
            "entitlement": "Your plan does not allow this operation.",
        }
        out["error_message"] = _USER_MESSAGES.get(
            err_class,
            "Processing failed. Please retry or contact support.",
        )
    return out


def _load_pipeline_context(redis_client, job_id: str):
    """Load PipelineContext from Redis (deferred import for testability)."""
    from pipeline_context import PipelineContext

    return PipelineContext.load(redis_client, job_id)


def _reconstruct_context_from_db(conn, job_id: str, redis_client, temp_root: str = "/tmp"):
    """Reconstruct PipelineContext from DB when Redis state is gone.

    Used for corner re-selection on completed sessions. Returns None if
    the job is not found or the original CSV no longer exists.
    """
    from pathlib import Path
    from pipeline_context import PipelineContext

    row = conn.execute(
        text("SELECT job_id, workspace_id, file_path FROM ingestion_jobs WHERE job_id = :job_id"),
        {"job_id": job_id},
    ).fetchone()

    if row is None:
        return None

    file_path = row["file_path"] if isinstance(row, dict) else row[2]
    workspace_id = row["workspace_id"] if isinstance(row, dict) else row[1]

    if not file_path or not Path(file_path).exists():
        return None

    return PipelineContext.create(
        redis_client=redis_client,
        job_id=job_id,
        workspace_id=str(workspace_id) if workspace_id else None,
        session_id=job_id,  # convention: session_id == job_id
        file_path=str(file_path),
        temp_root=temp_root,
    )


def _revoke_inflight_ocp(conn, job_id: str):
    """Revoke an in-flight OCP Celery task to prevent race conditions."""
    try:
        row = conn.execute(
            text("SELECT analysis_json FROM sessions WHERE id = :sid"),
            {"sid": job_id},
        ).fetchone()
        if row:
            aj = json.loads(row[0]) if row[0] else {}
            ocp_task_id = aj.get("ocp_task_id")
            if ocp_task_id:
                try:
                    from tasks.celery_app import celery
                    celery.control.revoke(ocp_task_id, terminate=True)
                    logger.info("Revoked in-flight OCP task %s for job %s", ocp_task_id, job_id)
                except ImportError:
                    pass
    except Exception:
        logger.debug("OCP revocation skipped for job %s", job_id, exc_info=True)


def _dispatch_finalize(job_id: str):
    """Dispatch the pipeline_finalize Celery task (deferred import for testability)."""
    from tasks.pipeline_tasks import pipeline_finalize

    pipeline_finalize.delay(job_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@bp.route("", methods=["GET"])
@rate_limit(tier="read")
@validate_params(JobListParams)
def list_recent_jobs():
    """List recent jobs for the current workspace.

    Query params validated via JobListParams schema.

    Returns:
        200 with ``{"jobs": [...]}``
    """
    limit = g.params.limit
    conn = get_pg_connection()
    jobs = list_jobs(conn, g.workspace_id, limit=limit)
    return api_response({"jobs": [_sanitize_job(j) for j in jobs]})


@bp.route("/<job_id>/status", methods=["GET"])
@rate_limit(tier="read")
def job_status(job_id: str):
    """Get current status of a specific job.

    Returns:
        200 with job data, or 404 if not found.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)
    if job is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)
    return api_response(_sanitize_job(job))


@bp.route("/<job_id>/cancel", methods=["POST"])
@rate_limit(tier="write")
def cancel(job_id: str):
    """Cancel a running or pending job.

    Returns:
        200 with ``{"cancelled": true}``, or 404 if not cancellable.
    """
    conn = get_pg_connection()
    result = cancel_job(conn, job_id, g.workspace_id)
    if not result:
        return api_error(ErrorCode.NOT_FOUND, "Job not found or already terminal", status=404)
    return api_response({"cancelled": True})


@bp.route("/<job_id>/retry", methods=["POST"])
@rate_limit(tier="write")
def retry(job_id: str):
    """Retry a failed job by creating a new Celery task.

    Returns:
        200 with ``{"retried": true, "new_job_id": "..."}``
        404 if not found
        409 if job is not in a failed/cancelled state
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)

    if job is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    if job.get("status") not in ("failed", "cancelled"):
        return api_error(
            ErrorCode.CONFLICT,
            f"Only failed/cancelled jobs can be retried (current: {job.get('status')})",
            status=409,
        )

    # Check compute budget before retrying
    try:
        from web.compute_budget import check_compute_budget
        plan_tier = getattr(g, "plan_tier", None)
        allowed, info = check_compute_budget(conn, getattr(g, "current_user_id", 0), g.workspace_id, plan_tier)
        if not allowed:
            return api_error(
                ErrorCode.RATE_LIMITED,
                f"Compute budget exceeded: {info['running_jobs']}/{info['max_jobs']} jobs running",
                status=429,
            )
    except Exception:
        logger.warning("Compute budget check failed — allowing retry", exc_info=True)

    # Create a new job entry as a retry (copy file_path and required NOT NULL cols)
    import uuid
    new_job_id = uuid.uuid4().hex

    # Get original job's file_path for the PipelineContext
    original_file_path = job.get("file_path", "")

    conn.execute(
        text(
            "INSERT INTO ingestion_jobs "
            "  (job_id, workspace_id, file_path, file_size, sha256_partial, "
            "   status, stage_name, stage_index, stage_total, updated_at) "
            "SELECT :new_id, workspace_id, file_path, file_size, "
            "  COALESCE(sha256_partial, ''), "
            "  'pending', 'retry_queued', 0, 14, now() "
            "FROM ingestion_jobs WHERE job_id = :old_id AND workspace_id = :ws"
        ),
        {"new_id": new_job_id, "old_id": job_id, "ws": g.workspace_id},
    )
    conn.commit()

    # Seed PipelineContext in Redis (required by Celery workers)
    try:
        from pipeline_context import PipelineContext

        redis_client = _get_redis()
        PipelineContext.create(
            redis_client=redis_client,
            job_id=new_job_id,
            workspace_id=str(g.workspace_id),
            session_id=new_job_id,
            file_path=original_file_path,
        )

        # Copy session metadata from original job if available
        original_meta = redis_client.get(f"pipeline:meta:{job_id}")
        if original_meta:
            redis_client.set(f"pipeline:meta:{new_job_id}", original_meta, ex=7200)
    except Exception:
        logger.warning("Failed to seed PipelineContext for retry %s", new_job_id, exc_info=True)

    # Dispatch the pipeline chain (ingest → analyze → finalize)
    try:
        from tasks.pipeline_tasks import build_pipeline_chain
        build_pipeline_chain(new_job_id).apply_async()
    except Exception:
        logger.exception("Failed to dispatch retry task for %s", new_job_id)

    return api_response({"retried": True, "new_job_id": new_job_id})


@bp.route("/<job_id>/track-layout", methods=["GET"])
@rate_limit(tier="read")
def track_layout(job_id: str):
    """Get the track layout for corner selection.

    Only available when the job is in ``awaiting_corner_selection`` status.

    Returns:
        200 with track layout JSON (latitudes, longitudes, distances, speeds, corners).
        404 if job not found.
        409 if job is not awaiting corner selection.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)

    if job is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    if job.get("status") != "awaiting_corner_selection":
        return api_error(
            ErrorCode.CONFLICT,
            f"Job is not awaiting corner selection (current: {job.get('status')})",
            status=409,
        )

    # Read track layout from Redis
    redis_client = _get_redis()
    raw = redis_client.get(f"pipeline:layout:{job_id}")
    if raw is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            "Track layout not found (may have expired)",
            status=404,
        )

    layout = json.loads(raw)
    return api_response(layout)


@bp.route("/<job_id>/resume", methods=["POST"])
@rate_limit(tier="write")
@validate_body(ResumeJobSchema)
def resume(job_id: str):
    """Resume a paused job with a joker decision or corner selection.

    Accepts either:
    - ``{"joker_decision": "accept"|"reject"}`` for paused (joker) jobs
    - ``{"selected_corner_ids": [0, 2, 5]}`` for awaiting_corner_selection jobs

    Returns:
        200 with ``{"resumed": true}`` if successful.
        404 if job not found.
        409 if job is not in a resumable status.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)

    if job is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    current_status = job.get("status")
    if current_status not in ("paused", "awaiting_corner_selection", "completed"):
        return api_error(
            ErrorCode.CONFLICT,
            f"Job is not resumable (current status: {current_status})",
            status=409,
        )

    redis_client = _get_redis()
    ctx = _load_pipeline_context(redis_client, job_id)

    if ctx is None and current_status == "completed":
        ctx = _reconstruct_context_from_db(conn, job_id, redis_client)
        if ctx is None:
            return api_error(
                ErrorCode.CONFLICT,
                "Original session file no longer available. Please re-upload.",
                status=409,
            )

    if ctx is None:
        return api_error(
            ErrorCode.CONFLICT,
            "Pipeline context expired. Please re-upload the file.",
            status=409,
        )

    if current_status in ("awaiting_corner_selection", "completed"):
        # Corner selection path — custom geometry or legacy ID filter
        if g.body.corners is not None:
            ctx.set_custom_corners([
                {"s_start": c.s_start, "s_apex": c.s_apex, "s_end": c.s_end}
                for c in g.body.corners
            ])
            ctx.save()
        elif g.body.selected_corner_ids is not None:
            ctx.set_selected_corner_ids(g.body.selected_corner_ids)
            ctx.save()
    else:
        # Joker decision path
        joker_decision = g.body.joker_decision
        if joker_decision is not None:
            ctx.set_joker_decision(joker_decision)
            ctx.save()

    # Update job status to processing
    conn.execute(
        text(
            "UPDATE ingestion_jobs SET status = 'processing', updated_at = now() "
            "WHERE job_id = :job_id AND workspace_id = :workspace_id"
        ),
        {"job_id": job_id, "workspace_id": g.workspace_id},
    )
    conn.commit()

    # Revoke any in-flight OCP task from the previous run
    if current_status == "completed":
        _revoke_inflight_ocp(conn, job_id)

    # Dispatch pipeline_finalize task
    _dispatch_finalize(job_id)

    return api_response({"resumed": True})


@bp.route("/<job_id>/stream", methods=["GET"])
def stream(job_id: str):
    """SSE endpoint — streams job progress events.

    Polls PG every 2 seconds and emits JSON events with:
    ``{status, stage_name, progress_pct, error_message}``

    Closes on terminal status, after 30-minute timeout, or if the job
    appears stale (``updated_at`` unchanged for 5 minutes).
    """
    workspace_id = g.workspace_id

    def _generate() -> Generator[str, None, None]:
        start = time.time()
        last_updated_at = None
        last_change_time = start
        conn = None
        try:
            while True:
                elapsed = time.time() - start
                if elapsed > _SSE_TIMEOUT:
                    yield f"data: {json.dumps({'status': 'timeout', 'error_message': 'SSE stream timed out'})}\n\n"
                    return

                try:
                    if conn is None:
                        conn = get_pg_connection()
                    job = get_job(conn, job_id, workspace_id)
                except Exception:
                    logger.warning("SSE: failed to query job %s", job_id, exc_info=True)
                    # Close broken connection so next iteration creates a fresh one
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = None
                    yield f"data: {json.dumps({'status': 'error', 'error_message': 'DB query failed'})}\n\n"
                    time.sleep(_SSE_POLL_INTERVAL)
                    continue

                if job is None:
                    yield f"data: {json.dumps({'status': 'not_found', 'error_message': 'Job not found'})}\n\n"
                    return

                # Staleness detection: if updated_at hasn't changed for 5 minutes,
                # the job is likely stuck (worker crash, lost Celery task, etc.).
                current_updated = job.get("updated_at")
                if current_updated != last_updated_at:
                    last_updated_at = current_updated
                    last_change_time = time.time()
                elif time.time() - last_change_time > _SSE_STALE_SECONDS:
                    yield f"data: {json.dumps({'status': 'stale', 'error_message': 'Job appears stuck — no progress for 5 minutes'})}\n\n"
                    return

                # Compute progress percentage
                stage_index = job.get("stage_index") or 0
                stage_total = job.get("stage_total") or 15
                progress_pct = round((stage_index / stage_total) * 100, 1) if stage_total > 0 else 0

                # Sanitise error_message for SSE: don't leak internals
                raw_err = job.get("error_message")
                safe_err = None
                if raw_err:
                    err_class = job.get("error_class", "")
                    _SSE_MSGS = {
                        "fatal": "Analysis failed. The file may be corrupted or unsupported.",
                        "transient": "A temporary error occurred. Retrying...",
                        "entitlement": "Plan limit reached.",
                    }
                    safe_err = _SSE_MSGS.get(err_class, "Processing failed.")

                event = {
                    "status": job.get("status"),
                    "stage_name": job.get("stage_name"),
                    "progress_pct": progress_pct,
                    "error_message": safe_err,
                    "session_id": job.get("session_id") or job.get("job_id"),
                }
                yield f"data: {json.dumps(event)}\n\n"

                if job.get("status") in _TERMINAL_STATUSES:
                    return

                time.sleep(_SSE_POLL_INTERVAL)
        except GeneratorExit:
            # Client disconnected — clean up gracefully
            logger.debug("SSE: client disconnected for job %s", job_id)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
