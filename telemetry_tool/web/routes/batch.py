"""Batch reprocessing API routes — create, list, cancel batches.

Provides endpoints for triggering batch re-analysis of all sessions
in a workspace, listing batch job status, and cancelling batches.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request
from sqlalchemy import text

logger = logging.getLogger(__name__)

bp = Blueprint("batch", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_pg_connection():
    """Return a PG connection via the web.db_pg module."""
    from web.db_pg import get_pg_connection as _get_pg

    return _get_pg()


def _dispatch_batch_task(batch_job_id: int, workspace_id: int):
    """Dispatch the dispatch_batch Celery task (deferred import for testability)."""
    from tasks.batch_tasks import dispatch_batch

    dispatch_batch.delay(batch_job_id, workspace_id)


def _revoke_batch_tasks(batch_id: int, workspace_id: int):
    """Revoke all pending Celery tasks for a batch.

    Queries ingestion_jobs associated with this batch and revokes
    each pending/running task.
    """
    try:
        conn = get_pg_connection()
        cursor = conn.execute(
            text(
                "SELECT celery_task_id FROM ingestion_jobs "
                "WHERE batch_job_id = :batch_id AND workspace_id = :ws "
                "AND status NOT IN ('completed', 'failed', 'cancelled')"
            ),
            {"batch_id": batch_id, "ws": workspace_id},
        )
        rows = cursor.fetchall()

        from celery_app import celery

        for row in rows:
            r = dict(row) if not isinstance(row, dict) else row
            task_id = r.get("celery_task_id", "")
            if task_id:
                celery.control.revoke(task_id, terminate=True)

        # Cancel all pending jobs in the batch
        conn.execute(
            text(
                "UPDATE ingestion_jobs SET status = 'cancelled', updated_at = now() "
                "WHERE batch_job_id = :batch_id AND workspace_id = :ws "
                "AND status NOT IN ('completed', 'failed', 'cancelled')"
            ),
            {"batch_id": batch_id, "ws": workspace_id},
        )
        conn.commit()
    except Exception:
        logger.warning("Failed to revoke tasks for batch %d", batch_id, exc_info=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@bp.route("/batch-reanalyze", methods=["POST"])
def batch_reanalyze():
    """Create a batch reprocessing job.

    Inserts a ``batch_jobs`` row and dispatches the ``dispatch_batch``
    Celery task.

    Returns:
        202 with ``{"batch_job_id": N}``
    """
    conn = get_pg_connection()

    # Insert batch_jobs row
    cursor = conn.execute(
        text(
            "INSERT INTO batch_jobs (workspace_id, status) "
            "VALUES (:ws, 'pending') RETURNING id"
        ),
        {"ws": g.workspace_id},
    )
    row = cursor.fetchone()
    batch_id = dict(row)["id"] if not isinstance(row, dict) else row["id"]
    conn.commit()

    # Dispatch Celery task
    _dispatch_batch_task(batch_id, g.workspace_id)

    return jsonify({"batch_job_id": batch_id}), 202


@bp.route("/batch-jobs", methods=["GET"])
def list_batch_jobs():
    """List batch jobs for the current workspace.

    Returns:
        200 with ``{"batches": [...]}``
    """
    conn = get_pg_connection()
    cursor = conn.execute(
        text(
            "SELECT * FROM batch_jobs "
            "WHERE workspace_id = :ws "
            "ORDER BY created_at DESC "
            "LIMIT 50"
        ),
        {"ws": g.workspace_id},
    )
    rows = cursor.fetchall()
    batches = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return jsonify({"batches": batches}), 200


@bp.route("/batch-jobs/<int:batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id: int):
    """Cancel a batch job and revoke its pending tasks.

    Returns:
        200 with ``{"cancelled": true}``
        404 if batch not found or wrong workspace.
    """
    conn = get_pg_connection()

    # Check batch exists and belongs to workspace
    cursor = conn.execute(
        text(
            "SELECT * FROM batch_jobs "
            "WHERE id = :id AND workspace_id = :ws"
        ),
        {"id": batch_id, "ws": g.workspace_id},
    )
    batch = cursor.fetchone()

    if batch is None:
        return jsonify({"error": "Batch job not found"}), 404

    # Revoke pending Celery tasks
    _revoke_batch_tasks(batch_id, g.workspace_id)

    # Update batch status
    conn.execute(
        text(
            "UPDATE batch_jobs SET status = 'cancelled', updated_at = now() "
            "WHERE id = :id AND workspace_id = :ws"
        ),
        {"id": batch_id, "ws": g.workspace_id},
    )
    conn.commit()

    return jsonify({"cancelled": True}), 200
