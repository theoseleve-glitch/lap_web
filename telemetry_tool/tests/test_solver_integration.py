# telemetry_tool/tests/test_solver_integration.py
"""Integration test: synthetic oval regression gate.

This is THE critical test — if it fails, the solver is broken.
"""
import logging
import math

import numpy as np
import pytest

from solver.ocp_solver import solve_ocp
from solver.track_model import TrackMesh
from solver.vehicle_params import OCPVehicleParams
from solver.tire_model import LoadSensitiveTire

logger = logging.getLogger(__name__)
_G = 9.80665


def _build_oval_mesh(
    straight_length: float = 93.0,
    corner_radius: float = 50.0,
    n_nodes: int = 500,
) -> TrackMesh:
    """Build a synthetic oval track: two straights + two semicircles.

    Total length ~ 2*straight + 2*pi*R = 2*93 + 2*pi*50 = 500.2m
    """
    corner_arc = math.pi * corner_radius  # half circumference

    # Build distance/curvature arrays
    n_straight = int(n_nodes * straight_length / (2 * straight_length + 2 * corner_arc))
    n_corner = int(n_nodes * corner_arc / (2 * straight_length + 2 * corner_arc))

    s_list = []
    k_list = []
    offset = 0.0

    for seg_type in ["straight", "corner", "straight", "corner"]:
        if seg_type == "straight":
            n = max(n_straight, 10)
            s_seg = np.linspace(offset, offset + straight_length, n, endpoint=False)
            k_seg = np.zeros(n)
            offset += straight_length
        else:
            n = max(n_corner, 10)
            s_seg = np.linspace(offset, offset + corner_arc, n, endpoint=False)
            k_seg = np.full(n, 1.0 / corner_radius)
            offset += corner_arc

        s_list.append(s_seg)
        k_list.append(k_seg)

    s_arr = np.concatenate(s_list)
    k_arr = np.concatenate(k_list)

    # Add final point
    s_arr = np.append(s_arr, offset)
    k_arr = np.append(k_arr, 0.0)

    ds = np.diff(s_arr)
    track_length = float(s_arr[-1] - s_arr[0])

    return TrackMesh(s=s_arr, kappa=k_arr, ds=ds, track_length=track_length)


class TestSyntheticOval:
    """Regression gate: OCP on a synthetic oval must match analytical bounds."""

    @pytest.mark.slow
    def test_oval_lap_time_within_tolerance(self):
        R = 50.0
        mu = 1.0
        mass = 1200.0
        P_max = 150_000.0  # 150 kW

        mesh = _build_oval_mesh(corner_radius=R, n_nodes=500)

        params = OCPVehicleParams(
            mass=mass, h_cg=0.0, wheelbase=2.6, track_width=1.55,
            A=0.0, Cd=0.0, Cl=0.0, rho=1.225, Cr=0.0,
            mu_ref=mu, load_sensitivity=0.0,
            P_max=P_max, F_brake_max=mass * mu * _G,
            F_drive_max=mass * mu * _G,
        )

        tire = LoadSensitiveTire(
            mu_ref=mu, Fz_ref=params.Fz_static_per_axle, sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire, max_iter=2000)
        assert result.converged, f"Solver did not converge: {result.solver_meta}"

        # Analytical reference (point-mass, no aero, no rolling, no load transfer)
        v_corner = math.sqrt(mu * _G * R)  # ~22.15 m/s
        straight_len = 93.0
        corner_arc = math.pi * R

        # Corner time: 2 semicircles at v_corner
        t_corners = 2 * (corner_arc / v_corner)

        # Straight time: numeric integration with constant-power + traction limit
        a_max_traction = mu * _G
        dt = 0.01  # seconds
        v = v_corner
        d = 0.0
        t_straight = 0.0
        while d < straight_len:
            a = min(P_max / (mass * max(v, 1.0)), a_max_traction)
            v += a * dt
            d += v * dt
            t_straight += dt
        # Two straights (approximate — real solver handles braking too)
        t_straights = 2 * t_straight

        t_analytical_approx = t_corners + t_straights

        # Regression gate: OCP must be within 1.0s of analytical
        assert abs(result.lap_time_s - t_analytical_approx) < 1.0, (
            f"OCP lap time {result.lap_time_s:.2f}s too far from "
            f"analytical {t_analytical_approx:.2f}s (delta="
            f"{abs(result.lap_time_s - t_analytical_approx):.2f}s, limit=1.0s)"
        )

    @pytest.mark.slow
    def test_corner_speeds_near_analytical(self):
        """Corner speeds should be close to sqrt(mu*g*R)."""
        R = 50.0
        mu = 1.0

        mesh = _build_oval_mesh(corner_radius=R, n_nodes=500)
        params = OCPVehicleParams(
            mass=1200.0, h_cg=0.0, wheelbase=2.6, track_width=1.55,
            A=0.0, Cd=0.0, Cl=0.0, rho=1.225, Cr=0.0,
            mu_ref=mu, load_sensitivity=0.0,
            P_max=150_000.0, F_brake_max=1200.0 * mu * _G,
            F_drive_max=1200.0 * mu * _G,
        )
        tire = LoadSensitiveTire(
            mu_ref=mu, Fz_ref=params.Fz_static_per_axle, sensitivity=0.0,
        )

        result = solve_ocp(mesh, params, tire)

        v_analytical = math.sqrt(mu * _G * R)

        # Get speeds in corner regions (where kappa > 0.01)
        corner_mask = np.abs(mesh.kappa) > 0.01
        corner_speeds = result.speed_profile[corner_mask]

        # Mid-corner speeds (away from transitions) should be close to analytical
        n_corner = len(corner_speeds)
        if n_corner > 10:
            mid_corner = corner_speeds[n_corner // 4 : 3 * n_corner // 4]
            mean_mid = float(np.mean(mid_corner))
            assert mean_mid == pytest.approx(v_analytical, rel=0.05)  # within 5%
