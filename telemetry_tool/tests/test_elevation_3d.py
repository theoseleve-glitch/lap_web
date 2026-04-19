"""Tests for 3D elevation surface z(s,n), vertical curvature grid, and curb detection."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.elevation import (
    CurbDetection,
    ElevationSurface,
    build_elevation_surface,
    detect_curbs,
)
from track_surface.frenet import FrenetFrame


def _make_straight_frame(length: float = 200.0, n: int = 400) -> FrenetFrame:
    xy = np.column_stack([np.linspace(0, length, n), np.zeros(n)])
    return FrenetFrame.from_centerline(xy)


class TestElevationSurface:
    def test_flat_track_all_zeros(self):
        ff = _make_straight_frame()
        laps = [(ff.s_grid, np.zeros(ff.n_points), np.zeros(ff.n_points))]
        surf = build_elevation_surface(ff, laps)
        assert surf is not None
        np.testing.assert_allclose(surf.z_grid, 0.0, atol=0.01)
        np.testing.assert_allclose(surf.kv_grid, 0.0, atol=0.001)

    def test_sloped_track_preserves_gradient(self):
        ff = _make_straight_frame()
        # 5% uphill: z = 0.05 * s, slight lateral offset to land in center bins
        z = ff.s_grid * 0.05
        n = np.full(ff.n_points, 0.5)  # slightly positive to land in n=0 bin
        laps = [(ff.s_grid, n, z)]
        surf = build_elevation_surface(ff, laps)
        assert surf is not None
        # Find the column where data actually landed
        data_col = np.argmax(surf.count_grid.sum(axis=0))
        z_at_data = surf.z_grid[:, data_col]
        assert z_at_data[-1] > z_at_data[0]

    def test_dip_produces_positive_kv_at_center(self):
        """A valley in the track → positive κ_v (compression) at the bottom."""
        ff = _make_straight_frame()
        # Dip centered at s=100m
        z = -5.0 * np.exp(-((ff.s_grid - 100.0) / 20.0) ** 2)
        n = np.full(ff.n_points, 0.5)
        laps = [(ff.s_grid, n, z)]
        surf = build_elevation_surface(ff, laps)
        assert surf is not None

        data_col = np.argmax(surf.count_grid.sum(axis=0))
        idx_100 = np.argmin(np.abs(surf.s_bins - 100.0))
        # κ_v at the dip bottom should be positive
        assert surf.kv_grid[idx_100, data_col] > 0

    def test_lateral_z_variation(self):
        """Different z at different lateral offsets → crown effect."""
        ff = _make_straight_frame()
        rng = np.random.default_rng(42)
        laps = []
        # Drive at 3 different lateral offsets with different z
        for n_offset, z_offset in [(-3.0, 0.0), (0.0, 0.5), (3.0, 0.0)]:
            s = ff.s_grid.copy()
            n = np.full(ff.n_points, n_offset) + rng.normal(0, 0.1, ff.n_points)
            z = np.full(ff.n_points, z_offset)  # center is 0.5m higher
            laps.append((s, n, z))

        surf = build_elevation_surface(ff, laps, n_bin_m=2.0)
        assert surf is not None
        # The center columns should have higher z than edge columns
        center_col = len(surf.n_bins) // 2
        edge_col = 0
        mean_center = np.mean(surf.z_grid[:, center_col])
        mean_edge = np.mean(surf.z_grid[:, edge_col])
        assert mean_center > mean_edge

    def test_z_at_interpolates(self):
        ff = _make_straight_frame(100, 200)
        z = np.full(ff.n_points, 42.0)
        n = np.full(ff.n_points, 0.5)  # land in center bin
        laps = [(ff.s_grid, n, z)]
        surf = build_elevation_surface(ff, laps)
        assert surf is not None
        # After lateral gap-fill, z=42 should propagate across the grid
        assert abs(surf.z_at(50.0, 0.5) - 42.0) < 1.0

    def test_kv_at_interpolates(self):
        ff = _make_straight_frame()
        z = np.zeros(ff.n_points)  # flat
        laps = [(ff.s_grid, np.zeros(ff.n_points), z)]
        surf = build_elevation_surface(ff, laps)
        assert surf is not None
        assert abs(surf.kv_at(50.0, 0.0)) < 0.01

    def test_to_mesh_returns_3d_points(self):
        ff = _make_straight_frame(100, 200)
        z = np.full(ff.n_points, 5.0)
        laps = [(ff.s_grid, np.zeros(ff.n_points), z)]
        surf = build_elevation_surface(ff, laps, s_bin_m=10.0, n_bin_m=2.0)
        assert surf is not None
        mesh = surf.to_mesh(ff)
        assert mesh.shape[1] == 3  # (N, 3) = x, y, z
        assert mesh.shape[0] == surf.z_grid.shape[0] * surf.z_grid.shape[1]

    def test_returns_none_with_no_data(self):
        ff = _make_straight_frame()
        assert build_elevation_surface(ff, []) is None


class TestCurbDetection:
    def test_detects_raised_curb_at_edge(self):
        """Raised curb: direct ElevationSurface with known edge z-spike."""
        # Construct a surface directly with a curb at the left edge
        M, K = 40, 10
        s_bins = np.arange(0, 200, 5.0)[:M]
        n_bins = np.linspace(-5, 5, K)

        z_grid = np.zeros((M, K))
        count_grid = np.full((M, K), 10, dtype=int)

        # Raised curb on left edge (column K-1) between s=50-80m
        for i in range(M):
            s = s_bins[i]
            if 50 <= s <= 80:
                z_grid[i, K - 1] = 0.08  # 8cm raised curb at edge
                z_grid[i, K - 2] = 0.02  # slight rise at adjacent

        kv_grid = np.zeros((M, K))
        confidence = np.ones((M, K))

        surf = ElevationSurface(
            s_bins=s_bins, n_bins=n_bins,
            z_grid=z_grid, kv_grid=kv_grid,
            count_grid=count_grid, confidence=confidence,
        )
        curbs = detect_curbs(surf, z_threshold_m=0.03)
        left_curbs = [c for c in curbs if c.side == "left"]
        assert len(left_curbs) >= 1
        assert left_curbs[0].is_raised
        assert left_curbs[0].height_m > 0.03

    def test_no_curbs_on_flat_track(self):
        ff = _make_straight_frame()
        z = np.zeros(ff.n_points)
        laps = [(ff.s_grid, np.zeros(ff.n_points), z)]
        surf = build_elevation_surface(ff, laps)
        assert surf is not None
        curbs = detect_curbs(surf)
        assert len(curbs) == 0

    def test_curb_to_dict(self):
        curb = CurbDetection(
            s_center=75.0, n_position=6.0, side="left",
            height_m=0.05, length_m=30.0, is_raised=True,
        )
        d = curb.to_dict()
        assert d["side"] == "left"
        assert d["is_raised"] is True
        assert d["height_m"] == 0.05


class TestBuilderIntegration:
    def test_builder_populates_elevation_3d(self):
        """The builder should create an elevation_surface with >= 3 laps and z-data."""
        import pandas as pd
        from track_surface.builder import build_track_surface

        def _make_df(offset_m=0.0):
            n = 400
            t = np.linspace(0, 2 * np.pi, n, endpoint=False)
            x = 50 * np.cos(t)
            y = 50 * np.sin(t) + offset_m
            z = np.sin(t) * 3.0  # 3m elevation variation
            dist = np.concatenate([[0], np.cumsum(np.sqrt(np.diff(x)**2 + np.diff(y)**2))])
            return pd.DataFrame({
                "pos_x_m": x, "pos_y_m": y, "pos_z_m": z,
                "speed_mps": np.full(n, 25.0),
                "accel_lat_mps2": np.full(n, 9.81),
                "distance_m": dist, "time_s": np.linspace(0, 10, n),
            })

        laps = {1: _make_df(0.0), 2: _make_df(1.0), 3: _make_df(-1.0)}
        surface = build_track_surface(laps, "test_3d", "ac")
        assert surface.has_elevation_3d
        assert surface.elevation_surface is not None

    def test_builder_summary_includes_3d_fields(self):
        import pandas as pd
        from track_surface.builder import build_track_surface

        def _make_df():
            n = 300
            x = np.linspace(0, 200, n)
            y = np.zeros(n)
            return pd.DataFrame({
                "pos_x_m": x, "pos_y_m": y, "pos_z_m": np.sin(x / 30) * 2,
                "speed_mps": np.full(n, 20.0),
                "accel_lat_mps2": np.full(n, 5.0),
                "distance_m": x, "time_s": np.linspace(0, 10, n),
            })

        laps = {1: _make_df(), 2: _make_df(), 3: _make_df()}
        surface = build_track_surface(laps, "test_summary", "ac")
        d = surface.to_summary_dict()
        assert "has_elevation_3d" in d
        assert "has_curbs" in d
        assert "n_curbs" in d
