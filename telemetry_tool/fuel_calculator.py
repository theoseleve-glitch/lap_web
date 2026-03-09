"""
fuel_calculator.py
------------------
Model fuel load effect on pace and predict optimal pit strategy.

Public API
~~~~~~~~~~
``model_fuel_effect(sessions)`` -- Estimate seconds/kg of fuel.
``predict_pit_strategy(race_laps, fuel_effect, tank_capacity)``
"""
from __future__ import annotations

import logging
import math
import traceback
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

def model_fuel_effect(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Estimate pace effect of fuel load.

    Parameters
    ----------
    sessions : list[dict]
        Each: fuel_load_kg, best_lap_time_s.

    Returns
    -------
    dict: seconds_per_kg, correlation, scatter data.
    """
    valid = [(s["fuel_load_kg"], s["best_lap_time_s"]) for s in sessions
             if s.get("fuel_load_kg") is not None and s.get("best_lap_time_s") is not None
             and math.isfinite(s["fuel_load_kg"]) and math.isfinite(s["best_lap_time_s"])
             and s["fuel_load_kg"] > 0]

    if len(valid) < 3:
        return {"seconds_per_kg": 0.0, "r": None, "n": len(valid), "scatter": []}

    xs = np.array([v[0] for v in valid])
    ys = np.array([v[1] for v in valid])

    coeffs = np.polyfit(xs, ys, 1)
    r = float(np.corrcoef(xs, ys)[0, 1]) if np.std(xs) > 1e-10 and np.std(ys) > 1e-10 else 0

    return {
        "seconds_per_kg": round(float(coeffs[0]), 4),
        "r": round(r, 4) if math.isfinite(r) else None,
        "n": len(valid),
        "scatter": [{"fuel_kg": v[0], "time_s": v[1]} for v in valid],
    }

def predict_pit_strategy(
    total_laps: int,
    fuel_effect_s_per_kg: float,
    tank_capacity_kg: float,
    consumption_per_lap_kg: float,
    pit_stop_time_s: float = 25.0,
    base_lap_time_s: float = 60.0,
) -> dict[str, Any]:
    """
    Predict optimal pit stop strategy.

    Returns
    -------
    dict: strategies (list of pit options), optimal strategy.
    """
    if total_laps <= 0 or consumption_per_lap_kg <= 0:
        return {"strategies": [], "optimal": None}

    max_laps_per_stint = int(tank_capacity_kg / consumption_per_lap_kg)
    strategies = []

    for n_stops in range(0, min(5, total_laps)):
        stints = n_stops + 1
        laps_per_stint = total_laps / stints

        if laps_per_stint > max_laps_per_stint:
            continue

        # Fuel load at start of each stint
        fuel_start = laps_per_stint * consumption_per_lap_kg
        if fuel_start > tank_capacity_kg:
            fuel_start = tank_capacity_kg

        # Average fuel effect across stint
        avg_fuel = fuel_start / 2.0
        avg_fuel_penalty = avg_fuel * fuel_effect_s_per_kg

        total_time = (
            total_laps * (base_lap_time_s + avg_fuel_penalty)
            + n_stops * pit_stop_time_s
        )

        strategies.append({
            "n_stops": n_stops,
            "laps_per_stint": round(laps_per_stint, 1),
            "fuel_per_stint_kg": round(fuel_start, 1),
            "total_time_s": round(total_time, 2),
            "pit_time_total_s": round(n_stops * pit_stop_time_s, 1),
        })

    optimal = min(strategies, key=lambda s: s["total_time_s"]) if strategies else None

    return {"strategies": strategies, "optimal": optimal}

# ── Inline tests ──────────────────────────────────────────────
def _run_tests() -> None:
    passed, failed = [], []
    def _test(name, fn):
        try: fn(); passed.append(name)
        except Exception: failed.append((name, traceback.format_exc()))

    def t_fuel_effect():
        sessions = [{"fuel_load_kg": 5.0 + i, "best_lap_time_s": 60.0 + i*0.05} for i in range(10)]
        result = model_fuel_effect(sessions)
        assert result["seconds_per_kg"] > 0
        assert result["n"] == 10
    _test("fuel_effect", t_fuel_effect)

    def t_fuel_empty():
        result = model_fuel_effect([])
        assert result["n"] == 0
    _test("fuel_empty", t_fuel_empty)

    def t_pit_strategy():
        result = predict_pit_strategy(20, 0.05, 10.0, 0.5, 25.0, 60.0)
        assert len(result["strategies"]) > 0
        assert result["optimal"] is not None
    _test("pit_strategy", t_pit_strategy)

    def t_pit_zero_laps():
        result = predict_pit_strategy(0, 0.05, 10.0, 0.5)
        assert result["strategies"] == []
    _test("pit_zero_laps", t_pit_zero_laps)

    def t_pit_no_stops_possible():
        result = predict_pit_strategy(5, 0.05, 10.0, 1.0, 25.0, 60.0)
        assert any(s["n_stops"] == 0 for s in result["strategies"])
    _test("no_stops_possible", t_pit_no_stops_possible)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nFuel Calculator Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed: print(f"  OK {n}")
    for n, trace in failed: print(f"  FAIL {n}\n{trace}")
    if failed: raise AssertionError(f"{len(failed)} test(s) failed.")

if __name__ == "__main__": _run_tests()
