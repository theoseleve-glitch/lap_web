"""Tests for sim_optimizer validation, trace serialization, and session summary."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.analysis.validation import (
    validate_against_iracing_optimal,
)
from telemetry_tool.sim_optimizer.output.traces import (
    serialize_lap_delta,
    serialize_theoretical_trace,
)
from telemetry_tool.sim_optimizer.output.summary import build_session_summary


# ---------------------------------------------------------------------------
# Helpers — lightweight mock objects via SimpleNamespace
# ---------------------------------------------------------------------------

def _make_trace(n: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        distance_m=np.linspace(0, 1000, n),
        speed_mps=np.linspace(20, 60, n),
        throttle_pct=np.linspace(0, 100, n),
        brake_pct=np.linspace(100, 0, n),
        steering_deg=np.linspace(-10, 10, n),
        gear=np.array([2] * n, dtype=int),
        limit_type=np.array([1] * n, dtype=int),
    )


def _make_delta(n: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        distance_m=np.linspace(0, 1000, n),
        time_delta_s=np.linspace(-0.5, 0.5, n),
        speed_delta_mps=np.linspace(-2, 2, n),
        throttle_delta_pct=np.linspace(-10, 10, n),
        brake_delta_pct=np.linspace(-5, 5, n),
        steering_delta_deg=np.linspace(-3, 3, n),
        total_time_loss_s=1.234,
    )


def _make_corner(corner_id: int, time_loss: float) -> SimpleNamespace:
    return SimpleNamespace(
        corner_id=corner_id,
        time_loss_s=time_loss,
        root_cause="late_brake",
        coaching_text="Brake earlier",
    )


def _make_theoretical_result() -> SimpleNamespace:
    return SimpleNamespace(
        lap_time_s=62.345,
        method="qss_enhanced",
    )


def _make_vehicle_model() -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {"mass_kg": 1200, "power_kw": 150},
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validation_skip_on_none(self):
        result = validate_against_iracing_optimal(62.0, None)
        assert result["status"] == "skip"
        assert result["our_lap_time_s"] == 62.0
        assert result["iracing_optimal_delta_median_s"] is None

    def test_validation_pass_when_faster(self):
        # Negative delta means our lap is faster than iRacing optimal
        delta = np.array([-0.5, -0.3, -0.2])
        result = validate_against_iracing_optimal(61.0, delta)
        assert result["status"] == "pass"
        assert result["iracing_optimal_delta_median_s"] is not None
        assert result["iracing_optimal_delta_median_s"] < 0

    def test_validation_warn_when_slow(self):
        # Positive delta > 1.0s means we're too slow
        delta = np.array([2.0, 2.5, 1.8])
        result = validate_against_iracing_optimal(64.0, delta)
        assert result["status"] == "warn"
        assert result["iracing_optimal_delta_median_s"] > 1.0


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------

class TestSerializeTrace:
    def test_serialize_trace_has_keys(self):
        trace = _make_trace()
        out = serialize_theoretical_trace(trace)
        expected_keys = {
            "distance_m", "speed_mps", "speed_kph", "throttle_pct",
            "brake_pct", "steering_deg", "gear", "limit_type",
        }
        assert set(out.keys()) == expected_keys
        # All array values are plain lists
        for k in expected_keys:
            assert isinstance(out[k], list), f"{k} should be a list"

    def test_serialize_delta_has_keys(self):
        delta = _make_delta()
        out = serialize_lap_delta(delta)
        expected_keys = {
            "distance_m", "time_delta_s", "speed_delta_mps",
            "throttle_delta_pct", "brake_delta_pct", "steering_delta_deg",
            "total_time_loss_s",
        }
        assert set(out.keys()) == expected_keys
        # Array fields are lists, scalar is float
        assert isinstance(out["distance_m"], list)
        assert isinstance(out["total_time_loss_s"], float)


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_has_keys(self):
        result = _make_theoretical_result()
        trace = _make_trace()
        corners = [_make_corner(i, 0.1 * i) for i in range(8)]
        vehicle = _make_vehicle_model()
        validation = {"status": "pass", "message": "ok"}

        summary = build_session_summary(
            result, trace, corners, vehicle, validation, session_id="sess_001",
        )
        expected_keys = {
            "session_id", "theoretical_lap_time_s", "method",
            "vehicle_model", "validation", "n_corners",
            "top_corners", "total_time_loss_s",
        }
        assert set(summary.keys()) == expected_keys
        assert summary["session_id"] == "sess_001"
        assert summary["theoretical_lap_time_s"] == 62.345
        assert summary["method"] == "qss_enhanced"
        assert isinstance(summary["vehicle_model"], dict)
        assert summary["n_corners"] == 8
        assert len(summary["top_corners"]) == 5  # top 5 only
