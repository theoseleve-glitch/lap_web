"""
race_intelligence.py
--------------------
Stateless race intelligence -- pure functions that take engine state
and return predictions, alerts, and analysis.

All functions are read-only: they never mutate engine state.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PACE_TOLERANCE_S = 30
_FUEL_WARNING_S = 300
_FUEL_CRITICAL_S = 120


def predict_finish(
    race_duration_s: int,
    elapsed_s: float,
    stints: list[dict],
    race_start_ts: str | None,
    neutralizations: list[dict],
) -> dict[str, Any]:
    """Predict race finish time, pace delta, and completion percentage."""
    remaining = max(0.0, race_duration_s - elapsed_s)
    completion = (elapsed_s / race_duration_s * 100) if race_duration_s > 0 else 0.0

    pace_delta = 0
    for s in stints:
        if s.get("status") == "completed":
            actual = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
            planned = s.get("planned_duration_s") or 0
            pace_delta += actual - planned

    if pace_delta > _PACE_TOLERANCE_S:
        pace_status = "BEHIND"
    elif pace_delta < -_PACE_TOLERANCE_S:
        pace_status = "AHEAD"
    else:
        pace_status = "ON PLAN"

    neutralized_total = 0.0
    for n in neutralizations:
        ns = n["start_s"]
        ne = n.get("end_s") or elapsed_s
        if ne > ns:
            neutralized_total += ne - ns

    return {
        "remaining_s": int(remaining),
        "completion_pct": round(completion, 1),
        "pace_delta_s": pace_delta,
        "pace_status": pace_status,
        "race_start_ts": race_start_ts,
        "neutralized_total_s": int(neutralized_total),
    }


def fuel_alerts(
    current_fuel_kg: float,
    burn_rate_kgs: float,
    active_stint_end_s: int,
    elapsed_s: float,
    next_planned_pit_s: int | None,
) -> dict[str, Any]:
    """Fuel red zone alerts: countdown to empty, can-reach-pit check."""
    if burn_rate_kgs <= 0:
        return {
            "fuel_remaining_s": 999999,
            "fuel_status": "ok",
            "can_reach_pit": True,
            "shortfall_s": 0,
        }

    fuel_remaining_s = current_fuel_kg / burn_rate_kgs

    if fuel_remaining_s < _FUEL_CRITICAL_S:
        status = "critical"
    elif fuel_remaining_s < _FUEL_WARNING_S:
        status = "warning"
    else:
        status = "ok"

    pit_target = next_planned_pit_s or active_stint_end_s
    time_to_pit = max(0.0, pit_target - elapsed_s)
    fuel_needed_s = time_to_pit
    can_reach = fuel_remaining_s >= fuel_needed_s
    shortfall = max(0, int(fuel_needed_s - fuel_remaining_s)) if not can_reach else 0

    return {
        "fuel_remaining_s": int(fuel_remaining_s),
        "fuel_status": status,
        "can_reach_pit": can_reach,
        "shortfall_s": shortfall,
    }


# ---------------------------------------------------------------------------
# Pace analysis constants
# ---------------------------------------------------------------------------

_SWAP_PACE_THRESHOLD = 0.10   # 10 % degradation triggers swap suggestion
_TREND_THRESHOLD_S = 20       # seconds between consecutive stints to flag trend


def pace_analysis(
    stints: list[dict],
    active_stint: dict | None,
    elapsed_s: float,
) -> dict[str, Any]:
    """Analyse pace relative to own average and field average.

    Returns a dict with:
      - pace_vs_own_avg_s:   projected stint delta vs driver's own average (int | None)
      - pace_vs_field_avg_s: projected stint delta vs all-driver average  (int | None)
      - pace_trend:          "improving" | "degrading" | "stable"
      - recommendation:      optional string or None
    """
    completed = [s for s in stints if s.get("status") == "completed"]

    if not completed:
        return {
            "pace_vs_own_avg_s": None,
            "pace_vs_field_avg_s": None,
            "pace_trend": "stable",
            "recommendation": None,
        }

    # -- field average across all completed stints --
    field_durations = [
        s.get("actual_duration_s") or s.get("planned_duration_s")
        for s in completed
    ]
    field_avg = sum(field_durations) / len(field_durations) if field_durations else 0

    # -- own-average comparison (only when active stint is running) --
    pace_vs_own: int | None = None
    if active_stint:
        driver_id = active_stint.get("driver_id")
        own_stints = [s for s in completed if s.get("driver_id") == driver_id]
        if own_stints:
            own_durations = [
                s.get("actual_duration_s") or s.get("planned_duration_s")
                for s in own_stints
            ]
            own_avg = sum(own_durations) / len(own_durations)
            time_in_stint = elapsed_s - active_stint.get("planned_start_s", 0)
            planned = active_stint.get("planned_duration_s", 1)
            if time_in_stint > 0 and planned > 0:
                rate = time_in_stint / planned
                projected = planned * rate if rate > 0.1 else planned
                pace_vs_own = int(projected - own_avg)

    # -- field-average comparison --
    pace_vs_field: int | None = None
    if active_stint and field_avg > 0:
        time_in_stint = elapsed_s - active_stint.get("planned_start_s", 0)
        planned = active_stint.get("planned_duration_s", 1)
        if time_in_stint > 0 and planned > 0:
            rate = time_in_stint / planned
            projected = planned * rate if rate > 0.1 else planned
            pace_vs_field = int(projected - field_avg)

    # -- trend detection across last 3 completed stints --
    if active_stint:
        own_completed = [
            s for s in completed
            if s.get("driver_id") == active_stint.get("driver_id")
        ]
    else:
        own_completed = completed

    trend = "stable"
    if len(own_completed) >= 3:
        last3 = own_completed[-3:]
        durations = [
            s.get("actual_duration_s") or s.get("planned_duration_s")
            for s in last3
        ]
        diffs = [durations[i + 1] - durations[i] for i in range(len(durations) - 1)]
        if all(d > _TREND_THRESHOLD_S for d in diffs):
            trend = "degrading"
        elif all(d < -_TREND_THRESHOLD_S for d in diffs):
            trend = "improving"

    recommendation = "Consider early driver swap" if trend == "degrading" else None

    return {
        "pace_vs_own_avg_s": pace_vs_own,
        "pace_vs_field_avg_s": pace_vs_field,
        "pace_trend": trend,
        "recommendation": recommendation,
    }


def swap_suggestion(
    stints: list[dict],
    drivers: list[dict],
    active_stint: dict | None,
    elapsed_s: float,
    burn_rate_kgs: float,
    current_fuel_kg: float,
) -> dict[str, Any] | None:
    """Suggest a driver swap when the active driver's pace has degraded.

    Returns None when no swap is needed, or a dict with:
      - suggest_swap:    True
      - reason:          human-readable explanation
      - next_driver:     name of the suggested replacement driver
      - degradation_pct: percentage slower than own average
    """
    if not active_stint or not drivers:
        return None

    driver_id = active_stint.get("driver_id")
    completed = [
        s for s in stints
        if s.get("status") == "completed" and s.get("driver_id") == driver_id
    ]

    if len(completed) < 2:
        return None

    own_durations = [
        s.get("actual_duration_s") or s.get("planned_duration_s")
        for s in completed
    ]

    # Use last completed stint as the best indicator of current pace,
    # and compare against the average of all earlier completed stints.
    last_duration = own_durations[-1]
    earlier_avg = sum(own_durations[:-1]) / len(own_durations[:-1])
    degradation = (last_duration - earlier_avg) / earlier_avg if earlier_avg > 0 else 0

    if degradation < _SWAP_PACE_THRESHOLD:
        return None

    # Ensure there is enough fuel to even reach the pits (60 s minimum)
    min_fuel_s = 60
    fuel_remaining_s = current_fuel_kg / burn_rate_kgs if burn_rate_kgs > 0 else 999999
    if fuel_remaining_s < min_fuel_s:
        return None

    active_driver_name = next(
        (d.get("driver_name", "Unknown") for d in drivers if d.get("id") == driver_id),
        "Unknown",
    )
    next_driver = next(
        (d.get("driver_name", "Unknown") for d in drivers if d.get("id") != driver_id),
        None,
    )

    if not next_driver:
        return None

    return {
        "suggest_swap": True,
        "reason": f"{active_driver_name} is {degradation:.0%} slower than their average",
        "next_driver": next_driver,
        "degradation_pct": round(degradation * 100, 1),
    }


def rival_analysis(
    rivals: list[dict],
    rival_events: list[dict],
    elapsed_s: float,
) -> list[dict[str, Any]]:
    """Analyse rival pit patterns and estimate their strategy.

    Returns a list of dicts (one per rival) with:
      - rival_id, team_name, car_number
      - estimated_pits:  count of observed pit-in events
      - avg_stint_s:     average gap between consecutive pit-ins
      - last_activity_s: seconds since their most recent event
    """
    if not rivals:
        return []

    results: list[dict[str, Any]] = []
    for rival in rivals:
        rid = rival.get("id")
        events = [e for e in rival_events if e.get("rival_id") == rid]

        pit_events = sorted(
            [e for e in events if e.get("event_type") == "pit_in"],
            key=lambda e: e["at_s"],
        )
        estimated_pits = len(pit_events)

        avg_stint = 0
        if len(pit_events) >= 2:
            gaps = [
                pit_events[i + 1]["at_s"] - pit_events[i]["at_s"]
                for i in range(len(pit_events) - 1)
            ]
            avg_stint = int(sum(gaps) / len(gaps))

        all_sorted = sorted(events, key=lambda e: e["at_s"])
        last_activity_s = int(elapsed_s - all_sorted[-1]["at_s"]) if all_sorted else None

        results.append({
            "rival_id": rid,
            "team_name": rival.get("team_name", "Unknown"),
            "car_number": rival.get("car_number", ""),
            "estimated_pits": estimated_pits,
            "avg_stint_s": avg_stint,
            "last_activity_s": last_activity_s,
        })

    return results


def analyze_race(
    race_duration_s: int,
    elapsed_s: float,
    race_start_ts: str | None,
    stints: list[dict],
    active_stint: dict | None,
    drivers: list[dict],
    neutralizations: list[dict],
    current_fuel_kg: float,
    burn_rate_kgs: float,
    active_stint_end_s: int,
    next_planned_pit_s: int | None,
    rivals: list[dict],
    rival_events: list[dict],
) -> dict[str, Any]:
    """Top-level race analysis aggregator.

    Calls every intelligence sub-function and returns a unified dict
    with keys: finish, fuel, pace, swap, rivals.
    """
    return {
        "finish": predict_finish(
            race_duration_s, elapsed_s, stints,
            race_start_ts, neutralizations,
        ),
        "fuel": fuel_alerts(
            current_fuel_kg, burn_rate_kgs,
            active_stint_end_s, elapsed_s, next_planned_pit_s,
        ),
        "pace": pace_analysis(stints, active_stint, elapsed_s),
        "swap": swap_suggestion(
            stints, drivers, active_stint,
            elapsed_s, burn_rate_kgs, current_fuel_kg,
        ),
        "rivals": rival_analysis(rivals, rival_events, elapsed_s),
    }
