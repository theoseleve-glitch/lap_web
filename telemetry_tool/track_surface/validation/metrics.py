"""Metrics aggregation — turn a PipelineResult into a SessionMetrics.

Splits the PipelineResult into three coherent groups:

  Physics quality    — does the inverse solver produce believable lambda?
  Field quality      — does the surface field have decent coverage + confidence?
  Structure          — does it find the racing line / bucket separation?
  Planner            — do nominal/robust/exploitable agree with each other?
  Stability          — does lap-to-lap noise stay bounded?

These metrics are computed from PipelineResult fields only — no
re-running the pipeline. Pure functions, easy to unit-test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from track_surface.validation.harness import PipelineResult
from track_surface.validation.manifest import DatasetEntry


# ── Metrics record ───────────────────────────────────────────


@dataclass
class SessionMetrics:
    """Computed metrics for one validation run."""

    dataset_id: str
    group: str
    track_name: str
    vehicle_name: str

    # ── Physics ──────────────────────────────────────────────
    lambda_median: float
    lambda_mean: float
    lambda_std: float
    lambda_p5: float
    lambda_p95: float
    lambda_in_band_pct: float          # share within expected band
    fy_residual_std: float
    fx_residual_std: float
    accept_pct: float                  # accepted / (accepted + rejected) * 100

    # ── Field quality ────────────────────────────────────────
    coverage_pct: float
    cells_high_conf: int
    cells_zero_conf: int
    mean_confidence: float
    max_obs_per_cell: int

    # ── Bucket health ────────────────────────────────────────
    bucket_active_count: int
    bucket_sparse_count: int
    fallback_depth_distribution: dict[int, int]
    fallback_depth_2_pct: float        # share of grid points using global prior
    transition_quarantine_pct: float

    # ── Structure ────────────────────────────────────────────
    racing_line_lift: float            # center - mean(left, right)
    flat_vs_banked_lambda_diff: float | None  # None if track has no banking

    # ── Planner ──────────────────────────────────────────────
    planner_nominal_mean: float
    planner_robust_mean: float
    planner_exploitable_mean: float
    planner_robust_tightening: float    # nominal - robust
    planner_exploitable_lift: float     # exploitable - robust
    planner_trusted_pct: float          # of total grid points
    planner_max_robust_penalty: float

    # ── Stability ────────────────────────────────────────────
    lap_to_lap_std: float
    n_laps_used: int

    # ── Bookkeeping ──────────────────────────────────────────
    elapsed_s: float
    pipeline_succeeded: bool
    pipeline_warnings: list[str] = field(default_factory=list)
    exception: str | None = None

    # ── Persistence layer (only set if accumulator was wired) ──
    calibration_profile_id: str | None = None
    calibration_source: str | None = None
    accumulator_key: str | None = None
    accumulator_n_sessions_after: int = 0
    merge_outcome: str | None = None
    accumulated_fallback_depth_2_pct: float | None = None     # the WIN metric
    accumulated_evidence_source_counts: dict[str, int] = field(default_factory=dict)
    fallback_reduction_pct: float | None = None               # current_only_fb2 - accumulated_fb2

    def to_dict(self) -> dict[str, Any]:
        """Plain dict suitable for JSON dumping."""
        d = self.__dict__.copy()
        # Convert dict[int, int] keys to strings for JSON
        d["fallback_depth_distribution"] = {
            str(k): int(v) for k, v in self.fallback_depth_distribution.items()
        }
        d["pipeline_warnings"] = list(self.pipeline_warnings)
        return d


# ── Computation ──────────────────────────────────────────────


def _share_in_band(
    median: float, p5: float, p95: float, band: tuple[float, float],
) -> float:
    """Approximate share of the lambda distribution inside the band.

    We don't have the full sample array (kept out of PipelineResult to
    save memory), so we approximate from the percentile summary.

    If the band fully covers [p5, p95] we report ~90% (the base coverage
    of p5..p95). If the median is outside the band, we report 0.
    Otherwise, linear interpolation against the percentile bracket.
    """
    lo, hi = band
    if median < lo or median > hi:
        return 0.0

    # Coarse: how much of [p5, p95] sits inside [lo, hi]?
    span = max(p95 - p5, 1e-6)
    inside_lo = max(p5, lo)
    inside_hi = min(p95, hi)
    inside_share = max(0.0, (inside_hi - inside_lo) / span) * 0.9  # 0.9 = p5..p95 coverage
    # Add a small bonus when the median sits well inside the band
    band_center = 0.5 * (lo + hi)
    band_half = 0.5 * (hi - lo)
    if band_half > 0:
        center_score = max(0.0, 1.0 - abs(median - band_center) / band_half) * 0.1
    else:
        center_score = 0.0
    return float(min(1.0, inside_share + center_score) * 100.0)


def _compute_lap_to_lap_std(lap_lambdas: dict[int, float]) -> tuple[float, int]:
    """Standard deviation of per-lap mean lambda."""
    if len(lap_lambdas) < 2:
        return 0.0, len(lap_lambdas)
    vals = list(lap_lambdas.values())
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return float(var ** 0.5), len(vals)


def _flat_vs_banked_diff(bucket_diagnostics: dict[str, dict]) -> float | None:
    """If both flat and banked buckets have data, return |mean_diff|.

    We average across all phases (early/mid/late) within each section
    to produce one number per regime.
    """
    flat_means = []
    banked_means = []
    for key, stats in bucket_diagnostics.items():
        if not isinstance(stats, dict) or stats.get("n_cells", 0) == 0:
            continue
        lm = stats.get("lambda_mean")
        if lm is None:
            continue
        if key.startswith("flat/"):
            flat_means.append(float(lm))
        elif key.startswith("banked/"):
            banked_means.append(float(lm))

    if not flat_means or not banked_means:
        return None
    flat_avg = sum(flat_means) / len(flat_means)
    banked_avg = sum(banked_means) / len(banked_means)
    return float(abs(flat_avg - banked_avg))


def compute_metrics(result: PipelineResult, entry: DatasetEntry) -> SessionMetrics:
    """Aggregate a PipelineResult into a SessionMetrics.

    Pure function — no I/O, no pipeline re-execution.
    """
    # ── Lambda in-band ───────────────────────────────────────
    in_band_pct = _share_in_band(
        median=result.lambda_median,
        p5=result.lambda_p5,
        p95=result.lambda_p95,
        band=entry.expected.lambda_band,
    )

    # ── Accept rate ──────────────────────────────────────────
    total_blocks = result.n_accepted_blocks + result.n_rejected_blocks
    accept_pct = (
        100.0 * result.n_accepted_blocks / max(total_blocks, 1)
    )

    # ── Racing line lift ─────────────────────────────────────
    off_line_avg = 0.5 * (result.racing_line_left_lambda + result.racing_line_right_lambda)
    racing_line_lift = float(result.racing_line_center_lambda - off_line_avg)

    # ── Bucket fallback share ────────────────────────────────
    fb = result.bucket_fallback_distribution
    total_grid = sum(fb.values()) if fb else 0
    fb2_pct = (100.0 * fb.get(2, 0) / max(total_grid, 1)) if total_grid else 0.0

    # ── Planner derived ──────────────────────────────────────
    robust_tightening = float(
        result.planner_nominal_mean_mu - result.planner_robust_mean_mu
    )
    exploitable_lift = float(
        result.planner_exploitable_mean_mu - result.planner_robust_mean_mu
    )
    n_grid = max(
        result.planner_n_trusted
        + result.planner_n_degraded
        + result.planner_n_transition_excluded,
        1,
    )
    trusted_pct = 100.0 * result.planner_n_trusted / n_grid

    # ── Lap-to-lap stability ─────────────────────────────────
    l2l_std, n_laps_used = _compute_lap_to_lap_std(result.lap_lambdas)

    # ── Flat vs banked lambda separation ─────────────────────
    fb_diff = _flat_vs_banked_diff(result.bucket_diagnostics)

    # ── Accumulator-aware fallback metrics ───────────────────
    accumulated_fb2_pct: float | None = None
    fallback_reduction_pct: float | None = None
    if result.accumulated_fallback_distribution:
        afd = result.accumulated_fallback_distribution
        total_a = sum(afd.values())
        if total_a > 0:
            accumulated_fb2_pct = 100.0 * afd.get(2, 0) / total_a
            fallback_reduction_pct = fb2_pct - accumulated_fb2_pct

    return SessionMetrics(
        dataset_id=result.dataset_id,
        group=entry.group,
        track_name=entry.track.name,
        vehicle_name=entry.vehicle.name,
        # Physics
        lambda_median=result.lambda_median,
        lambda_mean=result.lambda_mean,
        lambda_std=result.lambda_std,
        lambda_p5=result.lambda_p5,
        lambda_p95=result.lambda_p95,
        lambda_in_band_pct=in_band_pct,
        fy_residual_std=result.fy_residual_std,
        fx_residual_std=result.fx_residual_std,
        accept_pct=accept_pct,
        # Field
        coverage_pct=result.field_coverage_pct,
        cells_high_conf=result.field_high_conf_cells,
        cells_zero_conf=result.field_zero_conf_cells,
        mean_confidence=result.field_mean_confidence,
        max_obs_per_cell=result.field_max_obs_per_cell,
        # Bucket
        bucket_active_count=result.bucket_active_count,
        bucket_sparse_count=result.bucket_sparse_count,
        fallback_depth_distribution=dict(result.bucket_fallback_distribution),
        fallback_depth_2_pct=fb2_pct,
        transition_quarantine_pct=result.transition_pct,
        # Structure
        racing_line_lift=racing_line_lift,
        flat_vs_banked_lambda_diff=fb_diff,
        # Planner
        planner_nominal_mean=result.planner_nominal_mean_mu,
        planner_robust_mean=result.planner_robust_mean_mu,
        planner_exploitable_mean=result.planner_exploitable_mean_mu,
        planner_robust_tightening=robust_tightening,
        planner_exploitable_lift=exploitable_lift,
        planner_trusted_pct=trusted_pct,
        planner_max_robust_penalty=result.planner_max_robust_penalty,
        # Stability
        lap_to_lap_std=l2l_std,
        n_laps_used=n_laps_used,
        # Persistence layer
        calibration_profile_id=result.calibration_profile_id,
        calibration_source=result.calibration_source,
        accumulator_key=result.accumulator_key,
        accumulator_n_sessions_after=result.accumulator_n_sessions_after,
        merge_outcome=result.merge_outcome,
        accumulated_fallback_depth_2_pct=accumulated_fb2_pct,
        accumulated_evidence_source_counts=dict(result.accumulated_evidence_source_counts),
        fallback_reduction_pct=fallback_reduction_pct,
        # Bookkeeping
        elapsed_s=result.elapsed_s,
        pipeline_succeeded=result.succeeded,
        pipeline_warnings=list(result.pipeline_warnings),
        exception=result.exception,
    )
