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
