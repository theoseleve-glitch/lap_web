"""
setup_tracker.py
----------------
Correlate vehicle setup parameters (tire pressure, camber, etc.)
with pace to identify which setup changes improve performance.

Public API
~~~~~~~~~~
``correlate_setup_vs_pace(setups)``
"""
from __future__ import annotations
import logging, math, traceback
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)

def correlate_setup_vs_pace(
    setups: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute correlation between setup parameters and lap pace.

    Parameters
    ----------
    setups : list[dict]
        Each: setup param values + best_lap_time_s.

    Returns
    -------
    dict: per_param correlations, scatter data, recommendations.
    """
    params = ["front_pressure", "rear_pressure", "front_camber", "rear_camber", "ride_height_mm", "weight_kg", "fuel_load_kg"]

    if len(setups) < 3:
        return {"correlations": {}, "recommendations": [], "n_sessions": len(setups)}

    correlations = {}
    for param in params:
        pairs = [(s[param], s["best_lap_time_s"]) for s in setups
                 if s.get(param) is not None and s.get("best_lap_time_s") is not None
                 and math.isfinite(s[param]) and math.isfinite(s["best_lap_time_s"])]

        if len(pairs) < 3:
            continue

        xs = np.array([p[0] for p in pairs])
        ys = np.array([p[1] for p in pairs])

        if np.std(xs) < 1e-10 or np.std(ys) < 1e-10:
            continue

        r = float(np.corrcoef(xs, ys)[0, 1])
        if not math.isfinite(r):
            continue

        # Linear fit
        coeffs = np.polyfit(xs, ys, 1)
        slope = float(coeffs[0])

        correlations[param] = {
            "r": round(r, 4),
            "slope": round(slope, 6),
            "n": len(pairs),
            "direction": "slower" if slope > 0 else "faster",
            "impact": round(abs(slope), 4),
        }

    # Recommendations (params with strong correlation)
    recs = []
    for param, info in correlations.items():
        if abs(info["r"]) >= 0.5:
            direction = "increase" if info["slope"] < 0 else "decrease"
            recs.append(f"Consider {direction} {param.replace('_', ' ')} (r={info['r']:.2f})")

    return {"correlations": correlations, "recommendations": recs, "n_sessions": len(setups)}

# ── Inline tests ──────────────────────────────────────────────
def _run_tests() -> None:
    passed, failed = [], []
    def _test(name, fn):
        try: fn(); passed.append(name)
        except Exception: failed.append((name, traceback.format_exc()))

    def t_linear():
        setups = [{"front_pressure": 1.0 + i*0.1, "best_lap_time_s": 60.0 + i*0.2} for i in range(10)]
        result = correlate_setup_vs_pace(setups)
        assert "front_pressure" in result["correlations"]
        assert result["correlations"]["front_pressure"]["r"] > 0.9
    _test("linear_correlation", t_linear)

    def t_no_correlation():
        np.random.seed(42)
        setups = [{"front_pressure": float(np.random.uniform(1.0, 2.0)), "best_lap_time_s": float(np.random.uniform(59, 62))} for _ in range(15)]
        result = correlate_setup_vs_pace(setups)
        if "front_pressure" in result["correlations"]:
            assert abs(result["correlations"]["front_pressure"]["r"]) < 0.7
    _test("no_correlation", t_no_correlation)

    def t_few():
        setups = [{"front_pressure": 1.5, "best_lap_time_s": 60.0}]
        result = correlate_setup_vs_pace(setups)
        assert result["correlations"] == {}
    _test("few_sessions", t_few)

    def t_empty():
        result = correlate_setup_vs_pace([])
        assert result["n_sessions"] == 0
    _test("empty", t_empty)

    def t_recommendations():
        setups = [{"front_pressure": 1.0 + i*0.1, "best_lap_time_s": 62.0 - i*0.3} for i in range(8)]
        result = correlate_setup_vs_pace(setups)
        assert len(result["recommendations"]) > 0
    _test("recommendations", t_recommendations)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nSetup Tracker Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed: print(f"  OK {n}")
    for n, trace in failed: print(f"  FAIL {n}\n{trace}")
    if failed: raise AssertionError(f"{len(failed)} test(s) failed.")

if __name__ == "__main__": _run_tests()
