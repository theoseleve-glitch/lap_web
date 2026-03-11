"""Tests for trail brake 4-block analyzer."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.trail_brake import analyze_trail_braking
from telemetry_tool.coaching.models import TrailBrakeAssessment, BrakingBlock


def _make_corner_lap(has_trail=True, has_pedal_channels=True):
    """
    Synthetic corner data: distance 100-200m.
    With trail-braking: brake overlaps with steering from 130-150m.
    Without: brake ends at 125m before steering starts at 130m.
    """
    n = 100
    dist = np.linspace(100, 200, n)
    speed = np.linspace(30, 15, n)  # decelerating into corner
    time_s = np.cumsum(np.diff(dist, prepend=dist[0]) / np.maximum(speed, 1))

    if has_pedal_channels:
        throttle = np.zeros(n)
        brake = np.zeros(n)
        steering = np.zeros(n)

        if has_trail:
            # Block 1 (100-105): throttle→brake transition
            throttle[:5] = np.linspace(80, 0, 5)
            # Block 2 (105-130): straight-line braking
            brake[5:30] = np.linspace(90, 70, 25)
            # Block 3 (130-150): trail-brake (brake + steer overlap)
            brake[30:50] = np.linspace(70, 0, 20)
            steering[30:50] = np.linspace(0, 45, 20)
            # Block 4 (150-155): brake→throttle transition
            steering[50:] = np.linspace(45, 30, n - 50)
            throttle[55:] = np.linspace(0, 60, n - 55)
        else:
            # No trail: brake ends before steering starts
            brake[5:25] = 80.0
            steering[30:] = 40.0
            throttle[55:] = 60.0

        return pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": speed, "Time (s)": time_s,
            "Throttle (%)": throttle, "Brake (%)": brake,
            "Steering angle (deg)": steering,
        })
    else:
        # Fallback: accel-only
        lat_accel = np.zeros(n)
        lon_accel = np.zeros(n)
        lon_accel[5:50] = -6.0  # braking
        lat_accel[30:] = 8.0    # cornering
        return pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": speed, "Time (s)": time_s,
            "Lateral acceleration (m/s2)": lat_accel,
            "Longitudinal acceleration (m/s2)": lon_accel,
        })


class TestTrailBrakeAnalyzer:
    def test_detects_four_blocks(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True)
        result = analyze_trail_braking(corner, lap)
        assert isinstance(result, TrailBrakeAssessment)
        assert len(result.blocks) == 4

    def test_trail_braking_detected(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True)
        result = analyze_trail_braking(corner, lap)
        assert result.has_trail_braking is True
        assert result.actual_overlap_m > 0

    def test_no_trail_braking_detected(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=False)
        result = analyze_trail_braking(corner, lap)
        assert result.has_trail_braking is False
        assert result.primary_issue == "no_trail_braking"

    def test_accel_fallback_tier(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True, has_pedal_channels=False)
        result = analyze_trail_braking(corner, lap)
        # Should still detect overlap from accel data
        assert isinstance(result, TrailBrakeAssessment)
        assert result.has_trail_braking is True

    def test_overall_score_range(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True)
        result = analyze_trail_braking(corner, lap)
        assert 0 <= result.overall_score <= 100
