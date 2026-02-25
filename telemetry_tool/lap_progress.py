"""
lap_progress.py
---------------
Lap-Over-Lap Progress Tracker — shows how performance evolves through
a session lap-by-lap with running PBs, rolling averages, consistency
windows, and flow state detection.

Core Features
~~~~~~~~~~~~~
1. **Running PB**: Track personal best progression through the session.
2. **Cumulative Mean**: Rolling and cumulative average pace.
3. **Rolling Consistency**: 5-lap rolling CV% window.
4. **Flow State Detection**: Streaks of consecutive improvement.
5. **Pace Zones**: Classify each lap as hot/good/average/slow/cold.
6. **Session Momentum**: Overall direction indicator.

Public API
~~~~~~~~~~
- ``analyze_lap_progress(lap_times, lap_numbers=None)``

Design Principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

ROLLING_WINDOW: Final[int] = 5
HOT_THRESHOLD_PCT: Final[float] = 0.5    # within 0.5% of PB
GOOD_THRESHOLD_PCT: Final[float] = 1.5   # within 1.5%
SLOW_THRESHOLD_PCT: Final[float] = 3.0   # beyond 3%
FLOW_MIN_STREAK: Final[int] = 3          # min consecutive improving laps


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class LapProgress:
    """Progress data for a single lap."""
    lap_number: int = 0
    lap_time_s: float = 0.0
    running_pb_s: float = 0.0
    is_pb: bool = False
    cumulative_mean_s: float = 0.0
    rolling_mean_s: float = 0.0
    rolling_cv_pct: float = 0.0
    delta_to_pb_s: float = 0.0
    delta_to_pb_pct: float = 0.0
    pace_zone: str = ""  # "hot", "good", "average", "slow", "cold"
    improvement_streak: int = 0  # consecutive improving laps ending here
    in_flow_state: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_number": self.lap_number,
            "lap_time_s": round(self.lap_time_s, 4),
            "running_pb_s": round(self.running_pb_s, 4),
            "is_pb": self.is_pb,
            "cumulative_mean_s": round(self.cumulative_mean_s, 4),
            "rolling_mean_s": round(self.rolling_mean_s, 4),
            "rolling_cv_pct": round(self.rolling_cv_pct, 3),
            "delta_to_pb_s": round(self.delta_to_pb_s, 4),
            "delta_to_pb_pct": round(self.delta_to_pb_pct, 3),
            "pace_zone": self.pace_zone,
            "improvement_streak": self.improvement_streak,
            "in_flow_state": self.in_flow_state,
        }


@dataclass
class FlowStreak:
    """A detected flow state streak."""
    start_lap: int = 0
    end_lap: int = 0
    length: int = 0
    improvement_s: float = 0.0  # total time gained over streak

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_lap": self.start_lap,
            "end_lap": self.end_lap,
            "length": self.length,
            "improvement_s": round(self.improvement_s, 4),
        }


@dataclass
class LapProgressResult:
    """Full progress analysis result."""
    n_laps: int = 0
    laps: list[LapProgress] = field(default_factory=list)
    pb_count: int = 0
    final_pb_s: float = 0.0
    first_lap_s: float = 0.0
    total_improvement_s: float = 0.0
    total_improvement_pct: float = 0.0
    flow_streaks: list[FlowStreak] = field(default_factory=list)
    longest_flow: int = 0
    pace_zone_counts: dict[str, int] = field(default_factory=dict)
    session_momentum: str = ""  # "building", "fading", "plateaued", "volatile"
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_laps": self.n_laps,
            "laps": [l.to_dict() for l in self.laps],
            "pb_count": self.pb_count,
            "final_pb_s": round(self.final_pb_s, 4),
            "first_lap_s": round(self.first_lap_s, 4),
            "total_improvement_s": round(self.total_improvement_s, 4),
            "total_improvement_pct": round(self.total_improvement_pct, 3),
            "flow_streaks": [f.to_dict() for f in self.flow_streaks],
            "longest_flow": self.longest_flow,
            "pace_zone_counts": self.pace_zone_counts,
            "session_momentum": self.session_momentum,
            "coaching": self.coaching,
        }


# ============================================================================
# Core Functions
# ============================================================================


def _classify_pace_zone(delta_pct: float) -> str:
    """Classify lap into pace zone by delta to PB."""
    if delta_pct <= HOT_THRESHOLD_PCT:
        return "hot"
    if delta_pct <= GOOD_THRESHOLD_PCT:
        return "good"
    if delta_pct <= SLOW_THRESHOLD_PCT:
        return "average"
    return "slow"


def _compute_rolling_cv(values: list[float], window: int) -> float:
    """Compute CV% over the last `window` values."""
    if len(values) < 2:
        return 0.0
    subset = values[-window:]
    arr = np.array(subset, dtype=float)
    mean = float(np.mean(arr))
    if mean <= 0:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return (std / mean) * 100


def _detect_momentum(laps: list[LapProgress]) -> str:
    """Detect session momentum from lap progress."""
    if len(laps) < 4:
        return "volatile"

    n = len(laps)
    # Compare first quarter vs last quarter
    q1_end = n // 4
    q4_start = n - n // 4

    q1_times = [l.lap_time_s for l in laps[:q1_end]] if q1_end > 0 else [laps[0].lap_time_s]
    q4_times = [l.lap_time_s for l in laps[q4_start:]]

    q1_mean = sum(q1_times) / len(q1_times)
    q4_mean = sum(q4_times) / len(q4_times)

    if q1_mean <= 0:
        return "volatile"

    delta_pct = ((q4_mean - q1_mean) / q1_mean) * 100

    # Also check PB progression in second half
    mid = n // 2
    late_pbs = sum(1 for l in laps[mid:] if l.is_pb)

    if delta_pct < -0.5 and late_pbs > 0:
        return "building"
    if delta_pct > 0.5:
        return "fading"

    # Check rolling CV stability
    late_cvs = [l.rolling_cv_pct for l in laps[mid:] if l.rolling_cv_pct > 0]
    if late_cvs and max(late_cvs) - min(late_cvs) < 0.3:
        return "plateaued"

    return "volatile"


def analyze_lap_progress(
    lap_times: list[float],
    lap_numbers: list[int] | None = None,
) -> LapProgressResult:
    """
    Full lap-over-lap progress analysis.

    Parameters
    ----------
    lap_times:
        List of valid lap times in seconds.
    lap_numbers:
        Optional corresponding lap numbers (defaults to 1..N).

    Returns
    -------
    LapProgressResult
    """
    result = LapProgressResult()

    # Filter valid
    valid = []
    if lap_numbers is None:
        lap_numbers = list(range(1, len(lap_times) + 1))

    for lt, ln in zip(lap_times, lap_numbers):
        if lt is not None and math.isfinite(lt) and lt > 0:
            valid.append((lt, ln))

    if len(valid) < 2:
        result.coaching = "Not enough valid laps for progress tracking."
        return result

    result.n_laps = len(valid)
    result.first_lap_s = valid[0][0]

    running_pb = float("inf")
    cumulative_times = []
    streak = 0
    prev_time = None
    streaks = []
    current_streak_start = -1

    for i, (lt, ln) in enumerate(valid):
        lp = LapProgress(lap_number=ln, lap_time_s=lt)

        # Running PB
        if lt < running_pb:
            running_pb = lt
            lp.is_pb = True
            result.pb_count += 1

        lp.running_pb_s = running_pb
        lp.delta_to_pb_s = lt - running_pb
        lp.delta_to_pb_pct = (lp.delta_to_pb_s / running_pb * 100) if running_pb > 0 else 0

        # Pace zone
        lp.pace_zone = _classify_pace_zone(lp.delta_to_pb_pct)

        # Cumulative mean
        cumulative_times.append(lt)
        lp.cumulative_mean_s = float(np.mean(cumulative_times))

        # Rolling mean & CV
        window = cumulative_times[-ROLLING_WINDOW:]
        lp.rolling_mean_s = float(np.mean(window))
        lp.rolling_cv_pct = _compute_rolling_cv(cumulative_times, ROLLING_WINDOW)

        # Improvement streak
        if prev_time is not None and lt < prev_time:
            streak += 1
            if streak == 1:
                current_streak_start = ln
        else:
            if streak >= FLOW_MIN_STREAK:
                streaks.append(FlowStreak(
                    start_lap=current_streak_start,
                    end_lap=valid[i - 1][1],
                    length=streak,
                    improvement_s=valid[i - streak][0] - valid[i - 1][0],
                ))
            streak = 0 if (prev_time is not None and lt >= prev_time) else 0

        lp.improvement_streak = streak
        lp.in_flow_state = streak >= FLOW_MIN_STREAK

        result.laps.append(lp)
        prev_time = lt

    # Check final streak
    if streak >= FLOW_MIN_STREAK:
        streaks.append(FlowStreak(
            start_lap=current_streak_start,
            end_lap=valid[-1][1],
            length=streak,
            improvement_s=valid[-streak][0] - valid[-1][0],
        ))

    result.final_pb_s = running_pb
    result.total_improvement_s = result.first_lap_s - running_pb
    if result.first_lap_s > 0:
        result.total_improvement_pct = (result.total_improvement_s / result.first_lap_s) * 100

    result.flow_streaks = streaks
    result.longest_flow = max((s.length for s in streaks), default=0)

    # Pace zone counts
    zone_counts = {}
    for l in result.laps:
        zone_counts[l.pace_zone] = zone_counts.get(l.pace_zone, 0) + 1
    result.pace_zone_counts = zone_counts

    # Momentum
    result.session_momentum = _detect_momentum(result.laps)

    # Coaching
    result.coaching = _generate_coaching(result)

    logger.info(
        "Lap progress: %d laps, %d PBs, improvement=%.3fs (%.1f%%), momentum=%s, %d flow streaks",
        result.n_laps, result.pb_count, result.total_improvement_s,
        result.total_improvement_pct, result.session_momentum, len(result.flow_streaks),
    )

    return result


def _generate_coaching(result: LapProgressResult) -> str:
    """Generate coaching insight."""
    parts = []

    if result.total_improvement_pct > 2:
        parts.append(f"Strong session progression: {result.total_improvement_s:.3f}s gained ({result.total_improvement_pct:.1f}%) from first to best lap.")
    elif result.total_improvement_pct > 0.5:
        parts.append(f"Solid improvement of {result.total_improvement_s:.3f}s from first to best lap.")
    else:
        parts.append("Minimal pace improvement during the session — focus on experimentation to find more speed.")

    if result.session_momentum == "building":
        parts.append("Momentum building through the session — strong late-session performance.")
    elif result.session_momentum == "fading":
        parts.append("Pace faded toward end — consider fatigue management or shorter stints.")
    elif result.session_momentum == "plateaued":
        parts.append("Performance plateaued — try adjusting technique or setup to break through.")

    hot_count = result.pace_zone_counts.get("hot", 0)
    total = result.n_laps
    if total > 0:
        hot_pct = hot_count / total * 100
        if hot_pct > 50:
            parts.append(f"{hot_pct:.0f}% of laps in the 'hot' zone — excellent consistency at peak pace.")
        elif hot_pct < 10 and total > 5:
            parts.append("Few laps in the hot zone — work on reproducing your best pace more consistently.")

    if result.longest_flow >= 5:
        parts.append(f"Achieved a {result.longest_flow}-lap improvement streak — strong flow state detected.")
    elif result.longest_flow >= 3:
        parts.append(f"Flow streak of {result.longest_flow} improving laps — good mental focus.")

    return " ".join(parts)


# ============================================================================
# Self-Tests
# ============================================================================


def _run_tests() -> None:
    """Verify all functions with synthetic data."""
    import sys

    passed = 0
    failed = 0
    total = 12

    def _ok(name: str):
        nonlocal passed
        passed += 1
        print(f"  OK {name}")

    def _fail(name: str, msg: str):
        nonlocal failed
        failed += 1
        print(f"  FAIL {name}: {msg}")

    # 1. Basic progress
    try:
        times = [65.0, 64.0, 63.5, 63.0, 62.8, 62.5, 62.3, 62.0]
        r = analyze_lap_progress(times)
        assert r.n_laps == 8
        assert r.pb_count >= 5  # Most laps should be PBs with monotone decrease
        assert r.final_pb_s <= 62.0
        assert r.total_improvement_s > 0
        _ok("basic_progress")
    except Exception as e:
        _fail("basic_progress", str(e))

    # 2. Running PB tracking
    try:
        times = [62.0, 63.0, 61.0, 62.5, 60.0]
        r = analyze_lap_progress(times)
        pbs = [l for l in r.laps if l.is_pb]
        assert len(pbs) == 3  # laps 1, 3, 5
        assert r.laps[0].is_pb
        assert not r.laps[1].is_pb
        assert r.laps[2].is_pb
        _ok("running_pb")
    except Exception as e:
        _fail("running_pb", str(e))

    # 3. Pace zones
    try:
        times = [60.0, 60.1, 60.2, 63.0, 60.0]
        r = analyze_lap_progress(times)
        # First lap is PB → hot zone (0% delta)
        assert r.laps[0].pace_zone == "hot"
        # 63.0 is 5% off best → slow
        assert r.laps[3].pace_zone == "slow", f"zone={r.laps[3].pace_zone}"
        _ok("pace_zones")
    except Exception as e:
        _fail("pace_zones", str(e))

    # 4. Flow state detection
    try:
        # 5 consecutive improving laps
        times = [65.0, 64.5, 64.0, 63.5, 63.0, 62.5, 65.0]
        r = analyze_lap_progress(times)
        assert len(r.flow_streaks) >= 1, f"streaks={len(r.flow_streaks)}"
        assert r.longest_flow >= 5, f"longest={r.longest_flow}"
        _ok("flow_state")
    except Exception as e:
        _fail("flow_state", str(e))

    # 5. No flow state (oscillating)
    try:
        times = [60.0, 61.0, 60.0, 61.0, 60.0, 61.0]
        r = analyze_lap_progress(times)
        assert r.longest_flow < 3
        _ok("no_flow")
    except Exception as e:
        _fail("no_flow", str(e))

    # 6. Rolling CV
    try:
        times = [60.0, 60.0, 60.0, 60.0, 60.0]
        r = analyze_lap_progress(times)
        # All identical → CV should be 0 or very close
        for l in r.laps:
            assert l.rolling_cv_pct < 0.01, f"cv={l.rolling_cv_pct}"
        _ok("rolling_cv_tight")
    except Exception as e:
        _fail("rolling_cv_tight", str(e))

    # 7. NaN robustness
    try:
        times = [60.0, float("nan"), 61.0, None, 60.5]
        r = analyze_lap_progress(times, [1, 2, 3, 4, 5])
        assert r.n_laps == 3
        _ok("nan_robustness")
    except Exception as e:
        _fail("nan_robustness", str(e))

    # 8. Single lap
    try:
        r = analyze_lap_progress([60.0])
        assert r.n_laps == 0
        assert "Not enough" in r.coaching
        _ok("single_lap")
    except Exception as e:
        _fail("single_lap", str(e))

    # 9. Momentum: building
    try:
        # Start slow, end fast
        times = [65.0, 64.5, 64.0, 63.5, 63.0, 62.5, 62.0, 61.5, 61.0, 60.5, 60.0, 59.5]
        r = analyze_lap_progress(times)
        assert r.session_momentum == "building", f"momentum={r.session_momentum}"
        _ok("momentum_building")
    except Exception as e:
        _fail("momentum_building", str(e))

    # 10. Serialization
    try:
        times = [60.0, 60.5, 61.0, 60.2]
        r = analyze_lap_progress(times)
        d = r.to_dict()
        import json
        json.dumps(d)
        assert "laps" in d
        assert "flow_streaks" in d
        assert "pace_zone_counts" in d
        _ok("serialization")
    except Exception as e:
        _fail("serialization", str(e))

    # 11. Deterministic
    try:
        times = [60.0, 60.5, 61.0, 60.2, 59.8]
        r1 = analyze_lap_progress(times)
        r2 = analyze_lap_progress(times)
        assert r1.to_dict() == r2.to_dict()
        _ok("deterministic")
    except Exception as e:
        _fail("deterministic", str(e))

    # 12. Zone counts
    try:
        times = [60.0, 60.1, 60.2, 62.0, 65.0, 60.0, 60.05]
        r = analyze_lap_progress(times)
        total = sum(r.pace_zone_counts.values())
        assert total == 7, f"total zones={total}"
        assert "hot" in r.pace_zone_counts
        _ok("zone_counts")
    except Exception as e:
        _fail("zone_counts", str(e))

    print(f"\nLap Progress Tests: {passed}/{total} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
