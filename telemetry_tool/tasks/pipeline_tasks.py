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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entitlement guard
# ---------------------------------------------------------------------------


def _verify_task_entitlements(user_id: int, workspace_id: int) -> bool:
    """Lightweight entitlement check for Celery workers.

    Returns True if the user's current plan allows report generation.
    Fails open if the check itself errors (don't break pipeline on
    transient DB issues).
    """
    try:
        from auth.entitlements import get_plan_entitlements, get_user_plan_tier

        conn = _get_pg_connection()
        tier = get_user_plan_tier(conn, user_id)
        plan = get_plan_entitlements(tier)
        if plan.get("reports_per_month") == 0:
            logger.warning(
                "Worker entitlement check failed: user=%s tier=%s",
                user_id,
                tier,
            )
            return False
        return True
    except Exception:
        logger.warning("Worker entitlement check error (failing open)", exc_info=True)
        return True  # Fail open — don't break pipeline on DB transient errors


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


def _update_job_progress(
    job_id: str,
    status: str,
    stage_name: Optional[str] = None,
    stage_index: Optional[int] = None,
    stage_total: Optional[int] = None,
    error_message: Optional[str] = None,
    error_class: Optional[str] = None,
    pause_reason: Optional[str] = None,
    conn=None,
) -> None:
    """Write pipeline progress to the PG ``ingestion_jobs`` table.

    Accepts an optional ``conn`` to reuse an existing PG connection
    instead of opening a new one per call.
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
        },
    )
    conn.commit()


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


def _build_session_meta(ctx: PipelineContext) -> dict:
    """Build the session_meta dict expected by ``run_full_analysis()``."""
    return {
        "session_id": ctx.session_id,
        "session_type": "practice",
        "track_state": "dry",
    }


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

    # Serialise optional fields as JSON
    speed_profile_json = None
    distance_json = None
    theo_lap = result.get("theoretical_lap")
    if theo_lap is not None and hasattr(theo_lap, "columns"):
        for c in theo_lap.columns:
            cl = c.lower()
            if distance_json is None and "distance" in cl:
                distance_json = _json.dumps(theo_lap[c].tolist())
            if speed_profile_json is None and ("v_env" in cl or "speed" in cl):
                speed_profile_json = _json.dumps(theo_lap[c].tolist())

    metrics_json = _json.dumps(theo_metrics) if theo_metrics else None

    corner_coaching = result.get("corner_coaching")
    corner_coaching_json = _json.dumps(corner_coaching) if corner_coaching else None

    delta_map = result.get("delta_map")
    delta_map_json = None
    if delta_map is not None and hasattr(delta_map, "to_dict"):
        try:
            delta_map_json = _json.dumps(delta_map.head(10).to_dict(orient="records"))
        except Exception:
            pass

    session_scalars = result.get("session_scalars")
    session_scalars_json = _json.dumps(session_scalars) if session_scalars else None

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


def _run_analyze_stages(ctx: PipelineContext) -> None:
    """Pass-through: mark analyze stages 5-8 as completed.

    The real analysis happens in ``_run_finalize_stages`` via
    ``run_full_analysis()``.
    """
    for i, stage in enumerate(_ANALYZE_STAGES):
        ctx.update_stage(stage, "running")
        logger.info("Job %s: stage %s (%d/%d)", ctx.job_id, stage, i + 1, len(_ANALYZE_STAGES))
        ctx.update_stage(stage, "completed")


def _run_finalize_stages(ctx: PipelineContext) -> None:
    """Run the full analysis pipeline and persist results.

    Calls ``run_full_analysis()`` which orchestrates all 14 pipeline
    stages in a single pass, then persists theoretical data and scores
    to the database.
    """
    from pipeline import run_full_analysis

    session_meta = _build_session_meta(ctx)

    # Mark first finalize stage as running
    ctx.update_stage(_FINALIZE_STAGES[0], "running")
    logger.info("Job %s: running full analysis pipeline", ctx.job_id)

    result = run_full_analysis(
        csv_path=ctx.file_path,
        session_meta=session_meta,
        enable_report=False,
    )

    # Persist theoretical data if available
    theo_metrics = result.get("theoretical_metrics")
    if theo_metrics:
        try:
            conn = _get_pg_connection()
            _store_theoretical_data(ctx.session_id, result, conn=conn)
        except Exception:
            logger.warning(
                "Failed to store theoretical data for session %s",
                ctx.session_id,
                exc_info=True,
            )

    # Persist scores if available
    score_result = result.get("score_result")
    if score_result:
        try:
            conn = _get_pg_connection()
            total_score = score_result.get("total_score")
            grade = score_result.get("grade")
            if total_score is not None or grade is not None:
                conn.execute(
                    text(
                        "UPDATE sessions SET total_score = :total_score, "
                        "grade = :grade WHERE session_id = :session_id"
                    ),
                    {
                        "total_score": total_score,
                        "grade": grade,
                        "session_id": ctx.session_id,
                    },
                )
                conn.commit()
                logger.info(
                    "Updated session %s with score=%.1f grade=%s",
                    ctx.session_id,
                    total_score or 0,
                    grade or "n/a",
                )
        except Exception:
            logger.warning(
                "Failed to update scores for session %s",
                ctx.session_id,
                exc_info=True,
            )

    # Mark all finalize stages as completed
    for i, stage in enumerate(_FINALIZE_STAGES):
        ctx.update_stage(stage, "completed")
        logger.info(
            "Job %s: stage %s completed (%d/%d)",
            ctx.job_id, stage, i + 1, len(_FINALIZE_STAGES),
        )


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

    # Verify user's plan still allows report generation
    if (
        hasattr(ctx, "user_id")
        and ctx.user_id
        and not _verify_task_entitlements(ctx.user_id, ctx.workspace_id)
    ):
        _update_job_progress(
            job_id=job_id,
            status="failed",
            error_message="Plan does not allow report generation",
            error_class="entitlement",
        )
        return None

    _update_job_progress(job_id=job_id, status="running", stage_name="ingest", stage_index=0, stage_total=15)

    # Acquire workspace lock
    if not acquire_workspace_lock(redis_client, ctx.workspace_id, job_id):
        raise TransientError(f"Workspace {ctx.workspace_id} is locked by another job")

    try:
        _run_ingest_stages(ctx)
        ctx.save()
        _update_job_progress(
            job_id=job_id, status="running",
            stage_name="ingest_complete", stage_index=4, stage_total=15,
        )
        return job_id
    except (TransientError, InteractionRequired):
        ctx.save()
        raise
    except FatalError as exc:
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class="fatal",
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        err_class = classify_error(exc)
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class=err_class,
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        if err_class == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc


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

    _update_job_progress(job_id=job_id, status="running", stage_name="analyze", stage_index=4, stage_total=15)

    try:
        _run_analyze_stages(ctx)
        ctx.save()
        _update_job_progress(
            job_id=job_id, status="running",
            stage_name="analyze_complete", stage_index=8, stage_total=15,
        )
        return job_id
    except InteractionRequired as exc:
        ctx.save()
        _update_job_progress(
            job_id=job_id, status="paused",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            pause_reason=exc.reason,
        )
        return None
    except FatalError as exc:
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class="fatal",
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        err_class = classify_error(exc)
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class=err_class,
        )
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        if err_class == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc


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

    # Re-acquire workspace lock on resume path (lock may have expired
    # during joker pause which can exceed the 30-minute TTL).
    if not acquire_workspace_lock(redis_client, ctx.workspace_id, job_id):
        raise TransientError(f"Workspace {ctx.workspace_id} is locked by another job (resume path)")

    _update_job_progress(job_id=job_id, status="running", stage_name="finalize", stage_index=8, stage_total=15)

    try:
        _run_finalize_stages(ctx)
        ctx.save()

        # Update sessions.processing_version
        try:
            conn = _get_pg_connection()
            conn.execute(
                text(
                    "UPDATE sessions SET processing_version = :version "
                    "WHERE session_id = :session_id"
                ),
                {"version": PIPELINE_VERSION, "session_id": ctx.session_id},
            )
            conn.commit()
        except Exception:
            logger.warning("Failed to update processing_version for session %s", ctx.session_id, exc_info=True)

        _update_job_progress(
            job_id=job_id, status="completed",
            stage_name="finalize_complete", stage_index=15, stage_total=15,
        )

        ctx.cleanup()
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)

        # Advisory memory check (exit_on_exceed=False: don't kill worker mid-task,
        # the memory guard in the worker's post-task hook handles that).
        if check_worker_memory(exit_on_exceed=False):
            logger.warning("Worker memory exceeds threshold after job %s", job_id)

        # Increment batch completed counter if part of a batch
        _increment_batch_counter(job_id, "completed_sessions")

        return job_id
    except FatalError as exc:
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class="fatal",
        )
        _increment_batch_counter(job_id, "failed_sessions")
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        err_class = classify_error(exc)
        _update_job_progress(
            job_id=job_id, status="failed",
            stage_name=ctx.current_stage, stage_index=None, stage_total=15,
            error_message=str(exc), error_class=err_class,
        )
        _increment_batch_counter(job_id, "failed_sessions")
        release_workspace_lock(redis_client, ctx.workspace_id, job_id)
        if err_class == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc


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
