"""Tests for coaching V3 pipeline stages."""
import pytest
from telemetry_tool.pipeline.stages.s13_coaching_v3 import (
    run_coaching_analyzers, run_multi_session_lookup, run_enhanced_coaching,
    persist_coaching_v3,
)


class TestRunCoachingAnalyzers:
    def test_returns_analyzer_bundle(self):
        """With minimal valid data, returns dict with analyzer keys."""
        corner_perfs = [{"corner_id": 1, "s_start": 0, "s_end": 100,
                         "theoretical_entry_speed_mps": 25.0,
                         "actual_entry_speed_mps": 22.0,
                         "theoretical_apex_speed_mps": 18.0,
                         "actual_apex_speed_mps": 16.0,
                         "theoretical_exit_speed_mps": 23.0,
                         "actual_exit_speed_mps": 20.0,
                         "braking_point_delta_m": 10.0,
                         "time_loss_s": 0.3}]
        result = run_coaching_analyzers(
            corner_perfs=corner_perfs, best_lap_df=None,
            theoretical_result=None, friction_model=None,
            resampled_laps={}, available_columns=set(),
        )
        assert isinstance(result, dict)
        for key in ("trail_brakes", "exit_cascades", "traction_budgets",
                     "symptoms", "throttle_lifts", "weight_transfers"):
            assert key in result

    def test_empty_corners_returns_empty_bundle(self):
        result = run_coaching_analyzers(
            corner_perfs=[], best_lap_df=None,
            theoretical_result=None, friction_model=None,
            resampled_laps={}, available_columns=set(),
        )
        assert all(len(v) == 0 for v in result.values())

    def test_none_corners_returns_empty_bundle(self):
        result = run_coaching_analyzers(
            corner_perfs=None, best_lap_df=None,
            theoretical_result=None, friction_model=None,
            resampled_laps={}, available_columns=set(),
        )
        assert isinstance(result, dict)


class TestRunMultiSessionLookup:
    def test_returns_none_without_pg(self, monkeypatch):
        monkeypatch.setenv("USE_PG", "0")
        result = run_multi_session_lookup(
            driver_id=1, track_id=1, corner_ids=[1, 2, 3],
        )
        assert result is None

    def test_returns_none_without_driver(self):
        result = run_multi_session_lookup(
            driver_id=None, track_id=1, corner_ids=[1],
        )
        assert result is None


class TestRunEnhancedCoaching:
    def test_returns_coaching_dict(self):
        corner_perfs = [{"corner_id": 1, "s_start": 0, "s_end": 100,
                         "theoretical_entry_speed_mps": 25.0,
                         "actual_entry_speed_mps": 22.0,
                         "theoretical_apex_speed_mps": 18.0,
                         "actual_apex_speed_mps": 16.0,
                         "theoretical_exit_speed_mps": 23.0,
                         "actual_exit_speed_mps": 20.0,
                         "braking_point_delta_m": 10.0,
                         "time_loss_s": 0.3, "time_loss_braking_s": 0.1,
                         "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
                         "grip_utilisation_pct": 65.0}]
        scores = {"total_score": 65, "grade": "C", "strengths": [], "weaknesses": [],
                  "sub_scores": {}}
        result = run_enhanced_coaching(
            corner_perfs=corner_perfs, coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_bundle={}, driver_history=None,
            vehicle_class="car", previous_goals=None,
        )
        assert isinstance(result, dict)
        assert "session_theme" in result
        assert "corner_coaching" in result

    def test_falls_back_on_missing_scores(self):
        fallback = {"old": "coaching"}
        result = run_enhanced_coaching(
            corner_perfs=[{"corner_id": 1}],
            coaching_v2=fallback, scores=None,
            lap_metrics=None, driving_style=None,
            analyzer_bundle={}, driver_history=None,
        )
        assert result == fallback

    def test_falls_back_on_missing_corners(self):
        fallback = {"old": "coaching"}
        result = run_enhanced_coaching(
            corner_perfs=None, coaching_v2=fallback,
            scores={"grade": "B"}, lap_metrics=None,
            driving_style=None, analyzer_bundle={},
            driver_history=None,
        )
        assert result == fallback


class TestPersistCoachingV3:
    def test_writes_to_analysis_json(self):
        analysis = {}
        coaching = {"session_theme": "Test", "corner_coaching": []}
        persist_coaching_v3(
            coaching_dict=coaching, analysis_json=analysis,
            conn=None, session_id=None, driver_id=None,
            track_id=None, corner_coaching=None,
        )
        assert "coaching_v3" in analysis
        assert analysis["coaching_v3"]["session_theme"] == "Test"

    def test_none_coaching_does_nothing(self):
        analysis = {}
        persist_coaching_v3(
            coaching_dict=None, analysis_json=analysis,
            conn=None, session_id=None, driver_id=None,
            track_id=None, corner_coaching=None,
        )
        assert "coaching_v3" not in analysis
