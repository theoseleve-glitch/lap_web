"""
throttle_mapping.py
-------------------
Per-corner throttle onset analysis: compare the driver's throttle application
point versus theoretical optimal. Produces heatmap-friendly data showing
throttle onset delay (or advantage) per corner per lap.

Public API
~~~~~~~~~~
``compute_throttle_profiles(corner_metrics_by_lap, theoretical_metrics=None)``
    Returns throttle onset analysis: per-corner, per-lap, and heatmap data.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_throttle_profiles(
    corner_metrics_by_lap: dict[int, list[dict[str, Any]]],
    theoretical_metrics: Optional[dict[int, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Compute throttle onset profiles for each corner across laps.

    Parameters
    ----------
    corner_metrics_by_lap : dict[int, list[dict]]
        Mapping of lap_number -> list of corner metric dicts.
        Each dict should have: corner_id, throttle_onset_m, exit_accel_mps2,
        exit_speed_mps.
    theoretical_metrics : dict[int, dict], optional
        Mapping of corner_id -> theoretical performance dict with
        ideal throttle_onset_m.

    Returns
    -------
    dict with keys:
        per_corner: list of per-corner summary dicts
        heatmap: dict with laps (rows), corners (cols), and values matrix
        overall_throttle_score: 0-100 aggregate score
    """
    theoretical_metrics = theoretical_metrics or {}

    # Group by corner_id
    corner_data: dict[int, list[tuple[int, dict]]] = {}
    for lap_num, metrics in corner_metrics_by_lap.items():
        for m in metrics:
            cid = m.get("corner_id")
            if cid is not None:
                corner_data.setdefault(cid, []).append((lap_num, m))

    if not corner_data:
        return {
            "per_corner": [],
            "heatmap": {"laps": [], "corners": [], "values": []},
            "overall_throttle_score": 0.0,
        }

    sorted_corners = sorted(corner_data.keys())
    all_laps = sorted(set(
        lap_num for laps in corner_data.values()
        for lap_num, _ in laps
    ))

    per_corner = []
    scores = []

    for cid in sorted_corners:
        entries = corner_data[cid]
        onsets = []
        exit_accels = []
        exit_speeds = []

        for lap_num, m in entries:
            to = m.get("throttle_onset_m")
            if to is not None and math.isfinite(to):
                onsets.append(to)
            ea = m.get("exit_accel_mps2")
            if ea is not None and math.isfinite(ea):
                exit_accels.append(ea)
            es = m.get("exit_speed_mps")
            if es is not None and math.isfinite(es):
                exit_speeds.append(es)

        # Theoretical comparison
        theo = theoretical_metrics.get(cid, {})
        theo_onset = theo.get("throttle_onset_m")

        onset_arr = np.array(onsets) if onsets else np.array([])
        summary = {
            "corner_id": cid,
            "n_samples": len(onsets),
            "mean_onset_m": round(float(np.mean(onset_arr)), 2) if len(onset_arr) > 0 else None,
            "std_onset_m": round(float(np.std(onset_arr, ddof=1)), 2) if len(onset_arr) > 1 else 0.0,
            "min_onset_m": round(float(np.min(onset_arr)), 2) if len(onset_arr) > 0 else None,
            "max_onset_m": round(float(np.max(onset_arr)), 2) if len(onset_arr) > 0 else None,
            "mean_exit_accel": round(float(np.mean(exit_accels)), 2) if exit_accels else None,
            "mean_exit_speed": round(float(np.mean(exit_speeds)), 2) if exit_speeds else None,
            "theoretical_onset_m": theo_onset,
            "onset_delta_m": None,
            "throttle_score": 0.0,
        }

        # Delta vs theoretical (positive = driver gets on throttle later = worse)
        if theo_onset is not None and summary["mean_onset_m"] is not None:
            delta = summary["mean_onset_m"] - theo_onset
            summary["onset_delta_m"] = round(delta, 2)
            # Score: 100 when on point, degrades with delay
            # Allow up to 10m delay before score = 0
            summary["throttle_score"] = round(
                max(0.0, min(100.0, 100.0 * (1.0 - abs(delta) / 10.0))), 1
            )
        elif len(onset_arr) > 1:
            # Without theoretical, score based on consistency
            cv = float(np.std(onset_arr, ddof=1) / max(abs(np.mean(onset_arr)), 0.1))
            summary["throttle_score"] = round(max(0.0, min(100.0, 100.0 * (1.0 - cv))), 1)

        scores.append(summary["throttle_score"])
        per_corner.append(summary)

    # Build heatmap: laps x corners → throttle onset values
    heatmap_values = []
    for lap_num in all_laps:
        row = []
        for cid in sorted_corners:
            # Find this lap's onset for this corner
            val = None
            for ln, m in corner_data.get(cid, []):
                if ln == lap_num:
                    to = m.get("throttle_onset_m")
                    if to is not None and math.isfinite(to):
                        val = round(to, 2)
                    break
            row.append(val)
        heatmap_values.append(row)

    overall = round(float(np.mean(scores)), 1) if scores else 0.0

    return {
        "per_corner": per_corner,
        "heatmap": {
            "laps": all_laps,
            "corners": sorted_corners,
            "values": heatmap_values,
        },
        "overall_throttle_score": overall,
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

    # Test 1: basic 5-lap known profiles
    def t_basic():
        data = {}
        for lap in range(1, 6):
            data[lap] = [
                {"corner_id": 1, "throttle_onset_m": 200.0 + lap * 0.1,
                 "exit_accel_mps2": 3.0, "exit_speed_mps": 18.0},
                {"corner_id": 2, "throttle_onset_m": 450.0 + lap * 0.2,
                 "exit_accel_mps2": 2.5, "exit_speed_mps": 15.0},
            ]
        result = compute_throttle_profiles(data)
        assert len(result["per_corner"]) == 2
        assert result["heatmap"]["laps"] == [1, 2, 3, 4, 5]
        assert result["heatmap"]["corners"] == [1, 2]
        assert len(result["heatmap"]["values"]) == 5
        assert result["overall_throttle_score"] > 0

    _test("basic_profiles", t_basic)

    # Test 2: with theoretical comparison
    def t_theoretical():
        data = {
            1: [{"corner_id": 1, "throttle_onset_m": 202.0}],
            2: [{"corner_id": 1, "throttle_onset_m": 201.5}],
            3: [{"corner_id": 1, "throttle_onset_m": 203.0}],
        }
        theo = {1: {"throttle_onset_m": 200.0}}
        result = compute_throttle_profiles(data, theoretical_metrics=theo)
        c = result["per_corner"][0]
        assert c["theoretical_onset_m"] == 200.0
        assert c["onset_delta_m"] is not None
        assert c["onset_delta_m"] > 0  # driver is late
        assert c["throttle_score"] > 0

    _test("theoretical_comparison", t_theoretical)

    # Test 3: empty input
    def t_empty():
        result = compute_throttle_profiles({})
        assert result["per_corner"] == []
        assert result["overall_throttle_score"] == 0.0

    _test("empty_input", t_empty)

    # Test 4: NaN values filtered
    def t_nan():
        data = {
            1: [{"corner_id": 1, "throttle_onset_m": 200.0}],
            2: [{"corner_id": 1, "throttle_onset_m": float("nan")}],
            3: [{"corner_id": 1, "throttle_onset_m": 201.0}],
        }
        result = compute_throttle_profiles(data)
        assert result["per_corner"][0]["n_samples"] == 2

    _test("nan_filtered", t_nan)

    # Test 5: heatmap dimensions correct
    def t_heatmap():
        data = {
            1: [{"corner_id": 1, "throttle_onset_m": 100.0},
                {"corner_id": 2, "throttle_onset_m": 200.0}],
            2: [{"corner_id": 1, "throttle_onset_m": 101.0}],
            # lap 2 missing corner 2
        }
        result = compute_throttle_profiles(data)
        h = result["heatmap"]
        assert len(h["values"]) == 2  # 2 laps
        assert len(h["values"][0]) == 2  # 2 corners per row
        assert h["values"][1][1] is None  # missing corner 2 in lap 2

    _test("heatmap_dimensions", t_heatmap)

    # Test 6: perfect throttle onset → score 100
    def t_perfect():
        data = {
            1: [{"corner_id": 1, "throttle_onset_m": 200.0}],
            2: [{"corner_id": 1, "throttle_onset_m": 200.0}],
        }
        theo = {1: {"throttle_onset_m": 200.0}}
        result = compute_throttle_profiles(data, theo)
        assert result["per_corner"][0]["throttle_score"] == 100.0

    _test("perfect_onset", t_perfect)

    # Test 7: very late throttle → low score
    def t_late():
        data = {
            1: [{"corner_id": 1, "throttle_onset_m": 215.0}],
            2: [{"corner_id": 1, "throttle_onset_m": 214.0}],
        }
        theo = {1: {"throttle_onset_m": 200.0}}
        result = compute_throttle_profiles(data, theo)
        assert result["per_corner"][0]["throttle_score"] < 10.0

    _test("late_throttle_low_score", t_late)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nThrottle Mapping Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
