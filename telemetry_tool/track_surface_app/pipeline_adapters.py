"""Adapter factory — produces the two callables that AnalysisOrchestrator expects.

This is the final seam between the app layer and the frozen research stack.
It is intentionally closure-based: each call to :func:`build_adapters` creates a
pair of functions (``run_pipeline_adapter`` + ``evaluate_release_adapter``) that
share a tiny cache so the ``DatasetEntry`` resolved in the first call is
reusable for metrics computation in the second call — without having to pass
the entry through the orchestrator's public signature.

One factory per analysis run. No module-level state, no cross-run contamination.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from track_surface.validation.harness import PipelineConfig, PipelineResult, run_pipeline
from track_surface.validation.manifest import DatasetEntry
from track_surface.validation.metrics import compute_metrics
from track_surface.validation.release_gate import (
    ReleaseCheck,
    ReleaseDecision,
    ReleaseSessionResult,
    ReleaseThresholds,
    ThresholdProfile,
    evaluate_session,
)

from track_surface_app.session_loader import (
    LoadResult,
    NotSupportedReason,
    SessionLoader,
    SessionNotFoundError,
)

logger = logging.getLogger(__name__)


@dataclass
class AdapterConfig:
    """Runtime configuration for the adapters.

    All paths may be ``None`` in minimal environments — the adapters degrade
    gracefully (no accumulator persistence, default release thresholds).
    """
    release_thresholds_path: str | None = None
    calibration_registry_path: str | None = None
    accumulator_dir: str | None = None


def _stub_pipeline_result_for_unsupported(
    session_id: int, reason: NotSupportedReason, detail: str | None
) -> PipelineResult:
    """Return a minimal PipelineResult that will resolve to Tier D.

    The SupportTierResolver picks Tier D when ``calibration_source`` is not
    ``"registry_active"`` OR when the pipeline hasn't produced track geometry.
    We set ``calibration_source="none"`` explicitly, which is the strongest
    possible signal to the resolver.
    """
    warnings = [f"not_supported:{reason}"]
    if detail:
        warnings.append(f"detail:{detail}")
    return PipelineResult(
        dataset_id=f"saas_session_{session_id}",
        ibt_path="",
        n_samples_total=0,
        n_valid=0,
        n_laps=0,
        track_length_m=0.0,
        calibration_profile_id=None,
        calibration_source="none",
        pipeline_warnings=warnings,
        exception=None,
    )


def _stub_release_result(
    reason: NotSupportedReason, detail: str | None
) -> ReleaseSessionResult:
    """Return a ReleaseSessionResult shaped so the resolver's decision path still
    produces a valid ``.decision.value`` string.

    ``SupportTierResolver`` short-circuits to Tier D before consulting the
    release decision when calibration_source isn't validated, so the exact
    decision value here doesn't change the outcome — but we emit PASS to avoid
    spuriously reporting FAIL when in reality the pipeline never ran.
    """
    return ReleaseSessionResult(
        dataset_id="unsupported",
        track_class="unknown",
        vehicle_class="unknown",
        profile_description=f"skipped:{reason}" + (f":{detail}" if detail else ""),
        decision=ReleaseDecision.PASS,
        checks=[],
        n_pass=0,
        n_warn=0,
        n_fail=0,
    )


@dataclass
class _AdapterState:
    """Tiny scratchpad shared between the two closures for one analysis run."""
    entry: DatasetEntry | None = None
    load_result: LoadResult | None = None
    thresholds: ReleaseThresholds | None = None


def build_adapters(
    *,
    session_loader: SessionLoader,
    config: AdapterConfig,
) -> tuple[Callable[[int, int], PipelineResult], Callable[[PipelineResult], ReleaseSessionResult]]:
    """Produce ``(run_pipeline_adapter, evaluate_release_adapter)``.

    The two adapters share a local ``_AdapterState`` so the ``DatasetEntry``
    resolved during ``run_pipeline_adapter`` can be re-used when computing
    session metrics for release evaluation.

    Each call to ``build_adapters`` returns a fresh pair with a fresh state —
    safe to instantiate once per Celery task invocation.
    """
    state = _AdapterState()

    # ── run_pipeline_adapter ────────────────────────────────

    def run_pipeline_adapter(session_id: int, workspace_id: int) -> PipelineResult:
        load_result = session_loader.load(session_id, workspace_id)
        state.load_result = load_result

        if not load_result.is_supported:
            logger.info(
                "Session %s not supported for track-surface analysis: %s (%s)",
                session_id, load_result.reason, load_result.detail,
            )
            return _stub_pipeline_result_for_unsupported(
                session_id=session_id,
                reason=load_result.reason,
                detail=load_result.detail,
            )

        state.entry = load_result.entry
        pipeline_config = PipelineConfig(
            accumulator_dir=config.accumulator_dir,
            calibration_registry_path=config.calibration_registry_path,
        )
        logger.info("Running track-surface pipeline for session %s (entry=%s)",
                    session_id, load_result.entry.id)
        return run_pipeline(load_result.entry, pipeline_config)

    # ── evaluate_release_adapter ────────────────────────────

    def evaluate_release_adapter(pipeline_result: PipelineResult) -> ReleaseSessionResult:
        # Short-circuit for unsupported sessions — we never built an entry.
        if state.entry is None or state.load_result is None or not state.load_result.is_supported:
            reason = state.load_result.reason if state.load_result else NotSupportedReason("no_entry_cached")
            detail = state.load_result.detail if state.load_result else None
            return _stub_release_result(reason, detail)

        # Real path — compute metrics and run the release gate.
        metrics = compute_metrics(pipeline_result, state.entry)

        if state.thresholds is None:
            state.thresholds = _load_thresholds(config.release_thresholds_path)

        track_class = state.entry.track.regime
        vehicle_class = state.entry.vehicle.klass
        profile: ThresholdProfile = state.thresholds.resolve(
            track_class=track_class, vehicle_class=vehicle_class,
        )
        return evaluate_session(
            metrics,
            profile,
            track_class=track_class,
            vehicle_class=vehicle_class,
        )

    return run_pipeline_adapter, evaluate_release_adapter


def _load_thresholds(path: str | None) -> ReleaseThresholds:
    """Load thresholds from disk, falling back to an empty default profile."""
    if not path:
        return ReleaseThresholds()
    p = Path(path)
    if not p.is_file():
        logger.warning("Release thresholds file not found at %s — using defaults", p)
        return ReleaseThresholds()
    try:
        return ReleaseThresholds.from_json(p)
    except Exception as exc:
        logger.exception("Failed to load thresholds from %s: %s — falling back to defaults",
                         p, exc)
        return ReleaseThresholds()
