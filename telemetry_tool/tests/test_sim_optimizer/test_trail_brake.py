"""Tests for combined-slip trail braking calculations."""
from __future__ import annotations

import math

import pytest

from telemetry_tool.sim_optimizer.reconstruction.trail_brake import (
    available_longitudinal,
    split_braking_cornering,
    split_traction_cornering,
)


class TestAvailableLongitudinal:
    def test_zero_lateral_full_longitudinal(self):
        """ay=0 -> full ax_max available."""
        result = available_longitudinal(ay_required=0.0, ay_max=12.0, ax_max=10.0, p=1.6)
        assert result == pytest.approx(10.0)

    def test_max_lateral_zero_longitudinal(self):
        """ay=ay_max -> no longitudinal available."""
        result = available_longitudinal(ay_required=12.0, ay_max=12.0, ax_max=10.0, p=1.6)
        assert result == pytest.approx(0.0)

    def test_partial_lateral(self):
        """ay=6 (50% of max 12) -> some longitudinal available, between 0 and ax_max."""
        result = available_longitudinal(ay_required=6.0, ay_max=12.0, ax_max=10.0, p=1.6)
        assert result > 0.0
        assert result < 10.0

    def test_p_norm_shape(self):
        """At p=2.0 (circle), ay=ax_max*0.707 -> available ~ ax_max*0.707."""
        ax_max = 10.0
        ay_max = 10.0
        ay_req = ax_max * math.sqrt(0.5)  # ~7.071
        result = available_longitudinal(ay_required=ay_req, ay_max=ay_max, ax_max=ax_max, p=2.0)
        expected = ax_max * math.sqrt(0.5)
        assert result == pytest.approx(expected, rel=1e-6)


class TestSplitBrakingCornering:
    def test_split_within_limit(self):
        """Low combined demand -> returned as-is."""
        a_long, a_lat = split_braking_cornering(
            a_long_required=-2.0,
            curvature=0.01,
            speed_mps=10.0,  # a_lat_needed = 100 * 0.01 = 1.0
            ay_max=12.0,
            ax_brake_max=10.0,
            p=1.6,
        )
        assert a_long == pytest.approx(-2.0)
        assert a_lat == pytest.approx(1.0)

    def test_split_exceeds_reduces_longitudinal(self):
        """High combined demand -> a_lat preserved, a_long reduced."""
        a_long, a_lat = split_braking_cornering(
            a_long_required=-10.0,
            curvature=0.1,
            speed_mps=10.0,  # a_lat_needed = 100 * 0.1 = 10.0
            ay_max=12.0,
            ax_brake_max=10.0,
            p=1.6,
        )
        # Lateral should be preserved at 10.0 (within ay_max)
        assert a_lat == pytest.approx(10.0)
        # Longitudinal must be reduced (can't have full 10 braking + 10 lateral)
        assert abs(a_long) < 10.0
        assert a_long < 0.0  # still braking
