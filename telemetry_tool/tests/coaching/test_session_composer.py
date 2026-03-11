"""Tests for session composer — full assembly."""
import pytest
from telemetry_tool.coaching.composers.session_composer import compose_session_coaching
from telemetry_tool.coaching.models import SessionCoaching
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy


def _corner_perfs(n=5):
    return [
        {"corner_id": i, "s_start": i * 100, "s_end": i * 100 + 50,
         "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
         "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
         "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
         "braking_point_delta_m": 10.0,
         "time_loss_s": 0.3, "time_loss_braking_s": 0.1,
         "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
         "grip_utilisation_pct": 65.0}
        for i in range(1, n + 1)
    ]


class TestSessionComposer:
    def test_produces_session_coaching(self):
        scores = {"total_score": 72, "grade": "B", "strengths": ["pace"],
                  "weaknesses": ["consistency"],
                  "sub_scores": {"pace": {"pct": 0.8}}}
        taxonomy = CauseTaxonomy()
        result = compose_session_coaching(
            corner_perfs=_corner_perfs(),
            coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_results={},
            taxonomy=taxonomy, vehicle_class="car",
            driver_history=None, previous_goals=None,
        )
        assert isinstance(result, SessionCoaching)
        assert len(result.focus_areas) <= 2
        assert len(result.drills) >= 1
        assert len(result.next_session_goals) >= 1
        assert result.vehicle_class == "car"

    def test_backward_compat_fields_present(self):
        scores = {"total_score": 50, "grade": "D", "strengths": [], "weaknesses": [],
                  "sub_scores": {}}
        taxonomy = CauseTaxonomy()
        result = compose_session_coaching(
            corner_perfs=_corner_perfs(1),
            coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_results={}, taxonomy=taxonomy,
            vehicle_class="car", driver_history=None, previous_goals=None,
        )
        d = result.to_dict()
        for key in ("session_theme", "narrative", "strengths", "weaknesses",
                     "focus_areas", "drills", "progression", "next_session_goals", "confidence"):
            assert key in d

    def test_corner_coaching_populated(self):
        scores = {"total_score": 65, "grade": "C", "strengths": [], "weaknesses": [],
                  "sub_scores": {}}
        taxonomy = CauseTaxonomy()
        result = compose_session_coaching(
            corner_perfs=_corner_perfs(3),
            coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_results={}, taxonomy=taxonomy,
            vehicle_class="kart", driver_history=None, previous_goals=None,
        )
        assert result.corner_coaching is not None
        assert len(result.corner_coaching) == 3
        for cc in result.corner_coaching:
            assert cc.primary_cause is not None

    def test_full_serialization_roundtrip(self):
        scores = {"total_score": 80, "grade": "A", "strengths": ["fast"],
                  "weaknesses": ["braking"], "sub_scores": {}}
        taxonomy = CauseTaxonomy()
        result = compose_session_coaching(
            corner_perfs=_corner_perfs(2),
            coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_results={}, taxonomy=taxonomy,
            vehicle_class="car", driver_history=None, previous_goals=None,
        )
        d = result.to_dict()
        # Should be fully JSON-serializable (no dataclass objects remaining)
        import json
        json_str = json.dumps(d)
        assert len(json_str) > 100
