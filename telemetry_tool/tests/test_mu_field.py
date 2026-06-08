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


# ---------------------------------------------------------------------------
# Task 6: solve_optimal_line_2d bridge + puddles_to_n_windows
# ---------------------------------------------------------------------------
from track_surface.frenet import FrenetFrame
from track_surface.model import TrackSurface


def _synthetic_surface_with_grip(n_pts: int = 200) -> TrackSurface:
    """Oval TrackSurface with boundaries + a rubber-line GripSurface."""
    t = np.linspace(0, 2 * np.pi, n_pts, endpoint=False)
    a, b = 200.0, 100.0
    xy = np.column_stack((a * np.cos(t), b * np.sin(t)))
    frenet = FrenetFrame.from_centerline(xy)

    s_bins = np.arange(0, frenet.total_length_m, 5.0)
    n_bins = np.arange(-8.0, 9.0, 1.0)
    M, K = len(s_bins), len(n_bins)
    mu = np.full((M, K), 1.0)
    ridge_col = int(np.argmin(np.abs(n_bins - 2.0)))
    mu[:, ridge_col] = 1.4
    gs = GripSurface(s_bins=s_bins, n_bins=n_bins, mu_grid=mu,
                     count_grid=np.full((M, K), 60, dtype=int),
                     confidence=np.ones((M, K)))
    n = frenet.n_points
    return TrackSurface(track_id="synthetic_oval", frenet=frenet,
                        width_left=np.full(n, 3.0), width_right=np.full(n, 3.0),
                        grip_2d=gs, n_laps=20, boundary_source="data_derived")


def test_solve_optimal_line_2d_dry_and_wet():
    pytest.importorskip("casadi")
    from track_surface.solver_bridge import solve_optimal_line_2d

    surface = _synthetic_surface_with_grip()
    dry = solve_optimal_line_2d(surface, condition="dry", n_points=100, max_time_s=60.0)
    wet = solve_optimal_line_2d(surface, condition="wet", n_points=100, max_time_s=60.0)

    assert dry.solver_status in ("optimal", "acceptable", "suboptimal")
    assert wet.solver_status in ("optimal", "acceptable", "suboptimal")
    assert wet.optimal_lap_time_s > dry.optimal_lap_time_s
    assert not np.allclose(dry.lateral_offset_m, wet.lateral_offset_m, atol=0.1)


def test_solve_optimal_line_2d_wet_with_puddles_excludes_corridor():
    pytest.importorskip("casadi")
    from track_surface.solver_bridge import puddles_to_n_windows, solve_optimal_line_2d

    surface = _synthetic_surface_with_grip()
    # Puddle near the inside (n=-1.5) sized so a real dry corridor survives on
    # the left (a radius-3.09 puddle would cover the whole ±3 m track and be
    # skipped). area_cells=3 -> r ≈ 2.18, keep-left corridor n_lo ≈ 1.19, and a
    # ~5.4 m exclusion window. n_points=200 -> ~4.8 m resample spacing so at
    # least one constrained point lands inside the window.
    puddle = PuddleZone(s_center=100.0, n_center=-1.5, depth_score=0.9, area_cells=3)
    wet = solve_optimal_line_2d(surface, condition="wet", puddles=[puddle],
                                n_points=200, max_time_s=60.0)
    assert wet.solver_status in ("optimal", "acceptable")
    # The corridor contract that matters: in the puddle s-window the line must
    # stay on the chosen dry side (>= the window's n_lo).
    windows = puddles_to_n_windows([puddle], surface.grip_2d, surface.width_left,
                                   surface.width_right, surface.frenet.s_grid)
    assert len(windows) == 1
    s0, s1, n_lo, n_hi = windows[0]
    window = (wet.distance_m >= s0) & (wet.distance_m <= s1)
    assert np.any(window)  # a constrained resampled point exists in the window
    assert np.all(wet.lateral_offset_m[window] >= n_lo - 1e-6)


def test_solve_optimal_line_2d_requires_grip():
    pytest.importorskip("casadi")
    from track_surface.solver_bridge import solve_optimal_line_2d
    surface = _synthetic_surface_with_grip()
    surface.grip_2d = None
    with pytest.raises(ValueError, match="grip_2d"):
        solve_optimal_line_2d(surface, condition="dry")


def test_puddles_to_n_windows_picks_wider_side():
    from track_surface.solver_bridge import puddles_to_n_windows

    surface = _synthetic_surface_with_grip()
    # Puddle near the right edge: keep-left is the only sensible corridor
    p = PuddleZone(s_center=50.0, n_center=-2.5, depth_score=0.5, area_cells=4)
    windows = puddles_to_n_windows([p], surface.grip_2d, surface.width_left,
                                   surface.width_right, surface.frenet.s_grid)
    assert len(windows) == 1
    s0, s1, n_lo, n_hi = windows[0]
    # keep-left: corridor ABOVE the puddle -> (n_c + r + margin, +inf)
    # r = max(sqrt(4 * 5.0 / pi), 1.0) ≈ 2.523, margin 0.5
    # n_lo = -2.5 + 2.523 + 0.5 ≈ 0.523
    assert n_hi == float("inf")
    assert n_lo == pytest.approx(-2.5 + np.sqrt(4 * 5.0 / np.pi) + 0.5, abs=0.05)


def test_puddles_to_n_windows_conflicting_overlap_drops_shallower():
    """Two overlapping puddles excluding OPPOSITE sides must not emit
    conflicting windows (which would make the NLP corridor empty and kill
    the wet solve) — the shallower puddle's window is dropped.

    Geometry (verified pre-fix): with wl=wr=8.0m and area_cells=3,
    r = max(sqrt(3*5.0/pi), 1.0) ≈ 2.185, margin=0.5.
      deep   (n=-1.0, depth=0.9): avail_above=8-((-1+2.185+0.5))=6.315,
        avail_below=(-1-2.185-0.5)+8=4.315 -> keep-left, n_lo≈1.685
      shallow (n=+1.0, depth=0.4): avail_above=8-((1+2.185+0.5))=4.315,
        avail_below=(1-2.185-0.5)+8=6.315 -> keep-right, n_hi≈-1.685
    Combined at a point in the s-overlap: lo=1.685 > hi=-1.685 -> ValueError.
    Post-fix: only the deep puddle's keep-left window survives.
    """
    from track_surface.solver_bridge import puddles_to_n_windows

    surface = _synthetic_surface_with_grip()
    wl = np.full(surface.frenet.n_points, 8.0)
    wr = np.full(surface.frenet.n_points, 8.0)
    # deep puddle at n=-1.0: keep-left (corridor above the puddle, n_lo > 0)
    deep = PuddleZone(s_center=100.0, n_center=-1.0, depth_score=0.9, area_cells=3)
    # shallow puddle at n=+1.0 same s: keep-right (corridor below, n_hi < 0)
    # -> conflicts with deep's keep-left over the shared s-window
    shallow = PuddleZone(s_center=100.0, n_center=1.0, depth_score=0.4, area_cells=3)

    windows = puddles_to_n_windows([shallow, deep], surface.grip_2d, wl, wr,
                                   surface.frenet.s_grid)
    assert len(windows) == 1, (
        f"expected 1 window (deep survives, shallow dropped), got {len(windows)}: {windows}"
    )
    s0, s1, n_lo, n_hi = windows[0]
    # The surviving window must be the deep puddle's keep-left corridor.
    assert n_hi == float("inf"), "surviving window must be keep-left (n_hi=inf)"
    assert n_lo > 0.0, f"keep-left n_lo must be positive (deep n=-1.0 + r + margin), got {n_lo}"


def test_bridge_passes_qss_warm_start(monkeypatch):
    """The bridge must hand solve_minimum_time_2d a real QSS warm start —
    silently dropping it would not fail any behavioral test (IPOPT converges
    anyway on simple fields), so pin the contract explicitly.

    Import-style note: solve_optimal_line_2d does a function-level
    ``from lap_oracle.solver.ocp_2d import solve_minimum_time_2d`` — the name
    is resolved at CALL TIME and bound to a local variable, so patching the
    module attribute on the ``lap_oracle.solver.ocp_2d`` object (which is the
    module the bridge actually imports from) is the correct intercept point.
    ``telemetry_tool.lap_oracle.solver.ocp_2d`` is a DIFFERENT module object
    under the sys.path configuration used here, so we pre-import the bridge
    module to ensure its ``lap_oracle`` path is loaded, then patch that.
    """
    pytest.importorskip("casadi")
    import track_surface.solver_bridge as sb

    # Force the bridge module to be imported so its sys.path entry for
    # lap_oracle is registered, then grab the module object the bridge uses.
    import lap_oracle.solver.ocp_2d as ocp2d_mod

    captured = {}
    orig = ocp2d_mod.solve_minimum_time_2d

    def spy(*args, **kwargs):
        captured["warm_start"] = kwargs.get("warm_start")
        return orig(*args, **kwargs)

    monkeypatch.setattr(ocp2d_mod, "solve_minimum_time_2d", spy)

    surface = _synthetic_surface_with_grip()
    sb.solve_optimal_line_2d(surface, condition="dry", n_points=60, max_time_s=30.0)

    assert captured, "spy was never called — monkeypatch did not intercept the import"
    assert captured["warm_start"] is not None, (
        "warm_start was None — bridge dropped the QSS warm start"
    )
    assert captured["warm_start"].solver_status == "qss_fallback"


# ---------------------------------------------------------------------------
# Task 5: NaN-aware shrink + limit-grid source for build_dry_mu_field
# ---------------------------------------------------------------------------
def test_shrink_treats_nan_as_unmeasured():
    s_bins, n_bins = _grids()
    M, K = len(s_bins), len(n_bins)
    mu = np.full((M, K), 1.2)
    count = np.full((M, K), 50, dtype=int)
    conf = np.ones((M, K))
    mu[3, 2] = np.nan          # count>0 but NaN value (limit below the sample floor)
    out = shrink_mu_grid(mu, count, conf)
    assert np.isfinite(out[3, 2])                       # filled by prior, not NaN
    assert out[3, 2] == pytest.approx(1.2 * 0.95, rel=1e-6)   # row prior * discount


def test_build_dry_reads_limit_grid_when_present():
    gs = _grip_surface_with_rubber_line()
    gs.mu_limit_grid = np.full(gs.mu_grid.shape, 1.5)
    field = build_dry_mu_field(gs)
    # Full confidence -> dry field equals the LIMIT grid (1.5), not the mean
    assert field.mu_grid.mean() == pytest.approx(1.5, abs=1e-6)


def test_build_dry_falls_back_to_mean_when_no_limit():
    gs = _grip_surface_with_rubber_line()
    gs.mu_limit_grid = None
    field = build_dry_mu_field(gs)
    np.testing.assert_allclose(field.mu_grid, gs.mu_grid)   # behaves exactly as before


def test_base_grip_uses_mean_for_sparse_below_floor_cells():
    """A sampled cell below the limit's sample floor (NaN limit) degrades to
    its measured MEAN in _base_grip_grid, never the global limit prior."""
    from track_surface.mu_field import _base_grip_grid
    gs = _grip_surface_with_rubber_line()
    gs.mu_limit_grid = np.full(gs.mu_grid.shape, 1.4)
    gs.mu_limit_grid[2, 2] = np.nan
    gs.mu_grid[2, 2] = 0.6
    gs.count_grid[2, 2] = 5
    base = _base_grip_grid(gs)
    assert base[2, 2] == pytest.approx(0.6)     # mean, not NaN, not 1.4
    assert base[0, 0] == pytest.approx(1.4)     # well-sampled cell keeps the limit


def test_base_grip_leaves_unmeasured_cells_nan():
    from track_surface.mu_field import _base_grip_grid
    gs = _grip_surface_with_rubber_line()
    gs.mu_limit_grid = np.full(gs.mu_grid.shape, 1.4)
    gs.mu_limit_grid[1, 1] = np.nan
    gs.count_grid[1, 1] = 0          # truly unmeasured
    base = _base_grip_grid(gs)
    assert np.isnan(base[1, 1])      # stays NaN -> shrink's unmeasured path
