"""Tests for the endurance race strategy feature."""

import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def strategy_db():
    """In-memory DB with full schema including race strategy tables."""
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestRaceStrategySchema:
    """Phase 15 tables exist and accept inserts."""

    def test_race_configs_table_exists(self, strategy_db):
        row = strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('Test 3h', 10800) RETURNING race_id"
        ).fetchone()
        assert row["race_id"] >= 1

    def test_race_drivers_table_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'Alice', 1)"
        )
        row = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1").fetchone()
        assert row["driver_name"] == "Alice"

    def test_race_stints_table_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute(
            "INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')"
        )
        row = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = 1").fetchone()
        assert row["stint_order"] == 1

    def test_race_pit_stops_table_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')")
        strategy_db.execute(
            "INSERT INTO race_pit_stops (race_id, stint_id, driver_change, refueled) VALUES (1, 1, 1, 0)"
        )
        row = strategy_db.execute("SELECT * FROM race_pit_stops WHERE race_id = 1").fetchone()
        assert row["driver_change"] == 1

    def test_race_configs_default_values(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        row = strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone()
        assert row["status"] == "draft"
        assert row["desired_stints"] == 4
        assert row["min_pit_stop_s"] == 60
        assert row["weigh_on_pit_exit"] == 0

    def test_schema_version_is_20(self, strategy_db):
        row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 20


class TestOptimizer:
    """Stint allocation optimizer."""

    def test_basic_equal_split(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 10800,  # 3h
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        assert len(result["stints"]) == 3
        total_drive = sum(s["planned_duration_s"] for s in result["stints"])
        total_pit = (3 - 1) * 60
        assert total_drive + total_pit == 10800

    def test_fuel_autonomy_caps_stint(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,  # 40 min max
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        for s in result["stints"]:
            assert s["planned_duration_s"] <= 2400

    def test_driver_max_stint_respected(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": 1800,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "B", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        for s in result["stints"]:
            if s["driver_id"] == 1:
                assert s["planned_duration_s"] <= 1800

    def test_infeasible_returns_false(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        # Both drivers max 1000s each = 2000s, race needs 7140s drive time
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": 1000,
             "min_cumulative_s": None, "max_cumulative_s": 1000, "min_rest_s": 0},
            {"id": 2, "driver_name": "B", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": 1000,
             "min_cumulative_s": None, "max_cumulative_s": 1000, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is False
        assert len(result["violations"]) > 0

    def test_round_robin_driver_assignment(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 4,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "B", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        driver_ids = [s["driver_id"] for s in result["stints"]]
        assert driver_ids == [1, 2, 1, 2]


class TestBallastCalculator:
    """Ballast calculation per stint."""

    def test_basic_ballast(self):
        from race_strategy_v2 import compute_ballast
        result = compute_ballast(
            min_total_kart_kg=165.0,
            empty_kart_kg=80.0,
            fuel_kg=12.0,
            driver_weight_kg=70.0,
        )
        assert result == pytest.approx(3.0)

    def test_no_ballast_needed(self):
        from race_strategy_v2 import compute_ballast
        result = compute_ballast(
            min_total_kart_kg=150.0,
            empty_kart_kg=80.0,
            fuel_kg=12.0,
            driver_weight_kg=70.0,
        )
        assert result == pytest.approx(0.0)  # 162 > 150, no ballast needed

    def test_ballast_clamps_to_zero(self):
        from race_strategy_v2 import compute_ballast
        result = compute_ballast(
            min_total_kart_kg=100.0,
            empty_kart_kg=80.0,
            fuel_kg=12.0,
            driver_weight_kg=70.0,
        )
        assert result == 0.0  # Already over minimum
