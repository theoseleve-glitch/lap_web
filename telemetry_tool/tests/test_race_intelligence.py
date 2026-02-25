"""Tests for the race intelligence module — stateless race analytics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_intelligence import predict_finish, fuel_alerts, pace_analysis, swap_suggestion, rival_analysis, analyze_race


class TestPredictFinish:

    def test_remaining_time(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=3600.0,
            stints=[], race_start_ts=None, neutralizations=[],
        )
        assert result["remaining_s"] == 3600

    def test_completion_pct(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=1800.0,
            stints=[], race_start_ts=None, neutralizations=[],
        )
        assert result["completion_pct"] == pytest.approx(25.0, abs=0.1)

    def test_pace_status_on_plan(self):
        stints = [
            {"status": "completed", "actual_duration_s": 2360, "planned_duration_s": 2360},
        ]
        result = predict_finish(
            race_duration_s=7200, elapsed_s=2420.0,
            stints=stints, race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "ON PLAN"
        assert result["pace_delta_s"] == 0

    def test_pace_status_behind(self):
        stints = [
            {"status": "completed", "actual_duration_s": 2420, "planned_duration_s": 2360},
        ]
        result = predict_finish(
            race_duration_s=7200, elapsed_s=2480.0,
            stints=stints, race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "BEHIND"
        assert result["pace_delta_s"] == 60

    def test_pace_status_ahead(self):
        stints = [
            {"status": "completed", "actual_duration_s": 2300, "planned_duration_s": 2360},
        ]
        result = predict_finish(
            race_duration_s=7200, elapsed_s=2360.0,
            stints=stints, race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "AHEAD"
        assert result["pace_delta_s"] == -60

    def test_no_completed_stints_is_on_plan(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=100.0,
            stints=[], race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "ON PLAN"

    def test_neutralized_time_subtracted(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=3600.0,
            stints=[], race_start_ts=None,
            neutralizations=[{"start_s": 1000, "end_s": 1600}],
        )
        assert result["neutralized_total_s"] == 600


class TestFuelAlerts:

    def test_fuel_ok(self):
        result = fuel_alerts(
            current_fuel_kg=6.0, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=500.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "ok"
        assert result["fuel_remaining_s"] > 300

    def test_fuel_warning(self):
        result = fuel_alerts(
            current_fuel_kg=0.8, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=2000.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "warning"

    def test_fuel_critical(self):
        result = fuel_alerts(
            current_fuel_kg=0.3, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=2200.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "critical"

    def test_can_reach_pit_true(self):
        result = fuel_alerts(
            current_fuel_kg=6.5, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=500.0,
            next_planned_pit_s=2360,
        )
        assert result["can_reach_pit"] is True
        assert result["shortfall_s"] == 0

    def test_can_reach_pit_false(self):
        result = fuel_alerts(
            current_fuel_kg=0.3, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=2000.0,
            next_planned_pit_s=2360,
        )
        assert result["can_reach_pit"] is False
        assert result["shortfall_s"] > 0

    def test_zero_burn_rate_safe(self):
        result = fuel_alerts(
            current_fuel_kg=5.0, burn_rate_kgs=0.0,
            active_stint_end_s=2360, elapsed_s=500.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "ok"
        assert result["can_reach_pit"] is True


class TestPaceAnalysis:

    def test_no_completed_stints_returns_none_deltas(self):
        result = pace_analysis(stints=[], active_stint=None, elapsed_s=100.0)
        assert result["pace_vs_own_avg_s"] is None
        assert result["pace_vs_field_avg_s"] is None
        assert result["pace_trend"] == "stable"

    def test_own_average_comparison(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2400, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2380, "planned_duration_s": 2360},
        ]
        active = {"driver_id": 1, "planned_start_s": 4900, "planned_duration_s": 2360, "status": "active"}
        result = pace_analysis(stints=stints, active_stint=active, elapsed_s=5500.0)
        assert result["pace_vs_own_avg_s"] is not None

    def test_pace_trend_degrading(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2400, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2450, "planned_duration_s": 2360},
        ]
        result = pace_analysis(stints=stints, active_stint=None, elapsed_s=7500.0)
        assert result["pace_trend"] == "degrading"

    def test_pace_trend_improving(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2450, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2400, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
        ]
        result = pace_analysis(stints=stints, active_stint=None, elapsed_s=7500.0)
        assert result["pace_trend"] == "improving"


class TestSwapSuggestion:

    def test_no_suggestion_when_pace_ok(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
        ]
        active = {"driver_id": 1, "planned_start_s": 2420, "planned_duration_s": 2360, "status": "active"}
        drivers = [
            {"id": 1, "driver_name": "Alice", "max_cumulative_s": 7200},
            {"id": 2, "driver_name": "Bob", "max_cumulative_s": 7200},
        ]
        result = swap_suggestion(
            stints=stints, drivers=drivers, active_stint=active,
            elapsed_s=3000.0, burn_rate_kgs=0.003333, current_fuel_kg=5.0,
        )
        assert result is None

    def test_suggestion_when_pace_degraded(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2700, "planned_duration_s": 2360},
        ]
        active = {"driver_id": 1, "planned_start_s": 5200, "planned_duration_s": 2360, "status": "active"}
        drivers = [
            {"id": 1, "driver_name": "Alice", "max_cumulative_s": 7200},
            {"id": 2, "driver_name": "Bob", "max_cumulative_s": 7200},
        ]
        result = swap_suggestion(
            stints=stints, drivers=drivers, active_stint=active,
            elapsed_s=6000.0, burn_rate_kgs=0.003333, current_fuel_kg=3.0,
        )
        assert result is not None
        assert result["suggest_swap"] is True
        assert "Bob" in result["next_driver"]


class TestRivalAnalysis:

    def test_empty_rivals(self):
        result = rival_analysis(rivals=[], rival_events=[], elapsed_s=3600.0)
        assert result == []

    def test_single_rival_with_pits(self):
        rivals = [{"id": 1, "team_name": "Alpha", "car_number": "42"}]
        events = [
            {"rival_id": 1, "event_type": "pit_in", "at_s": 1200},
            {"rival_id": 1, "event_type": "pit_in", "at_s": 2400},
            {"rival_id": 1, "event_type": "pit_in", "at_s": 3600},
        ]
        result = rival_analysis(rivals=rivals, rival_events=events, elapsed_s=4000.0)
        assert len(result) == 1
        assert result[0]["team_name"] == "Alpha"
        assert result[0]["estimated_pits"] == 3
        assert result[0]["avg_stint_s"] == 1200

    def test_last_activity_seconds(self):
        rivals = [{"id": 1, "team_name": "Beta", "car_number": "7"}]
        events = [{"rival_id": 1, "event_type": "pit_in", "at_s": 3000}]
        result = rival_analysis(rivals=rivals, rival_events=events, elapsed_s=3600.0)
        assert result[0]["last_activity_s"] == 600


class TestAnalyzeRace:

    def test_analyze_race_returns_all_keys(self):
        result = analyze_race(
            race_duration_s=7200, elapsed_s=3600.0, race_start_ts=None,
            stints=[], active_stint=None, drivers=[], neutralizations=[],
            current_fuel_kg=5.0, burn_rate_kgs=0.003333,
            active_stint_end_s=7200, next_planned_pit_s=None,
            rivals=[], rival_events=[],
        )
        assert "finish" in result
        assert "fuel" in result
        assert "pace" in result
        assert "swap" in result
        assert "rivals" in result
