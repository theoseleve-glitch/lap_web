"""
session_replay.py
-----------------
Session Replay Timeline — builds a lap-by-lap narrative of a session,
tracking the evolution of key metrics and identifying critical moments.

Concept
~~~~~~~
A session isn't just a collection of laps — it's a story. This module
reconstructs that story by tracking:

1. **Pace trajectory**: When did the driver find speed? When did they lose it?
2. **Personal bests**: The moment a new PB was set, and its context.
3. **Incidents**: Slow laps, potential mistakes, out-of-rhythm moments.
4. **Momentum shifts**: When the driver's rolling average changed trend.
5. **Stint transitions**: Pit stops, tyre changes, pace resets.

The result is a timeline of events that can be visualised as a scrollable
narrative or timeline chart.

Public API
~~~~~~~~~~
- ``build_session_timeline(laps, session_info)``
- ``classify_lap_event(lap, prev_laps, rolling_avg)``
- ``detect_momentum_shift(lap_times, window)``

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

ROLLING_WINDOW: Final[int] = 5
PB_MARGIN_PCT: Final[float] = 0.1     # PB within 0.1% also notable
SLOW_THRESHOLD_PCT: Final[float] = 5.0  # 5% slower than avg = incident
FAST_THRESHOLD_PCT: Final[float] = 1.5  # 1.5% faster than avg = hot lap
MOMENTUM_SENSITIVITY: Final[float] = 0.05  # seconds of rolling avg diff per lap


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class TimelineEvent:
    """A single event on the session timeline."""
    lap: int = 0
    lap_time_s: float = 0.0
    event_type: str = ""       # "pb", "hot_lap", "slow_lap", "momentum_up",
                                # "momentum_down", "first_lap", "stint_start",
                                # "consistent_run", "final_lap"
    severity: str = "info"     # "info", "positive", "warning", "highlight"
    description: str = ""
    delta_to_best_s: float = 0.0
    rolling_avg_s: float = 0.0
    cumulative_time_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap": self.lap,
            "lap_time_s": round(self.lap_time_s, 3),
            "event_type": self.event_type,
            "severity": self.severity,
            "description": self.description,
            "delta_to_best_s": round(self.delta_to_best_s, 3),
            "rolling_avg_s": round(self.rolling_avg_s, 3),
            "cumulative_time_s": round(self.cumulative_time_s, 3),
        }


@dataclass
class SessionTimeline:
    """Complete session timeline with events and metadata."""
    session_id: str = ""
    driver_name: str = ""
    total_laps: int = 0
    total_time_s: float = 0.0
    best_lap: int = 0
    best_time_s: float = 0.0
    events: list[TimelineEvent] = field(default_factory=list)
    summary: str = ""
    narrative: list[str] = field(default_factory=list)  # human-readable story

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "driver_name": self.driver_name,
            "total_laps": self.total_laps,
            "total_time_s": round(self.total_time_s, 3),
            "best_lap": self.best_lap,
            "best_time_s": round(self.best_time_s, 3),
            "events": [e.to_dict() for e in self.events],
            "summary": self.summary,
            "narrative": self.narrative,
            "event_counts": {
                et: sum(1 for e in self.events if e.event_type == et)
                for et in set(e.event_type for e in self.events)
            },
        }


# ============================================================================
# Core Functions
# ============================================================================


def classify_lap_event(
    lap_num: int,
    lap_time: float,
    prev_times: list[float],
    best_so_far: float,
    rolling_avg: float,
) -> Optional[TimelineEvent]:
    """
    Classify a single lap as a notable event (or None if unremarkable).

    Parameters
    ----------
    lap_num: Current lap number.
    lap_time: Current lap time in seconds.
    prev_times: All previous valid lap times.
    best_so_far: Best lap time seen so far.
    rolling_avg: Current rolling average.
    """
    if not math.isfinite(lap_time) or lap_time <= 0:
        return None

    event = TimelineEvent(lap=lap_num, lap_time_s=lap_time)

    # First lap
    if not prev_times:
        event.event_type = "first_lap"
        event.severity = "info"
        event.description = f"Session starts. Opening lap: {lap_time:.3f}s"
        return event

    event.delta_to_best_s = lap_time - best_so_far
    event.rolling_avg_s = rolling_avg

    # Personal best
    if lap_time < best_so_far:
        event.event_type = "pb"
        event.severity = "highlight"
        improvement = best_so_far - lap_time
        event.description = (
            f"NEW PERSONAL BEST! {lap_time:.3f}s "
            f"(-{improvement:.3f}s from previous best)"
        )
        return event

    # Very close to PB
    if abs(lap_time - best_so_far) / best_so_far * 100 < PB_MARGIN_PCT:
        event.event_type = "hot_lap"
        event.severity = "positive"
        event.description = (
            f"Near-PB lap: {lap_time:.3f}s "
            f"(+{event.delta_to_best_s:.3f}s from best)"
        )
        return event

    # Slow lap (incident/mistake)
    if rolling_avg > 0:
        pct_off = (lap_time - rolling_avg) / rolling_avg * 100
        if pct_off > SLOW_THRESHOLD_PCT:
            event.event_type = "slow_lap"
            event.severity = "warning"
            event.description = (
                f"Slow lap: {lap_time:.3f}s "
                f"(+{pct_off:.1f}% off rolling avg). Possible mistake or traffic."
            )
            return event

        # Fast lap (relative to rolling)
        if pct_off < -FAST_THRESHOLD_PCT:
            event.event_type = "hot_lap"
            event.severity = "positive"
            event.description = (
                f"Hot lap: {lap_time:.3f}s "
                f"({abs(pct_off):.1f}% faster than rolling avg)"
            )
            return event

    return None


def detect_momentum_shift(
    lap_times: list[float],
    window: int = ROLLING_WINDOW,
) -> list[tuple[int, str]]:
    """
    Detect laps where the rolling average trend changes direction.

    Returns
    -------
    list of (lap_number, direction)
        direction is "up" (improving) or "down" (degrading).
    """
    if len(lap_times) < window + 2:
        return []

    # Compute rolling averages
    rolling = []
    for i in range(len(lap_times)):
        start = max(0, i - window + 1)
        chunk = [t for t in lap_times[start:i + 1] if math.isfinite(t) and t > 0]
        if chunk:
            rolling.append(float(np.mean(chunk)))
        else:
            rolling.append(0.0)

    shifts: list[tuple[int, str]] = []
    # Track the dominant trend direction (only update on significant moves)
    dominant_direction = 0  # -1 = improving, +1 = degrading

    for i in range(2, len(rolling)):
        if rolling[i] <= 0 or rolling[i - 1] <= 0:
            continue
        trend = rolling[i] - rolling[i - 1]

        # Only register significant trends
        if abs(trend) < MOMENTUM_SENSITIVITY:
            continue

        current_dir = 1 if trend > 0 else -1

        if dominant_direction != 0 and current_dir != dominant_direction:
            # Trend reversal detected
            if current_dir == -1:
                shifts.append((i + 1, "up"))    # now improving
            else:
                shifts.append((i + 1, "down"))  # now degrading

        dominant_direction = current_dir

    return shifts


def build_session_timeline(
    laps: list[dict[str, Any]],
    session_info: Optional[dict[str, Any]] = None,
) -> SessionTimeline:
    """
    Build a complete session timeline from lap data.

    Parameters
    ----------
    laps:
        List of lap dicts with keys: ``lap_number``, ``lap_time_s``,
        ``is_valid`` (optional).
    session_info:
        Optional dict with ``session_id``, ``driver_name``.

    Returns
    -------
    SessionTimeline
    """
    info = session_info or {}
    tl = SessionTimeline(
        session_id=str(info.get("session_id", "")),
        driver_name=str(info.get("driver_name", "")),
    )

    # Filter and sort valid laps
    valid_laps = []
    for lap in laps:
        t = lap.get("lap_time_s")
        if t is not None and math.isfinite(float(t)) and float(t) > 0:
            n = int(lap.get("lap_number", 0))
            is_valid = lap.get("is_valid", 1)
            if is_valid not in (0, False):
                valid_laps.append((n, float(t)))

    valid_laps.sort(key=lambda x: x[0])

    if not valid_laps:
        tl.summary = "No valid lap data available."
        return tl

    tl.total_laps = len(valid_laps)

    # Build events lap by lap
    best_so_far = float("inf")
    prev_times: list[float] = []
    cumulative = 0.0
    narrative_parts: list[str] = []
    consistent_run = 0  # count of consecutive consistent laps

    for idx, (lap_num, lap_time) in enumerate(valid_laps):
        cumulative += lap_time

        # Rolling average
        window_times = prev_times[-(ROLLING_WINDOW - 1):] + [lap_time]
        rolling_avg = float(np.mean(window_times)) if window_times else lap_time

        # Classify
        event = classify_lap_event(lap_num, lap_time, prev_times, best_so_far, rolling_avg)

        if event:
            event.cumulative_time_s = cumulative
            event.rolling_avg_s = rolling_avg
            tl.events.append(event)

            # Narrative
            if event.event_type == "pb":
                narrative_parts.append(
                    f"Lap {lap_num}: Set a new personal best of {lap_time:.3f}s!"
                )
            elif event.event_type == "slow_lap":
                narrative_parts.append(
                    f"Lap {lap_num}: A slow lap at {lap_time:.3f}s disrupted rhythm."
                )

        # Track PB
        if lap_time < best_so_far:
            best_so_far = lap_time
            tl.best_lap = lap_num
            tl.best_time_s = lap_time

        # Track consistent runs (within 1% of rolling avg)
        if rolling_avg > 0 and abs(lap_time - rolling_avg) / rolling_avg < 0.01:
            consistent_run += 1
        else:
            if consistent_run >= 5:
                tl.events.append(TimelineEvent(
                    lap=lap_num - 1,
                    lap_time_s=prev_times[-1] if prev_times else lap_time,
                    event_type="consistent_run",
                    severity="positive",
                    description=f"Maintained {consistent_run}-lap consistent run "
                                f"(avg {rolling_avg:.3f}s)",
                    rolling_avg_s=rolling_avg,
                    cumulative_time_s=cumulative - lap_time,
                ))
            consistent_run = 0

        prev_times.append(lap_time)

    # Final consistent run
    if consistent_run >= 5:
        tl.events.append(TimelineEvent(
            lap=valid_laps[-1][0],
            event_type="consistent_run",
            severity="positive",
            description=f"Finished with a {consistent_run}-lap consistent run",
            cumulative_time_s=cumulative,
        ))

    # Add momentum shifts
    all_times = [t for _, t in valid_laps]
    shifts = detect_momentum_shift(all_times)
    for lap_idx_1based, direction in shifts:
        if lap_idx_1based <= len(valid_laps):
            actual_lap = valid_laps[lap_idx_1based - 1]
            tl.events.append(TimelineEvent(
                lap=actual_lap[0],
                lap_time_s=actual_lap[1],
                event_type=f"momentum_{direction}",
                severity="positive" if direction == "up" else "warning",
                description=(
                    f"Momentum shift {'UP' if direction == 'up' else 'DOWN'} "
                    f"around lap {actual_lap[0]}. "
                    f"{'Pace improving!' if direction == 'up' else 'Pace dropping.'}"
                ),
                cumulative_time_s=sum(t for _, t in valid_laps[:lap_idx_1based]),
            ))

    # Final lap event
    last = valid_laps[-1]
    tl.events.append(TimelineEvent(
        lap=last[0],
        lap_time_s=last[1],
        event_type="final_lap",
        severity="info",
        description=f"Session complete. {tl.total_laps} laps, "
                    f"best: {tl.best_time_s:.3f}s on lap {tl.best_lap}.",
        cumulative_time_s=cumulative,
    ))

    # Sort events by lap
    tl.events.sort(key=lambda e: (e.lap, e.event_type))

    tl.total_time_s = cumulative
    tl.narrative = narrative_parts

    # Summary
    pb_count = sum(1 for e in tl.events if e.event_type == "pb")
    slow_count = sum(1 for e in tl.events if e.event_type == "slow_lap")
    hot_count = sum(1 for e in tl.events if e.event_type == "hot_lap")

    tl.summary = (
        f"{tl.total_laps} laps completed. "
        f"Best: {tl.best_time_s:.3f}s (lap {tl.best_lap}). "
        f"PBs set: {pb_count}. Hot laps: {hot_count}. "
        f"Slow laps: {slow_count}."
    )

    logger.info(
        "Timeline: %d laps, %d events, best=%.3f (L%d), %d PBs, %d slow",
        tl.total_laps, len(tl.events), tl.best_time_s, tl.best_lap,
        pb_count, slow_count,
    )

    return tl


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

    def t_basic_timeline():
        laps = [{"lap_number": i + 1, "lap_time_s": 60.0 - 0.1 * i}
                for i in range(10)]
        tl = build_session_timeline(laps)
        assert tl.total_laps == 10
        assert tl.best_lap == 10  # last lap is fastest (improving)
        assert len(tl.events) > 0
        assert tl.total_time_s > 0

    _test("basic_timeline", t_basic_timeline)

    def t_pb_detection():
        laps = [
            {"lap_number": 1, "lap_time_s": 62.0},
            {"lap_number": 2, "lap_time_s": 61.5},
            {"lap_number": 3, "lap_time_s": 61.0},
            {"lap_number": 4, "lap_time_s": 60.5},
            {"lap_number": 5, "lap_time_s": 60.0},  # Best
        ]
        tl = build_session_timeline(laps)
        pb_events = [e for e in tl.events if e.event_type == "pb"]
        assert len(pb_events) >= 3  # at least laps 2,3,4 are PBs
        assert tl.best_time_s == 60.0

    _test("pb_detection", t_pb_detection)

    def t_slow_lap_detection():
        laps = [{"lap_number": i + 1, "lap_time_s": 60.0} for i in range(8)]
        laps.append({"lap_number": 9, "lap_time_s": 65.0})  # 8.3% slower
        laps.append({"lap_number": 10, "lap_time_s": 60.0})
        tl = build_session_timeline(laps)
        slow_events = [e for e in tl.events if e.event_type == "slow_lap"]
        assert len(slow_events) >= 1

    _test("slow_lap_detection", t_slow_lap_detection)

    def t_momentum_shift():
        # Improving, then degrading
        improving = [62.0 - 0.3 * i for i in range(8)]
        degrading = [60.0 + 0.3 * i for i in range(8)]
        all_times = improving + degrading
        shifts = detect_momentum_shift(all_times)
        assert len(shifts) >= 1  # at least one shift detected
        # Should be a "down" shift around lap 8-10
        down_shifts = [s for s in shifts if s[1] == "down"]
        assert len(down_shifts) >= 1

    _test("momentum_shift", t_momentum_shift)

    def t_consistent_run():
        # 10 very consistent laps
        laps = [{"lap_number": i + 1, "lap_time_s": 60.0 + (i % 2) * 0.05}
                for i in range(12)]
        tl = build_session_timeline(laps)
        consist_events = [e for e in tl.events if e.event_type == "consistent_run"]
        assert len(consist_events) >= 1

    _test("consistent_run", t_consistent_run)

    def t_no_laps():
        tl = build_session_timeline([])
        assert tl.total_laps == 0
        assert "No valid lap data" in tl.summary

    _test("no_laps", t_no_laps)

    def t_single_lap():
        laps = [{"lap_number": 1, "lap_time_s": 60.0}]
        tl = build_session_timeline(laps)
        assert tl.total_laps == 1
        assert tl.best_lap == 1

    _test("single_lap", t_single_lap)

    def t_invalid_laps_filtered():
        laps = [
            {"lap_number": 1, "lap_time_s": 60.0, "is_valid": 1},
            {"lap_number": 2, "lap_time_s": 120.0, "is_valid": 0},  # invalid
            {"lap_number": 3, "lap_time_s": 60.5, "is_valid": 1},
        ]
        tl = build_session_timeline(laps)
        assert tl.total_laps == 2  # only valid laps

    _test("invalid_laps_filtered", t_invalid_laps_filtered)

    def t_nan_robustness():
        laps = [
            {"lap_number": 1, "lap_time_s": 60.0},
            {"lap_number": 2, "lap_time_s": float("nan")},
            {"lap_number": 3, "lap_time_s": None},
            {"lap_number": 4, "lap_time_s": 60.5},
            {"lap_number": 5, "lap_time_s": 61.0},
        ]
        tl = build_session_timeline(laps)
        assert tl.total_laps >= 2
        assert math.isfinite(tl.total_time_s)

    _test("nan_robustness", t_nan_robustness)

    def t_serialization():
        laps = [{"lap_number": i + 1, "lap_time_s": 60.0 + i * 0.05}
                for i in range(10)]
        tl = build_session_timeline(laps, {"session_id": "test", "driver_name": "T"})
        d = tl.to_dict()
        assert "events" in d
        assert "summary" in d
        assert "event_counts" in d
        assert d["session_id"] == "test"

    _test("serialization", t_serialization)

    def t_deterministic():
        laps = [{"lap_number": i + 1, "lap_time_s": 60.0 + 0.08 * i}
                for i in range(15)]
        tl1 = build_session_timeline(laps)
        tl2 = build_session_timeline(laps)
        assert tl1.to_dict() == tl2.to_dict()

    _test("deterministic", t_deterministic)

    def t_event_types():
        """Ensure all event types are valid."""
        valid_types = {
            "pb", "hot_lap", "slow_lap", "momentum_up", "momentum_down",
            "first_lap", "stint_start", "consistent_run", "final_lap",
        }
        laps = [{"lap_number": i + 1, "lap_time_s": 60.0 - 0.2 * i}
                for i in range(10)]
        tl = build_session_timeline(laps)
        for e in tl.events:
            assert e.event_type in valid_types, f"Unknown type: {e.event_type}"

    _test("event_types", t_event_types)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nSession Replay Timeline Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
