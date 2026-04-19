"""Tests for aero_model identification and AeroModel dataclass."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.aero_model import (
    AeroModel,
    _G,
    identify_aero_model,
)


# ------------------------------------------------------------------
# AeroModel unit tests
# ------------------------------------------------------------------


def test_drag_accel():
    m = AeroModel(cda=1.0, cla=0.0, air_density=1.2)
    # 0.5 * 1.2 * 1.0 * 30^2 / 1200 = 0.5 * 1.2 * 900 / 1200 = 0.45
    assert m.drag_accel(30.0, 1200.0) == pytest.approx(0.45, abs=1e-9)


def test_downforce_factor():
    m = AeroModel(cda=1.0, cla=3.0, air_density=1.2)
    # 1 + 0.5 * 1.2 * 3.0 * 50^2 / (1200 * 9.80665)
    # = 1 + 0.5 * 1.2 * 3.0 * 2500 / 11767.98
    # = 1 + 4500 / 11767.98  ≈ 1.3822
    expected = 1.0 + 0.5 * 1.2 * 3.0 * 2500.0 / (1200.0 * _G)
    assert m.downforce_load_factor(50.0, 1200.0) == pytest.approx(expected, rel=1e-6)


def test_no_downforce_at_zero_cla():
    m = AeroModel(cda=1.0, cla=0.0, air_density=1.2)
    assert m.downforce_load_factor(50.0, 1200.0) == 1.0


# ------------------------------------------------------------------
# identify_aero_model tests
# ------------------------------------------------------------------


def test_identify_from_coastdown(sim_config):
    """200 synthetic coast-down points with known CdA=1.2 -> recovered within 15%."""
    rng = np.random.default_rng(99)
    n = 200
    cda_true = 1.2
    rho = 1.18
    mass = 1100.0

    speed = np.linspace(15, 50, n) + rng.normal(0, 0.1, n)
    # Pure drag deceleration + rolling resistance
    rr = sim_config.powertrain_rr_c0
    long_accel = -(0.5 * rho * cda_true * speed ** 2 / mass + rr * _G)

    throttle = np.zeros(n)
    brake = np.zeros(n)
    curvature = np.zeros(n)
    air_density = np.full(n, rho)
    car_dist_ahead = np.full(n, 200.0)

    model = identify_aero_model(
        speed_mps=speed,
        long_accel=long_accel,
        throttle=throttle,
        brake=brake,
        curvature=curvature,
        air_density=air_density,
        car_dist_ahead=car_dist_ahead,
        mass_kg=mass,
        config=sim_config,
    )

    assert model.source == "identified"
    assert model.cda == pytest.approx(cda_true, rel=0.15)


def test_cda_clamped(sim_config):
    m = AeroModel(cda=100.0, cla=0.0, air_density=1.2)
    c = m.clamped(sim_config)
    assert c.cda <= sim_config.aero_cda_clamp_hi  # 3.0


def test_fallback_on_no_coastdown(sim_config):
    """Only 1 sample with throttle=1.0 -> must return default CdA."""
    n = 1
    model = identify_aero_model(
        speed_mps=np.array([30.0]),
        long_accel=np.array([-2.0]),
        throttle=np.array([1.0]),
        brake=np.array([0.0]),
        curvature=np.array([0.0]),
        air_density=np.array([1.2]),
        car_dist_ahead=np.array([200.0]),
        mass_kg=1200.0,
        config=sim_config,
    )

    assert model.source == "default"
    assert model.cda == sim_config.aero_cda_default
