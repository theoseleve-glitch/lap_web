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


class TestFrictionEllipseDragSeparation:
    """Verify that aero drag is excluded from the friction ellipse.

    On a constant-radius circle at constant speed, the tire must produce
    drive force to overcome drag.  This drive force uses longitudinal
    grip, reducing the lateral grip available for cornering.  With correct
    physics, a high-drag car should be SLOWER on a circle than the
    zero-drag analytical limit v = sqrt(mu * g * R).
    """

    def test_high_drag_reduces_circle_speed(self):
        R = 200.0  # larger radius → higher speed → more drag effect
        mu = 1.0
        mesh = _make_circle_mesh(radius=R, n_nodes=200)

        # High-drag vehicle (Formula-like aero with lots of drag)
        params = OCPVehicleParams(
            mass=800.0, h_cg=0.0, wheelbase=3.0, track_width=1.8,
            A=1.5, Cd=1.0, Cl=0.0, rho=1.225, Cr=0.0,
            mu_ref=mu, load_sensitivity=0.0,
            P_max=500_000.0, F_brake_max=1e6, F_drive_max=1e6,
        )
        tire = LoadSensitiveTire(
            mu_ref=mu, Fz_ref=params.Fz_static_per_axle, sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire)
        assert result.converged

        v_no_drag = math.sqrt(mu * _G * R)  # ~44.3 m/s
        mean_speed = float(np.mean(result.speed_profile))

        # With significant drag, tire must use longitudinal grip to
        # overcome drag → less lateral grip → lower cornering speed.
        assert mean_speed < v_no_drag * 0.99, (
            f"High-drag car should be slower: {mean_speed:.2f} vs "
            f"no-drag limit {v_no_drag:.2f}"
        )


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
