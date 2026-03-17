"""Tests for the race strategy bridge service.

The bridge links endurance sessions (detected stints) to the race strategy
system (race_configs + race_stints + race_actuals).  Tests use in-memory
SQLite with manually applied migration 046/047 DDL since those tables are
not yet in the base ``ensure_schema()``.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# DDL for tables created by migrations 046 and 047 (not yet in schema.py)
# ---------------------------------------------------------------------------

_ENDURANCE_STINTS_DDL = """
CREATE TABLE IF NOT EXISTS endurance_stints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL REFERENCES sessions(session_id),
    stint_number    INTEGER NOT NULL,
    start_lap       INTEGER NOT NULL,
    end_lap         INTEGER NOT NULL,
    lap_count       INTEGER NOT NULL,
    pit_lap_number  INTEGER,
    pit_lap_time_s  REAL,
    condition       TEXT    DEFAULT 'dry',
    driver_id       INTEGER,
    driver_name     TEXT,
    UNIQUE(session_id, stint_number)
);
"""

_RACE_CONFIGS_EXTRA_COLS = """
ALTER TABLE race_configs ADD COLUMN session_id TEXT;
ALTER TABLE race_configs ADD COLUMN is_retrospective INTEGER NOT NULL DEFAULT 0;
"""

_RACE_ACTUALS_DDL = """
CREATE TABLE IF NOT EXISTS race_actuals (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id                  INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_order              INTEGER NOT NULL,
    actual_start_s           INTEGER,
    actual_end_s             INTEGER,
    actual_duration_s        INTEGER,
    actual_lap_count         INTEGER,
    actual_best_lap_s        REAL,
    actual_mean_lap_s        REAL,
    actual_consistency_cv_pct REAL,
    actual_pace_fade_pct     REAL,
    delta_duration_s         INTEGER,
    UNIQUE(race_id, stint_order)
);
"""

# Also need pit_threshold_s on sessions
_SESSIONS_EXTRA_COL = """
ALTER TABLE sessions ADD COLUMN pit_threshold_s REAL;
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bridge_db():
    """In-memory SQLite with full schema + migration 046/047 tables."""
    from db.migrate import ensure_schema

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    # Apply migration 046/047 DDL manually
    conn.executescript(_ENDURANCE_STINTS_DDL)
    conn.executescript(_RACE_ACTUALS_DDL)
    # Add extra columns (ALTER TABLE one at a time for SQLite)
    for stmt in _RACE_CONFIGS_EXTRA_COLS.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # Column may already exist
    try:
        conn.execute(_SESSIONS_EXTRA_COL.strip())
    except Exception:
        pass
    conn.commit()

    yield conn
    conn.close()


def _seed_session(conn, session_id: str = "sess-001") -> str:
    """Insert a minimal driver + session row and return session_id."""
    conn.execute(
        "INSERT OR IGNORE INTO drivers (driver_id, driver_name) VALUES (1, 'TestDriver')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO sessions "
        "(session_id, csv_filename, driver_id, session_date) "
        "VALUES (?, 'test.csv', 1, '2026-03-16')",
        (session_id,),
    )
    conn.commit()
    return session_id


def _seed_laps(conn, session_id: str, lap_times: list[float]) -> None:
    """Insert lap rows for a session."""
    for i, lt in enumerate(lap_times, start=1):
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES (?, ?, ?)",
            (session_id, i, lt),
        )
    conn.commit()


def _seed_stints(conn, session_id: str, stints: list[dict]) -> None:
    """Insert endurance_stints rows."""
    for s in stints:
        conn.execute(
            "INSERT INTO endurance_stints "
            "(session_id, stint_number, start_lap, end_lap, lap_count, "
            " pit_lap_number, pit_lap_time_s) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                s["stint_number"],
                s["start_lap"],
                s["end_lap"],
                s["end_lap"] - s["start_lap"] + 1,
                s.get("pit_lap_number"),
                s.get("pit_lap_time_s"),
            ),
        )
    conn.commit()


def _seed_full_scenario(conn):
    """Seed a complete 2-stint session with laps and stints.

    Stint 1: laps 1-5 (60s each)
    Pit lap 6: 120s
    Stint 2: laps 7-11 (62s each)

    Returns (session_id, stints, driver_map).
    """
    sid = _seed_session(conn)

    # 5 racing laps + 1 pit lap + 5 racing laps
    lap_times = [60.0] * 5 + [120.0] + [62.0] * 5
    _seed_laps(conn, sid, lap_times)

    stints = [
        {
            "stint_number": 1,
            "start_lap": 1,
            "end_lap": 5,
            "pit_lap_number": 6,
            "pit_lap_time_s": 120.0,
        },
        {
            "stint_number": 2,
            "start_lap": 7,
            "end_lap": 11,
            "pit_lap_number": None,
            "pit_lap_time_s": None,
        },
    ]
    _seed_stints(conn, sid, stints)

    driver_map = {1: "Alice", 2: "Bob"}
    return sid, stints, driver_map


# ---------------------------------------------------------------------------
# create_race_from_session tests
# ---------------------------------------------------------------------------

class TestCreateRaceFromSession:

    def test_creates_retrospective_race(self, bridge_db):
        """Happy path: creates a race_config with is_retrospective=1."""
        sid, _, driver_map = _seed_full_scenario(bridge_db)

        from services.race_strategy_bridge import create_race_from_session

        race_id = create_race_from_session(
            bridge_db,
            sid,
            race_meta={"race_name": "Test 3h"},
            driver_map=driver_map,
        )
        assert race_id >= 1

        row = bridge_db.execute(
            "SELECT is_retrospective, session_id FROM race_configs WHERE race_id = ?",
            (race_id,),
        ).fetchone()
        assert bool(row["is_retrospective"]) is True
        assert row["session_id"] == sid

    def test_populates_race_actuals(self, bridge_db):
        """Actuals rows match stint count."""
        sid, _, driver_map = _seed_full_scenario(bridge_db)

        from services.race_strategy_bridge import create_race_from_session

        race_id = create_race_from_session(
            bridge_db, sid,
            race_meta={"race_name": "Actuals Test"},
            driver_map=driver_map,
        )

        actuals = bridge_db.execute(
            "SELECT * FROM race_actuals WHERE race_id = ? ORDER BY stint_order",
            (race_id,),
        ).fetchall()
        assert len(actuals) == 2

        # Stint 1: 5 laps x 60s = 300s
        a1 = dict(actuals[0])
        assert a1["actual_duration_s"] == 300
        assert a1["actual_lap_count"] == 5
        assert a1["actual_best_lap_s"] == pytest.approx(60.0, abs=0.01)

        # Stint 2: 5 laps x 62s = 310s
        a2 = dict(actuals[1])
        assert a2["actual_duration_s"] == 310
        assert a2["actual_lap_count"] == 5

    def test_delta_duration_computed(self, bridge_db):
        """Planned vs actual delta is stored."""
        sid, _, driver_map = _seed_full_scenario(bridge_db)

        from services.race_strategy_bridge import create_race_from_session

        race_id = create_race_from_session(
            bridge_db, sid,
            race_meta={"race_name": "Delta Test"},
            driver_map=driver_map,
        )

        actuals = bridge_db.execute(
            "SELECT delta_duration_s FROM race_actuals WHERE race_id = ? ORDER BY stint_order",
            (race_id,),
        ).fetchall()
        # delta_duration_s = actual - planned; both should be non-None
        for row in actuals:
            assert row["delta_duration_s"] is not None

    def test_rejects_session_without_stints(self, bridge_db):
        """ValueError when session has < 2 stints."""
        sid = _seed_session(bridge_db)
        _seed_laps(bridge_db, sid, [60.0] * 5)
        # Only 1 stint
        _seed_stints(bridge_db, sid, [{
            "stint_number": 1, "start_lap": 1, "end_lap": 5,
        }])

        from services.race_strategy_bridge import create_race_from_session

        with pytest.raises(ValueError, match="at least 2"):
            create_race_from_session(
                bridge_db, sid,
                race_meta={"race_name": "Too Few"},
                driver_map={1: "Alice"},
            )

    def test_rejects_incomplete_driver_map(self, bridge_db):
        """ValueError when driver_map is missing stint numbers."""
        sid, _, _ = _seed_full_scenario(bridge_db)

        from services.race_strategy_bridge import create_race_from_session

        # Only map stint 1, but we have stints 1 and 2
        with pytest.raises(ValueError, match="driver_map missing"):
            create_race_from_session(
                bridge_db, sid,
                race_meta={"race_name": "Incomplete"},
                driver_map={1: "Alice"},  # Missing stint 2
            )

    def test_driver_weights_propagated(self, bridge_db):
        """Driver weight from race_meta flows to race_drivers."""
        sid, _, driver_map = _seed_full_scenario(bridge_db)

        from services.race_strategy_bridge import create_race_from_session

        race_id = create_race_from_session(
            bridge_db, sid,
            race_meta={
                "race_name": "Weight Test",
                "empty_kart_kg": 80.0,
                "full_tank_kg": 90.0,
                "min_total_kart_kg": 165.0,
            },
            driver_map=driver_map,
        )

        drivers = bridge_db.execute(
            "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
            (race_id,),
        ).fetchall()
        assert len(drivers) >= 2
        # Drivers should be persisted with names from driver_map
        names = [d["driver_name"] for d in drivers]
        assert "Alice" in names
        assert "Bob" in names

    def test_optimizer_runs_on_retrospective(self, bridge_db):
        """After creation, planned stints exist in race_stints."""
        sid, _, driver_map = _seed_full_scenario(bridge_db)

        from services.race_strategy_bridge import create_race_from_session

        race_id = create_race_from_session(
            bridge_db, sid,
            race_meta={"race_name": "Optimizer Test"},
            driver_map=driver_map,
        )

        planned = bridge_db.execute(
            "SELECT * FROM race_stints WHERE race_id = ? ORDER BY stint_order",
            (race_id,),
        ).fetchall()
        # Optimizer should have created planned stints
        assert len(planned) >= 2


# ---------------------------------------------------------------------------
# get_planned_vs_actual tests
# ---------------------------------------------------------------------------

class TestGetPlannedVsActual:

    def _create_race(self, conn):
        """Helper: seed full scenario and create a retrospective race."""
        sid, _, driver_map = _seed_full_scenario(conn)
        from services.race_strategy_bridge import create_race_from_session
        return create_race_from_session(
            conn, sid,
            race_meta={"race_name": "PvA Test"},
            driver_map=driver_map,
        )

    def test_returns_side_by_side(self, bridge_db):
        """Response has race, stints, and summary keys."""
        race_id = self._create_race(bridge_db)

        from services.race_strategy_bridge import get_planned_vs_actual

        result = get_planned_vs_actual(bridge_db, race_id)
        assert result is not None
        assert "race" in result
        assert "stints" in result
        assert "summary" in result
        assert len(result["stints"]) >= 2

        # Each stint has planned, actual, and delta
        for stint in result["stints"]:
            assert "planned" in stint
            assert "actual" in stint
            assert "delta_duration_s" in stint

    def test_summary_totals_correct(self, bridge_db):
        """total_planned_s and total_actual_s sum correctly."""
        race_id = self._create_race(bridge_db)

        from services.race_strategy_bridge import get_planned_vs_actual

        result = get_planned_vs_actual(bridge_db, race_id)
        summary = result["summary"]

        # Verify sums match individual stints
        sum_planned = sum(
            s["planned"]["duration_s"] or 0 for s in result["stints"]
        )
        sum_actual = sum(
            s["actual"]["duration_s"] or 0 for s in result["stints"]
        )
        assert summary["total_planned_s"] == sum_planned
        assert summary["total_actual_s"] == sum_actual
        assert summary["delta_s"] == sum_actual - sum_planned

    def test_driver_deltas_correct(self, bridge_db):
        """Per-driver totals in summary.driver_deltas are consistent."""
        race_id = self._create_race(bridge_db)

        from services.race_strategy_bridge import get_planned_vs_actual

        result = get_planned_vs_actual(bridge_db, race_id)
        driver_deltas = result["summary"]["driver_deltas"]

        # Each driver in deltas should have planned, actual, delta totals
        for name, dd in driver_deltas.items():
            assert "planned_s" in dd
            assert "actual_s" in dd
            assert "delta_s" in dd
            assert "stint_count" in dd
            assert dd["stint_count"] >= 1

    def test_returns_none_for_unknown_race(self, bridge_db):
        """get_planned_vs_actual returns None for a non-existent race_id."""
        from services.race_strategy_bridge import get_planned_vs_actual

        result = get_planned_vs_actual(bridge_db, 99999)
        assert result is None


# ---------------------------------------------------------------------------
# Repo-level helpers: endurance_stints round-trip
# ---------------------------------------------------------------------------

class TestEnduranceRepoIntegration:

    def test_detect_and_get_round_trip(self, bridge_db):
        """detect_and_store_stints followed by get_stints round-trips."""
        sid = _seed_session(bridge_db)
        # 5 normal laps + 1 pit + 5 normal
        _seed_laps(bridge_db, sid, [60.0] * 5 + [150.0] + [61.0] * 5)

        from web.repos.endurance_repo import detect_and_store_stints, get_stints

        detected = detect_and_store_stints(bridge_db, sid, {
            i: t for i, t in enumerate(
                [60.0] * 5 + [150.0] + [61.0] * 5, start=1
            )
        })
        assert len(detected) == 2

        fetched = get_stints(bridge_db, sid)
        assert len(fetched) == 2
        assert fetched[0]["stint_number"] == 1
        assert fetched[1]["stint_number"] == 2

    def test_detect_overwrites_previous(self, bridge_db):
        """Second call replaces previous stint data (idempotent)."""
        sid = _seed_session(bridge_db)
        _seed_laps(bridge_db, sid, [60.0] * 5 + [150.0] + [61.0] * 5)

        from web.repos.endurance_repo import detect_and_store_stints, get_stints

        laps = {i: t for i, t in enumerate(
            [60.0] * 5 + [150.0] + [61.0] * 5, start=1
        )}
        detect_and_store_stints(bridge_db, sid, laps)
        detect_and_store_stints(bridge_db, sid, laps)

        fetched = get_stints(bridge_db, sid)
        assert len(fetched) == 2  # Not doubled

    def test_get_stints_empty_session(self, bridge_db):
        """get_stints returns empty list for session with no stints."""
        sid = _seed_session(bridge_db)

        from web.repos.endurance_repo import get_stints

        assert get_stints(bridge_db, sid) == []
