"""Tests for corner composer — builds CornerCoachingDetail from analyzer outputs."""
import pytest
from telemetry_tool.coaching.composers.corner_composer import compose_corner_coaching
from telemetry_tool.coaching.models import (
    CornerCoachingDetail, SymptomDetection, Symptom,
)
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy


def _corner_perf(**overrides):
    defaults = {
        "corner_id": 3, "s_start": 100.0, "s_end": 200.0,
        "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
        "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
        "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
        "braking_point_delta_m": 12.0,
        "time_loss_s": 0.35, "time_loss_braking_s": 0.15,
        "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
        "grip_utilisation_pct": 68.0,
    }
    defaults.update(overrides)
    return defaults


class TestCornerComposer:
    def test_produces_corner_coaching_detail(self):
        taxonomy = CauseTaxonomy()
        result = compose_corner_coaching(
            corner_perf=_corner_perf(),
            trail_brake=None, traction=None, exit_cascade=None,
            symptoms=None, throttle_lifts=[], weight_transfer=None,
            taxonomy=taxonomy, vehicle_class="car", driver_history=None,
        )
        assert isinstance(result, CornerCoachingDetail)
        assert result.corner_id == 3
        assert result.primary_cause is not None
        assert len(result.coaching_tip) > 10
        assert len(result.progressive_steps) == 3

    def test_symptom_overrides_metric_cause(self):
        """When symptom says early_apex but metrics say braking, use symptom."""
        symptoms = SymptomDetection(
            corner_id=1,
            symptoms=[Symptom("early_apex", "Steering increases past apex",
                              {"steering_increase_deg": 12.0}, 0.9)]
        )
        taxonomy = CauseTaxonomy()
        result = compose_corner_coaching(
            corner_perf=_corner_perf(corner_id=1, braking_point_delta_m=3.0),
            trail_brake=None, traction=None, exit_cascade=None,
            symptoms=symptoms, throttle_lifts=[], weight_transfer=None,
            taxonomy=taxonomy, vehicle_class="car", driver_history=None,
        )
        assert result.primary_cause == "early_apex"

    def test_speed_targets_none_without_theoretical(self):
        taxonomy = CauseTaxonomy()
        result = compose_corner_coaching(
            corner_perf=_corner_perf(
                theoretical_apex_speed_mps=None,
                theoretical_entry_speed_mps=None,
                theoretical_exit_speed_mps=None,
                braking_point_delta_m=0.0,
            ),
            trail_brake=None, traction=None, exit_cascade=None,
            symptoms=None, throttle_lifts=[], weight_transfer=None,
            taxonomy=taxonomy, vehicle_class="car", driver_history=None,
        )
        assert result.apex_speed_target_kmh is None

    def test_large_braking_delta_causes_early_braking(self):
        taxonomy = CauseTaxonomy()
        result = compose_corner_coaching(
            corner_perf=_corner_perf(braking_point_delta_m=15.0),
            trail_brake=None, traction=None, exit_cascade=None,
            symptoms=None, throttle_lifts=[], weight_transfer=None,
            taxonomy=taxonomy, vehicle_class="kart", driver_history=None,
        )
        assert result.primary_cause == "early_braking_confidence"
        assert result.cause_severity in ("mild", "moderate", "severe")
