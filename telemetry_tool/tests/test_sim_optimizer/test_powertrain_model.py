"""Tests for powertrain model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.powertrain_model import (
    PowertrainModel,
    identify_powertrain_model,
    _G,
)


# ---------------------------------------------------------------------------
# Unit tests for PowertrainModel methods
# ---------------------------------------------------------------------------


def test_max_drive_accel():
    """Model with gear 3 torque map should produce accel > 0."""
    rpm_arr = np.array([3000.0, 5000.0, 7000.0])
    torque_arr = np.array([300.0, 350.0, 280.0])
    model = PowertrainModel(
        gear_torque_maps={3: (rpm_arr, torque_arr)},
        wheel_radius_m=0.33,
        transmission_efficiency=0.93,
        rr_c0=0.012,
        rr_c1=0.00008,
    )
    accel = model.max_drive_accel(speed_mps=30.0, gear=3, mass_kg=1200.0)
    assert accel > 0, f"Expected positive accel, got {accel}"


def test_rolling_resistance():
    """Rolling resistance at 30 m/s matches formula (c0 + c1*v) * g."""
    model = PowertrainModel(
        rr_c0=0.012,
        rr_c1=0.00008,
    )
    rr = model.rolling_resistance_accel(30.0)
    expected = (0.012 + 0.00008 * 30.0) * _G
    assert abs(rr - expected) < 1e-10, f"Expected {expected}, got {rr}"


def test_optimal_gear():
    """With gears 3 and 4, optimal_gear returns the one with more torque."""
    # Gear 3: high torque
    rpm3 = np.array([3000.0, 5000.0, 7000.0])
    torque3 = np.array([400.0, 450.0, 380.0])
    # Gear 4: lower torque
    rpm4 = np.array([3000.0, 5000.0, 7000.0])
    torque4 = np.array([200.0, 220.0, 180.0])
    model = PowertrainModel(
        gear_torque_maps={
            3: (rpm3, torque3),
            4: (rpm4, torque4),
        },
        wheel_radius_m=0.33,
        transmission_efficiency=0.93,
    )
    best = model.optimal_gear(speed_mps=30.0, mass_kg=1200.0)
    # Gear 3 has higher torque so should produce more accel
    assert best in (3, 4), f"Expected gear 3 or 4, got {best}"


# ---------------------------------------------------------------------------
# Integration tests for identify_powertrain_model
# ---------------------------------------------------------------------------


def test_identify_from_full_throttle(sim_config):
    """200 full-throttle samples in gear 3 should produce a gear-3 map."""
    rng = np.random.default_rng(99)
    n = 200
    rpm = np.linspace(3000, 8000, n) + rng.normal(0, 50, n)
    gear = np.full(n, 3, dtype=float)
    throttle = np.ones(n)
    speed_mps = np.linspace(20, 50, n)
    long_accel = np.full(n, 4.0) + rng.normal(0, 0.2, n)

    model = identify_powertrain_model(
        rpm=rpm,
        gear=gear,
        throttle=throttle,
        speed_mps=speed_mps,
        long_accel=long_accel,
        mass_kg=1200.0,
        config=sim_config,
    )
    assert 3 in model.gear_torque_maps, (
        f"Expected gear 3 in maps, got {list(model.gear_torque_maps.keys())}"
    )
    rpm_bins, torque_bins = model.gear_torque_maps[3]
    assert len(rpm_bins) >= 3
    assert all(t > 0 for t in torque_bins)


def test_fallback_on_no_data(sim_config):
    """Single low-throttle sample should produce empty gear_torque_maps."""
    model = identify_powertrain_model(
        rpm=np.array([4000.0]),
        gear=np.array([3.0]),
        throttle=np.array([0.5]),
        speed_mps=np.array([30.0]),
        long_accel=np.array([1.0]),
        mass_kg=1200.0,
        config=sim_config,
    )
    assert len(model.gear_torque_maps) == 0, (
        f"Expected empty maps, got {list(model.gear_torque_maps.keys())}"
    )
