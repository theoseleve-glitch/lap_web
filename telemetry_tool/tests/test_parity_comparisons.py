"""Unit tests for parity harness comparison functions.

Tests all four pure comparison functions from scripts/parity_harness.py:
  - compare_scores  (tolerance on score pillars)
  - compare_laps    (time tolerance in ms, exact best-lap index)
  - compare_corners (boundary tolerance in metres)
  - compare_sectors (time tolerance in seconds)

These are fast, pure-function tests with no I/O or network calls.
"""
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.parity_harness import (
    compare_corners,
    compare_laps,
    compare_scores,
    compare_sectors,
)


# ── Scores ────────────────────────────────────────────────────────────


class TestCompareScores:
    """compare_scores: tolerance-based numeric comparison of score pillars."""

    def test_scores_within_tolerance(self):
        """Identical scores should pass with zero failures."""
        local = {
            "total_score": 75.0,
            "pace": 18.0,
            "consistency": 15.0,
            "execution": 20.0,
            "robustness": 22.0,
            "adaptation": 11.0,
        }
        saas = dict(local)  # identical copy
        result = compare_scores(local, saas, tolerance=0.1)
        assert result["pass"] is True
        assert result["failures"] == []

    def test_scores_outside_tolerance(self):
        """Delta > 0.1 on a pillar must produce a failure."""
        local = {
            "total_score": 75.0,
            "pace": 18.0,
            "consistency": 15.0,
            "execution": 20.0,
            "robustness": 22.0,
            "adaptation": 11.0,
        }
        saas = dict(local)
        saas["pace"] = 18.5  # delta = 0.5, exceeds 0.1

        result = compare_scores(local, saas, tolerance=0.1)
        assert result["pass"] is False
        assert len(result["failures"]) == 1
        fail = result["failures"][0]
        assert fail["field"] == "pace"
        assert fail["delta"] > 0.1

    def test_scores_missing_field(self):
        """If one side has None for a field, report a missing-value failure."""
        local = {
            "total_score": 75.0,
            "pace": 18.0,
            "consistency": None,
            "execution": 20.0,
            "robustness": 22.0,
            "adaptation": 11.0,
        }
        saas = {
            "total_score": 75.0,
            "pace": 18.0,
            "consistency": 15.0,
            "execution": 20.0,
            "robustness": 22.0,
            "adaptation": 11.0,
        }
        result = compare_scores(local, saas, tolerance=0.1)
        assert result["pass"] is False
        fail = result["failures"][0]
        assert fail["field"] == "consistency"
        assert fail["reason"] == "missing_value"


# ── Laps ──────────────────────────────────────────────────────────────


def _make_lap(time_s: float, is_best: bool = False) -> dict:
    return {"lap_time_s": time_s, "is_best": is_best}


class TestCompareLaps:
    """compare_laps: time tolerance in ms, exact best-lap index match."""

    def test_laps_best_index_must_match(self):
        """Identical laps (same times, same best index) pass."""
        local = [
            _make_lap(60.0),
            _make_lap(59.5, is_best=True),
            _make_lap(60.1),
        ]
        saas = [
            _make_lap(60.0),
            _make_lap(59.5, is_best=True),
            _make_lap(60.1),
        ]
        result = compare_laps(local, saas, time_tolerance_ms=5)
        assert result["pass"] is True
        assert result["failures"] == []

    def test_laps_time_outside_tolerance(self):
        """Lap-time delta > 5 ms must fail."""
        local = [
            _make_lap(60.000, is_best=True),
            _make_lap(60.100),
        ]
        saas = [
            _make_lap(60.010, is_best=True),  # delta = 10 ms > 5
            _make_lap(60.100),
        ]
        result = compare_laps(local, saas, time_tolerance_ms=5)
        assert result["pass"] is False
        failures_on_time = [
            f for f in result["failures"]
            if f["field"].endswith(".time")
        ]
        assert len(failures_on_time) >= 1
        assert failures_on_time[0]["delta"] > 5

    def test_laps_count_mismatch(self):
        """Different lap counts produce an immediate failure."""
        local = [_make_lap(60.0), _make_lap(61.0)]
        saas = [_make_lap(60.0)]
        result = compare_laps(local, saas, time_tolerance_ms=5)
        assert result["pass"] is False
        assert result["failures"][0]["field"] == "lap_count"
        assert result["failures"][0]["local"] == 2
        assert result["failures"][0]["saas"] == 1


# ── Corners ───────────────────────────────────────────────────────────


def _make_corner(s_start: float, s_end: float, s_apex: float) -> dict:
    return {"s_start": s_start, "s_end": s_end, "s_apex": s_apex}


class TestCompareCorners:
    """compare_corners: boundary tolerance in metres."""

    def test_corners_within_tolerance(self):
        """Boundaries within 1 m of each other pass."""
        local = [
            _make_corner(100.0, 200.0, 150.0),
            _make_corner(400.0, 500.0, 450.0),
        ]
        saas = [
            _make_corner(100.5, 200.3, 150.9),  # all within 1m
            _make_corner(400.8, 499.2, 450.1),
        ]
        result = compare_corners(local, saas, boundary_tolerance_m=1.0)
        assert result["pass"] is True
        assert result["failures"] == []

    def test_corners_outside_tolerance(self):
        """Boundary delta > 1 m must fail."""
        local = [_make_corner(100.0, 200.0, 150.0)]
        saas = [_make_corner(102.0, 200.0, 150.0)]  # s_start off by 2 m
        result = compare_corners(local, saas, boundary_tolerance_m=1.0)
        assert result["pass"] is False
        assert len(result["failures"]) == 1
        fail = result["failures"][0]
        assert "s_start" in fail["field"]
        assert fail["delta"] > 1.0


# ── Sectors ───────────────────────────────────────────────────────────


def _make_sector(best_time_s: float, mean_time_s: float) -> dict:
    return {"best_time_s": best_time_s, "mean_time_s": mean_time_s}


class TestCompareSectors:
    """compare_sectors: time tolerance in seconds."""

    def test_sectors_within_tolerance(self):
        """Deltas < 0.001 s pass."""
        local = [
            _make_sector(14.200, 14.500),
            _make_sector(15.100, 15.300),
        ]
        saas = [
            _make_sector(14.2005, 14.5008),  # within 0.001
            _make_sector(15.1003, 15.2997),
        ]
        result = compare_sectors(local, saas, time_tolerance_s=0.001)
        assert result["pass"] is True
        assert result["failures"] == []

    def test_sectors_count_mismatch(self):
        """Different sector counts produce an immediate failure."""
        local = [_make_sector(14.2, 14.5), _make_sector(15.1, 15.3)]
        saas = [_make_sector(14.2, 14.5)]
        result = compare_sectors(local, saas, time_tolerance_s=0.001)
        assert result["pass"] is False
        assert result["failures"][0]["field"] == "sector_count"
        assert result["failures"][0]["local"] == 2
        assert result["failures"][0]["saas"] == 1
