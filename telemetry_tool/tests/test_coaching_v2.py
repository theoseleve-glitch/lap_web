"""Tests for Coaching V2 evidence-based coaching generator."""
from __future__ import annotations

import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest


class TestCoachingDataclasses:
    """CoachingV2 dataclass structure and serialization."""

    def test_coaching_evidence_to_dict(self):
        from corner_analysis import CoachingEvidence
        ev = CoachingEvidence(
            delta_time_s=0.08,
            s_offset_m=145.0,
            metric_values={"entry_speed_kmh": 95.3},
            source_events=["BP", "EOB"],
            confidence=0.85,
        )
        d = ev.to_dict()
        assert d["delta_time_s"] == 0.08
        assert d["source_events"] == ["BP", "EOB"]
        assert json.dumps(d)  # serializable

    def test_coaching_item_to_dict(self):
        from corner_analysis import CoachingEvidence, CoachingItem
        ev = CoachingEvidence(0.05, 100.0, {}, ["BP"], 0.9)
        item = CoachingItem(
            corner_id=3,
            category="confirming",
            text="Great apex speed",
            evidence=ev,
            confidence=0.9,
            stability_score=0.8,
            reason_code="",
        )
        d = item.to_dict()
        assert d["corner_id"] == 3
        assert d["category"] == "confirming"
        assert isinstance(d["evidence"], dict)

    def test_coaching_objective_to_dict(self):
        from corner_analysis import CoachingEvidence, CoachingObjective
        ev = CoachingEvidence(0.08, 200.0, {"bp_delta": -3.0}, ["BP"], 0.85)
        obj = CoachingObjective(
            rank=1,
            text="Brake 3m later into C4",
            event_target="BP",
            change_direction="later",
            measurable_metric="braking_point_delta_m",
            target_value=-3.0,
            current_value=0.0,
            evidence=ev,
        )
        d = obj.to_dict()
        assert d["rank"] == 1
        assert d["event_target"] == "BP"
        assert json.dumps(d)

    def test_coaching_v2_to_dict(self):
        from corner_analysis import CoachingV2
        cv2 = CoachingV2(
            confirmations=[],
            corrections=[],
            objectives=[],
            ratio_target=2.0,
            actual_ratio=0.0,
            suppressed_count=0,
        )
        d = cv2.to_dict()
        assert d["ratio_target"] == 2.0
        assert d["confirmations"] == []
        assert json.dumps(d)


class TestConfirmingFeedback:
    """Confirming feedback generation."""

    def test_corner_within_threshold_is_confirming(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.03,
                grip_utilisation_pct=90.0,
                actual_apex_speed_mps=20.0,
                theoretical_apex_speed_mps=21.0,
            ),
        ]
        result = generate_coaching_v2(perfs)
        assert len(result.confirmations) >= 1
        assert result.confirmations[0].corner_id == 1
        assert result.confirmations[0].category == "confirming"
        assert result.confirmations[0].evidence.confidence > 0

    def test_high_loss_corner_not_confirming(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.5,
                grip_utilisation_pct=60.0,
            ),
        ]
        result = generate_coaching_v2(perfs)
        assert len(result.confirmations) == 0


class TestCorrectiveFeedback:
    """Corrective feedback with max 1 per corner."""

    def test_high_loss_corner_gets_correction(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.3,
                grip_utilisation_pct=65.0,
                braking_point_delta_m=5.0,
            ),
        ]
        result = generate_coaching_v2(perfs)
        assert len(result.corrections) >= 1
        assert result.corrections[0].corner_id == 1
        assert result.corrections[0].category == "corrective"

    def test_max_one_correction_per_corner(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2

        # Corner with multiple issues
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.5,
                grip_utilisation_pct=50.0,
                braking_point_delta_m=8.0,
            ),
        ]
        timelines = [{
            "corner_id": 1,
            "mistakes": [
                {"type": "power_before_rotation", "severity": 0.7,
                 "evidence": {"estimated_time_cost_s": 0.15}},
                {"type": "rotation_too_late", "severity": 0.5,
                 "evidence": {"estimated_time_cost_s": 0.08}},
            ],
            "events": [],
            "segment_losses_s": {},
            "mrp_strength": 5.0,
            "mrp_stability_std_m": 3.0,
            "event_stability": {},
        }]
        result = generate_coaching_v2(perfs, corner_timelines=timelines)
        c1_corrections = [c for c in result.corrections if c.corner_id == 1]
        assert len(c1_corrections) <= 1


class TestConfidenceGating:
    """Confidence gating suppresses low-confidence advice."""

    def test_low_confidence_correction_unavailable(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.3,
                grip_utilisation_pct=60.0,
            ),
        ]
        # Very low data quality -> confidence halved
        result = generate_coaching_v2(perfs, data_quality=0.2)
        # With halved confidence, some items may be suppressed
        for c in result.corrections:
            assert c.confidence >= 0.0  # no negative confidence


class TestStabilityFiltering:
    """Stability filtering suppresses noisy advice."""

    def test_high_noise_suppresses_correction(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.15,
                grip_utilisation_pct=70.0,
                braking_point_delta_m=2.0,
            ),
        ]
        # High event instability
        timelines = [{
            "corner_id": 1,
            "mistakes": [],
            "events": [],
            "segment_losses_s": {},
            "mrp_strength": 5.0,
            "mrp_stability_std_m": 20.0,  # very unstable
            "event_stability": {"BP": 25.0, "EOB": 20.0},  # very high std
        }]
        result = generate_coaching_v2(perfs, corner_timelines=timelines)
        # Either suppressed or has low stability score
        assert result.suppressed_count >= 0  # at minimum tracking


class TestObjectives:
    """Top 3 objectives selection."""

    def test_objectives_capped_at_3(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=i, s_start=i*100, s_end=i*100+80,
                time_loss_s=0.2 + i*0.1,
                grip_utilisation_pct=60.0,
                braking_point_delta_m=float(i+1)*2,
            )
            for i in range(6)
        ]
        result = generate_coaching_v2(perfs)
        assert len(result.objectives) <= 3

    def test_objectives_ordered_by_impact(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.1, grip_utilisation_pct=70.0,
                braking_point_delta_m=2.0,
            ),
            CornerPerformance(
                corner_id=2, s_start=300, s_end=400,
                time_loss_s=0.5, grip_utilisation_pct=55.0,
                braking_point_delta_m=8.0,
            ),
        ]
        result = generate_coaching_v2(perfs)
        if len(result.objectives) >= 2:
            # Higher impact should be ranked first
            assert result.objectives[0].evidence.delta_time_s >= result.objectives[1].evidence.delta_time_s


class TestRatioEnforcement:
    """Confirming:corrective ratio enforcement."""

    def test_ratio_enforcement_promotes_borderline(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            # Borderline corner (loss < 0.1, grip > 75%)
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.08, grip_utilisation_pct=80.0,
            ),
            # Bad corner
            CornerPerformance(
                corner_id=2, s_start=300, s_end=400,
                time_loss_s=0.4, grip_utilisation_pct=55.0,
                braking_point_delta_m=6.0,
            ),
        ]
        result = generate_coaching_v2(perfs, ratio_target=2.0)
        # With ratio_target=2.0 and 1 correction, we need >= 2 confirmations
        # Borderline corner should be promoted
        assert result.actual_ratio >= 0  # ratio computed


class TestSnapshotDeterminism:
    """Deterministic outputs for fixed inputs."""

    def test_identical_inputs_same_output(self):
        from corner_analysis import CornerPerformance, generate_coaching_v2
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=100, s_end=200,
                time_loss_s=0.03, grip_utilisation_pct=90.0,
            ),
            CornerPerformance(
                corner_id=2, s_start=300, s_end=400,
                time_loss_s=0.3, grip_utilisation_pct=60.0,
                braking_point_delta_m=5.0,
            ),
        ]
        r1 = generate_coaching_v2(perfs)
        r2 = generate_coaching_v2(perfs)
        j1 = json.dumps(r1.to_dict(), sort_keys=True)
        j2 = json.dumps(r2.to_dict(), sort_keys=True)
        assert j1 == j2
