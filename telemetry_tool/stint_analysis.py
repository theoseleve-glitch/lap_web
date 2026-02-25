"""
stint_analysis.py
-----------------
Automatic stint detection and per-stint performance analytics.

A *stint* is a consecutive run of laps between pit stops or extended
track pauses.  This module:

1. **Detects stint boundaries** from lap-time gaps (a gap >= threshold
   between consecutive laps indicates a pit stop or red flag).
2. **Computes per-stint KPIs**: mean pace, consistency (CV%), pace
   fade, best lap, grip trend.
3. **Identifies the 'tyre cliff'** -- the lap within a stint where pace
   degrades beyond a threshold.
4. **Generates stint coaching hints** based on stint-level patterns.

Public API
~~~~~~~~~~
- ``detect_stints(lap_times_dict)``
- ``compute_stint_metrics(stints, lap_times_dict)``
- ``detect_tyre_cliff(lap_times, threshold_pct)``
- ``generate_stint_coaching(stint_metrics_list)``
- ``analyze_stints(lap_times_dict)``  (all-in-one)

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

# A gap between consecutive laps exceeding this factor x median lap time
# indicates a pit stop or session break.
PIT_GAP_FACTOR: Final[float] = 2.0

# Minimum laps in a stint to be considered meaningful for analysis
MIN_STINT_LAPS: Final[int] = 3

# Pace fade: if later laps exceed early laps by this %, it's a tyre cliff
TYRE_CLIFF_THRESHOLD_PCT: Final[float] = 3.0

# Rolling window for pace trend within a stint
PACE_TREND_WINDOW: Final[int] = 3

# Consistency thresholds
CV_GOOD_PCT: Final[float] = 1.5
CV_ACCEPTABLE_PCT: Final[float] = 3.0


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class Stint:
    """A consecutive run of laps within a session."""

    stint_number: int
    lap_start: int
    lap_end: int
    lap_count: int
    lap_numbers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stint_number": self.stint_number,
            "lap_start": self.lap_start,
            "lap_end": self.lap_end,
            "lap_count": self.lap_count,
            "lap_numbers": list(self.lap_numbers),
        }


@dataclass
class StintMetrics:
    """Performance metrics for a single stint."""

    stint_number: int
    lap_start: int
    lap_end: int
    lap_count: int
    best_lap: int
    best_time_s: float
    mean_time_s: float
    median_time_s: float
    std_time_s: float
    cv_pct: float                    # coefficient of variation %
    pace_fade_pct: float             # (last N laps mean - first N laps mean) / first * 100
    tyre_cliff_lap: Optional[int]    # lap where cliff detected, or None
    tyre_cliff_severity_pct: float   # how much slower after the cliff
    pace_trend_slope: float          # seconds per lap (positive = slowing)
    coaching_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stint_number": self.stint_number,
            "lap_start": self.lap_start,
            "lap_end": self.lap_end,
            "lap_count": self.lap_count,
            "best_lap": self.best_lap,
            "best_time_s": round(self.best_time_s, 3),
            "mean_time_s": round(self.mean_time_s, 3),
            "median_time_s": round(self.median_time_s, 3),
            "std_time_s": round(self.std_time_s, 3),
            "cv_pct": round(self.cv_pct, 2),
            "pace_fade_pct": round(self.pace_fade_pct, 2),
            "tyre_cliff_lap": self.tyre_cliff_lap,
            "tyre_cliff_severity_pct": round(self.tyre_cliff_severity_pct, 2),
            "pace_trend_slope": round(self.pace_trend_slope, 4),
            "coaching_hint": self.coaching_hint,
        }


@dataclass
class StintAnalysisResult:
    """Complete stint analysis for a session."""

    n_stints: int
    stints: list[Stint] = field(default_factory=list)
    stint_metrics: list[StintMetrics] = field(default_factory=list)
    best_stint: Optional[int] = None            # stint_number of fastest stint
    most_consistent_stint: Optional[int] = None  # stint_number with lowest CV
    session_coaching: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_stints": self.n_stints,
            "stints": [s.to_dict() for s in self.stints],
            "stint_metrics": [m.to_dict() for m in self.stint_metrics],
            "best_stint": self.best_stint,
            "most_consistent_stint": self.most_consistent_stint,
            "session_coaching": list(self.session_coaching),
        }


# ============================================================================
# Internal Helpers
# ============================================================================


def _linear_slope(y: np.ndarray) -> float:
    """OLS slope of y vs index (seconds per lap)."""
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


# ============================================================================
# Stint Detection
# ============================================================================


def detect_stints(
    lap_times_dict: dict[int, float],
    *,
    gap_factor: float = PIT_GAP_FACTOR,
    min_stint_laps: int = MIN_STINT_LAPS,
) -> list[Stint]:
    """
    Detect stint boundaries from lap-time data.

    A new stint starts when the gap between consecutive laps exceeds
    ``gap_factor x median(all_valid_times)``.

    Parameters
    ----------
    lap_times_dict:
        ``{lap_number: lap_time_s}`` -- must be keyed by lap number.
    gap_factor:
        Multiplier on median time to define a pit-stop gap.
    min_stint_laps:
        Minimum laps for a stint to be reported (shorter runs are merged
        into the nearest stint or discarded).

    Returns
    -------
    list[Stint]
    """
    if not lap_times_dict:
        return []

    sorted_laps = sorted(lap_times_dict.keys())
    valid_times = [t for t in lap_times_dict.values()
                   if math.isfinite(t) and t > 0]

    if len(valid_times) < 2:
        # Single lap or no valid data -- one stint
        return [Stint(
            stint_number=1,
            lap_start=sorted_laps[0],
            lap_end=sorted_laps[-1],
            lap_count=len(sorted_laps),
            lap_numbers=list(sorted_laps),
        )]

    median_time = float(np.median(valid_times))
    gap_threshold = median_time * gap_factor

    # Walk through sorted laps and split on gaps
    stints_raw: list[list[int]] = [[sorted_laps[0]]]

    for i in range(1, len(sorted_laps)):
        current_lap = sorted_laps[i]
        prev_lap = sorted_laps[i - 1]

        prev_time = lap_times_dict.get(prev_lap, float("nan"))
        curr_time = lap_times_dict.get(current_lap, float("nan"))

        # Gap detection: slow outlap, gap in lap numbers, or slow inlap
        is_gap = False
        if math.isfinite(prev_time) and prev_time > gap_threshold:
            is_gap = True
        if current_lap - prev_lap > 1:
            is_gap = True
        if math.isfinite(curr_time) and curr_time > gap_threshold:
            is_gap = True

        if is_gap:
            stints_raw.append([current_lap])
        else:
            stints_raw[-1].append(current_lap)

    # Merge short stints into neighbours
    merged: list[list[int]] = []
    for laps in stints_raw:
        if len(laps) < min_stint_laps and merged:
            merged[-1].extend(laps)
        else:
            merged.append(laps)

    # Final pass: if last stint is too short, merge backwards
    if len(merged) > 1 and len(merged[-1]) < min_stint_laps:
        merged[-2].extend(merged[-1])
        merged.pop()

    # Build Stint objects
    result: list[Stint] = []
    for idx, laps in enumerate(merged, start=1):
        result.append(Stint(
            stint_number=idx,
            lap_start=laps[0],
            lap_end=laps[-1],
            lap_count=len(laps),
            lap_numbers=list(laps),
        ))

    logger.info("Detected %d stint(s) from %d laps", len(result), len(sorted_laps))
    return result


# ============================================================================
# Tyre Cliff Detection
# ============================================================================


def detect_tyre_cliff(
    lap_times: list[float],
    *,
    threshold_pct: float = TYRE_CLIFF_THRESHOLD_PCT,
    window: int = PACE_TREND_WINDOW,
) -> tuple[Optional[int], float]:
    """
    Find the lap index where pace drops sharply (tyre cliff).

    Compares each lap's rolling average to the best rolling average
    in the stint.  The cliff is the first point where the difference
    exceeds *threshold_pct*.

    Parameters
    ----------
    lap_times:
        Consecutive lap times for a single stint.
    threshold_pct:
        Minimum % degradation from peak to declare a cliff.
    window:
        Rolling-average window size.

    Returns
    -------
    tuple[Optional[int], float]
        ``(cliff_index_0based, severity_pct)`` or ``(None, 0.0)``.
    """
    n = len(lap_times)
    if n < window + 1:
        return None, 0.0

    valid = [t for t in lap_times if math.isfinite(t) and t > 0]
    if len(valid) < window + 1:
        return None, 0.0

    arr = np.array(lap_times, dtype=float)
    # Replace NaN with median for rolling computation
    median_val = float(np.nanmedian(arr))
    arr_clean = np.where(np.isfinite(arr), arr, median_val)

    # Compute rolling mean
    kernel = np.ones(window) / window
    rolling = np.convolve(arr_clean, kernel, mode="valid")

    if len(rolling) < 2:
        return None, 0.0

    best_rolling = float(np.min(rolling))
    if best_rolling <= 0:
        return None, 0.0

    for i in range(len(rolling)):
        pct_above = (rolling[i] - best_rolling) / best_rolling * 100.0
        if pct_above >= threshold_pct and i > 0:
            # Map back to original lap index (center of window)
            cliff_idx = i + window // 2
            cliff_idx = min(cliff_idx, n - 1)
            # Severity: how much slower is the rest of the stint?
            post_cliff = arr_clean[cliff_idx:]
            severity = (float(np.mean(post_cliff)) - best_rolling) / best_rolling * 100.0
            return cliff_idx, max(0.0, severity)

    return None, 0.0


# ============================================================================
# Per-Stint Metrics
# ============================================================================


def compute_stint_metrics(
    stints: list[Stint],
    lap_times_dict: dict[int, float],
) -> list[StintMetrics]:
    """
    Compute performance metrics for each detected stint.

    Parameters
    ----------
    stints:
        Output of :func:`detect_stints`.
    lap_times_dict:
        ``{lap_number: lap_time_s}``.

    Returns
    -------
    list[StintMetrics]
    """
    results: list[StintMetrics] = []

    for stint in stints:
        times = [lap_times_dict.get(lap, float("nan"))
                 for lap in stint.lap_numbers]
        valid = [t for t in times if math.isfinite(t) and t > 0]

        if not valid:
            results.append(StintMetrics(
                stint_number=stint.stint_number,
                lap_start=stint.lap_start, lap_end=stint.lap_end,
                lap_count=stint.lap_count,
                best_lap=stint.lap_start, best_time_s=float("nan"),
                mean_time_s=float("nan"), median_time_s=float("nan"),
                std_time_s=float("nan"), cv_pct=float("nan"),
                pace_fade_pct=0.0, tyre_cliff_lap=None,
                tyre_cliff_severity_pct=0.0, pace_trend_slope=0.0,
            ))
            continue

        arr = np.array(valid, dtype=float)
        mean_t = float(np.mean(arr))
        median_t = float(np.median(arr))
        std_t = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        cv = (std_t / mean_t * 100.0) if mean_t > 0 else 0.0

        best_idx = int(np.argmin(arr))
        # Map back to lap number
        valid_lap_nums = [lap for lap, t in zip(stint.lap_numbers, times)
                          if math.isfinite(t) and t > 0]
        best_lap_num = (valid_lap_nums[best_idx]
                        if best_idx < len(valid_lap_nums) else stint.lap_start)

        # Pace fade: compare first N laps to last N laps
        n_compare = min(3, len(valid) // 2)
        if n_compare >= 1:
            early_mean = float(np.mean(arr[:n_compare]))
            late_mean = float(np.mean(arr[-n_compare:]))
            pace_fade = ((late_mean - early_mean) / early_mean * 100.0
                         if early_mean > 0 else 0.0)
        else:
            pace_fade = 0.0

        # Pace trend slope
        slope = _linear_slope(np.array(times, dtype=float))

        # Tyre cliff detection
        cliff_idx, cliff_severity = detect_tyre_cliff(times)
        cliff_lap = None
        if cliff_idx is not None and cliff_idx < len(stint.lap_numbers):
            cliff_lap = stint.lap_numbers[cliff_idx]

        results.append(StintMetrics(
            stint_number=stint.stint_number,
            lap_start=stint.lap_start, lap_end=stint.lap_end,
            lap_count=stint.lap_count,
            best_lap=best_lap_num, best_time_s=float(np.min(arr)),
            mean_time_s=round(mean_t, 3), median_time_s=round(median_t, 3),
            std_time_s=round(std_t, 3), cv_pct=round(cv, 2),
            pace_fade_pct=round(pace_fade, 2),
            tyre_cliff_lap=cliff_lap,
            tyre_cliff_severity_pct=round(cliff_severity, 2),
            pace_trend_slope=round(slope, 4),
        ))

    return results


# ============================================================================
# Stint Coaching
# ============================================================================


def generate_stint_coaching(
    stint_metrics: list[StintMetrics],
) -> list[str]:
    """
    Generate session-level coaching hints from stint analysis.

    Returns
    -------
    list[str]
        Actionable coaching sentences.
    """
    hints: list[str] = []

    if not stint_metrics:
        return hints

    # Multi-stint analysis
    if len(stint_metrics) > 1:
        best_stint = min(
            stint_metrics,
            key=lambda m: m.best_time_s if math.isfinite(m.best_time_s) else float("inf"),
        )
        worst_stint = max(
            stint_metrics,
            key=lambda m: m.mean_time_s if math.isfinite(m.mean_time_s) else 0,
        )
        if (math.isfinite(best_stint.mean_time_s)
                and math.isfinite(worst_stint.mean_time_s)):
            gap = worst_stint.mean_time_s - best_stint.mean_time_s
            if gap > 0.5:
                hints.append(
                    f"Stint {best_stint.stint_number} was {gap:.2f}s/lap faster "
                    f"on average than stint {worst_stint.stint_number}. "
                    f"Focus on replicating stint {best_stint.stint_number}'s approach."
                )

    for m in stint_metrics:
        # Coaching per stint
        if m.tyre_cliff_lap is not None and m.tyre_cliff_severity_pct > 2.0:
            m.coaching_hint = (
                f"Tyre cliff detected at lap {m.tyre_cliff_lap} "
                f"({m.tyre_cliff_severity_pct:.1f}% slower). "
                f"Consider a pit stop or smoother driving before lap {m.tyre_cliff_lap}."
            )
            hints.append(m.coaching_hint)
        elif m.pace_fade_pct > 3.0:
            m.coaching_hint = (
                f"Stint {m.stint_number}: {m.pace_fade_pct:.1f}% pace fade -- "
                f"focus on tyre management and consistent corner entry speeds."
            )
            hints.append(m.coaching_hint)
        elif m.cv_pct > CV_ACCEPTABLE_PCT:
            m.coaching_hint = (
                f"Stint {m.stint_number}: CV={m.cv_pct:.1f}% (inconsistent) -- "
                f"establish a target lap time and use reference points."
            )
            hints.append(m.coaching_hint)
        elif m.cv_pct <= CV_GOOD_PCT and m.pace_fade_pct <= 1.0:
            m.coaching_hint = (
                f"Stint {m.stint_number}: excellent consistency (CV={m.cv_pct:.1f}%) "
                f"with minimal fade. Strong performance."
            )

    return hints


# ============================================================================
# All-in-one Entry Point
# ============================================================================


def analyze_stints(
    lap_times_dict: dict[int, float],
    *,
    gap_factor: float = PIT_GAP_FACTOR,
    min_stint_laps: int = MIN_STINT_LAPS,
) -> StintAnalysisResult:
    """
    Full stint analysis pipeline.

    Parameters
    ----------
    lap_times_dict:
        ``{lap_number: lap_time_s}``.
    gap_factor:
        Pit-gap detection factor.
    min_stint_laps:
        Minimum laps per stint.

    Returns
    -------
    StintAnalysisResult
    """
    stints = detect_stints(
        lap_times_dict, gap_factor=gap_factor, min_stint_laps=min_stint_laps,
    )
    metrics = compute_stint_metrics(stints, lap_times_dict)
    coaching = generate_stint_coaching(metrics)

    # Identify best and most consistent stints
    best_stint_num = None
    most_consistent_num = None
    if metrics:
        valid_metrics = [m for m in metrics if math.isfinite(m.best_time_s)]
        if valid_metrics:
            best_stint_num = min(
                valid_metrics, key=lambda m: m.best_time_s,
            ).stint_number
        consist_metrics = [m for m in metrics
                          if math.isfinite(m.cv_pct) and m.lap_count >= MIN_STINT_LAPS]
        if consist_metrics:
            most_consistent_num = min(
                consist_metrics, key=lambda m: m.cv_pct,
            ).stint_number

    result = StintAnalysisResult(
        n_stints=len(stints),
        stints=stints,
        stint_metrics=metrics,
        best_stint=best_stint_num,
        most_consistent_stint=most_consistent_num,
        session_coaching=coaching,
    )

    logger.info(
        "Stint analysis: %d stints, best=#%s, most_consistent=#%s",
        result.n_stints, best_stint_num, most_consistent_num,
    )
    return result


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

    # --- detect_stints ---

    def t_single_stint():
        times = {i: 45.0 + 0.1 * i for i in range(1, 16)}
        stints = detect_stints(times)
        assert len(stints) == 1
        assert stints[0].lap_count == 15
        assert stints[0].lap_start == 1
        assert stints[0].lap_end == 15

    _test("single_stint", t_single_stint)

    def t_two_stints_with_pit():
        times = {}
        for i in range(1, 11):
            times[i] = 45.0
        times[10] = 120.0   # pit lap (2.67x median)
        for i in range(11, 21):
            times[i] = 45.5
        stints = detect_stints(times)
        assert len(stints) == 2, f"Expected 2 stints, got {len(stints)}"
        assert stints[0].lap_end < stints[1].lap_start

    _test("two_stints_with_pit", t_two_stints_with_pit)

    def t_empty_input():
        assert detect_stints({}) == []

    _test("empty_input", t_empty_input)

    def t_single_lap():
        stints = detect_stints({1: 44.5})
        assert len(stints) == 1
        assert stints[0].lap_count == 1

    _test("single_lap", t_single_lap)

    def t_gap_in_lap_numbers():
        times = {1: 45.0, 2: 45.1, 3: 45.2, 7: 45.3, 8: 45.4, 9: 45.5}
        stints = detect_stints(times, min_stint_laps=2)
        assert len(stints) == 2

    _test("gap_in_lap_numbers", t_gap_in_lap_numbers)

    # --- detect_tyre_cliff ---

    def t_no_cliff_stable():
        times = [45.0, 45.1, 44.9, 45.0, 45.1, 45.0, 44.9, 45.0]
        cliff, sev = detect_tyre_cliff(times)
        assert cliff is None

    _test("no_cliff_stable", t_no_cliff_stable)

    def t_cliff_detected():
        times = [45.0, 45.1, 45.0, 45.2, 47.0, 47.5, 48.0, 48.5]
        cliff, sev = detect_tyre_cliff(times, threshold_pct=2.0)
        assert cliff is not None, "Should detect cliff"
        assert sev > 0

    _test("cliff_detected", t_cliff_detected)

    def t_cliff_too_few_laps():
        times = [45.0, 46.0]
        cliff, sev = detect_tyre_cliff(times)
        assert cliff is None

    _test("cliff_too_few_laps", t_cliff_too_few_laps)

    # --- compute_stint_metrics ---

    def t_metrics_basic():
        stints = [Stint(1, 1, 10, 10, list(range(1, 11)))]
        times = {i: 45.0 + 0.05 * i for i in range(1, 11)}
        metrics = compute_stint_metrics(stints, times)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.lap_count == 10
        assert m.best_time_s < m.mean_time_s
        assert m.cv_pct >= 0

    _test("metrics_basic", t_metrics_basic)

    def t_metrics_with_nan():
        stints = [Stint(1, 1, 5, 5, [1, 2, 3, 4, 5])]
        times = {1: 45.0, 2: float("nan"), 3: 45.1, 4: 45.2, 5: 45.0}
        metrics = compute_stint_metrics(stints, times)
        assert len(metrics) == 1
        assert math.isfinite(metrics[0].mean_time_s)

    _test("metrics_with_nan", t_metrics_with_nan)

    # --- generate_stint_coaching ---

    def t_coaching_fade():
        m = StintMetrics(
            stint_number=1, lap_start=1, lap_end=10, lap_count=10,
            best_lap=2, best_time_s=44.5, mean_time_s=45.5,
            median_time_s=45.3, std_time_s=0.8, cv_pct=1.8,
            pace_fade_pct=5.0, tyre_cliff_lap=None,
            tyre_cliff_severity_pct=0.0, pace_trend_slope=0.15,
        )
        hints = generate_stint_coaching([m])
        assert len(hints) >= 1
        assert "fade" in hints[0].lower() or "tyre" in hints[0].lower()

    _test("coaching_fade", t_coaching_fade)

    def t_coaching_cliff():
        m = StintMetrics(
            stint_number=1, lap_start=1, lap_end=10, lap_count=10,
            best_lap=2, best_time_s=44.5, mean_time_s=46.0,
            median_time_s=45.5, std_time_s=1.2, cv_pct=2.6,
            pace_fade_pct=6.0, tyre_cliff_lap=7,
            tyre_cliff_severity_pct=4.5, pace_trend_slope=0.3,
        )
        hints = generate_stint_coaching([m])
        assert any("cliff" in h.lower() for h in hints)

    _test("coaching_cliff", t_coaching_cliff)

    # --- analyze_stints (all-in-one) ---

    def t_analyze_single_stint():
        times = {i: 45.0 + 0.02 * i for i in range(1, 16)}
        result = analyze_stints(times)
        assert result.n_stints == 1
        assert result.best_stint == 1
        assert result.most_consistent_stint == 1
        d = result.to_dict()
        assert "stints" in d
        assert "stint_metrics" in d

    _test("analyze_single_stint", t_analyze_single_stint)

    def t_analyze_multi_stint():
        times = {}
        for i in range(1, 11):
            times[i] = 45.0 + 0.01 * i
        times[10] = 130.0  # pit stop
        for i in range(11, 21):
            times[i] = 46.0 + 0.5 * (i - 11)  # degrading stint
        result = analyze_stints(times)
        assert result.n_stints >= 2
        assert result.best_stint is not None

    _test("analyze_multi_stint", t_analyze_multi_stint)

    def t_serialization_roundtrip():
        times = {i: 44.5 + 0.1 * i for i in range(1, 8)}
        result = analyze_stints(times)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert isinstance(d["stints"], list)
        assert isinstance(d["stint_metrics"], list)
        for sm in d["stint_metrics"]:
            for key in ("stint_number", "mean_time_s", "cv_pct", "pace_fade_pct"):
                assert key in sm, f"Missing key {key}"

    _test("serialization_roundtrip", t_serialization_roundtrip)

    def t_all_nan_times():
        times = {1: float("nan"), 2: float("nan"), 3: float("nan")}
        result = analyze_stints(times)
        assert result.n_stints >= 1

    _test("all_nan_times", t_all_nan_times)

    def t_deterministic():
        times = {i: 44.5 + 0.1 * i for i in range(1, 16)}
        r1 = analyze_stints(times)
        r2 = analyze_stints(times)
        assert r1.to_dict() == r2.to_dict()

    _test("deterministic", t_deterministic)

    # --- Summary ---
    total = len(passed) + len(failed)
    print(f"\nStint Analysis Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
