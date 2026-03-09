"""
batch_analysis.py
-----------------
Batch re-analysis: re-run the analysis pipeline on multiple sessions.

Public API
~~~~~~~~~~
``batch_reanalyze(session_ids, conn, settings)``
    Loop over sessions, call ``run_full_analysis()``, return summary.

Design principles
~~~~~~~~~~~~~~~~~
- Graceful failure: one session's failure does not stop the batch.
- Returns structured results for each session.
- Thread-safe: each analysis uses its own transaction.
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Job tracking ─────────────────────────────────────────────

_active_jobs: dict[str, dict[str, Any]] = {}


def _make_job_id() -> str:
    return str(uuid.uuid4())[:8]


# ── Batch re-analysis ────────────────────────────────────────

def batch_reanalyze(
    session_ids: list[str],
    conn: Any,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Re-analyze multiple sessions in sequence.

    Parameters
    ----------
    session_ids : list[str]
        Session IDs to re-analyze.
    conn : sqlite3.Connection
        Database connection.
    settings : dict, optional
        Override settings for the pipeline (e.g., session_type, track_state).

    Returns
    -------
    dict with keys:
        job_id, total, completed, failed, results, elapsed_s
    """
    if not session_ids:
        return {
            "job_id": _make_job_id(),
            "total": 0,
            "completed": 0,
            "failed": 0,
            "results": [],
            "elapsed_s": 0.0,
        }

    settings = settings or {}
    job_id = _make_job_id()
    start_time = time.time()

    job = {
        "job_id": job_id,
        "total": len(session_ids),
        "completed": 0,
        "failed": 0,
        "status": "running",
        "results": [],
        "started_at": time.time(),
    }
    _active_jobs[job_id] = job

    for i, session_id in enumerate(session_ids):
        result = _reanalyze_single(session_id, conn, settings)
        job["results"].append(result)

        if result["success"]:
            job["completed"] += 1
        else:
            job["failed"] += 1

        logger.info(
            "Batch [%d/%d] session %s: %s (%.1fs)",
            i + 1, len(session_ids), session_id,
            "OK" if result["success"] else "FAIL",
            result.get("elapsed_s", 0),
        )

    elapsed = time.time() - start_time
    job["status"] = "completed"
    job["elapsed_s"] = round(elapsed, 2)

    logger.info(
        "Batch complete: %d/%d succeeded, %d failed, %.1fs total",
        job["completed"], job["total"], job["failed"], elapsed,
    )

    return {
        "job_id": job_id,
        "total": job["total"],
        "completed": job["completed"],
        "failed": job["failed"],
        "results": job["results"],
        "elapsed_s": round(elapsed, 2),
    }


def _reanalyze_single(
    session_id: str,
    conn: Any,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Re-analyze a single session. Returns result dict."""
    start = time.time()

    try:
        # Look up session metadata from DB
        row = conn.execute(
            "SELECT csv_filename, session_type, track_state, driver_id "
            "FROM sessions WHERE session_id = :sid",
            {"sid": session_id},
        ).fetchone()

        if not row:
            return {
                "session_id": session_id,
                "success": False,
                "error": "Session not found in database",
                "elapsed_s": round(time.time() - start, 2),
            }

        csv_path = row["csv_filename"]
        session_type = settings.get("session_type", row["session_type"] or "practice")
        track_state = settings.get("track_state", row["track_state"] or "dry")

        # Attempt to import and run the pipeline
        try:
            from pipeline import run_full_analysis
        except ImportError:
            return {
                "session_id": session_id,
                "success": False,
                "error": "Could not import pipeline module",
                "elapsed_s": round(time.time() - start, 2),
            }

        from pathlib import Path
        csv_file = Path(csv_path)
        if not csv_file.exists():
            # Try relative to data/raw/
            from path_manager import get_raw_data_dir
            csv_file = get_raw_data_dir() / csv_file.name
            if not csv_file.exists():
                return {
                    "session_id": session_id,
                    "success": False,
                    "error": f"CSV file not found: {csv_path}",
                    "elapsed_s": round(time.time() - start, 2),
                }

        # Build session_meta dict for the pipeline
        session_meta = {
            "session_type": session_type,
            "track_state": track_state,
        }

        # Optional overrides
        if "driver_name" in settings:
            session_meta["driver_name"] = settings["driver_name"]
        elif row["driver_id"]:
            session_meta["driver_name"] = row["driver_id"]
        if "track_name" in settings:
            session_meta["track_name"] = settings["track_name"]

        # Run analysis
        summary = run_full_analysis(csv_path=str(csv_file), session_meta=session_meta)

        elapsed = round(time.time() - start, 2)

        # Extract key results
        score = summary.get("score_result", {})
        return {
            "session_id": session_id,
            "success": True,
            "total_score": score.get("total_score"),
            "grade": score.get("grade"),
            "n_laps": summary.get("n_valid_laps", 0),
            "elapsed_s": elapsed,
        }

    except Exception as exc:
        logger.error(
            "Batch reanalyze failed for %s: %s",
            session_id, exc, exc_info=True,
        )
        return {
            "session_id": session_id,
            "success": False,
            "error": str(exc),
            "elapsed_s": round(time.time() - start, 2),
        }


def get_job_status(job_id: str) -> Optional[dict[str, Any]]:
    """Get the status of a batch job."""
    job = _active_jobs.get(job_id)
    if not job:
        return None
    return {
        "job_id": job["job_id"],
        "total": job["total"],
        "completed": job["completed"],
        "failed": job["failed"],
        "status": job["status"],
        "elapsed_s": round(time.time() - job["started_at"], 2),
    }


# ── Inline tests ────────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite."""
    import traceback as tb

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, tb.format_exc()))

    # Test 1: empty batch
    def t_empty():
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        result = batch_reanalyze([], conn)
        assert result["total"] == 0
        assert result["completed"] == 0
        assert result["failed"] == 0
        conn.close()

    _test("empty_batch", t_empty)

    # Test 2: non-existent sessions
    def t_missing():
        import sqlite3

        from db.migrate import ensure_schema
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        result = batch_reanalyze(["nonexistent_1", "nonexistent_2"], conn)
        assert result["total"] == 2
        assert result["failed"] == 2
        assert result["completed"] == 0
        conn.close()

    _test("missing_sessions", t_missing)

    # Test 3: job status (non-empty batch stores job)
    def t_job_status():
        import sqlite3

        from db.migrate import ensure_schema
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        # Use non-empty batch (sessions won't exist, but job tracking works)
        result = batch_reanalyze(["fake_session"], conn)
        status = get_job_status(result["job_id"])
        assert status is not None
        assert status["status"] == "completed"
        conn.close()

    _test("job_status", t_job_status)

    # Test 4: job not found
    def t_job_missing():
        status = get_job_status("nonexistent")
        assert status is None

    _test("job_not_found", t_job_missing)

    total = len(passed) + len(failed)
    status_str = "PASS" if not failed else "FAIL"
    print(f"\nBatch Analysis Tests: {len(passed)}/{total} passed [{status_str}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
