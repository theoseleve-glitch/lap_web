"""Tests for mu_field: confidence shrinkage + dry/wet MuField builders.

No casadi needed — pure numpy.
"""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.drainage import PuddleZone
from track_surface.grip_2d import GripSurface
from track_surface.mu_field import build_dry_mu_field, build_wet_mu_field, shrink_mu_grid


def _grids(M=20, K=9):
    s_bins = np.arange(0, M * 5.0, 5.0)
    n_bins = np.arange(-(K // 2), K // 2 + 1, 1.0)
    return s_bins, n_bins


def test_high_confidence_cells_stay_raw():
    s_bins, n_bins = _grids()
    mu = np.full((len(s_bins), len(n_bins)), 1.3)
    count = np.full(mu.shape, 100, dtype=int)       # conf = 1.0
    conf = np.ones(mu.shape)
    out = shrink_mu_grid(mu, count, conf)
    np.testing.assert_allclose(out, mu)


def test_low_confidence_shrinks_toward_row_prior():
    s_bins, n_bins = _grids()
    M, K = len(s_bins), len(n_bins)
    mu = np.full((M, K), 1.0)
    count = np.full((M, K), 50, dtype=int)
    conf = np.ones((M, K))
    # One noisy outlier cell with a single sample claiming huge grip
    mu[5, 2] = 2.5
    count[5, 2] = 1
    conf[5, 2] = 1 / 50.0
    out = shrink_mu_grid(mu, count, conf)
    # Row prior is ~1.0 (count-weighted), so the outlier collapses near 1.0
    assert out[5, 2] < 1.1
    # ...and is strictly below the raw claim
    assert out[5, 2] < 2.5


def test_unmeasured_cells_get_pessimistic_prior():
    s_bins, n_bins = _grids()
    M, K = len(s_bins), len(n_bins)
    mu = np.full((M, K), 1.2)
    count = np.full((M, K), 50, dtype=int)
    conf = np.ones((M, K))
    mu[3, 0] = 1.0   # grip_2d defaults unmeasured cells to 1.0
    count[3, 0] = 0
    conf[3, 0] = 0.0
    out = shrink_mu_grid(mu, count, conf)
    row_prior = 1.2  # all measured neighbours
    assert out[3, 0] == pytest.approx(row_prior * 0.95, rel=1e-6)
    # Strictly below the prior — never optimistic about undriven asphalt
    assert out[3, 0] < row_prior


def test_fully_unmeasured_row_falls_back_to_global_prior():
    s_bins, n_bins = _grids()
    M, K = len(s_bins), len(n_bins)
    mu = np.full((M, K), 1.4)
    count = np.full((M, K), 50, dtype=int)
    conf = np.ones((M, K))
    mu[7, :] = 1.0
    count[7, :] = 0
    conf[7, :] = 0.0
    out = shrink_mu_grid(mu, count, conf)
    # Global measured mean is 1.4 → row 7 = 1.4 * 0.95
    np.testing.assert_allclose(out[7, :], 1.4 * 0.95, rtol=1e-6)


def test_never_exceeds_max_of_raw_and_prior():
    rng = np.random.default_rng(7)
    s_bins, n_bins = _grids()
    M, K = len(s_bins), len(n_bins)
    mu = 0.7 + rng.random((M, K))
    count = rng.integers(0, 80, size=(M, K))
    conf = np.clip(count / 50.0, 0.0, 1.0)
    out = shrink_mu_grid(mu, count, conf)
    measured = count > 0

    # Independently recompute the row prior (count-weighted mean of measured
    # cells per row, global measured mean as fallback) so this test can FAIL
    # if the implementation ever invents grip.
    global_prior = np.average(mu[measured], weights=count[measured])
    row_prior = np.full(M, global_prior)
    for i in range(M):
        if measured[i].any():
            row_prior[i] = np.average(mu[i, measured[i]], weights=count[i, measured[i]])

    # Measured cells: bounded by max(raw, row prior) — a 5x-inflation mutant fails this
    assert np.all(out[measured] <= np.maximum(mu, row_prior[:, None])[measured] + 1e-9)
    # Unmeasured cells: exactly the discounted prior
    if (~measured).any():
        expected_unmeasured = np.broadcast_to(row_prior[:, None] * 0.95, (M, K))
        np.testing.assert_allclose(out[~measured], expected_unmeasured[~measured], rtol=1e-9)
    assert out.shape == mu.shape


# ---------------------------------------------------------------------------
# Task 3: dry + wet MuField builders
# ---------------------------------------------------------------------------
def _grip_surface_with_rubber_line(M=40, K=17) -> GripSurface:
    """Synthetic dry grip: a high-mu 'rubber line' ridge at n = +2."""
    s_bins = np.arange(0, M * 5.0, 5.0)
    n_bins = np.arange(-8.0, 9.0, 1.0)
    mu = np.full((M, K), 1.0)
    ridge_col = int(np.argmin(np.abs(n_bins - 2.0)))
    mu[:, ridge_col] = 1.4                       # rubbered-in line
    count = np.full((M, K), 60, dtype=int)
    return GripSurface(
        s_bins=s_bins, n_bins=n_bins, mu_grid=mu,
        count_grid=count, confidence=np.ones((M, K)),
    )


def test_build_dry_mu_field_applies_shrinkage_and_shapes():
    gs = _grip_surface_with_rubber_line()
    field = build_dry_mu_field(gs)
    assert field.mu_grid.shape == gs.mu_grid.shape
    np.testing.assert_array_equal(field.s_bins, gs.s_bins)
    np.testing.assert_array_equal(field.n_bins, gs.n_bins)
    # Full-confidence input → dry field equals raw grid
    np.testing.assert_allclose(field.mu_grid, gs.mu_grid)


def test_wet_field_penalizes_rubber_line():
    gs = _grip_surface_with_rubber_line()
    wet = build_wet_mu_field(gs, puddles=[])
    ridge_col = int(np.argmin(np.abs(gs.n_bins - 2.0)))
    clean_col = int(np.argmin(np.abs(gs.n_bins + 4.0)))
    # In the wet, the rubber line must grip WORSE than clean asphalt
    assert wet.mu_grid[:, ridge_col].mean() < wet.mu_grid[:, clean_col].mean()
    # Bounded like invert_grip_for_wet
    assert wet.mu_grid.min() >= 0.2 - 1e-9
    assert wet.mu_grid.max() <= 1.0 + 1e-9


def test_wet_field_clamps_puddle_cells():
    gs = _grip_surface_with_rubber_line()
    puddle = PuddleZone(s_center=100.0, n_center=-2.0, depth_score=0.8, area_cells=6)
    wet = build_wet_mu_field(gs, puddles=[puddle])
    si = int(np.argmin(np.abs(gs.s_bins - 100.0)))
    ni = int(np.argmin(np.abs(gs.n_bins + 2.0)))
    assert wet.mu_grid[si, ni] == pytest.approx(0.2)
    # Just OUTSIDE the footprint radius (~3.09 m): cell at (100, +2) is 4 m
    # from center and must be untouched — pins the boundary, not just far field
    wet_nopuddle = build_wet_mu_field(gs, puddles=[])
    nj_out = int(np.argmin(np.abs(gs.n_bins - 2.0)))
    assert wet.mu_grid[si, nj_out] == pytest.approx(wet_nopuddle.mu_grid[si, nj_out])


def test_wet_field_never_below_wet_floor_even_with_unmeasured_cells():
    """Review carry-forward: shrinkage can emit row_prior*0.95 < 0.2 when a
    row's wet prior sits at the 0.2 floor — the builder must re-clip."""
    gs = _grip_surface_with_rubber_line()
    # Make one row fully rubbered (wet prior at the floor) with one unmeasured cell
    gs.mu_grid[10, :] = 1.4
    gs.count_grid[10, 5] = 0
    gs.confidence[10, 5] = 0.0
    wet = build_wet_mu_field(gs, puddles=[])
    assert wet.mu_grid.min() >= 0.2 - 1e-9


def test_puddle_outside_n_range_is_noop():
    """A puddle centered far off the drivable n-range must not affect the
    grid — guards against a future 'snap to nearest bin' regression."""
    gs = _grip_surface_with_rubber_line()
    off_grid = PuddleZone(s_center=100.0, n_center=50.0, depth_score=0.9, area_cells=6)
    wet = build_wet_mu_field(gs, puddles=[off_grid])
    wet_nopuddle = build_wet_mu_field(gs, puddles=[])
    np.testing.assert_allclose(wet.mu_grid, wet_nopuddle.mu_grid)
