"""Job management API routes — status, cancel, resume, SSE streaming.

Provides endpoints for monitoring and controlling pipeline processing jobs.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Generator

from flask import Blueprint, Response, g
from sqlalchemy import text

from tasks.job_registry import cancel_job, get_job, list_jobs

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit
from web.validation import validate_body, validate_params
from web.schemas.jobs import JobListParams, ResumeJobSchema

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


def _load_pipeline_context(redis_client, job_id: str):
    """Load PipelineContext from Redis (deferred import for testability)."""
    from pipeline_context import PipelineContext

    return PipelineContext.load(redis_client, job_id)


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
    return api_response({"jobs": jobs})


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
    return api_response(job)


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

    # Create a new job entry as a retry
    import uuid
    new_job_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO ingestion_jobs (job_id, workspace_id, file_name, status, stage_name) "
            "SELECT :new_id, workspace_id, file_name, 'queued', 'retry_queued' "
            "FROM ingestion_jobs WHERE job_id = :old_id AND workspace_id = :ws"
        ),
        {"new_id": new_job_id, "old_id": job_id, "ws": g.workspace_id},
    )
    conn.commit()

    # Dispatch the pipeline task
    try:
        from tasks.pipeline_tasks import run_pipeline
        run_pipeline.delay(new_job_id)
    except Exception:
        logger.exception("Failed to dispatch retry task for %s", new_job_id)

    return api_response({"retried": True, "new_job_id": new_job_id})


@bp.route("/<job_id>/resume", methods=["POST"])
@rate_limit(tier="write")
@validate_body(ResumeJobSchema)
def resume(job_id: str):
    """Resume a paused job with a joker decision.

    Expects validated JSON body via ResumeJobSchema: ``{"joker_decision": "accept"|"reject"}``

    Returns:
        200 with ``{"resumed": true}`` if successful.
        404 if job not found.
        409 if job is not in "paused" status.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)

    if job is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    if job.get("status") != "paused":
        return api_error(
            ErrorCode.CONFLICT,
            f"Job is not paused (current status: {job.get('status')})",
            status=409,
        )

    # Read joker decision from validated body
    joker_decision = g.body.joker_decision

    # Store joker decision in PipelineContext via Redis
    redis_client = _get_redis()
    ctx = _load_pipeline_context(redis_client, job_id)
    if ctx is not None:
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
                    conn = get_pg_connection()
                    job = get_job(conn, job_id, workspace_id)
                except Exception:
                    logger.warning("SSE: failed to query job %s", job_id, exc_info=True)
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

                event = {
                    "status": job.get("status"),
                    "stage_name": job.get("stage_name"),
                    "progress_pct": progress_pct,
                    "error_message": job.get("error_message"),
                }
                yield f"data: {json.dumps(event)}\n\n"

                if job.get("status") in _TERMINAL_STATUSES:
                    return

                time.sleep(_SSE_POLL_INTERVAL)
        except GeneratorExit:
            # Client disconnected — clean up gracefully
            logger.debug("SSE: client disconnected for job %s", job_id)

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
