"""Tests for the enhanced QSS solver (sim_optimizer.solver.qss_enhanced)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from kart_envelope.track.geometry import TrackGeometry
from telemetry_tool.sim_optimizer.config import SimOptimizerConfig
from telemetry_tool.sim_optimizer.param_id.aero_model import AeroModel
from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel
from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel
from telemetry_tool.sim_optimizer.param_id.powertrain_model import PowertrainModel
from telemetry_tool.sim_optimizer.param_id.suspension_model import SuspensionModel
from telemetry_tool.sim_optimizer.param_id.tyre_model import TyreModel
from telemetry_tool.sim_optimizer.param_id.vehicle_model import VehicleModel
from telemetry_tool.sim_optimizer.solver.qss_enhanced import (
    SimTheoreticalResult,
    compute_sim_theoretical_lap,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def simple_vehicle() -> VehicleModel:
    """A simple GT-class vehicle model for testing."""
    tyre = TyreModel(mu_lat=1.2, mu_long=1.2)
    aero = AeroModel(cda=0.8, cla=0.0, air_density=1.18)
    powertrain = PowertrainModel(
        gear_torque_maps={
            3: (
                np.array([3000, 5000, 7000, 9000], dtype=float),
                np.array([200, 250, 280, 220], dtype=float),
            ),
        },
        wheel_radius_m=0.33,
        transmission_efficiency=0.93,
        rr_c0=0.012,
        rr_c1=0.00008,
    )
    brake = BrakeModel(
        max_decel_mps2=12.0,
        brake_bias_front=0.56,
        fade_onset_temp_c=400.0,
        fade_rate=0.001,
    )
    suspension = SuspensionModel(
        spring_rate_lf=50000.0,
        spring_rate_rf=50000.0,
        spring_rate_lr=45000.0,
        spring_rate_rr=45000.0,
        static_defl_m=0.05,
    )
    mass = MassModel(base_mass_kg=1100.0, fuel_density_kg_l=0.75, bop_penalty_kg=0.0)
    return VehicleModel(
        tyre=tyre,
        aero=aero,
        powertrain=powertrain,
        brake=brake,
        suspension=suspension,
        mass=mass,
    )


def _make_circular_geometry(radius: float, lap_length: float, ds: float = 0.5) -> TrackGeometry:
    """Build a constant-curvature circular track."""
    n = int(lap_length / ds)
    dist = np.linspace(0, lap_length, n, endpoint=False)
    kappa = np.full(n, 1.0 / radius)
    heading = dist / radius  # theta = s / r
    x = radius * np.cos(heading)
    y = radius * np.sin(heading)
    return TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=lap_length,
        track_id="test_circular",
    )


def _make_straight_geometry(length: float, ds: float = 0.5) -> TrackGeometry:
    """Build a straight track (zero curvature)."""
    n = int(length / ds)
    dist = np.linspace(0, length, n, endpoint=False)
    kappa = np.zeros(n)
    heading = np.zeros(n)
    x = dist.copy()
    y = np.zeros(n)
    return TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=length,
        track_id="test_straight",
    )


def _make_oval_geometry(
    straight_length: float = 200.0,
    corner_radius: float = 33.33,
    ds: float = 0.5,
) -> TrackGeometry:
    """Build a simple oval: two straights + two semicircles."""
    corner_length = math.pi * corner_radius  # half-circle arc
    lap_length = 2 * straight_length + 2 * corner_length

    dist_list = []
    kappa_list = []
    s = 0.0

    # Straight 1
    while s < straight_length:
        dist_list.append(s)
        kappa_list.append(0.0)
        s += ds
    # Corner 1
    corner_end = straight_length + corner_length
    while s < corner_end:
        dist_list.append(s)
        kappa_list.append(1.0 / corner_radius)
        s += ds
    # Straight 2
    straight2_end = corner_end + straight_length
    while s < straight2_end:
        dist_list.append(s)
        kappa_list.append(0.0)
        s += ds
    # Corner 2
    while s < lap_length:
        dist_list.append(s)
        kappa_list.append(1.0 / corner_radius)
        s += ds

    dist = np.array(dist_list)
    kappa = np.array(kappa_list)
    n = len(dist)

    # Simple heading/xy (not geometrically exact, but sufficient for solver)
    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)

    return TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=lap_length,
        track_id="test_oval",
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestCircularTrack:
    """QSS solver on a constant-curvature circle."""

    def test_circular_track(self, simple_vehicle: VehicleModel) -> None:
        kappa = 0.04  # 1/25m radius
        radius = 1.0 / kappa
        lap_length = 500.0
        geom = _make_circular_geometry(radius, lap_length)
        config = SimOptimizerConfig(solver_apex_curvature_threshold=0.001)

        result = compute_sim_theoretical_lap(geom, simple_vehicle, config=config)

        assert isinstance(result, SimTheoreticalResult)

        # Expected corner speed: v = sqrt(ay_max / kappa)
        # ay_max ~ mu * g ~ 1.2 * 9.81 ~ 11.77 m/s^2
        # v_corner ~ sqrt(11.77 / 0.04) ~ 17.2 m/s
        mean_speed = float(np.mean(result.speed_profile_mps))
        expected_speed = 17.2
        assert mean_speed == pytest.approx(expected_speed, rel=0.15), (
            f"Mean speed {mean_speed:.1f} m/s not within 15% of {expected_speed:.1f}"
        )

        expected_time = lap_length / expected_speed
        assert result.lap_time_s == pytest.approx(expected_time, rel=0.15), (
            f"Lap time {result.lap_time_s:.1f}s not within 15% of {expected_time:.1f}s"
        )


class TestStraightTrack:
    """QSS solver on a straight track."""

    def test_straight_track(self, simple_vehicle: VehicleModel) -> None:
        geom = _make_straight_geometry(500.0)

        result = compute_sim_theoretical_lap(geom, simple_vehicle)

        assert isinstance(result, SimTheoreticalResult)
        # On a straight, speed should ramp up (power limited)
        # The profile should generally increase or be at max
        max_speed = float(np.max(result.speed_profile_mps))
        assert max_speed > 20.0, f"Max speed {max_speed:.1f} m/s too low for a straight"
        assert result.lap_time_s > 0


class TestOvalTrack:
    """QSS solver on an oval track."""

    def test_produces_valid_result(self, simple_vehicle: VehicleModel) -> None:
        geom = _make_oval_geometry()
        config = SimOptimizerConfig(solver_apex_curvature_threshold=0.001)

        result = compute_sim_theoretical_lap(geom, simple_vehicle, config=config)

        n = len(geom.distance_m)

        # All arrays same length
        assert len(result.speed_profile_mps) == n
        assert len(result.distance_m) == n
        assert len(result.accel_profile_mps2) == n
        assert len(result.cornering_limited) == n
        assert len(result.accel_limited) == n
        assert len(result.braking_limited) == n
        assert len(result.gear_profile) == n

        # Positive lap time
        assert result.lap_time_s > 0

        # Speeds within bounds
        v_min = config.solver_min_speed_mps
        v_max = config.solver_max_speed_mps
        assert float(np.min(result.speed_profile_mps)) >= v_min - 0.01
        assert float(np.max(result.speed_profile_mps)) <= v_max + 0.01

        # Method tag
        assert result.method == "sim_qss"

        # to_dict round-trip
        d = result.to_dict()
        assert "lap_time_s" in d
        assert "speed_profile_mps" in d
