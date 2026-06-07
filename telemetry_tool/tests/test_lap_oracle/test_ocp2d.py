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
# +3.026), m_down=-1.565 (disp +0.094). Set to ~half the smaller observed
# displacement (0.094/2 = 0.047) but floored at the 0.05 minimum.
MIN_SHIFT_M = 0.05


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
    assert m_up > m_base + MIN_SHIFT_M
    assert m_down < m_base - MIN_SHIFT_M


@needs_casadi
def test_uniform_low_grip_is_slower():
    track = _oval_track(n=100)
    vp = _default_vehicle()
    hi = solve_minimum_time_2d(track, vp, _uniform_field(track.total_length_m, 1.0),
                               n_points=100, max_time_s=60.0)
    lo = solve_minimum_time_2d(track, vp, _uniform_field(track.total_length_m, 0.6),
                               n_points=100, max_time_s=60.0)
    assert lo.optimal_lap_time_s > hi.optimal_lap_time_s
