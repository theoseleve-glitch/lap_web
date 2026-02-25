"""
weight_simulation.py
--------------------
Physics-based weight-to-pace simulation.

Models how changes in vehicle+driver weight affect lap time through:
- Acceleration phases: F=ma → heavier = slower exit speeds
- Braking phases: heavier = longer braking distances (energy = 0.5*m*v^2)
- Cornering phases: heavier = lower lateral-g threshold (tyre load sensitivity)

Public API
~~~~~~~~~~
``simulate_weight_change(baseline, weight_delta_kg)``
    Predict lap time change from adding/removing weight.
``compute_weight_sensitivity(sessions)``
    Compute seconds-per-kg from historical session data.
``estimate_ballast_effect(baseline_time_s, baseline_weight_kg, ...)``
    Quick estimate using the ~0.03-0.05 s/kg rule of thumb.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Physics constants ────────────────────────────────────────
_GRAVITY = 9.81  # m/s^2
_TYRE_LOAD_SENSITIVITY = 0.15  # grip drops ~15% per doubling of load (simplified)

# Empirical kart/car weight sensitivity ranges (seconds per kg per minute of lap time)
_WEIGHT_SENSITIVITY_RANGES = {
    "kart":        {"low": 0.020, "typical": 0.035, "high": 0.055},
    "formula":     {"low": 0.015, "typical": 0.025, "high": 0.040},
    "gt":          {"low": 0.008, "typical": 0.015, "high": 0.025},
    "touring":     {"low": 0.010, "typical": 0.018, "high": 0.030},
    "default":     {"low": 0.015, "typical": 0.030, "high": 0.050},
}


def simulate_weight_change(
    baseline: dict[str, Any],
    weight_delta_kg: float,
    vehicle_class: str = "default",
) -> dict[str, Any]:
    """
    Predict lap time change from weight modification.

    Parameters
    ----------
    baseline : dict
        Must have 'lap_time_s' and 'weight_kg'.
        Optionally: 'corners' (list of corner dicts with speeds),
        'speed_profile' (distances + speeds), 'power_kw'.
    weight_delta_kg : float
        Positive = heavier, negative = lighter.
    vehicle_class : str
        One of: kart, formula, gt, touring, default.

    Returns
    -------
    dict with:
        baseline_time_s, predicted_time_s, delta_s, delta_pct,
        weight_original_kg, weight_new_kg, sensitivity_s_per_kg,
        breakdown (accel, braking, cornering contributions),
        coaching (text advice).
    """
    lap_time = baseline.get("lap_time_s", 0)
    weight_kg = baseline.get("weight_kg", 0)
    power_kw = baseline.get("power_kw")

    if lap_time <= 0 or weight_kg <= 0:
        return {
            "error": "Need valid lap_time_s and weight_kg",
            "baseline_time_s": lap_time,
            "predicted_time_s": lap_time,
            "delta_s": 0,
            "delta_pct": 0,
        }

    new_weight = weight_kg + weight_delta_kg
    if new_weight <= 0:
        return {"error": "New weight must be positive"}

    weight_ratio = new_weight / weight_kg

    # ── Phase-specific effects ───────────────────────────────

    # 1. Acceleration effect: t_accel ~ m / F → proportional to mass
    #    If power is constant, acceleration a = P/(m*v), so time ∝ mass
    accel_fraction = 0.35  # typical fraction of lap in acceleration
    accel_delta_pct = (weight_ratio - 1.0) * accel_fraction

    # 2. Braking effect: braking distance ∝ mass (KE = 0.5*m*v^2, same decel force)
    #    Slight offset: heavier cars have more tyre grip (linear) but more energy (linear)
    #    Net effect: braking distance approximately ∝ mass^0.3 (tyre load sensitivity)
    brake_fraction = 0.15
    brake_delta_pct = (weight_ratio ** 0.3 - 1.0) * brake_fraction

    # 3. Cornering effect: lateral g = μ * g, but μ decreases with load
    #    Tyre load sensitivity: μ_new / μ_old ≈ (weight_ratio)^(-sensitivity)
    #    Cornering speed ∝ sqrt(μ * g * R), so v_corner ∝ (μ)^0.5
    #    Time through corner ∝ 1/v_corner
    corner_fraction = 0.50
    mu_ratio = weight_ratio ** (-_TYRE_LOAD_SENSITIVITY)
    v_ratio = mu_ratio ** 0.5
    corner_delta_pct = (1.0 / v_ratio - 1.0) * corner_fraction

    total_delta_pct = accel_delta_pct + brake_delta_pct + corner_delta_pct
    delta_s = lap_time * total_delta_pct
    predicted_time = lap_time + delta_s

    # Sensitivity (seconds per kg)
    sensitivity = delta_s / weight_delta_kg if weight_delta_kg != 0 else 0

    # Validate against empirical range
    vclass = vehicle_class.lower() if vehicle_class else "default"
    emp_range = _WEIGHT_SENSITIVITY_RANGES.get(vclass, _WEIGHT_SENSITIVITY_RANGES["default"])
    lap_time_minutes = lap_time / 60.0
    emp_low = emp_range["low"] * lap_time_minutes
    emp_high = emp_range["high"] * lap_time_minutes
    emp_typical = emp_range["typical"] * lap_time_minutes

    # Coaching text
    coaching_parts = []
    if weight_delta_kg > 0:
        coaching_parts.append(
            f"Adding {weight_delta_kg:.1f} kg increases lap time by ~{abs(delta_s):.3f}s."
        )
        if abs(sensitivity) > 0:
            coaching_parts.append(
                f"Sensitivity: {abs(sensitivity):.4f} s/kg "
                f"(empirical range for {vclass}: {emp_low:.3f}-{emp_high:.3f} s/kg at this lap length)."
            )
        coaching_parts.append(
            "Focus on braking zones — heavier car needs earlier, harder braking."
        )
    elif weight_delta_kg < 0:
        coaching_parts.append(
            f"Removing {abs(weight_delta_kg):.1f} kg improves lap time by ~{abs(delta_s):.3f}s."
        )
        coaching_parts.append(
            "Lighter car may feel looser under braking — adjust bias slightly rearward."
        )
    else:
        coaching_parts.append("No weight change applied.")

    return {
        "baseline_time_s": round(lap_time, 4),
        "predicted_time_s": round(predicted_time, 4),
        "delta_s": round(delta_s, 4),
        "delta_pct": round(total_delta_pct * 100, 3),
        "weight_original_kg": round(weight_kg, 1),
        "weight_new_kg": round(new_weight, 1),
        "weight_delta_kg": round(weight_delta_kg, 1),
        "sensitivity_s_per_kg": round(abs(sensitivity), 4) if sensitivity else 0,
        "empirical_range": {
            "low_s_per_kg": round(emp_low, 4),
            "typical_s_per_kg": round(emp_typical, 4),
            "high_s_per_kg": round(emp_high, 4),
            "vehicle_class": vclass,
        },
        "breakdown": {
            "acceleration_delta_s": round(lap_time * accel_delta_pct, 4),
            "braking_delta_s": round(lap_time * brake_delta_pct, 4),
            "cornering_delta_s": round(lap_time * corner_delta_pct, 4),
            "acceleration_pct": round(accel_fraction * 100, 1),
            "braking_pct": round(brake_fraction * 100, 1),
            "cornering_pct": round(corner_fraction * 100, 1),
        },
        "coaching": " ".join(coaching_parts),
    }


def compute_weight_sensitivity(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute empirical seconds-per-kg from historical session data
    where weight varied.

    Parameters
    ----------
    sessions : list[dict]
        Each: {weight_kg, best_lap_time_s, session_date?, driver_name?}

    Returns
    -------
    dict: sensitivity_s_per_kg, r_value, n_sessions, scatter_data, coaching.
    """
    # Filter valid pairs
    pairs = []
    for s in sessions:
        w = s.get("weight_kg")
        t = s.get("best_lap_time_s")
        if (w is not None and t is not None
                and math.isfinite(w) and math.isfinite(t)
                and w > 0 and t > 0):
            pairs.append({
                "weight_kg": w,
                "lap_time_s": t,
                "label": s.get("session_date", ""),
            })

    if len(pairs) < 3:
        return {
            "sensitivity_s_per_kg": None,
            "r_value": None,
            "n_sessions": len(pairs),
            "scatter_data": pairs,
            "coaching": "Need 3+ sessions with weight data for sensitivity analysis.",
        }

    ws = np.array([p["weight_kg"] for p in pairs])
    ts = np.array([p["lap_time_s"] for p in pairs])

    if np.std(ws) < 0.1:
        return {
            "sensitivity_s_per_kg": None,
            "r_value": None,
            "n_sessions": len(pairs),
            "scatter_data": pairs,
            "coaching": "Weight was constant across sessions — no sensitivity can be computed.",
        }

    # Linear regression: lap_time = slope * weight + intercept
    coeffs = np.polyfit(ws, ts, 1)
    slope = float(coeffs[0])  # seconds per kg
    r = float(np.corrcoef(ws, ts)[0, 1])

    # Interpretation
    abs_r = abs(r)
    if abs_r >= 0.7:
        strength = "strong"
    elif abs_r >= 0.4:
        strength = "moderate"
    elif abs_r >= 0.2:
        strength = "weak"
    else:
        strength = "negligible"

    coaching = (
        f"Weight sensitivity: {abs(slope):.4f} s/kg ({strength} correlation, r={r:.3f}). "
        f"Based on {len(pairs)} sessions with weight range {min(ws):.1f}-{max(ws):.1f} kg."
    )

    return {
        "sensitivity_s_per_kg": round(abs(slope), 4),
        "slope": round(slope, 6),
        "r_value": round(r, 4),
        "strength": strength,
        "n_sessions": len(pairs),
        "weight_range": {"min": round(float(min(ws)), 1), "max": round(float(max(ws)), 1)},
        "scatter_data": pairs,
        "coaching": coaching,
    }


def estimate_ballast_effect(
    baseline_time_s: float,
    baseline_weight_kg: float,
    ballast_kg: float,
    vehicle_class: str = "default",
) -> dict[str, Any]:
    """
    Quick ballast/weight penalty estimate using empirical rule of thumb.

    Parameters
    ----------
    baseline_time_s : float
        Current best lap time.
    baseline_weight_kg : float
        Current vehicle + driver weight.
    ballast_kg : float
        Weight to add (positive) or remove (negative).
    vehicle_class : str
        Vehicle category for sensitivity lookup.

    Returns
    -------
    dict: estimated delta and range.
    """
    if baseline_time_s <= 0 or baseline_weight_kg <= 0:
        return {"error": "Invalid baseline parameters"}

    vclass = vehicle_class.lower() if vehicle_class else "default"
    emp = _WEIGHT_SENSITIVITY_RANGES.get(vclass, _WEIGHT_SENSITIVITY_RANGES["default"])
    lap_minutes = baseline_time_s / 60.0

    delta_low = ballast_kg * emp["low"] * lap_minutes
    delta_typical = ballast_kg * emp["typical"] * lap_minutes
    delta_high = ballast_kg * emp["high"] * lap_minutes

    return {
        "ballast_kg": ballast_kg,
        "baseline_time_s": round(baseline_time_s, 3),
        "predicted_time_low_s": round(baseline_time_s + delta_low, 3),
        "predicted_time_typical_s": round(baseline_time_s + delta_typical, 3),
        "predicted_time_high_s": round(baseline_time_s + delta_high, 3),
        "delta_low_s": round(delta_low, 4),
        "delta_typical_s": round(delta_typical, 4),
        "delta_high_s": round(delta_high, 4),
        "vehicle_class": vclass,
        "sensitivity_range": emp,
    }


# ── Multi-scenario comparison ────────────────────────────────

def compare_weight_scenarios(
    baseline: dict[str, Any],
    scenarios: list[dict[str, Any]],
    vehicle_class: str = "default",
) -> dict[str, Any]:
    """
    Compare multiple weight change scenarios.

    Parameters
    ----------
    baseline : dict
        Must have 'lap_time_s' and 'weight_kg'.
    scenarios : list[dict]
        Each: {name, weight_delta_kg}.

    Returns
    -------
    dict with scenario results and ranking.
    """
    results = []
    for sc in scenarios:
        name = sc.get("name", f"+{sc.get('weight_delta_kg', 0):.0f}kg")
        delta = sc.get("weight_delta_kg", 0)
        sim = simulate_weight_change(baseline, delta, vehicle_class)
        sim["scenario_name"] = name
        results.append(sim)

    # Rank by predicted time (fastest first)
    results.sort(key=lambda r: r.get("predicted_time_s", 999))

    return {
        "baseline": {
            "lap_time_s": baseline.get("lap_time_s"),
            "weight_kg": baseline.get("weight_kg"),
        },
        "scenarios": results,
        "fastest_scenario": results[0]["scenario_name"] if results else None,
    }


# ── Inline tests ──────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite."""
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # Test 1: Adding weight should increase lap time
    def t_heavier_slower():
        baseline = {"lap_time_s": 60.0, "weight_kg": 150}
        result = simulate_weight_change(baseline, 10)
        assert result["predicted_time_s"] > result["baseline_time_s"]
        assert result["delta_s"] > 0
        assert result["weight_new_kg"] == 160.0

    _test("heavier_is_slower", t_heavier_slower)

    # Test 2: Removing weight should decrease lap time
    def t_lighter_faster():
        baseline = {"lap_time_s": 60.0, "weight_kg": 150}
        result = simulate_weight_change(baseline, -10)
        assert result["predicted_time_s"] < result["baseline_time_s"]
        assert result["delta_s"] < 0

    _test("lighter_is_faster", t_lighter_faster)

    # Test 3: Zero change = no delta
    def t_zero_change():
        baseline = {"lap_time_s": 60.0, "weight_kg": 150}
        result = simulate_weight_change(baseline, 0)
        assert abs(result["delta_s"]) < 0.001

    _test("zero_weight_change", t_zero_change)

    # Test 4: Sensitivity scales with lap time
    def t_longer_lap_more_effect():
        short = simulate_weight_change({"lap_time_s": 30.0, "weight_kg": 150}, 10)
        long_ = simulate_weight_change({"lap_time_s": 90.0, "weight_kg": 150}, 10)
        assert abs(long_["delta_s"]) > abs(short["delta_s"])

    _test("longer_lap_more_effect", t_longer_lap_more_effect)

    # Test 5: Breakdown components sum correctly
    def t_breakdown_sum():
        baseline = {"lap_time_s": 60.0, "weight_kg": 150}
        result = simulate_weight_change(baseline, 10)
        bd = result["breakdown"]
        component_sum = (
            bd["acceleration_delta_s"]
            + bd["braking_delta_s"]
            + bd["cornering_delta_s"]
        )
        assert abs(component_sum - result["delta_s"]) < 0.001

    _test("breakdown_sums_correctly", t_breakdown_sum)

    # Test 6: Invalid inputs
    def t_invalid():
        result = simulate_weight_change({"lap_time_s": 0, "weight_kg": 0}, 10)
        assert "error" in result

    _test("invalid_inputs", t_invalid)

    # Test 7: Empirical sensitivity
    def t_empirical():
        sessions = [
            {"weight_kg": 150 + i * 2, "best_lap_time_s": 60.0 + i * 0.08}
            for i in range(8)
        ]
        result = compute_weight_sensitivity(sessions)
        assert result["sensitivity_s_per_kg"] is not None
        assert result["r_value"] > 0.9

    _test("empirical_sensitivity", t_empirical)

    # Test 8: Too few sessions
    def t_few():
        result = compute_weight_sensitivity([
            {"weight_kg": 150, "best_lap_time_s": 60.0}
        ])
        assert result["sensitivity_s_per_kg"] is None

    _test("few_sessions", t_few)

    # Test 9: Ballast estimate
    def t_ballast():
        result = estimate_ballast_effect(60.0, 150, 5, "kart")
        assert result["delta_typical_s"] > 0
        assert result["delta_low_s"] < result["delta_high_s"]

    _test("ballast_estimate", t_ballast)

    # Test 10: Multi-scenario comparison
    def t_scenarios():
        baseline = {"lap_time_s": 60.0, "weight_kg": 150}
        scenarios = [
            {"name": "Min weight", "weight_delta_kg": -5},
            {"name": "Standard", "weight_delta_kg": 0},
            {"name": "+5kg ballast", "weight_delta_kg": 5},
            {"name": "+10kg ballast", "weight_delta_kg": 10},
        ]
        result = compare_weight_scenarios(baseline, scenarios)
        assert result["fastest_scenario"] == "Min weight"
        assert len(result["scenarios"]) == 4

    _test("scenario_comparison", t_scenarios)

    # Test 11: Vehicle class affects sensitivity
    def t_vehicle_class():
        baseline = {"lap_time_s": 60.0, "weight_kg": 150}
        kart = simulate_weight_change(baseline, 10, "kart")
        gt = simulate_weight_change(baseline, 10, "gt")
        # Kart is more sensitive to weight than GT (same physics model)
        # Both use same physics but empirical ranges differ
        assert kart["empirical_range"]["typical_s_per_kg"] > gt["empirical_range"]["typical_s_per_kg"]

    _test("vehicle_class_sensitivity", t_vehicle_class)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nWeight Simulation Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
