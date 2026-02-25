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


class TestRaceStrategyIntegration:
    """Integration tests for the race strategy lifecycle."""

    def test_create_and_list(self, strategy_db):
        """Create a race and verify it appears in queries."""
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('Test 3h', 10800)"
        )
        strategy_db.commit()
        rows = strategy_db.execute("SELECT * FROM race_configs").fetchall()
        assert len(rows) == 1
        assert rows[0]["race_name"] == "Test 3h"

    def test_optimize_and_save_stints(self, strategy_db):
        """Full flow: create race, add drivers, optimize, save stints."""
        from race_strategy_v2 import optimize_stints

        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, desired_stints, min_pit_stop_s) "
            "VALUES ('Race', 7200, 4, 60)"
        )
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 70)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'B', 2, 80)")
        strategy_db.commit()

        race = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order").fetchall()]

        result = optimize_stints(race, drivers)
        assert result["feasible"] is True
        assert len(result["stints"]) == 4

        # Save stints to DB
        for s in result["stints"]:
            strategy_db.execute(
                "INSERT INTO race_stints (race_id, stint_order, driver_id, planned_start_s, planned_end_s, planned_duration_s, status) "
                "VALUES (?,?,?,?,?,?,'planned')",
                (1, s["stint_order"], s["driver_id"], s["planned_start_s"], s["planned_end_s"], s["planned_duration_s"]),
            )
        strategy_db.commit()

        stints = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = 1").fetchall()
        assert len(stints) == 4
        assert all(s["status"] == "planned" for s in stints)

    def test_reoptimize_mid_race(self, strategy_db):
        """Mid-race re-optimization adjusts remaining stints."""
        from race_strategy_v2 import optimize_stints, reoptimize_remaining

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
        assert result["feasible"] is True

        # Simulate: first stint completed, took 1800s
        completed = [{
            "stint_order": 1,
            "driver_id": 1,
            "actual_duration_s": 1800,
        }]
        elapsed = 1860  # 1800 drive + 60 pit

        reopt = reoptimize_remaining(config, drivers, completed, elapsed)
        assert reopt["feasible"] is True
        assert len(reopt["stints"]) == 3  # 4 - 1 completed = 3 remaining
        # All remaining stints should start after elapsed time
        for s in reopt["stints"]:
            assert s["planned_start_s"] >= elapsed

    def test_duplicate_race(self, strategy_db):
        """Duplicating a race copies config and drivers."""
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('Original', 7200)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.commit()

        # Simulate duplicate
        race = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        cur = strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES (?, ?)",
            (race["race_name"] + " (copy)", race["race_duration_s"]),
        )
        new_id = cur.lastrowid
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (?, 'A', 1)", (new_id,)
        )
        strategy_db.commit()

        races = strategy_db.execute("SELECT * FROM race_configs ORDER BY race_id").fetchall()
        assert len(races) == 2
        assert races[1]["race_name"] == "Original (copy)"

        drivers = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = ?", (new_id,)).fetchall()
        assert len(drivers) == 1

    def test_cascade_delete(self, strategy_db):
        """Deleting a race cascades to drivers, stints, pit stops."""
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')")
        strategy_db.execute("INSERT INTO race_pit_stops (race_id, driver_change, refueled) VALUES (1, 1, 0)")
        strategy_db.commit()

        # Enable FK enforcement for cascade test
        strategy_db.execute("PRAGMA foreign_keys = ON")
        strategy_db.execute("DELETE FROM race_configs WHERE race_id = 1")
        strategy_db.commit()

        assert strategy_db.execute("SELECT COUNT(*) FROM race_drivers").fetchone()[0] == 0
        assert strategy_db.execute("SELECT COUNT(*) FROM race_stints").fetchone()[0] == 0
        assert strategy_db.execute("SELECT COUNT(*) FROM race_pit_stops").fetchone()[0] == 0

    def test_status_transitions(self, strategy_db):
        """Race status follows draft -> ready -> live -> finished."""
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.commit()

        row = strategy_db.execute("SELECT status FROM race_configs WHERE race_id = 1").fetchone()
        assert row["status"] == "draft"

        strategy_db.execute("UPDATE race_configs SET status = 'ready' WHERE race_id = 1")
        row = strategy_db.execute("SELECT status FROM race_configs WHERE race_id = 1").fetchone()
        assert row["status"] == "ready"

        strategy_db.execute("UPDATE race_configs SET status = 'live' WHERE race_id = 1")
        row = strategy_db.execute("SELECT status FROM race_configs WHERE race_id = 1").fetchone()
        assert row["status"] == "live"

        strategy_db.execute("UPDATE race_configs SET status = 'finished' WHERE race_id = 1")
        row = strategy_db.execute("SELECT status FROM race_configs WHERE race_id = 1").fetchone()
        assert row["status"] == "finished"

    def test_no_drivers_infeasible(self):
        """Optimizer with no drivers returns infeasible."""
        from race_strategy_v2 import optimize_stints
        config = {"race_duration_s": 3600, "desired_stints": 2, "min_pit_stop_s": 60}
        result = optimize_stints(config, [])
        assert result["feasible"] is False
        assert "No drivers" in result["violations"][0]

    def test_pit_time_exceeds_race(self):
        """Optimizer reports infeasible when pit time exceeds race duration."""
        from race_strategy_v2 import optimize_stints
        config = {"race_duration_s": 100, "desired_stints": 10, "min_pit_stop_s": 60}
        drivers = [{"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
                     "min_stint_s": None, "max_stint_s": None,
                     "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0}]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is False
