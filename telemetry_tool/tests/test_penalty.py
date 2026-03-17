"""Tests for the penalty tracker service."""

import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def strategy_db():
    """In-memory DB with full schema including race_penalties table."""
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def live_race(strategy_db):
    """A live race with one active stint, ready for penalty operations."""
    from services.race_strategy import create_race, go_live
    from datetime import datetime, timezone

    race_id = create_race(strategy_db, {
        "race": {
            "race_name": "Penalty Test Race",
            "race_duration_s": 7200,
            "desired_stints": 2,
        },
        "drivers": [
            {"driver_name": "Alice", "weight_kg": 60},
        ],
    })

    # Insert a stint so go_live has something to activate
    strategy_db.execute(
        "INSERT INTO race_stints (race_id, stint_order, driver_id, "
        "planned_start_s, planned_end_s, planned_duration_s, status) "
        "VALUES (?,?,?,?,?,?,?)",
        (race_id, 1, 1, 0, 3600, 3600, "planned"),
    )
    strategy_db.commit()

    go_live(strategy_db, race_id)
    return race_id


class TestAddPenalty:
    """add_penalty creates a record in race_penalties."""

    def test_add_penalty_creates_record(self, strategy_db, live_race):
        from services.race_strategy_penalty import add_penalty

        result = add_penalty(
            strategy_db, live_race,
            penalty_type="passage",
            laps_deducted=0,
            reason="Pit lane speeding",
            passage_duration_s=30,
        )

        assert result is not None
        assert result["ok"] is True
        assert result["penalty_type"] == "passage"
        assert "elapsed_s" in result

        # Verify in DB
        rows = strategy_db.execute(
            "SELECT * FROM race_penalties WHERE race_id = ?",
            (live_race,),
        ).fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["penalty_type"] == "passage"
        assert row["reason"] == "Pit lane speeding"
        assert row["passage_duration_s"] == 30
        assert row["cleared"] == 0

    def test_add_penalty_returns_none_for_missing_race(self, strategy_db):
        from services.race_strategy_penalty import add_penalty

        result = add_penalty(strategy_db, 9999, penalty_type="laps", laps_deducted=1)
        assert result is None


class TestClearPenalty:
    """clear_penalty marks a penalty as cleared with a timestamp."""

    def test_clear_penalty_marks_cleared(self, strategy_db, live_race):
        from services.race_strategy_penalty import add_penalty, clear_penalty

        add_penalty(strategy_db, live_race, penalty_type="passage",
                     passage_duration_s=30)

        # Find the penalty ID
        row = strategy_db.execute(
            "SELECT id FROM race_penalties WHERE race_id = ?", (live_race,)
        ).fetchone()
        penalty_id = row["id"]

        result = clear_penalty(strategy_db, live_race, penalty_id)
        assert result is not None
        assert result["ok"] is True
        assert "cleared_at_s" in result

        # Verify in DB
        row = strategy_db.execute(
            "SELECT cleared, cleared_at_s FROM race_penalties WHERE id = ?",
            (penalty_id,),
        ).fetchone()
        assert row["cleared"] == 1
        assert row["cleared_at_s"] is not None

    def test_clear_penalty_returns_none_for_missing(self, strategy_db, live_race):
        from services.race_strategy_penalty import clear_penalty

        result = clear_penalty(strategy_db, live_race, 9999)
        assert result is None


class TestGetPenalties:
    """get_penalties returns all penalties for a race."""

    def test_get_penalties_returns_list(self, strategy_db, live_race):
        from services.race_strategy_penalty import add_penalty, get_penalties

        add_penalty(strategy_db, live_race, penalty_type="warning", reason="Track limits")
        add_penalty(strategy_db, live_race, penalty_type="laps", laps_deducted=2, reason="Contact")

        penalties = get_penalties(strategy_db, live_race)
        assert len(penalties) == 2
        assert penalties[0]["penalty_type"] == "warning"
        assert penalties[1]["penalty_type"] == "laps"
        assert penalties[1]["laps_deducted"] == 2

    def test_get_penalties_empty_for_no_penalties(self, strategy_db, live_race):
        from services.race_strategy_penalty import get_penalties

        penalties = get_penalties(strategy_db, live_race)
        assert penalties == []


class TestGetActivePassage:
    """get_active_passage returns the oldest uncleared passage penalty."""

    def test_get_active_passage_returns_uncleared(self, strategy_db, live_race):
        from services.race_strategy_penalty import (
            add_penalty, clear_penalty, get_active_passage,
        )

        # Add two passage penalties
        add_penalty(strategy_db, live_race, penalty_type="passage",
                     passage_duration_s=30, reason="P1")
        add_penalty(strategy_db, live_race, penalty_type="passage",
                     passage_duration_s=60, reason="P2")

        # Clear the first one
        first = strategy_db.execute(
            "SELECT id FROM race_penalties WHERE race_id = ? ORDER BY id LIMIT 1",
            (live_race,),
        ).fetchone()
        clear_penalty(strategy_db, live_race, first["id"])

        # Active passage should be the second (uncleared) one
        active = get_active_passage(strategy_db, live_race)
        assert active is not None
        assert active["reason"] == "P2"
        assert active["passage_duration_s"] == 60

    def test_get_active_passage_returns_none_when_all_cleared(self, strategy_db, live_race):
        from services.race_strategy_penalty import (
            add_penalty, clear_penalty, get_active_passage,
        )

        add_penalty(strategy_db, live_race, penalty_type="passage",
                     passage_duration_s=30)
        row = strategy_db.execute(
            "SELECT id FROM race_penalties WHERE race_id = ?", (live_race,)
        ).fetchone()
        clear_penalty(strategy_db, live_race, row["id"])

        active = get_active_passage(strategy_db, live_race)
        assert active is None
