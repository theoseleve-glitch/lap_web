"""Tests for mass model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel, identify_mass_model


class TestMassModel:
    """Unit tests for MassModel dataclass."""

    def test_fuel_burn_decreases_mass(self):
        model = MassModel(base_mass_kg=1200, fuel_density_kg_l=0.75, bop_penalty_kg=0)
        assert model.total_mass_kg(40) == pytest.approx(1230.0)
        assert model.total_mass_kg(20) == pytest.approx(1215.0)
        assert model.total_mass_kg(0) == pytest.approx(1200.0)

    def test_bop_penalty_added(self):
        model = MassModel(base_mass_kg=1200, fuel_density_kg_l=0.75, bop_penalty_kg=30)
        assert model.total_mass_kg(0) == pytest.approx(1230.0)

    def test_clamps_to_range(self, sim_config):
        model = MassModel(base_mass_kg=100, fuel_density_kg_l=0.75, bop_penalty_kg=0)
        clamped = model.clamped(sim_config.mass_clamp_lo_kg, sim_config.mass_clamp_hi_kg)
        assert clamped.base_mass_kg >= 500.0


class TestIdentifyMassModel:
    """Tests for the identify_mass_model function."""

    def test_identify_from_accel_data(self, sim_config):
        rng = np.random.default_rng(99)
        n = 100
        model = identify_mass_model(
            speed_mps=rng.uniform(20, 60, n),
            long_accel=rng.uniform(2.0, 5.0, n),
            throttle=np.full(n, 0.98),
            fuel_level_l=np.linspace(40, 35, n),
            bop_penalty_kg=np.zeros(n),
            config=sim_config,
        )
        assert model is not None
        assert model.base_mass_kg >= sim_config.mass_clamp_lo_kg
        assert model.base_mass_kg <= sim_config.mass_clamp_hi_kg

    def test_fallback_on_insufficient_data(self, sim_config):
        model = identify_mass_model(
            speed_mps=np.array([10.0]),
            long_accel=np.array([0.5]),
            throttle=np.array([0.5]),
            fuel_level_l=np.array([30.0]),
            bop_penalty_kg=np.array([0.0]),
            config=sim_config,
        )
        assert model.base_mass_kg == sim_config.mass_default_kg
