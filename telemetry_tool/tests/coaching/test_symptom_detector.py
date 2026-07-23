"""Tests for symptom detector with tier fallback."""
import pytest
import numpy as np
import pandas as pd
from coaching.analyzers.symptom_detector import detect_symptoms
from coaching.models import SymptomDetection


def _make_early_apex_lap():
    """Lap where steering increases past apex and road unused at exit."""
    n = 100
    dist = np.linspace(100, 200, n)
    speed = np.full(n, 20.0)
    steering = np.zeros(n)
    # Steering increases past apex (index 50)
    steering[30:70] = np.linspace(0, 60, 40)  # keeps increasing past midpoint
    lateral_pos = np.zeros(n)
    lateral_pos[80:] = 1.5  # 1.5m inside at exit = road unused
    return pd.DataFrame({
        "Distance (m)": dist, "Speed (m/s)": speed,
        "Steering angle (deg)": steering,
        "Lateral position (m)": lateral_pos,
    })


class TestSymptomDetector:
    def test_detects_early_apex_tier1(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = _make_early_apex_lap()
        result = detect_symptoms(corner, lap)
        assert isinstance(result, SymptomDetection)
        symptom_ids = [s.symptom_id for s in result.symptoms]
        assert "early_apex" in symptom_ids

    def test_tier2_no_steering_still_detects_via_position(self):
        """Without steering column, detect early apex via exit position."""
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        n = 100
        dist = np.linspace(100, 200, n)
        lap = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": np.full(n, 20.0),
            "Lateral position (m)": np.concatenate([np.zeros(80), np.full(20, 1.5)]),
        })
        result = detect_symptoms(corner, lap)
        symptom_ids = [s.symptom_id for s in result.symptoms]
        assert "early_apex" in symptom_ids

    def test_tier1_symptom_not_emitted_without_tier1_channels(self):
        """understeer_entry requires lat-accel + steering; GPS-only should not emit it."""
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(100, 200, 50),
            "Speed (m/s)": np.full(50, 20.0),
        })
        result = detect_symptoms(corner, lap)
        symptom_ids = [s.symptom_id for s in result.symptoms]
        assert "understeer_entry" not in symptom_ids

    def test_confidence_between_0_and_1(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = _make_early_apex_lap()
        result = detect_symptoms(corner, lap)
        for s in result.symptoms:
            assert 0 <= s.confidence <= 1
