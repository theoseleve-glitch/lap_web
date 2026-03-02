"""Tests for telemetry_tool.physics.slip_model module."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from physics.slip_model import (
    analyze_slip_session,
    analyze_traction_utilization,
    compute_slip_ratios,
    detect_lockups,
    detect_wheelspin,
)


# ===================================================================
# TestSlipRatios
# ===================================================================

class TestSlipRatios:
    """Tests for compute_slip_ratios."""

    def test_no_slip(self):
        """Wheel speed == vehicle speed -> ratios ~0."""
        vs = np.array([20.0, 20.0, 20.0])
        result = compute_slip_ratios(vs, vs, vs, vs, vs)
        for corner in ("fl", "fr", "rl", "rr"):
            np.testing.assert_allclose(result[corner], 0.0, atol=1e-10)

    def test_lockup(self):
        """Wheel speed = 0, vehicle > 0 -> negative slip ratio."""
        ws_locked = np.array([0.0, 0.0, 0.0])
        vs = np.array([20.0, 20.0, 20.0])
        ws_normal = np.array([20.0, 20.0, 20.0])
        result = compute_slip_ratios(ws_locked, ws_normal, ws_normal, ws_normal, vs)
        assert np.all(result["fl"] < 0)
        # fl should be -1.0 (full lockup)
        np.testing.assert_allclose(result["fl"], -1.0, atol=0.01)

    def test_wheelspin(self):
        """Wheel speed > vehicle speed -> positive slip ratio."""
        ws_spin = np.array([30.0, 30.0, 30.0])
        vs = np.array([20.0, 20.0, 20.0])
        ws_normal = np.array([20.0, 20.0, 20.0])
        result = compute_slip_ratios(ws_normal, ws_normal, ws_spin, ws_normal, vs)
        assert np.all(result["rl"] > 0)

    def test_zero_speed(self):
        """Both wheel and vehicle at 0 -> slip = 0 (clamped denom)."""
        zeros = np.array([0.0, 0.0])
        result = compute_slip_ratios(zeros, zeros, zeros, zeros, zeros)
        for corner in ("fl", "fr", "rl", "rr"):
            np.testing.assert_allclose(result[corner], 0.0, atol=1e-10)

    def test_nan_handling(self):
        """NaN in input -> slip = 0 for that sample."""
        ws = np.array([20.0, float("nan"), 20.0])
        vs = np.array([20.0, 20.0, 20.0])
        result = compute_slip_ratios(ws, ws, ws, ws, vs)
        assert result["fl"][1] == 0.0  # NaN replaced with 0

    def test_output_shape(self):
        """Output arrays have same length as input."""
        n = 50
        ws = np.ones(n) * 20.0
        vs = np.ones(n) * 20.0
        result = compute_slip_ratios(ws, ws, ws, ws, vs)
        for corner in ("fl", "fr", "rl", "rr"):
            assert len(result[corner]) == n


# ===================================================================
# TestLockupDetection
# ===================================================================

class TestLockupDetection:
    """Tests for detect_lockups."""

    def test_single_lockup(self):
        """One zone where slip < -0.15."""
        n = 100
        distances = np.linspace(0, 100, n)
        slip = np.zeros(n)
        # Lockup between 40-60m
        slip[40:60] = -0.3
        slip_ratios = {"fl": slip, "fr": np.zeros(n), "rl": np.zeros(n), "rr": np.zeros(n)}
        events = detect_lockups(distances, slip_ratios)
        assert len(events) >= 1
        assert events[0]["corner"] == "fl"
        assert events[0]["severity"] in ("light", "moderate")

    def test_no_lockup(self):
        """All slip > -0.15 -> empty list."""
        n = 100
        distances = np.linspace(0, 100, n)
        slip = np.full(n, -0.05)
        slip_ratios = {"fl": slip, "fr": slip, "rl": slip, "rr": slip}
        events = detect_lockups(distances, slip_ratios)
        assert len(events) == 0

    def test_severity_levels(self):
        """Light, moderate, severe lockups classified correctly."""
        n = 100
        distances = np.linspace(0, 300, n)
        slip = np.zeros(n)
        # Light lockup: -0.2
        slip[10:20] = -0.2
        # Moderate: -0.4
        slip[40:50] = -0.4
        # Severe: -0.6
        slip[70:80] = -0.6
        slip_ratios = {"fl": slip, "fr": np.zeros(n), "rl": np.zeros(n), "rr": np.zeros(n)}
        events = detect_lockups(distances, slip_ratios)
        severities = {e["severity"] for e in events}
        assert "light" in severities
        assert "moderate" in severities
        assert "severe" in severities

    def test_minimum_duration(self):
        """Very brief lockup < min_duration -> filtered out."""
        n = 200
        distances = np.linspace(0, 200, n)
        slip = np.zeros(n)
        # Only 1 sample (1m) below threshold
        slip[50] = -0.5
        slip_ratios = {"fl": slip, "fr": np.zeros(n), "rl": np.zeros(n), "rr": np.zeros(n)}
        events = detect_lockups(distances, slip_ratios, min_duration_m=2.0)
        assert len(events) == 0

    def test_empty_arrays(self):
        """Empty input -> empty list."""
        events = detect_lockups(np.array([]), {}, threshold=-0.15)
        assert events == []

    def test_multiple_corners(self):
        """Lockups on different wheels detected separately."""
        n = 100
        distances = np.linspace(0, 200, n)
        slip_fl = np.zeros(n)
        slip_fl[10:25] = -0.3
        slip_rr = np.zeros(n)
        slip_rr[60:75] = -0.4
        slip_ratios = {
            "fl": slip_fl, "fr": np.zeros(n),
            "rl": np.zeros(n), "rr": slip_rr,
        }
        events = detect_lockups(distances, slip_ratios)
        corners_hit = {e["corner"] for e in events}
        assert "fl" in corners_hit
        assert "rr" in corners_hit


# ===================================================================
# TestWheelspinDetection
# ===================================================================

class TestWheelspinDetection:
    """Tests for detect_wheelspin."""

    def test_single_wheelspin(self):
        """One zone where slip > 0.10."""
        n = 100
        distances = np.linspace(0, 100, n)
        slip = np.zeros(n)
        slip[30:50] = 0.25
        slip_ratios = {"fl": np.zeros(n), "fr": np.zeros(n),
                       "rl": slip, "rr": np.zeros(n)}
        events = detect_wheelspin(distances, slip_ratios)
        assert len(events) >= 1
        assert events[0]["corner"] == "rl"

    def test_no_wheelspin(self):
        """All slip < 0.10 -> empty list."""
        n = 100
        distances = np.linspace(0, 100, n)
        slip = np.full(n, 0.03)
        slip_ratios = {"fl": slip, "fr": slip, "rl": slip, "rr": slip}
        events = detect_wheelspin(distances, slip_ratios)
        assert len(events) == 0

    def test_severity_classification(self):
        """High slip -> severe wheelspin."""
        n = 100
        distances = np.linspace(0, 200, n)
        slip = np.zeros(n)
        slip[20:40] = 0.6
        slip_ratios = {"fl": np.zeros(n), "fr": np.zeros(n),
                       "rl": slip, "rr": np.zeros(n)}
        events = detect_wheelspin(distances, slip_ratios)
        assert any(e["severity"] == "severe" for e in events)

    def test_empty_input(self):
        """Empty arrays -> empty list."""
        events = detect_wheelspin(np.array([]), {})
        assert events == []


# ===================================================================
# TestTractionUtilization
# ===================================================================

class TestTractionUtilization:
    """Tests for analyze_traction_utilization."""

    def test_good_traction(self):
        """Low mean slip everywhere -> excellent rating."""
        n = 200
        distances = np.linspace(0, 500, n)
        slip_ratios = {
            "fl": np.full(n, 0.01),
            "fr": np.full(n, 0.01),
            "rl": np.full(n, 0.02),
            "rr": np.full(n, 0.02),
        }
        corners = [{"corner_id": 1, "entry_m": 100.0, "apex_m": 150.0, "exit_m": 200.0}]
        result = analyze_traction_utilization(distances, slip_ratios, corners)
        assert len(result) == 1
        assert result[0]["traction_rating"] == "excellent"

    def test_corner_with_issues(self):
        """High slip in one corner, low elsewhere."""
        n = 200
        distances = np.linspace(0, 500, n)
        slip = np.full(n, 0.01)
        # High slip in corner zone (100-200m)
        mask = (distances >= 100) & (distances <= 200)
        slip_rl = slip.copy()
        slip_rl[mask] = 0.25
        slip_ratios = {
            "fl": slip.copy(), "fr": slip.copy(),
            "rl": slip_rl, "rr": slip.copy(),
        }
        corners = [
            {"corner_id": 1, "entry_m": 100.0, "apex_m": 150.0, "exit_m": 200.0},
            {"corner_id": 2, "entry_m": 300.0, "apex_m": 350.0, "exit_m": 400.0},
        ]
        result = analyze_traction_utilization(distances, slip_ratios, corners)
        # Corner 1 should have worse traction
        assert result[0]["traction_rating"] in ("marginal", "poor")
        assert result[1]["traction_rating"] == "excellent"

    def test_no_data_in_zone(self):
        """Corner zone outside distance range -> no_data."""
        distances = np.linspace(0, 100, 50)
        slip_ratios = {"fl": np.zeros(50), "fr": np.zeros(50),
                       "rl": np.zeros(50), "rr": np.zeros(50)}
        corners = [{"corner_id": 1, "entry_m": 200.0, "apex_m": 250.0, "exit_m": 300.0}]
        result = analyze_traction_utilization(distances, slip_ratios, corners)
        assert result[0]["traction_rating"] == "no_data"

    def test_empty_corners(self):
        """No corners -> empty result."""
        distances = np.linspace(0, 100, 50)
        slip_ratios = {"fl": np.zeros(50)}
        result = analyze_traction_utilization(distances, slip_ratios, [])
        assert result == []


# ===================================================================
# TestAnalyzeSlipSession
# ===================================================================

class TestAnalyzeSlipSession:
    """Tests for the session-level master function."""

    def _make_lap_df(self, n=100, lockup_zone=None):
        """Create a single-lap DataFrame with slip columns."""
        df = pd.DataFrame({
            "distance_m": np.linspace(0, 500, n),
            "speed_mps": np.ones(n) * 20.0,
            "wheel_slip_fl": np.zeros(n),
            "wheel_slip_fr": np.zeros(n),
            "wheel_slip_rl": np.zeros(n),
            "wheel_slip_rr": np.zeros(n),
        })
        if lockup_zone:
            s, e = lockup_zone
            mask = (df["distance_m"] >= s) & (df["distance_m"] <= e)
            df.loc[mask, "wheel_slip_fl"] = -0.4
        return df

    def test_no_slip_data(self):
        """DataFrame without slip columns -> has_slip_data=False."""
        df = pd.DataFrame({
            "distance_m": np.linspace(0, 500, 50),
            "tire_temp_fl": np.ones(50) * 90.0,
        })
        result = analyze_slip_session({1: df})
        assert result["has_slip_data"] is False

    def test_with_slip_data(self):
        """DataFrames with slip columns produce results."""
        laps = {1: self._make_lap_df(), 2: self._make_lap_df()}
        result = analyze_slip_session(laps)
        assert result["has_slip_data"] is True
        assert "total_lockups" in result["summary"]

    def test_detects_lockup(self):
        """Session with lockup zone reports it."""
        laps = {1: self._make_lap_df(lockup_zone=(100, 150))}
        result = analyze_slip_session(laps)
        assert result["summary"]["total_lockups"] >= 1

    def test_empty_input(self):
        """Empty dict -> graceful default."""
        result = analyze_slip_session({})
        assert result["has_slip_data"] is False
