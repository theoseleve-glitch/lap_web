"""Tests for suspension_model identification and SuspensionModel dataclass."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.suspension_model import (
    SuspensionModel,
    identify_suspension_model,
)


# ------------------------------------------------------------------
# SuspensionModel unit tests
# ------------------------------------------------------------------


def test_per_wheel_load():
    """wheel_load_n returns spring_rate * deflection for the requested corner."""
    model = SuspensionModel(
        spring_rate_lf=50000.0,
        spring_rate_rf=50000.0,
        spring_rate_lr=45000.0,
        spring_rate_rr=45000.0,
        static_defl_m=0.05,
    )
    # lf at 0.06 m -> 50000 * 0.06 = 3000 N
    assert model.wheel_load_n("lf", 0.06) == pytest.approx(3000.0, abs=1e-9)
    # rr at 0.05 m -> 45000 * 0.05 = 2250 N
    assert model.wheel_load_n("rr", 0.05) == pytest.approx(2250.0, abs=1e-9)


def test_total_load_equals_weight():
    """Sum of 4 wheel loads at static deflection must be positive."""
    model = SuspensionModel(
        spring_rate_lf=50000.0,
        spring_rate_rf=50000.0,
        spring_rate_lr=45000.0,
        spring_rate_rr=45000.0,
        static_defl_m=0.05,
    )
    total = sum(
        model.wheel_load_n(c, model.static_defl_m)
        for c in ("lf", "rf", "lr", "rr")
    )
    assert total > 0


# ------------------------------------------------------------------
# identify_suspension_model tests
# ------------------------------------------------------------------


def test_identify_from_shock_data(sim_config):
    """200 points with oscillating lat_accel and correlated deflection."""
    rng = np.random.default_rng(77)
    n = 200
    mass = 1200.0

    # Oscillating lateral accel (like alternating corners)
    t = np.linspace(0, 4 * np.pi, n)
    lat_accel = 8.0 * np.sin(t) + rng.normal(0, 0.1, n)
    long_accel = rng.normal(0, 0.5, n)

    # Shock deflection responds to lateral load transfer
    # sign convention: LF is inner (-1) so compresses when lat_accel < 0
    base_defl = 0.05
    k_true = 60000.0  # N/m true spring rate

    # delta_load = sign * lat_accel * mass * 0.35 / 1.5
    # delta_defl = delta_load / k_true
    defl_lf = base_defl + (-1.0) * lat_accel * mass * 0.35 / 1.5 / k_true + rng.normal(0, 0.0002, n)
    defl_rf = base_defl + (1.0) * lat_accel * mass * 0.35 / 1.5 / k_true + rng.normal(0, 0.0002, n)
    defl_lr = base_defl + (-1.0) * lat_accel * mass * 0.35 / 1.5 / k_true + rng.normal(0, 0.0002, n)
    defl_rr = base_defl + (1.0) * lat_accel * mass * 0.35 / 1.5 / k_true + rng.normal(0, 0.0002, n)

    model = identify_suspension_model(
        shock_defl_lf=defl_lf,
        shock_defl_rf=defl_rf,
        shock_defl_lr=defl_lr,
        shock_defl_rr=defl_rr,
        lat_accel=lat_accel,
        long_accel=long_accel,
        mass_kg=mass,
        config=sim_config,
    )

    assert model.spring_rate_lf > 0
    # With clean synthetic data, should recover close to true rate
    assert model.spring_rate_lf == pytest.approx(k_true, rel=0.20)
    assert model.spring_rate_rf == pytest.approx(k_true, rel=0.20)


def test_fallback_on_no_data(sim_config):
    """All deflection arrays are None -> model with default spring rates."""
    lat_accel = np.zeros(200)
    long_accel = np.zeros(200)

    model = identify_suspension_model(
        shock_defl_lf=None,
        shock_defl_rf=None,
        shock_defl_lr=None,
        shock_defl_rr=None,
        lat_accel=lat_accel,
        long_accel=long_accel,
        mass_kg=1200.0,
        config=sim_config,
    )

    assert model.spring_rate_lf > 0
    assert model.spring_rate_rf > 0
    assert model.spring_rate_lr > 0
    assert model.spring_rate_rr > 0
    assert model.static_defl_m == 0.05  # default
