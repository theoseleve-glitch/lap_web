"""
routes/sessions_v2.py
---------------------
Async session upload endpoint.

POST /api/v1/sessions/upload
    Accepts a CSV file upload, inserts an ingestion_jobs record, seeds a
    PipelineContext in Redis, dispatches a Celery chain, and immediately
    returns a job_id with HTTP 202.  The caller polls
    GET /api/v1/jobs/<job_id> for progress.

Tier limits enforce per-plan file-size and session-count caps before
the file is accepted.
"""
from __future__ import annotations

import logging
import math
import os
import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, g, request

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
_ALLOWED_EXTENSIONS = {".csv", ".txt", ".ibt", ".ld", ".ldx", ".vbo", ".xrk", ".drk"}

# ── Tier limits ────────────────────────────────────────────────────────────

_TIER_LIMITS = {
    "free":        {"max_bytes": 50 * 1024 * 1024,   "max_sessions": 10},
    "demo":        {"max_bytes": 50 * 1024 * 1024,   "max_sessions": 10},
    "racer":       {"max_bytes": 500 * 1024 * 1024,  "max_sessions": None},
    "world-class": {"max_bytes": 2 * 1024**3,        "max_sessions": None},
    "world_class": {"max_bytes": 2 * 1024**3,        "max_sessions": None},
    "b2b":         {"max_bytes": 12 * 1024**3,        "max_sessions": None},
}
_TIER_TIMEOUTS = {
    "free": 120, "demo": 120,
    "racer": 600,
    "world-class": 1800, "world_class": 1800,
    "b2b": 3600,
}


def _get_conn():
    """Return a DB connection (alias for get_db_connection)."""
    return get_db_connection()


def _check_tier_limits(f, conn, workspace_id, plan_tier: str):
    """Return error message if a tier limit is exceeded, else None."""
    limits = _TIER_LIMITS.get(plan_tier, _TIER_LIMITS["free"])
    # File size check
    f.seek(0, 2)
    file_size = f.tell()
    f.seek(0)
    max_bytes = limits["max_bytes"]
    if file_size > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        return (
            f"File size ({file_size // (1024 * 1024)} MB) exceeds your plan limit "
            f"({max_mb} MB)."
        )
    # Session count check
    max_sessions = limits.get("max_sessions")
    if max_sessions is not None:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM sessions WHERE workspace_id = %(ws)s",
            {"ws": workspace_id},
        ).fetchone()
        count = row["cnt"] if isinstance(row, dict) else row[0] if row else 0
        if count >= max_sessions:
            return f"Session limit reached ({max_sessions}). Upgrade your plan."
    return None


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
        theo_t = theo_metrics.get("best_s")
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

    # Pipeline status — per-step statuses, degradation flags, versioning
    pipeline = summary.get("pipeline")
    if pipeline and isinstance(pipeline, dict):
        blob["pipeline"] = pipeline

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
    """Upload a CSV telemetry file and dispatch async analysis.

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
    HTTP 202 with JSON envelope ``{ok, data}`` where ``data`` contains:
        job_id, status
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
            f"Unsupported file type '{ext}'. Accepted: CSV, IBT (iRacing), LD/LDX (MoTeC), VBO (VBOX), XRK/DRK.",
            status=400,
        )

    # ── 2. Tier limit check ───────────────────────────────────────
    plan_tier = getattr(g, "plan_tier", "free")
    conn = _get_conn()
    limit_err = _check_tier_limits(f, conn, str(g.workspace_id), plan_tier)
    if limit_err:
        return api_error(ErrorCode.QUOTA_EXCEEDED, limit_err, status=402)

    # ── 3. Save to shared upload directory ────────────────────────
    # Use /data/uploads/ (Docker shared volume between API + Celery)
    # when available; fall back to tempfile for local dev.
    _shared_upload_dir = Path(os.environ.get("UPLOAD_DIR", "/data/uploads"))
    if _shared_upload_dir.is_dir():
        tmp_dir = str(
            _shared_upload_dir / f"job_{uuid.uuid4().hex[:12]}"
        )
        Path(tmp_dir).mkdir(parents=True, exist_ok=True)
    else:
        tmp_dir = tempfile.mkdtemp(prefix="telemetry_upload_")
    # Use the original filename (sanitised) to help pipeline logging.
    safe_name = Path(f.filename).name
    tmp_path = Path(tmp_dir) / safe_name

    try:
        f.save(str(tmp_path))
        logger.info("Saved upload to temp path: %s (%d bytes)",
                     tmp_path, tmp_path.stat().st_size)

        # ── 4. Build session metadata ─────────────────────────────
        session_meta: dict = {
            "session_type": request.form.get("session_type", "practice"),
            "track_state": request.form.get("track_state", "dry"),
            "driver_name": request.form.get("driver_name", "Unknown"),
            "source_filename": safe_name,
            "display_name": Path(safe_name).stem,
        }
        # Pass user-provided session_date to the pipeline
        _sd = request.form.get("session_date")
        if _sd:
            session_meta["session_date"] = _sd

        kart_id_str = request.form.get("kart_id")
        if kart_id_str:
            session_meta["kart_id"] = int(kart_id_str)

        exclude_laps = _parse_exclude_laps(request.form.get("exclude_laps"))
        if exclude_laps:
            session_meta["exclude_laps"] = exclude_laps

        lap_range = _parse_lap_range(request.form.get("lap_range"))
        if lap_range:
            session_meta["lap_range"] = list(lap_range)

        # ── 5. Create job record ──────────────────────────────────
        job_id = uuid.uuid4().hex
        conn = _get_conn()
        conn.execute(
            """INSERT INTO ingestion_jobs
               (job_id, workspace_id, file_path, file_size, sha256_partial,
                status, stage_name, stage_index, stage_total, updated_at)
               VALUES (%(job_id)s, %(ws)s, %(fpath)s, %(fsize)s, %(sha)s,
                       'pending', 'Queued', 0, 14, NOW())""",
            {
                "job_id": job_id,
                "ws": str(g.workspace_id),
                "fpath": str(tmp_path),
                "fsize": tmp_path.stat().st_size,
                "sha": "",
            },
        )
        conn.commit()

        # ── 6. Seed pipeline context in Redis ─────────────────────
        from tasks.pipeline_tasks import build_pipeline_chain
        from pipeline_context import PipelineContext
        from web.config import Config
        import redis as _redis
        import json as _json

        _r = _redis.Redis.from_url(Config.REDIS_URL)
        ctx = PipelineContext.create(
            redis_client=_r,
            job_id=job_id,
            workspace_id=str(g.workspace_id),
            session_id=job_id,  # placeholder — worker will create real session_id
            file_path=str(tmp_path),
        )
        # Store session_meta alongside context so the worker can retrieve it.
        _r.set(
            f"pipeline:meta:{job_id}",
            _json.dumps(session_meta),
            ex=7200,
        )

        # ── 7. Dispatch Celery chain ──────────────────────────────
        timeout = _TIER_TIMEOUTS.get(plan_tier, 120)
        build_pipeline_chain(job_id).apply_async(soft_time_limit=timeout)

        logger.info(
            "Upload accepted: job_id=%s workspace=%s file=%s tier=%s timeout=%ds",
            job_id, g.workspace_id, safe_name, plan_tier, timeout,
        )

        return api_response(
            {"job_id": job_id, "status": "pending",
             "message": "Upload accepted. Processing started."},
            status=202,
        )

    except Exception as exc:
        logger.exception("Upload dispatch failed: %s", exc)
        return api_error(
            ErrorCode.ANALYSIS_FAILED,
            "Failed to accept upload. Please try again or contact support.",
            status=500,
        )

    finally:
        pass  # Cleanup handled by Celery finalize task
