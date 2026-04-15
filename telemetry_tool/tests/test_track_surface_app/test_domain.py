"""Tests for track_surface_app domain enums + dataclasses."""
from __future__ import annotations

import pytest

from track_surface_app.domain import (
    SupportTier,
    ConfidenceLevel,
    AnalysisRunStatus,
    PlannerModeAvailability,
)


class TestSupportTier:
    def test_values_are_stable_strings(self):
        assert SupportTier.A.value == "A"
        assert SupportTier.B.value == "B"
        assert SupportTier.C.value == "C"
        assert SupportTier.D.value == "D"

    def test_from_string_roundtrip(self):
        for tier in SupportTier:
            assert SupportTier(tier.value) is tier

    def test_from_string_unknown_raises(self):
        with pytest.raises(ValueError):
            SupportTier("X")


class TestConfidenceLevel:
    def test_from_mean_confidence_high(self):
        assert ConfidenceLevel.from_mean_confidence(0.9) is ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_mean_confidence(0.80) is ConfidenceLevel.HIGH

    def test_from_mean_confidence_medium(self):
        assert ConfidenceLevel.from_mean_confidence(0.65) is ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_mean_confidence(0.50) is ConfidenceLevel.MEDIUM

    def test_from_mean_confidence_low(self):
        assert ConfidenceLevel.from_mean_confidence(0.49) is ConfidenceLevel.LOW
        assert ConfidenceLevel.from_mean_confidence(0.0) is ConfidenceLevel.LOW

    def test_from_mean_confidence_unknown(self):
        assert ConfidenceLevel.from_mean_confidence(None) is ConfidenceLevel.UNKNOWN


class TestAnalysisRunStatus:
    def test_terminal(self):
        assert AnalysisRunStatus.SUCCEEDED.is_terminal()
        assert AnalysisRunStatus.FAILED.is_terminal()
        assert not AnalysisRunStatus.QUEUED.is_terminal()
        assert not AnalysisRunStatus.RUNNING.is_terminal()


class TestPlannerModeAvailability:
    def test_for_tier_a_all_on(self):
        av = PlannerModeAvailability.for_tier(SupportTier.A)
        assert av.nominal and av.robust and av.exploitable

    def test_for_tier_b_exploitable_off(self):
        av = PlannerModeAvailability.for_tier(SupportTier.B)
        assert av.nominal and av.robust and not av.exploitable

    def test_for_tier_c_all_off(self):
        av = PlannerModeAvailability.for_tier(SupportTier.C)
        assert not (av.nominal or av.robust or av.exploitable)

    def test_for_tier_d_all_off(self):
        av = PlannerModeAvailability.for_tier(SupportTier.D)
        assert not (av.nominal or av.robust or av.exploitable)

    def test_to_dict(self):
        av = PlannerModeAvailability.for_tier(SupportTier.B)
        assert av.to_dict() == {"nominal": True, "robust": True, "exploitable": False}
