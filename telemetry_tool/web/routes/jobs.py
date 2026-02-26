"""Job management API routes — status, cancel, resume, SSE streaming.

Provides endpoints for monitoring and controlling pipeline processing jobs.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Generator

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import text

from tasks.job_registry import cancel_job, get_job, list_jobs

logger = logging.getLogger(__name__)

bp = Blueprint("jobs", __name__, url_prefix="/api/v1/jobs")

# Terminal statuses — SSE stream closes when job reaches one of these.
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# SSE polling interval (seconds).
_SSE_POLL_INTERVAL = 2

# SSE stream timeout (seconds) — 30 minutes.
_SSE_TIMEOUT = 30 * 60


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
def list_recent_jobs():
    """List recent jobs for the current workspace.

    Query params:
        limit (int): Max jobs to return (default 50).

    Returns:
        200 with ``{"jobs": [...]}``
    """
    limit = request.args.get("limit", 50, type=int)
    conn = get_pg_connection()
    jobs = list_jobs(conn, g.workspace_id, limit=limit)
    return jsonify({"jobs": jobs}), 200


@bp.route("/<job_id>/status", methods=["GET"])
def job_status(job_id: str):
    """Get current status of a specific job.

    Returns:
        200 with job data, or 404 if not found.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job), 200


@bp.route("/<job_id>/cancel", methods=["POST"])
def cancel(job_id: str):
    """Cancel a running or pending job.

    Returns:
        200 with ``{"cancelled": true}``, or 404 if not cancellable.
    """
    conn = get_pg_connection()
    result = cancel_job(conn, job_id, g.workspace_id)
    if not result:
        return jsonify({"error": "Job not found or already terminal"}), 404
    return jsonify({"cancelled": True}), 200


@bp.route("/<job_id>/resume", methods=["POST"])
def resume(job_id: str):
    """Resume a paused job with a joker decision.

    Expects JSON body: ``{"joker_decision": "accept"|"reject"}``

    Returns:
        200 with ``{"resumed": true}`` if successful.
        404 if job not found.
        409 if job is not in "paused" status.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)

    if job is None:
        return jsonify({"error": "Job not found"}), 404

    if job.get("status") != "paused":
        return jsonify({"error": "Job is not paused", "status": job.get("status")}), 409

    # Read joker decision from request body
    body = request.get_json(silent=True) or {}
    joker_decision = body.get("joker_decision", "")

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

    return jsonify({"resumed": True}), 200


@bp.route("/<job_id>/stream", methods=["GET"])
def stream(job_id: str):
    """SSE endpoint — streams job progress events.

    Polls PG every 2 seconds and emits JSON events with:
    ``{status, stage_name, progress_pct, error_message}``

    Closes on terminal status or after 30-minute timeout.
    """
    workspace_id = g.workspace_id

    def _generate() -> Generator[str, None, None]:
        start = time.time()
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

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
