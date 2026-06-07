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
        import casadi as ca
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
