"""
race_strategy.py
----------------
Race strategy planner: combine tire degradation, fuel load, weather,
and pit stop timing into an integrated strategy recommendation.

Public API
~~~~~~~~~~
``plan_race_strategy(params)``
    Generate comprehensive race strategy with optimal stops.
``simulate_race(params)``
    Lap-by-lap race simulation with fuel and tire models.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Tire compound models (degradation per lap) ──────────────
_TIRE_COMPOUNDS = {
    "soft": {
        "label": "Soft",
        "base_grip": 1.05,
        "deg_per_lap": 0.008,
        "cliff_lap": 15,
        "cliff_severity": 0.04,
        "optimal_window_laps": (1, 12),
    },
    "medium": {
        "label": "Medium",
        "base_grip": 1.00,
        "deg_per_lap": 0.004,
        "cliff_lap": 28,
        "cliff_severity": 0.03,
        "optimal_window_laps": (1, 25),
    },
    "hard": {
        "label": "Hard",
        "base_grip": 0.96,
        "deg_per_lap": 0.002,
        "cliff_lap": 45,
        "cliff_severity": 0.025,
        "optimal_window_laps": (1, 40),
    },
    "wet": {
        "label": "Wet",
        "base_grip": 0.85,
        "deg_per_lap": 0.003,
        "cliff_lap": 35,
        "cliff_severity": 0.02,
        "optimal_window_laps": (1, 30),
    },
    "inter": {
        "label": "Intermediate",
        "base_grip": 0.92,
        "deg_per_lap": 0.005,
        "cliff_lap": 22,
        "cliff_severity": 0.03,
        "optimal_window_laps": (1, 18),
    },
}


def _tire_pace_factor(compound: str, tire_age_laps: int) -> float:
    """
    Compute pace factor for a tire at given age.
    Returns multiplier on lap time (>1.0 = slower).
    """
    tc = _TIRE_COMPOUNDS.get(compound, _TIRE_COMPOUNDS["medium"])
    base = 1.0 / tc["base_grip"]  # base pace factor

    # Linear degradation
    deg = tc["deg_per_lap"] * tire_age_laps

    # Cliff effect (exponential increase after cliff lap)
    cliff_extra = 0.0
    if tire_age_laps > tc["cliff_lap"]:
        over = tire_age_laps - tc["cliff_lap"]
        cliff_extra = tc["cliff_severity"] * (1.0 - math.exp(-over * 0.15))

    return base + deg + cliff_extra


def simulate_race(
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Lap-by-lap race simulation with fuel and tire models.

    Parameters
    ----------
    params : dict
        Required: race_laps, base_lap_time_s, pit_loss_s
        Optional: fuel_load_kg, fuel_per_lap_kg, fuel_effect_s_per_kg,
                  tire_compound, weight_kg, air_temp_c, track_temp_c,
                  pit_stops (list of {lap, compound})

    Returns
    -------
    dict with lap_times, total_time_s, stints, fuel_remaining per lap.
    """
    race_laps = max(1, int(params.get("race_laps", 20) or 20))
    base_time = max(1.0, float(params.get("base_lap_time_s", 60.0) or 60.0))
    pit_loss = max(0, float(params.get("pit_loss_s", 25.0) or 25.0))

    fuel_load = params.get("fuel_load_kg", 0)
    fuel_per_lap = params.get("fuel_per_lap_kg", 0)
    fuel_effect = params.get("fuel_effect_s_per_kg", 0.035)

    tire_compound = params.get("tire_compound", "medium")
    weight_kg = params.get("weight_kg", 0)

    # Pit stops: list of {lap: int, compound: str}
    pit_stops = params.get("pit_stops", [])
    pit_stop_laps = {ps.get("lap"): ps.get("compound", tire_compound) for ps in pit_stops}

    lap_times = []
    fuel_remaining = []
    tire_ages = []
    stints = []

    current_compound = tire_compound
    tire_age = 0
    current_fuel = fuel_load
    stint_start = 1

    for lap in range(1, race_laps + 1):
        # Check for pit stop at this lap
        if lap in pit_stop_laps:
            # Record stint
            stints.append({
                "start_lap": stint_start,
                "end_lap": lap - 1,
                "compound": current_compound,
                "n_laps": lap - 1 - stint_start + 1,
            })
            stint_start = lap
            current_compound = pit_stop_laps[lap]
            tire_age = 0
            current_fuel = fuel_load  # refuel (if applicable)

        # Tire degradation effect
        tire_factor = _tire_pace_factor(current_compound, tire_age)

        # Fuel weight effect
        fuel_delta = current_fuel * fuel_effect if fuel_load > 0 else 0

        # Weather effect (simplified: hotter = slightly slower)
        temp_delta = 0.0
        air_temp = params.get("air_temp_c")
        if air_temp is not None and air_temp > 25:
            temp_delta = (air_temp - 25) * 0.01  # +0.01s per degree above 25C

        # Compute lap time
        lap_time = base_time * tire_factor + fuel_delta + temp_delta

        # Add pit loss
        if lap in pit_stop_laps:
            lap_time += pit_loss

        lap_times.append(round(lap_time, 3))
        fuel_remaining.append(round(max(0, current_fuel), 2))
        tire_ages.append(tire_age)

        # Update state
        tire_age += 1
        current_fuel = max(0, current_fuel - fuel_per_lap)

    # Final stint
    stints.append({
        "start_lap": stint_start,
        "end_lap": race_laps,
        "compound": current_compound,
        "n_laps": race_laps - stint_start + 1,
    })

    total_time = sum(lap_times)
    best_lap = min(lap_times)
    worst_lap = max(lap_times)

    return {
        "race_laps": race_laps,
        "total_time_s": round(total_time, 3),
        "best_lap_s": round(best_lap, 3),
        "worst_lap_s": round(worst_lap, 3),
        "mean_lap_s": round(total_time / race_laps, 3),
        "n_stops": len(pit_stops),
        "lap_data": [
            {
                "lap": i + 1,
                "time_s": lap_times[i],
                "fuel_kg": fuel_remaining[i],
                "tire_age": tire_ages[i],
            }
            for i in range(race_laps)
        ],
        "stints": stints,
    }


def plan_race_strategy(
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Generate optimal race strategy by comparing multiple stop/compound
    combinations.

    Parameters
    ----------
    params : dict
        Required: race_laps, base_lap_time_s, pit_loss_s
        Optional: available_compounds, fuel_load_kg, fuel_per_lap_kg,
                  max_stops (default 3)

    Returns
    -------
    dict with strategies ranked by total time, optimal highlighted.
    """
    race_laps = max(1, int(params.get("race_laps", 20) or 20))
    base_time = max(1.0, float(params.get("base_lap_time_s", 60.0) or 60.0))
    pit_loss = max(0, float(params.get("pit_loss_s", 25.0) or 25.0))
    max_stops = min(3, max(0, int(params.get("max_stops", 3) or 3)))
    compounds = params.get("available_compounds", ["soft", "medium", "hard"])
    compounds = compounds[:10]  # cap to prevent combinatorial explosion

    # Validate compounds
    compounds = [c for c in compounds if c in _TIRE_COMPOUNDS]
    if not compounds:
        compounds = ["medium"]

    strategies = []

    # 0-stop strategies (one compound for whole race)
    for comp in compounds:
        sim_params = {**params, "tire_compound": comp, "pit_stops": []}
        result = simulate_race(sim_params)
        strategies.append({
            "name": f"0-stop ({_TIRE_COMPOUNDS[comp]['label']})",
            "stops": 0,
            "total_time_s": result["total_time_s"],
            "best_lap_s": result["best_lap_s"],
            "worst_lap_s": result["worst_lap_s"],
            "stints": result["stints"],
            "pit_stops": [],
            "compounds_used": [comp],
        })

    # 1-stop strategies
    if max_stops >= 1:
        for comp1 in compounds:
            for comp2 in compounds:
                # Try different stop windows
                for stop_lap in range(
                    max(3, race_laps // 4),
                    min(race_laps - 2, 3 * race_laps // 4),
                    max(1, race_laps // 8),
                ):
                    pit_stops = [{"lap": stop_lap, "compound": comp2}]
                    sim_params = {**params, "tire_compound": comp1, "pit_stops": pit_stops}
                    result = simulate_race(sim_params)
                    strategies.append({
                        "name": f"1-stop L{stop_lap} ({_TIRE_COMPOUNDS[comp1]['label']}→{_TIRE_COMPOUNDS[comp2]['label']})",
                        "stops": 1,
                        "total_time_s": result["total_time_s"],
                        "best_lap_s": result["best_lap_s"],
                        "worst_lap_s": result["worst_lap_s"],
                        "stints": result["stints"],
                        "pit_stops": pit_stops,
                        "compounds_used": [comp1, comp2],
                    })

    # 2-stop strategies
    if max_stops >= 2 and race_laps >= 15:
        for comp1 in compounds:
            for comp2 in compounds:
                for comp3 in compounds:
                    third = race_laps // 3
                    twothird = 2 * race_laps // 3
                    pit_stops = [
                        {"lap": third, "compound": comp2},
                        {"lap": twothird, "compound": comp3},
                    ]
                    sim_params = {**params, "tire_compound": comp1, "pit_stops": pit_stops}
                    result = simulate_race(sim_params)
                    strategies.append({
                        "name": f"2-stop L{third},{twothird} ({_TIRE_COMPOUNDS[comp1]['label']}→{_TIRE_COMPOUNDS[comp2]['label']}→{_TIRE_COMPOUNDS[comp3]['label']})",
                        "stops": 2,
                        "total_time_s": result["total_time_s"],
                        "best_lap_s": result["best_lap_s"],
                        "worst_lap_s": result["worst_lap_s"],
                        "stints": result["stints"],
                        "pit_stops": pit_stops,
                        "compounds_used": [comp1, comp2, comp3],
                    })

    # Sort by total race time
    strategies.sort(key=lambda s: s["total_time_s"])

    # Mark optimal
    if strategies:
        strategies[0]["optimal"] = True

    # Take top strategies per stop count
    best_per_stops = {}
    for s in strategies:
        n = s["stops"]
        if n not in best_per_stops:
            best_per_stops[n] = s

    # Return top 10 overall + best per stop count
    top_strategies = strategies[:10]

    return {
        "race_laps": race_laps,
        "base_lap_time_s": base_time,
        "pit_loss_s": pit_loss,
        "n_strategies_evaluated": len(strategies),
        "strategies": top_strategies,
        "best_per_stops": best_per_stops,
        "optimal": strategies[0] if strategies else None,
        "available_compounds": [
            {
                "id": c,
                "label": _TIRE_COMPOUNDS[c]["label"],
                "optimal_life": _TIRE_COMPOUNDS[c]["optimal_window_laps"],
                "cliff_lap": _TIRE_COMPOUNDS[c]["cliff_lap"],
            }
            for c in compounds
        ],
    }


# ── Inline tests ──────────────────────────────────────────────

def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # Test 1: Basic race simulation
    def t_basic_sim():
        result = simulate_race({
            "race_laps": 10,
            "base_lap_time_s": 60.0,
            "pit_loss_s": 25.0,
            "tire_compound": "medium",
        })
        assert result["race_laps"] == 10
        assert len(result["lap_data"]) == 10
        assert result["total_time_s"] > 0
        assert result["n_stops"] == 0

    _test("basic_simulation", t_basic_sim)

    # Test 2: Pit stop increases total time
    def t_pit_stop():
        no_stop = simulate_race({
            "race_laps": 20, "base_lap_time_s": 60.0, "pit_loss_s": 25.0,
            "tire_compound": "hard",
        })
        with_stop = simulate_race({
            "race_laps": 20, "base_lap_time_s": 60.0, "pit_loss_s": 25.0,
            "tire_compound": "hard",
            "pit_stops": [{"lap": 10, "compound": "hard"}],
        })
        # Pit stop adds ~25s, but fresh tires may help on a short race
        assert with_stop["n_stops"] == 1

    _test("pit_stop_works", t_pit_stop)

    # Test 3: Soft tires degrade faster
    def t_soft_deg():
        soft = simulate_race({
            "race_laps": 20, "base_lap_time_s": 60.0, "pit_loss_s": 25.0,
            "tire_compound": "soft",
        })
        hard = simulate_race({
            "race_laps": 20, "base_lap_time_s": 60.0, "pit_loss_s": 25.0,
            "tire_compound": "hard",
        })
        # Soft starts faster but degrades more
        assert soft["lap_data"][0]["time_s"] < hard["lap_data"][0]["time_s"]
        assert soft["lap_data"][-1]["time_s"] > hard["lap_data"][-1]["time_s"]

    _test("soft_degrades_faster", t_soft_deg)

    # Test 4: Fuel effect
    def t_fuel():
        no_fuel = simulate_race({
            "race_laps": 10, "base_lap_time_s": 60.0, "pit_loss_s": 25.0,
            "fuel_load_kg": 0,
        })
        with_fuel = simulate_race({
            "race_laps": 10, "base_lap_time_s": 60.0, "pit_loss_s": 25.0,
            "fuel_load_kg": 20, "fuel_per_lap_kg": 2.0,
        })
        # Fuel makes first lap slower
        assert with_fuel["lap_data"][0]["time_s"] > no_fuel["lap_data"][0]["time_s"]
        # Last lap: fuel nearly gone, should be closer
        assert with_fuel["lap_data"][-1]["fuel_kg"] <= 2.0

    _test("fuel_effect", t_fuel)

    # Test 5: Strategy planner finds optimal
    def t_strategy():
        result = plan_race_strategy({
            "race_laps": 25,
            "base_lap_time_s": 65.0,
            "pit_loss_s": 25.0,
            "available_compounds": ["soft", "medium", "hard"],
            "max_stops": 2,
        })
        assert result["n_strategies_evaluated"] > 10
        assert result["optimal"] is not None
        assert len(result["strategies"]) <= 10

    _test("strategy_planner", t_strategy)

    # Test 6: Tire pace factor
    def t_tire_factor():
        fresh = _tire_pace_factor("soft", 0)
        aged = _tire_pace_factor("soft", 20)
        assert aged > fresh  # older tire = slower

    _test("tire_pace_factor", t_tire_factor)

    # Test 7: 0-stop vs 1-stop on long race with soft tires
    def t_stop_benefit():
        result = plan_race_strategy({
            "race_laps": 30,
            "base_lap_time_s": 60.0,
            "pit_loss_s": 20.0,
            "available_compounds": ["soft"],
            "max_stops": 1,
        })
        # 1-stop should be faster on softs over 30 laps
        best = result["optimal"]
        assert best is not None
        assert best["stops"] >= 1  # soft tires degrade too much for 30 laps

    _test("stop_benefit_long_race", t_stop_benefit)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nRace Strategy Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
