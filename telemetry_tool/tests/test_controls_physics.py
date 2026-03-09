"""Tests for the Tier 2 controls-physics module."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from physics.controls_physics import (
    analyze_corners_with_controls,
    compute_steering_smoothness,
    count_corrections,
    detect_brake_points,
    detect_coasting_zones,
    fit_power_curve,
    measure_throttle_application,
    measure_trail_braking,
    score_brake_modulation,
    score_shift_quality,
)

# ---------------------------------------------------------------------------
# Helpers for synthetic data
# ---------------------------------------------------------------------------

def _make_corners(n: int = 2, spacing: float = 200.0) -> list[dict]:
    """Generate *n* synthetic corners at regular spacing."""
    corners = []
    for i in range(n):
        base = 100.0 + i * spacing
        corners.append({
            "corner_id": i + 1,
            "entry_m": base,
            "apex_m": base + 30.0,
            "exit_m": base + 60.0,
        })
    return corners


def _make_distance(length: float = 500.0, step: float = 1.0) -> np.ndarray:
    return np.arange(0, length, step)


# =========================================================================
# BRAKE ANALYSIS
# =========================================================================


class TestBrakeAnalysis:

    def test_detect_brake_points_simple(self):
        """Ramp from 0 to 100 % -- should detect exactly one brake point."""
        d = _make_distance(100)
        brake = np.linspace(0, 100, len(d))
        pts = detect_brake_points(d, brake, threshold=5.0)
        assert len(pts) == 1
        # The brake point should be near where brake crosses 5 %
        assert 3.0 < pts[0] < 8.0

    def test_detect_brake_points_multiple(self):
        """Two brake zones separated by coast."""
        d = _make_distance(200)
        brake = np.zeros(len(d))
        brake[30:60] = 80.0   # first zone
        brake[130:160] = 90.0  # second zone
        pts = detect_brake_points(d, brake, threshold=5.0)
        assert len(pts) == 2
        assert abs(pts[0] - 30.0) < 2.0
        assert abs(pts[1] - 130.0) < 2.0

    def test_detect_brake_points_below_threshold(self):
        """Light braking never exceeds threshold -> empty list."""
        d = _make_distance(100)
        brake = np.full(len(d), 3.0)  # always below 5 %
        pts = detect_brake_points(d, brake, threshold=5.0)
        assert pts == []

    def test_detect_brake_points_empty_array(self):
        """Empty arrays -> empty list."""
        pts = detect_brake_points(np.array([]), np.array([]))
        assert pts == []

    def test_detect_brake_points_nan_handling(self):
        """NaN values treated as 0 -- should not crash."""
        d = _make_distance(50)
        brake = np.full(len(d), np.nan)
        brake[20:] = 50.0
        pts = detect_brake_points(d, brake, threshold=5.0)
        assert len(pts) >= 1

    def test_trail_braking_measurement(self):
        """Synthetic corner with overlapping brake + steering."""
        d = _make_distance(500)
        brake = np.zeros(len(d))
        steer = np.zeros(len(d))
        corners = _make_corners(1)  # entry=100, apex=130, exit=160

        # Brake from 90m to 145m (overlaps into corner)
        brake[90:145] = 60.0
        # Steering from 100m to 160m (the whole corner)
        steer[100:160] = 25.0

        result = measure_trail_braking(d, brake, steer, corners)
        assert len(result) == 1
        assert result[0]["corner_id"] == 1
        assert result[0]["trail_brake_pct"] > 0
        assert result[0]["trail_brake_duration_m"] > 0
        assert result[0]["peak_brake_in_turn"] == 60.0

    def test_trail_braking_no_overlap(self):
        """Brake and steering never overlap -> zero trail metrics."""
        d = _make_distance(500)
        brake = np.zeros(len(d))
        steer = np.zeros(len(d))
        corners = _make_corners(1)

        brake[50:90] = 80.0    # braking BEFORE corner
        steer[100:160] = 25.0  # steering IN corner (no brake)

        result = measure_trail_braking(d, brake, steer, corners)
        assert result[0]["trail_brake_pct"] == 0.0

    def test_brake_modulation_consistent(self):
        """Identical profiles across laps -> score near 1.0."""
        corners = _make_corners(1)
        profiles = []
        for _ in range(5):
            d = _make_distance(500)
            brake = np.zeros(len(d))
            brake[95:150] = 70.0  # identical brake zone
            profiles.append({"distances": d, "brake_pct": brake})

        score = score_brake_modulation(profiles, corners)
        assert score > 0.95

    def test_brake_modulation_inconsistent(self):
        """Very different profiles -> score well below 1.0."""
        corners = _make_corners(1)
        profiles = []
        rng = np.random.RandomState(42)
        for _ in range(5):
            d = _make_distance(500)
            brake = np.zeros(len(d))
            # Random brake intensity each lap (20-100)
            intensity = rng.uniform(20, 100)
            brake[95:150] = intensity
            profiles.append({"distances": d, "brake_pct": brake})

        score = score_brake_modulation(profiles, corners)
        assert score < 0.8

    def test_brake_modulation_empty(self):
        """Empty inputs -> 0.0."""
        assert score_brake_modulation([], []) == 0.0


# =========================================================================
# THROTTLE ANALYSIS
# =========================================================================


class TestThrottleAnalysis:

    def test_throttle_application_rate(self):
        """Linear throttle ramp on corner exit -> known rate."""
        d = _make_distance(500)
        throttle = np.zeros(len(d))
        corners = _make_corners(1)  # apex=130, exit=160

        # Linear ramp from 0 to 100% between apex (130) and exit (160) inclusive
        ramp = np.linspace(0, 100, 31)  # 31 points for indices 130..160
        throttle[130:161] = ramp

        result = measure_throttle_application(d, throttle, corners)
        assert len(result) == 1
        # Rate should be ~100/30 = ~3.33 pct/m
        rate = result[0]["exit_application_rate"]
        assert 2.5 < rate < 4.5

    def test_throttle_hesitation_zones(self):
        """Throttle < 20% within corner zone creates hesitation."""
        d = _make_distance(500)
        throttle = np.zeros(len(d))
        corners = _make_corners(1)  # entry=100, exit=160

        # Throttle at 10% in the middle of the corner (hesitation)
        throttle[100:120] = 10.0
        throttle[120:160] = 80.0

        result = measure_throttle_application(d, throttle, corners)
        assert len(result[0]["hesitation_zones"]) >= 1

    def test_coasting_detection(self):
        """Zone with both throttle=0 and brake=0."""
        d = _make_distance(200)
        throttle = np.full(len(d), 80.0)
        brake = np.zeros(len(d))

        # Coasting zone: 50m to 80m
        throttle[50:80] = 0.0
        brake[50:80] = 0.0

        zones = detect_coasting_zones(d, throttle, brake)
        assert len(zones) >= 1
        assert zones[0]["duration_m"] > 20

    def test_no_coasting(self):
        """Always on throttle or brake -> empty list."""
        d = _make_distance(200)
        throttle = np.full(len(d), 50.0)  # always on throttle
        brake = np.zeros(len(d))

        zones = detect_coasting_zones(d, throttle, brake)
        assert zones == []

    def test_coasting_empty_arrays(self):
        """Empty inputs -> empty list."""
        zones = detect_coasting_zones(np.array([]), np.array([]), np.array([]))
        assert zones == []

    def test_coasting_ignores_micro_zones(self):
        """Sub-half-metre coasting zone should be ignored."""
        d = np.array([0.0, 0.1, 0.2, 0.3, 10.0])
        throttle = np.array([50.0, 0.0, 0.0, 50.0, 50.0])
        brake = np.zeros(5)
        zones = detect_coasting_zones(d, throttle, brake)
        # The zone from 0.1 to 0.2 is only 0.1m -- should be filtered out
        assert len(zones) == 0


# =========================================================================
# STEERING ANALYSIS
# =========================================================================


class TestSteeringAnalysis:

    def test_smoothness_smooth_input(self):
        """Sine wave steering -> high smoothness."""
        d = _make_distance(500, step=0.5)
        steer = 30.0 * np.sin(2 * np.pi * d / 200.0)

        score = compute_steering_smoothness(d, steer)
        assert score > 0.8

    def test_smoothness_noisy_input(self):
        """Sine wave + heavy noise -> lower smoothness."""
        rng = np.random.RandomState(42)
        d = _make_distance(500, step=0.5)
        steer = 30.0 * np.sin(2 * np.pi * d / 200.0)
        steer += rng.normal(0, 15.0, len(d))  # heavy noise

        score = compute_steering_smoothness(d, steer)
        # Noisy should score lower than clean
        clean_score = compute_steering_smoothness(
            d, 30.0 * np.sin(2 * np.pi * d / 200.0)
        )
        assert score < clean_score

    def test_smoothness_constant_input(self):
        """No steering at all -> score 1.0 (no jerk)."""
        d = _make_distance(100)
        steer = np.zeros(len(d))
        score = compute_steering_smoothness(d, steer)
        assert score == 1.0

    def test_smoothness_short_array(self):
        """Very short array -> 0.0."""
        score = compute_steering_smoothness(np.array([0, 1, 2]), np.array([0, 1, 0]))
        assert score == 0.0

    def test_corrections_count(self):
        """Known number of sign changes in steering rate."""
        d = _make_distance(500)
        corners = _make_corners(1)  # entry=100, exit=160

        # Zigzag steering within corner: 4 clear direction changes
        steer = np.zeros(len(d))
        steer[100:120] = np.linspace(0, 20, 20)   # turning right
        steer[120:130] = np.linspace(20, 10, 10)   # correction back
        steer[130:145] = np.linspace(10, 25, 15)   # turning right again
        steer[145:160] = np.linspace(25, 15, 15)   # another correction

        result = count_corrections(d, steer, corners)
        assert len(result) == 1
        assert result[0]["corner_id"] == 1
        assert result[0]["correction_count"] >= 2

    def test_corrections_smooth_turn(self):
        """Smooth sine through corner -> few corrections."""
        d = _make_distance(500, step=0.5)
        corners = _make_corners(1)
        steer = 20.0 * np.sin(2 * np.pi * d / 200.0)

        result = count_corrections(d, steer, corners)
        # A smooth sine does have rate sign changes at peaks -- but
        # the count should be modest (not a noisy zigzag)
        assert result[0]["correction_count"] < 10

    def test_corrections_empty_corner(self):
        """Corner with no data points -> zero corrections."""
        d = _make_distance(50)  # only 0-50m
        corners = [{"corner_id": 1, "entry_m": 200.0, "apex_m": 230.0, "exit_m": 260.0}]
        steer = np.zeros(len(d))

        result = count_corrections(d, steer, corners)
        assert result[0]["correction_count"] == 0


# =========================================================================
# RPM / POWER CURVE
# =========================================================================


class TestPowerCurve:

    def _make_synthetic_power_data(self, n: int = 500):
        """Generate synthetic full-throttle data with a known power curve."""
        rng = np.random.RandomState(42)
        rpm = np.linspace(3000, 8000, n)
        throttle = np.full(n, 95.0)
        speed = np.linspace(15, 45, n)  # m/s

        # Synthetic torque curve peaking around 6000 RPM
        torque_profile = 200 * np.exp(-0.5 * ((rpm - 6000) / 1500) ** 2)
        omega = 2 * np.pi * rpm / 60.0
        power_w = torque_profile * omega  # P = T * omega
        # a = P / (m * v)
        mass = 350.0
        accel = power_w / (mass * speed)
        # Add small noise
        accel += rng.normal(0, 0.05, n)
        accel = np.clip(accel, 0.2, 50.0)

        return rpm, accel, throttle, speed

    def test_fit_basic(self):
        """Synthetic RPM/accel data -> peak power RPM is reasonable."""
        rpm, accel, throttle, speed = self._make_synthetic_power_data()
        result = fit_power_curve(rpm, accel, throttle, speed, mass_kg=350.0)

        assert len(result["rpm_points"]) > 0
        assert len(result["power_kw"]) > 0
        assert result["peak_power_rpm"] > 0
        # Peak should be somewhere around 6000-7000 RPM
        assert 4000 < result["peak_power_rpm"] < 8500

    def test_fit_insufficient_data(self):
        """Too few data points -> empty result."""
        result = fit_power_curve(
            np.array([3000, 4000]),
            np.array([5.0, 6.0]),
            np.array([95.0, 95.0]),
            np.array([20.0, 25.0]),
        )
        assert result["rpm_points"] == []

    def test_fit_low_throttle(self):
        """All throttle < 90% -> empty result (no full-throttle data)."""
        rpm = np.linspace(3000, 8000, 100)
        accel = np.full(100, 5.0)
        throttle = np.full(100, 50.0)  # below threshold
        speed = np.full(100, 30.0)
        result = fit_power_curve(rpm, accel, throttle, speed)
        assert result["rpm_points"] == []

    def test_shift_quality_perfect(self):
        """Shifts exactly at optimal RPM -> score ~1.0."""
        # Gear pattern: 1,1,...,2,2,...,3,3,...
        gear = np.array([1]*20 + [2]*20 + [3]*20, dtype=float)
        optimal = 7000.0
        rpm = np.full(60, 5000.0)
        # RPM just before upshift should be at optimal
        rpm[19] = optimal
        rpm[39] = optimal

        score = score_shift_quality(rpm, gear, optimal)
        assert score > 0.9

    def test_shift_quality_poor(self):
        """Shifts way too early -> score low."""
        gear = np.array([1]*20 + [2]*20 + [3]*20, dtype=float)
        optimal = 7000.0
        rpm = np.full(60, 4000.0)
        # Shifting at 4000 when optimal is 7000
        rpm[19] = 4000.0
        rpm[39] = 4000.0

        score = score_shift_quality(rpm, gear, optimal)
        assert score < 0.6

    def test_shift_quality_no_upshifts(self):
        """No gear changes -> 0.0."""
        gear = np.ones(50)
        rpm = np.full(50, 6000.0)
        score = score_shift_quality(rpm, gear, 7000.0)
        assert score == 0.0


# =========================================================================
# CORNER ANALYSIS MASTER
# =========================================================================


class TestCornerAnalysisMaster:

    def _make_full_dataframe(self, length: float = 500.0) -> pd.DataFrame:
        """DataFrame with all expected columns and two corners' worth of data."""
        n = int(length)
        d = np.arange(0, length, 1.0)
        rng = np.random.RandomState(42)

        brake = np.zeros(n)
        brake[90:145] = 60.0   # braking into corner 1
        brake[290:345] = 55.0  # braking into corner 2

        throttle = np.zeros(n)
        throttle[145:200] = np.linspace(0, 100, 55)
        throttle[200:290] = 100.0
        throttle[345:400] = np.linspace(0, 100, 55)
        throttle[400:] = 100.0

        steer = np.zeros(n)
        steer[100:160] = 25.0 * np.sin(np.linspace(0, np.pi, 60))
        steer[300:360] = -20.0 * np.sin(np.linspace(0, np.pi, 60))

        rpm = np.linspace(4000, 8000, n) + rng.normal(0, 50, n)
        gear = np.ones(n)
        gear[150:350] = 2.0
        gear[350:] = 3.0

        speed = 15.0 + 10.0 * np.sin(2 * np.pi * d / length)
        accel = np.gradient(speed)

        return pd.DataFrame({
            "distance_m": d,
            "brake_pct": brake,
            "throttle_pct": throttle,
            "steering_angle_deg": steer,
            "rpm": rpm,
            "gear": gear,
            "speed_mps": speed,
            "accel_long_mps2": accel,
        })

    def test_full_corner_analysis(self):
        """DataFrame with all columns, 2 corners -> returns enriched list."""
        df = self._make_full_dataframe()
        corners = _make_corners(2)

        results = analyze_corners_with_controls(df, corners)
        assert len(results) == 2
        assert results[0]["corner_id"] == 1
        assert results[1]["corner_id"] == 2

        # Check that brake analysis produced trail metrics
        assert "trail_brake_pct" in results[0]
        # Check throttle analysis produced exit rate
        assert "exit_application_rate" in results[0]
        # Check steering smoothness is present
        assert "steering_smoothness" in results[0]
        # Check corrections
        assert "correction_count" in results[0]

    def test_missing_columns_graceful(self):
        """DataFrame with only distance + speed -> no crash, partial results."""
        n = 200
        df = pd.DataFrame({
            "distance_m": np.arange(0, n, 1.0),
            "speed_mps": np.full(n, 20.0),
        })
        corners = _make_corners(1)

        results = analyze_corners_with_controls(df, corners)
        assert len(results) == 1
        assert results[0]["corner_id"] == 1
        # No brake/throttle/steering keys should be present
        assert "trail_brake_pct" not in results[0]
        assert "exit_application_rate" not in results[0]
        assert "steering_smoothness" not in results[0]

    def test_empty_dataframe(self):
        """Empty DataFrame -> empty list."""
        df = pd.DataFrame()
        corners = _make_corners(1)
        results = analyze_corners_with_controls(df, corners)
        assert results == []

    def test_empty_corners(self):
        """Non-empty DataFrame but no corners -> empty list."""
        df = pd.DataFrame({"distance_m": [0, 1, 2], "speed_mps": [10, 11, 12]})
        results = analyze_corners_with_controls(df, [])
        assert results == []

    def test_alternative_column_names(self):
        """Uses 'Distance (m)' instead of 'distance_m' -- should still work."""
        n = 200
        df = pd.DataFrame({
            "Distance (m)": np.arange(0, n, 1.0),
            "brake_pct": np.concatenate([np.zeros(90), np.full(60, 50.0), np.zeros(50)]),
        })
        corners = _make_corners(1)
        results = analyze_corners_with_controls(df, corners)
        assert len(results) == 1
        # Should have brake_points_before since brake_pct is present
        assert "brake_points_before" in results[0]

    def test_nan_filled_columns(self):
        """Columns full of NaN -> functions handle gracefully."""
        n = 200
        df = pd.DataFrame({
            "distance_m": np.arange(0, n, 1.0),
            "brake_pct": np.full(n, np.nan),
            "throttle_pct": np.full(n, np.nan),
            "steering_angle_deg": np.full(n, np.nan),
        })
        corners = _make_corners(1)
        # Should not raise
        results = analyze_corners_with_controls(df, corners)
        assert len(results) == 1
