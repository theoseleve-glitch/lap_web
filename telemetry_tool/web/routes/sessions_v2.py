"""
routes/sessions_v2.py
---------------------
Synchronous session upload endpoint.

POST /api/v1/sessions/upload
    Accepts a CSV file upload, runs the full analysis pipeline synchronously,
    persists results to the database, and returns a summary.

This is the Phase 1 re-port endpoint -- no Celery, no async.  The pipeline
runs in the request thread and blocks until complete.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from flask import Blueprint, request

from pipeline import run_full_analysis
from web.api_utils import api_error, api_response, ErrorCode
from web.db import get_db_connection
from web.models import (
    insert_gps_traces,
    insert_laps,
    insert_score_details,
    upsert_driver,
    upsert_session,
    upsert_track,
)

logger = logging.getLogger(__name__)

bp = Blueprint("sessions_v2", __name__, url_prefix="/api/v1")

# File extensions accepted for upload.
_ALLOWED_EXTENSIONS = {".csv", ".txt"}


def _parse_lap_range(raw: str | None) -> tuple[int, int] | None:
    """Parse a lap range string like '3-15' into a (3, 15) tuple."""
    if not raw:
        return None
    parts = raw.strip().split("-", 1)
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0].strip()), int(parts[1].strip()))
    except (ValueError, TypeError):
        return None


def _parse_exclude_laps(raw: str | None) -> list[int] | None:
    """Parse a comma-separated string like '1,2,16' into a list of ints."""
    if not raw:
        return None
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except (ValueError, TypeError):
        return None


@bp.route("/sessions/upload", methods=["POST"])
def upload_session():
    """Upload a CSV telemetry file and run synchronous analysis.

    Form fields
    -----------
    file : FileStorage (required)
        The CSV file to analyse.
    session_type : str
        ``"practice"`` | ``"qualifying"`` | ``"race"`` (default ``"practice"``).
    track_state : str
        ``"dry"`` | ``"wet"`` | ``"damp"`` (default ``"dry"``).
    driver_name : str
        Driver name (default ``"Unknown"``).
    lap_range : str (optional)
        E.g. ``"3-15"`` -- inclusive lap window.
    exclude_laps : str (optional)
        E.g. ``"1,2,16"`` -- comma-separated lap numbers to exclude.

    Returns
    -------
    JSON envelope ``{ok, data, meta}`` where ``data`` contains:
        session_id, grade, total_score, steps_ok, steps_failed
    """
    # ── 1. Validate file ──────────────────────────────────────────
    if "file" not in request.files:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No file provided. Include a 'file' field in the multipart upload.",
            status=400,
        )

    f = request.files["file"]
    if not f or not f.filename:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No file selected. Please attach a CSV file.",
            status=400,
        )

    ext = Path(f.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return api_error(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"Unsupported file type '{ext}'. Only CSV files are accepted.",
            status=400,
        )

    # ── 2. Save to temp directory ─────────────────────────────────
    tmp_dir = tempfile.mkdtemp(prefix="telemetry_upload_")
    # Use the original filename (sanitised) to help pipeline logging.
    safe_name = Path(f.filename).name
    tmp_path = Path(tmp_dir) / safe_name

    try:
        f.save(str(tmp_path))
        logger.info("Saved upload to temp path: %s (%d bytes)",
                     tmp_path, tmp_path.stat().st_size)

        # ── 3. Build session metadata ─────────────────────────────
        session_meta: dict = {
            "session_type": request.form.get("session_type", "practice"),
            "track_state": request.form.get("track_state", "dry"),
            "driver_name": request.form.get("driver_name", "Unknown"),
        }

        exclude_laps = _parse_exclude_laps(request.form.get("exclude_laps"))
        if exclude_laps:
            session_meta["exclude_laps"] = exclude_laps

        lap_range = _parse_lap_range(request.form.get("lap_range"))

        # ── 4. Run pipeline synchronously ─────────────────────────
        summary = run_full_analysis(
            csv_path=str(tmp_path),
            session_meta=session_meta,
            enable_ml=True,
            enable_report=False,  # No HTML/PDF in API mode
            lap_range=lap_range,
        )

        # ── 5. Persist to database ────────────────────────────────
        conn = get_db_connection()
        driver_name = (summary.get("session_meta") or session_meta).get(
            "driver_name", "Unknown"
        )
        driver_id = upsert_driver(conn, driver_name)

        # Ensure track exists before inserting session (FK constraint).
        track_id = summary.get("track_id")
        if track_id:
            track_entry = None
            # Try to get full fingerprint from tracks.json.
            try:
                from track_detection import load_track_database
                for te in load_track_database():
                    if te.get("track_id") == track_id:
                        track_entry = te
                        break
            except Exception:
                pass

            if track_entry is None:
                # Fall back to whatever the pipeline match result provides.
                tm = summary.get("track_match")
                track_entry = {
                    "track_id": track_id,
                    "track_name": (tm or {}).get("track_name", track_id),
                    "fingerprint": {
                        "lap_length_m": (tm or {}).get("lap_length_m", 0.0),
                        "bbox": {},
                        "start_lat": None,
                        "start_lon": None,
                        "sample_count": None,
                        "lap_count": None,
                    },
                }
            upsert_track(conn, track_entry)

        session_id = upsert_session(conn, summary, driver_id)
        insert_laps(conn, session_id, summary)
        insert_score_details(conn, session_id, summary)
        insert_gps_traces(conn, session_id, summary)
        conn.commit()

        logger.info(
            "Upload complete: session_id=%s, steps_ok=%d, steps_failed=%d",
            session_id,
            len(summary.get("steps_ok", [])),
            len(summary.get("steps_failed", [])),
        )

        # ── 6. Build response ─────────────────────────────────────
        score = summary.get("score_result") or {}
        return api_response({
            "session_id": session_id,
            "grade": score.get("grade"),
            "total_score": score.get("total_score"),
            "steps_ok": summary.get("steps_ok", []),
            "steps_failed": summary.get("steps_failed", []),
        })

    except Exception as exc:
        logger.exception("Upload pipeline failed: %s", exc)
        return api_error(
            ErrorCode.ANALYSIS_FAILED,
            "Analysis pipeline failed. Please try again or contact support.",
            status=500,
        )

    finally:
        # ── 7. Cleanup temp files ─────────────────────────────────
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
