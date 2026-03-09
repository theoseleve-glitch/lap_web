"""Batch reprocessing Celery task — dispatches pipeline chains for all sessions.

``dispatch_batch`` looks up a ``batch_jobs`` row, queries workspace sessions,
and creates individual ``ingestion_jobs`` + pipeline chains with staggered
countdowns to avoid overloading the worker pool.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text

from celery_app import celery
from tasks.job_registry import create_job

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_pg_connection():
    """Return a PG connection via the web.db_pg module."""
    from web.db_pg import get_pg_connection

    return get_pg_connection()


def _get_redis():
    """Create a Redis client from the app config."""
    import redis

    from web.config import Config

    return redis.Redis.from_url(Config.REDIS_URL)


def _build_and_dispatch_chain(job_id: str, countdown: int = 0):
    """Build a pipeline chain for the given job_id and apply with countdown."""
    from tasks.pipeline_tasks import build_pipeline_chain

    chain = build_pipeline_chain(job_id)
    chain.apply_async(countdown=countdown)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(name="tasks.batch_tasks.dispatch_batch")
def dispatch_batch(batch_job_id: int, workspace_id: int) -> None:
    """Dispatch pipeline chains for all sessions in a workspace.

    Steps:
    1. Look up the batch_jobs row from PG.
    2. Update batch status to "running".
    3. Query sessions for the workspace.
    4. For each session: create ingestion_jobs row, create PipelineContext,
       dispatch pipeline chain with staggered countdown (i * 2 seconds).
    5. If no sessions, mark batch as "completed".

    Parameters
    ----------
    batch_job_id : int
        The batch_jobs row ID.
    workspace_id : int
        Workspace that owns this batch.
    """
    conn = _get_pg_connection()

    # 1. Look up batch_jobs row
    cursor = conn.execute(
        text("SELECT * FROM batch_jobs WHERE id = :id AND workspace_id = :ws"),
        {"id": batch_job_id, "ws": workspace_id},
    )
    batch = cursor.fetchone()
    if batch is None:
        logger.error("Batch job %d not found for workspace %d", batch_job_id, workspace_id)
        return

    # 2. Update batch status to "running"
    conn.execute(
        text("UPDATE batch_jobs SET status = 'running', updated_at = now() WHERE id = :id"),
        {"id": batch_job_id},
    )
    conn.commit()

    # 3. Query sessions for the workspace
    cursor = conn.execute(
        text(
            "SELECT session_id, file_path, file_size FROM sessions "
            "WHERE workspace_id = :ws ORDER BY session_id"
        ),
        {"ws": workspace_id},
    )
    sessions = cursor.fetchall()

    # 5. If no sessions, mark batch as "completed"
    if not sessions:
        conn.execute(
            text(
                "UPDATE batch_jobs SET status = 'completed', "
                "total_sessions = 0, updated_at = now() WHERE id = :id"
            ),
            {"id": batch_job_id},
        )
        conn.commit()
        logger.info("Batch %d: no sessions found, marked completed", batch_job_id)
        return

    # 4. For each session: create ingestion_jobs row, dispatch pipeline chain
    for i, session_row in enumerate(sessions):
        row = dict(session_row) if not isinstance(session_row, dict) else session_row
        job_id = str(uuid.uuid4())

        # Create ingestion_jobs row
        create_job(
            conn,
            job_id=job_id,
            workspace_id=workspace_id,
            file_path=row.get("file_path", ""),
            file_size=row.get("file_size", 0),
            batch_job_id=batch_job_id,
        )

        # Create PipelineContext
        try:
            redis_client = _get_redis()
            from pipeline_context import PipelineContext

            PipelineContext.create(
                redis_client,
                job_id=job_id,
                workspace_id=str(workspace_id),
                session_id=row["session_id"],
                file_path=row.get("file_path", ""),
            )
        except Exception:
            logger.warning(
                "Batch %d: failed to create PipelineContext for session %s",
                batch_job_id, row["session_id"], exc_info=True,
            )

        # Dispatch pipeline chain with staggered countdown
        _build_and_dispatch_chain(job_id, countdown=i * 2)

    # Update batch total_sessions count
    conn.execute(
        text(
            "UPDATE batch_jobs SET total_sessions = :total, updated_at = now() "
            "WHERE id = :id"
        ),
        {"id": batch_job_id, "total": len(sessions)},
    )
    conn.commit()

    logger.info(
        "Batch %d: dispatched %d pipeline chains for workspace %d",
        batch_job_id, len(sessions), workspace_id,
    )
