"""Tests for the composite VehicleModel."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.aero_model import AeroModel
from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel
from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel
from telemetry_tool.sim_optimizer.param_id.powertrain_model import PowertrainModel
from telemetry_tool.sim_optimizer.param_id.suspension_model import SuspensionModel
from telemetry_tool.sim_optimizer.param_id.tyre_model import TyreModel
from telemetry_tool.sim_optimizer.param_id.vehicle_model import VehicleModel

_G = 9.80665


@pytest.fixture
def sample_vehicle_model() -> VehicleModel:
    """Build a VehicleModel with realistic GT3-ish parameters."""
    tyre = TyreModel(mu_lat=1.3, mu_long=1.3)
    aero = AeroModel(cda=1.0, cla=2.0, air_density=1.18)
    powertrain = PowertrainModel(
        gear_torque_maps={
            3: (
                np.array([4000.0, 6000.0, 8000.0]),
                np.array([300.0, 350.0, 280.0]),
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
    mass = MassModel(base_mass_kg=1200.0, fuel_density_kg_l=0.75, bop_penalty_kg=0.0)

    return VehicleModel(
        tyre=tyre,
        aero=aero,
        powertrain=powertrain,
        brake=brake,
        suspension=suspension,
        mass=mass,
    )


def test_max_lateral_g(sample_vehicle_model: VehicleModel) -> None:
    lat = sample_vehicle_model.max_lateral_g(30.0)
    assert lat > 0
    assert lat < 3.0 * _G


def test_downforce_increases_lateral_g(sample_vehicle_model: VehicleModel) -> None:
    lat_slow = sample_vehicle_model.max_lateral_g(10.0)
    lat_fast = sample_vehicle_model.max_lateral_g(50.0)
    assert lat_fast > lat_slow


def test_max_traction_g(sample_vehicle_model: VehicleModel) -> None:
    traction = sample_vehicle_model.max_traction_g(30.0, gear=3)
    assert traction > 0


def test_max_braking_g(sample_vehicle_model: VehicleModel) -> None:
    braking = sample_vehicle_model.max_braking_g(30.0)
    assert braking > 0


def test_combined_limit(sample_vehicle_model: VehicleModel) -> None:
    # Braking combined with moderate lateral should be within envelope
    assert sample_vehicle_model.combined_limit(ax=-5.0, ay=5.0, speed_mps=30.0) is True
    # Extreme combined load should exceed envelope
    assert sample_vehicle_model.combined_limit(ax=-20.0, ay=20.0, speed_mps=30.0) is False


def test_total_mass_with_fuel(sample_vehicle_model: VehicleModel) -> None:
    m = sample_vehicle_model.total_mass_kg(fuel_level_l=40.0)
    assert m == pytest.approx(1200.0 + 40.0 * 0.75)


def test_to_dict(sample_vehicle_model: VehicleModel) -> None:
    d = sample_vehicle_model.to_dict()
    assert "tyre" in d
    assert "aero" in d
    assert "mass" in d
    assert "powertrain" in d
    assert "brake" in d
    assert "suspension" in d
    assert "p_combined" in d
