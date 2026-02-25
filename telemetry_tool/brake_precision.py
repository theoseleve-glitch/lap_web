"""
brake_precision.py
------------------
Computes brake precision scores for each corner by analyzing the scatter
(standard deviation) of brake initiation points across multiple laps.

A highly consistent driver will brake at nearly the same point every lap,
yielding a high precision score. A driver who varies brake points significantly
will score lower.

Public API
~~~~~~~~~~
``compute_brake_precision(corner_metrics_by_lap)``
    Accepts a dict mapping lap_number -> list of corner metric dicts.
    Returns a list of per-corner brake precision dicts.

``compute_overall_brake_score(precision_results)``
    Returns a single 0-100 aggregate score across all corners.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def compute_brake_precision(
    corner_metrics_by_lap: dict[int, list[dict[str, Any]]],
    *,
    threshold_m: float = 5.0,
) -> list[dict[str, Any]]:
    """
    Compute brake precision scores for each corner.

    Parameters
    ----------
    corner_metrics_by_lap : dict[int, list[dict]]
        Mapping of lap_number -> list of corner metric dicts.
        Each dict must have 'corner_id' and 'brake_point_m'.
    threshold_m : float
        The standard deviation (in metres) at which precision = 0%.
        Lower std → higher precision score.

    Returns
    -------
    list[dict] — one per corner, each with:
        corner_id, n_samples, mean_brake_m, std_brake_m,
        min_brake_m, max_brake_m, range_brake_m,
        precision_score (0–100)
    """
    # Group by corner_id
    corner_data: dict[int, list[float]] = {}
    for lap_num, metrics in corner_metrics_by_lap.items():
        for m in metrics:
            cid = m.get("corner_id")
            bp = m.get("brake_point_m")
            if cid is not None and bp is not None and math.isfinite(bp):
                corner_data.setdefault(cid, []).append(bp)

    results = []
    for cid in sorted(corner_data.keys()):
        points = np.array(corner_data[cid])
        n = len(points)
        if n < 2:
            results.append({
                "corner_id": cid,
                "n_samples": n,
                "mean_brake_m": round(float(points[0]), 2) if n == 1 else None,
                "std_brake_m": 0.0,
                "min_brake_m": round(float(points[0]), 2) if n == 1 else None,
                "max_brake_m": round(float(points[0]), 2) if n == 1 else None,
                "range_brake_m": 0.0,
                "precision_score": 100.0 if n == 1 else 0.0,
            })
            continue

        mean_bp = float(np.mean(points))
        std_bp = float(np.std(points, ddof=1))
        min_bp = float(np.min(points))
        max_bp = float(np.max(points))
        range_bp = max_bp - min_bp

        # Precision: 100 * (1 - std/threshold), clamped to [0, 100]
        precision = max(0.0, min(100.0, 100.0 * (1.0 - std_bp / threshold_m)))

        results.append({
            "corner_id": cid,
            "n_samples": n,
            "mean_brake_m": round(mean_bp, 2),
            "std_brake_m": round(std_bp, 2),
            "min_brake_m": round(min_bp, 2),
            "max_brake_m": round(max_bp, 2),
            "range_brake_m": round(range_bp, 2),
            "precision_score": round(precision, 1),
        })

    return results


def compute_overall_brake_score(
    precision_results: list[dict[str, Any]],
) -> float:
    """
    Aggregate per-corner brake precision into one 0–100 score.

    Uses a weighted mean where corners with more samples
    carry more weight.
    """
    if not precision_results:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for r in precision_results:
        n = r.get("n_samples", 1)
        score = r.get("precision_score", 0.0)
        w = max(1, n)
        weighted_sum += score * w
        total_weight += w

    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 1)


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

    # Test 1: consistent braking → high score
    def t_consistent():
        data = {
            1: [{"corner_id": 1, "brake_point_m": 100.0}, {"corner_id": 2, "brake_point_m": 300.0}],
            2: [{"corner_id": 1, "brake_point_m": 100.1}, {"corner_id": 2, "brake_point_m": 300.2}],
            3: [{"corner_id": 1, "brake_point_m": 99.9},  {"corner_id": 2, "brake_point_m": 299.8}],
            4: [{"corner_id": 1, "brake_point_m": 100.05},{"corner_id": 2, "brake_point_m": 300.1}],
            5: [{"corner_id": 1, "brake_point_m": 100.0}, {"corner_id": 2, "brake_point_m": 300.0}],
        }
        results = compute_brake_precision(data)
        assert len(results) == 2
        for r in results:
            assert r["precision_score"] > 95.0, f"Corner {r['corner_id']}: score {r['precision_score']} should be >95"

    _test("consistent_braking_high_score", t_consistent)

    # Test 2: wild variation → low score
    def t_wild():
        data = {
            1: [{"corner_id": 1, "brake_point_m": 90.0}],
            2: [{"corner_id": 1, "brake_point_m": 100.0}],
            3: [{"corner_id": 1, "brake_point_m": 110.0}],
            4: [{"corner_id": 1, "brake_point_m": 80.0}],
            5: [{"corner_id": 1, "brake_point_m": 120.0}],
        }
        results = compute_brake_precision(data)
        assert len(results) == 1
        assert results[0]["precision_score"] < 10.0, f"Score {results[0]['precision_score']} should be <10"

    _test("wild_variation_low_score", t_wild)

    # Test 3: single lap → score 100 (no variation measurable)
    def t_single():
        data = {
            1: [{"corner_id": 1, "brake_point_m": 100.0}],
        }
        results = compute_brake_precision(data)
        assert len(results) == 1
        assert results[0]["precision_score"] == 100.0
        assert results[0]["n_samples"] == 1

    _test("single_lap", t_single)

    # Test 4: empty input
    def t_empty():
        results = compute_brake_precision({})
        assert results == []

    _test("empty_input", t_empty)

    # Test 5: NaN brake points ignored
    def t_nan():
        data = {
            1: [{"corner_id": 1, "brake_point_m": 100.0}],
            2: [{"corner_id": 1, "brake_point_m": float("nan")}],
            3: [{"corner_id": 1, "brake_point_m": 100.5}],
        }
        results = compute_brake_precision(data)
        assert len(results) == 1
        assert results[0]["n_samples"] == 2

    _test("nan_filtered", t_nan)

    # Test 6: overall score
    def t_overall():
        precision_results = [
            {"corner_id": 1, "n_samples": 10, "precision_score": 90.0},
            {"corner_id": 2, "n_samples": 5,  "precision_score": 60.0},
        ]
        overall = compute_overall_brake_score(precision_results)
        # Weighted: (90*10 + 60*5) / (10+5) = 1200/15 = 80.0
        assert abs(overall - 80.0) < 0.1, f"Expected ~80.0, got {overall}"

    _test("overall_score", t_overall)

    # Test 7: overall empty
    def t_overall_empty():
        assert compute_overall_brake_score([]) == 0.0

    _test("overall_empty", t_overall_empty)

    # Test 8: missing brake_point_m keys
    def t_missing_key():
        data = {
            1: [{"corner_id": 1}],  # no brake_point_m
            2: [{"corner_id": 1, "brake_point_m": None}],
        }
        results = compute_brake_precision(data)
        assert results == []

    _test("missing_brake_key", t_missing_key)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nBrake Precision Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
