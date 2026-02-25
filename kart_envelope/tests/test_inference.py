"""Tests for session scalar inference."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kart_envelope.config import default_config
from kart_envelope.inference.conditions import classify_conditions
from kart_envelope.inference.session_scalars import SessionScalars, infer_session_scalars


class TestInferScalars:
    def test_at_full_envelope(self, known_envelope):
        """Data generated at 100% of envelope → scalars ≈ 1.0."""
        np.random.seed(42)
        n = 2000
        v = np.random.uniform(4, 18, n)
        # Generate data at the envelope limits
        ay_max = 8.0
        ax_drive_max = 5.0
        ax_brake_max = 10.0
        ay = np.random.uniform(0, ay_max * 0.98, n)
        # Mix of traction and braking
        ax = np.where(np.random.rand(n) > 0.5,
                       np.random.uniform(0.5, ax_drive_max * 0.98, n),
                       -np.random.uniform(0.5, ax_brake_max * 0.98, n))

        laps = {1: pd.DataFrame({
            "speed_mps": v,
            "accel_long_mps2": ax,
            "accel_lat_mps2": ay,
        })}

        scalars = infer_session_scalars(laps, known_envelope, default_config())
        # With regularisation toward 1.0, should be close to 1.0
        assert scalars.mu_session == pytest.approx(1.0, abs=0.15)
        assert scalars.p_session == pytest.approx(1.0, abs=0.15)
        assert scalars.b_session == pytest.approx(1.0, abs=0.15)

    def test_at_80_percent(self, known_envelope):
        """Data at 80% of envelope → scalars ≈ 0.8."""
        np.random.seed(123)
        n = 2000
        scale = 0.80
        v = np.random.uniform(4, 18, n)
        ay = np.random.uniform(0, 8.0 * scale * 0.98, n)
        ax = np.where(np.random.rand(n) > 0.5,
                       np.random.uniform(0.5, 5.0 * scale * 0.98, n),
                       -np.random.uniform(0.5, 10.0 * scale * 0.98, n))

        laps = {1: pd.DataFrame({
            "speed_mps": v,
            "accel_long_mps2": ax,
            "accel_lat_mps2": ay,
        })}

        scalars = infer_session_scalars(laps, known_envelope, default_config())
        # With regularisation (lambda=0.1), raw 0.8 → ~0.82
        assert scalars.mu_session == pytest.approx(0.8, abs=0.15)
        assert scalars.p_session == pytest.approx(0.8, abs=0.15)

    def test_empty_data(self, known_envelope):
        """Empty data should return defaults."""
        laps = {}
        scalars = infer_session_scalars(laps, known_envelope)
        assert scalars.mu_session == 1.0
        assert scalars.confidence == 0.0


class TestClassifyConditions:
    def test_dry(self):
        s = SessionScalars(mu_session=0.95, p_session=1.0)
        assert classify_conditions(s) == "dry"

    def test_wet(self):
        s = SessionScalars(mu_session=0.55, p_session=0.8)
        assert classify_conditions(s) == "wet"

    def test_damp(self):
        s = SessionScalars(mu_session=0.72, p_session=0.9)
        assert classify_conditions(s) == "damp"

    def test_low_power(self):
        s = SessionScalars(mu_session=0.95, p_session=0.7)
        assert classify_conditions(s) == "low_power"
