"""
race_strategy_v2.py
-------------------
Endurance race strategy optimizer: constraint-bounded stint allocation
with ballast and fuel calculations.

Public API
~~~~~~~~~~
``optimize_stints(config, drivers)``
    Generate optimal stint plan satisfying all constraints.
``compute_ballast(min_total_kart_kg, empty_kart_kg, fuel_kg, driver_weight_kg)``
    Calculate required ballast weight.
``reoptimize_remaining(config, drivers, completed_stints, elapsed_s)``
    Mid-race re-optimization with completed stints fixed.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_ballast(
    min_total_kart_kg: float,
    empty_kart_kg: float,
    fuel_kg: float,
    driver_weight_kg: float,
) -> float:
    """Calculate required ballast to meet minimum kart weight."""
    current = empty_kart_kg + fuel_kg + driver_weight_kg
    needed = min_total_kart_kg - current
    return max(0.0, round(needed, 2))


def optimize_stints(
    config: dict[str, Any],
    drivers: list[dict[str, Any]],
    sleep_windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Generate optimal stint plan using constraint-bounded equal distribution.

    Parameters
    ----------
    config : dict
        race_duration_s, desired_stints, min_pit_stop_s, fuel_autonomy_s,
        empty_kart_kg, full_tank_kg, min_total_kart_kg (all optional except duration/stints)
    drivers : list[dict]
        Each with: id, driver_name, driver_order, weight_kg,
        min_stint_s, max_stint_s, min_cumulative_s, max_cumulative_s, min_rest_s

    Returns
    -------
    dict with feasible, stints, pit_stops, driver_summary, violations, warnings
    """
    race_duration = config["race_duration_s"]
    n_stints = max(1, config.get("desired_stints") or 1)
    pit_time = config.get("min_pit_stop_s") or 60
    fuel_autonomy = config.get("fuel_autonomy_s")

    # Qualifying fuel deduction: first stint has less fuel if not refueled after quali
    quali_duration = config.get("qualifying_duration_s") or 0
    refuel_after_quali = config.get("refuel_after_quali", 0)
    first_stint_autonomy = fuel_autonomy
    if fuel_autonomy and quali_duration and not refuel_after_quali:
        first_stint_autonomy = max(0, fuel_autonomy - quali_duration)

    # Pit window boundaries
    pit_open = config.get("pit_open_s")
    pit_close_before_end = config.get("pit_close_s")
    pit_close = (race_duration - pit_close_before_end) if pit_close_before_end else None

    if not drivers:
        return {"feasible": False, "stints": [], "pit_stops": [],
                "driver_summary": {}, "violations": ["No drivers configured"],
                "warnings": [], "total_pit_time_s": 0, "total_drive_time_s": 0}

    # Sort drivers by order
    drivers = sorted(drivers, key=lambda d: d.get("driver_order", 0))

    # Auto-increase stints if fuel autonomy requires it
    if fuel_autonomy:
        eff_first = first_stint_autonomy or fuel_autonomy
        while True:
            n_pits = n_stints - 1
            drive_time = race_duration - n_pits * pit_time
            if drive_time <= 0:
                break
            # Check both: average stint fits AND total capacity covers drive time
            max_capacity = eff_first + (n_stints - 1) * fuel_autonomy
            if drive_time / n_stints <= fuel_autonomy and max_capacity >= drive_time:
                break
            n_stints += 1

    # Effective drive time (subtract pit stops)
    n_pits = n_stints - 1
    total_pit_time = n_pits * pit_time
    drive_time = race_duration - total_pit_time

    if drive_time <= 0:
        return {"feasible": False, "stints": [], "pit_stops": [],
                "driver_summary": {}, "violations": ["Pit stops exceed race duration"],
                "warnings": [], "total_pit_time_s": total_pit_time, "total_drive_time_s": 0}

    # Ideal equal stint length
    ideal_stint = drive_time / n_stints

    # Assign drivers round-robin
    stints = []
    cumulative = {}  # driver_id -> total seconds assigned
    last_end = {}    # driver_id -> end time of their last stint

    violations = []
    warnings = []
    clock = 0  # seconds from race start

    for i in range(n_stints):
        driver = drivers[i % len(drivers)]
        did = driver["id"]

        # Calculate stint duration
        duration = ideal_stint

        # Apply driver max stint
        d_max = driver.get("max_stint_s")
        if d_max and duration > d_max:
            duration = d_max

        # Apply driver min stint
        d_min = driver.get("min_stint_s")
        if d_min and duration < d_min:
            duration = d_min

        # Apply fuel autonomy (reduced for first stint if qualifying without refuel)
        effective_autonomy = first_stint_autonomy if i == 0 else fuel_autonomy
        if effective_autonomy and duration > effective_autonomy:
            duration = effective_autonomy

        # Check driver cumulative max
        d_cum_max = driver.get("max_cumulative_s")
        so_far = cumulative.get(did, 0)
        if d_cum_max and so_far + duration > d_cum_max:
            duration = max(0, d_cum_max - so_far)

        # Check rest time
        d_rest = driver.get("min_rest_s") or 0
        if did in last_end and d_rest > 0:
            rest_available = clock - last_end[did]
            if rest_available < d_rest:
                warnings.append(
                    f"{driver['driver_name']} has only {rest_available}s rest "
                    f"(needs {d_rest}s) before stint {i + 1}"
                )

        duration = round(duration)

        stints.append({
            "stint_order": i + 1,
            "driver_id": did,
            "driver_name": driver["driver_name"],
            "planned_start_s": round(clock),
            "planned_end_s": round(clock + duration),
            "planned_duration_s": duration,
            "ballast_kg": _compute_stint_ballast(config, driver, i == 0),
        })

        cumulative[did] = cumulative.get(did, 0) + duration
        last_end[did] = clock + duration
        clock += duration

        # Add pit stop time (except after last stint)
        if i < n_stints - 1:
            clock += pit_time

    # Redistribute slack using multi-pass greedy approach
    for _pass in range(10):  # max 10 redistribution passes
        total_assigned = sum(s["planned_duration_s"] for s in stints)
        slack = drive_time - total_assigned
        if slack < 1:
            break

        # Find stints that can accept more time
        expandable = []
        for i, s in enumerate(stints):
            did = s["driver_id"]
            driver = next(d for d in drivers if d["id"] == did)
            eff_autonomy = first_stint_autonomy if i == 0 else fuel_autonomy
            cap = _stint_cap(driver, eff_autonomy)
            room = cap - s["planned_duration_s"] if cap else slack
            if room > 0:
                expandable.append((i, room))

        if not expandable:
            break

        per_stint_extra = slack / len(expandable)
        for idx, room in expandable:
            give = min(per_stint_extra, room)
            stints[idx]["planned_duration_s"] += round(give)

    # Rebuild timeline after redistribution
    if stints:
        clock = 0
        for i, s in enumerate(stints):
            s["planned_start_s"] = round(clock)
            s["planned_end_s"] = round(clock + s["planned_duration_s"])
            clock += s["planned_duration_s"]
            if i < n_stints - 1:
                clock += pit_time

        # Update cumulative after redistribution
        cumulative = {}
        for s in stints:
            cumulative[s["driver_id"]] = cumulative.get(s["driver_id"], 0) + s["planned_duration_s"]

    # Pit window enforcement: adjust stint boundaries
    if pit_open and len(stints) > 1:
        first_stint = stints[0]
        if first_stint["planned_end_s"] < pit_open:
            deficit = pit_open - first_stint["planned_end_s"]
            first_stint["planned_duration_s"] += deficit
            first_stint["planned_end_s"] = pit_open
            # Rebuild clock from first stint
            clock = first_stint["planned_end_s"] + pit_time
            for j in range(1, len(stints)):
                stints[j]["planned_start_s"] = round(clock)
                stints[j]["planned_end_s"] = round(clock + stints[j]["planned_duration_s"])
                clock += stints[j]["planned_duration_s"]
                if j < len(stints) - 1:
                    clock += pit_time

    if pit_close and len(stints) > 1:
        last_pit_idx = len(stints) - 2
        last_pit_at = stints[last_pit_idx]["planned_end_s"]
        if last_pit_at > pit_close:
            overshoot = last_pit_at - pit_close
            stints[last_pit_idx]["planned_duration_s"] -= overshoot
            stints[last_pit_idx]["planned_end_s"] -= overshoot
            stints[-1]["planned_start_s"] -= overshoot
            stints[-1]["planned_duration_s"] += overshoot

    # Sleep window overlap warnings (soft constraint)
    if sleep_windows:
        for s in stints:
            did = s["driver_id"]
            s_start = s["planned_start_s"]
            s_end = s["planned_end_s"]
            driver_name = s.get("driver_name", f"Driver {did}")
            for sw in sleep_windows:
                if sw.get("driver_id") != did:
                    continue
                sw_start = sw.get("start_s", 0)
                sw_end = sw.get("end_s", 0)
                overlap_start = max(s_start, sw_start)
                overlap_end = min(s_end, sw_end)
                if overlap_start < overlap_end:
                    overlap_min = (overlap_end - overlap_start) // 60
                    sw_label = sw.get("label") or f"{sw_start // 3600}h{(sw_start % 3600) // 60:02d}-{sw_end // 3600}h{(sw_end % 3600) // 60:02d}"
                    warnings.append(
                        f"{driver_name} stint {s['stint_order']} overlaps sleep window "
                        f"'{sw_label}' by {overlap_min}min"
                    )

    # Check feasibility: total assigned drive time
    total_assigned = sum(s["planned_duration_s"] for s in stints)
    if total_assigned + total_pit_time < race_duration * 0.95:
        violations.append(
            f"Cannot fill race: {total_assigned}s drive + {total_pit_time}s pit = "
            f"{total_assigned + total_pit_time}s vs {race_duration}s race"
        )

    # Check cumulative minimums
    for driver in drivers:
        did = driver["id"]
        d_cum_min = driver.get("min_cumulative_s")
        actual = cumulative.get(did, 0)
        if d_cum_min and actual < d_cum_min:
            violations.append(
                f"{driver['driver_name']} cumulative {actual}s < minimum {d_cum_min}s"
            )

    # Build pit stops
    pit_stops = []
    for i in range(len(stints) - 1):
        pit_stops.append({
            "after_stint": i + 1,
            "at_s": stints[i]["planned_end_s"],
            "duration_s": pit_time,
            "driver_change": stints[i]["driver_id"] != stints[i + 1]["driver_id"],
            "refuel": True,
        })

    # Check pit window violations
    if pit_open:
        for p in pit_stops:
            if p["at_s"] < pit_open:
                warnings.append(f"Pit stop at {p['at_s']}s is before pit window opens at {pit_open}s")
    if pit_close:
        for p in pit_stops:
            if p["at_s"] > pit_close:
                warnings.append(f"Pit stop at {p['at_s']}s is after pit window closes at {pit_close}s")

    # Build driver summary
    driver_summary = {}
    for driver in drivers:
        did = driver["id"]
        d_stints = [s for s in stints if s["driver_id"] == did]
        driver_summary[driver["driver_name"]] = {
            "total_drive_s": cumulative.get(did, 0),
            "stints": len(d_stints),
        }

    return {
        "feasible": len(violations) == 0,
        "stints": stints,
        "pit_stops": pit_stops,
        "driver_summary": driver_summary,
        "violations": violations,
        "warnings": warnings,
        "total_pit_time_s": total_pit_time,
        "total_drive_time_s": total_assigned,
    }


def reoptimize_remaining(
    config: dict[str, Any],
    drivers: list[dict[str, Any]],
    completed_stints: list[dict[str, Any]],
    elapsed_s: int,
    sleep_windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-optimize remaining stints given completed work."""
    remaining_time = config["race_duration_s"] - elapsed_s

    # Compute remaining cumulative budgets
    cumulative_used = {}
    for s in completed_stints:
        did = s["driver_id"]
        cumulative_used[did] = cumulative_used.get(did, 0) + s.get("actual_duration_s", 0)

    adjusted_drivers = []
    for d in drivers:
        adj = dict(d)
        used = cumulative_used.get(d["id"], 0)
        if adj.get("max_cumulative_s"):
            adj["max_cumulative_s"] = max(0, adj["max_cumulative_s"] - used)
        if adj.get("min_cumulative_s"):
            adj["min_cumulative_s"] = max(0, adj["min_cumulative_s"] - used)
        adjusted_drivers.append(adj)

    remaining_stints = max(1, config.get("desired_stints", 4) - len(completed_stints))

    remaining_config = {
        **config,
        "race_duration_s": remaining_time,
        "desired_stints": remaining_stints,
    }

    result = optimize_stints(remaining_config, adjusted_drivers, sleep_windows=sleep_windows)

    # Offset times by elapsed
    for s in result["stints"]:
        s["planned_start_s"] += elapsed_s
        s["planned_end_s"] += elapsed_s
        s["stint_order"] += len(completed_stints)
    for p in result["pit_stops"]:
        p["at_s"] += elapsed_s
        p["after_stint"] += len(completed_stints)

    return result


def _stint_cap(driver: dict[str, Any], fuel_autonomy: int | None) -> int | None:
    """Return the effective maximum stint duration for a driver, or None if uncapped."""
    caps = []
    d_max = driver.get("max_stint_s")
    if d_max:
        caps.append(d_max)
    if fuel_autonomy:
        caps.append(fuel_autonomy)
    return min(caps) if caps else None


def _compute_stint_ballast(
    config: dict[str, Any],
    driver: dict[str, Any],
    is_first: bool,
) -> float:
    """Compute ballast for a stint based on config and driver weight."""
    min_kart = config.get("min_total_kart_kg")
    empty = config.get("empty_kart_kg")
    full_tank = config.get("full_tank_kg")
    driver_weight = driver.get("weight_kg")

    if not all([min_kart, empty, driver_weight]):
        return 0.0

    fuel_kg = (full_tank or 0) - (empty or 0) if full_tank else 0
    fuel_kg = max(0, fuel_kg)

    return compute_ballast(min_kart, empty, fuel_kg, driver_weight)


def adjust_stints_for_weather(
    remaining_stints: list[dict[str, Any]],
    forecast: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Annotate remaining stints with weather risk and adjusted lap time estimates.

    For each stint:
    - Estimate conditions at stint time from forecast
    - Flag 'wet_risk' if rain_prob > 50% or rain_mm > 0.5
    - Suggest compound via estimate_track_conditions()

    Does NOT modify strategy -- returns annotated copies.

    Parameters
    ----------
    remaining_stints : list[dict]
        Stints to annotate, each with planned_start_s / planned_end_s.
    forecast : dict
        Weather forecast from get_weather_forecast(). Must contain a
        ``"forecast"`` key with hourly entries, or an ``"error"`` key.
    config : dict
        Race configuration (unused currently, reserved for future
        pace-adjustment logic).

    Returns
    -------
    list[dict]
        Shallow copies of stints with weather annotations added.
    """
    # If forecast is broken or missing the hourly list, return plain copies.
    if "error" in forecast or "forecast" not in forecast:
        return [dict(s) for s in remaining_stints]

    hourly = forecast["forecast"]
    if not hourly:
        return [dict(s) for s in remaining_stints]

    # Lazy import to avoid circular imports at module level
    from meteo_service import estimate_track_conditions

    annotated: list[dict[str, Any]] = []
    for stint in remaining_stints:
        s = dict(stint)  # shallow copy — never mutate the original

        # Midpoint of the stint in seconds from race start
        mid_s = (s.get("planned_start_s", 0) + s.get("planned_end_s", 0)) / 2.0

        # Map midpoint to the closest forecast hour (index)
        hour_idx = int(round(mid_s / 3600.0))
        hour_idx = max(0, min(hour_idx, len(hourly) - 1))

        hour = hourly[hour_idx]
        rain_prob = hour.get("rain_prob_pct", 0) or 0
        rain_mm = hour.get("rain_mm", 0) or 0

        if rain_prob > 50 or rain_mm > 0.5:
            s["wet_risk"] = True

            # Build a pseudo-weather dict for estimate_track_conditions
            weather_for_hour = {
                "air_temp_c": hour.get("air_temp_c"),
                "humidity_pct": hour.get("humidity_pct"),
                "rain_mm": rain_mm,
                "wind_speed_mps": hour.get("wind_speed_mps"),
            }
            conditions = estimate_track_conditions(weather_for_hour)

            s["recommended_compound"] = conditions.get("recommended_compound")
            s["grip_score_forecast"] = conditions.get("grip_score")
        else:
            s["wet_risk"] = False

        annotated.append(s)

    return annotated
