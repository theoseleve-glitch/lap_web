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
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from flask import Blueprint, Response, g, request

from web.api_utils import ErrorCode, api_error, api_response
from web.db import get_db_connection
from web.storage_quota import get_storage
from web.models import (
    insert_analysis_json,
    insert_condition_phases,
    insert_corner_metrics,
    insert_driver_progression,
    insert_driving_style_features,
    insert_gps_traces,
    insert_laps,
    insert_reference_line,
    insert_score_details,
    insert_stint_analysis,
    insert_theoretical_data,
    upsert_driver,
    upsert_kart_by_name,
    upsert_session,
    upsert_track,
)
from telemetry_tool.adapters.registry import supported_extensions as _supported_extensions
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("sessions_v2", __name__, url_prefix="/api/v1")

# File extensions accepted for upload.
# _STATIC_ALLOWED covers plain-text formats that are always accepted;
# supported_extensions() adds all extensions from registered adapters.
_STATIC_ALLOWED = {".csv", ".txt"}
_ALLOWED_EXTENSIONS = _STATIC_ALLOWED | _supported_extensions()

# ── Tier limits ────────────────────────────────────────────────────────────

_TIER_LIMITS = {
    # No active subscription → cannot upload (0 bytes). Legacy demo/free
    # collapse to locked. (No free tier in the one-membership model.)
    "locked":      {"max_bytes": 0,                  "max_sessions": 0},
    "racer":       {"max_bytes": 2500 * 1024 * 1024, "max_sessions": None},
    "world-class": {"max_bytes": -1,                  "max_sessions": None},
    "world_class": {"max_bytes": -1,                  "max_sessions": None},
    "b2b":         {"max_bytes": -1,                  "max_sessions": None},
}


def _get_conn() -> sqlite3.Connection:
    """Return a DB connection (alias for get_db_connection)."""
    return get_db_connection()


def _check_tier_limits(f: BinaryIO, conn: sqlite3.Connection, workspace_id: str, plan_tier: str) -> str | None:
    """Return error message if a tier limit is exceeded, else None."""
    limits = _TIER_LIMITS.get(plan_tier, _TIER_LIMITS["locked"])
    # File size check
    f.seek(0, 2)
    file_size = f.tell()
    f.seek(0)
    max_bytes = limits["max_bytes"]
    if max_bytes != -1 and file_size > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        return (
            f"File size ({file_size // (1024 * 1024)} MB) exceeds your plan limit "
            f"({max_mb} MB)."
        )
    # Hard resident-storage cap (separate from the monthly upload-VOLUME flow
    # limit below): total on-disk footprint for this workspace, regardless of
    # when it accumulated. storage_quota.get_storage()'s allocation auto-grows
    # and cannot itself serve as a cap; this uses the tier's fixed entitlement.
    from auth.entitlements import PLAN_ENTITLEMENTS
    resident_cap_gb = PLAN_ENTITLEMENTS.get(plan_tier, PLAN_ENTITLEMENTS["locked"]).get(
        "resident_storage_cap_gb", 0
    )
    if resident_cap_gb != -1:
        current = get_storage(conn, int(workspace_id))
        cap_bytes = resident_cap_gb * 1024 * 1024 * 1024
        if current["used_bytes"] + file_size > cap_bytes:
            used_gb = round(current["used_bytes"] / (1024 ** 3), 2)
            return (
                f"Resident storage limit exceeded ({used_gb} GB used / {resident_cap_gb} GB cap). "
                "Delete old sessions or upgrade your plan."
            )
    # Monthly upload volume check (atomic — locks row to prevent race conditions)
    user_id = getattr(g, "current_user_id", None)
    if user_id is not None:
        try:
            from auth.entitlements import check_and_record_quota
            file_size_mb = max(1, file_size // (1024 * 1024))  # at least 1 MB
            allowed, ctx = check_and_record_quota(
                conn, user_id, int(workspace_id), "upload_volume_mb", cost=file_size_mb,
            )
            if not allowed:
                limit_mb = ctx.get("limit", 0)
                used_mb = ctx.get("used", 0)
                return (
                    f"Monthly upload volume exceeded ({used_mb} MB / {limit_mb} MB). "
                    f"Resets {ctx.get('resets_at', 'next month')}."
                )
        except Exception:
            logger.warning("Volume quota check failed — allowing upload", exc_info=True)
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


def _persist_driver_progression(conn: sqlite3.Connection, driver_id: int, session_id: str, summary: dict[str, Any],
                                driving_style: dict[str, Any] | None) -> None:
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


def _compute_sector_analysis(summary: dict[str, Any]) -> dict[str, Any] | None:
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


def _persist_analysis_json(conn: sqlite3.Connection, session_id: str, summary: dict[str, Any]) -> None:
    """Build and persist the supplementary analysis_json blob."""
    blob: dict[str, Any] = {}

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

    # Coaching V2 (evidence-based, confidence-gated)
    cv2 = summary.get("coaching_v2")
    if cv2:
        blob["coaching_v2"] = cv2.to_dict() if hasattr(cv2, "to_dict") else cv2

    # Corner coaching V2 (per-section coaching from user-defined/autonomous corners)
    ccv2 = summary.get("corner_coaching_v2")
    if ccv2 and isinstance(ccv2, list):
        blob["corner_coaching_v2"] = ccv2

    # Driving style
    ds = summary.get("driving_style")
    if ds and isinstance(ds, dict):
        blob["driving_style"] = ds

    # Grip map (distance-binned friction coefficients)
    gm = summary.get("grip_map")
    if gm and isinstance(gm, dict):
        blob["grip_map"] = gm

    # Friction envelope (speed-binned combined G limits)
    fe = summary.get("friction_envelope")
    if fe and isinstance(fe, dict):
        blob["friction_envelope"] = fe

    # Sensor quality + map confidence (RC6, Day-10)
    sq = summary.get("sensor_quality")
    if sq and isinstance(sq, dict):
        blob["sensor_quality"] = sq

    # Conditions (weather-based scalar μ classifier, Day-11)
    cond = summary.get("conditions")
    if cond and isinstance(cond, dict):
        blob["conditions"] = cond

    # Coaching V3 (physics-based corner coaching, drills, narrative)
    cv3 = summary.get("coaching_v3")
    if cv3 and isinstance(cv3, dict):
        blob["coaching_v3"] = cv3

    # Gamification (XP, level, achievements, streak)
    gam = summary.get("gamification")
    if gam and isinstance(gam, dict):
        blob["gamification"] = gam

    # Lap validation analysis (invalid, incomplete, anomalous, deviation)
    for key in ("invalid_lap_analysis", "incomplete_lap_analysis",
                "anomalous_lap_analysis", "line_deviation_analysis"):
        val = summary.get(key)
        if val and isinstance(val, dict):
            serialisable = {}
            for k, v in val.items():
                serialisable[k] = sorted(v) if isinstance(v, set) else v
            blob[key] = serialisable

    if blob:
        insert_analysis_json(conn, session_id, blob)
        logger.info("Persisted analysis_json (%d keys) for session %s",
                     len(blob), session_id)


def _auto_session_title(
    driver: str, session_type: str, session_date: str | None, filename_stem: str
) -> str:
    """Generate a human-readable session title from metadata.

    Examples:
      "Alex Rossi - Practice - 2026-03-09"
      "Alex Rossi - Race"
      "session_2026_03_09" (fallback to filename)
    """
    parts: list[str] = []
    if driver and driver != "Unknown":
        parts.append(driver)
    type_label = session_type.capitalize() if session_type else ""
    if type_label:
        parts.append(type_label)
    if session_date:
        parts.append(session_date[:10])
    if parts:
        return " - ".join(parts)[:200]
    return filename_stem[:200]


@bp.route("/sessions/upload", methods=["POST"])
@rate_limit(tier="upload")
def upload_session() -> tuple[Response, int]:
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
        # Return structured import error for unsupported extensions
        try:
            from import_errors import ImportErrorCode, ImportFailure, make_support_ref
            failure = ImportFailure.from_code(
                ImportErrorCode.UNSUPPORTED_FILE_EXTENSION,
                support_ref=make_support_ref(),
                message_override=f"File type '{ext}' is not supported. Accepted: CSV, TXT, IBT (iRacing), LD/LDX (MoTeC), VBO (VBOX), XRK/DRK (AiM).",
            )
            return api_error(
                ErrorCode.UNSUPPORTED_FORMAT,
                failure.message,
                details=[{"import_error": failure.to_dict()}],
                status=400,
            )
        except ImportError:
            return api_error(
                ErrorCode.UNSUPPORTED_FORMAT,
                f"Unsupported file type '{ext}'. Accepted: CSV, IBT (iRacing), LD/LDX (MoTeC), VBO (VBOX), XRK/DRK.",
                status=400,
            )

    # ── 2. Tier limit check ───────────────────────────────────────
    plan_tier = getattr(g, "plan_tier", "locked")
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

    # ── 3a. Free-disk guard ───────────────────────────────────────
    # Refuse the write if the server volume is nearly full rather than
    # letting f.save() fill the disk and destabilise the host (and every
    # other tenant). The pipeline transiently needs scratch space well
    # beyond the raw size (decode + normalise), so require a 3x headroom
    # with a 256 MiB floor. The check itself must never block an upload,
    # so a stat failure falls through.
    try:
        import shutil as _shutil_guard
        incoming = request.content_length or 0
        free = _shutil_guard.disk_usage(tmp_dir).free
        required = max(incoming * 3, 256 * 1024 * 1024)
        if free < required:
            _shutil_guard.rmtree(tmp_dir, ignore_errors=True)
            logger.error(
                "Upload refused — low disk: free=%d bytes, required=%d bytes",
                free, required,
            )
            return api_error(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Server storage is temporarily full. Please try again shortly.",
                status=507,
            )
    except OSError:
        pass  # disk_usage unsupported on this FS — don't block on the check

    try:
        f.save(str(tmp_path))
        logger.info("Saved upload to temp path: %s (%d bytes)",
                     tmp_path, tmp_path.stat().st_size)

        # ── 3b. Preflight validation (fast, in-request) ───────────
        try:
            from preflight import run_preflight
            preflight_result = run_preflight(str(tmp_path))
            if not preflight_result.ok and preflight_result.failure:
                failure = preflight_result.failure
                logger.info(
                    "Preflight failed: code=%s support_ref=%s file=%s",
                    failure.code, failure.support_ref, f.filename,
                )
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    failure.message,
                    details=[{"import_error": failure.to_dict()}],
                    status=422,
                )
        except ImportError:
            logger.debug("Preflight module not available — skipping")
        except Exception:
            # Preflight is best-effort; don't block upload on preflight bugs
            logger.warning("Preflight validation raised — continuing", exc_info=True)

        # ── 4. Build session metadata ─────────────────────────────
        _VALID_SESSION_TYPES = {"practice", "qualifying", "race", "test", "endurance", "heat", "final"}
        _VALID_TRACK_STATES = {"dry", "wet", "damp", "mixed", "green", "rubbered", "dusty"}

        raw_session_type = request.form.get("session_type", "practice")
        raw_track_state = request.form.get("track_state", "dry")
        raw_driver_name = (request.form.get("driver_name") or "Unknown").strip()[:100]
        _sd = request.form.get("session_date")

        session_meta: dict[str, Any] = {
            "session_type": raw_session_type if raw_session_type in _VALID_SESSION_TYPES else "practice",
            "track_state": raw_track_state if raw_track_state in _VALID_TRACK_STATES else "dry",
            "driver_name": raw_driver_name or "Unknown",
            "source_filename": safe_name,
            "display_name": _auto_session_title(
                raw_driver_name, raw_session_type, _sd, Path(safe_name).stem
            ),
        }
        # Pass user-provided session_date to the pipeline
        if _sd:
            session_meta["session_date"] = _sd[:30]

        # Kart: accept kart_name (upsert → kart_id) or raw kart_id
        kart_name_raw = request.form.get("kart_name")
        if kart_name_raw and kart_name_raw.strip():
            session_meta["kart_id"] = upsert_kart_by_name(
                conn, kart_name_raw.strip()[:100],
            )
        else:
            kart_id_str = request.form.get("kart_id")
            if kart_id_str:
                try:
                    session_meta["kart_id"] = int(kart_id_str)
                except (ValueError, TypeError):
                    pass

        # Track name: stored for post-pipeline override (pipeline auto-detects from GPS)
        track_name_raw = request.form.get("track_name")
        if track_name_raw and track_name_raw.strip():
            session_meta["user_track_name"] = track_name_raw.strip()[:100]

        exclude_laps = _parse_exclude_laps(request.form.get("exclude_laps"))
        if exclude_laps:
            session_meta["exclude_laps"] = exclude_laps

        lap_range = _parse_lap_range(request.form.get("lap_range"))
        if lap_range:
            session_meta["lap_range"] = list(lap_range)

        if request.form.get("joker_enabled") == "1":
            session_meta["joker_enabled"] = True
            joker_lap_raw = request.form.get("joker_lap")
            if joker_lap_raw:
                try:
                    jl = int(joker_lap_raw.strip())
                    if jl >= 1:
                        session_meta["joker_lap_number"] = jl
                except (ValueError, TypeError):
                    pass  # Ignore invalid joker_lap

        # ── 4b. Filter profile + vehicle overrides ──────────────
        filter_profile_name = request.form.get("filter_profile")
        if filter_profile_name:
            session_meta["filter_profile"] = filter_profile_name

        vehicle_overrides: dict[str, Any] = {}
        _mass = request.form.get("mass_kg")
        if _mass is not None:
            try:
                _m = float(_mass)
            except (ValueError, TypeError):
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    f"mass_kg must be a number, got '{_mass}'",
                    status=400,
                )
            if not (30 <= _m <= 2000):
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    f"mass_kg must be between 30 and 2000, got {_m}",
                    status=400,
                )
            vehicle_overrides["mass_kg"] = _m

        _power = request.form.get("power_kw")
        if _power is not None:
            try:
                _p = float(_power)
            except (ValueError, TypeError):
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    f"power_kw must be a number, got '{_power}'",
                    status=400,
                )
            if not (1 <= _p <= 1000):
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    f"power_kw must be between 1 and 1000, got {_p}",
                    status=400,
                )
            vehicle_overrides["power_kw"] = _p

        _drag = request.form.get("drag_model")
        if _drag is not None:
            if _drag not in ("none", "kart", "gt", "touring", "custom"):
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    f"drag_model must be one of: none, kart, gt, touring, custom",
                    status=400,
                )
            vehicle_overrides["drag_model"] = _drag

        if vehicle_overrides:
            session_meta["vehicle_overrides"] = vehicle_overrides

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
        import json as _json

        import redis as _redis

        from pipeline_context import PipelineContext
        from tasks.pipeline_tasks import (
            TIER_TIMEOUTS_S,
            build_pipeline_chain,
            pipeline_queue_for_tier,
        )
        from web.config import Config

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
        # Threaded onto EVERY stage signature inside build_pipeline_chain
        # (not passed to apply_async) so the tier's grace reaches
        # pipeline_analyze/pipeline_finalize too — see TIER_TIMEOUTS_S docs.
        timeout = TIER_TIMEOUTS_S.get(plan_tier, TIER_TIMEOUTS_S["locked"])
        # FIX #5 (HIGH): route tiers whose hard timeout exceeds the shared
        # `pipeline` worker's blanket --time-limit onto the isolated
        # `pipeline_long` queue/worker instead, so a long b2b job can never
        # occupy one of only 2 shared pipeline slots — see
        # tasks.pipeline_tasks.pipeline_queue_for_tier.
        queue = pipeline_queue_for_tier(plan_tier)
        build_pipeline_chain(job_id, soft_time_limit=timeout, queue=queue).apply_async()

        logger.info(
            "Upload accepted: job_id=%s workspace=%s file=%s tier=%s timeout=%ds queue=%s",
            job_id, g.workspace_id, safe_name, plan_tier, timeout, queue,
        )

        return api_response(
            {"job_id": job_id, "status": "pending",
             "message": "Upload accepted. Processing started."},
            status=202,
        )

    except Exception as exc:
        logger.exception("Upload dispatch failed: %s", exc)
        # Clean up temp dir on error — Celery won't run to do it
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        # Try to return a structured error
        try:
            from import_errors import ImportErrorCode, ImportFailure, make_support_ref
            failure = ImportFailure.from_code(
                ImportErrorCode.PIPELINE_INTERNAL_ERROR,
                support_ref=make_support_ref(),
            )
            return api_error(
                ErrorCode.ANALYSIS_FAILED,
                failure.message,
                details=[{"import_error": failure.to_dict()}],
                status=500,
            )
        except ImportError:
            return api_error(
                ErrorCode.ANALYSIS_FAILED,
                "Failed to accept upload. Please try again or contact support.",
                status=500,
            )
