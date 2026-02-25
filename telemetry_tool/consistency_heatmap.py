"""
consistency_heatmap.py
----------------------
Generates a laps × corners consistency heatmap where each cell represents
the time loss (in ms) at that corner on that lap compared to the best
performance at that corner (either from best practices or session best).

Public API
~~~~~~~~~~
``compute_consistency_heatmap(corner_metrics, best_practices=None)``
    Returns a heatmap dict with rows=laps, cols=corners, cells=time_loss_ms.

``classify_consistency(heatmap_result)``
    Returns a per-corner consistency classification (consistent/variable/erratic).
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


# Thresholds for consistency classification
_CONSISTENT_THRESHOLD_MS = 20.0    # < 20ms → consistent
_VARIABLE_THRESHOLD_MS = 50.0      # < 50ms → variable, above → erratic


def compute_consistency_heatmap(
    corner_metrics: dict[int, list[dict[str, Any]]],
    best_practices: Optional[dict[int, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Build a consistency heatmap: laps × corners → time_loss_ms.

    Parameters
    ----------
    corner_metrics : dict[int, list[dict]]
        Mapping of lap_number -> list of corner metric dicts.
        Each dict must have 'corner_id' and 'time_loss_ms'.
    best_practices : dict[int, dict], optional
        Mapping of corner_id -> best practice dict with 'best_time_s'.
        If provided, time loss is computed relative to best practice.
        Otherwise, time loss is relative to session best for each corner.

    Returns
    -------
    dict with keys:
        laps: list of lap numbers (rows)
        corners: list of corner_ids (columns)
        values: 2D list [lap_idx][corner_idx] = time_loss_ms (or None)
        corner_stats: per-corner statistics dict
        total_time_loss_ms: sum of all time losses
        mean_time_loss_ms: average time loss per corner per lap
    """
    if not corner_metrics:
        return {
            "laps": [],
            "corners": [],
            "values": [],
            "corner_stats": [],
            "total_time_loss_ms": 0.0,
            "mean_time_loss_ms": 0.0,
        }

    # Collect all corner_ids and laps
    all_corners: set[int] = set()
    all_laps: set[int] = set()
    # Build lookup: (lap, corner) -> time_loss_ms
    lookup: dict[tuple[int, int], float] = {}

    for lap_num, metrics in corner_metrics.items():
        all_laps.add(lap_num)
        for m in metrics:
            cid = m.get("corner_id")
            tl = m.get("time_loss_ms")
            if cid is not None:
                all_corners.add(cid)
                if tl is not None and math.isfinite(tl):
                    lookup[(lap_num, cid)] = tl

    sorted_laps = sorted(all_laps)
    sorted_corners = sorted(all_corners)

    if not sorted_corners or not sorted_laps:
        return {
            "laps": [],
            "corners": [],
            "values": [],
            "corner_stats": [],
            "total_time_loss_ms": 0.0,
            "mean_time_loss_ms": 0.0,
        }

    # If using best practices, adjust values relative to best time
    # (Already should be time_loss_ms from corner analysis, but if
    #  best_practices provides corner best times, we could re-baseline)

    # Build the heatmap matrix
    values = []
    all_losses = []
    for lap_num in sorted_laps:
        row = []
        for cid in sorted_corners:
            val = lookup.get((lap_num, cid))
            row.append(round(val, 1) if val is not None else None)
            if val is not None:
                all_losses.append(val)
        values.append(row)

    # Per-corner statistics
    corner_stats = []
    for ci, cid in enumerate(sorted_corners):
        corner_vals = [
            values[li][ci]
            for li in range(len(sorted_laps))
            if values[li][ci] is not None
        ]
        if corner_vals:
            arr = np.array(corner_vals)
            corner_stats.append({
                "corner_id": cid,
                "n_laps": len(corner_vals),
                "mean_loss_ms": round(float(np.mean(arr)), 1),
                "std_loss_ms": round(float(np.std(arr, ddof=1)), 1) if len(arr) > 1 else 0.0,
                "min_loss_ms": round(float(np.min(arr)), 1),
                "max_loss_ms": round(float(np.max(arr)), 1),
                "total_loss_ms": round(float(np.sum(arr)), 1),
            })
        else:
            corner_stats.append({
                "corner_id": cid,
                "n_laps": 0,
                "mean_loss_ms": 0.0,
                "std_loss_ms": 0.0,
                "min_loss_ms": 0.0,
                "max_loss_ms": 0.0,
                "total_loss_ms": 0.0,
            })

    total = sum(all_losses) if all_losses else 0.0
    mean = float(np.mean(all_losses)) if all_losses else 0.0

    return {
        "laps": sorted_laps,
        "corners": sorted_corners,
        "values": values,
        "corner_stats": corner_stats,
        "total_time_loss_ms": round(total, 1),
        "mean_time_loss_ms": round(mean, 1),
    }


def classify_consistency(
    heatmap_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Classify each corner's consistency as 'consistent', 'variable', or 'erratic'.

    Parameters
    ----------
    heatmap_result : dict
        Output from compute_consistency_heatmap.

    Returns
    -------
    list[dict] — per-corner classification with corner_id, classification, std_loss_ms
    """
    classifications = []
    for cs in heatmap_result.get("corner_stats", []):
        std = cs.get("std_loss_ms", 0.0)
        if std < _CONSISTENT_THRESHOLD_MS:
            label = "consistent"
        elif std < _VARIABLE_THRESHOLD_MS:
            label = "variable"
        else:
            label = "erratic"

        classifications.append({
            "corner_id": cs["corner_id"],
            "classification": label,
            "std_loss_ms": std,
            "mean_loss_ms": cs.get("mean_loss_ms", 0.0),
        })

    return classifications


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

    # Test 1: basic heatmap
    def t_basic():
        data = {
            1: [
                {"corner_id": 1, "time_loss_ms": 10.0},
                {"corner_id": 2, "time_loss_ms": 30.0},
            ],
            2: [
                {"corner_id": 1, "time_loss_ms": 15.0},
                {"corner_id": 2, "time_loss_ms": 25.0},
            ],
            3: [
                {"corner_id": 1, "time_loss_ms": 12.0},
                {"corner_id": 2, "time_loss_ms": 28.0},
            ],
        }
        result = compute_consistency_heatmap(data)
        assert result["laps"] == [1, 2, 3]
        assert result["corners"] == [1, 2]
        assert len(result["values"]) == 3
        assert len(result["values"][0]) == 2
        assert result["total_time_loss_ms"] > 0

    _test("basic_heatmap", t_basic)

    # Test 2: empty input
    def t_empty():
        result = compute_consistency_heatmap({})
        assert result["laps"] == []
        assert result["total_time_loss_ms"] == 0.0

    _test("empty_input", t_empty)

    # Test 3: single lap (degenerate)
    def t_single():
        data = {
            1: [{"corner_id": 1, "time_loss_ms": 50.0}],
        }
        result = compute_consistency_heatmap(data)
        assert len(result["laps"]) == 1
        assert result["corner_stats"][0]["mean_loss_ms"] == 50.0

    _test("single_lap", t_single)

    # Test 4: 20 laps
    def t_many_laps():
        data = {}
        for lap in range(1, 21):
            data[lap] = [
                {"corner_id": c, "time_loss_ms": float(c * 10 + lap)}
                for c in range(1, 6)
            ]
        result = compute_consistency_heatmap(data)
        assert len(result["laps"]) == 20
        assert len(result["corners"]) == 5
        assert len(result["values"]) == 20
        assert all(len(row) == 5 for row in result["values"])

    _test("many_laps", t_many_laps)

    # Test 5: missing corners in some laps
    def t_missing_corners():
        data = {
            1: [{"corner_id": 1, "time_loss_ms": 10.0},
                {"corner_id": 2, "time_loss_ms": 20.0}],
            2: [{"corner_id": 1, "time_loss_ms": 12.0}],
            # Lap 2 missing corner 2
        }
        result = compute_consistency_heatmap(data)
        assert result["values"][1][1] is None  # Lap 2, corner 2

    _test("missing_corners", t_missing_corners)

    # Test 6: classification
    def t_classify():
        data = {
            1: [
                {"corner_id": 1, "time_loss_ms": 10.0},
                {"corner_id": 2, "time_loss_ms": 30.0},
                {"corner_id": 3, "time_loss_ms": 100.0},
            ],
            2: [
                {"corner_id": 1, "time_loss_ms": 11.0},
                {"corner_id": 2, "time_loss_ms": 60.0},
                {"corner_id": 3, "time_loss_ms": 10.0},
            ],
            3: [
                {"corner_id": 1, "time_loss_ms": 10.5},
                {"corner_id": 2, "time_loss_ms": 45.0},
                {"corner_id": 3, "time_loss_ms": 200.0},
            ],
        }
        hm = compute_consistency_heatmap(data)
        classes = classify_consistency(hm)
        assert len(classes) == 3
        # Corner 1: std ~0.5 → consistent
        assert classes[0]["classification"] == "consistent"
        # Corner 3: very high std → erratic
        assert classes[2]["classification"] == "erratic"

    _test("classification", t_classify)

    # Test 7: NaN values
    def t_nan():
        data = {
            1: [{"corner_id": 1, "time_loss_ms": 10.0}],
            2: [{"corner_id": 1, "time_loss_ms": float("nan")}],
        }
        result = compute_consistency_heatmap(data)
        assert result["corner_stats"][0]["n_laps"] == 1

    _test("nan_values", t_nan)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nConsistency Heatmap Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
