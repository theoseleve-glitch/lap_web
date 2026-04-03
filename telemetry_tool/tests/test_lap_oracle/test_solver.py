"""Tests for the OCP solver and QSS fallback.

All QSS tests run without CasADi.  OCP tests are skipped gracefully
when CasADi is not installed.
"""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.lap_oracle.config import (
    OCPSolution,
    VehicleParams,
    WeatherConditions,
)
from telemetry_tool.lap_oracle.solver.fallback_qss import solve_qss
from telemetry_tool.lap_oracle.solver.ocp import HAS_CASADI, solve_minimum_time
from telemetry_tool.lap_oracle.track.model import build_from_xy

# -- Helpers ----------------------------------------------------------------

def _oval_track(n: int = 200):
    """Generate an oval track with semi-axes a=200, b=100.

    Returns a TrackModel built from *n* equally spaced points on the
    ellipse perimeter.
    """
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    a, b = 200.0, 100.0
    x = a * np.cos(t)
    y = b * np.sin(t)
    xy = np.column_stack((x, y))
    return build_from_xy(xy, width=5.0, name="test_oval", sim="test")


def _default_vehicle(**overrides) -> VehicleParams:
    """Return a baseline vehicle, applying any keyword overrides."""
    kw = dict(
        mass_kg=1000.0,
        max_power_w=300_000.0,
        cda=0.7,
        cla=2.0,
        max_brake_decel=12.0,
        wheelbase_m=2.6,
    )
    kw.update(overrides)
    return VehicleParams(**kw)


# -- QSS fallback tests ----------------------------------------------------

class TestQSSFallback:
    """Tests that work regardless of CasADi installation."""

    def test_qss_produces_valid_solution(self):
        track = _oval_track()
        vp = _default_vehicle()
        sol = solve_qss(track, vp)

        assert isinstance(sol, OCPSolution)
        assert sol.solver_status == "qss_fallback"
        assert 10.0 < sol.optimal_lap_time_s < 300.0
        # Array lengths must match resampled track
        n = len(sol.speed_mps)
        assert len(sol.distance_m) == n
        assert len(sol.throttle) == n
        assert len(sol.brake) == n
        assert len(sol.steering_rad) == n
        assert len(sol.lateral_offset_m) == n

    def test_qss_heavier_car_slower(self):
        track = _oval_track()
        light = _default_vehicle(mass_kg=1000.0)
        heavy = _default_vehicle(mass_kg=1500.0)

        sol_light = solve_qss(track, light)
        sol_heavy = solve_qss(track, heavy)

        assert sol_heavy.optimal_lap_time_s > sol_light.optimal_lap_time_s

    def test_qss_wet_slower(self):
        track = _oval_track()
        vp = _default_vehicle()
        dry = WeatherConditions(grip_multiplier=1.0)
        wet = WeatherConditions(grip_multiplier=0.7)

        sol_dry = solve_qss(track, vp, weather=dry)
        sol_wet = solve_qss(track, vp, weather=wet)

        assert sol_wet.optimal_lap_time_s > sol_dry.optimal_lap_time_s

    def test_qss_speed_within_bounds(self):
        track = _oval_track()
        vp = _default_vehicle()
        sol = solve_qss(track, vp)

        assert np.all(sol.speed_mps >= 5.0)
        assert np.all(sol.speed_mps <= 400.0)


# -- CasADi OCP tests (skipped if not installed) ---------------------------

needs_casadi = pytest.mark.skipif(
    not HAS_CASADI,
    reason="CasADi not installed",
)


class TestOCPSolver:
    """Tests that require CasADi."""

    @needs_casadi
    def test_ocp_produces_solution(self):
        track = _oval_track(n=100)
        vp = _default_vehicle()
        sol = solve_minimum_time(
            track, vp, n_points=100, max_time_s=60.0,
        )

        assert isinstance(sol, OCPSolution)
        assert sol.solver_status in ("optimal", "suboptimal")
        assert sol.optimal_lap_time_s > 10.0

    @needs_casadi
    def test_ocp_faster_than_qss(self):
        track = _oval_track(n=100)
        vp = _default_vehicle()

        sol_qss = solve_qss(track, vp)
        sol_ocp = solve_minimum_time(
            track, vp, n_points=100, max_time_s=60.0,
        )

        # OCP should be equal or faster (lower lap time)
        assert sol_ocp.optimal_lap_time_s <= sol_qss.optimal_lap_time_s * 1.01
