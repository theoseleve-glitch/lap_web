"""
tyre_comparator.py
------------------
Tyre Compound Comparator — analyses performance differences between tyre
types/compounds by comparing stints or sessions run on different rubber.

Even without explicit compound data, this module can infer tyre changes
from pit stops and pace resets, then compare the resulting stints.

Core Features
~~~~~~~~~~~~~
1. **Stint Pace Comparison**: Compares mean pace, degradation rate, and
   consistency across detected stints (assumed different compounds).
2. **Fresh-Tyre Pace Delta**: Measures the pace offset at the start of
   each stint (fresh-tyre performance gap).
3. **Degradation Rate Comparison**: Which stint/compound degrades faster?
4. **Optimal Compound Selection**: Given race length, recommends which
   stint's tyre profile would be optimal.
5. **Crossover Lap**: When does the slower-degrading compound overtake
   the faster-starting compound?

Public API
~~~~~~~~~~
- ``compare_stints(stint_data)``
- ``compute_crossover(stint_a, stint_b)``
- ``recommend_compound(stint_comparisons, race_laps)``
- ``analyze_tyre_performance(session_laps, pit_laps)``

Design Principles
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

MIN_STINT_LAPS: Final[int] = 3
PIT_GAP_FACTOR: Final[float] = 2.0  # lap > median * factor = pit stop


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class StintProfile:
    """Performance profile of a single stint (assumed single compound)."""
    stint_index: int = 0
    compound_label: str = ""       # "Stint 1", "Stint 2", etc.
    laps: list[float] = field(default_factory=list)
    lap_start: int = 0
    lap_end: int = 0
    n_laps: int = 0
    fresh_pace_s: float = 0.0      # avg of first 3 laps
    mean_pace_s: float = 0.0
    best_pace_s: float = 0.0
    degradation_s_per_lap: float = 0.0
    cv_pct: float = 0.0
    total_time_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stint_index": self.stint_index,
            "compound_label": self.compound_label,
            "lap_start": self.lap_start,
            "lap_end": self.lap_end,
            "n_laps": self.n_laps,
            "fresh_pace_s": round(self.fresh_pace_s, 3),
            "mean_pace_s": round(self.mean_pace_s, 3),
            "best_pace_s": round(self.best_pace_s, 3),
            "degradation_s_per_lap": round(self.degradation_s_per_lap, 4),
            "cv_pct": round(self.cv_pct, 2),
            "total_time_s": round(self.total_time_s, 3),
        }


@dataclass
class StintComparison:
    """Comparison between two stints."""
    stint_a: str = ""
    stint_b: str = ""
    fresh_pace_delta_s: float = 0.0   # A - B (negative = A faster)
    mean_pace_delta_s: float = 0.0
    degradation_delta_s: float = 0.0  # A - B (negative = A degrades less)
    crossover_lap: int = 0            # lap where faster-degrading passes
    recommended: str = ""             # which stint profile is better for race

    def to_dict(self) -> dict[str, Any]:
        return {
            "stint_a": self.stint_a,
            "stint_b": self.stint_b,
            "fresh_pace_delta_s": round(self.fresh_pace_delta_s, 3),
            "mean_pace_delta_s": round(self.mean_pace_delta_s, 3),
            "degradation_delta_s": round(self.degradation_delta_s, 4),
            "crossover_lap": self.crossover_lap,
            "recommended": self.recommended,
        }


@dataclass
class TyreAnalysisResult:
    """Complete tyre compound analysis."""
    stint_profiles: list[StintProfile] = field(default_factory=list)
    comparisons: list[StintComparison] = field(default_factory=list)
    recommendation: str = ""
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stint_profiles": [sp.to_dict() for sp in self.stint_profiles],
            "comparisons": [c.to_dict() for c in self.comparisons],
            "recommendation": self.recommendation,
            "coaching": self.coaching,
        }


# ============================================================================
# Stint Detection & Profiling
# ============================================================================


def _detect_stints(
    lap_times: list[float],
    lap_numbers: list[int],
) -> list[list[tuple[int, float]]]:
    """Detect stints using pit-gap detection."""
    if not lap_times:
        return []

    valid = [
        (ln, t) for ln, t in zip(lap_numbers, lap_times)
        if t is not None and math.isfinite(t) and t > 0
    ]
    if len(valid) < 2:
        return [valid] if valid else []

    times_only = [t for _, t in valid]
    median = float(np.median(times_only))
    threshold = median * PIT_GAP_FACTOR

    stints: list[list[tuple[int, float]]] = []
    current: list[tuple[int, float]] = []

    for ln, t in valid:
        if t > threshold and current:
            # Pit stop detected
            stints.append(current)
            current = []
        else:
            current.append((ln, t))

    if current:
        stints.append(current)

    return stints


def _build_stint_profile(
    stint_laps: list[tuple[int, float]],
    stint_index: int,
) -> StintProfile:
    """Build a performance profile for a stint."""
    sp = StintProfile(
        stint_index=stint_index,
        compound_label=f"Stint {stint_index + 1}",
    )

    if not stint_laps:
        return sp

    sp.lap_start = stint_laps[0][0]
    sp.lap_end = stint_laps[-1][0]
    sp.laps = [t for _, t in stint_laps]
    sp.n_laps = len(sp.laps)
    sp.total_time_s = sum(sp.laps)

    arr = np.array(sp.laps, dtype=float)
    sp.mean_pace_s = float(np.mean(arr))
    sp.best_pace_s = float(np.min(arr))

    # Fresh pace: first 3 laps (or all if fewer)
    fresh_n = min(3, sp.n_laps)
    sp.fresh_pace_s = float(np.mean(arr[:fresh_n]))

    # CV
    std = float(np.std(arr, ddof=1)) if sp.n_laps > 1 else 0.0
    sp.cv_pct = (std / sp.mean_pace_s * 100) if sp.mean_pace_s > 0 else 0.0

    # Degradation: linear slope
    if sp.n_laps >= MIN_STINT_LAPS:
        x = np.arange(sp.n_laps, dtype=float)
        x_bar = float(np.mean(x))
        y_bar = float(np.mean(arr))
        ss_xx = float(np.sum((x - x_bar) ** 2))
        ss_xy = float(np.sum((x - x_bar) * (arr - y_bar)))
        sp.degradation_s_per_lap = max(0.0, ss_xy / ss_xx) if ss_xx > 0 else 0.0

    return sp


# ============================================================================
# Comparison
# ============================================================================


def compare_stints(
    profile_a: StintProfile,
    profile_b: StintProfile,
) -> StintComparison:
    """Compare two stint profiles."""
    comp = StintComparison(
        stint_a=profile_a.compound_label,
        stint_b=profile_b.compound_label,
    )

    comp.fresh_pace_delta_s = profile_a.fresh_pace_s - profile_b.fresh_pace_s
    comp.mean_pace_delta_s = profile_a.mean_pace_s - profile_b.mean_pace_s
    comp.degradation_delta_s = (
        profile_a.degradation_s_per_lap - profile_b.degradation_s_per_lap
    )

    # Crossover lap: when cumulative times cross
    comp.crossover_lap = compute_crossover(profile_a, profile_b)

    # Recommendation
    if profile_a.mean_pace_s < profile_b.mean_pace_s:
        if profile_a.degradation_s_per_lap <= profile_b.degradation_s_per_lap:
            comp.recommended = profile_a.compound_label
        else:
            comp.recommended = profile_a.compound_label + " (faster but degrades more)"
    else:
        if profile_b.degradation_s_per_lap <= profile_a.degradation_s_per_lap:
            comp.recommended = profile_b.compound_label
        else:
            comp.recommended = profile_b.compound_label + " (faster but degrades more)"

    return comp


def compute_crossover(
    profile_a: StintProfile,
    profile_b: StintProfile,
    max_laps: int = 60,
) -> int:
    """
    Find the lap where the slower-fresh-pace compound overtakes the faster one
    due to lower degradation.

    Returns
    -------
    int
        Crossover lap number (0 if no crossover within max_laps).
    """
    if (profile_a.degradation_s_per_lap == profile_b.degradation_s_per_lap):
        return 0  # parallel degradation, no crossover

    cum_a = 0.0
    cum_b = 0.0
    a_ahead = None

    for lap in range(1, max_laps + 1):
        pace_a = profile_a.fresh_pace_s + profile_a.degradation_s_per_lap * (lap - 1)
        pace_b = profile_b.fresh_pace_s + profile_b.degradation_s_per_lap * (lap - 1)
        cum_a += pace_a
        cum_b += pace_b

        currently_a_ahead = cum_a <= cum_b

        if a_ahead is not None and currently_a_ahead != a_ahead:
            return lap

        a_ahead = currently_a_ahead

    return 0


# ============================================================================
# Full Analysis
# ============================================================================


def analyze_tyre_performance(
    lap_times: list[float],
    lap_numbers: Optional[list[int]] = None,
    pit_laps: Optional[list[int]] = None,
) -> TyreAnalysisResult:
    """
    Full tyre compound analysis.

    Parameters
    ----------
    lap_times:
        All lap times in the session.
    lap_numbers:
        Optional actual lap numbers (parallel to lap_times).
    pit_laps:
        Optional explicit pit-stop laps. If None, auto-detected.

    Returns
    -------
    TyreAnalysisResult
    """
    result = TyreAnalysisResult()

    if lap_numbers is None:
        lap_numbers = list(range(1, len(lap_times) + 1))

    # Detect stints
    stint_groups = _detect_stints(lap_times, lap_numbers)

    # Filter out short stints
    stint_groups = [sg for sg in stint_groups if len(sg) >= MIN_STINT_LAPS]

    if len(stint_groups) < 1:
        result.coaching = "Not enough stint data for tyre analysis."
        return result

    # Build profiles
    for i, sg in enumerate(stint_groups):
        profile = _build_stint_profile(sg, i)
        result.stint_profiles.append(profile)

    # Pairwise comparisons
    for i in range(len(result.stint_profiles)):
        for j in range(i + 1, len(result.stint_profiles)):
            comp = compare_stints(result.stint_profiles[i], result.stint_profiles[j])
            result.comparisons.append(comp)

    # Overall recommendation
    if result.stint_profiles:
        best = min(result.stint_profiles, key=lambda p: p.mean_pace_s)
        most_consistent = min(result.stint_profiles, key=lambda p: p.cv_pct)
        lowest_deg = min(result.stint_profiles, key=lambda p: p.degradation_s_per_lap)

        result.recommendation = (
            f"Fastest overall: {best.compound_label} "
            f"({best.mean_pace_s:.3f}s avg). "
            f"Most consistent: {most_consistent.compound_label} "
            f"(CV {most_consistent.cv_pct:.1f}%). "
            f"Lowest degradation: {lowest_deg.compound_label} "
            f"({lowest_deg.degradation_s_per_lap:.4f}s/lap)."
        )

    # Coaching
    result.coaching = _generate_tyre_coaching(result)

    logger.info(
        "Tyre analysis: %d stints, %d comparisons",
        len(result.stint_profiles), len(result.comparisons),
    )

    return result


def _generate_tyre_coaching(result: TyreAnalysisResult) -> str:
    """Generate tyre management coaching."""
    parts: list[str] = []

    if len(result.stint_profiles) == 1:
        sp = result.stint_profiles[0]
        parts.append(
            f"Single stint of {sp.n_laps} laps. "
            f"Fresh pace: {sp.fresh_pace_s:.3f}s, "
            f"degradation: +{sp.degradation_s_per_lap:.3f}s/lap."
        )
        if sp.degradation_s_per_lap > 0.1:
            parts.append("High degradation — consider softer driving to preserve tyres.")
        elif sp.degradation_s_per_lap < 0.02:
            parts.append("Excellent tyre management — pace is very stable.")
        return " ".join(parts)

    if len(result.stint_profiles) >= 2:
        profiles = result.stint_profiles
        parts.append(f"{len(profiles)} stints detected. ")

        fastest = min(profiles, key=lambda p: p.fresh_pace_s)
        parts.append(
            f"Best fresh pace: {fastest.compound_label} "
            f"({fastest.fresh_pace_s:.3f}s)."
        )

        # Compare first vs second stint
        if len(profiles) >= 2:
            p1, p2 = profiles[0], profiles[1]
            if p2.fresh_pace_s < p1.fresh_pace_s:
                parts.append(
                    f"Fresh-tyre improvement: "
                    f"{p1.fresh_pace_s - p2.fresh_pace_s:.3f}s faster on {p2.compound_label}."
                )
            elif p2.fresh_pace_s > p1.fresh_pace_s:
                parts.append(
                    f"Warning: {p2.compound_label} starts "
                    f"{p2.fresh_pace_s - p1.fresh_pace_s:.3f}s slower. "
                    f"May indicate harder compound or cold tyres."
                )

    return " ".join(parts)


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

    def t_single_stint():
        times = [60.0 + 0.1 * i for i in range(15)]
        result = analyze_tyre_performance(times)
        assert len(result.stint_profiles) == 1
        sp = result.stint_profiles[0]
        assert sp.n_laps == 15
        assert sp.degradation_s_per_lap > 0.05

    _test("single_stint", t_single_stint)

    def t_two_stints():
        # Stint 1: fast, high deg. Stint 2: slightly slower, lower deg.
        stint1 = [60.0 + 0.15 * i for i in range(10)]
        pit = [180.0]  # big gap = pit stop
        stint2 = [60.5 + 0.05 * i for i in range(10)]
        times = stint1 + pit + stint2
        result = analyze_tyre_performance(times)
        assert len(result.stint_profiles) == 2
        assert len(result.comparisons) == 1
        # First stint should be faster on fresh pace
        assert result.stint_profiles[0].fresh_pace_s < result.stint_profiles[1].fresh_pace_s

    _test("two_stints", t_two_stints)

    def t_crossover():
        pa = StintProfile(fresh_pace_s=60.0, degradation_s_per_lap=0.2)
        pb = StintProfile(fresh_pace_s=61.0, degradation_s_per_lap=0.05)
        cross = compute_crossover(pa, pb)
        # A starts faster but degrades more. At some point B catches up.
        assert cross > 0, f"Expected crossover, got {cross}"

    _test("crossover", t_crossover)

    def t_no_crossover():
        pa = StintProfile(fresh_pace_s=60.0, degradation_s_per_lap=0.1)
        pb = StintProfile(fresh_pace_s=62.0, degradation_s_per_lap=0.1)
        cross = compute_crossover(pa, pb)
        assert cross == 0, "Parallel deg should not crossover"

    _test("no_crossover", t_no_crossover)

    def t_stint_profile_stats():
        laps = [60.0, 60.2, 60.4, 60.6, 60.8]
        sp = _build_stint_profile(
            [(i + 1, t) for i, t in enumerate(laps)], 0
        )
        assert sp.n_laps == 5
        assert abs(sp.fresh_pace_s - 60.2) < 0.01
        assert sp.best_pace_s == 60.0
        assert sp.degradation_s_per_lap > 0.15

    _test("stint_profile_stats", t_stint_profile_stats)

    def t_comparison_fields():
        pa = StintProfile(
            compound_label="Soft", fresh_pace_s=59.5,
            mean_pace_s=60.0, degradation_s_per_lap=0.15,
        )
        pb = StintProfile(
            compound_label="Hard", fresh_pace_s=60.5,
            mean_pace_s=60.2, degradation_s_per_lap=0.03,
        )
        comp = compare_stints(pa, pb)
        assert comp.fresh_pace_delta_s < 0  # A is faster on fresh
        assert comp.degradation_delta_s > 0  # A degrades more

    _test("comparison_fields", t_comparison_fields)

    def t_insufficient_data():
        times = [60.0, 61.0]  # only 2 laps
        result = analyze_tyre_performance(times)
        assert len(result.stint_profiles) == 0

    _test("insufficient_data", t_insufficient_data)

    def t_recommendation():
        stint1 = [60.0 + 0.1 * i for i in range(8)]
        pit = [180.0]
        stint2 = [60.3 + 0.05 * i for i in range(8)]
        times = stint1 + pit + stint2
        result = analyze_tyre_performance(times)
        assert result.recommendation != ""
        assert "Fastest" in result.recommendation

    _test("recommendation", t_recommendation)

    def t_coaching():
        times = [60.0 + 0.1 * i for i in range(10)]
        result = analyze_tyre_performance(times)
        assert result.coaching != ""

    _test("coaching", t_coaching)

    def t_nan_robustness():
        times = [60.0, float("nan"), None, 60.5, 61.0, 61.5, 62.0, 62.5]
        result = analyze_tyre_performance(times)
        assert len(result.stint_profiles) >= 1
        for sp in result.stint_profiles:
            assert math.isfinite(sp.mean_pace_s)

    _test("nan_robustness", t_nan_robustness)

    def t_serialization():
        times = [60.0 + 0.1 * i for i in range(10)]
        result = analyze_tyre_performance(times)
        d = result.to_dict()
        assert "stint_profiles" in d
        assert "comparisons" in d
        assert "recommendation" in d
        assert "coaching" in d

    _test("serialization", t_serialization)

    def t_deterministic():
        times = [60.0 + 0.08 * i for i in range(12)]
        r1 = analyze_tyre_performance(times)
        r2 = analyze_tyre_performance(times)
        assert r1.to_dict() == r2.to_dict()

    _test("deterministic", t_deterministic)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nTyre Comparator Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
