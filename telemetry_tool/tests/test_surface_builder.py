"""Tests for track_surface/builder.py and surface property modules."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from track_surface.boundary import estimate_boundaries
from track_surface.builder import build_track_surface
from track_surface.centerline import extract_centerline
from track_surface.elevation import build_elevation_profile, estimate_camber
from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import GripSurface, build_grip_surface
from track_surface.model import TrackSurface


def _make_oval_df(
    straight_len: float = 100.0,
    radius: float = 30.0,
    n_points: int = 400,
    offset_m: float = 0.0,
    elevation_slope: float = 0.0,
    lateral_g: float = 1.0,
) -> pd.DataFrame:
    """Generate a synthetic oval session DataFrame with canonical columns."""
    pts_x = []
    pts_y = []

    # Bottom straight
    n_straight = n_points // 4
    for i in range(n_straight):
        t = i / n_straight
        pts_x.append(t * straight_len)
        pts_y.append(offset_m)

    # Right semicircle
    n_arc = n_points // 4
    for i in range(n_arc):
        theta = -np.pi / 2 + np.pi * i / n_arc
        pts_x.append(straight_len + radius * np.cos(theta))
        pts_y.append(radius + radius * np.sin(theta) + offset_m)

    # Top straight
    for i in range(n_straight):
        t = i / n_straight
        pts_x.append(straight_len - t * straight_len)
        pts_y.append(2 * radius + offset_m)

    # Left semicircle
    for i in range(n_arc):
        theta = np.pi / 2 + np.pi * i / n_arc
        pts_x.append(radius * np.cos(theta))
        pts_y.append(radius + radius * np.sin(theta) + offset_m)

    x = np.array(pts_x)
    y = np.array(pts_y)
    n = len(x)

    # Compute distance
    diffs = np.sqrt(np.diff(x) ** 2 + np.diff(y) ** 2)
    dist = np.concatenate([[0], np.cumsum(diffs)])

    # Elevation with optional slope
    z = dist * elevation_slope

    speed = np.full(n, 25.0)  # 25 m/s
    a_lat = np.full(n, lateral_g * 9.80665)  # ~1G lateral

    return pd.DataFrame({
        "pos_x_m": x,
        "pos_y_m": y,
        "pos_z_m": z,
        "speed_mps": speed,
        "accel_lat_mps2": a_lat,
        "accel_long_mps2": np.zeros(n),
        "distance_m": dist,
        "time_s": np.linspace(0, dist[-1] / 25.0, n),
        "throttle_pct": np.full(n, 50.0),
        "brake_pct": np.zeros(n),
        "lap_number": np.ones(n),
    })


class TestBoundary:
    def test_returns_none_with_few_laps(self):
        cl = np.column_stack([np.linspace(0, 100, 200), np.zeros(200)])
        ff = FrenetFrame.from_centerline(cl)
        laps_sn = [(ff.s_grid, np.zeros(len(ff.s_grid)))]
        assert estimate_boundaries(ff, laps_sn, min_laps=3) is None

    def test_returns_widths_with_enough_laps(self):
        cl = np.column_stack([np.linspace(0, 100, 200), np.zeros(200)])
        ff = FrenetFrame.from_centerline(cl)
        rng = np.random.default_rng(0)
        laps_sn = []
        for _ in range(5):
            s = ff.s_grid.copy()
            n = rng.normal(0, 2.0, len(s))
            laps_sn.append((s, n))

        result = estimate_boundaries(ff, laps_sn, min_laps=3)
        assert result is not None
        wl, wr = result
        assert len(wl) == ff.n_points
        assert np.all(wl > 0)
        assert np.all(wr > 0)


class TestElevation:
    def test_flat_track_near_zero(self):
        cl = np.column_stack([np.linspace(0, 100, 200), np.zeros(200)])
        ff = FrenetFrame.from_centerline(cl)
        laps_sz = [(ff.s_grid, np.zeros(len(ff.s_grid)))]
        elev, slope = build_elevation_profile(ff, laps_sz)
        np.testing.assert_allclose(elev, 0.0, atol=0.01)
        np.testing.assert_allclose(slope, 0.0, atol=0.1)

    def test_sloped_track(self):
        cl = np.column_stack([np.linspace(0, 100, 200), np.zeros(200)])
        ff = FrenetFrame.from_centerline(cl)
        # 5% uphill slope: z = 0.05 * s
        z = ff.s_grid * 0.05
        laps_sz = [(ff.s_grid, z)]
        elev, slope = build_elevation_profile(ff, laps_sz)
        # Elevation should follow the slope
        assert elev[-1] > elev[0]
        # Slope should be ~5%
        mean_slope = np.mean(slope[10:-10])
        assert abs(mean_slope - 5.0) < 1.0


class TestCamber:
    def test_no_lateral_spread_returns_zeros(self):
        cl = np.column_stack([np.linspace(0, 100, 200), np.zeros(200)])
        ff = FrenetFrame.from_centerline(cl)
        # All samples at n=0
        laps = [(ff.s_grid, np.zeros(len(ff.s_grid)), np.zeros(len(ff.s_grid)))]
        result = estimate_camber(ff, laps)
        np.testing.assert_allclose(result, 0.0, atol=0.01)


class TestGripSurface:
    def test_mu_at_default_for_empty(self):
        gs = GripSurface(
            s_bins=np.array([]),
            n_bins=np.array([]),
            mu_grid=np.array([]).reshape(0, 0),
            count_grid=np.array([]).reshape(0, 0),
            confidence=np.array([]).reshape(0, 0),
        )
        assert gs.mu_at(50.0, 0.0) == 1.0

    def test_centerline_slice(self):
        s = np.arange(0, 100, 5.0)
        n = np.array([-2, -1, 0, 1, 2.0])
        mu = np.ones((len(s), len(n))) * 1.2
        gs = GripSurface(s, n, mu, np.ones_like(mu, dtype=int), np.ones_like(mu))
        cl = gs.centerline_slice()
        np.testing.assert_allclose(cl, 1.2, atol=0.01)


class TestVerticalCurvature:
    def test_compression_computed_from_elevation(self):
        """A dip in the track should produce positive vertical curvature."""
        from track_surface.elevation import build_elevation_profile, compute_vertical_curvature

        cl = np.column_stack([np.linspace(0, 200, 400), np.zeros(400)])
        ff = FrenetFrame.from_centerline(cl)

        # Elevation: flat → dip at 100m → flat
        # z = -5 * exp(-((s - 100) / 20)^2)  (5m deep dip, 20m wide)
        z = -5.0 * np.exp(-((ff.s_grid - 100.0) / 20.0) ** 2)
        laps_sz = [(ff.s_grid, z)]
        elev, _ = build_elevation_profile(ff, laps_sz)
        kv = compute_vertical_curvature(elev, ff.s_grid)

        # At the bottom of the dip (s=100m), kv should be positive (compression)
        idx_center = np.argmin(np.abs(ff.s_grid - 100.0))
        assert kv[idx_center] > 0, "Compression at dip bottom should be positive kv"

        # On the shoulders (s=70, s=130), kv should be negative (crest-like transition)
        idx_shoulder = np.argmin(np.abs(ff.s_grid - 70.0))
        assert kv[idx_shoulder] < kv[idx_center], "Shoulder should have less kv than dip bottom"

    def test_flat_track_zero_vert_curvature(self):
        from track_surface.elevation import build_elevation_profile, compute_vertical_curvature

        cl = np.column_stack([np.linspace(0, 200, 400), np.zeros(400)])
        ff = FrenetFrame.from_centerline(cl)
        z = np.zeros(len(ff.s_grid))
        laps_sz = [(ff.s_grid, z)]
        elev, _ = build_elevation_profile(ff, laps_sz)
        kv = compute_vertical_curvature(elev, ff.s_grid)
        np.testing.assert_allclose(kv, 0.0, atol=0.001)

    def test_compression_increases_effective_grip(self):
        """Compression zone should produce grip > 1.0 in the builder output."""
        # Single lap with a dip in the elevation — at 200m mark
        df = _make_oval_df(elevation_slope=0.0)
        # Inject a dip in the elevation
        dist = df["distance_m"].to_numpy()
        dip_center = np.median(dist)
        z = -3.0 * np.exp(-((dist - dip_center) / 15.0) ** 2)
        df["pos_z_m"] = z

        laps = {1: df}
        surface = build_track_surface(laps, "test_track", "ac")

        # Vertical curvature should exist and have positive values at the dip
        assert surface.has_vert_curvature
        assert np.max(surface.vert_curvature_1pm) > 0


class TestBuildTrackSurface:
    def test_single_lap_bronze(self):
        laps = {1: _make_oval_df()}
        surface = build_track_surface(laps, "test_track", "ac")
        assert surface.quality_tier == "bronze"
        assert surface.frenet.total_length_m > 100
        assert not surface.has_boundaries
        assert surface.n_laps == 1

    def test_three_laps_silver(self):
        laps = {
            1: _make_oval_df(offset_m=-1.0),
            2: _make_oval_df(offset_m=0.0),
            3: _make_oval_df(offset_m=1.0),
        }
        surface = build_track_surface(laps, "test_track", "ac")
        assert surface.quality_tier == "silver"
        assert surface.has_boundaries

    def test_with_elevation(self):
        laps = {1: _make_oval_df(elevation_slope=0.05)}
        surface = build_track_surface(laps, "test_track", "ac")
        assert surface.has_elevation
        assert surface.elevation_m[-1] > surface.elevation_m[0]

    def test_summary_dict(self):
        laps = {1: _make_oval_df()}
        surface = build_track_surface(laps, "test_track", "ac")
        d = surface.to_summary_dict()
        assert d["track_id"] == "test_track"
        assert d["quality_tier"] == "bronze"
        assert d["n_laps"] == 1
        assert d["total_length_m"] > 100

    def test_no_valid_laps_raises(self):
        laps = {1: pd.DataFrame({"a": [1, 2, 3]})}
        with pytest.raises(ValueError, match="No valid laps"):
            build_track_surface(laps, "test", "ac")
