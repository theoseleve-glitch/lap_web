"""Tests for the SQLite -> PostgreSQL data migration script.

All tests SKIP automatically when TELEMETRY_PG_URL is not set,
so they never fail in CI environments without a PostgreSQL server.

To run locally::

    export TELEMETRY_PG_URL="postgresql://telemetry:telemetry@localhost:5432/telemetry_test"
    pytest telemetry_tool/tests/test_data_migration.py -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Also add the project root above telemetry_tool for scripts import.
_REPO_ROOT = _PROJECT_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Skip the entire module if no PostgreSQL URL is configured.
PG_URL = os.environ.get("TELEMETRY_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL, reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL tests"
)

psycopg2 = pytest.importorskip("psycopg2")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_sqlite(tmp_path):
    """Create a temporary SQLite DB with schema and sample data.

    Returns the path to the SQLite file.
    """
    from db.migrate import ensure_schema

    db_path = tmp_path / "test_migrate.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    # --- Drivers ---
    conn.execute(
        "INSERT INTO drivers (driver_id, driver_name, notes) "
        "VALUES (1, 'Alice', 'Test driver A')"
    )
    conn.execute(
        "INSERT INTO drivers (driver_id, driver_name, notes) "
        "VALUES (2, 'Bob', NULL)"
    )

    # --- Tracks ---
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m, has_joker) "
        "VALUES ('t1', 'Spa Karting', 900.0, 0)"
    )
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m, has_joker) "
        "VALUES ('t2', 'Le Mans Mini', 1200.0, 1)"
    )

    # --- Sessions ---
    conn.execute(
        "INSERT INTO sessions "
        "(session_id, csv_filename, driver_id, track_id, session_type, "
        " track_state, session_date, n_laps, best_lap_time_s, "
        " mean_lap_time_s, total_score, grade, weather_json) "
        "VALUES ('s1', 'file1.csv', 1, 't1', 'practice', 'dry', "
        " '2025-06-01', 10, 55.3, 56.1, 78.5, 'B', ?)",
        (json.dumps({"temp": 22, "wind": "light"}),),
    )
    conn.execute(
        "INSERT INTO sessions "
        "(session_id, csv_filename, driver_id, track_id, session_type, "
        " track_state, session_date, n_laps, best_lap_time_s, "
        " mean_lap_time_s, total_score, grade) "
        "VALUES ('s2', 'file2.csv', 2, 't2', 'qualifying', 'wet', "
        " '2025-06-02', 8, 60.1, 61.5, 70.0, 'C')"
    )

    # --- Laps ---
    for i in range(1, 11):
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid, is_best) "
            "VALUES ('s1', ?, ?, 1, ?)",
            (i, 55.3 + i * 0.2, 1 if i == 1 else 0),
        )
    for i in range(1, 9):
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid, is_best) "
            "VALUES ('s2', ?, ?, 1, ?)",
            (i, 60.1 + i * 0.3, 1 if i == 1 else 0),
        )

    # --- Score details ---
    conn.execute(
        "INSERT INTO score_details "
        "(session_id, pace_score, pace_max, consistency_score, consistency_max, "
        " execution_score, execution_max, robustness_score, robustness_max, "
        " strengths_json, weaknesses_json) "
        "VALUES ('s1', 20.0, 25.0, 18.0, 25.0, 19.0, 25.0, 21.5, 25.0, ?, ?)",
        (json.dumps(["smooth braking"]), json.dumps(["late apex"])),
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def pg_clean():
    """Reset the public schema in the target PG database and run Alembic.

    Yields the PG URL. After the test, drops and recreates the public schema.
    """
    import psycopg2 as pg2

    conn = pg2.connect(PG_URL)
    conn.autocommit = True
    cur = conn.cursor()

    # Drop and recreate public schema to get a clean slate.
    cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
    cur.execute("CREATE SCHEMA public")
    cur.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
    cur.close()
    conn.close()

    # Run Alembic upgrade to create all tables.
    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_ini = _PROJECT_ROOT / "alembic.ini"
    alembic_cfg = AlembicConfig(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", PG_URL)
    command.upgrade(alembic_cfg, "head")

    yield PG_URL

    # Cleanup: drop and recreate public schema.
    conn = pg2.connect(PG_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
    cur.execute("CREATE SCHEMA public")
    cur.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMigrationTransfersAllRows:
    """Verify that all seeded rows are transferred from SQLite to PG."""

    def test_migration_transfers_all_rows(self, seeded_sqlite, pg_clean):
        from scripts.migrate_sqlite_to_pg import migrate

        result = migrate(seeded_sqlite, pg_clean)

        # Verify counts returned by the migrate function.
        assert result["drivers"] == 2
        assert result["tracks"] == 2
        assert result["sessions"] == 2
        assert result["laps"] == 18  # 10 + 8
        assert result["score_details"] == 1

        # Verify data actually landed in PostgreSQL.
        import psycopg2 as pg2

        conn = pg2.connect(pg_clean)
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM drivers")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT count(*) FROM tracks")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT count(*) FROM sessions")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT count(*) FROM laps")
        assert cur.fetchone()[0] == 18

        cur.execute("SELECT count(*) FROM score_details")
        assert cur.fetchone()[0] == 1

        # Verify JSONB data was transferred correctly.
        cur.execute(
            "SELECT weather_json FROM sessions WHERE session_id = 's1'"
        )
        weather = cur.fetchone()[0]
        assert weather is not None
        # psycopg2 returns JSONB as a Python dict automatically.
        if isinstance(weather, str):
            weather = json.loads(weather)
        assert weather["temp"] == 22

        # Verify BOOLEAN conversion (has_joker).
        cur.execute(
            "SELECT has_joker FROM tracks WHERE track_id = 't1'"
        )
        val = cur.fetchone()[0]
        assert val is False or val == 0  # Either Python False or int 0

        cur.execute(
            "SELECT has_joker FROM tracks WHERE track_id = 't2'"
        )
        val = cur.fetchone()[0]
        assert val is True or val == 1

        cur.close()
        conn.close()


class TestMigrationIsIdempotent:
    """Running the migration twice must not duplicate rows."""

    def test_migration_is_idempotent(self, seeded_sqlite, pg_clean):
        from scripts.migrate_sqlite_to_pg import migrate

        # First run.
        result1 = migrate(seeded_sqlite, pg_clean)

        # Second run — should not raise and counts should stay the same.
        result2 = migrate(seeded_sqlite, pg_clean)

        # The second run still reports the same number of rows attempted,
        # but ON CONFLICT DO NOTHING means PG won't have duplicates.
        import psycopg2 as pg2

        conn = pg2.connect(pg_clean)
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM drivers")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT count(*) FROM tracks")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT count(*) FROM sessions")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT count(*) FROM laps")
        assert cur.fetchone()[0] == 18

        cur.execute("SELECT count(*) FROM score_details")
        assert cur.fetchone()[0] == 1

        cur.close()
        conn.close()
