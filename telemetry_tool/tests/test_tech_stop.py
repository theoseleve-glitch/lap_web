"""Tests for tech stop feature in race strategy."""

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

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


def _create_live_race(conn, tech_stop_duration_s=360):
    """Helper: create a race with one driver, one active stint, status=live."""
    now = datetime.now(timezone.utc)
    start_ts = (now - timedelta(seconds=1800)).isoformat()
    conn.execute(
        "INSERT INTO race_configs (race_name, race_duration_s, tech_stop_enabled, "
        "tech_stop_duration_s, race_start_ts, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Test Race", 10800, 1, tech_stop_duration_s, start_ts, "live"),
    )
    race_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (?, ?, ?)",
        (race_id, "Alice", 1),
    )
    driver_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (?, ?, ?, ?)",
        (race_id, 1, driver_id, "active"),
    )
    conn.commit()
    return race_id


class TestTechStopIn:
    """tech_stop_in does not change active stint status."""

    def test_tech_stop_in_leaves_stint_active(self, strategy_db):
        from services.race_strategy_tech import tech_stop_in
        race_id = _create_live_race(strategy_db)

        result = tech_stop_in(strategy_db, race_id)
        assert result is not None
        assert result["ok"] is True
        assert result["tech_stop"] is True

        # Stint should still be active
        stint = strategy_db.execute(
            "SELECT status FROM race_stints WHERE race_id = ? AND status = 'active'",
            (race_id,),
        ).fetchone()
        assert stint is not None
        assert stint["status"] == "active"

    def test_tech_stop_in_rejects_if_already_in_pit(self, strategy_db):
        from services.race_strategy_tech import tech_stop_in
        race_id = _create_live_race(strategy_db)

        # First tech stop in
        result1 = tech_stop_in(strategy_db, race_id)
        assert result1 is not None

        # Second should be rejected
        result2 = tech_stop_in(strategy_db, race_id)
        assert result2 is None


class TestTechStopOut:
    """tech_stop_out validates duration and creates pit_stop record."""

    def test_rejects_if_duration_less_than_minimum(self, strategy_db):
        from services.race_strategy_tech import tech_stop_in, tech_stop_out
        race_id = _create_live_race(strategy_db, tech_stop_duration_s=9999)

        tech_stop_in(strategy_db, race_id)
        result = tech_stop_out(strategy_db, race_id)
        assert result is not None
        assert result["error"] == "too_early"
        assert result["remaining_s"] > 0

    def test_creates_pit_stop_with_type_tech(self, strategy_db):
        from services.race_strategy_tech import tech_stop_in, tech_stop_out
        race_id = _create_live_race(strategy_db, tech_stop_duration_s=0)

        tech_stop_in(strategy_db, race_id)
        result = tech_stop_out(strategy_db, race_id)
        assert result is not None
        assert result["ok"] is True

        pit = strategy_db.execute(
            "SELECT * FROM race_pit_stops WHERE race_id = ? AND pit_type = 'tech'",
            (race_id,),
        ).fetchone()
        assert pit is not None
        assert pit["pit_type"] == "tech"
        assert pit["driver_change"] == 0  # False stored as 0 in SQLite

    def test_clears_pit_in_at_s(self, strategy_db):
        from services.race_strategy_tech import tech_stop_in, tech_stop_out
        race_id = _create_live_race(strategy_db, tech_stop_duration_s=0)

        tech_stop_in(strategy_db, race_id)
        # Verify pit_in_at_s is set
        race = strategy_db.execute(
            "SELECT pit_in_at_s FROM race_configs WHERE race_id = ?", (race_id,)
        ).fetchone()
        assert race["pit_in_at_s"] is not None

        tech_stop_out(strategy_db, race_id)
        # Verify pit_in_at_s is cleared
        race = strategy_db.execute(
            "SELECT pit_in_at_s FROM race_configs WHERE race_id = ?", (race_id,)
        ).fetchone()
        assert race["pit_in_at_s"] is None

    def test_returns_none_if_not_in_tech_stop(self, strategy_db):
        from services.race_strategy_tech import tech_stop_out
        race_id = _create_live_race(strategy_db)

        result = tech_stop_out(strategy_db, race_id)
        assert result is None
