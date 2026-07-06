"""Pipeline Celery tasks — three chained groups covering the full pipeline.

Group 1: ``pipeline_ingest``  (stages 1-4)  — CSV read, GPS filter, derived, trim
Group 2: ``pipeline_analyze`` (stages 5-8)  — track detect, corners, resample, features
Group 3: ``pipeline_finalize``(stages 9-15) — ref line, physics, theoretical, ML, scoring, reports

Each task receives a ``job_id``, loads :class:`PipelineContext` from Redis,
runs its stages, saves context, and returns ``job_id`` for the next task
in the chain.

``build_pipeline_chain(job_id)`` returns a Celery chain of all three.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import redis
from celery import chain
from sqlalchemy import text

from celery_app import celery
from pipeline_context import PipelineContext
from pipeline_errors import (
    FatalError,
    InteractionRequired,
    TransientError,
    classify_error,
)
from pipeline_version import PIPELINE_VERSION
from tasks.concurrency import (
    acquire_workspace_lock,
    check_worker_memory,
    release_workspace_lock,
)
from auth.entitlements import get_user_entitlements

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured error helper
# ---------------------------------------------------------------------------


def _make_import_error_json(exc: BaseException) -> str | None:
    """Convert an exception to a structured ImportFailure JSON string.

    Returns None if the import_errors module is unavailable (graceful degradation).
    """
    try:
        import json as _json
        from import_errors import ImportFailure, classify_import_error
        failure = classify_import_error(exc)
        return _json.dumps(failure.to_dict())
    except Exception:
        logger.debug("Could not generate structured import error", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Entitlement guard
# ---------------------------------------------------------------------------


def _resolve_session_owner(conn, session_id, workspace_id) -> tuple[int | None, int | None]:
    """Resolve the owning (workspace_id, owner_user_id) for a session.

    Used when ctx.user_id is absent (reprocess / batch tasks).  Walks:
      session_id → sessions.workspace_id (if workspace_id not already known)
                 → workspaces.owner_user_id

    Returns (resolved_workspace_id, owner_user_id) or (None, None) if
    either lookup fails or the session/workspace row does not exist.
    """
    try:
        ws_id = workspace_id
        if not ws_id and session_id:
            row = conn.execute(
                text("SELECT workspace_id FROM sessions WHERE session_id = :sid"),
                {"sid": session_id},
            ).fetchone()
            if row is None:
                return None, None
            ws_id = row[0] if not isinstance(row, dict) else row.get("workspace_id")

        if not ws_id:
            return None, None

        owner_row = conn.execute(
            text("SELECT owner_user_id FROM workspaces WHERE id = :wsid"),
            {"wsid": ws_id},
        ).fetchone()
        if owner_row is None:
            return ws_id, None
        owner_id = (
            owner_row[0]
            if not isinstance(owner_row, dict)
            else owner_row.get("owner_user_id")
        )
        return ws_id, owner_id
    except Exception:
        logger.warning(
            "Worker entitlement: failed to resolve session owner "
            "(session_id=%s workspace_id=%s)",
            session_id, workspace_id, exc_info=True,
        )
        return None, None


def _verify_task_entitlements(
    user_id: int | None,
    workspace_id: int | None,
    conn=None,
    session_id=None,
) -> bool:
    """Entitlement check for Celery workers — fails CLOSED on any error.

    Behaviour:
    - If user_id is absent, resolves the workspace owner via session_id so
      reprocess/batch tasks are checked against the owning tier.
    - Calls get_user_entitlements() (status-aware since cfe9cbf) and denies
      when analyses_per_month == 0 (the locked floor for any inactive/unpaid
      subscription regardless of plan_tier).
    - On ANY exception during the check, raises TransientError so the Celery
      retry policy can attempt once more on a transient DB blip.  A check
      failure NEVER grants access.
    - Only if the owning workspace/user genuinely cannot be resolved
      (session not found, workspace orphaned) does it deny definitively
      (return False) rather than retrying — those are not transient states.

    Returns True only when the owner has a non-zero analyses entitlement
    (i.e. active/trialing/past_due/canceled subscription + paid tier).
    """
    # Resolve the identity we'll check against.
    resolved_user_id = user_id
    resolved_ws_id = workspace_id

    # Manage connection lifetime: if the caller already owns a connection, use
    # it (avoids a second connection open from the worker pool).  If not, open
    # one ourselves — but we own it, so we must close it when done.
    _owned_conn = False
    if conn is None:
        try:
            conn = _get_pg_connection()
            _owned_conn = True
        except Exception:
            logger.error(
                "Worker entitlement: could not open DB connection "
                "(user=%s workspace=%s) — failing CLOSED",
                user_id, workspace_id, exc_info=True,
            )
            raise TransientError("Entitlement DB connection failed") from None

    try:
        # --- Step 1: resolve owner when user_id is absent -------------------
        if not resolved_user_id:
            resolved_ws_id, resolved_user_id = _resolve_session_owner(
                conn, session_id, workspace_id
            )
            if not resolved_user_id:
                # Session/workspace genuinely unresolvable — not a transient
                # error.  Deny without retry to avoid infinite retry storms on
                # a legitimately missing job.
                logger.warning(
                    "Worker entitlement: could not resolve owner for "
                    "session_id=%s workspace_id=%s — denying",
                    session_id, workspace_id,
                )
                return False

        # --- Step 2: fetch status-aware entitlements ------------------------
        try:
            ents = get_user_entitlements(conn, resolved_user_id, resolved_ws_id)
        except Exception:
            logger.error(
                "Worker entitlement: get_user_entitlements raised "
                "(user=%s workspace=%s) — failing CLOSED",
                resolved_user_id, resolved_ws_id, exc_info=True,
            )
            raise TransientError("Entitlement lookup failed") from None

        # --- Step 3: deny when on the locked floor --------------------------
        # analyses_per_month == 0 is the invariant set by get_user_entitlements
        # for every locked/unpaid/expired/inactive status (cfe9cbf).
        # -1 means unlimited (world_class); any positive value is permitted.
        analyses_allowed = ents.get("analyses_per_month", 0)
        if analyses_allowed == 0:
            logger.warning(
                "Worker entitlement denied: user=%s workspace=%s "
                "tier=%s status=%s analyses_per_month=0",
                resolved_user_id, resolved_ws_id,
                ents.get("plan_tier"), ents.get("subscription_status"),
            )
            return False

        return True

    finally:
        if _owned_conn:
            _return_pg_connection(conn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_redis():
    """Create a Redis client from the app config."""
    from web.config import Config

    return redis.Redis.from_url(Config.REDIS_URL)


def _get_pg_connection():
    """Return a PG connection via the web.db_pg module."""
    from web.db_pg import get_pg_connection

    return get_pg_connection()


def _return_pg_connection(conn) -> None:
    """Close a standalone task connection (no-ops on None / double-close)."""
    if conn is None:
        return
    from web.db_pg import return_pg_connection
    return_pg_connection(conn)


def _open_task_conn(ctx):
    """Open ONE PG connection for a pipeline task and pin the workspace RLS GUC.

    Pipeline tasks touch RLS tables (``ingestion_jobs``, ``sessions``,
    ``workspaces`` …) from their FIRST statement — before
    ``_persist_session_data`` runs. The Celery worker runs with NO Flask app
    context (``celery = make_celery()`` with app=None, so no ``ContextTask``),
    which means ``web.db_pg.get_pg_connection()`` returns a BRAND-NEW
    connection on every call — a ``SET`` on one connection does NOT carry to
    the next. So each task must open a SINGLE connection, ``SET`` the GUC on it
    (connection-scoped, NOT ``SET LOCAL``, so it survives the many independent
    COMMITs across stages), and thread THAT connection through every helper via
    ``conn=``. Under the non-privileged ``telemetry_app`` role a GUC-less
    statement on an RLS-forced table raises ``unrecognized configuration
    parameter`` and fails the task. Caller MUST close the returned connection
    via :func:`_return_pg_connection` in a ``finally``. Mirrors the
    self-contained connection handling in ``_persist_session_data``.
    """
    conn = _get_pg_connection()
    if getattr(ctx, "workspace_id", None):
        try:
            conn.execute(
                "SET app.current_workspace_id = %(ws)s",
                {"ws": str(ctx.workspace_id)},
            )
            conn.commit()
        except Exception:
            # This runs BEFORE the task's try/finally, so close the freshly
            # opened connection ourselves rather than leaking it on a
            # connection-setup hiccup.
            _return_pg_connection(conn)
            raise
    return conn


def _update_job_progress(
    job_id: str,
    status: str,
    stage_name: Optional[str] = None,
    stage_index: Optional[int] = None,
    stage_total: Optional[int] = None,
    error_message: Optional[str] = None,
    error_class: Optional[str] = None,
    pause_reason: Optional[str] = None,
    import_error_json: Optional[str] = None,
    conn=None,
) -> None:
    """Write pipeline progress to the PG ``ingestion_jobs`` table.

    Accepts an optional ``conn`` to reuse an existing PG connection
    instead of opening a new one per call.

    ``import_error_json`` stores a structured ImportFailure dict as JSON
    for rich error rendering on the frontend.
    """
    if conn is None:
        conn = _get_pg_connection()
    conn.execute(
        text(
            "UPDATE ingestion_jobs SET "
            "  status = :status,"
            "  stage_name = :stage_name,"
            "  stage_index = :stage_index,"
            "  stage_total = :stage_total,"
            "  error_message = :error_message,"
            "  error_class = :error_class,"
            "  pause_reason = :pause_reason,"
            "  import_error_json = COALESCE(:import_error_json, import_error_json),"
            "  updated_at = now() "
            "WHERE job_id = :job_id"
        ),
        {
            "job_id": job_id,
            "status": status,
            "stage_name": stage_name,
            "stage_index": stage_index,
            "stage_total": stage_total,
            "error_message": error_message,
            "error_class": error_class,
            "pause_reason": pause_reason,
            "import_error_json": import_error_json,
        },
    )
    conn.commit()


def _make_progress_callback(job_id: str, conn=None):
    """Return a callback compatible with pipeline.run_full_analysis(progress_callback=...)."""
    def _cb(stage_index: int, stage_total: int, stage_name: str, status: str) -> None:
        _update_job_progress(
            job_id,
            status="processing",
            stage_name=stage_name,
            stage_index=stage_index,
            stage_total=stage_total,
            conn=conn,
        )
    return _cb


# ---------------------------------------------------------------------------
# Batch counter helpers
# ---------------------------------------------------------------------------


def _increment_batch_counter(job_id: str, column: str, conn=None) -> None:
    """Increment batch_jobs.completed_sessions or failed_sessions for this job.

    Only acts if the job belongs to a batch (has batch_job_id).
    """
    if conn is None:
        conn = _get_pg_connection()
    try:
        row = conn.execute(
            text("SELECT batch_job_id FROM ingestion_jobs WHERE job_id = :jid"),
            {"jid": job_id},
        ).fetchone()
        if row is None:
            return
        batch_id = row[0] if not isinstance(row, dict) else row.get("batch_job_id")
        if batch_id is None:
            return
        conn.execute(
            text(
                f"UPDATE batch_jobs SET {column} = {column} + 1, "  # noqa: S608
                "updated_at = now() WHERE id = :bid"
            ),
            {"bid": batch_id},
        )
        conn.commit()
    except Exception:
        logger.warning("Failed to increment batch %s for job %s", column, job_id, exc_info=True)


# ---------------------------------------------------------------------------
# Stage runners — ingest/analyze are pass-through (run_full_analysis handles
# everything in a single call during finalize); finalize calls the real pipeline.
# ---------------------------------------------------------------------------

_INGEST_STAGES = ["csv_read", "gps_filter", "derived_channels", "session_trim"]
_ANALYZE_STAGES = ["track_detect", "corner_detect", "resample", "features"]
_FINALIZE_STAGES = [
    "reference_line", "physics_models", "theoretical_lap",
    "ml_anomaly", "scoring", "reports", "cleanup",
]


def _build_session_meta(ctx: PipelineContext, conn=None) -> dict:
    """Build the session_meta dict expected by ``run_full_analysis()``.

    Reads user-provided metadata from Redis ``pipeline:meta:{job_id}``
    (set by the upload endpoint) and merges with context defaults.

    ``conn`` is the task's GUC-pinned connection; it is used for the driver
    experience lookup so that query inherits the workspace RLS context.
    """
    import json as _json

    meta = {
        "session_id": ctx.session_id,
        "session_type": "practice",
        "track_state": "dry",
        "driver_name": "Unknown",
    }

    # Read user-provided metadata from Redis (set by sessions_v2.py upload)
    try:
        r = _get_redis()
        raw = r.get(f"pipeline:meta:{ctx.job_id}")
        if raw:
            user_meta = _json.loads(raw)
            meta.update(user_meta)
    except Exception:
        logger.warning("Failed to read pipeline:meta for job %s", ctx.job_id, exc_info=True)

    # Day-14: Bridge step 05's track_id from the analyze stage so the
    # finalize stage's resume-from-step8 path doesn't fall through to the
    # sentinel default. Paired with the write in _run_analyze_stages.
    try:
        r2 = _get_redis()
        tid_raw = r2.get(f"pipeline:track_id:{ctx.job_id}")
        if tid_raw:
            tid = tid_raw.decode("utf-8") if isinstance(tid_raw, (bytes, bytearray)) else tid_raw
            if tid and tid != "unknown_track":
                meta["track_id"] = tid
    except Exception:
        logger.warning("Failed to read pipeline:track_id for job %s", ctx.job_id, exc_info=True)

    # Ensure session_id is always from context
    meta["session_id"] = ctx.session_id

    # Fetch driver experience (total_laps) for adaptive scoring. MUST use the
    # task's GUC-pinned connection: the worker has no Flask app context, so a
    # fresh get_pg_connection() here would be GUC-less (raising on the RLS
    # drivers/driver_profiles tables under the telemetry_app cutover, swallowed
    # → silent scoring degradation) AND would leak (never closed).
    meta.setdefault("driver_total_laps", 0)
    if conn is not None:
        try:
            _drv_row = conn.execute(
                "SELECT driver_id FROM drivers WHERE driver_name = %(driver_name)s",
                {"driver_name": meta.get("driver_name", "Unknown")},
            ).fetchone()
            if _drv_row:
                _drv_id = _drv_row[0] if not isinstance(_drv_row, dict) else _drv_row.get("driver_id")
                _prof_row = conn.execute(
                    "SELECT total_laps FROM driver_profiles WHERE driver_id = %(driver_id)s",
                    {"driver_id": _drv_id},
                ).fetchone()
                if _prof_row:
                    meta["driver_total_laps"] = int(
                        (_prof_row[0] if not isinstance(_prof_row, dict) else _prof_row.get("total_laps", 0)) or 0
                    )
        except Exception:
            # Graceful fallback (new driver / no profile). Reset the shared conn
            # so a failed read can't leave it in an aborted-transaction state.
            try:
                conn.rollback()
            except Exception:
                pass

    # Track-onboarding GT-miss detection hook (pipeline/stages/s10d_surface.py)
    # needs both of these: job_id doubles as the onboarding request's
    # session_ref (must equal ingestion_jobs.job_id -- see PipelineContext's
    # session_id==job_id convention), and is_operator_run is the gate that
    # keeps ordinary end-user uploads from ever triggering onboarding.
    meta["job_id"] = ctx.job_id
    meta["is_operator_run"] = bool(getattr(ctx, "is_operator_run", False))

    return meta


def _build_analysis_blob(result: dict) -> dict:
    """Build a curated analysis JSON blob from the pipeline result.

    Extracts serialisable metadata (no DataFrames) for the
    ``sessions.analysis_json`` column.
    """
    blob: dict = {}

    # Pipeline status — per-step statuses, degradation flags, versioning
    pipeline = result.get("pipeline")
    if pipeline and isinstance(pipeline, dict):
        blob["pipeline"] = pipeline

    # Consistency metrics from score_result
    score_result = result.get("score_result") or {}
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
    dq = result.get("data_quality")
    if dq and isinstance(dq, dict):
        blob["data_quality_summary"] = dq

    # Track evolution
    te = result.get("track_evolution")
    if te and isinstance(te, dict):
        blob["track_evolution"] = te

    # Coaching summary
    coaching = result.get("coaching_guide") or result.get("coaching_summary")
    if coaching and isinstance(coaching, str):
        blob["coaching_summary"] = coaching

    # Corner performances
    cp = result.get("corner_performances")
    if cp and isinstance(cp, list):
        blob["corner_performances"] = cp

    # Coaching V2 (evidence-based, confidence-gated)
    cv2 = result.get("coaching_v2")
    if cv2:
        blob["coaching_v2"] = cv2.to_dict() if hasattr(cv2, "to_dict") else cv2

    # Corner coaching V2 (per-section coaching from user-defined/autonomous corners)
    ccv2 = result.get("corner_coaching_v2")
    if ccv2 and isinstance(ccv2, list):
        blob["corner_coaching_v2"] = ccv2

    # Driving style
    ds = result.get("driving_style")
    if ds and isinstance(ds, dict):
        blob["driving_style"] = ds

    # Grip map (distance-binned friction coefficients)
    gm = result.get("grip_map")
    if gm and isinstance(gm, dict):
        blob["grip_map"] = gm

    # Friction envelope (speed-binned combined G limits)
    fe = result.get("friction_envelope")
    if fe and isinstance(fe, dict):
        blob["friction_envelope"] = fe

    # Coaching V3 (physics-based corner coaching, drills, narrative)
    cv3 = result.get("coaching_v3")
    if cv3 and isinstance(cv3, dict):
        blob["coaching_v3"] = cv3

    # Gamification (XP, level, achievements, streak)
    gam = result.get("gamification")
    if gam and isinstance(gam, dict):
        blob["gamification"] = gam

    # Lap validation analysis (invalid, incomplete, anomalous, deviation)
    # These are needed by insert_laps() and for the frontend to show status.
    for key in ("invalid_lap_analysis", "incomplete_lap_analysis",
                "anomalous_lap_analysis", "line_deviation_analysis"):
        val = result.get(key)
        if val and isinstance(val, dict):
            # Convert sets to lists for JSON serialisation
            serialisable = {}
            for k, v in val.items():
                serialisable[k] = sorted(v) if isinstance(v, set) else v
            blob[key] = serialisable

    # Day-14 (C): port V2 bug-2 fix (V2 commit bdef6a4c) — conditions +
    # sensor_quality from the orchestrator (steps 10e and 10f) were never
    # copied into the persisted blob on the lap_web celery flow. Without
    # this, the /track-surface route's `analysis.get("conditions")` returns
    # None and ConditionRow has nothing to render. The sync upload path
    # (_persist_analysis_json) already includes these keys; this brings
    # the celery flow to parity.
    sq = result.get("sensor_quality")
    if sq and isinstance(sq, dict):
        blob["sensor_quality"] = sq
    cond = result.get("conditions")
    if cond and isinstance(cond, dict):
        blob["conditions"] = cond

    # Day-15 Stage B Issue 2: same V2-bug-2 shape — track_surface_summary
    # (the JSON-safe TrackSurface.to_summary_dict() output set by
    # orchestrator step 10d) was never copied into the persisted blob.
    # Without this, analysis_json.track_surface_summary.boundary_source is
    # missing — which is the definitive acceptance gate for the
    # hand_traced vs data_derived switch.
    tss = result.get("track_surface_summary")
    if tss and isinstance(tss, dict):
        blob["track_surface_summary"] = tss

    return blob


def _sanitize_for_json(obj):
    """Recursively replace NaN/Inf floats with None for valid JSON."""
    import math as _math
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _store_theoretical_data(session_id: str, result: dict, conn=None) -> None:
    """Persist theoretical lap metrics to the ``theoretical_data`` table.

    Extracts theoretical_time_s, gap_pct, and serialises speed profile,
    distances, metrics, coaching, delta_map, and scalars as JSON.
    Uses ``INSERT ... ON CONFLICT (session_id) DO UPDATE SET ...`` to upsert.
    """
    import json as _json

    theo_metrics = result.get("theoretical_metrics") or {}
    if not theo_metrics:
        return

    if conn is None:
        conn = _get_pg_connection()

    theoretical_time_s = theo_metrics.get("best_s")

    # Compute gap_pct: (actual_best - theoretical) / theoretical * 100
    lap_times = result.get("lap_times") or []
    valid_times = [t for t in lap_times if isinstance(t, (int, float)) and t > 0]
    actual_best = min(valid_times) if valid_times else None
    gap_pct = None
    if theoretical_time_s and actual_best and theoretical_time_s > 0:
        gap_pct = round((actual_best - theoretical_time_s) / theoretical_time_s * 100, 2)

    # Serialise optional fields as JSON (sanitize NaN/Inf → null)
    speed_profile_json = None
    distance_json = None
    theo_lap = result.get("theoretical_lap")
    if theo_lap is not None and hasattr(theo_lap, "columns"):
        for c in theo_lap.columns:
            cl = c.lower()
            if distance_json is None and "distance" in cl:
                distance_json = _json.dumps(_sanitize_for_json(theo_lap[c].tolist()))
            if speed_profile_json is None and ("v_env" in cl or "speed" in cl):
                speed_profile_json = _json.dumps(_sanitize_for_json(theo_lap[c].tolist()))

    metrics_json = _json.dumps(_sanitize_for_json(theo_metrics)) if theo_metrics else None

    corner_coaching = result.get("corner_coaching")
    corner_coaching_json = _json.dumps(_sanitize_for_json(corner_coaching)) if corner_coaching else None

    delta_map = result.get("delta_map")
    delta_map_json = None
    if delta_map is not None and hasattr(delta_map, "to_dict"):
        try:
            delta_map_json = _json.dumps(_sanitize_for_json(delta_map.head(10).to_dict(orient="records")))
        except Exception:
            pass

    session_scalars = result.get("session_scalars")
    session_scalars_json = _json.dumps(_sanitize_for_json(session_scalars)) if session_scalars else None

    conn.execute(
        text(
            "INSERT INTO theoretical_data "
            "  (session_id, theoretical_time_s, actual_best_time_s, gap_pct,"
            "   simulation_method, speed_profile_json, distance_json,"
            "   metrics_json, corner_coaching_json, delta_map_json,"
            "   session_scalars_json) "
            "VALUES "
            "  (:session_id, :theoretical_time_s, :actual_best_time_s, :gap_pct,"
            "   :simulation_method, :speed_profile_json, :distance_json,"
            "   :metrics_json, :corner_coaching_json, :delta_map_json,"
            "   :session_scalars_json) "
            "ON CONFLICT (session_id) DO UPDATE SET "
            "  theoretical_time_s   = EXCLUDED.theoretical_time_s,"
            "  actual_best_time_s   = EXCLUDED.actual_best_time_s,"
            "  gap_pct              = EXCLUDED.gap_pct,"
            "  simulation_method    = EXCLUDED.simulation_method,"
            "  speed_profile_json   = EXCLUDED.speed_profile_json,"
            "  distance_json        = EXCLUDED.distance_json,"
            "  metrics_json         = EXCLUDED.metrics_json,"
            "  corner_coaching_json = EXCLUDED.corner_coaching_json,"
            "  delta_map_json       = EXCLUDED.delta_map_json,"
            "  session_scalars_json = EXCLUDED.session_scalars_json"
        ),
        {
            "session_id": session_id,
            "theoretical_time_s": theoretical_time_s,
            "actual_best_time_s": actual_best,
            "gap_pct": gap_pct,
            "simulation_method": theo_metrics.get("simulation_method"),
            "speed_profile_json": speed_profile_json,
            "distance_json": distance_json,
            "metrics_json": metrics_json,
            "corner_coaching_json": corner_coaching_json,
            "delta_map_json": delta_map_json,
            "session_scalars_json": session_scalars_json,
        },
    )
    conn.commit()
    logger.info("Persisted theoretical data for session %s", session_id)


def _try_store_raw_sidecar(ctx: PipelineContext) -> None:
    """Store raw irsdk__ Parquet sidecar for .ibt uploads.

    When the uploaded file is an iRacing .ibt binary, re-reads it using the
    sim optimizer's ibt_loader to produce the irsdk__-prefixed DataFrame
    and stores it as a Parquet sidecar. This enables the sim optimizer API
    endpoints (/theoretical, /delta, /corners) for the session.

    Best-effort: logs and continues on any failure.
    """
    file_path = ctx.file_path
    if not file_path or not file_path.lower().endswith(".ibt"):
        return

    try:
        from telemetry_tool.sim_optimizer.ingest.ibt_loader import load_ibt
        from web.routes.theoretical import store_raw_sidecar

        raw_df = load_ibt(file_path)
        if raw_df is not None and len(raw_df) > 0:
            session_id = ctx.session_id or ctx.job_id
            store_raw_sidecar(session_id, raw_df)
            logger.info(
                "Stored irsdk__ raw sidecar for session %s (%d rows, %d cols)",
                session_id, len(raw_df), len(raw_df.columns),
            )
    except Exception:
        logger.warning("Failed to store raw sidecar for %s — continuing", file_path, exc_info=True)


def _run_ingest_stages(ctx: PipelineContext) -> None:
    """Pass-through: mark ingest stages 1-4 as completed.

    The real CSV read and processing happens in ``_run_finalize_stages``
    via ``run_full_analysis()`` which orchestrates the entire pipeline
    in a single call.
    """
    for i, stage in enumerate(_INGEST_STAGES):
        ctx.update_stage(stage, "running")
        logger.info("Job %s: stage %s (%d/%d)", ctx.job_id, stage, i + 1, len(_INGEST_STAGES))
        ctx.update_stage(stage, "completed")


def _run_analyze_stages(ctx: PipelineContext, job_id: str | None = None, conn=None) -> dict:
    """Run pipeline stages 1-7 (ingest through corner detection).

    Calls ``run_full_analysis(stop_after_corners=True)`` to get track
    layout and intermediate data, then saves resampled laps to temp dir
    and corners to Redis for the finalize stage to pick up.

    Returns the pipeline result dict (contains track_layout, resampled_laps,
    corners). Returns empty dict if no corners detected (flat track / poor GPS).
    """
    import json as _json

    from pipeline import run_full_analysis

    session_meta = _build_session_meta(ctx, conn=conn)
    _job_id = job_id or ctx.job_id

    result = run_full_analysis(
        csv_path=ctx.file_path,
        session_meta=session_meta,
        enable_report=False,
        progress_callback=_make_progress_callback(_job_id, conn),
        stop_after_corners=True,
        workspace_id=ctx.workspace_id,
        skip_gamification=True,  # _persist_session_data owns SaaS gamification
    )

    resampled_laps = result.get("resampled_laps") or {}
    corners = result.get("corners") or []
    track_layout = result.get("track_layout")
    track_id = result.get("track_id")

    # Persist resampled laps to temp dir (Parquet) for finalize to load
    for lap_num, df in resampled_laps.items():
        ctx.save_dataframe(f"resampled_lap_{lap_num}", df)

    # Persist corners to Redis with 2-hour TTL
    r = _get_redis()
    r.set(
        f"pipeline:corners:{ctx.job_id}",
        _json.dumps(corners),
        ex=7200,
    )

    # Persist track layout to Redis with 2-hour TTL
    if track_layout:
        r.set(
            f"pipeline:layout:{ctx.job_id}",
            _json.dumps(track_layout),
            ex=7200,
        )

    # Day-14: Bridge step 05's track_id across the analyze->finalize boundary.
    # _run_finalize_stages calls run_full_analysis(resume_from_step8=True), which
    # skips step 05 and would otherwise fall back to meta.get("track_id",
    # "unknown_track") -> sentinel. Storing the real UUID here lets
    # _build_session_meta inject it back into meta so the resume path keeps
    # a valid track_id.
    if track_id and track_id != "unknown_track":
        r.set(
            f"pipeline:track_id:{ctx.job_id}",
            track_id,
            ex=7200,
        )

    return {
        "corners": corners,
        "track_layout": track_layout,
        "resampled_lap_count": len(resampled_laps),
    }


def _load_intermediate_state(ctx: PipelineContext) -> tuple[dict | None, list | None]:
    """Load resampled laps and corners saved by _run_analyze_stages.

    Returns (resampled_laps, corners) or (None, None) if state is missing
    (e.g. Redis TTL expired).
    """
    import glob as _glob
    import json as _json

    # Load resampled laps from Parquet files in temp dir
    resampled_laps = {}
    pattern = str(ctx.temp_dir / "resampled_lap_*.parquet")
    for path in sorted(_glob.glob(pattern)):
        # Extract lap number from filename: "resampled_lap_3.parquet" → 3
        stem = Path(path).stem  # "resampled_lap_3"
        try:
            lap_num = int(stem.split("_")[-1])
        except (ValueError, IndexError):
            continue
        df = ctx.load_dataframe(stem)
        if df is not None:
            resampled_laps[lap_num] = df

    if not resampled_laps:
        logger.warning("No resampled laps found in temp dir for job %s", ctx.job_id)
        return None, None

    # Load corners from Redis
    corners = []
    try:
        r = _get_redis()
        raw = r.get(f"pipeline:corners:{ctx.job_id}")
        if raw:
            corners = _json.loads(raw)
    except Exception:
        logger.warning("Failed to load corners from Redis for job %s", ctx.job_id, exc_info=True)

    return resampled_laps, corners


def _run_finalize_stages(ctx: PipelineContext, job_id: Optional[str] = None, conn=None) -> None:
    """Run pipeline stages 8-14 and persist all results to DB.

    Attempts to load intermediate state (resampled laps + corners) saved
    by ``_run_analyze_stages``. If available, calls ``run_full_analysis()``
    in resume mode (skipping stages 1-7). Falls back to a full re-run if
    intermediate state is missing (e.g. Redis TTL expired).

    If ``ctx.selected_corner_ids`` is set, filters corners to only those
    selected by the user.
    """
    from pipeline import run_full_analysis

    session_meta = _build_session_meta(ctx, conn=conn)

    # Mark first finalize stage as running
    ctx.update_stage(_FINALIZE_STAGES[0], "running")
    _job_id = job_id or ctx.job_id

    # Try to load intermediate state from analyze stage
    resampled_laps, corners = _load_intermediate_state(ctx)

    if resampled_laps:
        # Custom corners override auto-detected; legacy filter as fallback
        if ctx.custom_corners is not None:
            import json as _json
            from pipeline.helpers import enrich_custom_corners
            import numpy as np

            redis_client = ctx.redis_client
            raw_layout = redis_client.get(f"pipeline:layout:{ctx.job_id}") if redis_client else None
            if raw_layout:
                layout = _json.loads(raw_layout)
                lats = np.array(layout.get("latitudes", []))
                lons = np.array(layout.get("longitudes", []))
                dists = np.array(layout.get("distances", []))
                corners = enrich_custom_corners(ctx.custom_corners, lats, lons, dists)
            else:
                corners = [
                    {**cn, "corner_id": i, "lat": 0.0, "lon": 0.0, "direction": "S"}
                    for i, cn in enumerate(ctx.custom_corners)
                ]
            logger.info(
                "Job %s: using %d custom corners (user-defined)",
                ctx.job_id, len(corners),
            )
        elif ctx.selected_corner_ids is not None and corners:
            selected_set = set(ctx.selected_corner_ids)
            corners = [c for c in corners if c.get("corner_id") in selected_set]
            logger.info(
                "Job %s: filtered to %d selected corners (from user selection)",
                ctx.job_id, len(corners),
            )

        logger.info("Job %s: resuming from step 8 with %d laps, %d corners",
                     ctx.job_id, len(resampled_laps), len(corners))
        result = run_full_analysis(
            csv_path=ctx.file_path,
            session_meta=session_meta,
            enable_report=False,
            progress_callback=_make_progress_callback(_job_id, conn),
            resume_from_step8=True,
            preloaded_resampled_laps=resampled_laps,
            preloaded_corners=corners,
            workspace_id=ctx.workspace_id,
            skip_gamification=True,  # _persist_session_data owns SaaS gamification
        )
    else:
        # Fallback: full re-run (intermediate state expired or missing)
        logger.warning("Job %s: intermediate state missing, running full pipeline", ctx.job_id)
        _fallback_corners = None
        if ctx.custom_corners is not None:
            _fallback_corners = [
                {**cn, "corner_id": i, "lat": 0.0, "lon": 0.0, "direction": "S"}
                for i, cn in enumerate(ctx.custom_corners)
            ]
            logger.info("Job %s: passing %d custom corners to full re-run",
                         ctx.job_id, len(_fallback_corners))
        result = run_full_analysis(
            csv_path=ctx.file_path,
            session_meta=session_meta,
            enable_report=False,
            progress_callback=_make_progress_callback(_job_id, conn),
            preloaded_corners=_fallback_corners,
            workspace_id=ctx.workspace_id,
            skip_gamification=True,  # _persist_session_data owns SaaS gamification
        )

    # ── Persist all session data to the database ──────────────────
    _persist_session_data(ctx, result)

    # ── Store raw irsdk__ sidecar for .ibt uploads (sim optimizer) ──
    _try_store_raw_sidecar(ctx)

    # ── OCP theoretical solver — disabled for v1 (expensive, not surfaced in UI yet) ──
    # TODO(v2): re-enable when OCP results are displayed in session reports
    _update_job_progress(
        job_id=job_id or ctx.job_id, status="running",
        stage_name="finalize_complete", stage_index=15, stage_total=16,
        conn=conn,  # MUST reuse the task's GUC-pinned conn (worker has no
                    # app context → a fresh conn here is GUC-less and fails
                    # the RLS UPDATE under the telemetry_app cutover)
    )

    # Mark all finalize stages as completed
    for i, stage in enumerate(_FINALIZE_STAGES):
        ctx.update_stage(stage, "completed")
        logger.info(
            "Job %s: stage %s completed (%d/%d)",
            ctx.job_id, stage, i + 1, len(_FINALIZE_STAGES),
        )


def _persist_session_data(ctx: PipelineContext, result: dict) -> None:
    """Persist the full analysis result to the database.

    Sets workspace RLS context, then upserts driver/track/session,
    inserts laps, GPS traces, corner metrics, scores, theoretical data,
    reference line, and analysis JSON.

    Uses connection-scoped ``SET`` (not ``SET LOCAL``) so the
    ``app.current_workspace_id`` parameter survives ``COMMIT`` and
    ``ROLLBACK`` across all steps.  Each step commits independently
    so that a later failure doesn't roll back earlier steps.
    """
    from web.models import (
        insert_analysis_json,
        insert_corner_metrics,
        insert_gps_traces,
        insert_laps,
        insert_reference_line,
        insert_score_details,
        upsert_driver,
        upsert_session,
        upsert_track,
        upsert_track_by_name,
    )

    conn = _get_pg_connection()

    try:
        # Use connection-scoped SET (not SET LOCAL) so the workspace
        # context survives COMMIT/ROLLBACK between steps.  SET LOCAL
        # resets on every COMMIT, which caused workspace_id DEFAULT
        # failures (`unrecognized configuration parameter`) in tables
        # that rely on current_setting('app.current_workspace_id').
        conn.execute(
            "SET app.current_workspace_id = %(ws)s",
            {"ws": str(ctx.workspace_id)},
        )
        logger.info(
            "Set workspace context (connection-scoped) ws=%s for job %s",
            ctx.workspace_id, ctx.job_id,
        )

        # 1. Upsert driver
        meta = result.get("session_meta") or {}
        driver_name = meta.get("driver_name", "Unknown")
        driver_id = upsert_driver(conn, driver_name)
        conn.commit()
        logger.info("Upserted driver '%s' (id=%d) for job %s", driver_name, driver_id, ctx.job_id)

        # 2. Upsert track (if detected)
        track_match = result.get("track_match")
        if track_match and isinstance(track_match, dict):
            try:
                upsert_track(conn, track_match)
                conn.commit()
                logger.info("Upserted track %s for job %s", track_match.get("track_id", "?"), ctx.job_id)
            except Exception:
                logger.warning("Failed to upsert track for session %s", ctx.session_id, exc_info=True)
                conn.rollback()

        # 2b. User-provided track name overrides pipeline detection.
        # The user typed a track name in the upload form — honour it.
        user_track_name = meta.get("user_track_name")
        if user_track_name:
            try:
                user_tid = upsert_track_by_name(conn, user_track_name)
                conn.commit()
                result["track_id"] = user_tid
                logger.info(
                    "User-provided track '%s' → track_id=%s for job %s",
                    user_track_name, user_tid, ctx.job_id,
                )
            except Exception:
                logger.warning("Failed to upsert user track '%s'", user_track_name, exc_info=True)
                conn.rollback()

        # 2c. Ensure fallback track exists (FK requires a valid tracks row).
        # The tracks table has NOT NULL on lap_length_m and workspace_id
        # (workspace_id defaults from current_setting, set above).
        fallback_tid = result.get("track_id") or "unknown_track"
        if not track_match or track_match.get("track_id") != fallback_tid:
            try:
                conn.execute(
                    "INSERT INTO tracks (track_id, track_name, lap_length_m) "
                    "VALUES (%(track_id)s, %(track_name)s, %(lap_length_m)s) "
                    "ON CONFLICT (track_id) DO NOTHING",
                    {"track_id": fallback_tid, "track_name": fallback_tid, "lap_length_m": 0.0},
                )
                conn.commit()
            except Exception:
                logger.warning("Fallback track upsert failed", exc_info=True)
                conn.rollback()

        # 3. Upsert session (critical — must succeed)
        session_id = upsert_session(conn, result, driver_id)
        conn.commit()
        logger.info("Persisted session %s (driver_id=%d) for job %s", session_id, driver_id, ctx.job_id)

        # 4. Insert laps
        try:
            n_laps = insert_laps(conn, session_id, result)
            conn.commit()
            logger.info("Inserted %d laps for session %s", n_laps, session_id)
        except Exception:
            logger.warning("Failed to insert laps for session %s", session_id, exc_info=True)
            conn.rollback()

        # 5. Insert GPS traces
        try:
            n_gps = insert_gps_traces(conn, session_id, result)
            conn.commit()
            logger.info("Inserted %d GPS trace rows for session %s", n_gps, session_id)
        except Exception:
            logger.warning("Failed to insert GPS traces for session %s", session_id, exc_info=True)
            conn.rollback()

        # 6. Insert corner metrics
        try:
            corners = result.get("corners")
            if corners:
                insert_corner_metrics(conn, session_id, result)
                conn.commit()
                logger.info("Inserted corner metrics for session %s", session_id)
        except Exception:
            logger.warning("Failed to insert corner metrics for session %s", session_id, exc_info=True)
            conn.rollback()

        # 7. Insert score details (expects full result dict)
        try:
            score_result = result.get("score_result")
            if score_result:
                insert_score_details(conn, session_id, result)
                conn.commit()
                logger.info("Inserted score details for session %s", session_id)
        except Exception:
            logger.warning("Failed to insert score details for session %s", session_id, exc_info=True)
            conn.rollback()

        # 8. Insert theoretical data
        try:
            theo_metrics = result.get("theoretical_metrics")
            if theo_metrics:
                _store_theoretical_data(session_id, result, conn=conn)
                # _store_theoretical_data commits internally
        except Exception:
            logger.warning("Failed to store theoretical data for session %s", session_id, exc_info=True)
            conn.rollback()

        # 9. Insert reference line
        try:
            ref_line = result.get("reference_line")
            if ref_line is not None:
                insert_reference_line(conn, session_id, result)
                conn.commit()
                logger.info("Inserted reference line for session %s", session_id)
        except Exception:
            logger.warning("Failed to insert reference line for session %s", session_id, exc_info=True)
            conn.rollback()

        # 11. Persist channel metadata from adapter registry
        try:
            import json as _json
            _data_tier = result.get("data_tier", 1)
            _avail_ch = result.get("available_channels", [])
            _src_fmt = result.get("source_format", "racechrono")
            _src_meta = result.get("source_metadata", {})
            conn.execute(
                "UPDATE sessions SET data_tier = %(tier)s, "
                "available_channels = %(channels)s, "
                "source_format = %(fmt)s, "
                "source_metadata = %(meta)s "
                "WHERE session_id = %(sid)s",
                {
                    "tier": _data_tier,
                    "channels": _json.dumps(_avail_ch),
                    "fmt": _src_fmt,
                    "meta": _json.dumps(_src_meta),
                    "sid": session_id,
                },
            )
            conn.commit()
            logger.info(
                "Persisted channel metadata (tier=%d, %d channels, format=%s) for session %s",
                _data_tier, len(_avail_ch), _src_fmt, session_id,
            )
        except Exception:
            logger.warning("Failed to persist channel metadata for session %s", session_id, exc_info=True)
            conn.rollback()

        # 12. Gamification — award XP, check achievements, update streak
        try:
            from gamification.xp import award_session_xp
            from gamification.achievements import check_achievements
            from gamification.streaks import update_streak
            from gamification.queries import count_driver_sessions, get_driver_best_lap

            meta = result.get("session_meta") or {}
            score_result = result.get("score_result") or {}
            badges = score_result.get("badges", [])

            # ── Idempotency gate (Option B) ─────────────────────────────────
            # Read the per-session flag BEFORE any award.  Base XP and the
            # comeback multiplier are first-process-only; mastery, quests,
            # achievements, and streak run unconditionally (they are already
            # state-based/idempotent).
            _flag_row = conn.execute(
                "SELECT gamification_applied FROM sessions WHERE session_id = :sid",
                {"sid": session_id},
            ).fetchone()
            already_scored = bool(_flag_row["gamification_applied"]) if _flag_row else False
            # ────────────────────────────────────────────────────────────────

            session_date = meta.get("session_date") or meta.get("date", "")
            streak_result = update_streak(conn, driver_id, ctx.workspace_id, session_date)
            conn.commit()

            prev_best = get_driver_best_lap(conn, driver_id, ctx.workspace_id)
            lap_times = result.get("lap_times") or []
            valid_times = [t for t in lap_times if t and isinstance(t, (int, float)) and t > 0]
            current_best = min(valid_times) if valid_times else None

            # Count BEFORE awarding so we can detect the driver's first session.
            # The session row for THIS session is already persisted (step 1),
            # so the first upload sees count == 1.
            session_count = count_driver_sessions(conn, driver_id, ctx.workspace_id)

            if not already_scored:
                xp_result = award_session_xp(
                    conn, driver_id, ctx.workspace_id, session_id,
                    badges=badges,
                    previous_best_lap=prev_best,
                    current_best_lap=current_best,
                    is_first_session=(session_count == 1),
                )
                # Stamp the flag in the SAME commit as the base-XP award so a
                # crash between the two can never leave XP committed with the
                # flag still false (which would cause one spurious re-award on
                # the next reprocess).  award_session_xp does NOT commit
                # internally, so both writes land in one atomic transaction.
                conn.execute(
                    "UPDATE sessions SET gamification_applied = true "
                    "WHERE session_id = :sid",
                    {"sid": session_id},
                )
                conn.commit()
            else:
                # Reprocess path: base XP already awarded — synthesise a zero-
                # delta xp_result so downstream in-memory code stays consistent.
                from gamification.queries import get_driver_xp
                from gamification.xp import compute_level
                _cur = get_driver_xp(conn, driver_id, ctx.workspace_id)
                _total = _cur["total_xp"] if _cur else 0
                _lvl = compute_level(_total)
                xp_result = {
                    "xp_gained": 0,
                    "xp_breakdown": {},
                    "old_total": _total,
                    "new_total": _total,
                    "old_level": _lvl,
                    "new_level": _lvl,
                    "leveled_up": False,
                }
                logger.info(
                    "Gamification: session %s already scored — skipping base XP + comeback",
                    session_id,
                )
            achievement_context = {
                "session_count": session_count,
                "badges": badges,
                "streak": streak_result.get("current_streak", 0),
                "is_personal_best": (
                    current_best is not None and prev_best is not None
                    and current_best < prev_best
                ),
                "score_improvement": 0,
                "plan_just_completed": False,
                "week_just_completed": False,
            }
            new_achievements = check_achievements(
                conn, driver_id, ctx.workspace_id, session_id, achievement_context,
            )
            conn.commit()

            # ── Corner mastery stars (Phase 1) ───────────────────────
            star_events: list = []
            try:
                from gamification.mastery import (
                    compute_corner_scores, update_corner_mastery,
                )
                from gamification.queries import upsert_driver_xp
                from gamification.xp import compute_level

                _track_id = (result.get("track_id")
                             or meta.get("track_id") or "unknown_track")
                _condition = meta.get("track_state", "dry")
                _corner_scores = compute_corner_scores(conn, session_id)
                _pending_star_events: list = []
                _pending_star_xp = 0
                if _corner_scores:
                    _pending_star_events = update_corner_mastery(
                        conn, driver_id, ctx.workspace_id, _track_id,
                        _condition, _corner_scores, session_id,
                    )
                    _pending_star_xp = sum(e["xp"] for e in _pending_star_events)
                    if _pending_star_xp:
                        upsert_driver_xp(
                            conn, driver_id, ctx.workspace_id,
                            xp_delta=_pending_star_xp,
                            level=compute_level(xp_result["new_total"] + _pending_star_xp),
                            streak=streak_result.get("current_streak", 0),
                            longest=streak_result.get("longest_streak", 0),
                            last_date=None,
                        )
                # Commit BEFORE mutating in-memory xp_result so a rollback on
                # failure cannot leave xp_result inflated.
                conn.commit()
                # Only update in-memory state after the commit succeeds.
                if _pending_star_xp:
                    xp_result["xp_gained"] += _pending_star_xp
                    xp_result["new_total"] += _pending_star_xp
                    xp_result["new_level"] = compute_level(xp_result["new_total"])
                    xp_result["leveled_up"] = (
                        xp_result["new_level"] > xp_result["old_level"])
                star_events = _pending_star_events
            except Exception:
                logger.warning("Corner mastery update failed (non-fatal) for %s",
                               session_id, exc_info=True)
                try:
                    conn.rollback()
                except Exception:
                    pass

            # ── Quests (Phase 2a): verify active, then generate next ──
            quests_completed: list = []
            quests_active: list = []
            try:
                from gamification.quests import (
                    expire_stale_quests, extract_session_facts,
                    generate_quests, verify_quests,
                )
                from gamification.queries import upsert_driver_xp
                from gamification.xp import compute_level

                _facts = extract_session_facts(conn, result, session_id, driver_id, ctx.workspace_id)
                expire_stale_quests(conn, driver_id, ctx.workspace_id)
                _pending_completed = verify_quests(conn, _facts, driver_id, ctx.workspace_id, session_id)
                quest_xp = sum(q["xp"] for q in _pending_completed)
                if quest_xp:
                    upsert_driver_xp(
                        conn, driver_id, ctx.workspace_id,
                        xp_delta=quest_xp,
                        level=compute_level(xp_result["new_total"] + quest_xp),
                        streak=streak_result.get("current_streak", 0),
                        longest=streak_result.get("longest_streak", 0),
                        last_date=None,
                    )
                _pending_active = generate_quests(conn, _facts, driver_id, ctx.workspace_id, session_id)
                # Commit BEFORE mutating in-memory xp_result so a rollback on
                # failure cannot leave xp_result inflated.
                conn.commit()
                # Only update in-memory state and expose quest lists after the
                # commit succeeds.  quests_completed/quests_active remain [] if
                # anything above threw.
                if quest_xp:
                    xp_result["xp_gained"] += quest_xp
                    xp_result["new_total"] += quest_xp
                    xp_result["new_level"] = compute_level(xp_result["new_total"])
                    xp_result["leveled_up"] = xp_result["new_level"] > xp_result["old_level"]
                quests_completed = _pending_completed
                quests_active = _pending_active
            except Exception:
                logger.warning("Quest step failed (non-fatal) for %s", session_id, exc_info=True)
                try:
                    conn.rollback()
                except Exception:
                    pass

            # ── Comeback Shakedown (Phase 2b): multiply this session's
            #    gamification XP after a long absence (zero-shame return) ──
            #    Gated on not already_scored: re-firing on reprocess would
            #    double XP because it keys off xp_result["xp_gained"] > 0.
            comeback = None
            if not already_scored:
                try:
                    from gamification.quests import weeks_since_last_session
                    from gamification.catalog import COMEBACK_WEEKS, COMEBACK_XP_MULTIPLIER
                    from gamification.queries import upsert_driver_xp
                    from gamification.xp import compute_level

                    weeks_away = weeks_since_last_session(
                        conn, driver_id, ctx.workspace_id, session_id, session_date
                    )
                    if weeks_away >= COMEBACK_WEEKS and xp_result.get("xp_gained", 0) > 0:
                        bonus = int(xp_result["xp_gained"] * (COMEBACK_XP_MULTIPLIER - 1))
                        if bonus > 0:
                            upsert_driver_xp(
                                conn, driver_id, ctx.workspace_id, xp_delta=bonus,
                                level=compute_level(xp_result["new_total"] + bonus),
                                streak=streak_result.get("current_streak", 0),
                                longest=streak_result.get("longest_streak", 0),
                                last_date=None,
                            )
                            # Commit BEFORE mutating in-memory xp_result so a
                            # rollback on failure cannot leave xp_result inflated.
                            conn.commit()
                            # Only update in-memory state after the commit succeeds.
                            xp_result["xp_gained"] += bonus
                            xp_result["new_total"] += bonus
                            xp_result["new_level"] = compute_level(xp_result["new_total"])
                            xp_result["leveled_up"] = xp_result["new_level"] > xp_result["old_level"]
                        comeback = {"weeks_away": weeks_away, "multiplier": COMEBACK_XP_MULTIPLIER}
                except Exception:
                    logger.warning("Comeback step failed (non-fatal) for %s", session_id, exc_info=True)
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            result["gamification"] = {
                "xp_gained": xp_result.get("xp_gained", 0),
                "old_level": xp_result.get("old_level", 0),
                "new_level": xp_result.get("new_level", 0),
                "leveled_up": xp_result.get("leveled_up", False),
                "current_streak": streak_result.get("current_streak", 0),
                "pit_pass_used": streak_result.get("pit_pass_used", False),
                "pit_passes": streak_result.get("pit_passes", 0),
                "stars": star_events,
                "quests_completed": quests_completed,
                "quests_active": quests_active,
                "comeback": comeback,
                "new_achievements": [
                    {"key": a["key"], "label": a["label"], "description": a["description"], "icon": a["icon"]}
                    for a in new_achievements
                ],
            }
            logger.info(
                "Gamification: +%d XP, level %d->%d, streak %d, %d achievements for %s",
                xp_result.get("xp_gained", 0), xp_result.get("old_level", 0),
                xp_result.get("new_level", 0), streak_result.get("current_streak", 0),
                len(new_achievements), session_id,
            )
        except Exception:
            logger.warning("Gamification failed (non-fatal) for session %s", session_id, exc_info=True)
            try:
                conn.rollback()
            except Exception:
                pass

        # 13. Insert the curated analysis JSON blob LAST — it must run AFTER
        #     step 12 so it captures result["gamification"]. The per-session
        #     gamification panel is read from sessions.analysis_json
        #     (data_v2 session-detail), and since the SaaS pipeline now sets
        #     skip_gamification=True the orchestrator no longer pre-populates
        #     result["gamification"]; only step 12 above does.
        try:
            analysis_blob = _build_analysis_blob(result)
            if analysis_blob:
                insert_analysis_json(conn, session_id, analysis_blob)
                conn.commit()
                logger.info("Inserted analysis JSON (%d keys) for session %s",
                            len(analysis_blob), session_id)
        except Exception:
            logger.warning("Failed to insert analysis JSON for session %s", session_id, exc_info=True)
            conn.rollback()

    except Exception:
        logger.exception("Failed to persist session data for job %s", ctx.job_id)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@celery.task(
    name="tasks.pipeline_tasks.pipeline_ingest",
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
)
def pipeline_ingest(self, job_id: str) -> Optional[str]:
    """Ingest stages 1-4: CSV read, GPS filter, derived channels, trim.

    Acquires workspace lock before processing. Raises TransientError
    if the lock cannot be acquired (Celery will retry).
    """
    redis_client = _get_redis()
    ctx = PipelineContext.load(redis_client, job_id)

    if ctx is None:
        raise FatalError(f"PipelineContext not found for job {job_id}")

    # RLS: open the single GUC-pinned connection BEFORE any ingestion_jobs
    # write (including the entitlement-fail write below) and thread it through
    # every helper; close it in the finally.
    conn = _open_task_conn(ctx)
    try:
        # Verify the owning user's plan allows report generation.
        # Always checked — even when ctx.user_id is absent (reprocess/batch
        # paths), the guard resolves the session owner via session_id so locked
        # workspaces cannot bypass the check by omitting user_id.
        # TransientError from the guard is caught by the autoretry_for clause
        # above; definitive False (locked/unresolvable) marks the job failed.
        user_id_for_check = getattr(ctx, "user_id", None) or None
        session_id_for_check = getattr(ctx, "session_id", None) or None
        if not _verify_task_entitlements(
            user_id=user_id_for_check,
            workspace_id=ctx.workspace_id,
            conn=conn,
            session_id=session_id_for_check,
        ):
            _update_job_progress(
                job_id=job_id,
                status="failed",
                error_message="Plan does not allow report generation",
                error_class="entitlement",
                conn=conn,
            )
            return None

        _update_job_progress(job_id=job_id, status="running", stage_name="ingest", stage_index=0, stage_total=15, conn=conn)

        # Acquire workspace lock (inside try so failures update job status)
        if not acquire_workspace_lock(redis_client, ctx.workspace_id, job_id):
            raise TransientError(f"Workspace {ctx.workspace_id} is locked by another job")

        _run_ingest_stages(ctx)
        ctx.save()
        _update_job_progress(
            job_id=job_id, status="running",
            stage_name="ingest_complete", stage_index=4, stage_total=15,
            conn=conn,
        )
        return job_id
    except TransientError:
        # On final retry (retries exhausted), mark job as failed so the
        # SSE stream sees a terminal status instead of "stuck at 0%".
        if self.request.retries >= self.max_retries:
            _update_job_progress(
                job_id=job_id, status="failed",
                stage_name="ingest", stage_index=0, stage_total=15,
                error_message="Pipeline busy — please retry in a few minutes",
                error_class="transient",
                conn=conn,
            )
        ctx.save()
        raise
    except InteractionRequired:
        ctx.save()
        raise
    except FatalError as exc:
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class="fatal",
            import_error_json=_make_import_error_json(exc),
            conn=conn,
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        err_class = classify_error(exc)
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class=err_class,
            import_error_json=_make_import_error_json(exc),
            conn=conn,
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        if err_class == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc
    finally:
        _return_pg_connection(conn)


@celery.task(
    name="tasks.pipeline_tasks.pipeline_analyze",
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
)
def pipeline_analyze(self, job_id: Optional[str]) -> Optional[str]:
    """Analyze stages 5-8: track detect, corners, resample, features.

    Catches InteractionRequired and sets job to "paused" status,
    returning None to stop the Celery chain.
    """
    if job_id is None:
        return None

    redis_client = _get_redis()
    ctx = PipelineContext.load(redis_client, job_id)

    if ctx is None:
        raise FatalError(f"PipelineContext not found for job {job_id}")

    # RLS: open the single GUC-pinned connection for this task and thread it
    # through every helper; close it in the finally.
    conn = _open_task_conn(ctx)
    try:
        _update_job_progress(job_id=job_id, status="running", stage_name="analyze", stage_index=4, stage_total=15, conn=conn)

        phase1_result = _run_analyze_stages(ctx, job_id=job_id, conn=conn)
        ctx.save()

        corners = phase1_result.get("corners") or []
        track_layout = phase1_result.get("track_layout")
        logger.info(
            "Job %s: analyze complete — %d corners detected",
            job_id, len(corners),
        )

        # Pause for corner selection if corners were detected and
        # we have a track layout for the picker UI.
        if corners and track_layout:
            _update_job_progress(
                job_id=job_id, status="awaiting_corner_selection",
                stage_name="corner_detect", stage_index=7, stage_total=15,
                pause_reason="corner_selection",
                conn=conn,
            )
            # Release workspace lock while waiting for user interaction.
            # pipeline_finalize will re-acquire it on the resume path.
            release_workspace_lock(redis_client, ctx.workspace_id, job_id)
            logger.info("Job %s: pausing for corner selection (%d corners), lock released", job_id, len(corners))
            return None  # Stop Celery chain — user resumes via /jobs/<id>/resume

        # No corners or no layout — continue without pause
        _update_job_progress(
            job_id=job_id, status="running",
            stage_name="analyze_complete", stage_index=8, stage_total=15,
            conn=conn,
        )
        return job_id
    except InteractionRequired as exc:
        ctx.save()
        # Use specific status for corner selection vs generic pause
        status = "awaiting_corner_selection" if exc.reason == "corner_selection" else "paused"
        _update_job_progress(
            job_id=job_id, status=status,
            stage_name="corner_detect", stage_index=7, stage_total=15,
            pause_reason=exc.reason,
            conn=conn,
        )
        # Release workspace lock while waiting for user interaction.
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        return None
    except FatalError as exc:
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class="fatal",
            import_error_json=_make_import_error_json(exc),
            conn=conn,
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        err_class = classify_error(exc)
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class=err_class,
            import_error_json=_make_import_error_json(exc),
            conn=conn,
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        if err_class == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc
    finally:
        _return_pg_connection(conn)


@celery.task(
    name="tasks.pipeline_tasks.pipeline_finalize",
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
)
def pipeline_finalize(self, job_id: Optional[str]) -> Optional[str]:
    """Finalize stages 9-15: ref line, physics, theoretical, ML, scoring, reports.

    Marks job as "completed", updates ``sessions.processing_version``,
    calls ``ctx.cleanup()``, releases workspace lock, and checks worker memory.

    On the resume path (after joker pause), re-acquires the workspace lock
    in case it expired during the pause window.
    """
    if job_id is None:
        return None

    redis_client = _get_redis()
    ctx = PipelineContext.load(redis_client, job_id)

    if ctx is None:
        raise FatalError(f"PipelineContext not found for job {job_id}")

    # RLS: open the single GUC-pinned connection for this task; thread it
    # through every helper and close it in the finally.
    conn = _open_task_conn(ctx)

    # Re-acquire workspace lock on resume path (lock may have expired
    # during joker pause which can exceed the 30-minute TTL).
    if not acquire_workspace_lock(redis_client, ctx.workspace_id, job_id):
        _return_pg_connection(conn)
        raise TransientError(f"Workspace {ctx.workspace_id} is locked by another job (resume path)")

    try:
        _update_job_progress(job_id=job_id, status="running", stage_name="finalize", stage_index=8, stage_total=16, conn=conn)

        _run_finalize_stages(ctx, job_id=job_id, conn=conn)
        ctx.save()

        # Update sessions.processing_version + pipeline version hash + model version
        try:
            from pipeline_status import get_model_version
            from pipeline_version import full_version_string

            conn.execute(
                text(
                    "UPDATE sessions SET "
                    "  processing_version = :version,"
                    "  pipeline_version_hash = :version_hash,"
                    "  model_version = :model_version "
                    "WHERE session_id = :session_id"
                ),
                {
                    "version": PIPELINE_VERSION,
                    "version_hash": full_version_string(),
                    "model_version": get_model_version(),
                    "session_id": ctx.session_id,
                },
            )
            conn.commit()
        except Exception:
            # Reset the shared task connection: an un-rolled-back failure leaves
            # it in InFailedSqlTransaction and every later conn.execute (staging
            # cleanup, batch counter) would then fail too.
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Failed to update processing_version for session %s", ctx.session_id, exc_info=True)

        _update_job_progress(
            job_id=job_id, status="completed",
            stage_name="finalize_complete", stage_index=15, stage_total=15,
            conn=conn,
        )

        # Record report usage for quota tracking
        try:
            from auth.entitlements import record_usage
            ws_id = int(ctx.workspace_id) if ctx.workspace_id else None
            if ws_id is not None:
                # Look up user_id from the ingestion_jobs record
                _job_row = conn.execute(
                    text("SELECT workspace_id FROM ingestion_jobs WHERE job_id = :jid"),
                    {"jid": job_id},
                ).fetchone()
                if _job_row:
                    # Get workspace owner as user_id for usage tracking
                    _owner_row = conn.execute(
                        text("SELECT owner_user_id FROM workspaces WHERE id = :wsid"),
                        {"wsid": ws_id},
                    ).fetchone()
                    if _owner_row:
                        _owner = dict(_owner_row) if not isinstance(_owner_row, dict) else _owner_row
                        record_usage(conn, _owner["owner_user_id"], ws_id, "report_generated")
                        conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Failed to record report usage for job %s", job_id, exc_info=True)

        # Reconcile this workspace's storage now that the new session's files
        # are on disk — keeps the allocation matched to consumption right after
        # upload, not just on the next data-page view / daily reconcile.
        try:
            from web.storage_quota import recompute_and_store
            _ws_for_storage = int(ctx.workspace_id) if ctx.workspace_id else None
            if _ws_for_storage is not None:
                recompute_and_store(conn, _ws_for_storage)
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Storage reconcile after job %s failed", job_id, exc_info=True)

        # Remove the transient upload-staging dir now the pipeline has ingested
        # and persisted the raw sidecar (_try_store_raw_sidecar). The staging
        # file is NOT the canonical copy, so it would otherwise leak under
        # UPLOAD_DIR forever. Success path only — a failed job may retry and
        # still need its staging file; stale failed dirs are swept separately.
        try:
            import shutil as _shutil_stage
            _fp_row = conn.execute(
                text("SELECT file_path FROM ingestion_jobs WHERE job_id = :jid"),
                {"jid": job_id},
            ).fetchone()
            _fp = None
            if _fp_row:
                _fp = (dict(_fp_row) if not isinstance(_fp_row, dict) else _fp_row).get("file_path")
            if _fp:
                _stage_dir = Path(_fp).resolve().parent
                # Guard: only remove dedicated per-job staging dirs.
                if _stage_dir.name.startswith(("job_", "telemetry_upload_")):
                    _shutil_stage.rmtree(_stage_dir, ignore_errors=True)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Upload-staging cleanup after job %s failed", job_id, exc_info=True)

        ctx.cleanup()
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)

        # Advisory memory check (exit_on_exceed=False: don't kill worker mid-task,
        # the memory guard in the worker's post-task hook handles that).
        if check_worker_memory(exit_on_exceed=False):
            logger.warning("Worker memory exceeds threshold after job %s", job_id)

        # Increment batch completed counter if part of a batch
        _increment_batch_counter(job_id, "completed_sessions", conn=conn)

        return job_id
    except FatalError as exc:
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class="fatal",
            import_error_json=_make_import_error_json(exc),
            conn=conn,
        )
        _increment_batch_counter(job_id, "failed_sessions", conn=conn)
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        err_class = classify_error(exc)
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class=err_class,
            import_error_json=_make_import_error_json(exc),
            conn=conn,
        )
        _increment_batch_counter(job_id, "failed_sessions", conn=conn)
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        if err_class == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc
    finally:
        _return_pg_connection(conn)


# ---------------------------------------------------------------------------
# Chain builder
# ---------------------------------------------------------------------------


def build_pipeline_chain(job_id: str):
    """Return a Celery chain: ingest -> analyze -> finalize.

    Usage::

        chain = build_pipeline_chain("job-abc")
        chain.apply_async()
    """
    return chain(
        pipeline_ingest.s(job_id),
        pipeline_analyze.s(),
        pipeline_finalize.s(),
    )
