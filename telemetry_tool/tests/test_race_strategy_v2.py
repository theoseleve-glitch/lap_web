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

    def test_schema_version_is_24(self, strategy_db):
        row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 24

    def test_race_windows_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_windows (race_id, window_type, start_s, end_s, window_order) "
            "VALUES (1, 'pitlane', 300, 3300, 1)"
        )
        row = strategy_db.execute("SELECT * FROM race_windows WHERE race_id = 1").fetchone()
        assert row["window_type"] == "pitlane"
        assert row["start_s"] == 300
        assert row["end_s"] == 3300

    def test_race_windows_has_rule_columns(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
            "refuel_allowed, driver_change_allowed, window_order) "
            "VALUES (1, 'tech_stop', 'Tech 1', 1800, 2400, 0, 1, 1)"
        )
        row = strategy_db.execute("SELECT * FROM race_windows WHERE race_id = 1").fetchone()
        assert row["label"] == "Tech 1"
        assert row["refuel_allowed"] == 0
        assert row["driver_change_allowed"] == 1

    def test_race_drivers_has_color_hex_column(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, color_hex) "
            "VALUES (1, 'Alice', 1, '#58a6ff')"
        )
        row = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1").fetchone()
        assert row["color_hex"] == "#58a6ff"

    def test_race_stints_has_ballast_decomposition_columns(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute(
            "INSERT INTO race_stints (race_id, stint_order, driver_id, ballast_base_kg, "
            "ballast_fuel_offset_kg, fuel_burn_rate_kgs, status) VALUES (1, 1, 1, 2.0, 1.5, 0.003, 'planned')"
        )
        row = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = 1").fetchone()
        assert row["ballast_base_kg"] == 2.0
        assert row["ballast_fuel_offset_kg"] == 1.5
        assert row["fuel_burn_rate_kgs"] == 0.003

    def test_race_configs_has_quick_pit_stop_column(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, quick_pit_stop_s) VALUES ('R', 3600, 30)"
        )
        row = strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone()
        assert row["quick_pit_stop_s"] == 30

    def test_race_pit_stops_has_pit_type_column(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')")
        strategy_db.execute(
            "INSERT INTO race_pit_stops (race_id, stint_id, driver_change, refueled, pit_type) VALUES (1, 1, 1, 0, 'quick')"
        )
        row = strategy_db.execute("SELECT * FROM race_pit_stops WHERE race_id = 1").fetchone()
        assert row["pit_type"] == "quick"


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


class TestImportExport:
    """JSON import/export for race configs."""

    def test_export_structure(self, strategy_db):
        """Export produces valid JSON with all sections."""
        from web.routes.race_strategy_v2 import _build_export_dict

        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, desired_stints) VALUES ('Export Test', 7200, 4)"
        )
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 70)")
        strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, planned_duration_s, status) VALUES (1, 1, 1, 1800, 'planned')")
        strategy_db.execute("INSERT INTO race_pit_stops (race_id, driver_change, refueled) VALUES (1, 1, 0)")
        strategy_db.commit()

        result = _build_export_dict(strategy_db, 1)
        assert result["version"] == 1
        assert result["race"]["race_name"] == "Export Test"
        assert len(result["drivers"]) == 1
        assert len(result["stints"]) == 1
        assert len(result["pit_stops"]) == 1

    def test_import_creates_race(self, strategy_db):
        """Import JSON creates a new race in draft status."""
        from web.routes.race_strategy_v2 import _import_race_from_dict

        data = {
            "version": 1,
            "race": {
                "race_name": "Imported Race",
                "race_duration_s": 10800,
                "desired_stints": 3,
                "min_pit_stop_s": 60,
                "status": "finished",
            },
            "drivers": [
                {"driver_name": "Alice", "driver_order": 1, "weight_kg": 70,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
                {"driver_name": "Bob", "driver_order": 2, "weight_kg": 80,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            ],
            "stints": [],
            "pit_stops": [],
        }

        race_id = _import_race_from_dict(strategy_db, data)
        assert race_id >= 1

        race = strategy_db.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
        assert race["race_name"] == "Imported Race"
        assert race["status"] == "draft"  # Always draft on import

        drivers = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)).fetchall()
        assert len(drivers) == 2
        assert drivers[0]["driver_name"] == "Alice"

    def test_import_remaps_driver_ids_in_stints(self, strategy_db):
        """Import remaps old driver IDs to new auto-increment IDs."""
        from web.routes.race_strategy_v2 import _import_race_from_dict

        data = {
            "version": 1,
            "race": {"race_name": "Remap Test", "race_duration_s": 3600, "min_pit_stop_s": 60},
            "drivers": [
                {"id": 99, "driver_name": "Old", "driver_order": 1, "weight_kg": 70,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            ],
            "stints": [
                {"stint_order": 1, "driver_id": 99, "planned_duration_s": 1800,
                 "planned_start_s": 0, "planned_end_s": 1800, "status": "planned",
                 "ballast_kg": 0, "actual_start_s": None, "actual_end_s": None,
                 "actual_duration_s": None, "notes": None},
            ],
            "pit_stops": [],
        }

        race_id = _import_race_from_dict(strategy_db, data)
        stints = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = ?", (race_id,)).fetchall()
        assert len(stints) == 1
        # The driver_id should be the NEW auto-increment id, not 99
        new_driver = strategy_db.execute("SELECT id FROM race_drivers WHERE race_id = ?", (race_id,)).fetchone()
        assert stints[0]["driver_id"] == new_driver["id"]

    def test_import_rejects_missing_name(self, strategy_db):
        """Import rejects JSON without race_name."""
        from web.routes.race_strategy_v2 import _import_race_from_dict

        data = {"version": 1, "race": {"race_duration_s": 3600}, "drivers": [], "stints": [], "pit_stops": []}
        with pytest.raises(ValueError, match="race_name"):
            _import_race_from_dict(strategy_db, data)

    def test_roundtrip_export_import(self, strategy_db):
        """Export then import produces equivalent race."""
        from web.routes.race_strategy_v2 import _build_export_dict, _import_race_from_dict

        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, desired_stints, team_name) "
            "VALUES ('Roundtrip', 7200, 4, 'Team X')"
        )
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 70)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'B', 2, 80)")
        strategy_db.commit()

        exported = _build_export_dict(strategy_db, 1)
        new_id = _import_race_from_dict(strategy_db, exported)

        new_race = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = ?", (new_id,)).fetchone())
        assert new_race["race_name"] == "Roundtrip"
        assert new_race["team_name"] == "Team X"
        assert new_race["race_duration_s"] == 7200

        new_drivers = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (new_id,)).fetchall()
        assert len(new_drivers) == 2


class TestQualifyingFuel:
    """Qualifying fuel deduction in optimizer."""

    def test_qualifying_no_refuel_reduces_first_stint(self):
        """Without refuel-after-quali, first stint fuel is reduced."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,
            "qualifying_duration_s": 600,
            "refuel_after_quali": 0,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        # First stint should be capped at fuel_autonomy - qualifying_duration
        assert result["stints"][0]["planned_duration_s"] <= 2400 - 600

    def test_qualifying_with_refuel_no_change(self):
        """With refuel-after-quali, first stint uses full autonomy."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,
            "qualifying_duration_s": 600,
            "refuel_after_quali": 1,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        assert result["stints"][0]["planned_duration_s"] <= 2400

    def test_qualifying_no_fuel_autonomy_no_effect(self):
        """Without fuel_autonomy_s, qualifying has no optimizer effect."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "qualifying_duration_s": 600,
            "refuel_after_quali": 0,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True


class TestPitWindows:
    """Pit window enforcement in optimizer."""

    def test_pit_open_delays_first_pit(self):
        """First pit stop should not happen before pit_open_s."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "pit_open_s": 1800,
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
        # First pit stop (end of stint 1) should be >= pit_open_s
        assert result["stints"][0]["planned_end_s"] >= 1800

    def test_pit_close_ensures_last_pit_before_close(self):
        """Last pit stop should happen before pit_close_s from end."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "pit_close_s": 1800,
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
        if result["pit_stops"]:
            last_pit = result["pit_stops"][-1]
            assert last_pit["at_s"] <= 5400

    def test_pit_window_warning_when_violated(self):
        """When constraints force a pit outside window, add warning."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 3600,
            "desired_stints": 4,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "pit_open_s": 2400,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        pit_warnings = [w for w in result["warnings"] if "pit window" in w.lower()]
        assert len(pit_warnings) > 0 or result["stints"][0]["planned_end_s"] >= 2400


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


class TestTier3Schema:
    """Tier 3 schema: race_messages table and com_channel column."""

    def test_race_messages_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_messages (race_id, author, message, category) "
            "VALUES (1, 'Engineer', 'Box box box', 'pit')"
        )
        row = strategy_db.execute("SELECT * FROM race_messages WHERE race_id = 1").fetchone()
        assert row["author"] == "Engineer"
        assert row["category"] == "pit"

    def test_race_messages_cascade_delete(self, strategy_db):
        strategy_db.execute("PRAGMA foreign_keys = ON")
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message) VALUES (1, 'A', 'test')")
        strategy_db.commit()
        strategy_db.execute("DELETE FROM race_configs WHERE race_id = 1")
        assert strategy_db.execute("SELECT COUNT(*) FROM race_messages").fetchone()[0] == 0

    def test_com_channel_column_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, com_channel) "
            "VALUES (1, 'Alice', 1, 'CH 7')"
        )
        row = strategy_db.execute("SELECT com_channel FROM race_drivers WHERE race_id = 1").fetchone()
        assert row["com_channel"] == "CH 7"

    def test_schema_version_is_24(self, strategy_db):
        row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 24


class TestTeamTalk:
    """TeamTalk message CRUD."""

    def test_insert_and_retrieve_messages(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message, category) VALUES (1, 'Eng', 'Box now', 'pit')")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message, category) VALUES (1, 'Spotter', 'Rain in 10', 'weather')")
        strategy_db.commit()
        msgs = strategy_db.execute("SELECT * FROM race_messages WHERE race_id = 1 ORDER BY msg_id").fetchall()
        assert len(msgs) == 2
        assert msgs[0]["category"] == "pit"
        assert msgs[1]["category"] == "weather"

    def test_messages_included_in_export(self, strategy_db):
        from web.routes.race_strategy_v2 import _build_export_dict
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message) VALUES (1, 'A', 'hello')")
        strategy_db.commit()
        result = _build_export_dict(strategy_db, 1)
        assert "messages" in result
        assert len(result["messages"]) == 1

    def test_com_channel_in_export(self, strategy_db):
        from web.routes.race_strategy_v2 import _build_export_dict
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, com_channel) "
            "VALUES (1, 'A', 1, 'CH 5')"
        )
        strategy_db.commit()
        result = _build_export_dict(strategy_db, 1)
        assert result["drivers"][0]["com_channel"] == "CH 5"


class TestI18n:
    """Multilingual translation loading."""

    def test_load_english(self):
        from web.i18n import load_translations
        t = load_translations("en")
        assert t["race_strategy"] == "Race Strategy"
        assert t["driver"] == "Driver"

    def test_load_french(self):
        from web.i18n import load_translations
        t = load_translations("fr")
        assert t["race_strategy"] == "Stratégie de Course"

    def test_fallback_to_english(self):
        from web.i18n import load_translations
        t = load_translations("xx")
        assert t["race_strategy"] == "Race Strategy"

    def test_missing_key_returns_english(self):
        from web.i18n import load_translations
        t = load_translations("fr")
        assert "race_strategy" in t


class TestWeatherIntegration:
    """Weather features for race strategy."""

    def test_fuel_adjustment_wet(self):
        """Wet grip factor reduces effective fuel autonomy."""
        from wet_physics import get_grip_factor
        grip = get_grip_factor("wet")
        base_autonomy = 2400
        adjusted = int(base_autonomy * grip)
        assert adjusted < base_autonomy
        assert adjusted > 0

    def test_fuel_adjustment_dry(self):
        """Dry conditions don't reduce autonomy."""
        from wet_physics import get_grip_factor
        grip = get_grip_factor("dry")
        base_autonomy = 2400
        adjusted = int(base_autonomy * grip)
        assert adjusted == base_autonomy

    def test_track_conditions_from_weather(self):
        """estimate_track_conditions returns grip info."""
        from meteo_service import estimate_track_conditions
        weather = {
            "air_temp_c": 20, "humidity_pct": 50, "wind_speed_mps": 3,
            "rain_mm": 0, "cloud_cover_pct": 30
        }
        result = estimate_track_conditions(weather)
        assert "track_state" in result
        assert "grip_score" in result


class TestTier6Schema:
    """Tier 6 schema — neutralizations, rivals, rival events."""

    def test_schema_version_is_24(self, strategy_db):
        row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 24

    def test_race_neutralizations_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_neutralizations (race_id, start_s, reason) "
            "VALUES (1, 600, 'safety_car')"
        )
        row = strategy_db.execute("SELECT * FROM race_neutralizations WHERE race_id = 1").fetchone()
        assert row["start_s"] == 600
        assert row["end_s"] is None
        assert row["reason"] == "safety_car"

    def test_race_rivals_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_rivals (race_id, team_name, car_number) "
            "VALUES (1, 'Team Alpha', '42')"
        )
        row = strategy_db.execute("SELECT * FROM race_rivals WHERE race_id = 1").fetchone()
        assert row["team_name"] == "Team Alpha"
        assert row["car_number"] == "42"

    def test_race_rival_events_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_rivals (race_id, team_name, car_number) VALUES (1, 'X', '1')"
        )
        strategy_db.execute(
            "INSERT INTO race_rival_events (race_id, rival_id, event_type, at_s, detail) "
            "VALUES (1, 1, 'pit_in', 1200, 'quick stop')"
        )
        row = strategy_db.execute("SELECT * FROM race_rival_events WHERE race_id = 1").fetchone()
        assert row["event_type"] == "pit_in"
        assert row["at_s"] == 1200
        assert row["detail"] == "quick stop"
