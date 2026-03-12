"""PG-based job registry — replaces the in-memory JobStore.

Provides CRUD operations for ``ingestion_jobs`` rows scoped by
workspace_id.  All functions accept a DB connection as the first
argument so callers control the transaction boundary.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Statuses that represent a finished job (no further transitions allowed).
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _revoke_celery_task(celery_task_id: str) -> None:
    """Best-effort revoke of a Celery task by its ID."""
    if not celery_task_id:
        return
    try:
        from celery_app import celery

        celery.control.revoke(celery_task_id, terminate=True)
        logger.info("Revoked Celery task %s", celery_task_id)
    except Exception:
        logger.warning("Failed to revoke Celery task %s", celery_task_id, exc_info=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_job(
    conn,
    job_id: str,
    workspace_id: int,
    file_path: str,
    file_size: int,
    celery_task_id: str = "",
    batch_job_id: Optional[int] = None,
) -> None:
    """Insert a new row into ``ingestion_jobs``.

    Parameters
    ----------
    conn :
        Database connection (PgConnectionWrapper or similar).
    job_id : str
        Unique job identifier (UUID).
    workspace_id : int
        Workspace that owns this job.
    file_path : str
        Path to the source CSV file.
    file_size : int
        File size in bytes.
    celery_task_id : str
        Celery AsyncResult ID (may be empty until dispatched).
    batch_job_id : int | None
        Optional parent batch job ID.
    """
    conn.execute(
        text(
            "INSERT INTO ingestion_jobs "
            "  (job_id, workspace_id, file_path, file_size, sha256_partial, "
            "   celery_task_id, batch_job_id, status) "
            "VALUES "
            "  (:job_id, :workspace_id, :file_path, :file_size, :sha256_partial, "
            "   :celery_task_id, :batch_job_id, 'pending')"
        ),
        {
            "job_id": job_id,
            "workspace_id": workspace_id,
            "file_path": file_path,
            "file_size": file_size,
            "sha256_partial": "",
            "celery_task_id": celery_task_id,
            "batch_job_id": batch_job_id,
        },
    )
    conn.commit()


def get_job(conn, job_id: str, workspace_id: int) -> Optional[dict]:
    """Fetch a single job by ``job_id`` AND ``workspace_id``.

    Returns a dict with job fields or ``None`` if not found (or wrong
    workspace).
    """
    cursor = conn.execute(
        text(
            "SELECT * FROM ingestion_jobs "
            "WHERE job_id = :job_id AND workspace_id = :workspace_id"
        ),
        {"job_id": job_id, "workspace_id": workspace_id},
    )
    row = cursor.fetchone()
    if row is None:
        return None
    # row may be a dict-like object (RealDictRow) or a plain dict
    return dict(row) if not isinstance(row, dict) else row


def list_jobs(conn, workspace_id: int, limit: int = 50) -> list[dict]:
    """List jobs for a workspace, newest first.

    Parameters
    ----------
    conn :
        Database connection.
    workspace_id : int
        Workspace scope.
    limit : int
        Maximum number of rows to return (default 50).

    Returns
    -------
    list[dict]
    """
    cursor = conn.execute(
        text(
            "SELECT * FROM ingestion_jobs "
            "WHERE workspace_id = :workspace_id "
            "ORDER BY started_at DESC "
            "LIMIT :limit"
        ),
        {"workspace_id": workspace_id, "limit": limit},
    )
    rows = cursor.fetchall()
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


def cancel_job(conn, job_id: str, workspace_id: int) -> bool:
    """Cancel a running/pending job.

    - Looks up the job by ``job_id`` AND ``workspace_id``.
    - Returns ``False`` if not found or already in a terminal status.
    - Revokes the associated Celery task.
    - Sets status to ``'cancelled'``.
    - Returns ``True`` on success.
    """
    cursor = conn.execute(
        text(
            "SELECT * FROM ingestion_jobs "
            "WHERE job_id = :job_id AND workspace_id = :workspace_id"
        ),
        {"job_id": job_id, "workspace_id": workspace_id},
    )
    row = cursor.fetchone()

    if row is None:
        return False

    row_dict = dict(row) if not isinstance(row, dict) else row
    if row_dict.get("status") in _TERMINAL_STATUSES:
        return False

    # Revoke the Celery task (best-effort)
    celery_task_id = row_dict.get("celery_task_id", "")
    _revoke_celery_task(celery_task_id)

    # Update status
    conn.execute(
        text(
            "UPDATE ingestion_jobs SET status = 'cancelled', updated_at = now() "
            "WHERE job_id = :job_id AND workspace_id = :workspace_id"
        ),
        {"job_id": job_id, "workspace_id": workspace_id},
    )
    conn.commit()
    return True
