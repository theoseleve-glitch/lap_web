"""AnalysisOrchestrator — drives one analysis run end-to-end.

Responsibilities:
  1. enqueue(session_id, workspace_id, force_rerun) → run_id (INSERT queued row)
  2. execute(run_id) → runs pipeline, resolves tier, writes artifacts,
     updates status.

The two halves are split because the HTTP layer calls enqueue() synchronously
and execute() runs inside the Celery task. Both share the same orchestrator
object so test harness stays simple (call execute() inline — no Celery needed).

All heavy dependencies are injected:
  - run_pipeline_fn(session_id, workspace_id) → PipelineResult
  - evaluate_release_fn(pipeline_result) → ReleaseSessionResult
  - conn_factory() → DB connection (PG wrapper in prod, sqlite3 in tests)
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from track_surface_app.artifacts import ArtifactWriter
from track_surface_app.domain import (
    AnalysisRunStatus,
    ConfidenceLevel,
    PlannerModeAvailability,
    SupportTier,
)
from track_surface_app.gating import OutputGate
from track_surface_app.persistence import AnalysisRunRepository
from track_surface_app.support import SupportTierResolver

logger = logging.getLogger(__name__)


# Keys exposed in pipeline_summary (kept small — this is persisted per-run).
_SAFE_PIPELINE_SUMMARY_FIELDS = (
    "n_samples_total", "n_valid",
    "best_lap", "best_lap_time_s", "n_laps", "track_length_m",
    "field_coverage_pct", "field_mean_confidence",
    "field_high_conf_cells", "field_zero_conf_cells",
    "bucket_active_count", "bucket_sparse_count",
    "planner_nominal_mean_mu", "planner_robust_mean_mu", "planner_exploitable_mean_mu",
    "planner_n_trusted", "planner_n_degraded", "planner_max_robust_penalty",
    "calibration_profile_id", "calibration_source",
    "elapsed_s",
)


def _sanitized_summary(pr: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _SAFE_PIPELINE_SUMMARY_FIELDS:
        val = getattr(pr, key, None)
        if isinstance(val, (int, float, str)) or val is None:
            out[key] = val

    # Stringify the lap-times dict keys (int → str) for JSON-safety.
    lap_times = getattr(pr, "lap_times_s", None) or {}
    out["lap_times_s"] = {str(k): float(v) for k, v in lap_times.items()}
    return out


def _fallback_depth_distribution(pr: Any) -> dict[str, float]:
    """Turn the integer histogram into normalized % by depth key."""
    raw = getattr(pr, "bucket_fallback_distribution", None) or {}
    total = sum(raw.values()) if raw else 0
    if total <= 0:
        return {}
    return {str(k): (v / total) * 100.0 for k, v in raw.items()}


class AnalysisOrchestrator:
    def __init__(
        self,
        *,
        conn_factory: Callable[[], Any],
        artifacts_base_dir: Path | str,
        run_pipeline_fn: Callable[[int, int], Any],
        evaluate_release_fn: Callable[[Any], Any],
        calibration_registry: Any = None,
    ):
        self._conn_factory = conn_factory
        self._artifacts_base_dir = Path(artifacts_base_dir)
        self._run_pipeline_fn = run_pipeline_fn
        self._evaluate_release_fn = evaluate_release_fn
        self._calibration_registry = calibration_registry

    # ── Public API ────────────────────────────────────────────

    def enqueue(
        self,
        *,
        session_id: int,
        workspace_id: int,
        force_rerun: bool = False,
    ) -> str:
        """Create a queued analysis run and return its run_id."""
        conn = self._conn_factory()
        repo = AnalysisRunRepository(conn)
        if not force_rerun and repo.has_in_flight(session_id):
            raise RuntimeError(f"analysis_run_in_flight for session {session_id}")
        run_id = uuid.uuid4().hex
        repo.insert_queued(run_id=run_id, session_id=session_id, workspace_id=workspace_id)
        logger.info("Enqueued analysis run %s for session %s (workspace %s)",
                    run_id, session_id, workspace_id)
        return run_id

    def execute(self, run_id: str) -> None:
        """Run the pipeline synchronously against the given run_id row."""
        conn = self._conn_factory()
        repo = AnalysisRunRepository(conn)
        run = repo.get(run_id)
        if run is None:
            logger.error("execute() called for unknown run_id %s", run_id)
            return

        repo.update_status(run_id, AnalysisRunStatus.RUNNING)
        logger.info("Running analysis %s (session=%s)", run_id, run.session_id)

        try:
            pipeline_result = self._run_pipeline_fn(run.session_id, run.workspace_id)
        except Exception as exc:
            logger.exception("Pipeline execution failed for run %s", run_id)
            repo.mark_failed(run_id=run_id, error_code="INTERNAL_ERROR",
                             error_message=f"pipeline: {exc}")
            return

        try:
            release_result = self._evaluate_release_fn(pipeline_result)
        except Exception as exc:
            logger.exception("Release gate evaluation failed for run %s", run_id)
            repo.mark_failed(run_id=run_id, error_code="INTERNAL_ERROR",
                             error_message=f"release_gate: {exc}")
            return

        tier, reason = SupportTierResolver().resolve(pipeline_result, release_result)
        gate = OutputGate(tier)
        availability = PlannerModeAvailability.for_tier(tier)
        confidence_level = (
            ConfidenceLevel.from_mean_confidence(
                getattr(pipeline_result, "field_mean_confidence", None)
            )
            if tier is not SupportTier.D
            else ConfidenceLevel.UNKNOWN
        )

        try:
            writer = ArtifactWriter(
                self._artifacts_base_dir, run_id=run_id, session_id=run.session_id,
            )
            artifacts_index = writer.write_all(pipeline_result, gate=gate)
        except Exception as exc:
            logger.exception("Artifact writing failed for run %s", run_id)
            repo.mark_failed(run_id=run_id, error_code="INTERNAL_ERROR",
                             error_message=f"artifacts: {exc}")
            return

        repo.mark_succeeded(
            run_id=run_id,
            support_tier=tier,
            support_reason=reason,
            confidence_level=confidence_level,
            fallback_depth_distribution=_fallback_depth_distribution(pipeline_result),
            validated_vehicle_profile=getattr(pipeline_result, "calibration_profile_id", None),
            validated_track_profile=None,   # wired when track registry is exposed
            planner_mode_availability=availability.to_dict(),
            warnings=list(getattr(pipeline_result, "pipeline_warnings", []) or []),
            artifacts_index=artifacts_index,
            release_decision=getattr(getattr(release_result, "decision", None), "value", None),
            pipeline_summary=_sanitized_summary(pipeline_result),
        )
        logger.info("Analysis %s succeeded: tier=%s reason=%s", run_id, tier.value, reason)
