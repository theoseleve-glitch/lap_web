"""
routes/ingest.py
----------------
Flask blueprint for streaming ingestion progress (SSE + polling).

Endpoints
~~~~~~~~~
- ``GET /api/ingest/<job_id>/status``  -- JSON polling endpoint
- ``GET /api/ingest/<job_id>/stream``  -- Server-Sent Events stream
- ``GET /api/ingest/jobs``             -- list active/recent ingestion jobs

All endpoints are gated behind INGEST_V2.  When the flag is OFF, every
endpoint returns 404 with a JSON error.

Job state is persisted to the ``ingestion_jobs`` SQLite table (v12 schema)
with an in-memory cache for fast SSE polling (dual-write pattern).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

from flask import Blueprint, Response, jsonify
from web.api_utils import api_error, api_response, ErrorCode

logger = logging.getLogger(__name__)

bp = Blueprint("ingest", __name__, url_prefix="/api/ingest")

# Safety cap on SSE iterations (prevent indefinite hang if job state is stuck)
_SSE_MAX_ITERATIONS = 7200  # 7200 * 0.5s = 1 hour max


def _check_flag():
    """Return error response if INGEST_V2 is not enabled."""
    try:
        from ingest.config import INGEST_V2
        if not INGEST_V2:
            return api_error(ErrorCode.NOT_FOUND, "INGEST_V2 feature flag is not enabled", status=404)
    except ImportError:
        return api_error(ErrorCode.NOT_FOUND, "ingest module not available", status=404)
    return None


# ---------------------------------------------------------------------------
# JobStore — dual-write: in-memory cache + SQLite persistence
# ---------------------------------------------------------------------------

class JobStore:
    """Persistent job state backed by the ``ingestion_jobs`` SQLite table.

    In-memory dict provides sub-millisecond reads for the SSE polling loop.
    SQLite provides durability across Flask restarts.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._db_available: Optional[bool] = None

    def _get_conn(self):
        """Lazy import to avoid circular imports at module load time."""
        try:
            from web.db import get_db_connection
            conn = get_db_connection()
            self._db_available = True
            return conn
        except Exception:
            self._db_available = False
            return None

    def _persist_register(self, job: dict) -> None:
        """INSERT a new row into the ingestion_jobs table."""
        conn = self._get_conn()
        if conn is None:
            return
        try:
            conn.execute(
                "INSERT OR IGNORE INTO ingestion_jobs "
                "(job_id, file_path, file_size, sha256_partial, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    job["job_id"],
                    job.get("file_path", ""),
                    job.get("file_size", 0),
                    job.get("sha256_partial", ""),
                    job.get("status", "pending"),
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("JobStore persist_register failed (non-fatal): %s", exc)

    def _persist_update(self, job_id: str, **fields) -> None:
        """UPDATE specific columns for a job row."""
        conn = self._get_conn()
        if conn is None:
            return
        set_clauses = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [job_id]
        try:
            conn.execute(
                f"UPDATE ingestion_jobs SET {set_clauses} WHERE job_id=?",
                values,
            )
            conn.commit()
        except Exception as exc:
            logger.debug("JobStore persist_update failed (non-fatal): %s", exc)

    def register(self, job_id: str, file_path: str, file_size: int,
                 sha256_partial: str = "") -> None:
        """Register a new ingestion job."""
        job = {
            "job_id": job_id,
            "file_path": file_path,
            "file_name": os.path.basename(file_path),
            "file_size": file_size,
            "sha256_partial": sha256_partial,
            "status": "pending",
            "progress": None,
            "started_at": time.time(),
        }
        self._cache[job_id] = job
        self._persist_register(job)

    def update_progress(self, job_id: str, progress_dict: dict) -> None:
        """Update the progress snapshot for a job."""
        job = self._cache.get(job_id)
        if job:
            job["progress"] = progress_dict
            job["status"] = progress_dict.get("phase", job["status"])
        # Periodic SQLite update (every 10th call to avoid write amplification)
        n_rows = progress_dict.get("rows_read", 0)
        n_chunks = progress_dict.get("chunks_flushed", 0)
        status = progress_dict.get("phase", "reading")
        if n_chunks % 10 == 0 or status in ("merging", "complete", "failed"):
            self._persist_update(
                job_id,
                n_rows_loaded=n_rows,
                n_chunks=n_chunks,
                status=status,
            )

    def complete(self, job_id: str, *, error: str | None = None,
                 peak_rss_mb: float = 0, throughput_mb_s: float = 0) -> None:
        """Mark a job as complete or failed."""
        job = self._cache.get(job_id)
        if job:
            job["status"] = "failed" if error else "complete"
            job["completed_at"] = time.time()
            job["elapsed_s"] = round(time.time() - job["started_at"], 2)
            if error:
                job["error"] = error

        status = "failed" if error else "complete"
        elapsed = job.get("elapsed_s", 0) if job else 0
        fields: dict[str, Any] = {
            "status": status,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_s": elapsed,
        }
        if error:
            fields["error_message"] = error
        self._persist_update(job_id, **fields)

    def get(self, job_id: str) -> Optional[dict]:
        """Get a job by ID (memory cache first, then SQLite fallback)."""
        if job_id in self._cache:
            return self._cache[job_id]
        # SQLite fallback for jobs from a previous Flask session
        conn = self._get_conn()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT job_id, file_path, file_size, status, started_at, "
                "elapsed_s, error_message FROM ingestion_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row:
                job = dict(row)
                job["file_name"] = os.path.basename(job.get("file_path", ""))
                job["started_at"] = job.get("started_at", time.time())
                self._cache[job_id] = job
                return job
        except Exception:
            pass
        return None

    def list_recent(self, limit: int = 50) -> list[dict]:
        """List recent jobs (memory cache for active, SQLite for historical)."""
        # Active jobs from cache
        active = [
            {
                "job_id": j["job_id"],
                "file_name": j.get("file_name", os.path.basename(j.get("file_path", ""))),
                "status": j["status"],
                "elapsed_s": round(time.time() - j["started_at"], 2)
                if isinstance(j.get("started_at"), (int, float))
                else j.get("elapsed_s", 0),
            }
            for j in self._cache.values()
        ]
        # If we have enough from cache, return immediately
        if len(active) >= limit:
            return active[:limit]

        # Supplement with historical jobs from SQLite
        conn = self._get_conn()
        if conn is None:
            return active
        try:
            rows = conn.execute(
                "SELECT job_id, file_path, status, elapsed_s "
                "FROM ingestion_jobs "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            cached_ids = {j["job_id"] for j in active}
            for row in rows:
                d = dict(row)
                if d["job_id"] not in cached_ids:
                    d["file_name"] = os.path.basename(d.get("file_path", ""))
                    active.append(d)
        except Exception:
            pass
        return active[:limit]


# Module-level store instance
_store = JobStore()


# -- Public helpers (called by pipeline code) --------------------------

def register_job(job_id: str, file_path: str, file_size: int,
                 sha256_partial: str = "") -> None:
    """Register a new ingestion job for progress tracking."""
    _store.register(job_id, file_path, file_size, sha256_partial)


def update_job_progress(job_id: str, progress_dict: dict) -> None:
    """Update the progress snapshot for a job."""
    _store.update_progress(job_id, progress_dict)


def complete_job(job_id: str, *, error: str | None = None) -> None:
    """Mark a job as complete or failed."""
    _store.complete(job_id, error=error)


# -- Routes -----------------------------------------------------------

@bp.route("/jobs", methods=["GET"])
def list_jobs():
    """List all active and recent ingestion jobs."""
    err = _check_flag()
    if err:
        return err
    return api_response({"jobs": _store.list_recent()})


@bp.route("/<job_id>/status", methods=["GET"])
def get_status(job_id: str):
    """Polling endpoint: return current progress snapshot as JSON."""
    err = _check_flag()
    if err:
        return err
    job = _store.get(job_id)
    if not job:
        return api_error(ErrorCode.NOT_FOUND, f"Job {job_id} not found", status=404)
    elapsed = (
        round(time.time() - job["started_at"], 2)
        if isinstance(job.get("started_at"), (int, float))
        else job.get("elapsed_s", 0)
    )
    return api_response({
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job.get("progress"),
        "elapsed_s": elapsed,
    })


@bp.route("/<job_id>/stream", methods=["GET"])
def stream_progress(job_id: str):
    """SSE endpoint: stream progress events until complete/failed."""
    err = _check_flag()
    if err:
        return err
    job = _store.get(job_id)
    if not job:
        return api_error(ErrorCode.NOT_FOUND, f"Job {job_id} not found", status=404)

    def _generate():
        iterations = 0
        while iterations < _SSE_MAX_ITERATIONS:
            iterations += 1
            j = _store.get(job_id)
            if not j:
                yield f"data: {json.dumps({'error': 'job disappeared'})}\n\n"
                break
            elapsed = (
                round(time.time() - j["started_at"], 2)
                if isinstance(j.get("started_at"), (int, float))
                else j.get("elapsed_s", 0)
            )
            payload = {
                "status": j["status"],
                "progress": j.get("progress"),
                "elapsed_s": elapsed,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if j["status"] in ("complete", "failed"):
                break
            time.sleep(0.5)

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
