"""Tests for all 16 handling detectors."""
import numpy as np
import pytest

from telemetry_tool.handling.types import SessionContext
from telemetry_tool.handling.detectors.apex_timing import ApexTimingDetector
from telemetry_tool.handling.detectors.corner_balance import CornerBalanceDetector
from telemetry_tool.handling.detectors.speed_recovery import SpeedRecoveryDetector
from telemetry_tool.handling.detectors.lat_g_jerk import LatGJerkDetector
from telemetry_tool.handling.detectors.trail_braking import TrailBrakingDetector
from telemetry_tool.handling.detectors.gg_shape import GGShapeDetector
from telemetry_tool.handling.detectors.yaw_residual import YawResidualDetector
from telemetry_tool.handling.detectors.heading_accel import HeadingAccelDetector
from telemetry_tool.handling.detectors.friction_asymmetry import FrictionAsymmetryDetector
from telemetry_tool.handling.detectors.speed_scrub import SpeedScrubDetector
from telemetry_tool.handling.detectors.throttle_response import ThrottleResponseDetector
from telemetry_tool.handling.detectors.steering_corrections import SteeringCorrectionsDetector
from telemetry_tool.handling.detectors.lat_g_plateau import LatGPlateauDetector
from telemetry_tool.handling.detectors.braking_distance import BrakingDistanceDetector
from telemetry_tool.handling.detectors.line_variation import LineVariationDetector

from telemetry_tool.tests.handling.conftest import _make_corner


@pytest.fixture
def ctx():
    return SessionContext()


class TestApexTiming:
    def test_late_apex_understeer(self, ctx):
        cw = _make_corner(late_apex=True)
        v = ApexTimingDetector().detect(cw, ctx)
        assert v.direction > 0, "Late apex should indicate understeer (positive)"

    def test_early_apex_oversteer(self, ctx):
        cw = _make_corner(early_apex=True)
        v = ApexTimingDetector().detect(cw, ctx)
        assert v.direction < 0, "Early apex should indicate oversteer (negative)"


class TestCornerBalance:
    def test_neutral_corner(self, ctx):
        cw = _make_corner()
        v = CornerBalanceDetector().detect(cw, ctx)
        assert abs(v.direction) < 0.5 or v.confidence == 0


class TestSpeedRecovery:
    def test_exit_speed_drop_oversteer(self, ctx):
        cw = _make_corner(exit_speed_drop=True)
        v = SpeedRecoveryDetector().detect(cw, ctx)
        # Low recovery or negative should be oversteer
        assert v.direction <= 0 or v.confidence == 0


class TestThrottleResponse:
    def test_detects_late_throttle(self, ctx):
        """Corner with delayed throttle application."""
        cw = _make_corner()
        # Set exit to have no positive accel (driver never accelerates)
        cw.a_lon_g[2 * cw.n_samples // 3:] = -0.05
        v = ThrottleResponseDetector().detect(cw, ctx)
        # Should detect oversteer (long delay = managing rear)
        assert v.direction < 0 or v.confidence == 0


class TestLineVariation:
    def test_no_cross_lap_data(self, ctx):
        cw = _make_corner()
        v = LineVariationDetector().detect(cw, ctx)
        # With no all_lap_corners, should return confidence=1 (no modification)
        assert v.is_confidence_modifier
        assert v.confidence >= 0.9


class TestAllDetectorsReturnVotes:
    """Ensure every detector returns a valid DetectorVote without crashing."""
    DETECTORS = [
        ApexTimingDetector, CornerBalanceDetector, SpeedRecoveryDetector,
        LatGJerkDetector, TrailBrakingDetector, GGShapeDetector,
        YawResidualDetector, HeadingAccelDetector,
        FrictionAsymmetryDetector, SpeedScrubDetector, ThrottleResponseDetector,
        SteeringCorrectionsDetector, LatGPlateauDetector, BrakingDistanceDetector,
        LineVariationDetector,
    ]

    @pytest.mark.parametrize("det_cls", DETECTORS, ids=lambda c: c.__name__)
    def test_no_crash(self, det_cls, ctx):
        cw = _make_corner()
        v = det_cls().detect(cw, ctx)
        assert -1.0 <= v.direction <= 1.0
        assert 0.0 <= v.confidence <= 1.0
        assert v.zone in ("entry", "mid", "exit")
