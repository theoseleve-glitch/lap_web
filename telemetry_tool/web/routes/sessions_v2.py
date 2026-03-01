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
import math
import shutil
import tempfile
from pathlib import Path

from flask import Blueprint, request

from pipeline import run_full_analysis
from web.api_utils import api_error, api_response, ErrorCode
from web.db import get_db_connection
from web.models import (
    insert_analysis_json,
    insert_condition_phases,
    insert_corner_metrics,
    insert_driving_style_features,
    insert_driver_progression,
    insert_gps_traces,
    insert_laps,
    insert_reference_line,
    insert_score_details,
    insert_stint_analysis,
    insert_theoretical_data,
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


def _persist_driver_progression(conn, driver_id, session_id, summary,
                                driving_style):
    """Compute and persist a driver progression snapshot."""
    import numpy as np

    lap_times = summary.get("lap_times") or []
    valid_lt = [t for t in lap_times
                if t and isinstance(t, (int, float))
                and math.isfinite(t) and t > 0]
    n_laps = len(valid_lt)
    best_s = min(valid_lt) if valid_lt else None
    mean_s = sum(valid_lt) / n_laps if n_laps > 0 else None

    # Pace delta: best - theoretical (positive = slower)
    pace_delta = None
    theo_metrics = summary.get("theoretical_metrics") or {}
    if best_s and theo_metrics:
        theo_t = theo_metrics.get("theoretical_time_s")
        if theo_t and isinstance(theo_t, (int, float)):
            pace_delta = best_s - theo_t

    # Consistency: CV% of valid lap times
    cv_pct = None
    if n_laps >= 3 and mean_s:
        std = float(np.std(valid_lt))
        cv_pct = (std / mean_s * 100.0)

    # Style indices from driving_style
    aggression = None
    smoothness = None
    if driving_style:
        feat = driving_style.get("features", {})
        aggression = feat.get("turn_in_aggressiveness")
        smoothness = feat.get("smoothness_composite")

    total_score = None
    score_result = summary.get("score_result")
    if score_result:
        total_score = score_result.get("total_score")

    prog_data = {
        "session_date": session_id[:10],
        "track_id":     summary.get("track_id"),
        "pace_delta_s": pace_delta,
        "consistency_cv_pct": cv_pct,
        "aggression_index":   aggression,
        "smoothness_index":   smoothness,
        "total_score":        total_score,
        "n_laps":             n_laps,
    }
    insert_driver_progression(conn, driver_id, session_id, prog_data)
    logger.info("Persisted driver progression for session %s", session_id)


def _compute_sector_analysis(summary: dict) -> dict | None:
    """Extract valid lap times from summary and run sector analysis."""
    try:
        from sector_analysis import analyze_sector_performance
    except ImportError:
        return None

    lap_times = summary.get("lap_times") or []
    valid = [t for t in lap_times
             if t and isinstance(t, (int, float)) and math.isfinite(t) and t > 0]
    if len(valid) < 3:
        return None

    result = analyze_sector_performance(valid)
    return result.to_dict()


def _persist_analysis_json(conn, session_id: str, summary: dict) -> None:
    """Build and persist the supplementary analysis_json blob."""
    blob: dict = {}

    # Sector analysis (computed fresh from lap times)
    sector = _compute_sector_analysis(summary)
    if sector:
        blob["sector_analysis"] = sector

    # Consistency metrics (from score_result)
    score_result = summary.get("score_result") or {}
    details = score_result.get("details") or {}
    if details.get("consistency"):
        cons = details["consistency"]
        blob["consistency_metrics"] = {
            "cv_pct": cons.get("cv_pct"),
            "std_dev_s": cons.get("std_dev_s"),
            "best_to_median_delta_s": cons.get("best_to_median_delta_s"),
        }

    # Robustness metrics
    if details.get("robustness"):
        rob = details["robustness"]
        blob["robustness_metrics"] = {
            "early_mean_s": rob.get("early_mean_s"),
            "late_mean_s": rob.get("late_mean_s"),
        }

    # Data quality summary
    dq = summary.get("data_quality")
    if dq and isinstance(dq, dict):
        blob["data_quality_summary"] = dq

    # Track evolution / grip evolution
    te = summary.get("track_evolution")
    if te and isinstance(te, dict):
        blob["track_evolution"] = te

    # Coaching guide / summary
    coaching = summary.get("coaching_guide") or summary.get("coaching_summary")
    if coaching and isinstance(coaching, str):
        blob["coaching_summary"] = coaching

    # Corner performances (aggregated from corner_metrics in pipeline)
    cp = summary.get("corner_performances")
    if cp and isinstance(cp, list):
        blob["corner_performances"] = cp

    if blob:
        insert_analysis_json(conn, session_id, blob)
        logger.info("Persisted analysis_json (%d keys) for session %s",
                     len(blob), session_id)


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
            "source_filename": safe_name,
            "display_name": Path(safe_name).stem,
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

        # Extract telemetry start time for session_date derivation
        _ctx = summary.get("session_context")
        if _ctx and hasattr(_ctx, "start_time") and _ctx.start_time:
            summary["telemetry_start_time"] = str(_ctx.start_time)
        elif summary.get("session_meta", {}).get("start_time"):
            summary["telemetry_start_time"] = str(summary["session_meta"]["start_time"])

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

        # ── Persist analysis outputs (defensive — each independent) ──
        try:
            insert_condition_phases(conn, session_id, summary)
        except Exception as e:
            logger.warning("Condition phases persist skipped: %s", e)

        try:
            insert_theoretical_data(conn, session_id, summary)
            logger.info("Persisted theoretical data for session %s", session_id)
        except Exception as e:
            logger.warning("Theoretical data persist failed: %s", e,
                           exc_info=True)

        try:
            insert_reference_line(conn, session_id, summary)
            logger.info("Persisted reference line for session %s", session_id)
        except Exception as e:
            logger.warning("Reference line persist failed: %s", e,
                           exc_info=True)

        try:
            cm_count = insert_corner_metrics(conn, session_id, summary)
            if cm_count > 0:
                logger.info("Persisted %d corner metrics for session %s",
                            cm_count, session_id)
        except Exception as e:
            logger.warning("Corner metrics persist skipped: %s", e)

        # Driving style features
        driving_style = summary.get("driving_style")
        if driving_style:
            try:
                insert_driving_style_features(
                    conn, driver_id, session_id, driving_style,
                )
                logger.info("Persisted driving style: %s",
                            driving_style.get("style_label"))
            except Exception as e:
                logger.warning("Driving style persist skipped: %s", e)

        # Driver progression snapshot
        try:
            _persist_driver_progression(
                conn, driver_id, session_id, summary, driving_style,
            )
        except Exception as e:
            logger.warning("Driver progression persist skipped: %s", e)

        # Stint analysis (from pipeline summary)
        try:
            insert_stint_analysis(conn, session_id, summary)
        except Exception as e:
            logger.warning("Stint analysis persist skipped: %s", e)

        # ── Supplementary analysis blob (analysis_json) ──
        try:
            _persist_analysis_json(conn, session_id, summary)
        except Exception as e:
            logger.warning("analysis_json persist skipped: %s", e)

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
