"""Tests for throttle lift detector."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.throttle_lift import detect_throttle_lifts
from telemetry_tool.coaching.models import ThrottleLiftEvent


def _make_lift_lap(drop_pct=60, lat_grip_pct=75):
    n = 100
    dist = np.linspace(100, 200, n)
    throttle = np.full(n, 70.0)
    throttle[50:53] = [70, 30, 10]  # abrupt lift at midpoint
    throttle[53:60] = np.linspace(10, 70, 7)  # recover
    lat_accel = np.full(n, lat_grip_pct / 100 * 10)  # as fraction of 10 m/s2 max
    return pd.DataFrame({
        "Distance (m)": dist, "Speed (m/s)": np.full(n, 25.0),
        "Throttle (%)": throttle,
        "Lateral acceleration (m/s2)": lat_accel,
        "Time (s)": np.linspace(0, 4, n),
    })


class TestThrottleLiftDetector:
    def test_detects_dangerous_lift(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_lift_lap(drop_pct=60, lat_grip_pct=75)
        results = detect_throttle_lifts(corner, lap, friction_max=10.0, vehicle_mass_kg=750.0)
        assert len(results) >= 1
        assert results[0].severity == "dangerous"

    def test_benign_lift(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_lift_lap(drop_pct=15, lat_grip_pct=30)
        results = detect_throttle_lifts(corner, lap, friction_max=10.0, vehicle_mass_kg=750.0)
        if results:
            assert results[0].severity == "benign"

    def test_no_throttle_channel_returns_empty(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(100, 200, 50),
            "Speed (m/s)": np.full(50, 25.0),
        })
        results = detect_throttle_lifts(corner, lap, friction_max=10.0, vehicle_mass_kg=750.0)
        assert results == []
