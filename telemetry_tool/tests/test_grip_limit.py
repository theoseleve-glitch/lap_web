# telemetry_tool/tests/test_grip_limit.py
"""Tests for the 2D grip-surface cornering-LIMIT grid (per-session p90, MAX-merge)."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.grip_2d import GripSurface


def _empty_grids(M=10, K=5):
    s_bins = np.arange(0, M * 5.0, 5.0)
    n_bins = np.arange(-(K // 2), K // 2 + 1, 1.0)
    mu = np.ones((M, K))
    count = np.zeros((M, K), dtype=int)
    conf = np.zeros((M, K))
    return s_bins, n_bins, mu, count, conf


def test_gripsurface_limit_grid_defaults_none():
    s_bins, n_bins, mu, count, conf = _empty_grids()
    gs = GripSurface(s_bins=s_bins, n_bins=n_bins, mu_grid=mu,
                     count_grid=count, confidence=conf)
    assert gs.mu_limit_grid is None


def test_gripsurface_accepts_limit_grid():
    s_bins, n_bins, mu, count, conf = _empty_grids()
    lim = np.full(mu.shape, np.nan)
    lim[3, 2] = 1.35
    gs = GripSurface(s_bins=s_bins, n_bins=n_bins, mu_grid=mu,
                     count_grid=count, confidence=conf, mu_limit_grid=lim)
    assert gs.mu_limit_grid is not None
    assert gs.mu_limit_grid[3, 2] == pytest.approx(1.35)
    assert np.isnan(gs.mu_limit_grid[0, 0])


# append to telemetry_tool/tests/test_grip_limit.py
import pandas as pd
from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import build_grip_surface, _MIN_LIMIT_SAMPLES, _LIMIT_PERCENTILE


def _straight_frenet(length_m=200.0, n=400):
    xy = np.column_stack((np.linspace(0, length_m, n), np.zeros(n)))
    return FrenetFrame.from_centerline(xy)


def _lap_df(frenet, *, n_offset=0.0, a_lat_g, speed_mps=30.0, n_samples=120):
    """One synthetic lap: constant lateral accel a_lat_g (in g) at a fixed
    lateral offset, straight-line geometry so s spans the track."""
    x = np.linspace(2.0, frenet.total_length_m - 2.0, n_samples)
    y = np.full(n_samples, n_offset)
    return pd.DataFrame({
        "pos_x_m": x, "pos_y_m": y,
        "Speed (m/s)": np.full(n_samples, speed_mps),
        "accel_lat_mps2": np.full(n_samples, a_lat_g * 9.80665),
    })


def _best_sampled_finite_cell(gs):
    """Return (si, ni) of the cell with the most samples that has a finite limit.
    Uses the entire 2D grid so cell-index arithmetic in the test is bin-agnostic."""
    mask = np.where(np.isfinite(gs.mu_limit_grid), gs.count_grid, -1)
    return np.unravel_index(int(np.nanargmax(mask)), mask.shape)


def test_limit_grid_recovers_cornering_limit_not_mean():
    """A cell driven mostly near the limit but with some low-load samples:
    the limit grid must report ~the high quantile, NOT the mean."""
    frenet = _straight_frenet()
    laps = [_lap_df(frenet, a_lat_g=1.3) for _ in range(9)] + \
           [_lap_df(frenet, a_lat_g=0.3) for _ in range(3)]
    gs = build_grip_surface(frenet, laps)
    assert gs is not None and gs.mu_limit_grid is not None
    si, ni = _best_sampled_finite_cell(gs)
    mean_here = gs.mu_grid[si, ni]
    limit_here = gs.mu_limit_grid[si, ni]
    assert mean_here < 1.15
    assert limit_here > 1.2
    assert limit_here > mean_here + 0.1


def test_limit_grid_nan_below_sample_floor():
    """Cells with < _MIN_LIMIT_SAMPLES samples get NaN, not a noisy p90.
    Uses 10 laps (>= _MIN_LAPS) but very sparse samples so most cells have
    fewer than _MIN_LIMIT_SAMPLES hits and must stay NaN."""
    frenet = _straight_frenet()
    laps = [_lap_df(frenet, a_lat_g=1.2, n_samples=4) for _ in range(10)]
    gs = build_grip_surface(frenet, laps)
    assert gs is not None and gs.mu_limit_grid is not None
    assert np.isnan(gs.mu_limit_grid).any()
    finite = np.isfinite(gs.mu_limit_grid)
    assert np.all(gs.count_grid[finite] >= _MIN_LIMIT_SAMPLES)


def test_mean_grid_unchanged_by_limit_addition():
    """Regression lock: adding the limit must not perturb the mean grid."""
    frenet = _straight_frenet()
    laps = [_lap_df(frenet, a_lat_g=1.0) for _ in range(12)]
    gs = build_grip_surface(frenet, laps)
    # Pick a well-sampled cell from the n column where samples actually land
    ni = int(np.argmax(gs.count_grid.sum(axis=0)))
    si = int(gs.count_grid.shape[0] // 2)
    assert gs.mu_grid[si, ni] == pytest.approx(1.0, abs=0.05)
