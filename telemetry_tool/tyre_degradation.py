"""
tyre_degradation.py
-------------------
Tyre grip evolution model for improved robustness scoring.

Separates mechanical grip degradation from driver fatigue so the
robustness scorer can distinguish "the tyres gave up" from "the driver
gave up".

Architecture
~~~~~~~~~~~~
1.  **Per-lap grip extraction** â€” for each lap, extract the peak lateral
    and braking accelerations achieved (robust 95th-percentile).
2.  **Grip trend fitting** â€” linear regression on per-lap peak-g values
    to quantify degradation rate.
3.  **Thermal warm-up detection** â€” identify the number of laps until
    grip peaks (tyre warm-up / scrub-in phase).
4.  **Stint-level friction models** â€” build a ``FrictionCircle`` for
    early / mid / late stints and compare the ellipse area shrinkage.
5.  **Robustness integration** â€” export a ``grip_adjustment_factor``
    that ``scoring._score_robustness`` uses to discount pace fade
    attributable to tyre degradation.

Public API
~~~~~~~~~~
- ``compute_grip_evolution(resampled_laps, lap_times, ...)``
- ``compute_stint_friction_models(resampled_laps, ...)``
- ``grip_adjusted_fade(fade_frac, grip_evolution)``
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================================

# Column conventions

# =============================================================================


_COL_SPEED:    Final[str] = "Speed (m/s)"
_COL_DIST:     Final[str] = "Distance (m)"
_COL_LAT_G:    Final[str] = "Lateral acceleration (G) *calc"
_COL_LONG_G:   Final[str] = "Longitudinal acceleration (G) *calc"
_COL_LAT_MPS2: Final[str] = "accel_lat_mps2"
_COL_LONG_MPS2: Final[str] = "accel_long_mps2"

_G: Final[float] = 9.80665

# =============================================================================

# Defaults

# =============================================================================


_DEFAULT_WINDOW:     Final[int]   = 3      # rolling-average window for smoothing per-lap peaks
_DEFAULT_PERCENTILE: Final[float] = 95.0   # percentile for peak-g extraction
_DEFAULT_N_STINTS:   Final[int]   = 3      # early / mid / late
_MIN_LAPS_FOR_TREND: Final[int]   = 4      # need â‰¥ 4 laps for meaningful regression

# Grip-drop thresholds for robustness adjustment

GRIP_DROP_TYRE_LIMITED_PCT:  Final[float] = 10.0   # â‰¥ 10 % drop â†’ tyre-limited
GRIP_DROP_MECHANICAL_PCT:    Final[float] = 3.0    # < 3 % â†’ not tyre-related
WARMUP_SEARCH_LAPS:          Final[int]   = 6      # max laps to scan for warm-up peak


# =============================================================================

# Data structures

# =============================================================================


class TyreDegradationError(ValueError):
    """Raised on invalid input or insufficient data."""


@dataclass
class GripEvolution:
    """Per-lap grip evolution analysis.

    Attributes
    ----------
    peak_lateral_g_per_lap : list[float]
        95th-percentile lateral acceleration per lap [G].
    peak_braking_g_per_lap : list[float]
        95th-percentile braking deceleration per lap [G].
    grip_trend_lateral : float
        Linear-fit slope of lateral g vs lap number [G/lap].
        Negative = degradation.
    grip_trend_braking : float
        Linear-fit slope of braking g vs lap number [G/lap].
    estimated_grip_drop_pct : float
        Total estimated grip loss from peak to final lap [%].
        Averaged across lateral and braking.
    thermal_phase_laps : int
        Number of laps until grip first peaks (tyre warm-up).
        0 if grip peaks on the first lap.
    degradation_rate_pct_per_lap : float
        Mean grip loss rate after warm-up phase [%/lap].
    n_laps : int
        Total laps analysed.
    lap_numbers : list[int]
        Lap keys in order.
    """

    peak_lateral_g_per_lap:       list[float] = field(default_factory=list)
    peak_braking_g_per_lap:       list[float] = field(default_factory=list)
    grip_trend_lateral:           float = 0.0
    grip_trend_braking:           float = 0.0
    estimated_grip_drop_pct:      float = 0.0
    thermal_phase_laps:           int = 0
    degradation_rate_pct_per_lap: float = 0.0
    n_laps:                       int = 0
    lap_numbers:                  list[int] = field(default_factory=list)
    track_evolution_pct:          float = 0.0
    grip_direction:               str = "stable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "peak_lateral_g_per_lap":       [round(v, 4) for v in self.peak_lateral_g_per_lap],
            "peak_braking_g_per_lap":       [round(v, 4) for v in self.peak_braking_g_per_lap],
            "grip_trend_lateral":           round(self.grip_trend_lateral, 6),
            "grip_trend_braking":           round(self.grip_trend_braking, 6),
            "estimated_grip_drop_pct":      round(self.estimated_grip_drop_pct, 2),
            "track_evolution_pct":          round(self.track_evolution_pct, 2),
            "grip_direction":               self.grip_direction,
            "thermal_phase_laps":           self.thermal_phase_laps,
            "degradation_rate_pct_per_lap": round(self.degradation_rate_pct_per_lap, 3),
            "n_laps":                       self.n_laps,
            "lap_numbers":                  list(self.lap_numbers),
        }

    @property
    def is_tyre_limited(self) -> bool:
        """True if grip drop exceeds the tyre-limited threshold."""
        return self.estimated_grip_drop_pct >= GRIP_DROP_TYRE_LIMITED_PCT

    @property
    def is_grip_stable(self) -> bool:
        """True if grip drop is below the mechanical threshold."""
        return self.estimated_grip_drop_pct < GRIP_DROP_MECHANICAL_PCT

    @property
    def is_track_improving(self) -> bool:
        """True if grip is increasing (track evolution, not degradation)."""
        return self.grip_direction == "improving"

    @property
    def is_mixed(self) -> bool:
        """True if track improving while tyres degrading (net unclear)."""
        return self.grip_direction == "mixed"


@dataclass
class StintFrictionComparison:
    """Comparison of friction ellipses across stints.

    Attributes
    ----------
    stint_labels : list[str]
        ``["early", "mid", "late"]`` (or subset).
    stint_lap_ranges : list[tuple[int, int]]
        ``(first_lap, last_lap)`` for each stint.
    lateral_max_per_stint : list[float]
        Mean of ``lateral_max(v_grid)`` for each stint's model [m/s²].
    braking_max_per_stint : list[float]
        Mean of ``braking_max(v_grid)`` for each stint's model [m/s²].
    area_shrinkage_pct : float
        Estimated ellipse area reduction from first to last stint [%].
    """

    stint_labels:            list[str] = field(default_factory=list)
    stint_lap_ranges:        list[tuple[int, int]] = field(default_factory=list)
    lateral_max_per_stint:   list[float] = field(default_factory=list)
    braking_max_per_stint:   list[float] = field(default_factory=list)
    area_shrinkage_pct:      float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stint_labels":          list(self.stint_labels),
            "stint_lap_ranges":      [list(r) for r in self.stint_lap_ranges],
            "lateral_max_per_stint": [round(v, 4) for v in self.lateral_max_per_stint],
            "braking_max_per_stint": [round(v, 4) for v in self.braking_max_per_stint],
            "area_shrinkage_pct":    round(self.area_shrinkage_pct, 2),
        }


# =============================================================================

# Internal helpers

# =============================================================================


def _extract_lateral_g(df: pd.DataFrame) -> np.ndarray:
    """Extract absolute lateral acceleration in G from a lap DataFrame."""
    for col, scale in [(_COL_LAT_MPS2, 1.0 / _G), (_COL_LAT_G, 1.0)]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values.astype(float)
            return np.abs(vals) * scale
    return np.array([], dtype=float)


def _extract_braking_g(df: pd.DataFrame) -> np.ndarray:
    """Extract braking deceleration in G (positive) from a lap DataFrame."""
    for col, scale in [(_COL_LONG_MPS2, 1.0 / _G), (_COL_LONG_G, 1.0)]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values.astype(float)
            # Braking is negative longitudinal accel â†’ take abs of negatives

            braking = np.where(vals < 0, np.abs(vals), 0.0)
            return braking * scale
    return np.array([], dtype=float)


def _peak_percentile(arr: np.ndarray, pct: float = _DEFAULT_PERCENTILE) -> float:
    """Robust peak extraction: return the *pct*-th percentile of finite values."""
    finite = arr[np.isfinite(arr)]
    if len(finite) < 3:
        return float("nan")
    return float(np.percentile(finite, pct))


def _linear_slope(y: np.ndarray) -> float:
    """Slope of a simple least-squares linear fit of y vs index."""
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    mask = np.isfinite(y)
    if mask.sum() < 2:
        return 0.0
    xm = x[mask]
    ym = y[mask]
    x_mean = xm.mean()
    y_mean = ym.mean()
    denom = float(((xm - x_mean) ** 2).sum())
    if denom < 1e-12:
        return 0.0
    return float(((xm - x_mean) * (ym - y_mean)).sum() / denom)


def _detect_warmup_peak(values: list[float], max_search: int = WARMUP_SEARCH_LAPS) -> int:
    """
    Find the lap number (0-indexed) at which grip first peaks.

    Scans the first *max_search* laps for the maximum value.  If the
    peak is on lap 0 there is no warm-up phase.

    Returns
    -------
    int
        0-indexed lap of peak grip.  0 = no warm-up detected.
    """
    if len(values) < 2:
        return 0
    search = values[:min(len(values), max_search)]
    finite = [(i, v) for i, v in enumerate(search) if math.isfinite(v)]
    if not finite:
        return 0
    peak_idx = max(finite, key=lambda t: t[1])[0]
    return peak_idx


# =============================================================================

# Public API

# =============================================================================


def compute_grip_evolution(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    *,
    window: int = _DEFAULT_WINDOW,
    percentile: float = _DEFAULT_PERCENTILE,
) -> GripEvolution:
    """
    Compute per-lap grip evolution from telemetry.

    Parameters
    ----------
    resampled_laps:
        ``{lap_number: DataFrame}`` with accel channels.
    lap_times:
        Lap times in lap-number order (used for correspondence only).
    window:
        Rolling-average window for smoothing per-lap peaks.
    percentile:
        Percentile used for robust peak-g extraction.

    Returns
    -------
    GripEvolution
    """
    sorted_keys = sorted(resampled_laps.keys())
    n_laps = len(sorted_keys)

    if n_laps < 2:
        return GripEvolution(n_laps=n_laps, lap_numbers=list(sorted_keys))

    # --- Extract per-lap peaks -- -

    lat_peaks: list[float] = []
    brk_peaks: list[float] = []

    for key in sorted_keys:
        df = resampled_laps[key]
        lat_g = _extract_lateral_g(df)
        brk_g = _extract_braking_g(df)
        lat_peaks.append(_peak_percentile(lat_g, percentile))
        brk_peaks.append(_peak_percentile(brk_g, percentile))

    # --- Optional smoothing
    def _smooth(vals: list[float], w: int) -> list[float]:
        if w <= 1 or len(vals) < w:
            return vals
        arr = np.array(vals, dtype=float)
        kernel = np.ones(w) / w
        # Pad edges to avoid shrinking

        padded = np.pad(arr, (w // 2, w // 2), mode="edge")
        smoothed = np.convolve(padded, kernel, mode="valid")[:len(arr)]
        return smoothed.tolist()

    lat_smooth = _smooth(lat_peaks, window)
    brk_smooth = _smooth(brk_peaks, window)

    # --- Trend fitting -- -

    lat_arr = np.array(lat_smooth, dtype=float)
    brk_arr = np.array(brk_smooth, dtype=float)

    trend_lat = _linear_slope(lat_arr)
    trend_brk = _linear_slope(brk_arr)

    # --- Thermal warm-up detection -- -

    warmup_lat = _detect_warmup_peak(lat_smooth)
    warmup_brk = _detect_warmup_peak(brk_smooth)
    thermal_phase = max(warmup_lat, warmup_brk)

    # --- Estimated total grip drop (peak â†’ final lap)
    def _drop_pct(vals: list[float], warmup_idx: int) -> float:
        """Compute % drop from peak (at warmup_idx) to final value."""
        finite = [(i, v) for i, v in enumerate(vals) if math.isfinite(v)]
        if len(finite) < 2:
            return 0.0
        peak_val = max(v for _, v in finite[:max(warmup_idx + 1, 1)])
        # Average of last 2 laps for stability

        final_vals = [v for _, v in finite[-min(2, len(finite)):]]
        final_val = float(np.mean(final_vals))
        if peak_val <= 0:
            return 0.0
        return max(0.0, (peak_val - final_val) / peak_val * 100.0)

    drop_lat = _drop_pct(lat_smooth, thermal_phase)
    drop_brk = _drop_pct(brk_smooth, thermal_phase)
    raw_drop = (drop_lat + drop_brk) / 2.0

    # --- Classify grip direction -- -

    # Positive trends = grip increasing = track improving

    # Negative trends = grip decreasing = tyre degradation

    avg_trend = (trend_lat + trend_brk) / 2.0

    # Compute trend-based evolution: how much did grip change in total?

    # Use mean peak grip as baseline for percentage calculation

    all_peaks = [v for v in lat_smooth + brk_smooth if math.isfinite(v)]
    mean_peak = float(np.mean(all_peaks)) if all_peaks else 1.0
    trend_total_pct = abs(avg_trend * (n_laps - 1)) / max(mean_peak, 0.01) * 100.0

    if avg_trend > 0.001 and trend_total_pct > 2.0:
        # Grip is INCREASING over the session

        if raw_drop > GRIP_DROP_MECHANICAL_PCT:
            # Mixed: trends say improving but peak-to-final shows drop

            # (warm-up then tyre wear while track improves)

            track_evolution_pct = trend_total_pct
            estimated_drop = raw_drop
            grip_direction = "mixed"
        else:
            # Clear improvement: track evolution, not degradation

            track_evolution_pct = trend_total_pct
            estimated_drop = 0.0
            grip_direction = "improving"
    elif avg_trend < -0.001 and raw_drop >= GRIP_DROP_MECHANICAL_PCT:
        # Grip DECREASING = tyre degradation

        track_evolution_pct = 0.0
        estimated_drop = raw_drop
        grip_direction = "degrading"
    elif raw_drop >= GRIP_DROP_MECHANICAL_PCT:
        # Drop detected but trend ambiguous

        track_evolution_pct = 0.0
        estimated_drop = raw_drop
        grip_direction = "degrading"
    else:
        # Stable: no significant trend or drop

        track_evolution_pct = max(0.0, trend_total_pct) if avg_trend > 0 else 0.0
        estimated_drop = raw_drop
        grip_direction = "stable"

    # --- Degradation rate after warm-up
    post_warmup_laps = n_laps - thermal_phase
    if post_warmup_laps > 1 and estimated_drop > 0:
        deg_rate = estimated_drop / post_warmup_laps
    else:
        deg_rate = 0.0

    result = GripEvolution(
        peak_lateral_g_per_lap=lat_smooth,
        peak_braking_g_per_lap=brk_smooth,
        grip_trend_lateral=trend_lat,
        grip_trend_braking=trend_brk,
        estimated_grip_drop_pct=round(estimated_drop, 2),
        track_evolution_pct=round(track_evolution_pct, 2),
        grip_direction=grip_direction,
        thermal_phase_laps=thermal_phase,
        degradation_rate_pct_per_lap=round(deg_rate, 3),
        n_laps=n_laps,
        lap_numbers=list(sorted_keys),
    )

    logger.info(
        "Grip evolution: %d laps, warm-up=%d laps, direction=%s, "
        "lat_trend=%.4f G/lap, brk_trend=%.4f G/lap, "
        "degradation=%.1f%%, track_evo=%.1f%%, rate=%.2f%%/lap",
        n_laps, thermal_phase, grip_direction,
        trend_lat, trend_brk,
        estimated_drop, track_evolution_pct, deg_rate,
    )
    return result


def compute_stint_friction_models(
    resampled_laps: dict[int, pd.DataFrame],
    *,
    n_stints: int = _DEFAULT_N_STINTS,
) -> StintFrictionComparison:
    """
    Build friction models for early / mid / late stints and compare.

    The shrinkage of the friction ellipse across stints quantifies
    tyre degradation at the vehicle-dynamics level.

    Parameters
    ----------
    resampled_laps:
        ``{lap_number: DataFrame}``.
    n_stints:
        Number of stints to divide laps into (default 3).

    Returns
    -------
    StintFrictionComparison
    """
    sorted_keys = sorted(resampled_laps.keys())
    n_laps = len(sorted_keys)

    if n_laps < n_stints * 2:
        # Not enough laps for meaningful stint comparison

        return StintFrictionComparison()

    # --- Split laps into stints
    stint_size = n_laps // n_stints
    labels = ["early", "mid", "late"][:n_stints]
    stint_ranges: list[tuple[int, int]] = []
    stint_lap_dicts: list[dict[int, pd.DataFrame]] = []

    for i in range(n_stints):
        start_idx = i * stint_size
        end_idx = (i + 1) * stint_size if i < n_stints - 1 else n_laps
        keys = sorted_keys[start_idx:end_idx]
        stint_ranges.append((keys[0], keys[-1]))
        stint_lap_dicts.append({k: resampled_laps[k] for k in keys})

    # --- Build friction model per stint
    # Try importing friction_model; if unavailable, fall back to manual extraction

    try:
        import friction_model as fm
        _has_fm = True
    except ImportError:
        _has_fm = False

    lat_maxes: list[float] = []
    brk_maxes: list[float] = []

    if _has_fm:
        for stint_laps in stint_lap_dicts:
            try:
                fc = fm.build_friction_model(stint_laps)
                # Mean of grip envelope across speed range

                lat_maxes.append(float(np.mean(fc.lateral_vals)) / _G)
                brk_maxes.append(float(np.mean(fc.braking_vals)) / _G)
            except Exception as exc:
                logger.warning("Stint friction model failed: %s", exc)
                lat_maxes.append(float("nan"))
                brk_maxes.append(float("nan"))
    else:
        # Manual fallback: extract peak g per stint

        for stint_laps in stint_lap_dicts:
            all_lat: list[float] = []
            all_brk: list[float] = []
            for df in stint_laps.values():
                lat = _extract_lateral_g(df)
                brk = _extract_braking_g(df)
                if len(lat) > 0:
                    all_lat.append(_peak_percentile(lat))
                if len(brk) > 0:
                    all_brk.append(_peak_percentile(brk))
            lat_maxes.append(float(np.mean(all_lat)) if all_lat else float("nan"))
            brk_maxes.append(float(np.mean(all_brk)) if all_brk else float("nan"))

    # --- Compute area shrinkage
    # Friction ellipse area ~ Ï€ * a_lat * a_brk

    # Shrinkage = 1 - (late_area / early_area)

    finite_lat = [v for v in lat_maxes if math.isfinite(v)]
    finite_brk = [v for v in brk_maxes if math.isfinite(v)]

    area_shrinkage = 0.0
    if len(finite_lat) >= 2 and len(finite_brk) >= 2:
        early_area = finite_lat[0] * finite_brk[0]
        late_area  = finite_lat[-1] * finite_brk[-1]
        if early_area > 0:
            area_shrinkage = (1.0 - late_area / early_area) * 100.0

    return StintFrictionComparison(
        stint_labels=labels,
        stint_lap_ranges=stint_ranges,
        lateral_max_per_stint=lat_maxes,
        braking_max_per_stint=brk_maxes,
        area_shrinkage_pct=round(area_shrinkage, 2),
    )


def grip_adjusted_fade(
    fade_frac: float,
    grip_evolution: Optional[GripEvolution],
) -> float:
    """
    Adjust the pace-fade fraction by discounting tyre degradation.

    When grip drops significantly, the driver cannot maintain the same
    lap times even with perfect concentration.  This function returns an
    adjusted fade value that isolates the *driver-attributable* fade.

    Logic
    ~~~~~
    - ``grip_drop â‰¥ 10 %`` â†’ tyre-limited; halve the fade penalty.
    - ``grip_drop âˆˆ [3 %, 10 %)`` â†’ partial: scale discount linearly.
    - ``grip_drop < 3 %`` â†’ not tyre-related; no discount.

    Parameters
    ----------
    fade_frac:
        Raw pace fade fraction (late_mean - early_mean) / early_mean.
    grip_evolution:
        Output of :func:`compute_grip_evolution`.  ``None`` â†’ no adjustment.

    Returns
    -------
    float
        Adjusted fade fraction (always â‰¤ original).
    """
    if grip_evolution is None or math.isnan(fade_frac):
        return fade_frac

    grip_drop = grip_evolution.estimated_grip_drop_pct

    if grip_drop < GRIP_DROP_MECHANICAL_PCT:
        # Not tyre related â€” full penalty

        return fade_frac

    if grip_drop >= GRIP_DROP_TYRE_LIMITED_PCT:
        # Heavily tyre-limited â€” halve the penalty

        discount = 0.50
    else:
        # Partial: linearly interpolate discount from 0 â†’ 0.50

        t = (grip_drop - GRIP_DROP_MECHANICAL_PCT) / (
            GRIP_DROP_TYRE_LIMITED_PCT - GRIP_DROP_MECHANICAL_PCT
        )
        discount = t * 0.50

    adjusted = fade_frac * (1.0 - discount)
    logger.debug(
        "Grip-adjusted fade: raw=%.4f, grip_drop=%.1f%%, "
        "discount=%.2f, adjusted=%.4f",
        fade_frac, grip_drop, discount, adjusted,
    )
    return adjusted


# =============================================================================

# Self-test

# =============================================================================


def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Synthetic data -- -


    N_LAPS = 15
    N_PTS  = 300

    def _make_laps(
        n_laps: int = N_LAPS,
        degrade_pct: float = 0.0,
        seed: int = 42,
    ) -> dict[int, pd.DataFrame]:
        """Create synthetic resampled laps with controllable degradation.

        *degrade_pct*: total lateral grip loss from first to last lap (0â€“100).
        """
        rng = np.random.default_rng(seed)
        laps: dict[int, pd.DataFrame] = {}
        dist = np.linspace(0, 600, N_PTS, endpoint=False)

        for i in range(n_laps):
            t_frac = i / max(n_laps - 1, 1)
            grip_factor = 1.0 - (degrade_pct / 100.0) * t_frac

            speed = 20 + 8 * np.sin(2 * np.pi * dist / 600) + rng.normal(0, 0.3, N_PTS)
            speed = np.clip(speed, 5, 35)
            lat_g = (1.2 * grip_factor + rng.normal(0, 0.05, N_PTS))
            lat_g = np.clip(np.abs(lat_g) * np.abs(np.sin(2 * np.pi * dist / 600)), 0, 2.0)
            long_g = rng.normal(0, 0.3, N_PTS)
            # Add braking zones (negative)

            brake_zones = (dist > 100) & (dist < 150) | (dist > 400) & (dist < 450)
            long_g[brake_zones] = -(1.0 * grip_factor + rng.normal(0, 0.05, brake_zones.sum()))

            laps[i + 1] = pd.DataFrame({
                _COL_DIST:     dist,
                _COL_SPEED:    speed,
                _COL_LAT_MPS2: lat_g * _G,
                _COL_LONG_MPS2: long_g * _G,
            })

        return laps

    def _make_times(n: int = N_LAPS, base: float = 30.0, fade: float = 0.0) -> list[float]:
        return [base + fade * i / max(n - 1, 1) for i in range(n)]

    # -- Tests

    def t_extract_lateral_g():
        df = pd.DataFrame({_COL_LAT_MPS2: [9.81, 4.9, -9.81, 0]})
        g = _extract_lateral_g(df)
        assert len(g) == 4
        assert abs(g[0] - 1.0) < 0.01
        assert abs(g[2] - 1.0) < 0.01  # absolute value

    _test("extract_lateral_g", t_extract_lateral_g)

    def t_extract_lateral_g_from_G_col():
        df = pd.DataFrame({_COL_LAT_G: [1.2, 0.5, -0.8]})
        g = _extract_lateral_g(df)
        assert abs(g[0] - 1.2) < 0.01

    _test("extract_lateral_g_from_G_col", t_extract_lateral_g_from_G_col)

    def t_extract_braking_g():
        df = pd.DataFrame({_COL_LONG_MPS2: [-9.81, 4.9, -4.905, 0]})
        g = _extract_braking_g(df)
        assert abs(g[0] - 1.0) < 0.01
        assert g[1] == 0.0  # traction, not braking
        assert abs(g[2] - 0.5) < 0.01

    _test("extract_braking_g", t_extract_braking_g)

    def t_linear_slope_positive():
        y = np.array([1.0, 2.0, 3.0, 4.0])
        s = _linear_slope(y)
        assert abs(s - 1.0) < 0.01

    _test("linear_slope_positive", t_linear_slope_positive)

    def t_linear_slope_negative():
        y = np.array([4.0, 3.0, 2.0, 1.0])
        s = _linear_slope(y)
        assert abs(s - (-1.0)) < 0.01

    _test("linear_slope_negative", t_linear_slope_negative)

    def t_linear_slope_flat():
        y = np.array([5.0, 5.0, 5.0, 5.0])
        s = _linear_slope(y)
        assert abs(s) < 0.001

    _test("linear_slope_flat", t_linear_slope_flat)

    def t_detect_warmup_lap0():
        vals = [1.5, 1.4, 1.3, 1.2]  # peak at lap 0
        assert _detect_warmup_peak(vals) == 0

    _test("detect_warmup_lap0", t_detect_warmup_lap0)

    def t_detect_warmup_lap2():
        vals = [1.0, 1.3, 1.5, 1.4, 1.3]  # peak at lap 2
        assert _detect_warmup_peak(vals) == 2

    _test("detect_warmup_lap2", t_detect_warmup_lap2)

    def t_grip_evolution_stable():
        laps = _make_laps(degrade_pct=0.0)
        times = _make_times()
        ev = compute_grip_evolution(laps, times)
        assert ev.n_laps == N_LAPS
        assert len(ev.peak_lateral_g_per_lap) == N_LAPS
        assert len(ev.peak_braking_g_per_lap) == N_LAPS
        assert ev.estimated_grip_drop_pct < 5.0, (
            f"Stable tyres should show < 5% drop, got {ev.estimated_grip_drop_pct}%"
        )
        assert ev.is_grip_stable

    _test("grip_evolution_stable", t_grip_evolution_stable)

    def t_grip_evolution_degrading():
        laps = _make_laps(degrade_pct=20.0, seed=99)
        times = _make_times(fade=2.0)
        ev = compute_grip_evolution(laps, times)
        assert ev.estimated_grip_drop_pct > 5.0, (
            f"20% degrade should show > 5% drop, got {ev.estimated_grip_drop_pct}%"
        )
        assert ev.grip_trend_lateral < 0, (
            f"Degrading tyres should have negative lateral trend: {ev.grip_trend_lateral}"
        )
        assert ev.is_tyre_limited or ev.estimated_grip_drop_pct >= 8.0

    _test("grip_evolution_degrading", t_grip_evolution_degrading)

    def t_grip_evolution_few_laps():
        laps = {1: list(_make_laps(n_laps=1).values())[0]}
        ev = compute_grip_evolution(laps, [30.0])
        assert ev.n_laps == 1
        assert ev.estimated_grip_drop_pct == 0.0

    _test("grip_evolution_few_laps", t_grip_evolution_few_laps)

    def t_grip_evolution_to_dict():
        ev = GripEvolution(
            peak_lateral_g_per_lap=[1.2, 1.15, 1.1],
            peak_braking_g_per_lap=[1.3, 1.25, 1.2],
            grip_trend_lateral=-0.05,
            grip_trend_braking=-0.05,
            estimated_grip_drop_pct=8.5,
            thermal_phase_laps=1,
            degradation_rate_pct_per_lap=4.25,
            n_laps=3,
            lap_numbers=[1, 2, 3],
        )
        d = ev.to_dict()
        assert d["n_laps"] == 3
        assert d["estimated_grip_drop_pct"] == 8.5
        assert len(d["peak_lateral_g_per_lap"]) == 3

    _test("grip_evolution_to_dict", t_grip_evolution_to_dict)

    def t_stint_comparison_basic():
        laps = _make_laps(n_laps=12, degrade_pct=15.0)
        result = compute_stint_friction_models(laps, n_stints=3)
        assert len(result.stint_labels) == 3
        assert result.stint_labels == ["early", "mid", "late"]
        assert len(result.lateral_max_per_stint) == 3
        assert len(result.braking_max_per_stint) == 3

    _test("stint_comparison_basic", t_stint_comparison_basic)

    def t_stint_comparison_few_laps():
        laps = _make_laps(n_laps=3)
        result = compute_stint_friction_models(laps, n_stints=3)
        # 3 laps < 3*2 = 6 minimum

        assert len(result.stint_labels) == 0

    _test("stint_comparison_few_laps", t_stint_comparison_few_laps)

    def t_stint_comparison_degrading():
        laps = _make_laps(n_laps=12, degrade_pct=25.0, seed=77)
        result = compute_stint_friction_models(laps, n_stints=3)
        # Late stint lateral should be lower than early

        if (math.isfinite(result.lateral_max_per_stint[0]) and
                math.isfinite(result.lateral_max_per_stint[-1])):
            assert result.lateral_max_per_stint[-1] <= result.lateral_max_per_stint[0] * 1.05, (
                f"Late stint lateral should be <= early: "
                f"{result.lateral_max_per_stint[-1]:.3f} vs {result.lateral_max_per_stint[0]:.3f}"
            )

    _test("stint_comparison_degrading", t_stint_comparison_degrading)

    def t_stint_comparison_to_dict():
        result = StintFrictionComparison(
            stint_labels=["early", "late"],
            stint_lap_ranges=[(1, 5), (6, 10)],
            lateral_max_per_stint=[1.2, 1.0],
            braking_max_per_stint=[1.3, 1.1],
            area_shrinkage_pct=15.5,
        )
        d = result.to_dict()
        assert d["area_shrinkage_pct"] == 15.5

    _test("stint_comparison_to_dict", t_stint_comparison_to_dict)

    def t_grip_adjusted_fade_none():
        assert grip_adjusted_fade(0.05, None) == 0.05

    _test("grip_adjusted_fade_none", t_grip_adjusted_fade_none)

    def t_grip_adjusted_fade_no_degradation():
        ev = GripEvolution(estimated_grip_drop_pct=1.0)
        adjusted = grip_adjusted_fade(0.05, ev)
        assert adjusted == 0.05, "No discount for < 3% grip drop"

    _test("grip_adjusted_fade_no_degradation", t_grip_adjusted_fade_no_degradation)

    def t_grip_adjusted_fade_tyre_limited():
        ev = GripEvolution(estimated_grip_drop_pct=15.0)
        raw_fade = 0.04
        adjusted = grip_adjusted_fade(raw_fade, ev)
        assert adjusted < raw_fade, "Tyre-limited should reduce penalty"
        assert abs(adjusted - 0.02) < 0.001, f"Expected ~0.02, got {adjusted}"

    _test("grip_adjusted_fade_tyre_limited", t_grip_adjusted_fade_tyre_limited)

    def t_grip_adjusted_fade_partial():
        ev = GripEvolution(estimated_grip_drop_pct=6.5)
        raw_fade = 0.04
        adjusted = grip_adjusted_fade(raw_fade, ev)
        assert 0 < adjusted < raw_fade

    _test("grip_adjusted_fade_partial", t_grip_adjusted_fade_partial)

    def t_grip_adjusted_fade_nan():
        ev = GripEvolution(estimated_grip_drop_pct=10.0)
        assert math.isnan(grip_adjusted_fade(float("nan"), ev))

    _test("grip_adjusted_fade_nan", t_grip_adjusted_fade_nan)

    def t_is_tyre_limited_property():
        assert GripEvolution(estimated_grip_drop_pct=12.0).is_tyre_limited
        assert not GripEvolution(estimated_grip_drop_pct=5.0).is_tyre_limited

    _test("is_tyre_limited_property", t_is_tyre_limited_property)

    def t_is_grip_stable_property():
        assert GripEvolution(estimated_grip_drop_pct=1.0).is_grip_stable
        assert not GripEvolution(estimated_grip_drop_pct=5.0).is_grip_stable

    _test("is_grip_stable_property", t_is_grip_stable_property)

    def t_warmup_reflected_in_evolution():
        """Construct laps where grip ramps up then degrades."""
        rng = np.random.default_rng(55)
        laps: dict[int, pd.DataFrame] = {}
        dist = np.linspace(0, 500, 200)
        # Warm-up for 3 laps, then degrade

        for i in range(10):
            if i < 3:
                grip = 0.8 + 0.2 * (i / 2)
            else:
                grip = 1.2 - 0.05 * (i - 3)
            lat = np.abs(grip * np.sin(2 * np.pi * dist / 500)) + rng.normal(0, 0.02, 200)
            long = rng.normal(0, 0.2, 200)
            brake_zone = (dist > 100) & (dist < 150)
            long[brake_zone] = -grip + rng.normal(0, 0.02, brake_zone.sum())

            laps[i + 1] = pd.DataFrame({
                _COL_DIST: dist,
                _COL_SPEED: np.full(200, 20.0),
                _COL_LAT_MPS2: lat * _G,
                _COL_LONG_MPS2: long * _G,
            })

        ev = compute_grip_evolution(laps, _make_times(10))
        assert ev.thermal_phase_laps >= 1, (
            f"Should detect warm-up, got thermal_phase={ev.thermal_phase_laps}"
        )

    _test("warmup_reflected_in_evolution", t_warmup_reflected_in_evolution)

    def t_degradation_rate():
        laps = _make_laps(n_laps=12, degrade_pct=20.0, seed=88)
        ev = compute_grip_evolution(laps, _make_times(12))
        assert ev.degradation_rate_pct_per_lap > 0.0, (
            f"Should have positive deg rate, got {ev.degradation_rate_pct_per_lap}"
        )

    _test("degradation_rate", t_degradation_rate)

    def t_empty_accel_columns():
        """Laps with no accel data should produce zeroed peaks."""
        laps = {
            1: pd.DataFrame({_COL_DIST: [0, 100, 200], _COL_SPEED: [20, 25, 20]}),
            2: pd.DataFrame({_COL_DIST: [0, 100, 200], _COL_SPEED: [20, 24, 20]}),
        }
        ev = compute_grip_evolution(laps, [30.0, 31.0])
        assert ev.n_laps == 2
        # Peaks should be NaN since no accel columns

        assert all(math.isnan(v) for v in ev.peak_lateral_g_per_lap)

    _test("empty_accel_columns", t_empty_accel_columns)

    def t_scoring_integration_format():
        """Output is compatible with _score_robustness metrics dict."""
        laps = _make_laps(degrade_pct=12.0)
        ev = compute_grip_evolution(laps, _make_times())

        # The pipeline would add these to the metrics dict

        fade_frac = 0.03  # 3% pace fade
        adjusted = grip_adjusted_fade(fade_frac, ev)

        # This would go into _score_robustness as the fade value

        assert isinstance(adjusted, float)
        assert 0 <= adjusted <= fade_frac

    _test("scoring_integration_format", t_scoring_integration_format)

    def t_grip_evolution_improving():
        """When grip increases over the session, should report track evolution."""
        rng_imp = np.random.default_rng(111)
        laps: dict[int, pd.DataFrame] = {}
        dist = np.linspace(0, 600, N_PTS, endpoint=False)
        for i in range(12):
            # Grip increases from 0.8 to 1.2 over 12 laps (drying track)

            grip = 0.8 + 0.4 * i / 11
            lat_g = np.clip(np.abs(grip + rng_imp.normal(0, 0.03, N_PTS))
                            * np.abs(np.sin(2 * np.pi * dist / 600)), 0, 2.0)
            long_g = rng_imp.normal(0, 0.2, N_PTS)
            brake_zones = (dist > 100) & (dist < 150) | (dist > 400) & (dist < 450)
            long_g[brake_zones] = -(grip + rng_imp.normal(0, 0.03, brake_zones.sum()))
            laps[i + 1] = pd.DataFrame({
                _COL_DIST: dist, _COL_SPEED: np.full(N_PTS, 22.0),
                _COL_LAT_MPS2: lat_g * _G, _COL_LONG_MPS2: long_g * _G,
            })
        ev = compute_grip_evolution(laps, _make_times(12))
        assert ev.grip_direction == "improving", (
            f"Expected improving, got {ev.grip_direction}"
        )
        assert ev.track_evolution_pct > 0, (
            f"Should have positive track_evolution_pct, got {ev.track_evolution_pct}"
        )
        assert ev.estimated_grip_drop_pct == 0.0, (
            f"Degradation should be clamped to 0 for improving grip, "
            f"got {ev.estimated_grip_drop_pct}"
        )

    _test("grip_evolution_improving", t_grip_evolution_improving)

    def t_grip_evolution_to_dict_has_new_fields():
        ev = GripEvolution(
            track_evolution_pct=6.5,
            grip_direction="improving",
            estimated_grip_drop_pct=0.0,
        )
        d = ev.to_dict()
        assert d["track_evolution_pct"] == 6.5
        assert d["grip_direction"] == "improving"
        assert d["estimated_grip_drop_pct"] == 0.0
        assert ev.is_track_improving
        assert not ev.is_tyre_limited

    _test("grip_evolution_to_dict_has_new_fields", t_grip_evolution_to_dict_has_new_fields)

    # -- Summary
    total = len(passed) + len(failed)
    print(f"\nTyre Degradation Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
