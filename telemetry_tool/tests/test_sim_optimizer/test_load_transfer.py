"""Tests for per-wheel load transfer calculation."""
import pytest

from telemetry_tool.sim_optimizer.solver.load_transfer import (
    WheelLoads,
    _G,
    compute_wheel_loads,
)


class TestStaticLoads:
    """test_static_loads: zero accel -> all loads equal to mass*g/4 for 50/50 weight dist."""

    def test_static_loads(self):
        loads = compute_wheel_loads(0.0, 0.0, 300.0, weight_dist_front=0.50)
        expected = 300.0 * _G / 4.0
        assert loads.lf == pytest.approx(expected, rel=1e-9)
        assert loads.rf == pytest.approx(expected, rel=1e-9)
        assert loads.lr == pytest.approx(expected, rel=1e-9)
        assert loads.rr == pytest.approx(expected, rel=1e-9)


class TestLateralTransfer:
    """test_lateral_transfer: right turn (lat=5 m/s^2) -> left wheels heavier than right."""

    def test_lateral_transfer(self):
        loads = compute_wheel_loads(5.0, 0.0, 300.0)
        # Positive lat = right turn -> left wheels gain load
        assert loads.lf > loads.rf
        assert loads.lr > loads.rr


class TestLongitudinalTransfer:
    """test_longitudinal_transfer: braking (long=-8 m/s^2) -> front wheels heavier than rear."""

    def test_longitudinal_transfer(self):
        loads = compute_wheel_loads(0.0, -8.0, 300.0)
        # Negative long = braking -> front gains, rear loses
        assert loads.lf > loads.lr
        assert loads.rf > loads.rr


class TestTotalEqualsWeight:
    """test_total_equals_weight: any accel combination -> total load approx mass * g."""

    def test_total_equals_weight(self):
        # Use moderate accels that won't cause clamping
        loads = compute_wheel_loads(3.0, -2.0, 300.0)
        expected_weight = 300.0 * _G
        assert loads.total() == pytest.approx(expected_weight, rel=1e-9)


class TestNoNegativeLoads:
    """test_no_negative_loads: extreme accel -> all loads >= 0."""

    def test_no_negative_loads(self):
        # Extreme lateral + longitudinal to force clamping
        loads = compute_wheel_loads(50.0, -50.0, 300.0)
        assert loads.lf >= 0.0
        assert loads.rf >= 0.0
        assert loads.lr >= 0.0
        assert loads.rr >= 0.0
