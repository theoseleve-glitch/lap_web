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
