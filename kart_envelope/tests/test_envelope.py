"""Tests for CapabilityEnvelope training and protocol compliance."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from kart_envelope.config import default_config
from kart_envelope.envelope.capability import (
    CapabilityEnvelope,
    EnvelopeError,
    train_capability_envelope,
)


class TestCapabilityEnvelope:
    def test_lateral_max(self, known_envelope):
        """lateral_max should return 8.0 at any speed in range."""
        assert float(known_envelope.lateral_max(10.0)) == pytest.approx(8.0)

    def test_traction_max(self, known_envelope):
        assert float(known_envelope.traction_max(10.0)) == pytest.approx(5.0)

    def test_braking_max(self, known_envelope):
        assert float(known_envelope.braking_max(10.0)) == pytest.approx(10.0)

    def test_max_cornering_speed_circle(self, known_envelope):
        """On a circle with R=25m (kappa=0.04), v_max = sqrt(8/0.04) = 14.14."""
        v = known_envelope.max_cornering_speed(0.04)
        assert v == pytest.approx(14.14, abs=0.2)

    def test_max_lateral_under_braking(self, known_envelope):
        """Combined slip should reduce available lateral grip."""
        full_lat = known_envelope.max_lateral_accel(10.0, 0.0)
        reduced = known_envelope.max_lateral_accel(10.0, 3.0)
        assert reduced < full_lat

    def test_max_long_under_cornering(self, known_envelope):
        """Combined slip should reduce available traction under cornering."""
        full_trac = known_envelope.max_longitudinal_accel(10.0, 0.0)
        reduced = known_envelope.max_longitudinal_accel(10.0, 4.0)
        assert reduced < full_trac

    def test_scaled(self, known_envelope):
        """Scaling should multiply limits."""
        scaled = known_envelope.scaled(mu=0.8, p_drive=0.7, b_brake=0.9)
        assert float(scaled.lateral_max(10.0)) == pytest.approx(8.0 * 0.8)
        assert float(scaled.traction_max(10.0)) == pytest.approx(5.0 * 0.7)
        assert float(scaled.braking_max(10.0)) == pytest.approx(10.0 * 0.9)

    def test_serialisation_roundtrip(self, known_envelope):
        """to_dict → from_dict should preserve values."""
        d = known_envelope.to_dict()
        restored = CapabilityEnvelope.from_dict(d)
        assert float(restored.lateral_max(10.0)) == pytest.approx(
            float(known_envelope.lateral_max(10.0)))
        assert restored.p_combined == pytest.approx(known_envelope.p_combined)

    def test_save_load_roundtrip(self, known_envelope, tmp_path):
        path = tmp_path / "test_envelope.json"
        known_envelope.save(path)
        loaded = CapabilityEnvelope.load(path)
        assert loaded.p_combined == known_envelope.p_combined
        np.testing.assert_allclose(loaded.ay_max, known_envelope.ay_max)


class TestTrainEnvelope:
    def test_train_from_synthetic(self, synthetic_oval_laps):
        """Training on synthetic data should produce physically plausible limits."""
        cfg = default_config()
        envelope = train_capability_envelope(
            [synthetic_oval_laps], config=cfg, track_id="test", kart_id="test",
        )
        # Limits should be positive
        assert np.all(envelope.ay_max > 0)
        assert np.all(envelope.ax_drive_max > 0)
        assert np.all(envelope.ax_brake_max > 0)
        # p should be in expected range
        assert 1.0 <= envelope.p_combined <= 3.0

    def test_insufficient_data(self):
        """Should raise EnvelopeError with < 50 samples."""
        tiny = {1: pd.DataFrame({
            "speed_mps": [5.0],
            "accel_long_mps2": [1.0],
            "accel_lat_mps2": [1.0],
        })}
        with pytest.raises(EnvelopeError):
            train_capability_envelope([tiny])


# Need pandas import for test_insufficient_data
import pandas as pd
