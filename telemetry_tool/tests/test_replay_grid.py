"""Tests for build_master_grid, align_to_grid, event_to_grid_index."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.resampling import (
    _COL_DIST,
    align_to_grid,
    build_master_grid,
    event_to_grid_index,
)


# ---------------------------------------------------------------------------
# build_master_grid
# ---------------------------------------------------------------------------


def _make_lap_df(max_dist: float, n: int = 100) -> pd.DataFrame:
    """Helper: minimal resampled lap DataFrame with Distance (m)."""
    return pd.DataFrame({_COL_DIST: np.linspace(0, max_dist, n)})


class TestBuildMasterGrid:
    def test_returns_n_points(self):
        laps = {1: _make_lap_df(500), 2: _make_lap_df(600)}
        grid = build_master_grid(laps, n_points=200)
        assert len(grid) == 200

    def test_range_from_median(self):
        laps = {
            1: _make_lap_df(400),
            2: _make_lap_df(600),
            3: _make_lap_df(800),
        }
        grid = build_master_grid(laps, n_points=500)
        # Median of [400, 600, 800] == 600
        np.testing.assert_allclose(grid[-1], 600.0, atol=1e-9)

    def test_empty_laps_returns_default(self):
        grid = build_master_grid({}, n_points=1000)
        assert len(grid) == 1000
        np.testing.assert_allclose(grid[0], 0.0)
        np.testing.assert_allclose(grid[-1], 1000.0)


# ---------------------------------------------------------------------------
# align_to_grid
# ---------------------------------------------------------------------------


class TestAlignToGrid:
    def test_identity_alignment(self):
        grid = np.linspace(0, 100, 50)
        data = np.sin(grid)
        result = align_to_grid(data, grid, grid)
        np.testing.assert_allclose(result, data, atol=1e-12)

    def test_interpolation(self):
        data_dist = np.array([0.0, 10.0])
        data = np.array([0.0, 100.0])
        master = np.array([5.0])
        result = align_to_grid(data, data_dist, master)
        np.testing.assert_allclose(result, [50.0], atol=1e-9)


# ---------------------------------------------------------------------------
# event_to_grid_index
# ---------------------------------------------------------------------------


class TestEventToGridIndex:
    def test_exact_match(self):
        grid = np.linspace(0, 100, 101)  # 0, 1, 2, ..., 100
        assert event_to_grid_index(50.0, grid) == 50

    def test_nearest(self):
        grid = np.linspace(0, 100, 11)  # 0, 10, 20, ..., 100
        # 23.0 is closer to 20 (idx 2) than 30 (idx 3)
        assert event_to_grid_index(23.0, grid) == 2
        # 27.0 is closer to 30 (idx 3) than 20 (idx 2)
        assert event_to_grid_index(27.0, grid) == 3

    def test_out_of_range_clamps(self):
        grid = np.linspace(0, 100, 101)
        assert event_to_grid_index(-50.0, grid) == 0
        assert event_to_grid_index(999.0, grid) == 100
