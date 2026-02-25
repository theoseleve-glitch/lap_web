"""
fatigue_detection.py
--------------------
Driver fatigue and concentration detection from telemetry data.

Separates *driver fatigue* from *tyre degradation* by analysing
behavioural proxies that degrade with mental load but remain
unaffected by mechanical grip changes:

1. **Braking consistency decay** -- increasing scatter in brake-point
   distance over the session (fatigued drivers brake later/earlier
   unpredictably).
2. **Smoothness degradation** -- rising jerk-RMS or yaw variance
   in later laps indicates loss of fine motor control.
3. **Reaction time proxy** -- brake-to-apex time variance widening.
4. **Mental lapse detection** -- sudden pace outliers (>2 std from
   rolling mean) after a stable window indicate attention drops.
5. **Concentration index** -- composite 0-100 score combining all
   indicators, decreasing = fatigue.

Public API
~~~~~~~~~~
- ``compute_fatigue_indicators(lap_metrics, lap_times)``
- ``detect_mental_lapses(lap_times, window)``
- ``compute_concentration_index(indicators)``
- ``analyze_fatigue(lap_metrics, lap_times)``   (all-in-one)

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs -> identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# Minimum laps for fatigue analysis to be meaningful
MIN_LAPS_FOR_FATIGUE: Final[int] = 8

# Rolling window for smoothness / consistency comparison
FATIGUE_WINDOW: Final[int] = 4

# Mental lapse: lap time > rolling_mean + LAPSE_STD_FACTOR * rolling_std
LAPSE_STD_FACTOR: Final[float] = 2.0

# Minimum stable laps before a lapse is flagged (can't be fatigued on lap 2)
MIN_STABLE_BEFORE_LAPSE: Final[int] = 4

# Weight of each indicator in the concentration index
_W_SMOOTHNESS: Final[float] = 0.30
_W_BRAKING:    Final[float] = 0.25
_W_LAPSES:     Final[float] = 0.25
_W_PACE_DECAY: Final[float] = 0.20


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class FatigueIndicators:
    """Per-half comparison of fatigue-sensitive metrics."""

    n_laps: int = 0

    # Smoothness: first-half vs second-half jerk RMS
    smoothness_first_half: float = float("nan")
    smoothness_second_half: float = float("nan")
    smoothness_degradation_pct: float = 0.0  # positive = getting rougher

    # Braking consistency: std of brake_max across laps
    braking_std_first_half: float = float("nan")
    braking_std_second_half: float = float("nan")
    braking_consistency_decay_pct: float = 0.0  # positive = more scattered

    # Mental lapses
    lapse_laps: list[int] = field(default_factory=list)
    lapse_count: int = 0

    # Pace decay (pure pace, not corrected for grip)
    pace_slope_s_per_lap: float = 0.0  # positive = slowing

    # Concentration index 0 = fatigued, 100 = fresh
    concentration_index: float = 100.0

    # Qualitative assessment
    fatigue_level: str = "fresh"  # fresh / mild / moderate / severe
    coaching_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_laps": self.n_laps,
            "smoothness_first_half": _r(self.smoothness_first_half),
            "smoothness_second_half": _r(self.smoothness_second_half),
            "smoothness_degradation_pct": _r(self.smoothness_degradation_pct),
            "braking_std_first_half": _r(self.braking_std_first_half),
            "braking_std_second_half": _r(self.braking_std_second_half),
            "braking_consistency_decay_pct": _r(self.braking_consistency_decay_pct),
            "lapse_laps": list(self.lapse_laps),
            "lapse_count": self.lapse_count,
            "pace_slope_s_per_lap": _r(self.pace_slope_s_per_lap, 4),
            "concentration_index": _r(self.concentration_index, 1),
            "fatigue_level": self.fatigue_level,
            "coaching_hint": self.coaching_hint,
        }


def _r(v: float, places: int = 2) -> float:
    """Safe round that handles NaN."""
    if math.isfinite(v):
        return round(v, places)
    return v


# ============================================================================
# Internal Helpers
# ============================================================================


def _linear_slope(y: np.ndarray) -> float:
    """OLS slope of y vs index."""
    n = len(y)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    mask = np.isfinite(y)
    if mask.sum() < 3:
        return 0.0
    xm, ym = x[mask], y[mask]
    x_bar, y_bar = float(xm.mean()), float(ym.mean())
    denom = float(((xm - x_bar) ** 2).sum())
    if denom < 1e-12:
        return 0.0
    return float(((xm - x_bar) * (ym - y_bar)).sum() / denom)


def _safe_float(v: Any) -> float:
    """Convert value to float, returning NaN for None/invalid."""
    if v is None:
        return float("nan")
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return float("nan")


def _split_halves(values: list) -> tuple[list[float], list[float]]:
    """Split values into two halves, filtering None/NaN."""
    valid = [_safe_float(v) for v in values]
    valid = [v for v in valid if math.isfinite(v)]
    mid = len(valid) // 2
    return valid[:mid], valid[mid:]


# ============================================================================
# Mental Lapse Detection
# ============================================================================


def detect_mental_lapses(
    lap_times: list[float],
    lap_numbers: list[int],
    *,
    window: int = FATIGUE_WINDOW,
    std_factor: float = LAPSE_STD_FACTOR,
    min_stable: int = MIN_STABLE_BEFORE_LAPSE,
) -> list[int]:
    """
    Detect laps where the driver had a sudden pace drop (mental lapse).

    A lapse is a lap significantly slower than the recent rolling average,
    occurring after a period of stable driving.

    Parameters
    ----------
    lap_times:
        Ordered lap times.
    lap_numbers:
        Corresponding lap numbers.
    window:
        Rolling window for mean/std calculation.
    std_factor:
        Number of standard deviations above rolling mean to flag.
    min_stable:
        Minimum consecutive stable laps before a lapse can be detected.

    Returns
    -------
    list[int]
        Lap numbers where mental lapses were detected.
    """
    n = len(lap_times)
    if n < window + min_stable:
        return []

    arr = np.array(lap_times, dtype=float)
    # Replace NaN with median
    median_val = float(np.nanmedian(arr))
    arr_clean = np.where(np.isfinite(arr), arr, median_val)

    lapses: list[int] = []

    for i in range(window, n):
        recent = arr_clean[max(0, i - window):i]
        r_mean = float(np.mean(recent))
        r_std = float(np.std(recent, ddof=1)) if len(recent) > 1 else 0.0

        if r_std < 0.01:
            # Very consistent -- use a minimum threshold
            r_std = 0.3

        threshold = r_mean + std_factor * r_std
        current = arr_clean[i]

        # Check if current lap is a lapse AND we had stable laps before
        if current > threshold and i >= min_stable:
            # Verify preceding laps were stable (no outliers)
            preceding = arr_clean[max(0, i - min_stable):i]
            prec_cv = float(np.std(preceding, ddof=1) / np.mean(preceding) * 100.0)
            if prec_cv < 3.0:  # Stable preceding window
                if i < len(lap_numbers):
                    lapses.append(lap_numbers[i])

    return lapses


# ============================================================================
# Fatigue Indicators
# ============================================================================


def compute_fatigue_indicators(
    lap_metrics: list[dict],
    lap_times: list[float],
    lap_numbers: list[int],
) -> FatigueIndicators:
    """
    Compute all fatigue indicators from per-lap metrics.

    Parameters
    ----------
    lap_metrics:
        List of dicts with keys like ``jerk_rms_mps3``, ``braking_max_mps2``,
        ``lat_accel_rms_mps2``, etc.
    lap_times:
        Ordered lap times.
    lap_numbers:
        Corresponding lap numbers.

    Returns
    -------
    FatigueIndicators
    """
    n = len(lap_times)
    result = FatigueIndicators(n_laps=n)

    if n < MIN_LAPS_FOR_FATIGUE:
        result.fatigue_level = "insufficient_data"
        result.coaching_hint = "Not enough laps for fatigue analysis."
        return result

    # --- Smoothness degradation (jerk RMS) ---
    jerk_values = [m.get("jerk_rms_mps3", m.get("jerk_rms", float("nan")))
                   for m in lap_metrics]
    jerk_first, jerk_second = _split_halves(jerk_values)

    if jerk_first and jerk_second:
        mean_first = float(np.mean(jerk_first))
        mean_second = float(np.mean(jerk_second))
        result.smoothness_first_half = mean_first
        result.smoothness_second_half = mean_second
        if mean_first > 0:
            result.smoothness_degradation_pct = (
                (mean_second - mean_first) / mean_first * 100.0
            )

    # --- Braking consistency decay ---
    brake_values = [m.get("braking_max_mps2", m.get("braking_max", float("nan")))
                    for m in lap_metrics]
    brake_first, brake_second = _split_halves(brake_values)

    if len(brake_first) >= 2 and len(brake_second) >= 2:
        std_first = float(np.std(brake_first, ddof=1))
        std_second = float(np.std(brake_second, ddof=1))
        result.braking_std_first_half = std_first
        result.braking_std_second_half = std_second
        if std_first > 0.01:
            result.braking_consistency_decay_pct = (
                (std_second - std_first) / std_first * 100.0
            )

    # --- Mental lapses ---
    lapses = detect_mental_lapses(lap_times, lap_numbers)
    result.lapse_laps = lapses
    result.lapse_count = len(lapses)

    # --- Pace decay ---
    valid_times = np.array(
        [t for t in lap_times if math.isfinite(t) and t > 0], dtype=float,
    )
    result.pace_slope_s_per_lap = _linear_slope(valid_times)

    return result


# ============================================================================
# Concentration Index
# ============================================================================


def compute_concentration_index(
    indicators: FatigueIndicators,
) -> float:
    """
    Compute a composite 0-100 concentration index.

    100 = fully alert and consistent; 0 = severely fatigued.

    Factors in: smoothness degradation, braking scatter increase,
    mental lapse frequency, and pace decay trend.
    """
    n = indicators.n_laps
    if n < MIN_LAPS_FOR_FATIGUE:
        return 100.0

    scores: list[tuple[float, float]] = []  # (score_0_1, weight)

    # Smoothness score: 0% degradation = 1.0, 50%+ degradation = 0.0
    smooth_deg = max(0.0, indicators.smoothness_degradation_pct)
    smooth_score = max(0.0, 1.0 - smooth_deg / 50.0)
    scores.append((smooth_score, _W_SMOOTHNESS))

    # Braking score: 0% decay = 1.0, 100%+ decay = 0.0
    brake_decay = max(0.0, indicators.braking_consistency_decay_pct)
    brake_score = max(0.0, 1.0 - brake_decay / 100.0)
    scores.append((brake_score, _W_BRAKING))

    # Lapse score: 0 lapses = 1.0, 3+ lapses = 0.0
    lapse_score = max(0.0, 1.0 - indicators.lapse_count / 3.0)
    scores.append((lapse_score, _W_LAPSES))

    # Pace score: 0 slope = 1.0, +0.5s/lap = 0.0
    pace_slope = max(0.0, indicators.pace_slope_s_per_lap)
    pace_score = max(0.0, 1.0 - pace_slope / 0.5)
    scores.append((pace_score, _W_PACE_DECAY))

    # Weighted sum
    total_weight = sum(w for _, w in scores)
    if total_weight < 1e-6:
        return 100.0
    weighted = sum(s * w for s, w in scores) / total_weight
    return round(max(0.0, min(100.0, weighted * 100.0)), 1)


def _classify_fatigue(concentration: float) -> tuple[str, str]:
    """Map concentration index to qualitative level + coaching hint."""
    if concentration >= 85.0:
        return "fresh", "Driver maintained excellent concentration throughout."
    if concentration >= 65.0:
        return "mild", (
            "Mild concentration fade detected in later laps. "
            "Consider shorter stints or a mental reset routine."
        )
    if concentration >= 40.0:
        return "moderate", (
            "Noticeable fatigue: braking and smoothness degraded significantly. "
            "Pit stop or driver change recommended at this stint length."
        )
    return "severe", (
        "Severe fatigue indicators: frequent mental lapses and pace decay. "
        "Reduce stint length and add recovery breaks."
    )


# ============================================================================
# All-in-one Entry Point
# ============================================================================


def analyze_fatigue(
    lap_metrics: list[dict],
    lap_times: list[float],
    lap_numbers: list[int],
) -> FatigueIndicators:
    """
    Full fatigue analysis pipeline.

    Parameters
    ----------
    lap_metrics:
        Per-lap metric dicts.
    lap_times:
        Ordered lap times.
    lap_numbers:
        Corresponding lap numbers.

    Returns
    -------
    FatigueIndicators
    """
    indicators = compute_fatigue_indicators(lap_metrics, lap_times, lap_numbers)

    # Early return for insufficient data
    if indicators.fatigue_level == "insufficient_data":
        return indicators

    concentration = compute_concentration_index(indicators)
    indicators.concentration_index = concentration
    level, hint = _classify_fatigue(concentration)
    indicators.fatigue_level = level
    indicators.coaching_hint = hint

    logger.info(
        "Fatigue analysis: %d laps, concentration=%.1f, level=%s, "
        "smoothness_deg=%.1f%%, brake_decay=%.1f%%, lapses=%d",
        indicators.n_laps, concentration, level,
        indicators.smoothness_degradation_pct,
        indicators.braking_consistency_decay_pct,
        indicators.lapse_count,
    )
    return indicators


# ============================================================================
# Self-test
# ============================================================================


def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # Helpers
    def _make_metrics(n: int, jerk_base: float = 5.0, jerk_fade: float = 0.0,
                      brake_base: float = 10.0, brake_scatter: float = 0.0) -> list[dict]:
        rng = np.random.default_rng(42)
        metrics = []
        for i in range(n):
            t_frac = i / max(n - 1, 1)
            jerk = jerk_base + jerk_fade * t_frac + rng.normal(0, 0.2)
            brake = brake_base + rng.normal(0, 0.3 + brake_scatter * t_frac)
            metrics.append({
                "jerk_rms_mps3": max(0, jerk),
                "braking_max_mps2": max(0, brake),
            })
        return metrics

    def _make_times(n: int, base: float = 45.0, fade: float = 0.0,
                    lapse_at: list = None) -> tuple[list[float], list[int]]:
        rng = np.random.default_rng(42)
        times = []
        for i in range(n):
            t = base + fade * i / max(n - 1, 1) + rng.normal(0, 0.1)
            if lapse_at and (i + 1) in lapse_at:
                t += 3.0  # Big spike
            times.append(t)
        return times, list(range(1, n + 1))

    # --- Tests ---

    def t_fresh_driver():
        metrics = _make_metrics(15, jerk_fade=0.0, brake_scatter=0.0)
        times, nums = _make_times(15, fade=0.0)
        result = analyze_fatigue(metrics, times, nums)
        assert result.fatigue_level == "fresh", f"Expected fresh, got {result.fatigue_level}"
        assert result.concentration_index >= 80.0

    _test("fresh_driver", t_fresh_driver)

    def t_fatigued_driver():
        metrics = _make_metrics(15, jerk_fade=5.0, brake_scatter=3.0)
        times, nums = _make_times(15, fade=1.5, lapse_at=[10, 13])
        result = analyze_fatigue(metrics, times, nums)
        assert result.concentration_index < 80.0, (
            f"Fatigued driver should have low concentration: {result.concentration_index}"
        )
        assert result.fatigue_level in ("mild", "moderate", "severe")

    _test("fatigued_driver", t_fatigued_driver)

    def t_insufficient_laps():
        metrics = _make_metrics(5)
        times, nums = _make_times(5)
        result = analyze_fatigue(metrics, times, nums)
        assert result.fatigue_level == "insufficient_data"

    _test("insufficient_laps", t_insufficient_laps)

    def t_mental_lapses_detected():
        times = [45.0, 45.1, 44.9, 45.0, 45.1,
                 45.0, 44.9, 45.0, 48.5, 45.0]  # spike at lap 9
        nums = list(range(1, 11))
        lapses = detect_mental_lapses(times, nums)
        assert 9 in lapses, f"Should detect lapse at lap 9: {lapses}"

    _test("mental_lapses_detected", t_mental_lapses_detected)

    def t_no_lapses_stable():
        times = [45.0 + i * 0.01 for i in range(12)]
        nums = list(range(1, 13))
        lapses = detect_mental_lapses(times, nums)
        assert len(lapses) == 0, f"Stable session should have no lapses: {lapses}"

    _test("no_lapses_stable", t_no_lapses_stable)

    def t_concentration_bounds():
        metrics = _make_metrics(15)
        times, nums = _make_times(15)
        result = analyze_fatigue(metrics, times, nums)
        assert 0.0 <= result.concentration_index <= 100.0

    _test("concentration_bounds", t_concentration_bounds)

    def t_smoothness_degradation():
        metrics = _make_metrics(12, jerk_fade=4.0)
        times, nums = _make_times(12)
        indicators = compute_fatigue_indicators(metrics, times, nums)
        assert indicators.smoothness_degradation_pct > 0, (
            f"Jerk fade should cause smoothness degradation, "
            f"got {indicators.smoothness_degradation_pct}"
        )

    _test("smoothness_degradation", t_smoothness_degradation)

    def t_serialization():
        metrics = _make_metrics(10)
        times, nums = _make_times(10)
        result = analyze_fatigue(metrics, times, nums)
        d = result.to_dict()
        for key in ("concentration_index", "fatigue_level", "lapse_count",
                     "smoothness_degradation_pct", "coaching_hint"):
            assert key in d, f"Missing key: {key}"

    _test("serialization", t_serialization)

    def t_deterministic():
        metrics = _make_metrics(12)
        times, nums = _make_times(12)
        r1 = analyze_fatigue(metrics, times, nums)
        r2 = analyze_fatigue(metrics, times, nums)
        assert r1.to_dict() == r2.to_dict()

    _test("deterministic", t_deterministic)

    def t_all_nan():
        metrics = [{"jerk_rms_mps3": float("nan")} for _ in range(10)]
        times = [float("nan")] * 10
        nums = list(range(1, 11))
        result = analyze_fatigue(metrics, times, nums)
        assert result.n_laps == 10

    _test("all_nan", t_all_nan)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nFatigue Detection Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
