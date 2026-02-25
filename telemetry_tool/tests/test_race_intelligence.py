"""Tests for the race intelligence module — stateless race analytics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_intelligence import predict_finish, fuel_alerts


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
