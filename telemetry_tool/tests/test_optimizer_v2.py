"""Integration tests for optimize_stints_v2 — CSP solver wrapper.

Verifies that optimize_stints_v2 returns the dict shape expected by
RaceStateEngine and is compatible with the existing v1 contract.
"""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_strategy_v2 import optimize_stints, optimize_stints_v2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_config(**overrides):
    cfg = {
        "race_duration_s": 14400,   # 4h
        "desired_stints": 6,
        "min_pit_stop_s": 120,
        "fuel_autonomy_s": 7500,    # ~2h05
        "empty_kart_kg": 80.0,
        "full_tank_kg": 88.0,       # 8 kg fuel capacity
        "min_total_kart_kg": 160.0,
        "optimization_mode": "equal",
        "blackout_start_min": 0,
        "blackout_end_min": 0,
        "quick_change_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _two_drivers():
    return [
        {
            "id": 1,
            "driver_name": "Alice",
            "driver_order": 0,
            "weight_kg": 65.0,
            "avg_lap_time_s": 60.0,
            "wet_confidence": 0.7,
            "max_stint_s": None,
            "min_stint_s": None,
            "max_cumulative_s": None,
            "min_cumulative_s": None,
            "min_rest_s": 0,
            "allow_double_stint": False,
        },
        {
            "id": 2,
            "driver_name": "Bob",
            "driver_order": 1,
            "weight_kg": 80.0,
            "avg_lap_time_s": 63.0,
            "wet_confidence": 0.4,
            "max_stint_s": None,
            "min_stint_s": None,
            "max_cumulative_s": None,
            "min_cumulative_s": None,
            "min_rest_s": 0,
            "allow_double_stint": False,
        },
    ]


def _three_drivers():
    return [
        {
            "id": 1, "driver_name": "Alice", "driver_order": 0,
            "weight_kg": 65.0, "avg_lap_time_s": 60.0,
        },
        {
            "id": 2, "driver_name": "Bob", "driver_order": 1,
            "weight_kg": 80.0, "avg_lap_time_s": 63.0,
        },
        {
            "id": 3, "driver_name": "Charlie", "driver_order": 2,
            "weight_kg": 72.0, "avg_lap_time_s": 61.0,
        },
    ]


REQUIRED_RESULT_KEYS = {
    "feasible", "stints", "pit_stops", "driver_summary",
    "violations", "warnings", "total_pit_time_s", "total_drive_time_s",
}

REQUIRED_STINT_KEYS = {
    "stint_order", "driver_id", "driver_name",
    "planned_start_s", "planned_end_s", "planned_duration_s",
}

REQUIRED_PIT_KEYS = {
    "after_stint", "at_s", "duration_s", "refuel", "driver_change",
}


# ---------------------------------------------------------------------------
# Shape tests
# ---------------------------------------------------------------------------

class TestResultShape:
    """optimize_stints_v2 returns the dict shape expected by RaceStateEngine."""

    def test_has_all_top_level_keys(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        assert REQUIRED_RESULT_KEYS.issubset(result.keys())

    def test_stints_have_required_keys(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        assert len(result["stints"]) > 0
        for s in result["stints"]:
            assert REQUIRED_STINT_KEYS.issubset(s.keys()), (
                f"Missing keys in stint: {REQUIRED_STINT_KEYS - s.keys()}"
            )

    def test_pit_stops_have_required_keys(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        assert len(result["pit_stops"]) > 0
        for ps in result["pit_stops"]:
            assert REQUIRED_PIT_KEYS.issubset(ps.keys()), (
                f"Missing keys in pit stop: {REQUIRED_PIT_KEYS - ps.keys()}"
            )

    def test_driver_summary_has_entries(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        assert "Alice" in result["driver_summary"]
        assert "Bob" in result["driver_summary"]
        for name, info in result["driver_summary"].items():
            assert "total_drive_s" in info
            assert "stints" in info

    def test_violations_and_warnings_are_lists(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        assert isinstance(result["violations"], list)
        assert isinstance(result["warnings"], list)


# ---------------------------------------------------------------------------
# Coverage tests
# ---------------------------------------------------------------------------

class TestStintCoverage:
    """Stints must cover the race duration (drive time + pit time)."""

    def test_stints_cover_race_duration(self):
        config = _base_config()
        result = optimize_stints_v2(config, _two_drivers())
        total_drive = sum(s["planned_duration_s"] for s in result["stints"])
        total_pit = result["total_pit_time_s"]
        race_duration = config["race_duration_s"]
        # Within 60s tolerance (rounding)
        assert abs((total_drive + total_pit) - race_duration) < 60

    def test_stint_order_is_sequential(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        orders = [s["stint_order"] for s in result["stints"]]
        assert orders == list(range(1, len(orders) + 1))

    def test_planned_end_equals_start_plus_duration(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        for s in result["stints"]:
            assert s["planned_end_s"] == s["planned_start_s"] + s["planned_duration_s"]

    def test_stints_are_chronological(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        for i in range(1, len(result["stints"])):
            prev = result["stints"][i - 1]
            curr = result["stints"][i]
            assert curr["planned_start_s"] >= prev["planned_end_s"]


# ---------------------------------------------------------------------------
# Feasibility tests
# ---------------------------------------------------------------------------

class TestFeasibility:
    def test_feasible_basic_case(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        assert result["feasible"] is True
        assert len(result["violations"]) == 0

    def test_no_drivers_returns_infeasible(self):
        result = optimize_stints_v2(_base_config(), [])
        assert result["feasible"] is False

    def test_three_drivers_feasible(self):
        result = optimize_stints_v2(_base_config(), _three_drivers())
        assert result["feasible"] is True
        assert len(result["stints"]) >= 6


# ---------------------------------------------------------------------------
# RaceStateEngine compatibility
# ---------------------------------------------------------------------------

class TestRaceStateEngineCompat:
    """V2 result can be fed into RaceStateEngine without error."""

    def test_engine_accepts_v2_result(self):
        from race_state_engine import RaceStateEngine
        config = _base_config()
        drivers = _two_drivers()
        result = optimize_stints_v2(config, drivers)
        # Must not raise
        engine = RaceStateEngine(config, drivers, result["stints"], result["pit_stops"])
        snapshot = engine.snapshot()
        assert "stints" in snapshot


# ---------------------------------------------------------------------------
# V2 vs V1 parity
# ---------------------------------------------------------------------------

class TestV2VsV1Parity:
    """V2 returns a structurally compatible result with V1."""

    def test_same_top_level_keys(self):
        config = _base_config()
        drivers = _two_drivers()
        v1 = optimize_stints(config, drivers)
        v2 = optimize_stints_v2(config, drivers)
        assert set(v1.keys()) == set(v2.keys())

    def test_same_stint_keys(self):
        config = _base_config()
        drivers = _two_drivers()
        v1 = optimize_stints(config, drivers)
        v2 = optimize_stints_v2(config, drivers)
        v1_keys = set(v1["stints"][0].keys()) if v1["stints"] else set()
        v2_keys = set(v2["stints"][0].keys()) if v2["stints"] else set()
        # V2 must have at least the same keys as V1 (may have extras)
        assert v1_keys.issubset(v2_keys)


# ---------------------------------------------------------------------------
# Weather + sleep windows pass-through
# ---------------------------------------------------------------------------

class TestOptionalInputs:
    def test_sleep_windows_respected(self):
        config = _base_config()
        drivers = _two_drivers()
        # Alice sleeps for the middle 2 hours
        sleep = [{"driver_id": 1, "start_s": 5400, "end_s": 12600}]
        result = optimize_stints_v2(config, drivers, sleep_windows=sleep)
        assert result["feasible"] is True
        # Alice should not be driving during her sleep window
        for s in result["stints"]:
            if s["driver_id"] == 1:
                mid = (s["planned_start_s"] + s["planned_end_s"]) / 2
                # Her stints should not be centered in the sleep window
                assert not (5400 < mid < 12600), (
                    f"Alice stint centered at {mid}s inside sleep window"
                )

    def test_weather_windows_accepted(self):
        config = _base_config()
        drivers = _two_drivers()
        weather = [{"start_s": 3600, "end_s": 7200, "condition": "wet"}]
        result = optimize_stints_v2(
            config, drivers, weather_windows=weather,
        )
        assert result["feasible"] is True

    def test_no_optional_inputs(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        assert result["feasible"] is True


# ---------------------------------------------------------------------------
# Fuel + ballast
# ---------------------------------------------------------------------------

class TestFuelAndBallast:
    def test_ballast_present_on_stints(self):
        result = optimize_stints_v2(_base_config(), _two_drivers())
        for s in result["stints"]:
            assert "ballast_kg" in s
            assert isinstance(s["ballast_kg"], (int, float))

    def test_no_fuel_config_still_works(self):
        config = _base_config(fuel_autonomy_s=0, full_tank_kg=0, empty_kart_kg=0)
        result = optimize_stints_v2(config, _two_drivers())
        assert result["feasible"] is True

    def test_auto_increases_stints_for_fuel(self):
        # Very short fuel autonomy forces more stints
        config = _base_config(fuel_autonomy_s=1200, desired_stints=2)
        result = optimize_stints_v2(config, _two_drivers())
        assert len(result["stints"]) > 2
