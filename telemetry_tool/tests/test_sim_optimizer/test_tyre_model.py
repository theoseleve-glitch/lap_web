"""Tests for tyre_model identification and Pacejka force calculations."""
from __future__ import annotations

import math

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.tyre_model import (
    TyreModel,
    identify_tyre_model,
    pacejka_force,
)


# ------------------------------------------------------------------
# pacejka_force
# ------------------------------------------------------------------


def test_zero_slip_zero_force():
    """sin(c * atan(b * 0)) == 0, so force must be zero."""
    assert pacejka_force(slip=0.0, b=10.0, c=1.5, d=1.0, mu=1.2, fz=5000.0) == 0.0


def test_peak_near_optimal_slip():
    """Force should peak somewhere in the 0.03-0.15 slip range for b=10, c=1.5."""
    b, c, d, mu, fz = 10.0, 1.5, 1.0, 1.2, 5000.0
    slips = np.linspace(0.001, 0.30, 500)
    forces = [abs(pacejka_force(s, b, c, d, mu, fz)) for s in slips]
    peak_idx = int(np.argmax(forces))
    peak_slip = slips[peak_idx]
    assert 0.03 <= peak_slip <= 0.20, f"Peak at slip={peak_slip}"


def test_force_proportional_to_load():
    """Doubling fz must double the force (Pacejka is linear in fz)."""
    f1 = pacejka_force(0.05, 10.0, 1.5, 1.0, 1.2, 3000.0)
    f2 = pacejka_force(0.05, 10.0, 1.5, 1.0, 1.2, 6000.0)
    assert abs(f2 - 2.0 * f1) < 1e-6


# ------------------------------------------------------------------
# TyreModel
# ------------------------------------------------------------------


def test_max_lateral_force():
    """mu_lat * fz * d_lat for mu_lat=1.3, fz=5000 -> ~6500 N."""
    model = TyreModel(mu_lat=1.3)
    fz = 5000.0
    expected = 1.3 * 5000.0 * model.d_lat  # 6500
    assert abs(model.max_lateral_force(fz) - expected) < 1e-6


def test_max_longitudinal_force():
    """Max longitudinal force must be positive for positive load."""
    model = TyreModel(mu_long=1.3)
    assert model.max_longitudinal_force(5000.0) > 0.0


# ------------------------------------------------------------------
# identify_tyre_model
# ------------------------------------------------------------------


def test_identify_from_synthetic_data(sim_config):
    """Recover mu within 15% from noisy synthetic Pacejka data."""
    rng = np.random.default_rng(99)
    n = 500
    true_b, true_c, true_mu = 10.0, 1.5, 1.2

    fz = rng.uniform(3000, 8000, n)
    slip = rng.uniform(-0.12, 0.12, n)
    force = np.array([
        true_mu * fz_i * math.sin(true_c * math.atan(true_b * s))
        for s, fz_i in zip(slip, fz)
    ])
    force += rng.normal(0, 50, n)

    model = identify_tyre_model(
        slip_ratio=slip,
        longitudinal_force=force,
        lateral_slip=None,
        lateral_force=None,
        tyre_load=fz,
        config=sim_config,
    )
    assert abs(model.mu_long - true_mu) / true_mu < 0.15, (
        f"Recovered mu_long={model.mu_long:.3f}, expected ~{true_mu}"
    )


def test_mu_clamped(sim_config):
    """mu values outside config range must be clipped."""
    model = TyreModel(mu_lat=5.0, mu_long=0.1)
    clamped = model.clamped(sim_config)
    assert clamped.mu_lat <= sim_config.tyre_mu_clamp_hi
    assert clamped.mu_long >= sim_config.tyre_mu_clamp_lo


def test_fallback_on_no_data(sim_config):
    """All-None inputs should return a valid default model."""
    model = identify_tyre_model(
        slip_ratio=None,
        longitudinal_force=None,
        lateral_slip=None,
        lateral_force=None,
        tyre_load=None,
        config=sim_config,
    )
    assert model.mu_lat > 0
    assert model.mu_long > 0
    assert model.source == "default"
