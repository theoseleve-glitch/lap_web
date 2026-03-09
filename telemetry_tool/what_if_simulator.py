"""
what_if_simulator.py
--------------------
What-if simulator: apply hypothetical speed adjustments per corner
to a lap speed profile and recompute the predicted lap time.

Public API
~~~~~~~~~~
``simulate_what_if(speed_profile, adjustments)``
    Apply corner speed adjustments and return predicted lap time.
"""
from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

def simulate_what_if(
    speed_profile: dict[str, Any],
    adjustments: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Apply what-if corner speed adjustments to a speed profile.

    Parameters
    ----------
    speed_profile : dict
        Must have 'distances' (list[float]) and 'speeds' (list[float]).
        Optionally 'corners' with corner boundaries.
    adjustments : list[dict]
        Each: {corner_id, speed_pct_change} e.g. +5 means +5% speed.

    Returns
    -------
    dict: baseline_time_s, predicted_time_s, delta_s, delta_pct,
          per_corner_deltas (list)
    """
    dists = speed_profile.get("distances", [])
    speeds = speed_profile.get("speeds", [])
    corners = speed_profile.get("corners", [])

    if len(dists) < 2 or len(speeds) < 2 or len(dists) != len(speeds):
        return {"error": "Invalid speed profile", "baseline_time_s": 0, "predicted_time_s": 0, "delta_s": 0, "delta_pct": 0, "per_corner_deltas": []}

    d = np.array(dists, dtype=float)
    s = np.array(speeds, dtype=float)
    s = np.maximum(s, 0.1)  # avoid div by zero

    # Baseline time
    ds = np.diff(d)
    avg_s = (s[:-1] + s[1:]) / 2.0
    baseline = float(np.sum(ds / avg_s))

    # Apply adjustments
    s_adj = s.copy()
    per_corner = []

    for adj in adjustments:
        cid = adj.get("corner_id")
        pct = adj.get("speed_pct_change", 0)
        if cid is None or pct == 0:
            per_corner.append({"corner_id": cid, "delta_s": 0.0})
            continue

        # Find corner boundaries
        c_info = None
        for c in corners:
            if c.get("corner_id") == cid:
                c_info = c
                break

        if c_info is None:
            per_corner.append({"corner_id": cid, "delta_s": 0.0, "note": "corner not found"})
            continue

        d_start = c_info.get("d_start", 0)
        d_end = c_info.get("d_end", 0)

        # Apply speed change to points within corner
        mask = (d >= d_start) & (d <= d_end)
        factor = 1.0 + pct / 100.0

        # Calculate corner-specific delta
        corner_mask_idx = np.where(mask)[0]
        if len(corner_mask_idx) > 1:
            old_speeds = s_adj[corner_mask_idx].copy()
            s_adj[corner_mask_idx] *= factor
            new_speeds = s_adj[corner_mask_idx]

            # Time through corner before/after
            c_ds = np.diff(d[corner_mask_idx])
            old_dt = np.sum(c_ds / ((old_speeds[:-1] + old_speeds[1:]) / 2.0))
            new_dt = np.sum(c_ds / ((new_speeds[:-1] + new_speeds[1:]) / 2.0))
            per_corner.append({"corner_id": cid, "delta_s": round(new_dt - old_dt, 4)})
        else:
            per_corner.append({"corner_id": cid, "delta_s": 0.0})

    s_adj = np.maximum(s_adj, 0.1)
    avg_s_adj = (s_adj[:-1] + s_adj[1:]) / 2.0
    predicted = float(np.sum(ds / avg_s_adj))
    delta = predicted - baseline
    delta_pct = (delta / baseline * 100) if baseline > 0 else 0

    return {
        "baseline_time_s": round(baseline, 4),
        "predicted_time_s": round(predicted, 4),
        "delta_s": round(delta, 4),
        "delta_pct": round(delta_pct, 3),
        "per_corner_deltas": per_corner,
    }

# ── Inline tests ──────────────────────────────────────────────
def _run_tests() -> None:
    passed, failed = [], []
    def _test(name, fn):
        try: fn(); passed.append(name)
        except Exception: failed.append((name, traceback.format_exc()))

    def t_zero_adj():
        profile = {"distances": list(range(0, 1001, 10)), "speeds": [20.0]*101, "corners": []}
        result = simulate_what_if(profile, [])
        assert abs(result["delta_s"]) < 0.001
    _test("zero_adjustment", t_zero_adj)

    def t_speed_increase():
        dists = list(range(0, 1001, 1))
        speeds = [20.0]*1001
        corners = [{"corner_id": 1, "d_start": 200, "d_end": 400}]
        profile = {"distances": dists, "speeds": speeds, "corners": corners}
        result = simulate_what_if(profile, [{"corner_id": 1, "speed_pct_change": 10}])
        assert result["predicted_time_s"] < result["baseline_time_s"]
        assert result["delta_s"] < 0
    _test("speed_increase_faster", t_speed_increase)

    def t_speed_decrease():
        dists = list(range(0, 1001, 1))
        speeds = [20.0]*1001
        corners = [{"corner_id": 1, "d_start": 100, "d_end": 300}]
        profile = {"distances": dists, "speeds": speeds, "corners": corners}
        result = simulate_what_if(profile, [{"corner_id": 1, "speed_pct_change": -10}])
        assert result["predicted_time_s"] > result["baseline_time_s"]
    _test("speed_decrease_slower", t_speed_decrease)

    def t_empty_profile():
        result = simulate_what_if({"distances": [], "speeds": []}, [])
        assert result["baseline_time_s"] == 0
    _test("empty_profile", t_empty_profile)

    def t_missing_corner():
        dists = list(range(0, 501, 1))
        profile = {"distances": dists, "speeds": [15.0]*501, "corners": []}
        result = simulate_what_if(profile, [{"corner_id": 99, "speed_pct_change": 5}])
        assert abs(result["delta_s"]) < 0.001
    _test("missing_corner", t_missing_corner)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nWhat-If Simulator Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed: print(f"  OK {n}")
    for n, trace in failed: print(f"  FAIL {n}\n{trace}")
    if failed: raise AssertionError(f"{len(failed)} test(s) failed.")

if __name__ == "__main__": _run_tests()
