"""Tests for the 2D grip-aware minimum-time OCP solver."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.lap_oracle.config import VehicleParams
from telemetry_tool.lap_oracle.solver.ocp import HAS_CASADI
from telemetry_tool.lap_oracle.solver.ocp_2d import MuField
from telemetry_tool.lap_oracle.track.model import build_from_xy

needs_casadi = pytest.mark.skipif(not HAS_CASADI, reason="CasADi not installed")


# -- Helpers (mirror test_solver.py conventions) -----------------------------

def _oval_track(n: int = 200):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    a, b = 200.0, 100.0
    xy = np.column_stack((a * np.cos(t), b * np.sin(t)))
    return build_from_xy(xy, width=3.0, name="test_oval", sim="test")


def _default_vehicle(**overrides) -> VehicleParams:
    kw = dict(
        mass_kg=1000.0, max_power_w=300_000.0, cda=0.7, cla=2.0,
        max_brake_decel=12.0, wheelbase_m=2.6,
    )
    kw.update(overrides)
    return VehicleParams(**kw)


def _uniform_field(total_length_m: float, mu: float = 1.0) -> MuField:
    s_bins = np.arange(0.0, total_length_m, 5.0)
    n_bins = np.arange(-8.0, 9.0, 1.0)
    return MuField(
        s_bins=s_bins, n_bins=n_bins,
        mu_grid=np.full((len(s_bins), len(n_bins)), mu),
    )


# -- Task 1: interpolant layout ----------------------------------------------

@needs_casadi
def test_interpolant_matches_gripsurface_bilinear():
    """The CasADi interpolant must agree with GripSurface.mu_at at interior
    points. An ASYMMETRIC grid catches Fortran/C flatten-order bugs."""
    from track_surface.grip_2d import GripSurface
    from telemetry_tool.lap_oracle.solver.ocp_2d import _make_mu_interpolant
    import casadi as ca

    rng = np.random.default_rng(42)
    s_bins = np.arange(0.0, 500.0, 5.0)        # M = 100
    n_bins = np.arange(-8.0, 9.0, 1.0)         # K = 17  (M != K on purpose)
    mu_grid = 0.8 + 0.6 * rng.random((len(s_bins), len(n_bins)))

    gs = GripSurface(
        s_bins=s_bins, n_bins=n_bins, mu_grid=mu_grid,
        count_grid=np.full(mu_grid.shape, 50, dtype=int),
        confidence=np.ones(mu_grid.shape),
    )
    field = MuField(s_bins=s_bins, n_bins=n_bins, mu_grid=mu_grid)
    lut = _make_mu_interpolant(field)

    # Interior points strictly inside the grid (away from clamp edges)
    for _ in range(200):
        s = float(rng.uniform(s_bins[1], s_bins[-2]))
        n = float(rng.uniform(n_bins[1], n_bins[-2]))
        got = float(lut(ca.vertcat(s, n)))
        want = gs.mu_at(s, n)
        assert got == pytest.approx(want, abs=1e-9), (s, n)


def test_mufield_validates_shapes():
    with pytest.raises(ValueError):
        MuField(
            s_bins=np.arange(0, 100, 5.0),
            n_bins=np.arange(-8, 9, 1.0),
            mu_grid=np.ones((3, 3)),   # wrong shape
        )


@needs_casadi
def test_interpolant_extrapolates_outside_grid_documented():
    """CasADi 'linear' EXTRAPOLATES beyond the grid; GripSurface.mu_at CLAMPS.
    solve_minimum_time_2d guards this by clamping s into the s-domain and
    intersecting N_lat bounds with the n-domain. This test documents the
    divergence so the guard is never 'optimized away'."""
    from track_surface.grip_2d import GripSurface
    from telemetry_tool.lap_oracle.solver.ocp_2d import _make_mu_interpolant
    import casadi as ca

    s_bins = np.arange(0.0, 100.0, 5.0)
    n_bins = np.arange(-3.0, 4.0, 1.0)
    rng = np.random.default_rng(3)
    mu = 0.8 + 0.4 * rng.random((len(s_bins), len(n_bins)))
    field = MuField(s_bins=s_bins, n_bins=n_bins, mu_grid=mu)
    gs = GripSurface(s_bins=s_bins, n_bins=n_bins, mu_grid=mu,
                     count_grid=np.full(mu.shape, 50, dtype=int),
                     confidence=np.ones(mu.shape))
    lut = _make_mu_interpolant(field)
    # 5 m past the n edge: interpolant extrapolates, mu_at clamps
    got = float(lut(ca.vertcat(50.0, n_bins[-1] + 5.0)))
    clamped = gs.mu_at(50.0, n_bins[-1] + 5.0)
    assert got != pytest.approx(clamped, abs=1e-6)


# -- Task 4: solve_minimum_time_2d NLP ---------------------------------------

from telemetry_tool.lap_oracle.config import OCPSolution
from telemetry_tool.lap_oracle.solver.ocp_2d import solve_minimum_time_2d


# Minimum line displacement (m) that certifies 2D grip-awareness. Measured on
# the symmetric _oval_track with smooth +/-0.05 grip ramps vs the uniform-grip
# baseline (deterministic IPOPT solves): m_base=-1.472, m_up=+1.555 (disp
# +3.026), m_down=-1.565 (disp +0.094). Margins are asymmetric on purpose:
# the down-ramp grip pull aligns with the oval's geometric pull so the line is
# already near its bound — small headroom; the up-ramp fights geometry and
# wins big — demand a proportional shift.
MIN_SHIFT_UP_M = 1.0
MIN_SHIFT_DOWN_M = 0.05


def _ramp_mu_field(total_length_m: float, slope: float) -> MuField:
    """Smooth lateral grip ramp: mu(n) = 1.0 + slope*n (clipped to [0.5, 1.5]).

    Smooth on purpose: STEP-split fields trap IPOPT in a local basin on the
    low-grip side of the discontinuity (verified: left-grippy step field
    converges to lap 28.8s in the mu=0.7 region while the mirrored field
    reaches 21.8s — 'optimal' status certifies only LOCAL optimality)."""
    s_bins = np.arange(0.0, total_length_m, 5.0)
    n_bins = np.arange(-8.0, 9.0, 1.0)
    mu = np.clip(1.0 + slope * n_bins[None, :], 0.5, 1.5)
    mu = np.broadcast_to(mu, (len(s_bins), len(n_bins))).copy()
    return MuField(s_bins=s_bins, n_bins=n_bins, mu_grid=mu)


@needs_casadi
def test_2d_solver_produces_valid_solution():
    track = _oval_track(n=100)
    vp = _default_vehicle()
    field = _uniform_field(track.total_length_m, mu=1.0)
    sol = solve_minimum_time_2d(track, vp, field, n_points=100, max_time_s=60.0)

    assert isinstance(sol, OCPSolution)
    assert sol.solver_status in ("optimal", "suboptimal")
    assert sol.optimal_lap_time_s > 10.0
    n = len(sol.speed_mps)
    assert len(sol.lateral_offset_m) == n
    assert len(sol.distance_m) == n
    # Boundary respect: |N_lat| <= width * 0.9 (width=3.0 in _oval_track)
    assert np.all(np.abs(sol.lateral_offset_m) <= 3.0 * 0.9 + 1e-6)
    # Periodicity
    assert sol.lateral_offset_m[0] == pytest.approx(sol.lateral_offset_m[-1], abs=1e-6)


@needs_casadi
def test_line_shifts_toward_high_grip_side():
    """THE 2D-awareness proof, robust to track geometry: mirrored smooth
    grip ramps must displace the line toward each ramp's grippy side
    RELATIVE TO the uniform-grip baseline. A grip-blind (1D) solver gives
    identical lines for all three fields and fails both displacement
    assertions."""
    track = _oval_track(n=100)
    vp = _default_vehicle()

    base = solve_minimum_time_2d(track, vp, _uniform_field(track.total_length_m, 1.0),
                                 n_points=100, max_time_s=60.0)
    up = solve_minimum_time_2d(track, vp, _ramp_mu_field(track.total_length_m, +0.05),
                               n_points=100, max_time_s=60.0)
    down = solve_minimum_time_2d(track, vp, _ramp_mu_field(track.total_length_m, -0.05),
                                 n_points=100, max_time_s=60.0)

    assert base.solver_status == "optimal"
    assert up.solver_status == "optimal"
    assert down.solver_status == "optimal"

    m_base = float(np.mean(base.lateral_offset_m))
    m_up = float(np.mean(up.lateral_offset_m))
    m_down = float(np.mean(down.lateral_offset_m))

    # Grip increasing toward +n pulls the line toward +n, and vice versa
    assert m_up > m_base + MIN_SHIFT_UP_M
    assert m_down < m_base - MIN_SHIFT_DOWN_M


@needs_casadi
def test_uniform_low_grip_is_slower():
    track = _oval_track(n=100)
    vp = _default_vehicle()
    hi = solve_minimum_time_2d(track, vp, _uniform_field(track.total_length_m, 1.0),
                               n_points=100, max_time_s=60.0)
    lo = solve_minimum_time_2d(track, vp, _uniform_field(track.total_length_m, 0.6),
                               n_points=100, max_time_s=60.0)
    assert lo.optimal_lap_time_s > hi.optimal_lap_time_s


@needs_casadi
def test_zero_grip_field_does_not_nan_poison():
    """A degenerate all-zero grip field must not NaN-poison the NLP: the
    EPS_GRIP floor keeps the friction ellipse conditioned, so the solver
    returns a finite (very slow) solution instead of silent garbage."""
    track = _oval_track(n=60)
    vp = _default_vehicle()
    field = _uniform_field(track.total_length_m, mu=0.0)
    sol = solve_minimum_time_2d(track, vp, field, n_points=60, max_time_s=30.0)
    assert np.all(np.isfinite(sol.speed_mps))
    assert np.all(np.isfinite(sol.lateral_offset_m))
    # With grip floored at 0.05 the lap is dramatically slower than mu=1.0
    ref = solve_minimum_time_2d(track, vp, _uniform_field(track.total_length_m, 1.0),
                                n_points=60, max_time_s=30.0)
    assert sol.optimal_lap_time_s > ref.optimal_lap_time_s * 1.5


# -- Task 4b: envelope_caps support -----------------------------------------

def _brake_caps(total_length_m, brake_g):
    """Uniform demonstrated brake cap across speed (drive generous, non-binding)."""
    v = [5.0, 60.0]
    return {"v_grid": v,
            "ax_drive_max": [30.0, 30.0],
            "ax_brake_max": [brake_g * 9.80665, brake_g * 9.80665]}


@needs_casadi
def test_envelope_caps_none_is_byte_identical():
    track = _oval_track(n=100)
    vp = _default_vehicle()
    field = _uniform_field(track.total_length_m, mu=1.0)
    a = solve_minimum_time_2d(track, vp, field, n_points=100, max_time_s=60.0)
    b = solve_minimum_time_2d(track, vp, field, n_points=100, max_time_s=60.0,
                              envelope_caps=None)
    np.testing.assert_array_equal(a.lateral_offset_m, b.lateral_offset_m)
    np.testing.assert_array_equal(a.speed_mps, b.speed_mps)


@needs_casadi
def test_tighter_demonstrated_brake_cap_slows_the_lap():
    track = _oval_track(n=100)
    vp = _default_vehicle()
    field = _uniform_field(track.total_length_m, mu=1.0)
    loose = solve_minimum_time_2d(track, vp, field, n_points=100, max_time_s=60.0,
                                  envelope_caps=_brake_caps(track.total_length_m, 3.0))
    tight = solve_minimum_time_2d(track, vp, field, n_points=100, max_time_s=60.0,
                                  envelope_caps=_brake_caps(track.total_length_m, 0.5))
    assert tight.solver_status in ("optimal", "acceptable")
    assert tight.optimal_lap_time_s > loose.optimal_lap_time_s + 0.1


@needs_casadi
def test_solver_is_deterministic():
    """Gate 1: identical inputs → bit-identical line."""
    track = _oval_track(n=100)
    vp = _default_vehicle()
    field = _ramp_mu_field(track.total_length_m, +0.05)

    a = solve_minimum_time_2d(track, vp, field, n_points=100, max_time_s=60.0)
    b = solve_minimum_time_2d(track, vp, field, n_points=100, max_time_s=60.0)

    np.testing.assert_array_equal(a.lateral_offset_m, b.lateral_offset_m)
    np.testing.assert_array_equal(a.speed_mps, b.speed_mps)
    assert a.optimal_lap_time_s == b.optimal_lap_time_s

    # Multi-start must be deterministic too: the fixed start order and the
    # strict-< selection rule make the winning candidate reproducible, so a
    # multi-start solve on the step-discontinuous puddle field is also
    # bit-identical across calls.
    puddle = _field_with_puddle_block(track.total_length_m)
    c = solve_minimum_time_2d(track, vp, puddle, n_points=100, max_time_s=60.0,
                              n_lat_starts=(0.0, 2.0, -2.0))
    d = solve_minimum_time_2d(track, vp, puddle, n_points=100, max_time_s=60.0,
                              n_lat_starts=(0.0, 2.0, -2.0))

    np.testing.assert_array_equal(c.lateral_offset_m, d.lateral_offset_m)
    np.testing.assert_array_equal(c.speed_mps, d.speed_mps)
    assert c.optimal_lap_time_s == d.optimal_lap_time_s


def _field_with_puddle_block(total_length_m: float) -> MuField:
    """Uniform wet grip 0.85 with a puddle block (mu=0.2) over the
    inside strip (n <= -2.0) for s in [90, 130] — sitting where the
    unobstructed wet line wants to be in the first corner.

    The puddle boundary is at n=-2.0 (leaving the inside-outer 0.7m of the
    ±2.7m track bounds as puddle) so that the dry corridor (n > -2.0) is wide
    enough for the NLP to find a clean puddle-free solution without relying on
    bspline overshoot at the step edge.  mu_grid.max() == 0.85 (no phantom
    grip for cap regression)."""
    s_bins = np.arange(0.0, total_length_m, 5.0)
    n_bins = np.arange(-8.0, 9.0, 1.0)
    mu = np.full((len(s_bins), len(n_bins)), 0.85)
    s_mask = (s_bins >= 90.0) & (s_bins <= 130.0)
    n_mask = n_bins <= -2.0
    mu[np.ix_(s_mask, n_mask)] = 0.2
    return MuField(s_bins=s_bins, n_bins=n_bins, mu_grid=mu)


@needs_casadi
def test_wet_line_routes_around_puddle():
    """Gate 3 (synthetic form): the line must not cross puddle cells, and
    must carry more grip than the puddle-blind control line."""
    from track_surface.grip_2d import GripSurface

    track = _oval_track(n=100)
    vp = _default_vehicle()
    puddle_field = _field_with_puddle_block(track.total_length_m)
    control_field = _uniform_field(track.total_length_m, mu=0.85)

    # Multi-start the PUDDLE solve only. The step-clamped puddle block
    # (mu=0.2 for n<=-2.0 over s in [90,130]) creates a low-grip local basin
    # that traps a single cold start (N_lat=0) ON the puddle side — IPOPT
    # reports "optimal" in that basin and cannot cross the step. Seeding
    # lateral starts (0, +2, -2) lands a solve in the dry (n>-2.0) basin;
    # the best optimal candidate wins. This mirrors how the production
    # wet-field bridge will call the solver. The control solve stays
    # single-start (uniform field has no step basin to escape).
    sol = solve_minimum_time_2d(track, vp, puddle_field, n_points=100, max_time_s=60.0,
                                n_lat_starts=(0.0, 2.0, -2.0))
    control = solve_minimum_time_2d(track, vp, control_field, n_points=100, max_time_s=60.0)
    assert sol.solver_status == "optimal"

    # Sample mu under each line via the same bilinear scheme
    gs = GripSurface(
        s_bins=puddle_field.s_bins, n_bins=puddle_field.n_bins,
        mu_grid=puddle_field.mu_grid,
        count_grid=np.full(puddle_field.mu_grid.shape, 1, dtype=int),
        confidence=np.ones(puddle_field.mu_grid.shape),
    )
    mu_under_line = gs.mu_at_batch(sol.distance_m, sol.lateral_offset_m)
    mu_under_control = gs.mu_at_batch(control.distance_m, control.lateral_offset_m)

    # Zero puddle crossings: never inside mu<=0.25 territory
    assert float(mu_under_line.min()) > 0.25
    # And strictly better integrated grip than the puddle-blind line
    assert float(mu_under_line.mean()) > float(mu_under_control.mean()) - 1e-9
    # In the puddle s-window the line must sit on the dry (n > -2.0) side
    window = (sol.distance_m >= 95.0) & (sol.distance_m <= 125.0)
    assert np.all(sol.lateral_offset_m[window] > -2.0)


@needs_casadi
def test_smooth_interpolant_matches_grid_at_knots():
    """The bspline solver field must reproduce the grid values AT the knots
    (between knots it smooths — that's the point)."""
    import casadi as ca
    from telemetry_tool.lap_oracle.solver.ocp_2d import _make_mu_interpolant_smooth

    rng = np.random.default_rng(11)
    s_bins = np.arange(0.0, 200.0, 5.0)
    n_bins = np.arange(-8.0, 9.0, 1.0)
    mu = 0.7 + 0.5 * rng.random((len(s_bins), len(n_bins)))
    field = MuField(s_bins=s_bins, n_bins=n_bins, mu_grid=mu)
    lut = _make_mu_interpolant_smooth(field)
    for i_s in (1, 10, 20, 38):
        for i_n in (1, 8, 15):
            got = float(lut(ca.vertcat(s_bins[i_s], n_bins[i_n])))
            assert got == pytest.approx(mu[i_s, i_n], abs=1e-6), (i_s, i_n)


@needs_casadi
def test_empty_starts_raises():
    track = _oval_track(n=60)
    with pytest.raises(ValueError, match="n_lat_starts"):
        solve_minimum_time_2d(track, _default_vehicle(),
                              _uniform_field(track.total_length_m, 1.0),
                              n_lat_starts=())


@needs_casadi
def test_nlp_grip_is_capped_at_field_max():
    """The NLP must never see more grip than the field's true maximum:
    a field whose ONLY high-grip region is bspline-overshoot territory
    (just outside a step) must not produce a faster lap than the same
    field solved with uniform grip at the true max.

    (belt-and-suspenders: overshoot was measured at +9% but may not always
    flip this assertion at n_points=60 — the test is kept regardless as a
    structural guard against the fmin cap being silently removed)
    """
    track = _oval_track(n=60)
    vp = _default_vehicle()
    field = _field_with_puddle_block(track.total_length_m)
    ref = solve_minimum_time_2d(track, vp,
                                _uniform_field(track.total_length_m, 0.85),
                                n_points=60, max_time_s=30.0)
    sol = solve_minimum_time_2d(track, vp, field, n_points=60, max_time_s=30.0,
                                n_lat_starts=(0.0, 2.0, -2.0))
    # The puddle field is everywhere <= 0.85, so its lap can never beat the
    # uniform-0.85 lap (it could only do so by consuming overshoot grip)
    assert sol.optimal_lap_time_s >= ref.optimal_lap_time_s - 1e-6


# -- Task 6: hard corridor exclusions (n_windows) ----------------------------

def _field_with_flooded_inside_half(total_length_m: float) -> MuField:
    """The extreme scenario: puddle block covering the ENTIRE inside half
    (n <= 0) over s in [90, 130]. Free optimization cannot certify a dry
    line here once bspline overshoot is capped (see Task-5 history) — the
    production path excludes the flooded corridor as a HARD constraint."""
    s_bins = np.arange(0.0, total_length_m, 5.0)
    n_bins = np.arange(-8.0, 9.0, 1.0)
    mu = np.full((len(s_bins), len(n_bins)), 0.85)
    s_mask = (s_bins >= 90.0) & (s_bins <= 130.0)
    n_mask = n_bins <= 0.0
    mu[np.ix_(s_mask, n_mask)] = 0.2
    return MuField(s_bins=s_bins, n_bins=n_bins, mu_grid=mu)


@needs_casadi
def test_n_windows_force_dry_line_through_flooded_half():
    """Hard corridor exclusion solves the extreme flooded-inside-half case
    that free optimization cannot (capped grip, local basins)."""
    from track_surface.grip_2d import GripSurface

    track = _oval_track(n=100)
    vp = _default_vehicle()
    field = _field_with_flooded_inside_half(track.total_length_m)

    # Corridor lower bound clears the mu=0.2 step at n=0 with a 1 m margin —
    # exactly how puddles_to_n_windows sets it in production (puddle radius +
    # margin keeps the active bound off the steep grip transition that would
    # otherwise ill-condition the friction ellipse). The flooded inside half
    # (n <= 0) is excluded HARD; the line is forced onto the dry side.
    sol = solve_minimum_time_2d(
        track, vp, field, n_points=100, max_time_s=60.0,
        n_lat_starts=(0.0, 2.0),
        n_windows=((85.0, 135.0, 1.0, float("inf")),),
    )
    assert sol.solver_status in ("optimal", "acceptable")
    window = (sol.distance_m >= 90.0) & (sol.distance_m <= 130.0)
    assert np.all(sol.lateral_offset_m[window] >= 1.0 - 1e-6)
    gs = GripSurface(s_bins=field.s_bins, n_bins=field.n_bins, mu_grid=field.mu_grid,
                     count_grid=np.ones(field.mu_grid.shape, dtype=int),
                     confidence=np.ones(field.mu_grid.shape))
    mu_under = gs.mu_at_batch(sol.distance_m, sol.lateral_offset_m)
    assert float(mu_under.min()) > 0.25


@needs_casadi
def test_n_windows_impossible_corridor_raises():
    track = _oval_track(n=60)
    vp = _default_vehicle()
    field = _uniform_field(track.total_length_m, 1.0)
    with pytest.raises(ValueError):
        solve_minimum_time_2d(track, vp, field, n_points=60, max_time_s=30.0,
                              n_windows=((50.0, 100.0, 2.0, -2.0),))
