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
