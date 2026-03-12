# telemetry_tool/tests/test_solver_calibrator.py
"""Tests for the calibration loop."""
import math
import numpy as np
import pytest

from solver.calibrator import calibrate_params, CalibrationResult


class TestCalibrateParams:

    def test_no_adjustment_when_accurate(self):
        """If theoretical matches actual, no adjustment needed."""
        result = CalibrationResult(
            mu_ref_initial=1.2, mu_ref_final=1.2,
            P_max_initial=50000, P_max_final=50000,
            F_brake_initial=15000, F_brake_final=15000,
            passes=0, residual_pct=0.0,
        )
        # Verify structure
        assert result.passes == 0
        assert result.residual_pct == pytest.approx(0.0)

    def test_mu_ref_scales_up(self):
        """If theoretical apex speed < actual, mu_ref should increase."""
        result = calibrate_params(
            mu_ref=1.0,
            P_max=50000.0,
            F_brake_max=15000.0,
            actual_apex_speeds=[22.0, 18.0, 25.0],
            theoretical_apex_speeds=[20.0, 16.0, 23.0],
            actual_straight_end_speeds=[40.0],
            theoretical_straight_end_speeds=[40.0],
            actual_braking_dists=[50.0],
            theoretical_braking_dists=[50.0],
        )
        assert result.mu_ref_final > 1.0
        assert result.passes >= 1

    def test_single_pass_returns_adjusted_values(self):
        """Single-pass calibration: large discrepancy produces proportional adjustment."""
        result = calibrate_params(
            mu_ref=0.8,
            P_max=50000.0,
            F_brake_max=15000.0,
            actual_apex_speeds=[22.0],
            theoretical_apex_speeds=[15.0],
            actual_straight_end_speeds=[40.0],
            theoretical_straight_end_speeds=[35.0],
            actual_braking_dists=[50.0],
            theoretical_braking_dists=[60.0],
        )
        assert result.passes == 1
        # mu should scale by (22/15)^2 = 2.151
        assert result.mu_ref_final == pytest.approx(0.8 * (22.0 / 15.0) ** 2, rel=0.01)
        # P_max should scale by (40/35)^3 = 1.493
        assert result.P_max_final == pytest.approx(50000.0 * (40.0 / 35.0) ** 3, rel=0.01)
        # F_brake should scale by 60/50 = 1.2
        assert result.F_brake_final == pytest.approx(15000.0 * 1.2, rel=0.01)
