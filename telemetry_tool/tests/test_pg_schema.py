"""Tests for the initial PostgreSQL schema migration (001).

All tests SKIP automatically when the TELEMETRY_PG_URL environment variable
is not set, so they never fail in CI environments without a PostgreSQL server.

To run locally:
    export TELEMETRY_PG_URL="postgresql://telemetry:telemetry@localhost:5432/telemetry_test"
    pytest telemetry_tool/tests/test_pg_schema.py -v
"""

import os
import uuid

import pytest

# Skip the entire module if no PostgreSQL URL is configured.
PG_URL = os.environ.get("TELEMETRY_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL, reason="TELEMETRY_PG_URL not set — skipping PostgreSQL tests"
)

# Lazy imports so the module loads even without psycopg2 / sqlalchemy installed.
sa = pytest.importorskip("sqlalchemy")


@pytest.fixture(scope="module")
def pg_engine():
    """Create a disposable test schema, run Alembic upgrade, yield engine, then tear down."""
    from alembic import command
    from alembic.config import Config

    engine = sa.create_engine(PG_URL)

    # Use a unique schema per test run to allow parallel execution.
    test_schema = f"test_{uuid.uuid4().hex[:8]}"

    with engine.connect() as conn:
        conn.execute(sa.text(f"CREATE SCHEMA {test_schema}"))
        conn.execute(sa.text(f"SET search_path TO {test_schema}"))
        conn.commit()

    # Point the Alembic config at our test database and schema.
    alembic_cfg = Config()
    alembic_cfg.set_main_option("sqlalchemy.url", PG_URL)
    alembic_cfg.set_main_option(
        "script_location",
        os.path.join(os.path.dirname(__file__), "..", "alembic"),
    )

    # Run upgrade within the test schema.
    # We override the connection to set search_path.
    test_engine = sa.create_engine(
        PG_URL, connect_args={"options": f"-csearch_path={test_schema}"}
    )

    with test_engine.connect() as conn:
        alembic_cfg.attributes["connection"] = conn

        # Monkey-patch env.py to use our connection.
        def run_upgrade(rev, context):
            return context._migration_context._migrations_fn(rev, context)

        command.upgrade(alembic_cfg, "head")
        conn.commit()

    yield test_engine

    # Tear down: drop the test schema.
    with engine.connect() as conn:
        conn.execute(sa.text(f"DROP SCHEMA {test_schema} CASCADE"))
        conn.commit()

    engine.dispose()
    test_engine.dispose()


@pytest.fixture()
def conn(pg_engine):
    """Yield a connection with the test schema on the search path."""
    with pg_engine.connect() as connection:
        yield connection


# --------------------------------------------------------------------------
# Complete list of tables expected from the migration (all 17 phases).
# --------------------------------------------------------------------------
EXPECTED_TABLES = [
    # Phase 1
    "schema_version",
    "drivers",
    "tracks",
    "sessions",
    "laps",
    "gps_traces",
    "score_details",
    "condition_phases",
    # Phase 2
    "weekends",
    "weekend_sessions",
    "track_records",
    "condition_markers",
    # Phase 3
    "driver_profiles",
    "driver_progression",
    "driving_style_features",
    # Phase 4
    "theoretical_data",
    "reference_lines",
    # Phase 5
    "session_sectors",
    # Phase 6
    "data_health",
    "session_tags",
    # Phase 7
    "corner_metrics",
    "corner_best_practices",
    "track_key_corners",
    # Phase 8
    "session_weather",
    # Phase 9
    "vehicle_setups",
    "what_if_scenarios",
    # Phase 10
    "session_annotations",
    "development_plans",
    "plan_drill_sessions",
    "driver_badges",
    "custom_dashboards",
    "export_templates",
    # Phase 11
    "stint_analysis",
    # Phase 12
    "ingestion_jobs",
    # Phase 13
    "predefined_tracks",
    "predefined_karts",
    "karts",
    "track_sectors",
    # Phase 14
    "predefined_track_coords",
    # Phase 15
    "race_configs",
    "race_drivers",
    "race_stints",
    "race_pit_stops",
    "race_windows",
    # Phase 16
    "race_messages",
    # Phase 17
    "race_neutralizations",
    "race_rivals",
    "race_rival_events",
    # Phase 18 (auth)
    "users",
    "refresh_tokens",
    # Phase 19 (OAuth)
    "oauth_connections",
]


class TestCoreTablesExist:
    """Verify all expected tables were created by the 001 migration."""

    def test_core_tables_exist(self, conn):
        """Every table in the SQLite schema v24 must exist in PostgreSQL."""
        result = conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "AND table_type = 'BASE TABLE'"
            )
        )
        actual_tables = {row[0] for row in result}

        missing = set(EXPECTED_TABLES) - actual_tables
        assert not missing, f"Missing tables: {sorted(missing)}"


class TestSessionsForeignKeys:
    """Verify sessions has FK relationships to drivers and tracks."""

    def test_sessions_foreign_keys(self, conn):
        """sessions.driver_id -> drivers and sessions.track_id -> tracks."""
        result = conn.execute(
            sa.text(
                """
                SELECT
                    tc.constraint_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.table_name = 'sessions'
                    AND tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = current_schema()
                """
            )
        )
        fks = {(row[1], row[2], row[3]) for row in result}

        assert ("driver_id", "drivers", "driver_id") in fks, (
            "sessions.driver_id must reference drivers.driver_id"
        )
        assert ("track_id", "tracks", "track_id") in fks, (
            "sessions.track_id must reference tracks.track_id"
        )


class TestLapsUniqueConstraint:
    """Verify UNIQUE(session_id, lap_number) is enforced on laps."""

    def test_laps_unique_constraint(self, conn):
        """Insert duplicate (session_id, lap_number) should raise IntegrityError."""
        # Set up prerequisite rows.
        conn.execute(
            sa.text(
                "INSERT INTO drivers (driver_name) VALUES ('Test Driver') "
                "ON CONFLICT DO NOTHING"
            )
        )
        driver_id = conn.execute(
            sa.text("SELECT driver_id FROM drivers WHERE driver_name = 'Test Driver'")
        ).scalar()

        session_id = f"test-{uuid.uuid4().hex[:8]}"
        conn.execute(
            sa.text(
                "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
                "VALUES (:sid, 'test.csv', :did, '2026-01-01')"
            ),
            {"sid": session_id, "did": driver_id},
        )

        # First lap insert should succeed.
        conn.execute(
            sa.text(
                "INSERT INTO laps (session_id, lap_number, lap_time_s) "
                "VALUES (:sid, 1, 45.0)"
            ),
            {"sid": session_id},
        )

        # Duplicate should fail with IntegrityError.
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO laps (session_id, lap_number, lap_time_s) "
                    "VALUES (:sid, 1, 44.5)"
                ),
                {"sid": session_id},
            )

        conn.rollback()


class TestJsonbColumns:
    """Verify JSON columns use JSONB type, not TEXT."""

    def test_jsonb_columns(self, conn):
        """gps_traces JSON columns must be stored as jsonb."""
        result = conn.execute(
            sa.text(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'gps_traces'
                    AND table_schema = current_schema()
                    AND column_name IN (
                        'latitudes_json', 'longitudes_json',
                        'distances_json', 'speeds_json',
                        'accel_lat_json', 'accel_long_json'
                    )
                """
            )
        )
        col_types = {row[0]: row[1] for row in result}

        for col_name in [
            "latitudes_json",
            "longitudes_json",
            "distances_json",
            "speeds_json",
        ]:
            assert col_name in col_types, f"{col_name} column missing"
            assert col_types[col_name] == "jsonb", (
                f"{col_name} should be jsonb, got {col_types[col_name]}"
            )

        # Optional columns (accel_lat_json, accel_long_json) should also be jsonb.
        for col_name in ["accel_lat_json", "accel_long_json"]:
            if col_name in col_types:
                assert col_types[col_name] == "jsonb", (
                    f"{col_name} should be jsonb, got {col_types[col_name]}"
                )


class TestCascadeDeleteSessionLaps:
    """Verify ON DELETE CASCADE from sessions to laps."""

    def test_cascade_delete_session_laps(self, conn):
        """Deleting a session should cascade-delete its laps."""
        # Set up prerequisite rows.
        conn.execute(
            sa.text(
                "INSERT INTO drivers (driver_name) VALUES ('Cascade Driver') "
                "ON CONFLICT DO NOTHING"
            )
        )
        driver_id = conn.execute(
            sa.text(
                "SELECT driver_id FROM drivers WHERE driver_name = 'Cascade Driver'"
            )
        ).scalar()

        session_id = f"cascade-{uuid.uuid4().hex[:8]}"
        conn.execute(
            sa.text(
                "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
                "VALUES (:sid, 'cascade.csv', :did, '2026-01-01')"
            ),
            {"sid": session_id, "did": driver_id},
        )

        # Insert two laps.
        conn.execute(
            sa.text(
                "INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES "
                "(:sid, 1, 45.0), (:sid, 2, 44.5)"
            ),
            {"sid": session_id},
        )

        # Verify laps exist.
        count_before = conn.execute(
            sa.text("SELECT count(*) FROM laps WHERE session_id = :sid"),
            {"sid": session_id},
        ).scalar()
        assert count_before == 2

        # Delete the session.
        conn.execute(
            sa.text("DELETE FROM sessions WHERE session_id = :sid"),
            {"sid": session_id},
        )

        # Laps should be gone.
        count_after = conn.execute(
            sa.text("SELECT count(*) FROM laps WHERE session_id = :sid"),
            {"sid": session_id},
        ).scalar()
        assert count_after == 0

        conn.rollback()
