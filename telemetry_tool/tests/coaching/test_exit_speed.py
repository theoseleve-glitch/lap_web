"""Tests for exit speed cascade analyzer."""
import pytest
import numpy as np
import pandas as pd
from coaching.analyzers.exit_speed import analyze_exit_cascades
from coaching.models import ExitSpeedCascade


def _make_corners():
    """Two corners: C1 at 100-150m (before 200m straight), C3 at 400-430m (before 100m straight)."""
    return [
        {"corner_id": 1, "s_start": 100.0, "s_end": 150.0},
        {"corner_id": 3, "s_start": 400.0, "s_end": 430.0},
    ]


def _make_lap(exit_speeds_mps):
    """Lap DataFrame with distance grid and speed profile."""
    dist = np.arange(0, 600, 1.0)
    speed = np.full_like(dist, 30.0)
    # Set exit speeds at corner ends
    speed[150] = exit_speeds_mps[0]
    speed[430] = exit_speeds_mps[1]
    return pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": speed})


class TestExitSpeedCascade:
    def test_cascade_computed_for_each_corner(self):
        corners = _make_corners()
        driver_lap = _make_lap([20.0, 25.0])
        theo_lap = _make_lap([23.0, 27.0])
        track_length = 600.0
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, track_length)
        assert len(results) == 2
        assert all(isinstance(r, ExitSpeedCascade) for r in results)

    def test_full_integration_formula_used_for_low_speed(self):
        """At kart speeds (v_exit < 10 m/s), full integration must be used."""
        # Build custom laps with low exit speeds at s_end=80
        dist = np.arange(0, 600, 1.0)
        drv_speed = np.full_like(dist, 30.0)
        drv_speed[80] = 6.0  # ~22 km/h kart exit
        theo_speed = np.full_like(dist, 30.0)
        theo_speed[80] = 9.0  # ~32 km/h theoretical
        corners = [{"corner_id": 1, "s_start": 50.0, "s_end": 80.0}]
        driver_lap = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": drv_speed})
        theo_lap = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": theo_speed})
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, 600.0)
        r = results[0]
        assert r.time_loss_on_straight_s > 0

    def test_cascade_ratio(self):
        corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 150.0}]
        driver_lap = _make_lap([20.0, 25.0])
        theo_lap = _make_lap([23.0, 27.0])
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, 600.0)
        r = results[0]
        assert r.cascade_ratio == pytest.approx(
            r.time_loss_on_straight_s / max(r.time_loss_in_corner_s, 0.001), rel=0.01)

    def test_returns_empty_when_no_corners(self):
        results = analyze_exit_cascades([], pd.DataFrame(), pd.DataFrame(), 500.0)
        assert results == []

    def test_kmh_conversion(self):
        corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 150.0}]
        driver_lap = _make_lap([20.0, 25.0])
        theo_lap = _make_lap([23.0, 27.0])
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, 600.0)
        r = results[0]
        assert r.exit_gain_needed_kmh == pytest.approx(3.0 * 3.6, rel=0.01)
