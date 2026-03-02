"""Tests for telemetry_tool.physics.tire_thermal module."""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from physics.tire_thermal import (
    analyze_camber_from_zones,
    analyze_tire_session,
    compute_grip_factor,
    compute_thermal_balance,
    detect_optimal_window,
    predict_tire_degradation,
)


# ===================================================================
# TestGripFactor
# ===================================================================

class TestGripFactor:
    """Tests for compute_grip_factor."""

    def test_optimal_temperature(self):
        """Temperature inside optimal window returns 1.0."""
        assert compute_grip_factor(90.0) == 1.0

    def test_at_lower_bound(self):
        """Exactly at optimal_low returns 1.0."""
        assert compute_grip_factor(80.0) == 1.0

    def test_at_upper_bound(self):
        """Exactly at optimal_high returns 1.0."""
        assert compute_grip_factor(100.0) == 1.0

    def test_cold_temperature(self):
        """70C is below optimal -> grip < 1.0 but > 0."""
        grip = compute_grip_factor(70.0)
        assert 0.0 < grip < 1.0

    def test_overheated(self):
        """110C is above optimal -> grip < 1.0 but > 0."""
        grip = compute_grip_factor(110.0)
        assert 0.0 < grip < 1.0

    def test_extreme_cold(self):
        """40C is far below optimal -> clamps to 0.0."""
        grip = compute_grip_factor(40.0)
        assert grip == 0.0

    def test_extreme_hot(self):
        """150C is far above optimal -> clamps to 0.0."""
        grip = compute_grip_factor(150.0)
        assert grip == 0.0

    def test_clamp_floor(self):
        """Extreme cold should clamp to 0.0, not go negative."""
        grip = compute_grip_factor(-50.0)
        assert grip == 0.0

    def test_clamp_ceiling(self):
        """Very extreme hot should clamp to 0.0 not go negative."""
        grip = compute_grip_factor(250.0)
        assert grip == 0.0

    def test_cold_worse_than_warm(self):
        """70C (slightly cold) should have higher grip than 40C."""
        assert compute_grip_factor(70.0) > compute_grip_factor(40.0)

    def test_nan_returns_zero(self):
        """NaN input returns 0.0."""
        assert compute_grip_factor(float("nan")) == 0.0

    def test_custom_window(self):
        """Custom optimal window respected."""
        grip = compute_grip_factor(60.0, optimal_low=50.0, optimal_high=70.0)
        assert grip == 1.0

    def test_asymmetric_decay(self):
        """Hot side decays faster than cold side (k_hot > k_cold)."""
        # 10 degrees outside window on each side
        grip_cold = compute_grip_factor(70.0)  # 10 below 80
        grip_hot = compute_grip_factor(110.0)  # 10 above 100
        assert grip_cold > grip_hot  # hot decays faster


# ===================================================================
# TestThermalBalance
# ===================================================================

class TestThermalBalance:
    """Tests for compute_thermal_balance."""

    def test_balanced(self):
        """All four tyres at same temp -> good rating."""
        result = compute_thermal_balance(90.0, 90.0, 90.0, 90.0)
        assert result["balance_rating"] == "good"
        assert result["worst_imbalance"] == 0.0

    def test_lr_imbalance_front(self):
        """Big left-right delta on front -> poor."""
        result = compute_thermal_balance(100.0, 80.0, 90.0, 90.0)
        assert result["lr_front_delta"] == 20.0
        assert result["balance_rating"] == "poor"

    def test_lr_imbalance_rear(self):
        """Big left-right delta on rear."""
        result = compute_thermal_balance(90.0, 90.0, 100.0, 80.0)
        assert result["lr_rear_delta"] == 20.0
        assert result["balance_rating"] == "poor"

    def test_fr_imbalance(self):
        """Big front-rear delta."""
        result = compute_thermal_balance(100.0, 100.0, 80.0, 80.0)
        assert result["fr_delta"] == 20.0
        assert result["balance_rating"] == "poor"

    def test_marginal(self):
        """Moderate imbalance -> marginal."""
        result = compute_thermal_balance(93.0, 86.0, 90.0, 90.0)
        assert result["balance_rating"] == "marginal"

    def test_nan_input(self):
        """NaN input -> unknown rating."""
        result = compute_thermal_balance(float("nan"), 90.0, 90.0, 90.0)
        assert result["balance_rating"] == "unknown"
        assert np.isnan(result["worst_imbalance"])


# ===================================================================
# TestCamber
# ===================================================================

class TestCamber:
    """Tests for analyze_camber_from_zones."""

    def test_optimal(self):
        """Inner ~ mid ~ outer -> optimal."""
        result = analyze_camber_from_zones(92.0, 91.0, 90.0)
        assert result["classification"] == "optimal"

    def test_too_much(self):
        """Inner >> outer -> too much camber."""
        result = analyze_camber_from_zones(100.0, 90.0, 80.0)
        assert result["classification"] == "too_much"
        assert result["delta"] > 0

    def test_too_little(self):
        """Outer >> inner -> too little camber."""
        result = analyze_camber_from_zones(80.0, 90.0, 100.0)
        assert result["classification"] == "too_little"
        assert result["delta"] < 0

    def test_nan_input(self):
        """NaN input -> unknown."""
        result = analyze_camber_from_zones(float("nan"), 90.0, 90.0)
        assert result["classification"] == "unknown"

    def test_custom_threshold(self):
        """Custom threshold changes classification boundary."""
        # 6 degree delta, default threshold=5 -> too_much
        result_default = analyze_camber_from_zones(96.0, 93.0, 90.0)
        assert result_default["classification"] == "too_much"
        # Same temps, threshold=10 -> optimal
        result_wide = analyze_camber_from_zones(96.0, 93.0, 90.0, threshold=10.0)
        assert result_wide["classification"] == "optimal"


# ===================================================================
# TestDegradation
# ===================================================================

class TestDegradation:
    """Tests for predict_tire_degradation."""

    def test_stable_temps(self):
        """Flat temps across laps -> low degradation."""
        laps = [
            {"lap": i, "fl": 90.0, "fr": 90.0, "rl": 90.0, "rr": 90.0}
            for i in range(1, 11)
        ]
        result = predict_tire_degradation(laps)
        assert result["degradation_rate"] == "low"
        assert abs(result["temp_rise_per_lap"]) < 0.5

    def test_rising_temps(self):
        """Climbing temps -> high degradation."""
        laps = [
            {"lap": i, "fl": 80 + i * 3, "fr": 80 + i * 3,
             "rl": 80 + i * 3, "rr": 80 + i * 3}
            for i in range(1, 11)
        ]
        result = predict_tire_degradation(laps)
        assert result["degradation_rate"] == "high"
        assert result["temp_rise_per_lap"] > 1.5

    def test_moderate_rise(self):
        """Moderate temp rise -> moderate degradation."""
        laps = [
            {"lap": i, "fl": 85 + i * 0.8, "fr": 85 + i * 0.8,
             "rl": 85 + i * 0.8, "rr": 85 + i * 0.8}
            for i in range(1, 11)
        ]
        result = predict_tire_degradation(laps)
        assert result["degradation_rate"] == "moderate"

    def test_single_lap(self):
        """Only one lap entry -> handle gracefully."""
        laps = [{"lap": 1, "fl": 90.0, "fr": 90.0, "rl": 90.0, "rr": 90.0}]
        result = predict_tire_degradation(laps)
        assert result["degradation_rate"] == "unknown"

    def test_empty_input(self):
        """Empty list -> handle gracefully."""
        result = predict_tire_degradation([])
        assert result["degradation_rate"] == "unknown"
        assert result["temp_rise_per_lap"] == 0.0

    def test_grip_window_estimate(self):
        """Rising from 85C -> should estimate laps until 100C."""
        laps = [
            {"lap": i, "fl": 85 + i * 1.0, "fr": 85 + i * 1.0,
             "rl": 85 + i * 1.0, "rr": 85 + i * 1.0}
            for i in range(1, 6)
        ]
        result = predict_tire_degradation(laps)
        assert result["estimated_grip_window_laps"] > 0


# ===================================================================
# TestOptimalWindow
# ===================================================================

class TestOptimalWindow:
    """Tests for detect_optimal_window."""

    def test_finds_best_range(self):
        """Grip peaks at 85-95C -> returns those bounds."""
        np.random.seed(42)
        n = 1000
        temps = np.random.uniform(60.0, 120.0, n)
        # Grip peaks in 85-95 range
        grip = np.where(
            (temps >= 85) & (temps <= 95),
            2.0 + np.random.normal(0, 0.1, n),
            0.5 + np.random.normal(0, 0.1, n),
        )
        grip = np.abs(grip)

        low, high = detect_optimal_window(temps, grip, bin_width=5.0)
        # Optimal window should overlap with 85-95
        assert low <= 90.0
        assert high >= 90.0

    def test_fallback_on_empty(self):
        """Empty arrays -> default (80, 100)."""
        low, high = detect_optimal_window(np.array([]), np.array([]))
        assert low == 80.0
        assert high == 100.0

    def test_fallback_on_nans(self):
        """All-NaN arrays -> default (80, 100)."""
        nans = np.full(10, np.nan)
        low, high = detect_optimal_window(nans, nans)
        assert low == 80.0
        assert high == 100.0

    def test_single_point(self):
        """Single data point -> fallback."""
        low, high = detect_optimal_window(np.array([90.0]), np.array([1.5]))
        assert low == 80.0
        assert high == 100.0

    def test_uniform_grip(self):
        """All temps have same grip -> entire range is optimal."""
        temps = np.linspace(70, 110, 100)
        grip = np.ones(100) * 1.5
        low, high = detect_optimal_window(temps, grip)
        # Window should span most of the range
        assert high - low >= 30.0


# ===================================================================
# TestAnalyzeTireSession
# ===================================================================

class TestAnalyzeTireSession:
    """Tests for analyze_tire_session master function."""

    def _make_lap_df(self, n=100, base_temp=90.0):
        """Helper to create a single-lap DataFrame with tire data."""
        return pd.DataFrame({
            "distance_m": np.linspace(0, 1000, n),
            "tire_temp_fl": np.full(n, base_temp),
            "tire_temp_fr": np.full(n, base_temp + 2),
            "tire_temp_rl": np.full(n, base_temp - 1),
            "tire_temp_rr": np.full(n, base_temp + 1),
            "accel_lat_mps2": np.sin(np.linspace(0, 4 * np.pi, n)) * 1.5,
        })

    def test_no_tire_data(self):
        """DataFrame without tire columns -> has_tire_data=False."""
        df = pd.DataFrame({
            "distance_m": np.linspace(0, 1000, 50),
            "speed_mps": np.ones(50) * 20.0,
        })
        result = analyze_tire_session({1: df})
        assert result["has_tire_data"] is False

    def test_with_tire_data(self):
        """DataFrames with tire columns -> produces balance and degradation."""
        laps = {i: self._make_lap_df(base_temp=85 + i) for i in range(1, 6)}
        result = analyze_tire_session(laps)
        assert result["has_tire_data"] is True
        assert len(result["balance"]) == 5
        assert "degradation_rate" in result["degradation"]

    def test_empty_input(self):
        """Empty resampled_laps -> graceful default."""
        result = analyze_tire_session({})
        assert result["has_tire_data"] is False
