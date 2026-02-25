"""
weather_correlation.py
----------------------
Compute correlations between weather conditions and lap pace.

Uses Pearson correlation to quantify the relationship between
air temperature, track temperature, humidity, and lap times.
Produces scatter data for frontend charts.

Public API
~~~~~~~~~~
``compute_weather_pace_correlation(sessions_weather)``
    Accepts a list of dicts with weather + pace data.
    Returns correlation coefficients and scatter data.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_weather_pace_correlation(
    sessions_weather: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute correlation between weather variables and lap pace.

    Parameters
    ----------
    sessions_weather : list[dict]
        Each dict must have 'best_lap_time_s' and optionally:
        'air_temp_c', 'track_temp_c', 'humidity_pct',
        'wind_speed_mps', 'session_date'.

    Returns
    -------
    dict with keys:
        correlations: dict of variable -> {r, p_approx, n, interpretation}
        scatter_data: dict of variable -> list of {x, y, label} points
        summary: text summary of key findings
    """
    if not sessions_weather:
        return {
            "correlations": {},
            "scatter_data": {},
            "summary": "No weather data available.",
        }

    variables = [
        ("air_temp_c", "Air Temperature (°C)"),
        ("track_temp_c", "Track Temperature (°C)"),
        ("humidity_pct", "Humidity (%)"),
        ("wind_speed_mps", "Wind Speed (m/s)"),
    ]

    correlations = {}
    scatter_data = {}

    for var_key, var_label in variables:
        # Extract valid pairs
        pairs = []
        for sw in sessions_weather:
            x = sw.get(var_key)
            y = sw.get("best_lap_time_s")
            if (x is not None and y is not None
                    and math.isfinite(x) and math.isfinite(y)):
                pairs.append({
                    "x": x,
                    "y": y,
                    "label": sw.get("session_date", ""),
                })

        if len(pairs) < 5:
            correlations[var_key] = {
                "r": None,
                "n": len(pairs),
                "interpretation": "insufficient data (need 5+ sessions)",
                "label": var_label,
            }
            scatter_data[var_key] = pairs
            continue

        xs = np.array([p["x"] for p in pairs])
        ys = np.array([p["y"] for p in pairs])

        # Pearson correlation
        r = _pearson_r(xs, ys)

        # Simple interpretation
        abs_r = abs(r) if r is not None else 0
        if abs_r >= 0.7:
            interp = "strong"
        elif abs_r >= 0.4:
            interp = "moderate"
        elif abs_r >= 0.2:
            interp = "weak"
        else:
            interp = "negligible"

        direction = ""
        if r is not None:
            if r > 0:
                direction = " positive (higher {} → slower pace)".format(var_key.replace("_", " "))
            else:
                direction = " negative (higher {} → faster pace)".format(var_key.replace("_", " "))

        correlations[var_key] = {
            "r": round(r, 4) if r is not None else None,
            "n": len(pairs),
            "interpretation": interp + direction,
            "label": var_label,
        }
        scatter_data[var_key] = pairs

    # Summary
    findings = []
    for var_key, info in correlations.items():
        if info.get("r") is not None and abs(info["r"]) >= 0.3:
            findings.append(
                f"{info['label']}: r={info['r']:.3f} ({info['interpretation']})"
            )

    summary = (
        "Key findings: " + "; ".join(findings)
        if findings
        else "No significant weather-pace correlations found."
    )

    return {
        "correlations": correlations,
        "scatter_data": scatter_data,
        "summary": summary,
    }


def _pearson_r(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Compute Pearson correlation coefficient. Returns None if undefined."""
    if len(x) < 2:
        return None
    sx = np.std(x, ddof=1)
    sy = np.std(y, ddof=1)
    if sx < 1e-12 or sy < 1e-12:
        return None
    r = float(np.corrcoef(x, y)[0, 1])
    if not math.isfinite(r):
        return None
    return r


def compute_optimal_conditions(
    sessions_weather: list[dict[str, Any]],
    top_pct: float = 20.0,
) -> dict[str, Any]:
    """
    Find the weather conditions associated with the fastest laps.

    Parameters
    ----------
    sessions_weather : list[dict]
        Same format as compute_weather_pace_correlation.
    top_pct : float
        Percentage of fastest sessions to consider (default 20%).

    Returns
    -------
    dict with optimal condition ranges for each variable.
    """
    valid = [
        sw for sw in sessions_weather
        if sw.get("best_lap_time_s") is not None
        and math.isfinite(sw["best_lap_time_s"])
    ]
    if len(valid) < 3:
        return {"note": "insufficient data"}

    # Sort by pace, take top N%
    valid.sort(key=lambda s: s["best_lap_time_s"])
    n_top = max(1, int(len(valid) * top_pct / 100))
    top = valid[:n_top]

    result = {}
    for var_key in ("air_temp_c", "track_temp_c", "humidity_pct", "wind_speed_mps"):
        vals = [s[var_key] for s in top if s.get(var_key) is not None and math.isfinite(s[var_key])]
        if vals:
            arr = np.array(vals)
            result[var_key] = {
                "optimal_min": round(float(np.min(arr)), 1),
                "optimal_max": round(float(np.max(arr)), 1),
                "optimal_mean": round(float(np.mean(arr)), 1),
                "n_sessions": len(vals),
            }

    return result


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

    # Test 1: known linear relationship (temp → pace)
    def t_linear():
        data = []
        np.random.seed(42)
        for i in range(20):
            temp = 15.0 + i * 1.0
            pace = 60.0 + i * 0.3 + np.random.normal(0, 0.1)
            data.append({
                "air_temp_c": temp, "track_temp_c": temp + 10,
                "humidity_pct": 50.0, "wind_speed_mps": 2.0,
                "best_lap_time_s": pace, "session_date": f"2024-01-{i+1:02d}",
            })
        result = compute_weather_pace_correlation(data)
        r_air = result["correlations"]["air_temp_c"]["r"]
        assert r_air is not None
        assert r_air > 0.9, f"Expected strong positive r, got {r_air}"
        assert "strong" in result["correlations"]["air_temp_c"]["interpretation"]

    _test("linear_relationship", t_linear)

    # Test 2: no correlation
    def t_no_corr():
        data = []
        np.random.seed(99)
        for i in range(15):
            data.append({
                "air_temp_c": float(np.random.uniform(10, 35)),
                "best_lap_time_s": float(np.random.uniform(58, 62)),
                "session_date": f"2024-02-{i+1:02d}",
            })
        result = compute_weather_pace_correlation(data)
        r = result["correlations"]["air_temp_c"]["r"]
        assert r is not None
        assert abs(r) < 0.5, f"Expected weak correlation, got {r}"

    _test("no_correlation", t_no_corr)

    # Test 3: empty input
    def t_empty():
        result = compute_weather_pace_correlation([])
        assert result["correlations"] == {}
        assert "No weather data" in result["summary"]

    _test("empty_input", t_empty)

    # Test 4: too few points
    def t_few():
        data = [
            {"air_temp_c": 20.0, "best_lap_time_s": 60.0},
            {"air_temp_c": 25.0, "best_lap_time_s": 61.0},
        ]
        result = compute_weather_pace_correlation(data)
        assert result["correlations"]["air_temp_c"]["r"] is None
        assert "insufficient" in result["correlations"]["air_temp_c"]["interpretation"]

    _test("few_points", t_few)

    # Test 5: NaN values filtered
    def t_nan():
        data = [
            {"air_temp_c": 20.0, "best_lap_time_s": 60.0},
            {"air_temp_c": float("nan"), "best_lap_time_s": 61.0},
            {"air_temp_c": 25.0, "best_lap_time_s": float("nan")},
            {"air_temp_c": 22.0, "best_lap_time_s": 60.5},
            {"air_temp_c": 28.0, "best_lap_time_s": 62.0},
        ]
        result = compute_weather_pace_correlation(data)
        assert result["correlations"]["air_temp_c"]["n"] == 3

    _test("nan_filtered", t_nan)

    # Test 6: optimal conditions
    def t_optimal():
        data = []
        for i in range(10):
            data.append({
                "air_temp_c": 15.0 + i * 2.0,
                "best_lap_time_s": 60.0 + i * 0.5,
            })
        result = compute_optimal_conditions(data)
        # Top 20% = 2 sessions = lowest temps
        assert "air_temp_c" in result
        assert result["air_temp_c"]["optimal_mean"] < 20.0

    _test("optimal_conditions", t_optimal)

    # Test 7: scatter data contains labels
    def t_scatter():
        data = [
            {"air_temp_c": 20.0, "best_lap_time_s": 60.0, "session_date": "2024-01-01"},
            {"air_temp_c": 25.0, "best_lap_time_s": 61.0, "session_date": "2024-01-02"},
            {"air_temp_c": 30.0, "best_lap_time_s": 62.0, "session_date": "2024-01-03"},
        ]
        result = compute_weather_pace_correlation(data)
        sd = result["scatter_data"]["air_temp_c"]
        assert len(sd) == 3
        assert sd[0]["label"] == "2024-01-01"

    _test("scatter_data", t_scatter)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nWeather Correlation Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
