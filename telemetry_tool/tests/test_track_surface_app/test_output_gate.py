"""Tests for OutputGate — filters artifacts and planner modes by tier."""
from __future__ import annotations

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.gating import (
    OutputGate,
    ALL_ARTIFACT_KINDS,
    ALWAYS_PUBLIC_ARTIFACTS,
)


class TestArtifactGating:
    def test_tier_a_allows_everything(self):
        gate = OutputGate(SupportTier.A)
        allowed = gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS)
        assert set(allowed) == set(ALL_ARTIFACT_KINDS)

    def test_tier_b_filters_exploitable_only(self):
        gate = OutputGate(SupportTier.B)
        allowed = set(gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS))
        assert "planner_exploitable" not in allowed
        assert "planner_robust" in allowed
        assert "planner_nominal" in allowed
        assert "surface_field" in allowed

    def test_tier_c_only_summary_and_diagnostics(self):
        gate = OutputGate(SupportTier.C)
        allowed = set(gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS))
        assert allowed == {"summary", "diagnostics"}

    def test_tier_d_only_summary_and_diagnostics(self):
        gate = OutputGate(SupportTier.D)
        allowed = set(gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS))
        assert allowed == {"summary", "diagnostics"}


class TestArtifactAccess:
    @pytest.mark.parametrize("tier", list(SupportTier))
    def test_summary_is_always_public(self, tier):
        assert OutputGate(tier).is_artifact_allowed("summary")

    def test_tier_a_allows_exploitable(self):
        assert OutputGate(SupportTier.A).is_artifact_allowed("planner_exploitable")

    def test_tier_b_refuses_exploitable(self):
        assert not OutputGate(SupportTier.B).is_artifact_allowed("planner_exploitable")

    def test_tier_c_refuses_surface_field(self):
        assert not OutputGate(SupportTier.C).is_artifact_allowed("surface_field")

    def test_unknown_artifact_refused(self):
        assert not OutputGate(SupportTier.A).is_artifact_allowed("zzz_unknown")


class TestEndpointGating:
    def test_summary_endpoint_all_tiers(self):
        for tier in SupportTier:
            assert OutputGate(tier).is_endpoint_allowed("summary")

    def test_planner_endpoint_only_a_and_b(self):
        assert OutputGate(SupportTier.A).is_endpoint_allowed("planner")
        assert OutputGate(SupportTier.B).is_endpoint_allowed("planner")
        assert not OutputGate(SupportTier.C).is_endpoint_allowed("planner")
        assert not OutputGate(SupportTier.D).is_endpoint_allowed("planner")

    def test_surface_endpoint_all_except_d(self):
        assert OutputGate(SupportTier.A).is_endpoint_allowed("surface")
        assert OutputGate(SupportTier.B).is_endpoint_allowed("surface")
        assert OutputGate(SupportTier.C).is_endpoint_allowed("surface")
        assert not OutputGate(SupportTier.D).is_endpoint_allowed("surface")

    def test_uncertainty_endpoint_all_except_d(self):
        assert OutputGate(SupportTier.A).is_endpoint_allowed("uncertainty")
        assert not OutputGate(SupportTier.D).is_endpoint_allowed("uncertainty")
