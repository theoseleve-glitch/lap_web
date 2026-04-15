"""Warning classifier — turn metrics + expectations into OK/WARN/FAIL flags.

Categories map 1:1 to the failure modes called out in the design brief:

  low_observability         : too few accepted samples / too low coverage
  sparse_bucket             : <2 active condition buckets observed
  excessive_fallback        : too many grid points using global prior
  transition_contamination  : >X% samples in transition quarantine
  tire_model_mismatch       : Fy residual std way above expectation
  road_state_mismatch       : a_lat_tire mean drifts far from raw a_lat
  no_kappa_available        : informational; suppresses some longitudinal expectations
  planner_infeasibility     : robust > nominal anywhere (invariant violation)
  lambda_out_of_band        : median lambda outside per-track band
  racing_line_inverted      : center line lambda lower than off-line
  poor_lap_stability        : per-lap std exceeds expectation

Severity policy:
  - FAIL  : a contractual invariant is violated, or a metric blows past
            the per-dataset expectation.
  - WARN  : the metric is within tolerance but trending toward the
            edge, or a degraded path was used.
  - OK    : everything within bounds (no entry emitted unless verbose).

The classifier never raises. It produces structured ValidationWarnings.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from track_surface.validation.harness import PipelineResult
from track_surface.validation.manifest import DatasetEntry
from track_surface.validation.metrics import SessionMetrics

# ── Severity model ───────────────────────────────────────────


class WarningSeverity(Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"

    def is_at_least(self, other: "WarningSeverity") -> bool:
        order = {WarningSeverity.OK: 0, WarningSeverity.WARN: 1, WarningSeverity.FAIL: 2}
        return order[self] >= order[other]


@dataclass(frozen=True)
class ValidationWarning:
    """One classified observation about a session run."""
    category: str
    severity: WarningSeverity
    metric: str
    value: float
    threshold: float
    message: str

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity.value,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "message": self.message,
        }


# ── Hard-coded thresholds (intentional, traceable) ───────────

_BUCKET_ACTIVE_WARN: Final[int] = 2
_BUCKET_ACTIVE_FAIL: Final[int] = 1
_FALLBACK_DEPTH_2_WARN_PCT: Final[float] = 30.0
_FALLBACK_DEPTH_2_FAIL_PCT: Final[float] = 60.0
_TRANSITION_WARN_PCT: Final[float] = 20.0
_TRANSITION_FAIL_PCT: Final[float] = 40.0
_LAMBDA_IN_BAND_WARN_PCT: Final[float] = 50.0
_LAMBDA_IN_BAND_FAIL_PCT: Final[float] = 0.0  # band-out median
_RACING_LINE_LIFT_FAIL: Final[float] = -0.05  # center > off line by at least this much
_RACING_LINE_LIFT_WARN: Final[float] = 0.0
_LOW_ACCEPT_WARN_PCT: Final[float] = 30.0
_LOW_ACCEPT_FAIL_PCT: Final[float] = 10.0


# ── Classifier ───────────────────────────────────────────────


def classify_warnings(
    metrics: SessionMetrics,
    entry: DatasetEntry,
    *,
    result: PipelineResult | None = None,
    verbose: bool = False,
) -> list[ValidationWarning]:
    """Generate warnings for one session.

    Parameters
    ----------
    metrics : computed SessionMetrics
    entry   : the manifest entry the metrics were computed against
    result  : optional full PipelineResult — needed only for invariant
              checks that need raw planner outputs (robust > nominal)
    verbose : if True, emit OK entries too (default False — only WARN/FAIL)
    """
    warnings: list[ValidationWarning] = []

    # ── Catastrophic exception ───────────────────────────────
    if not metrics.pipeline_succeeded:
        warnings.append(ValidationWarning(
            category="pipeline_exception",
            severity=WarningSeverity.FAIL,
            metric="exception",
            value=0.0,
            threshold=0.0,
            message=metrics.exception or "Pipeline did not produce a lambda estimate",
        ))
        # Bail early — downstream metrics are zero-valued
        return warnings

    # ── Observability ────────────────────────────────────────
    if metrics.accept_pct < _LOW_ACCEPT_FAIL_PCT:
        warnings.append(ValidationWarning(
            category="low_observability",
            severity=WarningSeverity.FAIL,
            metric="accept_pct",
            value=metrics.accept_pct,
            threshold=_LOW_ACCEPT_FAIL_PCT,
            message=f"Only {metrics.accept_pct:.1f}% of subsampled blocks produced lambda — the inverse solver is rejecting nearly everything",
        ))
    elif metrics.accept_pct < _LOW_ACCEPT_WARN_PCT:
        warnings.append(ValidationWarning(
            category="low_observability",
            severity=WarningSeverity.WARN,
            metric="accept_pct",
            value=metrics.accept_pct,
            threshold=_LOW_ACCEPT_WARN_PCT,
            message=f"Acceptance rate {metrics.accept_pct:.1f}% is below {_LOW_ACCEPT_WARN_PCT:.0f}% — limited excitation in this session",
        ))

    if metrics.coverage_pct < entry.expected.min_field_coverage_pct:
        warnings.append(ValidationWarning(
            category="low_observability",
            severity=WarningSeverity.WARN,
            metric="coverage_pct",
            value=metrics.coverage_pct,
            threshold=entry.expected.min_field_coverage_pct,
            message=f"Field coverage {metrics.coverage_pct:.1f}% below expected {entry.expected.min_field_coverage_pct:.1f}%",
        ))

    # ── Bucket health ────────────────────────────────────────
    if metrics.bucket_active_count <= _BUCKET_ACTIVE_FAIL:
        warnings.append(ValidationWarning(
            category="sparse_bucket",
            severity=WarningSeverity.FAIL,
            metric="bucket_active_count",
            value=float(metrics.bucket_active_count),
            threshold=float(_BUCKET_ACTIVE_FAIL),
            message=f"Only {metrics.bucket_active_count} active bucket(s) — fallback degenerates into the global prior",
        ))
    elif metrics.bucket_active_count <= _BUCKET_ACTIVE_WARN:
        warnings.append(ValidationWarning(
            category="sparse_bucket",
            severity=WarningSeverity.WARN,
            metric="bucket_active_count",
            value=float(metrics.bucket_active_count),
            threshold=float(_BUCKET_ACTIVE_WARN),
            message=f"Bucket activity is thin ({metrics.bucket_active_count} active) — section/phase separation may not be meaningful",
        ))

    if metrics.fallback_depth_2_pct >= _FALLBACK_DEPTH_2_FAIL_PCT:
        warnings.append(ValidationWarning(
            category="excessive_fallback",
            severity=WarningSeverity.FAIL,
            metric="fallback_depth_2_pct",
            value=metrics.fallback_depth_2_pct,
            threshold=_FALLBACK_DEPTH_2_FAIL_PCT,
            message=f"{metrics.fallback_depth_2_pct:.1f}% of grid points fall back to the global prior — bucketed field is essentially unused",
        ))
    elif metrics.fallback_depth_2_pct >= _FALLBACK_DEPTH_2_WARN_PCT:
        warnings.append(ValidationWarning(
            category="excessive_fallback",
            severity=WarningSeverity.WARN,
            metric="fallback_depth_2_pct",
            value=metrics.fallback_depth_2_pct,
            threshold=_FALLBACK_DEPTH_2_WARN_PCT,
            message=f"{metrics.fallback_depth_2_pct:.1f}% of grid points use the global prior",
        ))

    # ── Transition contamination ─────────────────────────────
    if metrics.transition_quarantine_pct >= _TRANSITION_FAIL_PCT:
        warnings.append(ValidationWarning(
            category="transition_contamination",
            severity=WarningSeverity.FAIL,
            metric="transition_quarantine_pct",
            value=metrics.transition_quarantine_pct,
            threshold=_TRANSITION_FAIL_PCT,
            message=f"{metrics.transition_quarantine_pct:.1f}% of samples are in banking transition — too much data is being thrown away",
        ))
    elif metrics.transition_quarantine_pct >= _TRANSITION_WARN_PCT:
        warnings.append(ValidationWarning(
            category="transition_contamination",
            severity=WarningSeverity.WARN,
            metric="transition_quarantine_pct",
            value=metrics.transition_quarantine_pct,
            threshold=_TRANSITION_WARN_PCT,
            message=f"Transition quarantine claims {metrics.transition_quarantine_pct:.1f}% of samples",
        ))

    # ── Lambda band check ────────────────────────────────────
    band_lo, band_hi = entry.expected.lambda_band
    if metrics.lambda_median < band_lo or metrics.lambda_median > band_hi:
        warnings.append(ValidationWarning(
            category="lambda_out_of_band",
            severity=WarningSeverity.FAIL,
            metric="lambda_median",
            value=metrics.lambda_median,
            threshold=band_lo if metrics.lambda_median < band_lo else band_hi,
            message=f"Lambda median {metrics.lambda_median:.3f} sits outside the expected band [{band_lo:.2f}, {band_hi:.2f}] — likely tire-model or road-state mismatch",
        ))
    elif metrics.lambda_in_band_pct < _LAMBDA_IN_BAND_WARN_PCT:
        warnings.append(ValidationWarning(
            category="lambda_out_of_band",
            severity=WarningSeverity.WARN,
            metric="lambda_in_band_pct",
            value=metrics.lambda_in_band_pct,
            threshold=_LAMBDA_IN_BAND_WARN_PCT,
            message=f"Only {metrics.lambda_in_band_pct:.1f}% of the lambda distribution lies inside the expected band",
        ))

    # ── Tire model mismatch (residual std) ───────────────────
    if metrics.fy_residual_std > entry.expected.max_fy_residual_std:
        warnings.append(ValidationWarning(
            category="tire_model_mismatch",
            severity=WarningSeverity.WARN,
            metric="fy_residual_std",
            value=metrics.fy_residual_std,
            threshold=entry.expected.max_fy_residual_std,
            message=f"Fy residual std {metrics.fy_residual_std:.0f} N exceeds expected {entry.expected.max_fy_residual_std:.0f} N — tire model fit is poor for this car",
        ))

    # ── Road state mismatch ──────────────────────────────────
    if result is not None:
        a_lat_drift = abs(result.a_lat_tire_mean - result.a_lat_raw_mean)
        if a_lat_drift > 3.0:  # more than 3 m/s² difference in mean
            warnings.append(ValidationWarning(
                category="road_state_mismatch",
                severity=WarningSeverity.WARN,
                metric="a_lat_drift",
                value=float(a_lat_drift),
                threshold=3.0,
                message=f"|a_lat_tire - a_lat_raw|_mean = {a_lat_drift:.2f} m/s² — road-state estimator is removing a large lateral bias; verify banking estimate",
            ))

    # ── No kappa (informational) ─────────────────────────────
    if not entry.session.kappa_available:
        warnings.append(ValidationWarning(
            category="no_kappa_available",
            severity=WarningSeverity.WARN,
            metric="kappa_available",
            value=0.0,
            threshold=1.0,
            message="No wheel slip ratio (kappa) — longitudinal lambda is uninformed; only lateral excitation is used",
        ))

    # ── Racing line structure ────────────────────────────────
    if metrics.racing_line_lift < _RACING_LINE_LIFT_FAIL:
        warnings.append(ValidationWarning(
            category="racing_line_inverted",
            severity=WarningSeverity.FAIL,
            metric="racing_line_lift",
            value=metrics.racing_line_lift,
            threshold=_RACING_LINE_LIFT_FAIL,
            message=f"Center-line lambda is {-metrics.racing_line_lift:.3f} BELOW off-line — surface field is upside-down here",
        ))
    elif metrics.racing_line_lift < entry.expected.racing_line_lift_min:
        warnings.append(ValidationWarning(
            category="racing_line_inverted",
            severity=WarningSeverity.WARN,
            metric="racing_line_lift",
            value=metrics.racing_line_lift,
            threshold=entry.expected.racing_line_lift_min,
            message=f"Racing line lift {metrics.racing_line_lift:+.3f} below expected {entry.expected.racing_line_lift_min:+.3f}",
        ))

    # ── Lap stability ────────────────────────────────────────
    if metrics.lap_to_lap_std > entry.expected.max_lap_to_lap_std:
        warnings.append(ValidationWarning(
            category="poor_lap_stability",
            severity=WarningSeverity.WARN,
            metric="lap_to_lap_std",
            value=metrics.lap_to_lap_std,
            threshold=entry.expected.max_lap_to_lap_std,
            message=f"Per-lap lambda std {metrics.lap_to_lap_std:.3f} exceeds expected {entry.expected.max_lap_to_lap_std:.3f}",
        ))

    # ── Planner invariant: robust ≤ nominal ──────────────────
    if metrics.planner_robust_mean > metrics.planner_nominal_mean + 1e-6:
        warnings.append(ValidationWarning(
            category="planner_infeasibility",
            severity=WarningSeverity.FAIL,
            metric="robust_minus_nominal",
            value=metrics.planner_robust_mean - metrics.planner_nominal_mean,
            threshold=0.0,
            message="Planner invariant violated: robust mean μ > nominal mean μ",
        ))

    # ── Planner invariant: exploitable ≤ nominal ─────────────
    if metrics.planner_exploitable_mean > metrics.planner_nominal_mean + 1e-6:
        warnings.append(ValidationWarning(
            category="planner_infeasibility",
            severity=WarningSeverity.FAIL,
            metric="exploitable_minus_nominal",
            value=metrics.planner_exploitable_mean - metrics.planner_nominal_mean,
            threshold=0.0,
            message="Planner invariant violated: exploitable mean μ > nominal mean μ",
        ))

    # ── Optional verbose OK entries ──────────────────────────
    if verbose and not any(w.severity == WarningSeverity.FAIL for w in warnings):
        warnings.append(ValidationWarning(
            category="overall",
            severity=WarningSeverity.OK,
            metric="status",
            value=1.0,
            threshold=1.0,
            message="All checks passed",
        ))

    return warnings


def overall_severity(warnings: list[ValidationWarning]) -> WarningSeverity:
    """Reduce a list of warnings to the worst severity present."""
    if any(w.severity == WarningSeverity.FAIL for w in warnings):
        return WarningSeverity.FAIL
    if any(w.severity == WarningSeverity.WARN for w in warnings):
        return WarningSeverity.WARN
    return WarningSeverity.OK
