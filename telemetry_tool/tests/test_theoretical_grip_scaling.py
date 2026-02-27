"""Tests for grip-scaled theoretical lap functions."""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from theoretical_engine import (
    _OUT_ACCEL,
    _OUT_BRAKE,
    _OUT_DIST,
    _OUT_SPEED,
    scale_theoretical_by_grip,
    get_phase_theoreticals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dry_theoretical():
    """A simple dry theoretical lap DataFrame with known values."""
    return pd.DataFrame({
        _OUT_DIST:  [0.0, 100.0, 200.0, 300.0, 400.0],
        _OUT_SPEED: [20.0, 30.0, 40.0, 30.0, 20.0],
        _OUT_ACCEL: [5.0, 4.0, 3.0, 2.0, 1.0],
        _OUT_BRAKE: [-1.0, -2.0, -3.0, -4.0, -5.0],
    })


# ---------------------------------------------------------------------------
# TestScaleTheoreticalByGrip
# ---------------------------------------------------------------------------

class TestScaleTheoreticalByGrip:
    """Tests for scale_theoretical_by_grip."""

    def test_grip_factor_1_identity(self, dry_theoretical):
        """Factor 1.0 returns identical values."""
        result = scale_theoretical_by_grip(dry_theoretical, 1.0)
        pd.testing.assert_frame_equal(result, dry_theoretical)

    def test_grip_factor_scales_speed_by_sqrt(self, dry_theoretical):
        """Speed scales by sqrt(grip_factor). sqrt(0.64) = 0.8."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.64)
        expected_speeds = dry_theoretical[_OUT_SPEED].values * math.sqrt(0.64)
        np.testing.assert_allclose(
            result[_OUT_SPEED].values, expected_speeds, rtol=1e-10,
        )

    def test_grip_factor_scales_accel_linearly(self, dry_theoretical):
        """Acceleration scales linearly by grip_factor."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.5)
        expected_accel = dry_theoretical[_OUT_ACCEL].values * 0.5
        np.testing.assert_allclose(
            result[_OUT_ACCEL].values, expected_accel, rtol=1e-10,
        )

    def test_grip_factor_scales_braking_linearly(self, dry_theoretical):
        """Braking scales linearly by grip_factor, preserves negative sign."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.5)
        expected_brake = dry_theoretical[_OUT_BRAKE].values * 0.5
        np.testing.assert_allclose(
            result[_OUT_BRAKE].values, expected_brake, rtol=1e-10,
        )
        # All braking values must remain negative
        assert (result[_OUT_BRAKE].values < 0).all(), (
            "Braking values must remain negative after scaling"
        )

    def test_distance_unchanged(self, dry_theoretical):
        """Distance column is unchanged after grip scaling."""
        result = scale_theoretical_by_grip(dry_theoretical, 0.7)
        np.testing.assert_array_equal(
            result[_OUT_DIST].values, dry_theoretical[_OUT_DIST].values,
        )

    def test_returns_copy(self, dry_theoretical):
        """Original DataFrame is not modified."""
        original_speeds = dry_theoretical[_OUT_SPEED].values.copy()
        _ = scale_theoretical_by_grip(dry_theoretical, 0.5)
        np.testing.assert_array_equal(
            dry_theoretical[_OUT_SPEED].values, original_speeds,
        )

    def test_grip_factor_clamped(self, dry_theoretical):
        """Factor > 1 clamped to 1 (identity); factor < 0 gives zeros."""
        # Factor > 1 should behave like 1.0
        result_high = scale_theoretical_by_grip(dry_theoretical, 1.5)
        pd.testing.assert_frame_equal(result_high, dry_theoretical)

        # Factor < 0 should give zeros for speed/accel/brake
        result_neg = scale_theoretical_by_grip(dry_theoretical, -0.5)
        assert (result_neg[_OUT_SPEED].values == 0.0).all()
        assert (result_neg[_OUT_ACCEL].values == 0.0).all()
        assert (result_neg[_OUT_BRAKE].values == 0.0).all()


# ---------------------------------------------------------------------------
# TestGetPhaseTheoreticals
# ---------------------------------------------------------------------------

class TestGetPhaseTheoreticals:
    """Tests for get_phase_theoreticals."""

    def test_returns_dict_per_phase(self, dry_theoretical):
        """Returns one theoretical DataFrame per phase_id."""
        weather_timeline = pd.DataFrame({
            "lap_number": [1, 2, 3, 4, 5, 6],
            "grip_score": [90, 90, 90, 60, 60, 60],
        })
        phases_df = pd.DataFrame({
            "phase_id": [0, 1],
            "lap_start": [1, 4],
            "lap_end":   [3, 6],
        })
        result = get_phase_theoreticals(dry_theoretical, weather_timeline, phases_df)

        assert isinstance(result, dict)
        assert set(result.keys()) == {0, 1}
        for phase_id, df in result.items():
            assert isinstance(df, pd.DataFrame)
            assert _OUT_DIST in df.columns
            assert _OUT_SPEED in df.columns

    def test_phase_0_higher_speeds_than_phase_1(self, dry_theoretical):
        """Phase with grip=90 has higher speeds than phase with grip=60."""
        weather_timeline = pd.DataFrame({
            "lap_number": [1, 2, 3, 4, 5, 6],
            "grip_score": [90, 90, 90, 60, 60, 60],
        })
        phases_df = pd.DataFrame({
            "phase_id": [0, 1],
            "lap_start": [1, 4],
            "lap_end":   [3, 6],
        })
        result = get_phase_theoreticals(dry_theoretical, weather_timeline, phases_df)

        speeds_phase0 = result[0][_OUT_SPEED].values
        speeds_phase1 = result[1][_OUT_SPEED].values
        assert (speeds_phase0 >= speeds_phase1).all(), (
            "Phase 0 (grip=90) should have higher or equal speeds than phase 1 (grip=60)"
        )
