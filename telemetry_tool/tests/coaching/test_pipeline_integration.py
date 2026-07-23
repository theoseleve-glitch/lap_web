"""Tests for coaching V3 pipeline stages."""
import json
import pytest
from telemetry_tool.pipeline.stages.s13_coaching_v3 import (
    run_coaching_analyzers, run_multi_session_lookup, run_enhanced_coaching,
    persist_coaching_v3,
)
from coaching.composers.session_composer import compose_session_coaching
from coaching.taxonomy.causes import CauseTaxonomy


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
        # Fallback must be tagged "engine": "v2_fallback" (not a silent,
        # indistinguishable-from-v3 v2 payload) -- see test_coaching_engine_tag.py.
        fallback = {"old": "coaching"}
        result = run_enhanced_coaching(
            corner_perfs=[{"corner_id": 1}],
            coaching_v2=fallback, scores=None,
            lap_metrics=None, driving_style=None,
            analyzer_bundle={}, driver_history=None,
        )
        assert result == {**fallback, "engine": "v2_fallback"}

    def test_falls_back_on_missing_corners(self):
        fallback = {"old": "coaching"}
        result = run_enhanced_coaching(
            corner_perfs=None, coaching_v2=fallback,
            scores={"grade": "B"}, lap_metrics=None,
            driving_style=None, analyzer_bundle={},
            driver_history=None,
        )
        assert result == {**fallback, "engine": "v2_fallback"}


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


class TestEndToEndCoachingV3:
    """Full end-to-end test: analyzer → composer → persist → API shape."""

    def _make_corner_perfs(self, n=5):
        return [
            {"corner_id": i, "s_start": i * 100, "s_end": i * 100 + 50,
             "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
             "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
             "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
             "braking_point_delta_m": 10.0 + i,
             "time_loss_s": 0.3 + i * 0.05, "time_loss_braking_s": 0.1 + i * 0.02,
             "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
             "grip_utilisation_pct": 65.0 - i * 2}
            for i in range(1, n + 1)
        ]

    def test_full_v3_pipeline_produces_valid_output(self):
        """Simulate: analyzers → enhanced coaching → persist → JSON serialize."""
        corner_perfs = self._make_corner_perfs(4)
        scores = {
            "total_score": 68, "grade": "C",
            "strengths": ["pace", "execution"],
            "weaknesses": ["consistency", "braking"],
            "sub_scores": {"pace": {"pct": 0.82}},
        }

        # Step 1: Run analyzers (no lap data — analyzers degrade gracefully)
        bundle = run_coaching_analyzers(
            corner_perfs=corner_perfs, best_lap_df=None,
            theoretical_result=None, friction_model=None,
            resampled_laps={}, available_columns=set(),
        )
        assert isinstance(bundle, dict)

        # Step 2: Run enhanced coaching
        coaching_dict = run_enhanced_coaching(
            corner_perfs=corner_perfs, coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_bundle=bundle, driver_history=None,
            vehicle_class="kart", previous_goals=None,
        )
        assert isinstance(coaching_dict, dict)

        # Step 3: Persist to analysis_json
        analysis = {}
        persist_coaching_v3(
            coaching_dict=coaching_dict, analysis_json=analysis,
            conn=None, session_id=1, driver_id=1,
            track_id=1, corner_coaching=coaching_dict.get("corner_coaching"),
        )
        assert "coaching_v3" in analysis

        # Step 4: Validate API shape
        result = analysis["coaching_v3"]
        assert result["vehicle_class"] == "kart"
        assert len(result["focus_areas"]) <= 2
        assert len(result["drills"]) >= 1
        assert len(result["next_session_goals"]) >= 1
        assert "corner_coaching" in result
        assert len(result["corner_coaching"]) == 4

        # Each corner has required fields
        for cc in result["corner_coaching"]:
            assert "corner_id" in cc
            assert "primary_cause" in cc
            assert "coaching_tip" in cc
            assert len(cc["progressive_steps"]) == 3

        # Backward-compat fields present
        for key in ("session_theme", "narrative", "strengths", "weaknesses",
                     "focus_areas", "drills", "progression", "next_session_goals",
                     "confidence"):
            assert key in result

        # Full JSON serializable
        json_str = json.dumps(result)
        assert len(json_str) > 500

    def test_v3_graceful_with_single_corner(self):
        """Even with 1 corner, produces valid output."""
        corner_perfs = self._make_corner_perfs(1)
        scores = {"total_score": 85, "grade": "A", "strengths": ["fast"],
                  "weaknesses": [], "sub_scores": {}}

        coaching_dict = run_enhanced_coaching(
            corner_perfs=corner_perfs, coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_bundle={}, driver_history=None,
            vehicle_class="car",
        )
        assert isinstance(coaching_dict, dict)
        assert len(coaching_dict["corner_coaching"]) == 1
        assert coaching_dict["corner_coaching"][0]["corner_id"] == 1
