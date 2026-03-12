# telemetry_tool/tests/test_solver_ocp.py
"""Tests for the OCP solver."""
import math
import numpy as np
import pytest

from solver.ocp_solver import solve_ocp
from solver.track_model import TrackMesh
from solver.vehicle_params import OCPVehicleParams
from solver.tire_model import LoadSensitiveTire

_G = 9.80665


def _make_circle_mesh(radius: float = 50.0, n_nodes: int = 200) -> TrackMesh:
    """Create a constant-radius circular track mesh."""
    circumference = 2 * math.pi * radius
    s = np.linspace(0, circumference, n_nodes)
    kappa = np.full(n_nodes, 1.0 / radius)  # constant curvature
    ds = np.diff(s)
    return TrackMesh(s=s, kappa=kappa, ds=ds, track_length=circumference)


def _make_simple_params(mu: float = 1.0, mass: float = 1200.0) -> OCPVehicleParams:
    """Simple vehicle with no aero, no rolling resistance."""
    return OCPVehicleParams(
        mass=mass, h_cg=0.0, wheelbase=2.6, track_width=1.55,
        A=0.0, Cd=0.0, Cl=0.0, rho=1.225, Cr=0.0,
        mu_ref=mu, load_sensitivity=0.0,
        P_max=1e6, F_brake_max=1e6, F_drive_max=1e6,
    )


class TestConstantRadiusCircle:
    """The fundamental validation: on a constant-radius circle with no aero/rolling,
    the optimal speed is v = sqrt(mu * g * R)."""

    def test_circle_speed_matches_analytical(self):
        R = 50.0
        mu = 1.0
        mesh = _make_circle_mesh(radius=R, n_nodes=200)
        params = _make_simple_params(mu=mu)
        tire = LoadSensitiveTire(
            mu_ref=mu,
            Fz_ref=params.Fz_static_per_axle,
            sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire)
        assert result.converged

        v_analytical = math.sqrt(mu * _G * R)  # ~22.147 m/s

        # Speed should be nearly constant around the circle
        mean_speed = float(np.mean(result.speed_profile))
        assert mean_speed == pytest.approx(v_analytical, rel=0.01)

    def test_circle_lap_time_matches_analytical(self):
        R = 50.0
        mu = 1.0
        mesh = _make_circle_mesh(radius=R, n_nodes=200)
        params = _make_simple_params(mu=mu)
        tire = LoadSensitiveTire(
            mu_ref=mu,
            Fz_ref=params.Fz_static_per_axle,
            sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire)

        v_analytical = math.sqrt(mu * _G * R)
        circumference = 2 * math.pi * R
        t_analytical = circumference / v_analytical

        assert result.lap_time_s == pytest.approx(t_analytical, rel=0.01)


class TestSolverConvergence:
    """Test that the solver handles edge cases."""

    def test_warm_start_improves_convergence(self):
        R = 50.0
        mu = 1.0
        mesh = _make_circle_mesh(radius=R, n_nodes=100)
        params = _make_simple_params(mu=mu)
        tire = LoadSensitiveTire(
            mu_ref=mu, Fz_ref=params.Fz_static_per_axle, sensitivity=0.0,
        )

        # Good warm start: near-optimal speed
        v_opt = math.sqrt(mu * _G * R)
        warm_start = np.full(100, v_opt)

        result = solve_ocp(mesh, params, tire, warm_start=warm_start)
        assert result.converged
        # With good warm start, should converge in fewer iterations
        assert result.solver_meta["iterations"] < 100
