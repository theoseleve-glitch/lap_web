"""
rival_comparison.py
-------------------
Compare multiple drivers' performances on the same track using
segment-by-segment gap analysis and aggregate statistics.

Public API
~~~~~~~~~~
``compare_rivals(driver_data)``
    Accepts data for 2–5 drivers. Returns gap analysis and rankings.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def compare_rivals(
    driver_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare multiple drivers' performances.

    Parameters
    ----------
    driver_data : list[dict]
        Each dict should have:
            driver_id, driver_name, best_lap_time_s,
            mean_lap_time_s (optional),
            consistency_cv_pct (optional),
            corner_metrics (optional): list of per-corner dicts,
            total_score (optional).

    Returns
    -------
    dict with keys:
        rankings: list sorted by best_lap_time_s
        gap_analysis: pairwise gaps between drivers
        strengths_weaknesses: per-driver relative strengths
        n_drivers: int
    """
    if not driver_data:
        return {
            "rankings": [],
            "gap_analysis": [],
            "strengths_weaknesses": [],
            "n_drivers": 0,
        }

    # Filter out drivers without lap times
    valid = [
        d for d in driver_data
        if d.get("best_lap_time_s") is not None
        and math.isfinite(d.get("best_lap_time_s", float("nan")))
    ]

    if not valid:
        return {
            "rankings": [],
            "gap_analysis": [],
            "strengths_weaknesses": [],
            "n_drivers": 0,
        }

    # Sort by best lap time (ascending = fastest first)
    ranked = sorted(valid, key=lambda d: d["best_lap_time_s"])
    leader_time = ranked[0]["best_lap_time_s"]

    # Build rankings
    rankings = []
    for i, d in enumerate(ranked):
        gap_s = d["best_lap_time_s"] - leader_time
        gap_pct = (gap_s / leader_time * 100) if leader_time > 0 else 0

        rankings.append({
            "position": i + 1,
            "driver_id": d.get("driver_id"),
            "driver_name": d.get("driver_name", "Unknown"),
            "best_lap_time_s": round(d["best_lap_time_s"], 3),
            "mean_lap_time_s": round(d["mean_lap_time_s"], 3) if d.get("mean_lap_time_s") else None,
            "gap_to_leader_s": round(gap_s, 3),
            "gap_to_leader_pct": round(gap_pct, 2),
            "total_score": d.get("total_score"),
            "consistency_cv_pct": d.get("consistency_cv_pct"),
        })

    # Pairwise gap analysis
    gap_analysis = []
    for i in range(len(ranked)):
        for j in range(i + 1, len(ranked)):
            d_a = ranked[i]
            d_b = ranked[j]
            gap = d_b["best_lap_time_s"] - d_a["best_lap_time_s"]
            gap_analysis.append({
                "driver_a": d_a.get("driver_name", "?"),
                "driver_b": d_b.get("driver_name", "?"),
                "gap_s": round(gap, 3),
                "gap_pct": round(gap / d_a["best_lap_time_s"] * 100, 2) if d_a["best_lap_time_s"] > 0 else 0,
            })

    # Per-driver relative strengths/weaknesses
    strengths = []
    metrics_keys = [
        ("best_lap_time_s", "Raw Pace", True),     # lower=better
        ("consistency_cv_pct", "Consistency", True), # lower=better
        ("total_score", "Overall Score", False),     # higher=better
    ]

    for d in ranked:
        driver_strengths = []
        driver_weaknesses = []

        for key, label, lower_is_better in metrics_keys:
            val = d.get(key)
            if val is None:
                continue

            # Compare to average of others
            others = [o.get(key) for o in ranked if o is not d and o.get(key) is not None]
            if not others:
                continue

            avg_others = float(np.mean(others))
            if lower_is_better:
                if val < avg_others * 0.99:
                    driver_strengths.append(label)
                elif val > avg_others * 1.01:
                    driver_weaknesses.append(label)
            else:
                if val > avg_others * 1.01:
                    driver_strengths.append(label)
                elif val < avg_others * 0.99:
                    driver_weaknesses.append(label)

        strengths.append({
            "driver_name": d.get("driver_name", "?"),
            "strengths": driver_strengths,
            "weaknesses": driver_weaknesses,
        })

    return {
        "rankings": rankings,
        "gap_analysis": gap_analysis,
        "strengths_weaknesses": strengths,
        "n_drivers": len(ranked),
    }


def compare_corner_performance(
    driver_corner_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare drivers' corner-by-corner performance.

    Parameters
    ----------
    driver_corner_data : list[dict]
        Each dict: driver_name, corners: list of {corner_id, avg_time_loss_ms,
        avg_entry_speed, avg_apex_speed, avg_exit_speed}.

    Returns
    -------
    dict with corner_comparison: per-corner rankings across drivers.
    """
    if not driver_corner_data:
        return {"corner_comparison": []}

    # Collect all corner_ids
    all_corners: set[int] = set()
    for dd in driver_corner_data:
        for c in dd.get("corners", []):
            cid = c.get("corner_id")
            if cid is not None:
                all_corners.add(cid)

    comparisons = []
    for cid in sorted(all_corners):
        corner_entries = []
        for dd in driver_corner_data:
            for c in dd.get("corners", []):
                if c.get("corner_id") == cid:
                    corner_entries.append({
                        "driver_name": dd.get("driver_name", "?"),
                        "time_loss_ms": c.get("avg_time_loss_ms", 0),
                        "entry_speed": c.get("avg_entry_speed"),
                        "apex_speed": c.get("avg_apex_speed"),
                        "exit_speed": c.get("avg_exit_speed"),
                    })
                    break

        # Sort by time loss (lower = better)
        corner_entries.sort(key=lambda e: e.get("time_loss_ms") or 999)
        comparisons.append({
            "corner_id": cid,
            "drivers": corner_entries,
        })

    return {"corner_comparison": comparisons}


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

    # Test 1: two drivers
    def t_two():
        data = [
            {"driver_id": 1, "driver_name": "Alice", "best_lap_time_s": 60.0,
             "mean_lap_time_s": 61.0, "consistency_cv_pct": 1.5, "total_score": 85.0},
            {"driver_id": 2, "driver_name": "Bob", "best_lap_time_s": 61.0,
             "mean_lap_time_s": 62.0, "consistency_cv_pct": 2.0, "total_score": 78.0},
        ]
        result = compare_rivals(data)
        assert result["n_drivers"] == 2
        assert result["rankings"][0]["driver_name"] == "Alice"
        assert result["rankings"][0]["position"] == 1
        assert result["rankings"][1]["gap_to_leader_s"] == 1.0
        assert len(result["gap_analysis"]) == 1

    _test("two_drivers", t_two)

    # Test 2: five drivers
    def t_five():
        data = [
            {"driver_name": f"D{i}", "best_lap_time_s": 60.0 + i * 0.5}
            for i in range(5)
        ]
        result = compare_rivals(data)
        assert result["n_drivers"] == 5
        assert result["rankings"][0]["driver_name"] == "D0"
        # Pairwise: C(5,2) = 10
        assert len(result["gap_analysis"]) == 10

    _test("five_drivers", t_five)

    # Test 3: single driver
    def t_single():
        data = [
            {"driver_name": "Solo", "best_lap_time_s": 60.0},
        ]
        result = compare_rivals(data)
        assert result["n_drivers"] == 1
        assert result["rankings"][0]["gap_to_leader_s"] == 0.0

    _test("single_driver", t_single)

    # Test 4: empty
    def t_empty():
        result = compare_rivals([])
        assert result["n_drivers"] == 0

    _test("empty", t_empty)

    # Test 5: NaN lap time filtered
    def t_nan():
        data = [
            {"driver_name": "A", "best_lap_time_s": 60.0},
            {"driver_name": "B", "best_lap_time_s": float("nan")},
            {"driver_name": "C", "best_lap_time_s": 61.0},
        ]
        result = compare_rivals(data)
        assert result["n_drivers"] == 2

    _test("nan_filtered", t_nan)

    # Test 6: corner comparison
    def t_corners():
        data = [
            {
                "driver_name": "Alice",
                "corners": [
                    {"corner_id": 1, "avg_time_loss_ms": 10.0, "avg_entry_speed": 20.0},
                    {"corner_id": 2, "avg_time_loss_ms": 30.0, "avg_entry_speed": 18.0},
                ],
            },
            {
                "driver_name": "Bob",
                "corners": [
                    {"corner_id": 1, "avg_time_loss_ms": 20.0, "avg_entry_speed": 19.0},
                    {"corner_id": 2, "avg_time_loss_ms": 15.0, "avg_entry_speed": 19.5},
                ],
            },
        ]
        result = compare_corner_performance(data)
        cc = result["corner_comparison"]
        assert len(cc) == 2
        # Corner 1: Alice better (10 < 20)
        assert cc[0]["drivers"][0]["driver_name"] == "Alice"
        # Corner 2: Bob better (15 < 30)
        assert cc[1]["drivers"][0]["driver_name"] == "Bob"

    _test("corner_comparison", t_corners)

    # Test 7: strengths/weaknesses
    def t_strengths():
        data = [
            {"driver_name": "Fast", "best_lap_time_s": 58.0, "consistency_cv_pct": 3.0, "total_score": 90.0},
            {"driver_name": "Consistent", "best_lap_time_s": 60.0, "consistency_cv_pct": 0.5, "total_score": 85.0},
        ]
        result = compare_rivals(data)
        sw = result["strengths_weaknesses"]
        assert len(sw) == 2
        # Fast should have "Raw Pace" as strength
        fast_sw = [s for s in sw if s["driver_name"] == "Fast"][0]
        assert "Raw Pace" in fast_sw["strengths"]

    _test("strengths_weaknesses", t_strengths)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nRival Comparison Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
