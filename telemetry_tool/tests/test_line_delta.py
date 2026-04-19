"""Tests for track_surface line_delta, solver_bridge, and coaching."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from track_surface.coaching import generate_spatial_coaching
from track_surface.frenet import FrenetFrame
from track_surface.line_delta import (
    CornerLineLoss,
    LineDelta,
    compute_line_delta,
    decompose_corner_losses,
)
from track_surface.model import TrackSurface
from track_surface.solver_bridge import surface_to_track_model


def _make_straight_frame(length: float = 200.0, n: int = 400) -> FrenetFrame:
    xy = np.column_stack([np.linspace(0, length, n), np.zeros(n)])
    return FrenetFrame.from_centerline(xy)


def _make_straight_surface(length: float = 200.0) -> TrackSurface:
    ff = _make_straight_frame(length)
    return TrackSurface(
        track_id="test",
        frenet=ff,
        width_left=np.full(ff.n_points, 5.0),
        width_right=np.full(ff.n_points, 5.0),
        n_laps=5,
        sim_sources=["test"],
    )


class TestLineDelta:
    def test_on_optimal_zero_delta(self):
        ff = _make_straight_frame()
        # "Optimal" = straight along centerline at 30 m/s
        opt_dist = np.arange(0, 199, 1.0)
        opt_speed = np.full(len(opt_dist), 30.0)
        opt_n = np.zeros(len(opt_dist))

        # "Actual" = same trajectory
        actual = pd.DataFrame({
            "x_m": np.linspace(0, 198, 400),
            "y_m": np.zeros(400),
            "speed_mps": np.full(400, 30.0),
        })

        delta = compute_line_delta(ff, actual, opt_dist, opt_speed, opt_n)
        np.testing.assert_allclose(delta.delta_n, 0.0, atol=0.5)
        np.testing.assert_allclose(delta.delta_speed, 0.0, atol=0.5)
        assert abs(delta.total_time_loss_s) < 0.1

    def test_known_lateral_offset(self):
        ff = _make_straight_frame()
        opt_dist = np.arange(0, 199, 1.0)
        opt_speed = np.full(len(opt_dist), 30.0)
        opt_n = np.zeros(len(opt_dist))

        # Actual: 3m to the left
        actual = pd.DataFrame({
            "x_m": np.linspace(0, 198, 400),
            "y_m": np.full(400, 3.0),
            "speed_mps": np.full(400, 30.0),
        })

        delta = compute_line_delta(ff, actual, opt_dist, opt_speed, opt_n)
        # Delta n should be ~3.0 everywhere
        mean_dn = np.mean(delta.delta_n[10:-10])
        assert abs(mean_dn - 3.0) < 0.5

    def test_slower_speed_positive_time_loss(self):
        ff = _make_straight_frame()
        opt_dist = np.arange(0, 199, 1.0)
        opt_speed = np.full(len(opt_dist), 30.0)
        opt_n = np.zeros(len(opt_dist))

        # Actual: same line but slower (25 m/s)
        actual = pd.DataFrame({
            "x_m": np.linspace(0, 198, 400),
            "y_m": np.zeros(400),
            "speed_mps": np.full(400, 25.0),
        })

        delta = compute_line_delta(ff, actual, opt_dist, opt_speed, opt_n)
        assert delta.total_time_loss_s > 0.5  # ~1.1s slower over 200m

    def test_to_dict_keys(self):
        ff = _make_straight_frame(50, 100)
        opt_dist = np.arange(0, 49, 1.0)
        opt_speed = np.full(len(opt_dist), 30.0)
        opt_n = np.zeros(len(opt_dist))
        actual = pd.DataFrame({
            "x_m": np.linspace(0, 48, 100),
            "y_m": np.zeros(100),
            "speed_mps": np.full(100, 30.0),
        })
        delta = compute_line_delta(ff, actual, opt_dist, opt_speed, opt_n)
        d = delta.to_dict()
        assert "distance_m" in d
        assert "delta_n" in d
        assert "total_time_loss_s" in d


class TestCornerDecomposition:
    def test_decomposes_with_corners(self):
        ff = _make_straight_frame()
        opt_dist = np.arange(0, 199, 1.0)
        opt_speed = np.full(len(opt_dist), 30.0)
        opt_n = np.zeros(len(opt_dist))

        actual = pd.DataFrame({
            "x_m": np.linspace(0, 198, 400),
            "y_m": np.full(400, 2.0),
            "speed_mps": np.full(400, 28.0),
        })
        delta = compute_line_delta(ff, actual, opt_dist, opt_speed, opt_n)

        corners = [{"corner_id": 1, "s_start": 50, "s_end": 100, "s_apex": 75, "direction": "R"}]
        losses = decompose_corner_losses(delta, corners, ff)
        assert len(losses) == 1
        assert losses[0].total_loss_s > 0
        assert abs(losses[0].line_loss_s + losses[0].speed_loss_s - losses[0].total_loss_s) < 0.01

    def test_skips_empty_corners(self):
        ff = _make_straight_frame(50, 100)
        delta = LineDelta(
            distance_m=np.arange(50),
            actual_n=np.zeros(50),
            optimal_n=np.zeros(50),
            delta_n=np.zeros(50),
            actual_speed=np.full(50, 30.0),
            optimal_speed=np.full(50, 30.0),
            delta_speed=np.zeros(50),
            cumulative_time_delta=np.zeros(50),
        )
        # Corner outside the distance range
        corners = [{"corner_id": 1, "s_start": 100, "s_end": 150, "s_apex": 125}]
        losses = decompose_corner_losses(delta, corners, ff)
        assert len(losses) == 0


class TestSolverBridge:
    def test_surface_to_track_model_with_defaults(self):
        surface = _make_straight_surface()
        # This will fail if lap_oracle isn't importable — that's expected
        try:
            tm = surface_to_track_model(surface)
            assert tm.centerline_xy.shape == surface.frenet.centerline_xy.shape
            assert tm.total_length_m > 0
            np.testing.assert_allclose(tm.width_left, 5.0)
        except ImportError:
            pytest.skip("lap_oracle not available")

    def test_bridge_with_none_fields(self):
        ff = _make_straight_frame(100, 200)
        surface = TrackSurface(
            track_id="t", frenet=ff, n_laps=1, sim_sources=["test"],
        )
        try:
            tm = surface_to_track_model(surface)
            # Should use defaults
            np.testing.assert_allclose(tm.width_left, 5.0)
            np.testing.assert_allclose(tm.banking, 0.0)
            np.testing.assert_allclose(tm.grip_map, 1.0)
        except ImportError:
            pytest.skip("lap_oracle not available")


class TestCoaching:
    def test_generates_apex_tip(self):
        surface = _make_straight_surface()
        losses = [CornerLineLoss(
            corner_id=1, s_start=50, s_end=100,
            total_loss_s=0.3, line_loss_s=0.2, speed_loss_s=0.1,
            apex_error_m=1.5, entry_error_m=0.3, exit_error_m=-0.5,
        )]
        coaching = generate_spatial_coaching(losses, surface)
        assert len(coaching) == 1
        assert "apex" in coaching[0]["coaching"].lower()

    def test_skips_small_losses(self):
        surface = _make_straight_surface()
        losses = [CornerLineLoss(
            corner_id=1, s_start=50, s_end=100,
            total_loss_s=0.01, line_loss_s=0.005, speed_loss_s=0.005,
            apex_error_m=0.1, entry_error_m=0.0, exit_error_m=0.0,
        )]
        coaching = generate_spatial_coaching(losses, surface)
        assert len(coaching) == 0
