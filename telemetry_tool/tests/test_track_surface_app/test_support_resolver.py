"""Tests for SupportTierResolver."""
from __future__ import annotations

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.support import SupportTierResolver, compute_fallback_depth_2_pct


class TestComputeFallbackDepth2Pct:
    def test_empty_dist_returns_zero(self):
        assert compute_fallback_depth_2_pct({}) == 0.0

    def test_basic_ratio(self):
        # 800 + 150 + 50 = 1000, 50/1000 = 5%
        assert compute_fallback_depth_2_pct({0: 800, 1: 150, 2: 50}) == pytest.approx(5.0)

    def test_no_fb2_key_returns_zero(self):
        assert compute_fallback_depth_2_pct({0: 100, 1: 0}) == 0.0

    def test_only_fb2(self):
        assert compute_fallback_depth_2_pct({2: 100}) == 100.0


class TestTierResolution:
    def test_tier_a_full_pass(self, tier_a_inputs):
        pr, rr = tier_a_inputs
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.A
        assert reason == "all_checks_passed"

    def test_tier_b_via_moderate_fallback(self, tier_b_inputs_fallback):
        pr, rr = tier_b_inputs_fallback
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.B
        assert reason == "moderate_fallback"

    def test_tier_b_via_release_warn(self, tier_b_inputs_warn):
        pr, rr = tier_b_inputs_warn
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.B
        assert reason == "release_gate_warn"

    def test_tier_c_via_fail(self, tier_c_inputs_fail):
        pr, rr = tier_c_inputs_fail
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "release_gate_fail"

    def test_tier_c_via_high_fallback(self, tier_c_inputs_fallback):
        pr, rr = tier_c_inputs_fallback
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "high_global_fallback"

    def test_tier_d_no_calibration(self, tier_d_inputs_no_calibration):
        pr, rr = tier_d_inputs_no_calibration
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.D
        assert reason == "vehicle_profile_not_validated"

    def test_tier_d_default_calibration(self, tier_d_inputs_default_calibration):
        pr, rr = tier_d_inputs_default_calibration
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.D
        assert reason == "vehicle_profile_not_validated"

    def test_tier_d_when_pipeline_failed(self, make_pipeline_result, make_release_result):
        pr = make_pipeline_result(
            calibration_source="registry_active",
            n_valid=0,
            exception="RuntimeError: solver failed",
        )
        rr = make_release_result("fail")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.D
        assert reason == "track_geometry_missing"


class TestTierBoundaries:
    def test_fb2_at_exactly_10_goes_b(self, make_pipeline_result, make_release_result):
        # 100 → 10% exactly
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 800, 1: 100, 2: 100},
            calibration_source="registry_active",
        )
        rr = make_release_result("pass")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.B
        assert reason == "moderate_fallback"

    def test_fb2_at_9_99_goes_a(self, make_pipeline_result, make_release_result):
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 900, 1: 1, 2: 99},   # 99/1000 = 9.9%
            calibration_source="registry_active",
        )
        rr = make_release_result("pass")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.A

    def test_fb2_at_exactly_30_goes_c(self, make_pipeline_result, make_release_result):
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 600, 1: 100, 2: 300},
            calibration_source="registry_active",
        )
        rr = make_release_result("pass")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "high_global_fallback"

    def test_fail_beats_high_fallback(self, make_pipeline_result, make_release_result):
        # Both conditions true — FAIL reported first
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 400, 1: 200, 2: 400},
            calibration_source="registry_active",
        )
        rr = make_release_result("fail")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "release_gate_fail"
