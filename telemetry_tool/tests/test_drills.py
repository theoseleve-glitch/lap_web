"""Tests for drill registry, issue->drill mapping, and practice plan generation."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from drills import (
    DRILL_REGISTRY,
    Drill,
    PracticePlan,
    generate_practice_plan,
    map_issues_to_drills,
)


class TestDrillRegistry:
    def test_registry_not_empty(self):
        assert len(DRILL_REGISTRY) >= 8

    def test_drill_has_required_fields(self):
        d = DRILL_REGISTRY[0]
        assert d.drill_id
        assert d.title
        assert d.required_channels
        assert d.issue_types

    def test_all_drill_ids_unique(self):
        ids = [d.drill_id for d in DRILL_REGISTRY]
        assert len(ids) == len(set(ids))

    def test_drill_to_dict(self):
        d = DRILL_REGISTRY[0].to_dict()
        assert "drill_id" in d
        assert "success_criteria" in d


class TestMapIssuesToDrills:
    def test_maps_over_drop(self):
        coaching_v2 = {
            "corrections": [
                {"corner_id": 3, "text": "test", "evidence": {"source_events": ["BP"]},
                 "reason_code": "over_drop"}
            ]
        }
        result = map_issues_to_drills(coaching_v2, ["Brake (%)", "accel_long"])
        assert any(r["drill_id"] == "brake_release_progressive" for r in result)

    def test_no_duplicate_drills(self):
        coaching_v2 = {
            "corrections": [
                {"corner_id": 3, "reason_code": "over_drop"},
                {"corner_id": 5, "reason_code": "over_drop"},
            ]
        }
        result = map_issues_to_drills(coaching_v2, ["Brake (%)", "accel_long"])
        drill_ids = [r["drill_id"] for r in result]
        assert len(drill_ids) == len(set(drill_ids))

    def test_empty_coaching(self):
        result = map_issues_to_drills({}, ["speed"])
        assert result == []

    def test_missing_channels_reported(self):
        coaching_v2 = {
            "corrections": [{"corner_id": 3, "reason_code": "over_drop"}]
        }
        result = map_issues_to_drills(coaching_v2, ["speed"])  # no Brake, no accel_long
        assert any(r.get("missing_channels") for r in result)


class TestGeneratePracticePlan:
    def test_returns_practice_plan(self):
        coaching_v2 = {
            "corrections": [
                {"corner_id": 3, "reason_code": "over_drop"},
                {"corner_id": 5, "reason_code": "under_rotation"},
            ]
        }
        plan = generate_practice_plan(coaching_v2, ["Brake (%)", "yaw_rate", "accel_long"])
        assert isinstance(plan, PracticePlan)
        assert plan.warmup is not None
        assert len(plan.drills) <= 2

    def test_max_drills_cap(self):
        coaching_v2 = {
            "corrections": [
                {"corner_id": i, "reason_code": "over_drop"} for i in range(10)
            ]
        }
        plan = generate_practice_plan(coaching_v2, ["Brake (%)"], max_drills=1)
        assert len(plan.drills) <= 1

    def test_channel_warnings(self):
        coaching_v2 = {
            "corrections": [{"corner_id": 3, "reason_code": "under_rotation"}]
        }
        plan = generate_practice_plan(coaching_v2, ["speed"])
        assert isinstance(plan.channel_warnings, list)

    def test_to_dict(self):
        plan = generate_practice_plan({"corrections": []}, ["speed"])
        d = plan.to_dict()
        assert "warmup" in d
        assert "drills" in d
        assert "evaluation" in d

    def test_empty_coaching_returns_minimal_plan(self):
        plan = generate_practice_plan({}, ["speed"])
        assert isinstance(plan, PracticePlan)
        assert len(plan.drills) == 0
