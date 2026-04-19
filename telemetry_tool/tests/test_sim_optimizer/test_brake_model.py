"""Tests for brake model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel, identify_brake_model


class TestBrakeModel:
    """Unit tests for BrakeModel dataclass methods."""

    def test_max_decel(self):
        model = BrakeModel(max_decel_mps2=12, brake_bias_front=0.56,
                           fade_onset_temp_c=400, fade_rate=0.001)
        assert model.max_braking_decel(30.0, brake_temp_c=200.0) == pytest.approx(12.0)

    def test_fade_reduces_decel(self):
        model = BrakeModel(max_decel_mps2=12, brake_bias_front=0.56,
                           fade_onset_temp_c=400, fade_rate=0.001)
        cold = model.max_braking_decel(30.0, brake_temp_c=200.0)
        hot = model.max_braking_decel(30.0, brake_temp_c=600.0)
        assert hot < cold

    def test_inverse_pressure(self):
        model = BrakeModel(max_decel_mps2=12, brake_bias_front=0.56,
                           fade_onset_temp_c=400, fade_rate=0.001)
        pct = model.inverse_brake_pct(6.0, speed_mps=30.0)
        assert 0.0 < pct < 1.0


class TestIdentifyBrakeModel:
    """Tests for the identify_brake_model function."""

    def test_identify_from_braking_data(self, sim_config):
        rng = np.random.default_rng(42)
        n = 200
        model = identify_brake_model(
            speed_mps=np.linspace(50, 10, n),
            long_accel=np.linspace(-11, -3, n),
            brake=np.linspace(0.9, 0.3, n),
            brake_raw=np.linspace(0.9, 0.3, n) + rng.normal(0, 0.01, n),
            abs_active=np.zeros(n),
            brake_bias=np.full(n, 57.0),
            config=sim_config,
        )
        assert model.max_decel_mps2 > 0

    def test_fallback_on_no_data(self, sim_config):
        model = identify_brake_model(
            speed_mps=np.array([30.0]),
            long_accel=np.array([2.0]),
            brake=np.array([0.0]),
            brake_raw=np.array([0.0]),
            abs_active=np.array([0.0]),
            brake_bias=np.array([57.0]),
            config=sim_config,
        )
        assert model.max_decel_mps2 > 0
