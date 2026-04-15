"""Tests for track_surface.drainage — water drainage / puddle detection."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.drainage import PuddleZone, compute_drainage
from track_surface.elevation import ElevationSurface


def _make_flat_surface(M=20, K=10, s_len=100.0, n_range=5.0):
    """Build a flat ElevationSurface (z = 0 everywhere)."""
    s_bins = np.linspace(0, s_len, M)
    n_bins = np.linspace(-n_range, n_range, K)
    z_grid = np.zeros((M, K))
    return ElevationSurface(
        s_bins=s_bins,
        n_bins=n_bins,
        z_grid=z_grid,
        kv_grid=np.zeros((M, K)),
        count_grid=np.ones((M, K), dtype=int) * 10,
        confidence=np.ones((M, K)),
    )


def _make_surface_with_dip(
    M=20, K=10, s_len=100.0, n_range=5.0,
    dip_si=10, dip_nj=5, dip_depth=0.5,
):
    """Build an ElevationSurface with a known dip at (dip_si, dip_nj)."""
    s_bins = np.linspace(0, s_len, M)
    n_bins = np.linspace(-n_range, n_range, K)
    # Slight upward slope so there's gradient towards edges
    z_grid = np.ones((M, K)) * 1.0
    # Create a dip: lower z at the target cell and its neighbours
    for di in range(-1, 2):
        for dj in range(-1, 2):
            si = dip_si + di
            nj = dip_nj + dj
            if 0 <= si < M and 0 <= nj < K:
                dist = abs(di) + abs(dj)
                z_grid[si, nj] = 1.0 - dip_depth * (1.0 - 0.3 * dist)
    return ElevationSurface(
        s_bins=s_bins,
        n_bins=n_bins,
        z_grid=z_grid,
        kv_grid=np.zeros((M, K)),
        count_grid=np.ones((M, K), dtype=int) * 10,
        confidence=np.ones((M, K)),
    )


class TestPuddleZone:
    def test_to_dict_fields(self):
        pz = PuddleZone(s_center=123.4, n_center=-2.56, depth_score=0.789, area_cells=15)
        d = pz.to_dict()
        assert d["s_center"] == 123.4
        assert d["n_center"] == -2.56
        assert d["depth_score"] == 0.789
        assert d["area_cells"] == 15

    def test_to_dict_rounding(self):
        pz = PuddleZone(s_center=1.23456, n_center=-0.12345, depth_score=0.12345, area_cells=3)
        d = pz.to_dict()
        assert d["s_center"] == 1.2
        assert d["n_center"] == -0.12
        assert d["depth_score"] == 0.123


class TestComputeDrainage:
    def test_flat_surface_no_puddles(self):
        """A perfectly flat surface should produce no puddles with depth."""
        surf = _make_flat_surface()
        puddles = compute_drainage(surf)
        # Flat surface: no z-range -> no puddles
        assert puddles == []

    def test_known_dip_found(self):
        """A surface with a single known dip should detect a puddle there."""
        dip_si, dip_nj = 10, 5
        surf = _make_surface_with_dip(dip_si=dip_si, dip_nj=dip_nj, dip_depth=0.5)
        puddles = compute_drainage(surf)
        assert len(puddles) >= 1
        # The deepest puddle should be near the dip location
        top = puddles[0]
        assert top.depth_score > 0
        expected_s = float(surf.s_bins[dip_si])
        expected_n = float(surf.n_bins[dip_nj])
        assert abs(top.s_center - expected_s) <= float(np.ptp(surf.s_bins))
        assert abs(top.n_center - expected_n) <= float(np.ptp(surf.n_bins))

    def test_sorted_by_depth_descending(self):
        """Puddles should be sorted by depth_score descending."""
        surf = _make_surface_with_dip(dip_si=10, dip_nj=5, dip_depth=0.5)
        puddles = compute_drainage(surf)
        for i in range(len(puddles) - 1):
            assert puddles[i].depth_score >= puddles[i + 1].depth_score

    def test_small_grid_returns_empty(self):
        """Grids smaller than 3x3 should return empty."""
        s_bins = np.array([0.0, 5.0])
        n_bins = np.array([-1.0, 1.0])
        z_grid = np.array([[1.0, 1.0], [0.5, 0.5]])
        surf = ElevationSurface(
            s_bins=s_bins, n_bins=n_bins, z_grid=z_grid,
            kv_grid=np.zeros((2, 2)), count_grid=np.ones((2, 2), dtype=int),
            confidence=np.ones((2, 2)),
        )
        assert compute_drainage(surf) == []

    def test_depth_score_bounded_zero_one(self):
        """All depth_score values should be in [0, 1]."""
        surf = _make_surface_with_dip(dip_si=10, dip_nj=5, dip_depth=0.8)
        puddles = compute_drainage(surf)
        for p in puddles:
            assert 0.0 <= p.depth_score <= 1.0

    def test_area_cells_positive(self):
        """All puddle zones should have at least 2 cells."""
        surf = _make_surface_with_dip(dip_si=10, dip_nj=5, dip_depth=0.3)
        puddles = compute_drainage(surf)
        for p in puddles:
            assert p.area_cells >= 2

    def test_multiple_dips(self):
        """Surface with two dips should detect at least two basins."""
        M, K = 30, 10
        s_bins = np.linspace(0, 150, M)
        n_bins = np.linspace(-5, 5, K)
        z_grid = np.ones((M, K)) * 2.0
        # Dip 1 at (5, 3)
        z_grid[5, 3] = 0.5
        z_grid[4, 3] = 1.0
        z_grid[6, 3] = 1.0
        z_grid[5, 2] = 1.0
        z_grid[5, 4] = 1.0
        # Dip 2 at (20, 7)
        z_grid[20, 7] = 0.3
        z_grid[19, 7] = 1.0
        z_grid[21, 7] = 1.0
        z_grid[20, 6] = 1.0
        z_grid[20, 8] = 1.0

        surf = ElevationSurface(
            s_bins=s_bins, n_bins=n_bins, z_grid=z_grid,
            kv_grid=np.zeros((M, K)), count_grid=np.ones((M, K), dtype=int) * 10,
            confidence=np.ones((M, K)),
        )
        puddles = compute_drainage(surf)
        # Should detect basins around both dips
        assert len(puddles) >= 2
