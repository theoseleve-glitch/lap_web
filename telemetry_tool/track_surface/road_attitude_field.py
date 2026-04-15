"""
track_surface/road_attitude_field.py
------------------------------------
Track-position-anchored, multi-lap road attitude estimator.

This module produces ``bank(s)`` and ``grade(s)`` fields — functions of the
Frenet arc-length coordinate ``s`` along the reference line — by aggregating
per-sample evidence across laps.

Why a field, not a per-sample estimate
--------------------------------------
Per-sample bank/grade estimates derived from IMU + GPS have per-sample noise
on the order of several degrees, while real road attitude varies by much
less at the same spatial scale. The previous per-sample
``road_attitude_estimator`` was shown to have std ≈ 10° over a lap, with
mean signal ≈ 1.6°. Applying per-sample correction injected more noise than
it removed.

Road attitude is a property of the *road*, not of the *kart*. A given s-bin
has ONE true bank and ONE true grade. The sensible thing is to collect all
the per-sample evidence that ever passed through that s-bin — across every
lap of every session — and aggregate it robustly. Repeated visits reduce
noise by √N; median/MAD reject transient outliers (kerb strikes,
acceleration spikes) that per-sample smoothing cannot.

Inputs
------
* A list of :class:`LapSamples` (per-lap time series in kart frame).
* A pre-built :class:`FrenetFrame` (centerline + curvature).
* Optional :class:`RoadAttitudeFieldConfig`.

Outputs
-------
A :class:`RoadAttitudeField` with per-s-bin bank, grade, spread, confidence,
evidence count, and lap coverage. All fields live on a uniform s-grid.

Method
------
For each lap sample at position ``s`` with speed ``v``, GPS-derived
curvature ``κ``, lateral accel ``a_lat`` (kart y, left-positive, g units),
and longitudinal accel ``a_lon`` (kart x, forward-positive, g units):

  bank_evidence_deg  = arcsin(clip(a_lat − v²κ/g,   −0.9, +0.9))  [deg]
  grade_evidence_deg = arcsin(clip(dv/dt_g − a_lon, −0.9, +0.9))  [deg]

The sign follows ``road_attitude_estimator``: +bank = left side higher;
+grade = uphill. The grade formula is *not* ``(a_lon − dv/dt_g)`` — that
produces the inverted sign. The accelerometer convention in this codebase
reports the gravity direction (stationary phone with Z up reads
``(0, 0, -1)``), so on +grade uphill the forward axis reads ``-sin(grade)``
and we must negate to recover +grade.

Each sample is gated. Samples that fail a gate do not contribute to the
corresponding field. This is more conservative than downweighting — we
prefer *absent evidence* over *polluted evidence*.

Gates (bank):
  • speed > min_speed_mps
  • |v²κ/g| > bank_min_centripetal_g           (need real centripetal signal)
  • mount not flagged unstable
  • orientation_quality ≥ min_orientation_quality
  • per-sample evidence within |bank_clamp_deg| × 2 (reject absurd spikes)

Gates (grade):
  • speed > min_speed_mps
  • |a_lat| < bank_min_centripetal_g × 2        (no hard cornering)
  • |dv/dt_g| < grade_max_transient_g           (no hard brake/throttle)
  • mount not flagged unstable
  • orientation_quality ≥ min_orientation_quality

Aggregation:
  Per s-bin, per channel (bank and grade independently):
    • Collect every passing sample's evidence into a pool.
    • Also remember which lap each sample came from (for lap_coverage).
    • If #samples ≥ min_samples_per_bin AND #laps ≥ min_laps_per_bin:
        mean = weighted median of the pool (weights = orientation_quality)
        std  = MAD × 1.4826 (robust std estimator)
        confidence = composite(count, lap_coverage, consistency, quality)
    • Otherwise bin is marked unconfident (confidence ≤ 0.2, value = 0°).

Smoothing:
  After per-bin aggregation, mean bank and grade are gently smoothed over
  ``smooth_window_bins`` bins with a simple box filter. Default is 3 bins
  (15 m at 5 m/bin) — enough to suppress per-bin ripple but not enough to
  erase a real banking change across half a track section.

Invariant: this is a *demand-cleaning support product*, not a friction or
grip estimate. The field describes observed kinematics consistent with
road tilt. It does not claim to measure road friction.

Production safety
-----------------
This module does NOT modify bronze or silver demand. It is built for
shadow-mode evaluation. Integration into the demand pipeline requires
separate evidence that correction improves alignment — see
``scripts/validate_road_attitude_field.py``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_G = 9.80665
_MAD_TO_STD = 1.4826    # normal-distribution MAD→std factor


# ─────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────


@dataclass
class LapSamples:
    """One lap's time-series data in **kart frame** (positive y = LEFT,
    positive x = forward). Samples are uniformly spaced in time.

    ``alat_g`` and ``along_g`` must be in *signed* G units with the kart
    frame convention documented in ``road_attitude_estimator.py``. The
    caller is responsible for any mount-frame rotation upstream.
    """

    x: np.ndarray                          # (N,) local meters
    y: np.ndarray                          # (N,) local meters
    speed: np.ndarray                      # (N,) m/s
    alat_g: np.ndarray                     # (N,) signed lateral G, kart y
    along_g: np.ndarray                    # (N,) signed longitudinal G, kart x
    dt: float = 0.04                       # seconds (inverse sample rate)
    orientation_quality: float = 1.0       # 0..1 scalar per lap
    mount_unstable: bool = False           # scalar per lap
    source: str = ''                       # free-form session label


@dataclass
class RoadAttitudeFieldConfig:
    """Tunable thresholds. Defaults are conservative for karts."""

    s_bin_m: float = 5.0
    min_speed_mps: float = 7.0

    # Bank gate: a meaningful centripetal signal is required so bank can
    # be separated from vehicle lateral dynamics.
    bank_min_centripetal_g: float = 0.15

    # Grade gate: vehicle must not be in a hard transient, because grade
    # and longitudinal vehicle accel are confounded.
    grade_max_transient_g: float = 0.25

    # Minimum evidence per bin. Below these → bin is unconfident.
    min_samples_per_bin: int = 15
    min_laps_per_bin: int = 2

    # Physical clamps — karts rarely exceed these even on steep sections.
    bank_clamp_deg: float = 8.0
    grade_clamp_deg: float = 8.0

    # Per-sample evidence outside this multiplier of the clamp is rejected
    # as an outlier before aggregation.
    per_sample_outlier_multiplier: float = 2.0

    # Small spatial smoothing on the aggregated fields. Keep modest to
    # preserve real local structure.
    smooth_window_bins: int = 3

    # Samples from laps below this orientation_quality are excluded.
    min_orientation_quality: float = 0.3

    # Spread scaling used when computing consistency confidence.
    # Smaller → tighter expectation of spread. 2° ≈ "clean" bank estimate.
    consistency_scale_deg_bank: float = 2.0
    consistency_scale_deg_grade: float = 2.0


@dataclass
class RoadAttitudeField:
    """Per-s-bin road attitude estimate with confidence + diagnostics.

    Per-channel fields (``bank_*`` / ``grade_*``) are populated independently
    because the two channels have different gates — a bin can be confident
    for bank and unconfident for grade, or vice versa. The legacy combined
    fields ``confidence``, ``evidence_count``, and ``lap_coverage`` take the
    element-wise max across channels and are kept for backward compatibility.
    """

    s_bins: np.ndarray                      # (M,) bin centers, meters
    bank_mean_deg: np.ndarray               # (M,) robust central tendency
    bank_std_deg: np.ndarray                # (M,) robust spread (MAD-based)
    grade_mean_deg: np.ndarray              # (M,)
    grade_std_deg: np.ndarray               # (M,)
    confidence: np.ndarray                  # (M,) combined 0..1 (max of bank/grade)
    evidence_count: np.ndarray              # (M,) max(bank_count, grade_count)
    lap_coverage: np.ndarray                # (M,) max(bank_laps, grade_laps)
    # Per-channel fields (purely additive — no change to existing consumers)
    bank_confidence: np.ndarray = field(default_factory=lambda: np.array([]))
    bank_evidence_count: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    bank_lap_coverage: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    grade_confidence: np.ndarray = field(default_factory=lambda: np.array([]))
    grade_evidence_count: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    grade_lap_coverage: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    diagnostics: dict = field(default_factory=dict)

    # ── Query helpers ────────────────────────────────────────────

    def bank_at(self, s) -> np.ndarray | float:
        """Linear interpolation of mean bank at query ``s`` (scalar or array)."""
        return self._interp(s, self.bank_mean_deg)

    def grade_at(self, s) -> np.ndarray | float:
        """Linear interpolation of mean grade at query ``s``."""
        return self._interp(s, self.grade_mean_deg)

    def confidence_at(self, s) -> np.ndarray | float:
        """Linear interpolation of confidence at query ``s``."""
        return self._interp(s, self.confidence)

    def _interp(self, s, arr: np.ndarray):
        if self.s_bins.size == 0:
            return 0.0 if np.isscalar(s) else np.zeros_like(np.asarray(s, dtype=float))
        s_arr = np.asarray(s, dtype=float)
        period = float(self.s_bins[-1] - self.s_bins[0] + (self.s_bins[1] - self.s_bins[0]))
        s_wrapped = s_arr % period if period > 0 else s_arr
        out = np.interp(s_wrapped, self.s_bins, arr)
        return float(out) if np.isscalar(s) else out

    def to_dict(self) -> dict:
        """JSON-safe serialization (lists of rounded floats / ints)."""
        def _rf(arr, nd=3):
            return [round(float(v), nd) for v in arr]

        def _ri(arr):
            return [int(v) for v in arr]

        return {
            's_bins': _rf(self.s_bins, 1),
            'bank_mean_deg': _rf(self.bank_mean_deg, 3),
            'bank_std_deg': _rf(self.bank_std_deg, 3),
            'bank_confidence': _rf(self.bank_confidence, 3),
            'bank_evidence_count': _ri(self.bank_evidence_count),
            'bank_lap_coverage': _ri(self.bank_lap_coverage),
            'grade_mean_deg': _rf(self.grade_mean_deg, 3),
            'grade_std_deg': _rf(self.grade_std_deg, 3),
            'grade_confidence': _rf(self.grade_confidence, 3),
            'grade_evidence_count': _ri(self.grade_evidence_count),
            'grade_lap_coverage': _ri(self.grade_lap_coverage),
            # Legacy combined fields for backward compatibility.
            'confidence': _rf(self.confidence, 3),
            'evidence_count': _ri(self.evidence_count),
            'lap_coverage': _ri(self.lap_coverage),
            'diagnostics': self.diagnostics,
        }


# ─────────────────────────────────────────────────────────────────
# Robust aggregation helpers
# ─────────────────────────────────────────────────────────────────


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Weighted median — the value where cumulative weight crosses 0.5.

    Robust to outliers in ``values``; robust to imbalanced weights.
    """
    if len(values) == 0:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    order = np.argsort(values)
    v_sorted = values[order]
    w_sorted = np.clip(weights[order], 0.0, None)
    w_sum = w_sorted.sum()
    if w_sum <= 0:
        return float(np.median(values))
    cum = np.cumsum(w_sorted) / w_sum
    idx = int(np.searchsorted(cum, 0.5))
    return float(v_sorted[min(idx, len(v_sorted) - 1)])


def _mad_std(values: np.ndarray, center: float) -> float:
    """MAD-based robust standard-deviation estimate around a given center.

    Uses the classic Gaussian consistency factor 1.4826.
    """
    if len(values) == 0:
        return 0.0
    return float(_MAD_TO_STD * np.median(np.abs(values - center)))


def _box_smooth(arr: np.ndarray, window: int, valid_mask: np.ndarray) -> np.ndarray:
    """Box-car smoothing that only averages over samples flagged valid.

    Unconfident bins are excluded from their neighbors' averages, preventing
    zeros from bleeding into good regions. Bins outside any valid neighborhood
    are returned unchanged.
    """
    if window <= 1 or arr.size == 0:
        return arr.copy()
    if window % 2 == 0:
        window += 1
    half = window // 2
    n = len(arr)
    out = arr.copy()
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        neigh = valid_mask[lo:hi]
        if neigh.any():
            out[i] = float(np.mean(arr[lo:hi][neigh]))
    return out


# ─────────────────────────────────────────────────────────────────
# Per-lap sample extraction
# ─────────────────────────────────────────────────────────────────


def _curvature_at(frenet: FrenetFrame, s: np.ndarray) -> np.ndarray:
    """Signed curvature at arc-length positions ``s`` — wraps cleanly."""
    s_mod = np.asarray(s, dtype=float) % max(frenet.total_length_m, 1e-9)
    return np.interp(s_mod, frenet.s_grid, frenet.curvature_1pm)


def _extract_lap_evidence(
    lap: LapSamples,
    frenet: FrenetFrame,
    cfg: RoadAttitudeFieldConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Project one lap's samples onto the s-grid and compute per-sample evidence.

    Returns
    -------
    s_idx : (K,) int array — s-bin index per passing sample (may differ
        between bank and grade; we return the *union* mask per channel and
        build two subsets later)
    bank_evidence_deg : (K,) float — per-sample bank
    grade_evidence_deg : (K,) float — per-sample grade
    bank_valid : (K,) bool — sample passes bank gate
    grade_valid : (K,) bool — sample passes grade gate
    """
    n = len(lap.x)
    if n < 50:
        empty = np.array([], dtype=int)
        f = np.array([], dtype=float)
        b = np.array([], dtype=bool)
        return empty, f, f, b, b

    # Project to Frenet s, bin by s_bin_m
    s_arr, _ = frenet.xy_to_sn(lap.x, lap.y)
    s_arr = np.mod(s_arr, frenet.total_length_m) if frenet.total_length_m > 0 else s_arr

    # Per-sample GPS-derived longitudinal accel (g units).
    dt = lap.dt if lap.dt and lap.dt > 0 else 0.04
    dv_dt_g = np.gradient(lap.speed) / dt / _G

    # Per-sample centripetal (g units) from Frenet curvature at current s.
    kappa = _curvature_at(frenet, s_arr)
    centripetal_g = (lap.speed ** 2) * kappa / _G

    # Per-sample attitude evidence (degrees), sign convention documented above.
    # Grade uses dv/dt - along_g (not along_g - dv/dt), matching the sign
    # convention in road_attitude_estimator.py where the accelerometer
    # reports gravity direction, so on +grade uphill along_g ≈ -sin(grade).
    sin_bank = np.clip(lap.alat_g - centripetal_g, -0.9, 0.9)
    sin_grade = np.clip(dv_dt_g - lap.along_g, -0.9, 0.9)
    bank_evidence_deg = np.degrees(np.arcsin(sin_bank))
    grade_evidence_deg = np.degrees(np.arcsin(sin_grade))

    # ── Gates ──
    speed_ok = lap.speed > cfg.min_speed_mps
    mount_ok = (
        (not lap.mount_unstable)
        and (lap.orientation_quality >= cfg.min_orientation_quality)
    )
    not_outlier_bank = np.abs(bank_evidence_deg) <= cfg.bank_clamp_deg * cfg.per_sample_outlier_multiplier
    not_outlier_grade = np.abs(grade_evidence_deg) <= cfg.grade_clamp_deg * cfg.per_sample_outlier_multiplier

    bank_valid = (
        speed_ok
        & (np.abs(centripetal_g) > cfg.bank_min_centripetal_g)
        & not_outlier_bank
    )
    grade_valid = (
        speed_ok
        & (np.abs(lap.alat_g) < cfg.bank_min_centripetal_g * 2.0)       # not hard cornering
        & (np.abs(dv_dt_g) < cfg.grade_max_transient_g)
        & not_outlier_grade
    )
    if not mount_ok:
        bank_valid[:] = False
        grade_valid[:] = False

    # Clamp evidence to the configured physical range for robust aggregation.
    bank_evidence_deg = np.clip(bank_evidence_deg, -cfg.bank_clamp_deg, cfg.bank_clamp_deg)
    grade_evidence_deg = np.clip(grade_evidence_deg, -cfg.grade_clamp_deg, cfg.grade_clamp_deg)

    s_idx = np.floor(s_arr / cfg.s_bin_m).astype(int)
    return s_idx, bank_evidence_deg, grade_evidence_deg, bank_valid, grade_valid


# ─────────────────────────────────────────────────────────────────
# Main estimator
# ─────────────────────────────────────────────────────────────────


def estimate_road_attitude_field(
    laps: Iterable[LapSamples],
    frenet: FrenetFrame,
    config: Optional[RoadAttitudeFieldConfig] = None,
) -> RoadAttitudeField:
    """Aggregate per-lap evidence into a track-space bank/grade field.

    See module docstring for method and invariants.
    """
    cfg = config or RoadAttitudeFieldConfig()
    laps = list(laps)

    total_length = float(frenet.total_length_m)
    if total_length <= 0:
        return _empty_field(cfg)

    s_bin_edges = np.arange(0.0, total_length + cfg.s_bin_m, cfg.s_bin_m)
    s_centers = s_bin_edges[:-1] + cfg.s_bin_m / 2.0
    M = len(s_centers)
    if M == 0:
        return _empty_field(cfg)

    # Accumulators: per-bin lists (keep lap id for coverage).
    bank_samples: list[list[float]] = [[] for _ in range(M)]
    bank_weights: list[list[float]] = [[] for _ in range(M)]
    bank_lap_ids: list[set[int]] = [set() for _ in range(M)]
    grade_samples: list[list[float]] = [[] for _ in range(M)]
    grade_weights: list[list[float]] = [[] for _ in range(M)]
    grade_lap_ids: list[set[int]] = [set() for _ in range(M)]

    n_laps_total = len(laps)
    n_laps_used_bank = 0
    n_laps_used_grade = 0

    for lap_id, lap in enumerate(laps):
        try:
            s_idx, bank_ev, grade_ev, bank_ok, grade_ok = _extract_lap_evidence(
                lap, frenet, cfg,
            )
        except Exception as exc:
            logger.warning("Lap %d (%s) skipped: %s", lap_id, lap.source, exc)
            continue
        if len(s_idx) == 0:
            continue

        # Clamp bin index into the valid range. Out-of-range can happen if
        # a sample wraps past total_length due to GPS noise.
        s_idx = np.clip(s_idx, 0, M - 1)
        weight = float(np.clip(lap.orientation_quality, 0.0, 1.0))

        bank_contributed = False
        grade_contributed = False

        # Bank contributions
        idx_bank = s_idx[bank_ok]
        vals_bank = bank_ev[bank_ok]
        for bi, val in zip(idx_bank, vals_bank):
            bank_samples[bi].append(float(val))
            bank_weights[bi].append(weight)
            bank_lap_ids[bi].add(lap_id)
            bank_contributed = True

        # Grade contributions
        idx_grade = s_idx[grade_ok]
        vals_grade = grade_ev[grade_ok]
        for gi, val in zip(idx_grade, vals_grade):
            grade_samples[gi].append(float(val))
            grade_weights[gi].append(weight)
            grade_lap_ids[gi].add(lap_id)
            grade_contributed = True

        if bank_contributed:
            n_laps_used_bank += 1
        if grade_contributed:
            n_laps_used_grade += 1

    # ── Per-bin aggregation ──
    bank_mean = np.zeros(M)
    bank_std = np.zeros(M)
    grade_mean = np.zeros(M)
    grade_std = np.zeros(M)
    bank_count = np.zeros(M, dtype=int)
    bank_coverage = np.zeros(M, dtype=int)
    grade_count = np.zeros(M, dtype=int)
    grade_coverage = np.zeros(M, dtype=int)
    bank_valid_bin = np.zeros(M, dtype=bool)
    grade_valid_bin = np.zeros(M, dtype=bool)

    # Bank per bin
    for i in range(M):
        vals = bank_samples[i]
        bank_count[i] = len(vals)
        bank_coverage[i] = len(bank_lap_ids[i])
        if len(vals) >= cfg.min_samples_per_bin and len(bank_lap_ids[i]) >= cfg.min_laps_per_bin:
            v_arr = np.asarray(vals, dtype=float)
            w_arr = np.asarray(bank_weights[i], dtype=float)
            m = _weighted_median(v_arr, w_arr)
            m = float(np.clip(m, -cfg.bank_clamp_deg, cfg.bank_clamp_deg))
            bank_mean[i] = m
            bank_std[i] = _mad_std(v_arr, m)
            bank_valid_bin[i] = True

    # Grade per bin
    for i in range(M):
        vals = grade_samples[i]
        grade_count[i] = len(vals)
        grade_coverage[i] = len(grade_lap_ids[i])
        if len(vals) >= cfg.min_samples_per_bin and len(grade_lap_ids[i]) >= cfg.min_laps_per_bin:
            v_arr = np.asarray(vals, dtype=float)
            w_arr = np.asarray(grade_weights[i], dtype=float)
            m = _weighted_median(v_arr, w_arr)
            m = float(np.clip(m, -cfg.grade_clamp_deg, cfg.grade_clamp_deg))
            grade_mean[i] = m
            grade_std[i] = _mad_std(v_arr, m)
            grade_valid_bin[i] = True

    # Combined (legacy) = max across channels
    evidence_count = np.maximum(bank_count, grade_count)
    lap_coverage = np.maximum(bank_coverage, grade_coverage)

    # ── Confidence per channel ──
    bank_confidence = _compute_channel_confidence(
        count=bank_count, coverage=bank_coverage, std=bank_std,
        valid=bank_valid_bin, scale_deg=cfg.consistency_scale_deg_bank,
        n_laps_total=max(1, n_laps_total), cfg=cfg,
    )
    grade_confidence = _compute_channel_confidence(
        count=grade_count, coverage=grade_coverage, std=grade_std,
        valid=grade_valid_bin, scale_deg=cfg.consistency_scale_deg_grade,
        n_laps_total=max(1, n_laps_total), cfg=cfg,
    )
    # Combined (legacy) confidence = max across channels.
    confidence = np.maximum(bank_confidence, grade_confidence)

    # ── Modest spatial smoothing (only on valid bins) ──
    valid_either = bank_valid_bin | grade_valid_bin
    bank_mean = _box_smooth(bank_mean, cfg.smooth_window_bins, bank_valid_bin)
    grade_mean = _box_smooth(grade_mean, cfg.smooth_window_bins, grade_valid_bin)

    diagnostics = {
        's_bin_m': cfg.s_bin_m,
        'n_bins': int(M),
        'n_bins_bank_valid': int(bank_valid_bin.sum()),
        'n_bins_grade_valid': int(grade_valid_bin.sum()),
        'n_bins_any_valid': int(valid_either.sum()),
        'bank_coverage_frac': float(bank_valid_bin.mean()),
        'grade_coverage_frac': float(grade_valid_bin.mean()),
        'n_laps_total': int(n_laps_total),
        'n_laps_used_bank': int(n_laps_used_bank),
        'n_laps_used_grade': int(n_laps_used_grade),
        'mean_lap_coverage_bank': float(
            np.mean([len(s) for s in bank_lap_ids if len(s) > 0]) if any(bank_lap_ids) else 0.0
        ),
        'mean_lap_coverage_grade': float(
            np.mean([len(s) for s in grade_lap_ids if len(s) > 0]) if any(grade_lap_ids) else 0.0
        ),
        'median_bank_std_on_valid_deg': float(
            np.median(bank_std[bank_valid_bin]) if bank_valid_bin.any() else 0.0
        ),
        'median_grade_std_on_valid_deg': float(
            np.median(grade_std[grade_valid_bin]) if grade_valid_bin.any() else 0.0
        ),
        'mean_bank_on_valid_deg': float(
            np.mean(bank_mean[bank_valid_bin]) if bank_valid_bin.any() else 0.0
        ),
        'mean_grade_on_valid_deg': float(
            np.mean(grade_mean[grade_valid_bin]) if grade_valid_bin.any() else 0.0
        ),
        'config': {
            's_bin_m': cfg.s_bin_m,
            'min_speed_mps': cfg.min_speed_mps,
            'bank_min_centripetal_g': cfg.bank_min_centripetal_g,
            'grade_max_transient_g': cfg.grade_max_transient_g,
            'min_samples_per_bin': cfg.min_samples_per_bin,
            'min_laps_per_bin': cfg.min_laps_per_bin,
            'bank_clamp_deg': cfg.bank_clamp_deg,
            'grade_clamp_deg': cfg.grade_clamp_deg,
            'smooth_window_bins': cfg.smooth_window_bins,
            'min_orientation_quality': cfg.min_orientation_quality,
        },
    }

    return RoadAttitudeField(
        s_bins=s_centers,
        bank_mean_deg=bank_mean,
        bank_std_deg=bank_std,
        grade_mean_deg=grade_mean,
        grade_std_deg=grade_std,
        confidence=confidence,
        evidence_count=evidence_count,
        lap_coverage=lap_coverage,
        bank_confidence=bank_confidence,
        bank_evidence_count=bank_count,
        bank_lap_coverage=bank_coverage,
        grade_confidence=grade_confidence,
        grade_evidence_count=grade_count,
        grade_lap_coverage=grade_coverage,
        diagnostics=diagnostics,
    )


def _compute_channel_confidence(
    *,
    count: np.ndarray,
    coverage: np.ndarray,
    std: np.ndarray,
    valid: np.ndarray,
    scale_deg: float,
    n_laps_total: int,
    cfg: RoadAttitudeFieldConfig,
) -> np.ndarray:
    """Per-bin confidence for ONE channel (bank or grade) in [0, 1].

    Components:
      • count_score: saturates at 2 × min_samples_per_bin (more evidence
        helps but plateaus).
      • lap_score:   saturates at min(5, n_laps_total). More laps = more
        independent evidence = higher confidence.
      • consistency_score: higher when robust std is small relative to the
        configured scale.
    Invalid bins (not enough evidence to produce a mean) get confidence ≤ 0.2.
    """
    count_sat = max(1, 2 * cfg.min_samples_per_bin)
    lap_sat = max(1, min(5, n_laps_total))

    count_score = np.clip(count / count_sat, 0.0, 1.0)
    lap_score = np.clip(coverage / lap_sat, 0.0, 1.0)
    consistency = np.where(
        valid,
        np.clip(1.0 - std / scale_deg, 0.0, 1.0),
        0.5,
    )
    confidence = 0.35 * count_score + 0.35 * lap_score + 0.30 * consistency
    confidence = np.where(valid, confidence, np.minimum(confidence, 0.2))
    return np.clip(confidence, 0.0, 1.0)


def _empty_field(cfg: RoadAttitudeFieldConfig) -> RoadAttitudeField:
    empty = np.array([], dtype=float)
    empty_i = np.array([], dtype=int)
    return RoadAttitudeField(
        s_bins=empty,
        bank_mean_deg=empty,
        bank_std_deg=empty,
        grade_mean_deg=empty,
        grade_std_deg=empty,
        confidence=empty,
        evidence_count=empty_i,
        lap_coverage=empty_i,
        diagnostics={'empty': True, 'reason': 'no_data'},
    )
