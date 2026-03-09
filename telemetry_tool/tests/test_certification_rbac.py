# telemetry_tool/tests/test_certification_rbac.py
"""Certification RBAC tests — verify backend enforcement of tier gates.

Tests that entitlement definitions correctly map features to tiers,
independent of frontend UI.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from auth.entitlements import (
    KNOWN_PLANS,
    PLAN_ENTITLEMENTS,
    check_usage_limit,
    get_plan_entitlements,
)


class TestPlanEntitlements:

    def test_demo_is_alias_for_free(self):
        assert PLAN_ENTITLEMENTS["demo"] is PLAN_ENTITLEMENTS["free"]

    def test_known_plans_complete(self):
        assert "free" in KNOWN_PLANS
        assert "demo" in KNOWN_PLANS
        assert "racer" in KNOWN_PLANS
        assert "world_class" in KNOWN_PLANS

    def test_demo_limits(self):
        ent = get_plan_entitlements("demo")
        assert ent["reports_per_month"] == 1
        assert ent["uploads_per_month"] == 1
        assert ent["api_access"] is False
        assert ent["comparison_progress"] is False
        assert ent["coaching_drills"] is False
        assert ent["viz_workspace"] is False

    def test_racer_limits(self):
        ent = get_plan_entitlements("racer")
        assert ent["reports_per_month"] == 10
        assert ent["uploads_per_month"] == 10
        assert ent["api_access"] is False
        assert ent["comparison_progress"] is False
        assert ent["coaching_drills"] is True
        assert ent["viz_workspace"] is True

    def test_world_class_limits(self):
        ent = get_plan_entitlements("world_class")
        assert ent["reports_per_month"] == -1
        assert ent["uploads_per_month"] == -1
        assert ent["api_access"] is True
        assert ent["comparison_progress"] is True
        assert ent["coaching_drills"] is True
        assert ent["viz_workspace"] is True

    def test_unknown_plan_falls_back_to_free(self):
        ent = get_plan_entitlements("nonexistent_tier")
        assert ent == PLAN_ENTITLEMENTS["free"]


class TestUsageLimits:

    def test_demo_report_under_limit(self):
        allowed, info = check_usage_limit("demo", "reports", 0)
        assert allowed is True
        assert info["remaining"] == 1

    def test_demo_report_at_limit(self):
        allowed, info = check_usage_limit("demo", "reports", 1)
        assert allowed is False
        assert info["remaining"] == 0

    def test_demo_report_over_limit(self):
        allowed, info = check_usage_limit("demo", "reports", 5)
        assert allowed is False

    def test_racer_report_under_limit(self):
        allowed, info = check_usage_limit("racer", "reports", 5)
        assert allowed is True
        assert info["remaining"] == 5

    def test_world_class_unlimited(self):
        allowed, info = check_usage_limit("world_class", "reports", 9999)
        assert allowed is True
        assert info["remaining"] == -1

    def test_unknown_metric_denied(self):
        allowed, info = check_usage_limit("racer", "unknown_metric", 0)
        assert allowed is False


class TestFeatureAccessMatrix:
    """Parametrized cross-tier feature access verification."""

    MATRIX = [
        ("demo", "api_access", False),
        ("racer", "api_access", False),
        ("world_class", "api_access", True),
        ("demo", "comparison_progress", False),
        ("racer", "comparison_progress", False),
        ("world_class", "comparison_progress", True),
        ("demo", "coaching_drills", False),
        ("racer", "coaching_drills", True),
        ("world_class", "coaching_drills", True),
        ("demo", "viz_workspace", False),
        ("racer", "viz_workspace", True),
        ("world_class", "viz_workspace", True),
        ("demo", "live_pace", False),
        ("racer", "live_pace", True),
        ("world_class", "live_pace", True),
        ("demo", "pdf_reports", False),
        ("racer", "pdf_reports", True),
        ("world_class", "pdf_reports", True),
        ("demo", "max_workspace_members", 1),
        ("racer", "max_workspace_members", 1),
        ("world_class", "max_workspace_members", 5),
    ]

    @pytest.mark.parametrize("plan,feature,expected", MATRIX)
    def test_feature_access(self, plan, feature, expected):
        ent = get_plan_entitlements(plan)
        assert ent[feature] == expected, (
            f"{plan}.{feature}: expected {expected}, got {ent[feature]}"
        )
