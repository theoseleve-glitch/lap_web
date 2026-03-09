"""Test edge cases across modules."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestEdgeCases:
    def test_empty_brake_precision(self):
        from brake_precision import compute_brake_precision
        result = compute_brake_precision({})
        assert result == []

    def test_single_lap_throttle(self):
        from throttle_mapping import compute_throttle_profiles
        metrics = {1: [{"corner_id": 1, "throttle_onset_m": 10.0}]}
        result = compute_throttle_profiles(metrics)
        assert result is not None

    def test_empty_consistency_heatmap(self):
        from consistency_heatmap import compute_consistency_heatmap
        result = compute_consistency_heatmap({})
        assert result["laps"] == []

    def test_what_if_empty_profile(self):
        from what_if_simulator import simulate_what_if
        result = simulate_what_if({"distances": [], "speeds": []}, [])
        assert result["baseline_time_s"] == 0

    def test_setup_tracker_empty(self):
        from setup_tracker import correlate_setup_vs_pace
        result = correlate_setup_vs_pace([])
        assert result["n_sessions"] == 0

    def test_fuel_calc_empty(self):
        from fuel_calculator import model_fuel_effect
        result = model_fuel_effect([])
        assert result["seconds_per_kg"] == 0

    def test_line_opt_empty(self):
        from line_optimization import identify_line_deviations
        result = identify_line_deviations(
            {"latitudes": [], "longitudes": []},
            {"latitudes": [], "longitudes": []},
        )
        assert result["mean_deviation_m"] == 0

    def test_annotations_empty_body(self, test_db):
        from annotations import create_annotation
        with pytest.raises(ValueError):
            create_annotation(test_db, "s1", "")

    def test_dashboard_empty_name(self, test_db):
        from dashboard_builder import create_dashboard
        with pytest.raises(ValueError):
            create_dashboard(test_db, "", [{"type": "recent_sessions"}])

    def test_plan_bad_template(self, test_db):
        from development_plan import create_plan_from_template
        with pytest.raises(ValueError):
            create_plan_from_template(test_db, 1, "nonexistent")
