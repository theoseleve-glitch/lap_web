"""
line_optimization.py
--------------------
Identify racing line deviations from a reference (optimal) line
and score the risk/reward tradeoff of different lines.

Public API
~~~~~~~~~~
``identify_line_deviations(actual_line, reference_line)``
``score_risk_reward(deviations, corner_metrics)``
"""
from __future__ import annotations
import logging, math, traceback
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)

def identify_line_deviations(
    actual_line: dict[str, Any],
    reference_line: dict[str, Any],
) -> dict[str, Any]:
    """
    Measure lateral deviation between actual and reference racing lines.

    Parameters
    ----------
    actual_line : dict with 'latitudes', 'longitudes' (lists).
    reference_line : dict with 'latitudes', 'longitudes' (lists).

    Returns
    -------
    dict: deviations (list of floats in metres), mean_deviation_m, max_deviation_m,
          deviation_points (list of {distance_m, deviation_m}).
    """
    a_lats = actual_line.get("latitudes", [])
    a_lons = actual_line.get("longitudes", [])
    r_lats = reference_line.get("latitudes", [])
    r_lons = reference_line.get("longitudes", [])

    n_actual = min(len(a_lats), len(a_lons))
    n_ref = min(len(r_lats), len(r_lons))

    if n_actual < 2 or n_ref < 2:
        return {"deviations": [], "mean_deviation_m": 0.0, "max_deviation_m": 0.0, "deviation_points": []}

    # Resample to same length
    n = min(n_actual, n_ref)

    deviations = []
    for i in range(n):
        # Approximate distance in metres using Haversine
        dlat = a_lats[i] - r_lats[i]
        dlon = a_lons[i] - r_lons[i]
        # Rough conversion: 1 degree lat ~ 111320m, 1 degree lon ~ 111320 * cos(lat)
        lat_m = dlat * 111320
        cos_lat = math.cos(math.radians(a_lats[i])) if math.isfinite(a_lats[i]) else 1.0
        lon_m = dlon * 111320 * cos_lat
        dev = math.sqrt(lat_m**2 + lon_m**2)
        deviations.append(round(dev, 2))

    arr = np.array(deviations)

    return {
        "deviations": deviations,
        "mean_deviation_m": round(float(np.mean(arr)), 2),
        "max_deviation_m": round(float(np.max(arr)), 2),
        "n_points": n,
    }

def score_risk_reward(
    deviations: list[float],
    time_gains_ms: list[float],
) -> dict[str, Any]:
    """
    Score the risk/reward of line deviations.

    Parameters
    ----------
    deviations : list[float] -- deviation in metres per point.
    time_gains_ms : list[float] -- time gained (negative = lost) per point.

    Returns
    -------
    dict: risk_reward_score (0-100), classification.
    """
    if not deviations or not time_gains_ms:
        return {"risk_reward_score": 0.0, "classification": "unknown", "n_points": 0}

    n = min(len(deviations), len(time_gains_ms))
    devs = np.array(deviations[:n])
    gains = np.array(time_gains_ms[:n])

    # Points where deviation is large but time was gained = good risk
    # Points where deviation is large but time was lost = bad risk
    large_dev = devs > np.mean(devs) + np.std(devs)

    if large_dev.sum() == 0:
        return {"risk_reward_score": 50.0, "classification": "conservative", "n_points": n}

    risky_gains = gains[large_dev]
    pct_positive = float((risky_gains < 0).sum() / len(risky_gains)) * 100  # gains < 0 means faster

    score = min(100.0, max(0.0, pct_positive))

    if score > 70:
        cls = "rewarding"
    elif score > 40:
        cls = "balanced"
    else:
        cls = "risky"

    return {"risk_reward_score": round(score, 1), "classification": cls, "n_points": n}

# ── Inline tests ──────────────────────────────────────────────
def _run_tests() -> None:
    passed, failed = [], []
    def _test(name, fn):
        try: fn(); passed.append(name)
        except Exception: failed.append((name, traceback.format_exc()))

    def t_on_optimal():
        line = {"latitudes": [45.0, 45.001, 45.002], "longitudes": [7.0, 7.001, 7.002]}
        result = identify_line_deviations(line, line)
        assert result["mean_deviation_m"] < 0.1
    _test("on_optimal", t_on_optimal)

    def t_offline():
        actual = {"latitudes": [45.0, 45.001, 45.002], "longitudes": [7.0, 7.001, 7.002]}
        ref = {"latitudes": [45.0001, 45.0011, 45.0021], "longitudes": [7.0, 7.001, 7.002]}
        result = identify_line_deviations(actual, ref)
        assert result["mean_deviation_m"] > 5.0
    _test("offline", t_offline)

    def t_empty():
        result = identify_line_deviations({"latitudes": [], "longitudes": []}, {"latitudes": [], "longitudes": []})
        assert result["mean_deviation_m"] == 0.0
    _test("empty", t_empty)

    def t_risk_reward():
        devs = [0.1, 0.2, 5.0, 6.0, 0.3]
        gains = [0.0, 0.0, -50.0, -30.0, 0.0]  # large deviations gained time
        result = score_risk_reward(devs, gains)
        assert result["risk_reward_score"] > 50
    _test("risk_reward", t_risk_reward)

    def t_risk_empty():
        result = score_risk_reward([], [])
        assert result["n_points"] == 0
    _test("risk_empty", t_risk_empty)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nLine Optimization Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed: print(f"  OK {n}")
    for n, trace in failed: print(f"  FAIL {n}\n{trace}")
    if failed: raise AssertionError(f"{len(failed)} test(s) failed.")

if __name__ == "__main__": _run_tests()
