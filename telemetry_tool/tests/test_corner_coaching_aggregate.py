"""Tests for corner_coaching_aggregate.py."""
from __future__ import annotations

import numpy as np
import pytest

from corner_coaching_aggregate import (
    CornerProven,
    CornerActual,
    compute_proven_limits,
    compute_actual_metrics,
    classify_root_cause,
    compute_time_loss,
    generate_narrative,
    compute_corner_coaching_v4,
)
from track_surface import AggregateGrip


def _make_aggregate(n=100, mu=1.2):
    dist = np.linspace(0, 500, n)
    return AggregateGrip(
        distance_bins=dist,
        mu_p95=np.full(n, mu),
        mu_mean=np.full(n, mu * 0.9),
        mu_lon_accel=np.full(n, 0.4),
        mu_lon_brake=np.full(n, 0.9),
        session_count=10,
        track_id="test",
    )


def _make_corners():
    return [
        {"corner_id": 1, "corner_name": "T1", "direction": "R",
         "s_start": 100.0, "s_apex": 130.0, "s_end": 160.0,
         "curvature_1pm": 0.02},
        {"corner_id": 2, "corner_name": "T2", "direction": "L",
         "s_start": 250.0, "s_apex": 280.0, "s_end": 310.0,
         "curvature_1pm": 0.01},
    ]


class TestComputeProvenLimits:
    def test_returns_one_entry_per_corner(self):
        result = compute_proven_limits(_make_aggregate(), _make_corners())
        assert len(result) == 2

    def test_proven_speeds_are_positive(self):
        for p in compute_proven_limits(_make_aggregate(mu=1.2), _make_corners()):
            assert p.entry_kph > 0
            assert p.apex_kph > 0
            assert p.exit_kph > 0

    def test_higher_grip_gives_higher_speed(self):
        corners = _make_corners()
        low = compute_proven_limits(_make_aggregate(mu=0.8), corners)
        high = compute_proven_limits(_make_aggregate(mu=1.4), corners)
        assert high[0].apex_kph > low[0].apex_kph

    def test_tighter_corner_gives_lower_speed(self):
        result = compute_proven_limits(_make_aggregate(mu=1.2), _make_corners())
        assert result[0].apex_kph < result[1].apex_kph  # T1 kappa=0.02 > T2 kappa=0.01


class TestComputeActualMetrics:
    def test_extracts_speeds_at_corner_points(self):
        distances = np.linspace(0, 500, 200)
        speeds_mps = np.full(200, 25.0)
        accel_mps2 = np.zeros(200)
        result = compute_actual_metrics(distances, speeds_mps, accel_mps2, _make_corners())
        assert len(result) == 2
        for a in result:
            assert abs(a.entry_kph - 90.0) < 2.0

    def test_detects_brake_point(self):
        distances = np.linspace(0, 500, 500)
        speeds_mps = np.full(500, 30.0)
        accel_mps2 = np.zeros(500)
        brake_zone = (distances >= 80) & (distances <= 100)
        accel_mps2[brake_zone] = -5.0
        speeds_mps[brake_zone] = np.linspace(30, 22, brake_zone.sum())
        result = compute_actual_metrics(distances, speeds_mps, accel_mps2, _make_corners())
        assert result[0].brake_point_m is not None
        assert 75 < result[0].brake_point_m < 100


class TestClassifyRootCause:
    def _proven(self, entry=100, apex=75, exit_=90, brake=230):
        return CornerProven(1, entry, apex, exit_, brake)
    def _actual(self, entry=100, apex=75, exit_=90, brake=230):
        return CornerActual(1, entry, apex, exit_, brake)

    def test_early_brake(self):
        assert "early_brake" in classify_root_cause(self._proven(brake=230), self._actual(brake=222))
    def test_late_brake(self):
        assert "late_brake" in classify_root_cause(self._proven(brake=230), self._actual(brake=238))
    def test_apex_deficit(self):
        assert "apex_deficit" in classify_root_cause(self._proven(apex=78), self._actual(apex=72, entry=100))
    def test_exit_under_application(self):
        assert "exit_under_application" in classify_root_cause(
            self._proven(exit_=92), self._actual(exit_=80), grip_headroom_pct=15.0)
    def test_clean_corner(self):
        assert classify_root_cause(self._proven(), self._actual()) == []


class TestComputeTimeLoss:
    def test_slower_has_positive_loss(self):
        d = np.array([0, 10, 20, 30])
        assert compute_time_loss(d, np.full(4, 20.0), np.full(4, 25.0)) > 0
    def test_equal_speed_zero(self):
        d = np.array([0, 10, 20, 30])
        assert abs(compute_time_loss(d, np.full(4, 25.0), np.full(4, 25.0))) < 0.001


class TestGenerateNarrative:
    def test_early_brake(self):
        text = generate_narrative("T4", "R",
            CornerProven(4, 105, 78, 92, 234), CornerActual(4, 105, 72, 88, 229),
            ["early_brake"], 12, 0.31)
        assert "braking" in text.lower() and "T4" in text and "12" in text
    def test_apex_deficit(self):
        text = generate_narrative("T2", "L",
            CornerProven(2, 95, 68, 82, None), CornerActual(2, 95, 61, 80, None),
            ["apex_deficit"], 8, 0.18)
        assert "apex" in text.lower() and "T2" in text
    def test_empty_causes(self):
        text = generate_narrative("T1", "R",
            CornerProven(1, 100, 75, 90, None), CornerActual(1, 100, 75, 90, None),
            [], 5, 0.0)
        assert isinstance(text, str) and "clean" in text.lower()


class TestComputeCornerCoachingV4:
    def test_full_pipeline(self):
        agg = _make_aggregate(n=200, mu=1.2)
        corners = _make_corners()
        speed_trace = {
            "distances": np.linspace(0, 500, 200).tolist(),
            "speeds": np.full(200, 20.0).tolist(),  # constant 72kph -- slower than proven
        }
        result = compute_corner_coaching_v4(agg, corners, speed_trace)
        assert "corners" in result
        assert "summary" in result
        assert result["summary"]["aggregate_sessions"] == 10

    def test_empty_speed_trace(self):
        agg = _make_aggregate()
        result = compute_corner_coaching_v4(agg, _make_corners(), {"distances": [], "speeds": []})
        assert result["corners"] == []
