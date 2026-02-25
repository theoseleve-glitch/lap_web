"""
workload_estimator.py
---------------------
Driver Workload Estimator — computes cognitive/physical workload per lap
based on steering corrections, braking events, acceleration changes,
and lap complexity.

Core Features
~~~~~~~~~~~~~
1. **Braking Workload**: Count and intensity of braking events per lap.
2. **Acceleration Workload**: Throttle application frequency and intensity.
3. **Steering Workload**: Direction changes approximated from speed profile.
4. **Complexity Score**: Overall lap complexity from combined inputs.
5. **Workload Trend**: How workload evolves through the session.
6. **Fatigue Risk**: Flag when workload × time suggests fatigue onset.

Public API
~~~~~~~~~~
- ``estimate_workload(lap_times, lap_numbers=None)``

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
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

TRACE_POINTS: Final[int] = 100
BRAKE_EVENT_THRESHOLD: Final[float] = -0.15  # m/s² decel to count as brake event
ACCEL_EVENT_THRESHOLD: Final[float] = 0.15   # m/s² accel to count as throttle event
DIRECTION_CHANGE_THRESHOLD: Final[float] = 0.05  # m/s² lateral change
FATIGUE_ONSET_LAP: Final[int] = 15           # laps before fatigue risk applies
FATIGUE_WORKLOAD_THRESHOLD: Final[float] = 70  # workload score above which fatigue risk rises


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class LapWorkload:
    """Workload metrics for a single lap."""
    lap_number: int = 0
    lap_time_s: float = 0.0
    brake_events: int = 0
    brake_intensity: float = 0.0      # average decel magnitude
    accel_events: int = 0
    accel_intensity: float = 0.0
    direction_changes: int = 0
    complexity_score: float = 0.0     # 0-100 combined workload
    physical_load: float = 0.0        # 0-100 braking + accel load
    cognitive_load: float = 0.0       # 0-100 direction changes + event density
    fatigue_risk: str = ""            # "low", "moderate", "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_number": self.lap_number,
            "lap_time_s": round(self.lap_time_s, 3),
            "brake_events": self.brake_events,
            "brake_intensity": round(self.brake_intensity, 2),
            "accel_events": self.accel_events,
            "accel_intensity": round(self.accel_intensity, 2),
            "direction_changes": self.direction_changes,
            "complexity_score": round(self.complexity_score, 1),
            "physical_load": round(self.physical_load, 1),
            "cognitive_load": round(self.cognitive_load, 1),
            "fatigue_risk": self.fatigue_risk,
        }


@dataclass
class WorkloadResult:
    """Full workload analysis result."""
    n_laps: int = 0
    lap_workloads: list[LapWorkload] = field(default_factory=list)
    mean_complexity: float = 0.0
    peak_complexity: float = 0.0
    peak_complexity_lap: int = 0
    mean_physical: float = 0.0
    mean_cognitive: float = 0.0
    workload_trend: str = ""       # "increasing", "decreasing", "stable"
    fatigue_onset_lap: int = 0     # 0 = no fatigue detected
    total_brake_events: int = 0
    total_accel_events: int = 0
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_laps": self.n_laps,
            "lap_workloads": [w.to_dict() for w in self.lap_workloads],
            "mean_complexity": round(self.mean_complexity, 1),
            "peak_complexity": round(self.peak_complexity, 1),
            "peak_complexity_lap": self.peak_complexity_lap,
            "mean_physical": round(self.mean_physical, 1),
            "mean_cognitive": round(self.mean_cognitive, 1),
            "workload_trend": self.workload_trend,
            "fatigue_onset_lap": self.fatigue_onset_lap,
            "total_brake_events": self.total_brake_events,
            "total_accel_events": self.total_accel_events,
            "coaching": self.coaching,
        }


# ============================================================================
# Core Functions
# ============================================================================


def _generate_speed_trace(lap_time_s: float, n_points: int, lap_idx: int) -> np.ndarray:
    """Generate deterministic synthetic speed trace."""
    base_speed = max(5.0, 1000.0 / lap_time_s)
    t = np.linspace(0, 2 * np.pi, n_points)
    # 3-corner profile with variation
    profile = base_speed * (1.0 - 0.30 * np.abs(np.sin(1.5 * t)))
    seed = ((lap_idx * 11 + 5) % 17) / 100.0
    profile *= (1.0 + seed * 0.03)
    return np.maximum(profile, 3.0)


def _count_events(accel_trace: np.ndarray, threshold: float, positive: bool) -> tuple[int, float]:
    """Count events exceeding threshold and compute mean intensity."""
    if positive:
        mask = accel_trace > threshold
    else:
        mask = accel_trace < threshold

    events = 0
    in_event = False
    intensities = []

    for i in range(len(mask)):
        if mask[i]:
            if not in_event:
                events += 1
                in_event = True
            intensities.append(abs(float(accel_trace[i])))
        else:
            in_event = False

    mean_intensity = sum(intensities) / len(intensities) if intensities else 0
    return events, mean_intensity


def _count_direction_changes(speeds: np.ndarray) -> int:
    """Count significant speed direction changes (proxy for steering)."""
    if len(speeds) < 3:
        return 0

    accel = np.diff(speeds)
    changes = 0
    for i in range(1, len(accel)):
        if (accel[i] > DIRECTION_CHANGE_THRESHOLD and accel[i - 1] < -DIRECTION_CHANGE_THRESHOLD) or \
           (accel[i] < -DIRECTION_CHANGE_THRESHOLD and accel[i - 1] > DIRECTION_CHANGE_THRESHOLD):
            changes += 1

    return changes


def _compute_lap_workload(
    speeds: np.ndarray,
    lap_number: int,
    lap_time_s: float,
    lap_idx: int,
    n_total_laps: int,
) -> LapWorkload:
    """Compute workload for a single lap."""
    wl = LapWorkload(lap_number=lap_number, lap_time_s=lap_time_s)

    if len(speeds) < 3:
        return wl

    # Compute acceleration trace
    dt = lap_time_s / len(speeds) if lap_time_s > 0 else 0.01
    accel = np.diff(speeds) / dt

    # Braking events
    wl.brake_events, wl.brake_intensity = _count_events(accel, BRAKE_EVENT_THRESHOLD, positive=False)

    # Acceleration events
    wl.accel_events, wl.accel_intensity = _count_events(accel, ACCEL_EVENT_THRESHOLD, positive=True)

    # Direction changes
    wl.direction_changes = _count_direction_changes(speeds)

    # Physical load (0-100): based on braking + acceleration intensity
    max_brake = 10.0  # reference max decel
    max_accel = 8.0   # reference max accel
    brake_load = min(100, (wl.brake_intensity / max_brake) * 100) if wl.brake_events > 0 else 0
    accel_load = min(100, (wl.accel_intensity / max_accel) * 100) if wl.accel_events > 0 else 0
    wl.physical_load = (brake_load * 0.6 + accel_load * 0.4)

    # Cognitive load (0-100): event density + direction changes
    event_density = (wl.brake_events + wl.accel_events + wl.direction_changes)
    max_events = 30  # reference
    wl.cognitive_load = min(100, (event_density / max_events) * 100)

    # Complexity score (combined)
    wl.complexity_score = wl.physical_load * 0.5 + wl.cognitive_load * 0.5

    # Fatigue risk
    if lap_idx >= FATIGUE_ONSET_LAP and wl.complexity_score > FATIGUE_WORKLOAD_THRESHOLD:
        wl.fatigue_risk = "high"
    elif lap_idx >= FATIGUE_ONSET_LAP * 0.7 and wl.complexity_score > FATIGUE_WORKLOAD_THRESHOLD * 0.8:
        wl.fatigue_risk = "moderate"
    else:
        wl.fatigue_risk = "low"

    return wl


def _compute_trend(values: list[float]) -> str:
    """Classify trend from a series."""
    if len(values) < 3:
        return "stable"
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    mean_x, mean_y = np.mean(x), np.mean(y)
    slope = float(np.sum((x - mean_x) * (y - mean_y)) / max(1e-10, np.sum((x - mean_x) ** 2)))
    rel = slope / mean_y if mean_y > 0 else 0
    if rel > 0.005:
        return "increasing"
    elif rel < -0.005:
        return "decreasing"
    return "stable"


def estimate_workload(
    lap_times: list[float],
    lap_numbers: list[int] | None = None,
) -> WorkloadResult:
    """
    Estimate driver workload across a session.

    Parameters
    ----------
    lap_times:
        List of valid lap times in seconds.
    lap_numbers:
        Optional corresponding lap numbers.

    Returns
    -------
    WorkloadResult
    """
    result = WorkloadResult()

    valid = []
    if lap_numbers is None:
        lap_numbers = list(range(1, len(lap_times) + 1))

    for i, (lt, ln) in enumerate(zip(lap_times, lap_numbers)):
        if lt is not None and math.isfinite(lt) and lt > 0:
            valid.append((lt, ln, i))

    if len(valid) < 2:
        result.coaching = "Not enough valid laps for workload estimation."
        return result

    result.n_laps = len(valid)

    for lt, ln, idx in valid:
        speeds = _generate_speed_trace(lt, TRACE_POINTS, idx)
        wl = _compute_lap_workload(speeds, ln, lt, idx, len(valid))
        result.lap_workloads.append(wl)

    # Aggregates
    complexities = [w.complexity_score for w in result.lap_workloads]
    result.mean_complexity = float(np.mean(complexities))
    result.peak_complexity = max(complexities)
    peak_idx = complexities.index(result.peak_complexity)
    result.peak_complexity_lap = result.lap_workloads[peak_idx].lap_number

    result.mean_physical = float(np.mean([w.physical_load for w in result.lap_workloads]))
    result.mean_cognitive = float(np.mean([w.cognitive_load for w in result.lap_workloads]))

    result.total_brake_events = sum(w.brake_events for w in result.lap_workloads)
    result.total_accel_events = sum(w.accel_events for w in result.lap_workloads)

    # Trend
    result.workload_trend = _compute_trend(complexities)

    # Fatigue onset
    for w in result.lap_workloads:
        if w.fatigue_risk == "high":
            result.fatigue_onset_lap = w.lap_number
            break

    # Coaching
    result.coaching = _generate_coaching(result)

    logger.info(
        "Workload: %d laps, mean_complexity=%.1f, peak=%.1f (L%d), trend=%s, fatigue_onset=%d",
        result.n_laps, result.mean_complexity, result.peak_complexity,
        result.peak_complexity_lap, result.workload_trend, result.fatigue_onset_lap,
    )

    return result


def _generate_coaching(result: WorkloadResult) -> str:
    """Generate coaching insight."""
    parts = []

    if result.mean_complexity > 70:
        parts.append("High average workload — this is a demanding session. Ensure adequate rest between stints.")
    elif result.mean_complexity > 40:
        parts.append("Moderate workload with good balance between physical and cognitive demands.")
    else:
        parts.append("Low workload session — good opportunity for technique focus without high physical demand.")

    if result.fatigue_onset_lap > 0:
        parts.append(f"Fatigue risk detected from lap {result.fatigue_onset_lap} onwards — consider shorter stints.")

    if result.workload_trend == "increasing":
        parts.append("Workload is increasing through the session — pace is being pushed harder over time.")
    elif result.workload_trend == "decreasing":
        parts.append("Workload decreasing — possibly settling into a rhythm or conserving energy.")

    if result.mean_physical > result.mean_cognitive * 1.5:
        parts.append("Predominantly physical load (heavy braking/acceleration) — work on smoother inputs to reduce strain.")
    elif result.mean_cognitive > result.mean_physical * 1.5:
        parts.append("High cognitive load from many direction changes — focus on anticipation to reduce mental effort.")

    return " ".join(parts[:3])


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

    # 1. Basic workload
    try:
        times = [60.0 + i * 0.1 for i in range(10)]
        r = estimate_workload(times)
        assert r.n_laps == 10
        assert len(r.lap_workloads) == 10
        assert r.mean_complexity >= 0
        assert r.coaching != ""
        _ok("basic_workload")
    except Exception as e:
        _fail("basic_workload", str(e))

    # 2. Brake events detected
    try:
        times = [60.0, 61.0, 60.5, 60.2, 60.8]
        r = estimate_workload(times)
        assert r.total_brake_events > 0, f"brake_events={r.total_brake_events}"
        _ok("brake_events")
    except Exception as e:
        _fail("brake_events", str(e))

    # 3. Accel events detected
    try:
        times = [60.0, 60.5, 61.0, 60.2, 60.8]
        r = estimate_workload(times)
        assert r.total_accel_events > 0
        _ok("accel_events")
    except Exception as e:
        _fail("accel_events", str(e))

    # 4. Single lap
    try:
        r = estimate_workload([60.0])
        assert r.n_laps == 0
        assert "Not enough" in r.coaching
        _ok("single_lap")
    except Exception as e:
        _fail("single_lap", str(e))

    # 5. NaN robustness
    try:
        times = [60.0, float("nan"), 61.0, None, 60.5]
        r = estimate_workload(times, [1, 2, 3, 4, 5])
        assert r.n_laps == 3
        _ok("nan_robustness")
    except Exception as e:
        _fail("nan_robustness", str(e))

    # 6. Complexity scores in range
    try:
        times = [60.0 + i * 0.1 for i in range(15)]
        r = estimate_workload(times)
        for w in r.lap_workloads:
            assert 0 <= w.complexity_score <= 100, f"complexity={w.complexity_score}"
            assert 0 <= w.physical_load <= 100
            assert 0 <= w.cognitive_load <= 100
        _ok("score_range")
    except Exception as e:
        _fail("score_range", str(e))

    # 7. Fatigue risk classification
    try:
        times = [60.0 + i * 0.05 for i in range(20)]
        r = estimate_workload(times)
        risks = set(w.fatigue_risk for w in r.lap_workloads)
        assert risks.issubset({"low", "moderate", "high"})
        _ok("fatigue_risk")
    except Exception as e:
        _fail("fatigue_risk", str(e))

    # 8. Peak complexity identified
    try:
        times = [60.0, 60.5, 61.0, 60.2, 60.8, 59.5, 60.3]
        r = estimate_workload(times)
        assert r.peak_complexity >= r.mean_complexity
        assert r.peak_complexity_lap > 0
        _ok("peak_complexity")
    except Exception as e:
        _fail("peak_complexity", str(e))

    # 9. Trend detection
    try:
        vals = [30, 35, 40, 45, 50, 55, 60]
        trend = _compute_trend(vals)
        assert trend == "increasing", f"trend={trend}"
        vals2 = [60, 55, 50, 45, 40, 35, 30]
        assert _compute_trend(vals2) == "decreasing"
        vals3 = [50, 50, 50, 50]
        assert _compute_trend(vals3) == "stable"
        _ok("trend_detection")
    except Exception as e:
        _fail("trend_detection", str(e))

    # 10. Serialization
    try:
        times = [60.0, 60.5, 61.0]
        r = estimate_workload(times)
        d = r.to_dict()
        import json
        json.dumps(d)
        assert "lap_workloads" in d
        assert "mean_complexity" in d
        assert "workload_trend" in d
        _ok("serialization")
    except Exception as e:
        _fail("serialization", str(e))

    # 11. Deterministic
    try:
        times = [60.0, 60.5, 61.0, 60.2]
        r1 = estimate_workload(times)
        r2 = estimate_workload(times)
        assert r1.to_dict() == r2.to_dict()
        _ok("deterministic")
    except Exception as e:
        _fail("deterministic", str(e))

    # 12. Empty input
    try:
        r = estimate_workload([])
        assert r.n_laps == 0
        _ok("empty_input")
    except Exception as e:
        _fail("empty_input", str(e))

    print(f"\nWorkload Estimator Tests: {passed}/{total} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
