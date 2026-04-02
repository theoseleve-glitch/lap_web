"""Tests for input reconstruction from theoretical speed profiles."""
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
from telemetry_tool.sim_optimizer.reconstruction.input_trace import (
    TheoreticalInputTrace,
    reconstruct_inputs,
)
from telemetry_tool.sim_optimizer.solver.qss_enhanced import compute_sim_theoretical_lap


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


def _make_oval_geometry(
    straight_length: float = 200.0,
    corner_radius: float = 33.33,
    ds: float = 0.5,
) -> TrackGeometry:
    """Build a simple oval: two straights + two semicircles (~500 m)."""
    corner_length = math.pi * corner_radius
    lap_length = 2 * straight_length + 2 * corner_length

    dist_list: list[float] = []
    kappa_list: list[float] = []
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


@pytest.fixture
def oval_result(simple_vehicle: VehicleModel) -> tuple[TheoreticalInputTrace, TrackGeometry, VehicleModel]:
    """Run QSS solver on oval, then reconstruct inputs."""
    geom = _make_oval_geometry()
    config = SimOptimizerConfig(solver_apex_curvature_threshold=0.001)
    theoretical = compute_sim_theoretical_lap(geom, simple_vehicle, config=config)
    trace = reconstruct_inputs(theoretical, simple_vehicle, geom)
    return trace, geom, simple_vehicle


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestInputReconstruction:

    def test_arrays_same_length(self, oval_result):
        trace, geom, _ = oval_result
        n = len(geom.distance_m)
        assert len(trace.distance_m) == n
        assert len(trace.speed_mps) == n
        assert len(trace.throttle_pct) == n
        assert len(trace.brake_pct) == n
        assert len(trace.steering_deg) == n
        assert len(trace.gear) == n
        assert len(trace.limit_type) == n

    def test_throttle_brake_exclusive(self, oval_result):
        trace, _, _ = oval_result
        for i in range(len(trace.throttle_pct)):
            if trace.throttle_pct[i] > 0.01:
                assert trace.brake_pct[i] < 0.01, (
                    f"At i={i}: throttle={trace.throttle_pct[i]:.3f} "
                    f"but brake={trace.brake_pct[i]:.3f}"
                )

    def test_steering_nonzero_in_corners(self, oval_result):
        trace, geom, _ = oval_result
        corner_mask = geom.curvature_1pm > 0.01
        steering_in_corners = np.abs(trace.steering_deg[corner_mask])
        assert np.all(steering_in_corners > 0.1), (
            f"Min |steering| in corners: {float(np.min(steering_in_corners)):.3f} deg"
        )

    def test_gear_positive(self, oval_result):
        trace, _, _ = oval_result
        assert np.all(trace.gear >= 1), (
            f"Min gear: {int(np.min(trace.gear))}"
        )

    def test_throttle_in_range(self, oval_result):
        trace, _, _ = oval_result
        assert float(np.min(trace.throttle_pct)) >= 0.0
        assert float(np.max(trace.throttle_pct)) <= 1.0

    def test_brake_in_range(self, oval_result):
        trace, _, _ = oval_result
        assert float(np.min(trace.brake_pct)) >= 0.0
        assert float(np.max(trace.brake_pct)) <= 1.0
