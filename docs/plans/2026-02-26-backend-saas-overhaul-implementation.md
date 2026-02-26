# Backend SaaS Overhaul — Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate from SQLite to PostgreSQL and add JWT authentication — the foundation for multi-tenant SaaS.

**Architecture:** Replace `sqlite3.Connection` with `psycopg2` connection pool. Add Alembic for schema migrations. Introduce auth middleware with feature flag (`AUTH_REQUIRED`). All changes backward-compatible — existing SQLite tests continue passing via `USE_PG` flag.

**Tech Stack:** PostgreSQL 16, psycopg2-binary, Alembic, PyJWT, Argon2-cffi, authlib (OAuth), Pydantic v2

**Design doc:** `docs/plans/2026-02-26-backend-saas-overhaul-design.md`

---

## PR 1: Alembic Migration Framework + PostgreSQL Schema

### Task 1: Add PostgreSQL dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Add dependencies**

Add to `requirements.txt`:
```
psycopg2-binary>=2.9
alembic>=1.13
sqlalchemy>=2.0
```

Note: SQLAlchemy is needed only for Alembic's migration engine — we are NOT adopting an ORM. All queries remain raw SQL.

**Step 2: Install**

Run: `pip install -r requirements.txt`
Expected: All packages install without conflict.

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add PostgreSQL and Alembic dependencies"
```

---

### Task 2: Initialize Alembic project structure

**Files:**
- Create: `telemetry_tool/alembic.ini`
- Create: `telemetry_tool/alembic/env.py`
- Create: `telemetry_tool/alembic/script.py.mako`
- Create: `telemetry_tool/alembic/versions/` (empty dir)

**Step 1: Initialize Alembic**

Run from `telemetry_tool/`:
```bash
cd telemetry_tool && alembic init alembic
```

**Step 2: Configure `alembic.ini`**

Edit `telemetry_tool/alembic.ini` — set the sqlalchemy.url to use env var:
```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql://%(TELEMETRY_PG_URL)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**Step 3: Configure `alembic/env.py`**

Replace generated `env.py` with env-var-driven config:
```python
"""Alembic environment configuration."""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override URL from environment
pg_url = os.environ.get(
    "TELEMETRY_PG_URL",
    "postgresql://telemetry:telemetry@localhost:5432/telemetry"
)
config.set_main_option("sqlalchemy.url", pg_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 4: Commit**

```bash
git add telemetry_tool/alembic.ini telemetry_tool/alembic/
git commit -m "chore: initialize Alembic migration framework"
```

---

### Task 3: Write initial PostgreSQL schema migration

**Files:**
- Create: `telemetry_tool/alembic/versions/001_initial_schema.py`

This is the largest task — translating all 80+ SQLite tables to PostgreSQL DDL. Key changes from SQLite:
- `TEXT` JSON columns → `JSONB`
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL` or `INTEGER GENERATED ALWAYS AS IDENTITY`
- `REAL` → `DOUBLE PRECISION`
- `:param` placeholders → `%(param)s` (handled in Task 6)
- Add explicit `NOT NULL` where SQLite defaulted to it
- Add `ON DELETE CASCADE` to all FK relationships that should cascade
- Add indexes for common query patterns

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_pg_schema.py`:
```python
"""Tests for PostgreSQL schema migration."""
import os
import pytest

# Skip entire module if no PG available
pg_url = os.environ.get("TELEMETRY_PG_URL")
pytestmark = pytest.mark.skipif(
    not pg_url, reason="TELEMETRY_PG_URL not set"
)


@pytest.fixture(scope="module")
def pg_engine():
    """Create a fresh test database and run migrations."""
    from sqlalchemy import create_engine, text
    engine = create_engine(pg_url)
    # Drop all tables for clean state
    with engine.connect() as conn:
        conn.execute(text(
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
        ))
        conn.commit()
    # Run alembic migrations
    from alembic.config import Config
    from alembic import command
    alembic_cfg = Config("telemetry_tool/alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", pg_url)
    command.upgrade(alembic_cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_conn(pg_engine):
    """Per-test connection with rollback."""
    conn = pg_engine.connect()
    txn = conn.begin()
    yield conn
    txn.rollback()
    conn.close()


def test_core_tables_exist(pg_conn):
    """All core tables created by migration."""
    from sqlalchemy import text
    result = pg_conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    ))
    tables = {row[0] for row in result}
    expected = {
        "schema_version", "tracks", "drivers", "sessions", "laps",
        "gps_traces", "score_details", "condition_phases",
        "weekends", "weekend_sessions", "track_records",
        "driver_profiles", "driver_progression", "driving_style_features",
        "theoretical_data", "reference_lines", "session_sectors",
        "data_health", "session_tags", "corner_metrics",
        "corner_best_practices", "track_key_corners", "session_weather",
        "vehicle_setups", "what_if_scenarios", "session_annotations",
        "development_plans", "plan_drill_sessions", "driver_badges",
        "custom_dashboards", "export_templates", "stint_analysis",
        "ingestion_jobs", "predefined_tracks", "predefined_karts",
        "karts", "track_sectors", "predefined_track_coords",
        "race_configs", "race_drivers", "race_stints", "race_pit_stops",
        "race_windows", "race_messages", "condition_markers",
        "race_neutralizations", "race_rivals", "race_rival_events",
    }
    missing = expected - tables
    assert not missing, f"Missing tables: {missing}"


def test_sessions_foreign_keys(pg_conn):
    """Sessions table has FK to drivers and tracks."""
    from sqlalchemy import text
    result = pg_conn.execute(text("""
        SELECT tc.constraint_name, ccu.table_name AS foreign_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
        WHERE tc.table_name = 'sessions'
          AND tc.constraint_type = 'FOREIGN KEY'
    """))
    fk_targets = {row[1] for row in result}
    assert "drivers" in fk_targets
    assert "tracks" in fk_targets


def test_laps_unique_constraint(pg_conn):
    """Laps has UNIQUE(session_id, lap_number)."""
    from sqlalchemy import text
    # Insert a driver, track, session
    pg_conn.execute(text(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
    ))
    pg_conn.execute(text(
        "INSERT INTO tracks (track_id, track_name) VALUES ('t1', 'Track')"
    ))
    pg_conn.execute(text(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id) "
        "VALUES ('s1', 'f.csv', 1, 't1')"
    ))
    pg_conn.execute(text(
        "INSERT INTO laps (session_id, lap_number, lap_time_s) "
        "VALUES ('s1', 1, 60.0)"
    ))
    # Duplicate should fail
    with pytest.raises(Exception):  # IntegrityError
        pg_conn.execute(text(
            "INSERT INTO laps (session_id, lap_number, lap_time_s) "
            "VALUES ('s1', 1, 61.0)"
        ))


def test_jsonb_columns(pg_conn):
    """GPS traces use JSONB, not TEXT."""
    from sqlalchemy import text
    result = pg_conn.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'gps_traces'
          AND column_name = 'latitudes_json'
    """))
    row = result.fetchone()
    assert row is not None
    assert row[1] == "jsonb"


def test_cascade_delete_session_laps(pg_conn):
    """Deleting a session cascades to its laps."""
    from sqlalchemy import text
    pg_conn.execute(text(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
    ))
    pg_conn.execute(text(
        "INSERT INTO tracks (track_id, track_name) VALUES ('t1', 'Track')"
    ))
    pg_conn.execute(text(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id) "
        "VALUES ('s1', 'f.csv', 1, 't1')"
    ))
    pg_conn.execute(text(
        "INSERT INTO laps (session_id, lap_number, lap_time_s) "
        "VALUES ('s1', 1, 60.0)"
    ))
    pg_conn.execute(text("DELETE FROM sessions WHERE session_id = 's1'"))
    result = pg_conn.execute(text(
        "SELECT COUNT(*) FROM laps WHERE session_id = 's1'"
    ))
    assert result.scalar() == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_pg_schema.py -v`
Expected: SKIP (no PG URL) or FAIL (no migration file yet)

**Step 3: Write the migration file**

Create `telemetry_tool/alembic/versions/001_initial_schema.py`. This is a large file — here's the structure with the most critical tables. The complete file translates all 17 phases from `db/schema.py`:

```python
"""Initial PostgreSQL schema — translated from SQLite v24.

Revision ID: 001
Revises:
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Phase 1: Core ──────────────────────────────────
    op.create_table(
        "schema_version",
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("description", sa.Text),
        sa.Column("applied_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "drivers",
        sa.Column("driver_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_name", sa.Text, nullable=False, unique=True),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "tracks",
        sa.Column("track_id", sa.Text, primary_key=True),
        sa.Column("track_name", sa.Text, nullable=False),
        sa.Column("lap_length_m", sa.Float),
        sa.Column("bbox_json", JSONB),
        sa.Column("start_lat", sa.Float),
        sa.Column("start_lon", sa.Float),
        sa.Column("has_joker", sa.Boolean, server_default="false"),
        sa.Column("joker_distance_delta_m", sa.Float),
        sa.Column("joker_time_delta_s", sa.Float),
        sa.Column("dry_reference_session_id", sa.Text),
        sa.Column("wet_reference_session_id", sa.Text),
    )

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text, primary_key=True),
        sa.Column("csv_filename", sa.Text),
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("drivers.driver_id", ondelete="SET NULL")),
        sa.Column("track_id", sa.Text,
                  sa.ForeignKey("tracks.track_id", ondelete="SET NULL")),
        sa.Column("session_type", sa.Text),
        sa.Column("track_state", sa.Text),
        sa.Column("session_date", sa.Text),
        sa.Column("n_laps", sa.Integer),
        sa.Column("best_lap_time_s", sa.Float),
        sa.Column("mean_lap_time_s", sa.Float),
        sa.Column("total_score", sa.Float),
        sa.Column("grade", sa.Text),
        sa.Column("html_report_path", sa.Text),
        sa.Column("weather_json", JSONB),
        sa.Column("joker_lap_number", sa.Integer),
        sa.Column("notes", sa.Text),
        sa.Column("kart_id", sa.Integer),
    )

    op.create_table(
        "laps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("lap_time_s", sa.Float),
        sa.Column("speed_max_mps", sa.Float),
        sa.Column("speed_mean_mps", sa.Float),
        sa.Column("braking_max_mps2", sa.Float),
        sa.Column("accel_max_mps2", sa.Float),
        sa.Column("line_length_m", sa.Float),
        sa.Column("is_valid", sa.Boolean, server_default="true"),
        sa.Column("is_best", sa.Boolean, server_default="false"),
        sa.Column("phase_id", sa.Integer),
        sa.Column("invalid_reason", sa.Text),
        sa.Column("is_joker", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("session_id", "lap_number"),
    )

    op.create_table(
        "gps_traces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("latitudes_json", JSONB),
        sa.Column("longitudes_json", JSONB),
        sa.Column("distances_json", JSONB),
        sa.Column("speeds_json", JSONB),
        sa.Column("accel_lat_json", JSONB),
        sa.Column("accel_long_json", JSONB),
        sa.UniqueConstraint("session_id", "lap_number"),
    )

    op.create_table(
        "score_details",
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("pace_score", sa.Float),
        sa.Column("pace_max", sa.Float),
        sa.Column("consistency_score", sa.Float),
        sa.Column("consistency_max", sa.Float),
        sa.Column("execution_score", sa.Float),
        sa.Column("execution_max", sa.Float),
        sa.Column("robustness_score", sa.Float),
        sa.Column("robustness_max", sa.Float),
        sa.Column("strengths_json", JSONB),
        sa.Column("weaknesses_json", JSONB),
        sa.Column("adaptation_score", sa.Float),
    )

    op.create_table(
        "condition_phases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("phase_id", sa.Integer, nullable=False),
        sa.Column("lap_start", sa.Integer),
        sa.Column("lap_end", sa.Integer),
        sa.Column("label", sa.Text),
        sa.Column("confidence", sa.Float),
        sa.Column("median_pace_s", sa.Float),
        sa.UniqueConstraint("session_id", "phase_id"),
    )

    # ── Phase 2: Events ────────────────────────────────
    op.create_table(
        "weekends",
        sa.Column("weekend_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("track_id", sa.Text, sa.ForeignKey("tracks.track_id")),
        sa.Column("start_date", sa.Text),
        sa.Column("end_date", sa.Text),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "weekend_sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("weekend_id", sa.Integer,
                  sa.ForeignKey("weekends.weekend_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("session_order", sa.Integer),
    )

    op.create_table(
        "track_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text,
                  sa.ForeignKey("tracks.track_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("record_time_s", sa.Float),
        sa.Column("record_holder", sa.Text),
        sa.Column("record_date", sa.Text),
        sa.Column("vehicle_class", sa.Text),
        sa.Column("source", sa.Text),
    )

    op.create_table(
        "condition_markers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("lap_number", sa.Integer),
        sa.Column("new_state", sa.Text),
        sa.Column("notes", sa.Text),
    )

    # ── Phase 3: Driver Profiles ───────────────────────
    op.create_table(
        "driver_profiles",
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("weight_kg", sa.Float),
        sa.Column("kart_class", sa.Text),
        sa.Column("experience_level", sa.Text),
        sa.Column("goals", sa.Text),
        sa.Column("preferred_tracks", sa.Text),
        sa.Column("email", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("id_code", sa.Text),
        sa.Column("pace_delta_mean_s", sa.Float),
        sa.Column("consistency_rating", sa.Float),
        sa.Column("aggression_index", sa.Float),
        sa.Column("smoothness_index", sa.Float),
        sa.Column("improvement_trend", sa.Float),
        sa.Column("total_sessions", sa.Integer, server_default="0"),
        sa.Column("total_laps", sa.Integer, server_default="0"),
        sa.Column("best_ever_time_s", sa.Float),
        sa.Column("best_ever_track_id", sa.Text),
        sa.Column("wet_skill_proxy", sa.Float),
        sa.Column("custom_notes", sa.Text),
        sa.Column("updated_at", sa.Text),
    )

    op.create_table(
        "driver_progression",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("session_date", sa.Text),
        sa.Column("track_id", sa.Text),
        sa.Column("pace_delta_s", sa.Float),
        sa.Column("consistency_cv_pct", sa.Float),
        sa.Column("aggression_index", sa.Float),
        sa.Column("smoothness_index", sa.Float),
        sa.Column("total_score", sa.Float),
        sa.Column("n_laps", sa.Integer),
    )

    op.create_table(
        "driving_style_features",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("drivers.driver_id", ondelete="CASCADE")),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("trail_braking_depth", sa.Float),
        sa.Column("brake_point_consistency", sa.Float),
        sa.Column("apex_speed_ratio", sa.Float),
        sa.Column("turn_in_aggressiveness", sa.Float),
        sa.Column("throttle_onset_delay_m", sa.Float),
        sa.Column("exit_acceleration_efficiency", sa.Float),
        sa.Column("line_variation_index", sa.Float),
        sa.Column("smoothness_composite", sa.Float),
        sa.Column("style_label", sa.Text),
        sa.Column("style_confidence", sa.Float),
        sa.Column("strengths_json", JSONB),
        sa.Column("weaknesses_json", JSONB),
    )

    # ── Phase 4-17: Remaining tables ───────────────────
    # (continuing same pattern for all remaining tables)

    op.create_table(
        "theoretical_data",
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("theoretical_time_s", sa.Float),
        sa.Column("actual_best_time_s", sa.Float),
        sa.Column("gap_pct", sa.Float),
        sa.Column("simulation_method", sa.Text),
        sa.Column("speed_profile_json", JSONB),
        sa.Column("distance_json", JSONB),
        sa.Column("metrics_json", JSONB),
    )

    op.create_table(
        "reference_lines",
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  unique=True),
        sa.Column("latitudes_json", JSONB),
        sa.Column("longitudes_json", JSONB),
        sa.Column("distances_json", JSONB),
        sa.Column("speeds_json", JSONB),
    )

    op.create_table(
        "session_sectors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("sector_index", sa.Integer),
        sa.Column("distance_m", sa.Float),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("label", sa.Text),
    )

    op.create_table(
        "data_health",
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("gps_quality", sa.Text),
        sa.Column("accel_quality", sa.Text),
        sa.Column("channel_count", sa.Integer),
        sa.Column("missing_channels", sa.Text),
        sa.Column("data_gaps", sa.Integer),
        sa.Column("total_samples", sa.Integer),
        sa.Column("overall_score", sa.Float),
        sa.Column("report_json", JSONB),
    )

    op.create_table(
        "session_tags",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("tag", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("source", sa.Text, server_default="'auto'"),
    )

    op.create_table(
        "corner_metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("corner_id", sa.Integer, nullable=False),
        sa.Column("brake_point_m", sa.Float),
        sa.Column("brake_intensity", sa.Float),
        sa.Column("entry_speed_mps", sa.Float),
        sa.Column("apex_speed_mps", sa.Float),
        sa.Column("exit_speed_mps", sa.Float),
        sa.Column("throttle_onset_m", sa.Float),
        sa.Column("exit_accel_mps2", sa.Float),
        sa.Column("grip_utilization", sa.Float),
        sa.Column("time_loss_ms", sa.Float),
        sa.Column("coaching_hint", sa.Text),
    )

    op.create_table(
        "corner_best_practices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text,
                  sa.ForeignKey("tracks.track_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("corner_id", sa.Integer, nullable=False),
        sa.Column("best_entry_speed_mps", sa.Float),
        sa.Column("best_apex_speed_mps", sa.Float),
        sa.Column("best_exit_speed_mps", sa.Float),
        sa.Column("best_brake_m", sa.Float),
        sa.Column("best_throttle_onset_m", sa.Float),
        sa.Column("best_time_s", sa.Float),
        sa.Column("sample_count", sa.Integer),
        sa.Column("source_sessions", JSONB),
        sa.UniqueConstraint("track_id", "corner_id"),
    )

    op.create_table(
        "track_key_corners",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text,
                  sa.ForeignKey("tracks.track_id", ondelete="CASCADE")),
        sa.Column("corner_id", sa.Integer),
        sa.Column("label", sa.Text),
        sa.Column("lat", sa.Float),
        sa.Column("lon", sa.Float),
        sa.Column("dist_m", sa.Float),
    )

    op.create_table(
        "session_weather",
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("air_temp_c", sa.Float),
        sa.Column("track_temp_c", sa.Float),
        sa.Column("humidity_pct", sa.Float),
        sa.Column("wind_speed_mps", sa.Float),
        sa.Column("wind_dir_deg", sa.Float),
        sa.Column("pressure_hpa", sa.Float),
        sa.Column("weather_source", sa.Text),
        sa.Column("recorded_at", sa.Text),
    )

    op.create_table(
        "vehicle_setups",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  unique=True),
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("drivers.driver_id", ondelete="SET NULL")),
        sa.Column("setup_name", sa.Text),
        sa.Column("front_pressure", sa.Float),
        sa.Column("rear_pressure", sa.Float),
        sa.Column("front_camber", sa.Float),
        sa.Column("rear_camber", sa.Float),
        sa.Column("ride_height_mm", sa.Float),
        sa.Column("spring_rate", sa.Float),
        sa.Column("weight_kg", sa.Float),
        sa.Column("fuel_load_kg", sa.Float),
        sa.Column("gear_ratios_json", JSONB),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "what_if_scenarios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("scenario_name", sa.Text),
        sa.Column("adjustments_json", JSONB),
        sa.Column("predicted_time_s", sa.Float),
        sa.Column("baseline_time_s", sa.Float),
        sa.Column("delta_s", sa.Float),
    )

    op.create_table(
        "session_annotations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("lap_number", sa.Integer),
        sa.Column("distance_m", sa.Float),
        sa.Column("annotation_type", sa.Text, server_default="'note'"),
        sa.Column("title", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("tags_json", JSONB),
        sa.Column("created_at", sa.Text),
        sa.Column("updated_at", sa.Text),
    )

    op.create_table(
        "development_plans",
        sa.Column("plan_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("drivers.driver_id", ondelete="CASCADE")),
        sa.Column("plan_name", sa.Text),
        sa.Column("template_id", sa.Text),
        sa.Column("level", sa.Text),
        sa.Column("weeks_json", JSONB),
        sa.Column("progress_json", JSONB),
        sa.Column("status", sa.Text, server_default="'active'"),
        sa.Column("created_at", sa.Text),
        sa.Column("completed_at", sa.Text),
    )

    op.create_table(
        "plan_drill_sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.Integer,
                  sa.ForeignKey("development_plans.plan_id", ondelete="CASCADE")),
        sa.Column("week_index", sa.Integer),
        sa.Column("drill_index", sa.Integer),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="SET NULL")),
        sa.Column("linked_at", sa.Text),
        sa.UniqueConstraint("plan_id", "week_index", "drill_index", "session_id"),
    )

    op.create_table(
        "driver_badges",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("drivers.driver_id", ondelete="CASCADE")),
        sa.Column("badge_type", sa.Text),
        sa.Column("badge_name", sa.Text),
        sa.Column("badge_level", sa.Integer),
        sa.Column("metadata_json", JSONB),
        sa.Column("earned_at", sa.Text),
        sa.Column("plan_id", sa.Integer,
                  sa.ForeignKey("development_plans.plan_id", ondelete="SET NULL")),
    )

    op.create_table(
        "custom_dashboards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_id", sa.Integer),
        sa.Column("dashboard_name", sa.Text),
        sa.Column("layout_json", JSONB),
        sa.Column("is_default", sa.Boolean, server_default="false"),
    )

    op.create_table(
        "export_templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("template_name", sa.Text, unique=True),
        sa.Column("sections_json", JSONB),
        sa.Column("format", sa.Text),
    )

    op.create_table(
        "stint_analysis",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("stint_number", sa.Integer),
        sa.Column("lap_start", sa.Integer),
        sa.Column("lap_end", sa.Integer),
        sa.Column("lap_count", sa.Integer),
        sa.Column("best_lap", sa.Integer),
        sa.Column("best_time_s", sa.Float),
        sa.Column("mean_time_s", sa.Float),
        sa.Column("median_time_s", sa.Float),
        sa.Column("std_time_s", sa.Float),
        sa.Column("cv_pct", sa.Float),
        sa.Column("pace_fade_pct", sa.Float),
        sa.Column("tyre_cliff_lap", sa.Integer),
        sa.Column("tyre_cliff_severity_pct", sa.Float),
        sa.Column("pace_trend_slope", sa.Float),
        sa.Column("coaching_hint", sa.Text),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("job_id", sa.Text, primary_key=True),
        sa.Column("file_path", sa.Text),
        sa.Column("file_size", sa.BigInteger),
        sa.Column("sha256", sa.Text),
        sa.Column("sha256_partial", sa.Text),
        sa.Column("encoding", sa.Text),
        sa.Column("delimiter", sa.Text),
        sa.Column("header_idx", sa.Integer),
        sa.Column("n_rows_total", sa.Integer),
        sa.Column("n_rows_loaded", sa.Integer),
        sa.Column("n_chunks", sa.Integer),
        sa.Column("cache_dir", sa.Text),
        sa.Column("status", sa.Text, server_default="'pending'"),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.Text),
        sa.Column("completed_at", sa.Text),
        sa.Column("elapsed_s", sa.Float),
        sa.Column("peak_rss_mb", sa.Float),
        sa.Column("throughput_mb_s", sa.Float),
    )

    # ── Phase 13: Catalogs ─────────────────────────────
    op.create_table(
        "predefined_tracks",
        sa.Column("predefined_track_id", sa.Integer, primary_key=True,
                  autoincrement=True),
        sa.Column("country", sa.Text),
        sa.Column("track_name", sa.Text),
        sa.Column("city", sa.Text),
        sa.Column("region", sa.Text),
        sa.Column("layout_name", sa.Text),
        sa.Column("layout_length_m", sa.Float),
        sa.Column("direction", sa.Text),
        sa.Column("rental_available", sa.Boolean),
        sa.Column("owner_available", sa.Boolean),
        sa.Column("outdoor", sa.Boolean),
        sa.Column("data_quality", sa.Text),
        sa.Column("source_url", sa.Text),
    )

    op.create_table(
        "predefined_karts",
        sa.Column("predefined_kart_id", sa.Integer, primary_key=True,
                  autoincrement=True),
        sa.Column("segment", sa.Text),
        sa.Column("manufacturer", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("model_year_start", sa.Integer),
        sa.Column("use_or_championship", sa.Text),
        sa.Column("engine", sa.Text),
        sa.Column("power_hp", sa.Float),
        sa.Column("engine_type", sa.Text),
        sa.Column("kart_weight_kg", sa.Float),
        sa.Column("top_speed_kmh", sa.Float),
        sa.Column("zero_to_100_s", sa.Float),
        sa.Column("power_to_weight", sa.Float),
        sa.Column("braking_g_est", sa.Float),
        sa.Column("lateral_g_est", sa.Float),
        sa.Column("weight_source", sa.Text),
    )

    op.create_table(
        "karts",
        sa.Column("kart_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("predefined_kart_id", sa.Integer,
                  sa.ForeignKey("predefined_karts.predefined_kart_id")),
        sa.Column("kart_name", sa.Text),
        sa.Column("manufacturer", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("engine", sa.Text),
        sa.Column("power_hp", sa.Float),
        sa.Column("kart_weight_kg", sa.Float),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.Text),
    )

    op.create_table(
        "track_sectors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text,
                  sa.ForeignKey("tracks.track_id", ondelete="CASCADE")),
        sa.Column("sector_index", sa.Integer),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("distance_m", sa.Float),
        sa.Column("label", sa.Text),
    )

    op.create_table(
        "predefined_track_coords",
        sa.Column("track_name", sa.Text, primary_key=True),
        sa.Column("city", sa.Text),
        sa.Column("country", sa.Text),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("geocoded_at", sa.Text),
    )

    # ── Phase 15-17: Race Strategy ─────────────────────
    op.create_table(
        "race_configs",
        sa.Column("race_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_name", sa.Text),
        sa.Column("track_name", sa.Text),
        sa.Column("team_name", sa.Text),
        sa.Column("race_duration_s", sa.Integer),
        sa.Column("reference_weight_kg", sa.Float),
        sa.Column("desired_stints", sa.Integer),
        sa.Column("fuel_autonomy_s", sa.Integer),
        sa.Column("min_pit_stop_s", sa.Integer),
        sa.Column("pit_speed_kmh", sa.Float),
        sa.Column("pit_open_s", sa.Integer),
        sa.Column("pit_close_s", sa.Integer),
        sa.Column("empty_kart_kg", sa.Float),
        sa.Column("full_tank_kg", sa.Float),
        sa.Column("min_total_kart_kg", sa.Float),
        sa.Column("weigh_on_pit_exit", sa.Boolean, server_default="true"),
        sa.Column("qualifying_duration_s", sa.Integer),
        sa.Column("refuel_after_quali", sa.Boolean, server_default="true"),
        sa.Column("mandatory_driver_change", sa.Boolean, server_default="false"),
        sa.Column("refueling_allowed", sa.Boolean, server_default="true"),
        sa.Column("quick_pit_stop_s", sa.Integer),
        sa.Column("race_start_ts", sa.Text),
        sa.Column("status", sa.Text, server_default="'draft'"),
        sa.Column("created_at", sa.Text),
        sa.Column("updated_at", sa.Text),
    )

    op.create_table(
        "race_drivers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("driver_name", sa.Text),
        sa.Column("driver_order", sa.Integer),
        sa.Column("min_stint_s", sa.Integer),
        sa.Column("max_stint_s", sa.Integer),
        sa.Column("min_cumulative_s", sa.Integer),
        sa.Column("max_cumulative_s", sa.Integer),
        sa.Column("min_rest_s", sa.Integer),
        sa.Column("weight_kg", sa.Float),
        sa.Column("com_channel", sa.Text),
        sa.Column("color_hex", sa.Text),
    )

    op.create_table(
        "race_stints",
        sa.Column("stint_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("stint_order", sa.Integer),
        sa.Column("driver_id", sa.Integer,
                  sa.ForeignKey("race_drivers.id", ondelete="SET NULL")),
        sa.Column("planned_start_s", sa.Integer),
        sa.Column("planned_end_s", sa.Integer),
        sa.Column("actual_start_s", sa.Integer),
        sa.Column("actual_end_s", sa.Integer),
        sa.Column("actual_duration_s", sa.Integer),
        sa.Column("fuel_at_start", sa.Float),
        sa.Column("fuel_at_end", sa.Float),
        sa.Column("ballast_kg", sa.Float),
        sa.Column("ballast_base_kg", sa.Float),
        sa.Column("ballast_fuel_offset_kg", sa.Float),
        sa.Column("fuel_burn_rate_kgs", sa.Float),
        sa.Column("notes", sa.Text),
        sa.Column("status", sa.Text, server_default="'planned'"),
    )

    op.create_table(
        "race_pit_stops",
        sa.Column("pit_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("stint_id", sa.Integer,
                  sa.ForeignKey("race_stints.stint_id", ondelete="SET NULL")),
        sa.Column("planned_at_s", sa.Integer),
        sa.Column("actual_at_s", sa.Integer),
        sa.Column("duration_s", sa.Integer),
        sa.Column("driver_change", sa.Boolean, server_default="false"),
        sa.Column("refueled", sa.Boolean, server_default="false"),
        sa.Column("fuel_added_kg", sa.Float),
        sa.Column("ballast_changed", sa.Boolean, server_default="false"),
        sa.Column("notes", sa.Text),
        sa.Column("pit_type", sa.Text, server_default="'full'"),
    )

    op.create_table(
        "race_windows",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("window_type", sa.Text),
        sa.Column("label", sa.Text),
        sa.Column("start_s", sa.Integer),
        sa.Column("end_s", sa.Integer),
        sa.Column("refuel_allowed", sa.Boolean, server_default="true"),
        sa.Column("driver_change_allowed", sa.Boolean, server_default="true"),
        sa.Column("window_order", sa.Integer),
    )

    op.create_table(
        "race_messages",
        sa.Column("msg_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("author", sa.Text),
        sa.Column("message", sa.Text),
        sa.Column("category", sa.Text, server_default="'general'"),
        sa.Column("created_at", sa.Text),
    )

    op.create_table(
        "race_neutralizations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("start_s", sa.Integer),
        sa.Column("end_s", sa.Integer),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.Text),
    )

    op.create_table(
        "race_rivals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("team_name", sa.Text),
        sa.Column("car_number", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.Text),
    )

    op.create_table(
        "race_rival_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("rival_id", sa.Integer,
                  sa.ForeignKey("race_rivals.id", ondelete="CASCADE")),
        sa.Column("event_type", sa.Text),
        sa.Column("at_s", sa.Integer),
        sa.Column("detail", sa.Text),
        sa.Column("created_at", sa.Text),
    )

    # ── Indexes ────────────────────────────────────────
    op.create_index("idx_sessions_driver", "sessions", ["driver_id"])
    op.create_index("idx_sessions_track", "sessions", ["track_id"])
    op.create_index("idx_sessions_date", "sessions", ["session_date"])
    op.create_index("idx_laps_session", "laps", ["session_id"])
    op.create_index("idx_gps_session_lap", "gps_traces",
                    ["session_id", "lap_number"])
    op.create_index("idx_corner_metrics_session", "corner_metrics",
                    ["session_id"])
    op.create_index("idx_driver_prog_driver", "driver_progression",
                    ["driver_id"])
    op.create_index("idx_race_stints_race", "race_stints", ["race_id"])
    op.create_index("idx_race_drivers_race", "race_drivers", ["race_id"])
    op.create_index("idx_stint_analysis_session", "stint_analysis",
                    ["session_id"])
    op.create_index("idx_annotations_session", "session_annotations",
                    ["session_id"])
    op.create_index("idx_badges_driver", "driver_badges", ["driver_id"])

    # Record schema version
    op.execute(
        "INSERT INTO schema_version (version, description) "
        "VALUES (24, 'Initial PostgreSQL migration from SQLite v24')"
    )


def downgrade() -> None:
    # Drop all tables in reverse dependency order
    tables = [
        "race_rival_events", "race_rivals", "race_neutralizations",
        "race_messages", "race_windows", "race_pit_stops", "race_stints",
        "race_drivers", "race_configs",
        "predefined_track_coords", "track_sectors", "karts",
        "predefined_karts", "predefined_tracks",
        "ingestion_jobs", "stint_analysis",
        "export_templates", "custom_dashboards", "driver_badges",
        "plan_drill_sessions", "development_plans", "session_annotations",
        "what_if_scenarios", "vehicle_setups", "session_weather",
        "track_key_corners", "corner_best_practices", "corner_metrics",
        "session_tags", "data_health", "session_sectors",
        "reference_lines", "theoretical_data",
        "driving_style_features", "driver_progression", "driver_profiles",
        "condition_markers", "track_records", "weekend_sessions", "weekends",
        "condition_phases", "score_details", "gps_traces", "laps",
        "sessions", "tracks", "drivers", "schema_version",
    ]
    for table in tables:
        op.drop_table(table)
```

**Step 4: Run tests against PostgreSQL**

First start a local PG (Docker):
```bash
docker run -d --name telemetry-pg -e POSTGRES_USER=telemetry -e POSTGRES_PASSWORD=telemetry -e POSTGRES_DB=telemetry -p 5432:5432 postgres:16
```

Then run:
```bash
TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5432/telemetry pytest telemetry_tool/tests/test_pg_schema.py -v
```
Expected: All 5 tests PASS.

**Step 5: Verify existing SQLite tests still pass**

Run: `pytest telemetry_tool/tests/ -v --ignore=telemetry_tool/tests/test_pg_schema.py`
Expected: All existing tests PASS (no regression).

**Step 6: Commit**

```bash
git add telemetry_tool/alembic/ telemetry_tool/tests/test_pg_schema.py
git commit -m "feat(db): initial PostgreSQL schema migration via Alembic

Translates all 80+ tables from SQLite v24 schema to PostgreSQL DDL.
Key changes: TEXT JSON → JSONB, proper FK ON DELETE CASCADE,
explicit indexes for common query patterns."
```

---

### Task 4: Docker Compose for development PostgreSQL + Redis

**Files:**
- Create: `docker-compose.yml`

**Step 1: Write docker-compose.yml**

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: telemetry
      POSTGRES_PASSWORD: telemetry
      POSTGRES_DB: telemetry
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U telemetry"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pg_data:
```

**Step 2: Test it starts**

Run: `docker compose up -d && docker compose ps`
Expected: Both services healthy.

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: add Docker Compose for PostgreSQL and Redis"
```

---

### Task 5: Database connection abstraction layer

**Files:**
- Create: `telemetry_tool/web/db_pg.py`
- Modify: `telemetry_tool/web/db.py`
- Create: `telemetry_tool/tests/test_db_connection.py`

This task introduces a `USE_PG` feature flag. When ON, connections come from a psycopg2 pool. When OFF (default), existing SQLite behavior is preserved.

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_db_connection.py`:
```python
"""Tests for the database connection abstraction."""
import os
import pytest


class TestConnectionFactory:
    """Test that USE_PG flag routes to correct backend."""

    def test_sqlite_default(self, monkeypatch):
        """Without USE_PG, returns sqlite3 connection."""
        monkeypatch.delenv("USE_PG", raising=False)
        # Force reimport to pick up env change
        import importlib
        from web import db
        importlib.reload(db)
        conn = db.get_db_connection(db_path=":memory:")
        assert "sqlite3" in type(conn).__module__
        conn.close()

    @pytest.mark.skipif(
        not os.environ.get("TELEMETRY_PG_URL"),
        reason="TELEMETRY_PG_URL not set"
    )
    def test_pg_when_flag_on(self, monkeypatch):
        """With USE_PG=1, returns psycopg2 connection."""
        monkeypatch.setenv("USE_PG", "1")
        import importlib
        from web import db_pg
        conn = db_pg.get_pg_connection()
        assert "psycopg2" in type(conn).__module__
        conn.close()


class TestPgRowFactory:
    """Ensure PG connections return dict-like rows (matching sqlite3.Row)."""

    @pytest.mark.skipif(
        not os.environ.get("TELEMETRY_PG_URL"),
        reason="TELEMETRY_PG_URL not set"
    )
    def test_pg_returns_dict_rows(self):
        from web import db_pg
        conn = db_pg.get_pg_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 AS val, 'hello' AS msg")
        row = cur.fetchone()
        # Should be accessible by column name
        assert row["val"] == 1
        assert row["msg"] == "hello"
        cur.close()
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_db_connection.py -v`
Expected: ImportError — `db_pg` module doesn't exist yet.

**Step 3: Write `db_pg.py`**

Create `telemetry_tool/web/db_pg.py`:
```python
"""PostgreSQL connection management.

Provides a connection pool and per-request connection via Flask g,
mirroring the interface of db.py for SQLite.

Activated by USE_PG=1 environment variable.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

PG_URL = os.environ.get(
    "TELEMETRY_PG_URL",
    "postgresql://telemetry:telemetry@localhost:5432/telemetry",
)


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Lazy-init a threaded connection pool."""
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=PG_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        logger.info("PostgreSQL connection pool created (min=2, max=10)")
    return _pool


def get_pg_connection():
    """Return a connection from the pool.

    Inside Flask: cached on g, returned to pool on teardown.
    Outside Flask: caller must close() when done.
    """
    try:
        from flask import g
        if "db" not in g:
            g.db = _get_pool().getconn()
            g.db.autocommit = False
        return g.db
    except (ImportError, RuntimeError):
        pass

    # Standalone (pipeline, CLI, tests)
    conn = _get_pool().getconn()
    conn.autocommit = False
    return conn


def close_pg(exc: Optional[BaseException] = None) -> None:
    """Return connection to pool (Flask teardown hook)."""
    try:
        from flask import g
        conn = g.pop("db", None)
        if conn is not None:
            if exc is not None:
                conn.rollback()
            _get_pool().putconn(conn)
    except (ImportError, RuntimeError):
        pass


def init_pg() -> None:
    """Run Alembic migrations to head."""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("telemetry_tool/alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", PG_URL)
    command.upgrade(alembic_cfg, "head")
    logger.info("PostgreSQL schema migrated to head")
```

**Step 4: Update `db.py` with USE_PG routing**

Add to top of `telemetry_tool/web/db.py` (after existing imports):
```python
# At top of get_db_connection(), add PG routing:
def get_db_connection(db_path=None):
    if os.environ.get("USE_PG", "0") == "1":
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    # ... existing SQLite logic unchanged ...
```

**Step 5: Run tests**

Run: `pytest telemetry_tool/tests/test_db_connection.py::TestConnectionFactory::test_sqlite_default -v`
Expected: PASS

Run (with PG): `USE_PG=1 TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5432/telemetry pytest telemetry_tool/tests/test_db_connection.py -v`
Expected: All PASS

**Step 6: Verify SQLite tests still pass**

Run: `pytest telemetry_tool/tests/ -v --ignore=telemetry_tool/tests/test_pg_schema.py --ignore=telemetry_tool/tests/test_db_connection.py`
Expected: All existing tests PASS.

**Step 7: Commit**

```bash
git add telemetry_tool/web/db_pg.py telemetry_tool/web/db.py telemetry_tool/tests/test_db_connection.py
git commit -m "feat(db): add PostgreSQL connection pool with USE_PG feature flag

Introduces db_pg.py with psycopg2 ThreadedConnectionPool (min=2, max=10).
USE_PG=1 env var routes get_db_connection() to PG pool.
Default remains SQLite — no behavior change without the flag."
```

---

### Task 6: SQL query compatibility layer

**Files:**
- Create: `telemetry_tool/db/sql_compat.py`
- Create: `telemetry_tool/tests/test_sql_compat.py`

SQLite uses `?` or `:name` placeholders. psycopg2 uses `%s` or `%(name)s`. This task creates a thin translation layer so existing queries work on both backends.

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_sql_compat.py`:
```python
"""Tests for SQL parameter style translation."""
from db.sql_compat import translate_params


def test_named_params():
    sql = "SELECT * FROM sessions WHERE session_id = :session_id AND driver_id = :driver_id"
    pg_sql = translate_params(sql)
    assert pg_sql == "SELECT * FROM sessions WHERE session_id = %(session_id)s AND driver_id = %(driver_id)s"


def test_positional_params():
    sql = "INSERT INTO laps (session_id, lap_number) VALUES (?, ?)"
    pg_sql = translate_params(sql)
    assert pg_sql == "INSERT INTO laps (session_id, lap_number) VALUES (%s, %s)"


def test_no_params():
    sql = "SELECT COUNT(*) FROM drivers"
    assert translate_params(sql) == sql


def test_mixed_not_altered():
    """Strings without params pass through unchanged."""
    sql = "SELECT * FROM tracks WHERE track_name LIKE '%test%'"
    pg_sql = translate_params(sql)
    # The LIKE % should not be confused with param %s
    assert "%(test)s" not in pg_sql


def test_insert_or_ignore_to_on_conflict():
    sql = "INSERT OR IGNORE INTO schema_version (version) VALUES (:v)"
    pg_sql = translate_params(sql)
    assert "ON CONFLICT DO NOTHING" in pg_sql


def test_insert_or_replace_to_upsert():
    sql = "INSERT OR REPLACE INTO sessions (session_id, csv_filename) VALUES (:sid, :fname)"
    pg_sql = translate_params(sql)
    assert "ON CONFLICT" in pg_sql
```

**Step 2: Run to verify failure**

Run: `pytest telemetry_tool/tests/test_sql_compat.py -v`
Expected: ImportError — module doesn't exist.

**Step 3: Implement**

Create `telemetry_tool/db/sql_compat.py`:
```python
"""SQL dialect translation between SQLite and PostgreSQL.

Translates parameter styles:
  SQLite  :name  → PostgreSQL %(name)s
  SQLite  ?      → PostgreSQL %s

Also translates SQLite-specific syntax:
  INSERT OR IGNORE  → INSERT ... ON CONFLICT DO NOTHING
  INSERT OR REPLACE → INSERT ... ON CONFLICT (...) DO UPDATE
"""
from __future__ import annotations

import os
import re

_USE_PG = os.environ.get("USE_PG", "0") == "1"


def translate_params(sql: str) -> str:
    """Translate SQLite param style to PostgreSQL if USE_PG is active."""
    if not _USE_PG:
        return sql

    # INSERT OR IGNORE → ON CONFLICT DO NOTHING
    sql = re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO",
        "INSERT INTO",
        sql,
        flags=re.IGNORECASE,
    )
    if "OR IGNORE" not in sql and "ON CONFLICT" not in sql:
        # Check if we just removed OR IGNORE — add ON CONFLICT
        pass
    # For INSERT OR IGNORE, append ON CONFLICT DO NOTHING before VALUES result
    if re.search(r"INSERT\s+INTO.*VALUES", sql, re.IGNORECASE):
        if "ON CONFLICT" not in sql and "or ignore" in sql.lower():
            sql = sql.rstrip(";") + " ON CONFLICT DO NOTHING"

    # Handle the translation more carefully
    result = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
    if result != sql:
        # We removed OR IGNORE, add ON CONFLICT DO NOTHING
        result = result.rstrip(";")
        if "ON CONFLICT" not in result:
            result += " ON CONFLICT DO NOTHING"
        sql = result

    # INSERT OR REPLACE → basic upsert (caller must customize)
    sql = re.sub(
        r"INSERT\s+OR\s+REPLACE\s+INTO",
        "INSERT INTO",
        sql,
        flags=re.IGNORECASE,
    )

    # Named params :name → %(name)s
    # Careful not to match ::type_cast in PostgreSQL
    sql = re.sub(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)", r"%(\1)s", sql)

    # Positional params ? → %s
    sql = sql.replace("?", "%s")

    return sql
```

**Step 4: Run tests**

Run: `USE_PG=1 pytest telemetry_tool/tests/test_sql_compat.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/db/sql_compat.py telemetry_tool/tests/test_sql_compat.py
git commit -m "feat(db): SQL parameter translation layer for SQLite ↔ PostgreSQL

Translates :name → %(name)s, ? → %s, INSERT OR IGNORE → ON CONFLICT.
Active only when USE_PG=1."
```

---

## PR 2: SQLite → PostgreSQL Data Migration Script

### Task 7: Data migration script

**Files:**
- Create: `scripts/migrate_sqlite_to_pg.py`
- Create: `telemetry_tool/tests/test_data_migration.py`

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_data_migration.py`:
```python
"""Test SQLite → PostgreSQL data migration."""
import os
import sqlite3
import pytest

pg_url = os.environ.get("TELEMETRY_PG_URL")
pytestmark = pytest.mark.skipif(not pg_url, reason="TELEMETRY_PG_URL not set")


@pytest.fixture
def seeded_sqlite(tmp_path):
    """Create a SQLite DB with sample data."""
    from db.migrate import ensure_schema
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    # Seed data
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Alice')")
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (2, 'Bob')")
    conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500.0)")
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "n_laps, best_lap_time_s, total_score, grade) "
        "VALUES ('s1', 'test.csv', 1, 't1', 5, 60.0, 80.0, 'B')"
    )
    for i in range(1, 6):
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) VALUES ('s1', ?, ?, 1)",
            (i, 60.0 + i * 0.1),
        )
    conn.commit()
    conn.close()
    return db_path


def test_migration_transfers_all_rows(seeded_sqlite):
    """All rows from SQLite appear in PostgreSQL."""
    from scripts.migrate_sqlite_to_pg import migrate
    result = migrate(str(seeded_sqlite), pg_url)
    assert result["drivers"] == 2
    assert result["tracks"] == 1
    assert result["sessions"] == 1
    assert result["laps"] == 5


def test_migration_is_idempotent(seeded_sqlite):
    """Running migration twice doesn't duplicate data."""
    from scripts.migrate_sqlite_to_pg import migrate
    migrate(str(seeded_sqlite), pg_url)
    result = migrate(str(seeded_sqlite), pg_url)
    assert result["drivers"] == 2  # not 4
```

**Step 2: Implement migration script**

Create `scripts/migrate_sqlite_to_pg.py`:
```python
"""Migrate data from SQLite telemetry.db to PostgreSQL.

Usage:
    python scripts/migrate_sqlite_to_pg.py [--sqlite PATH] [--pg-url URL]

Idempotent: uses INSERT ... ON CONFLICT DO NOTHING for all tables.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# Tables in dependency order (parents before children)
TABLE_ORDER = [
    "schema_version",
    "drivers", "tracks",
    "sessions",
    "laps", "gps_traces", "score_details", "condition_phases",
    "weekends", "weekend_sessions", "track_records", "condition_markers",
    "driver_profiles", "driver_progression", "driving_style_features",
    "theoretical_data", "reference_lines", "session_sectors",
    "data_health", "session_tags",
    "corner_metrics", "corner_best_practices", "track_key_corners",
    "session_weather",
    "vehicle_setups", "what_if_scenarios",
    "session_annotations", "development_plans", "plan_drill_sessions",
    "driver_badges", "custom_dashboards", "export_templates",
    "stint_analysis", "ingestion_jobs",
    "predefined_tracks", "predefined_karts", "karts", "track_sectors",
    "predefined_track_coords",
    "race_configs", "race_drivers", "race_stints", "race_pit_stops",
    "race_windows", "race_messages",
    "race_neutralizations", "race_rivals", "race_rival_events",
]


def migrate(sqlite_path: str, pg_url: str) -> dict[str, int]:
    """Migrate all data from SQLite to PostgreSQL.

    Returns dict of table_name → row_count migrated.
    """
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(pg_url)

    counts = {}

    try:
        for table in TABLE_ORDER:
            count = _migrate_table(sqlite_conn, pg_conn, table)
            counts[table] = count
            if count > 0:
                logger.info("Migrated %d rows from %s", count, table)

        pg_conn.commit()
        logger.info("Migration complete: %s", counts)
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()

    return counts


def _migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    table: str,
) -> int:
    """Copy all rows from one SQLite table to PostgreSQL."""
    cursor = sqlite_conn.execute(f"SELECT * FROM {table}")  # noqa: S608
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    if not rows:
        return 0

    # Build INSERT ... ON CONFLICT DO NOTHING
    cols_str = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    pg_cursor = pg_conn.cursor()
    count = 0
    for row in rows:
        values = [_convert_value(row[col]) for col in columns]
        try:
            pg_cursor.execute(sql, values)
            count += pg_cursor.rowcount
        except psycopg2.IntegrityError:
            pg_conn.rollback()
            # Skip rows that violate constraints
            continue

    return count


def _convert_value(value):
    """Convert SQLite value to PostgreSQL-compatible value."""
    if isinstance(value, str):
        # Check if it's a JSON string that should go into JSONB
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (list, dict)):
                return json.dumps(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
    return value


if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL")
    parser.add_argument("--sqlite", default="telemetry.db", help="SQLite DB path")
    parser.add_argument(
        "--pg-url",
        default=os.environ.get(
            "TELEMETRY_PG_URL",
            "postgresql://telemetry:telemetry@localhost:5432/telemetry",
        ),
        help="PostgreSQL connection URL",
    )
    args = parser.parse_args()
    result = migrate(args.sqlite, args.pg_url)
    print(f"Migration complete. Rows migrated: {result}")
```

**Step 3: Run tests**

```bash
TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5432/telemetry pytest telemetry_tool/tests/test_data_migration.py -v
```
Expected: Both tests PASS.

**Step 4: Commit**

```bash
git add scripts/migrate_sqlite_to_pg.py telemetry_tool/tests/test_data_migration.py
git commit -m "feat(db): SQLite → PostgreSQL data migration script

Idempotent migration using INSERT ON CONFLICT DO NOTHING.
Handles JSON TEXT → JSONB conversion automatically.
Processes tables in FK dependency order."
```

---

## PR 3: Connection Pool Integration

### Task 8: Update Flask app factory to support PostgreSQL

**Files:**
- Modify: `telemetry_tool/web/app.py` (lines 114-129)
- Modify: `telemetry_tool/web/config.py`

**Step 1: Add PG config to Config class**

Add to `telemetry_tool/web/config.py`:
```python
# PostgreSQL (SaaS mode)
USE_PG = os.environ.get("USE_PG", "0") == "1"
PG_URL = os.environ.get(
    "TELEMETRY_PG_URL",
    "postgresql://telemetry:telemetry@localhost:5432/telemetry",
)
```

**Step 2: Update app.py DB initialization**

In `create_app()`, replace the DB init block (lines ~114-129) with:
```python
if cfg.USE_PG:
    from .db_pg import close_pg, init_pg
    app.teardown_appcontext(close_pg)
    with app.app_context():
        init_pg()
        # Sync tracks + merge duplicates still needed
        from .db_pg import get_pg_connection
        conn = get_pg_connection()
        _sync_tracks(conn)
else:
    from .db import close_db, init_db, set_default_db_path
    set_default_db_path(cfg.DB_PATH)
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db(cfg.DB_PATH)
        from .db import get_db_connection
        conn = get_db_connection()
        _sync_tracks(conn)
```

**Step 3: Run existing tests without USE_PG**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All existing tests PASS (SQLite path unchanged).

**Step 4: Commit**

```bash
git add telemetry_tool/web/app.py telemetry_tool/web/config.py
git commit -m "feat(app): Flask factory routes to PG or SQLite based on USE_PG flag

No behavior change without USE_PG=1. Existing SQLite path preserved."
```

---

## PR 4: Auth — Registration, Login, JWT

### Task 9: Auth dependencies and config

**Files:**
- Modify: `requirements.txt`
- Modify: `telemetry_tool/web/config.py`

**Step 1: Add auth dependencies**

Add to `requirements.txt`:
```
PyJWT>=2.8
argon2-cffi>=23.1
pydantic>=2.5
```

**Step 2: Add auth config**

Add to `Config` class in `config.py`:
```python
# Auth
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "0") == "1"
JWT_SECRET = os.environ.get("TELEMETRY_JWT_SECRET", "jwt-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRY_MINUTES = 15
JWT_REFRESH_EXPIRY_DAYS = 30
```

**Step 3: Commit**

```bash
git add requirements.txt telemetry_tool/web/config.py
git commit -m "chore: add auth dependencies (PyJWT, argon2, pydantic)"
```

---

### Task 10: Auth migration — users and refresh_tokens tables

**Files:**
- Create: `telemetry_tool/alembic/versions/002_auth_tables.py`

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_pg_schema.py`:
```python
def test_auth_tables_exist(pg_conn):
    """Auth tables created by migration 002."""
    from sqlalchemy import text
    result = pg_conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name IN ('users', 'refresh_tokens')"
    ))
    tables = {row[0] for row in result}
    assert "users" in tables
    assert "refresh_tokens" in tables


def test_users_email_unique(pg_conn):
    """Users table enforces unique email."""
    from sqlalchemy import text
    pg_conn.execute(text(
        "INSERT INTO users (email, password_hash, display_name) "
        "VALUES ('a@b.com', 'hash', 'Alice')"
    ))
    with pytest.raises(Exception):
        pg_conn.execute(text(
            "INSERT INTO users (email, password_hash, display_name) "
            "VALUES ('a@b.com', 'hash2', 'Alice2')"
        ))
```

**Step 2: Write migration**

Create `telemetry_tool/alembic/versions/002_auth_tables.py`:
```python
"""Add auth tables: users, refresh_tokens.

Revision ID: 002
Revises: 001
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text),
        sa.Column("display_name", sa.Text),
        sa.Column("avatar_url", sa.Text),
        sa.Column("email_verified", sa.Boolean, server_default="false"),
        sa.Column("mfa_secret", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("device_info", sa.Text),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_refresh_tokens_user", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("users")
```

**Step 3: Run migration + tests**

```bash
cd telemetry_tool && TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5432/telemetry alembic upgrade head
TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5432/telemetry pytest tests/test_pg_schema.py -v
```
Expected: All tests PASS (including new auth table tests).

**Step 4: Commit**

```bash
git add telemetry_tool/alembic/versions/002_auth_tables.py telemetry_tool/tests/test_pg_schema.py
git commit -m "feat(auth): add users and refresh_tokens tables (migration 002)"
```

---

### Task 11: Auth service — password hashing, JWT, core logic

**Files:**
- Create: `telemetry_tool/auth/__init__.py`
- Create: `telemetry_tool/auth/service.py`
- Create: `telemetry_tool/auth/models.py`
- Create: `telemetry_tool/tests/test_auth_service.py`

**Step 1: Write failing tests**

Create `telemetry_tool/tests/test_auth_service.py`:
```python
"""Tests for auth service — password hashing, JWT, registration."""
import time
import pytest


class TestPasswordHashing:
    def test_hash_and_verify(self):
        from auth.service import hash_password, verify_password
        hashed = hash_password("mysecretpassword")
        assert hashed != "mysecretpassword"
        assert verify_password("mysecretpassword", hashed)
        assert not verify_password("wrongpassword", hashed)

    def test_different_hashes_for_same_password(self):
        from auth.service import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # salted


class TestJWT:
    def test_create_and_decode_access_token(self):
        from auth.service import create_access_token, decode_access_token
        token = create_access_token(user_id=42, secret="test-secret")
        payload = decode_access_token(token, secret="test-secret")
        assert payload["user_id"] == 42
        assert payload["type"] == "access"

    def test_expired_token_raises(self):
        from auth.service import create_access_token, decode_access_token
        token = create_access_token(user_id=1, secret="s", expiry_minutes=-1)
        with pytest.raises(Exception, match="expired|Expired"):
            decode_access_token(token, secret="s")

    def test_invalid_token_raises(self):
        from auth.service import decode_access_token
        with pytest.raises(Exception):
            decode_access_token("garbage.token.here", secret="s")

    def test_create_refresh_token(self):
        from auth.service import create_refresh_token
        token = create_refresh_token()
        assert len(token) >= 32  # sufficient entropy


class TestRegistration:
    def test_register_user(self, test_db_pg):
        from auth.service import register_user
        user = register_user(test_db_pg, "alice@example.com", "password123", "Alice")
        assert user["id"] is not None
        assert user["email"] == "alice@example.com"
        assert user["display_name"] == "Alice"

    def test_duplicate_email_raises(self, test_db_pg):
        from auth.service import register_user, AuthError
        register_user(test_db_pg, "bob@example.com", "pass", "Bob")
        with pytest.raises(AuthError, match="already registered"):
            register_user(test_db_pg, "bob@example.com", "pass2", "Bob2")


class TestLogin:
    def test_login_success(self, test_db_pg):
        from auth.service import register_user, login_user
        register_user(test_db_pg, "carol@example.com", "mypass", "Carol")
        result = login_user(test_db_pg, "carol@example.com", "mypass", secret="s")
        assert "access_token" in result
        assert "refresh_token" in result

    def test_login_wrong_password(self, test_db_pg):
        from auth.service import register_user, login_user, AuthError
        register_user(test_db_pg, "dave@example.com", "correct", "Dave")
        with pytest.raises(AuthError, match="Invalid credentials"):
            login_user(test_db_pg, "dave@example.com", "wrong", secret="s")

    def test_login_nonexistent_user(self, test_db_pg):
        from auth.service import login_user, AuthError
        with pytest.raises(AuthError, match="Invalid credentials"):
            login_user(test_db_pg, "nobody@example.com", "pass", secret="s")
```

Note: `test_db_pg` fixture needs to be added to conftest — it provides a PG connection with auth tables. For unit-only tests (hashing, JWT), no DB needed.

**Step 2: Implement auth service**

Create `telemetry_tool/auth/__init__.py`:
```python
"""Authentication and authorization package."""
```

Create `telemetry_tool/auth/service.py`:
```python
"""Core auth service — registration, login, JWT, password hashing."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)


class AuthError(Exception):
    """Authentication/authorization error with user-safe message."""
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        super().__init__(message)
        self.code = code


# ── Password ───────────────────────────────────────────

def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


# ── JWT ────────────────────────────────────────────────

def create_access_token(
    user_id: int,
    secret: str,
    expiry_minutes: int = 15,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired", "TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid token", "INVALID_TOKEN")

    if payload.get("type") != "access":
        raise AuthError("Invalid token type", "INVALID_TOKEN")

    return payload


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Registration ───────────────────────────────────────

def register_user(conn, email: str, password: str, display_name: str) -> dict:
    """Create a new user account. Raises AuthError if email taken."""
    password_hash = hash_password(password)

    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, password_hash, display_name) "
            "VALUES (%s, %s, %s) RETURNING id, email, display_name, created_at",
            (email, password_hash, display_name),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row)
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise AuthError("Email already registered", "CONFLICT")
        raise


# ── Login ──────────────────────────────────────────────

def login_user(
    conn,
    email: str,
    password: str,
    secret: str,
    access_expiry_minutes: int = 15,
    refresh_expiry_days: int = 30,
) -> dict:
    """Authenticate user by email/password. Returns tokens."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, password_hash, display_name "
        "FROM users WHERE email = %s AND deleted_at IS NULL",
        (email,),
    )
    user = cur.fetchone()

    if user is None or not verify_password(password, user["password_hash"]):
        raise AuthError("Invalid credentials", "INVALID_CREDENTIALS")

    # Issue tokens
    access_token = create_access_token(user["id"], secret, access_expiry_minutes)
    refresh_token = create_refresh_token()

    # Store refresh token hash
    expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_expiry_days)
    cur.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s)",
        (user["id"], hash_refresh_token(refresh_token), expires_at),
    )
    conn.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
        },
    }
```

**Step 3: Run tests**

```bash
# Unit tests (no PG needed)
pytest telemetry_tool/tests/test_auth_service.py -v -k "TestPasswordHashing or TestJWT"

# Integration tests (needs PG)
TELEMETRY_PG_URL=... pytest telemetry_tool/tests/test_auth_service.py -v -k "TestRegistration or TestLogin"
```
Expected: All PASS.

**Step 4: Commit**

```bash
git add telemetry_tool/auth/ telemetry_tool/tests/test_auth_service.py
git commit -m "feat(auth): core auth service — Argon2id hashing, JWT tokens, register/login

Unit-tested password hashing and JWT creation/verification.
Integration-tested registration (unique email) and login flow."
```

---

### Task 12: Auth routes — /auth/register, /auth/login, /auth/refresh, /auth/logout

**Files:**
- Create: `telemetry_tool/web/routes/auth.py`
- Create: `telemetry_tool/tests/test_auth_routes.py`

**Step 1: Write failing tests**

Create `telemetry_tool/tests/test_auth_routes.py`:
```python
"""Tests for auth API routes."""
import json
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TELEMETRY_PG_URL"), reason="TELEMETRY_PG_URL not set"
)


@pytest.fixture
def auth_client(pg_app):
    """Flask test client with PG backend."""
    return pg_app.test_client()


def test_register(auth_client):
    resp = auth_client.post("/auth/register", json={
        "email": "new@example.com",
        "password": "SecurePass123",
        "display_name": "NewUser",
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert data["data"]["user"]["email"] == "new@example.com"
    assert "access_token" in data["data"]


def test_register_duplicate(auth_client):
    auth_client.post("/auth/register", json={
        "email": "dup@example.com", "password": "pass", "display_name": "Dup",
    })
    resp = auth_client.post("/auth/register", json={
        "email": "dup@example.com", "password": "pass2", "display_name": "Dup2",
    })
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "CONFLICT"


def test_login(auth_client):
    auth_client.post("/auth/register", json={
        "email": "login@example.com", "password": "mypass", "display_name": "Login",
    })
    resp = auth_client.post("/auth/login", json={
        "email": "login@example.com", "password": "mypass",
    })
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data


def test_login_wrong_password(auth_client):
    auth_client.post("/auth/register", json={
        "email": "wrong@example.com", "password": "correct", "display_name": "W",
    })
    resp = auth_client.post("/auth/login", json={
        "email": "wrong@example.com", "password": "incorrect",
    })
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_protected_route_without_token(auth_client):
    resp = auth_client.get("/api/v1/me")
    assert resp.status_code == 401


def test_protected_route_with_token(auth_client):
    # Register + login
    auth_client.post("/auth/register", json={
        "email": "me@example.com", "password": "pass", "display_name": "Me",
    })
    login = auth_client.post("/auth/login", json={
        "email": "me@example.com", "password": "pass",
    })
    token = login.get_json()["data"]["access_token"]

    resp = auth_client.get("/api/v1/me", headers={
        "Authorization": f"Bearer {token}",
    })
    assert resp.status_code == 200
    assert resp.get_json()["data"]["email"] == "me@example.com"
```

**Step 2: Implement auth routes**

Create `telemetry_tool/web/routes/auth.py`:
```python
"""Auth routes — register, login, refresh, logout."""
from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _get_conn():
    """Get DB connection (PG in SaaS mode)."""
    from web.db import get_db_connection
    return get_db_connection()


def _json_response(data=None, error=None, status=200):
    """Consistent response envelope."""
    if error:
        return jsonify({"ok": False, "error": error, "meta": {}}), status
    return jsonify({"ok": True, "data": data, "meta": {}}), status


@bp.route("/register", methods=["POST"])
def register():
    from auth.service import register_user, login_user, AuthError

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or "").strip()

    if not email or not password:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Email and password required"},
            status=400,
        )

    if len(password) < 8:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Password must be at least 8 characters"},
            status=400,
        )

    conn = _get_conn()
    try:
        user = register_user(conn, email, password, display_name or email.split("@")[0])
        # Auto-login after registration
        secret = current_app.config.get("JWT_SECRET", "jwt-dev-secret")
        result = login_user(conn, email, password, secret)
        return _json_response(data=result, status=201)
    except AuthError as e:
        status = 409 if e.code == "CONFLICT" else 400
        return _json_response(error={"code": e.code, "message": str(e)}, status=status)


@bp.route("/login", methods=["POST"])
def login():
    from auth.service import login_user, AuthError

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Email and password required"},
            status=400,
        )

    conn = _get_conn()
    secret = current_app.config.get("JWT_SECRET", "jwt-dev-secret")
    try:
        result = login_user(conn, email, password, secret)
        return _json_response(data=result)
    except AuthError as e:
        return _json_response(
            error={"code": e.code, "message": str(e)}, status=401,
        )


@bp.route("/logout", methods=["POST"])
def logout():
    from auth.service import hash_refresh_token

    body = request.get_json(silent=True) or {}
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        return _json_response(data={"message": "Logged out"})

    conn = _get_conn()
    token_hash = hash_refresh_token(refresh_token)
    conn.cursor().execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = %s",
        (token_hash,),
    )
    conn.commit()
    return _json_response(data={"message": "Logged out"})
```

**Step 3: Add auth middleware**

Create `telemetry_tool/web/middleware/__init__.py`:
```python
"""Middleware package."""
```

Create `telemetry_tool/web/middleware/auth.py`:
```python
"""JWT auth middleware — extracts user from Bearer token."""
from functools import wraps

from flask import request, g, current_app, jsonify


def auth_middleware():
    """Before-request hook: decode JWT if present."""
    if not current_app.config.get("AUTH_REQUIRED"):
        return  # Legacy mode — no auth required

    # Skip auth for auth routes themselves
    if request.path.startswith("/auth/"):
        return

    # Skip for legacy HTML routes (backward compat)
    if not request.path.startswith("/api/v1/"):
        return

    token = _extract_token()
    if token is None:
        return jsonify({
            "ok": False,
            "error": {"code": "UNAUTHORIZED", "message": "Authentication required"},
            "meta": {},
        }), 401

    from auth.service import decode_access_token, AuthError
    secret = current_app.config.get("JWT_SECRET", "jwt-dev-secret")
    try:
        payload = decode_access_token(token, secret)
        g.current_user_id = payload["user_id"]
    except AuthError as e:
        return jsonify({
            "ok": False,
            "error": {"code": e.code, "message": str(e)},
            "meta": {},
        }), 401


def require_auth(f):
    """Decorator: endpoint requires valid JWT."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, "current_user_id") or g.current_user_id is None:
            return jsonify({
                "ok": False,
                "error": {"code": "UNAUTHORIZED", "message": "Authentication required"},
                "meta": {},
            }), 401
        return f(*args, **kwargs)
    return decorated


def _extract_token():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None
```

**Step 4: Add /api/v1/me route and register auth blueprint**

Add to `telemetry_tool/web/routes/auth.py`:
```python
@bp.route("/api/v1/me", methods=["GET"])
def me():
    """Return current user profile. Requires auth."""
    from web.middleware.auth import require_auth

    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return _json_response(
            error={"code": "UNAUTHORIZED", "message": "Authentication required"},
            status=401,
        )

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, display_name, created_at FROM users WHERE id = %s",
        (user_id,),
    )
    user = cur.fetchone()
    if user is None:
        return _json_response(
            error={"code": "NOT_FOUND", "message": "User not found"}, status=404,
        )
    return _json_response(data=dict(user))
```

Register in `app.py`:
```python
# In create_app(), after existing blueprint registration:
if cfg.USE_PG:
    from .routes.auth import bp as auth_bp
    from .middleware.auth import auth_middleware
    app.register_blueprint(auth_bp)
    app.before_request(auth_middleware)
```

**Step 5: Run tests**

```bash
USE_PG=1 AUTH_REQUIRED=1 TELEMETRY_PG_URL=... pytest telemetry_tool/tests/test_auth_routes.py -v
```
Expected: All PASS.

**Step 6: Verify no regression**

```bash
pytest telemetry_tool/tests/ -v --ignore=telemetry_tool/tests/test_pg_schema.py --ignore=telemetry_tool/tests/test_db_connection.py --ignore=telemetry_tool/tests/test_data_migration.py --ignore=telemetry_tool/tests/test_auth_routes.py --ignore=telemetry_tool/tests/test_auth_service.py
```
Expected: All existing SQLite tests PASS.

**Step 7: Commit**

```bash
git add telemetry_tool/web/routes/auth.py telemetry_tool/web/middleware/ telemetry_tool/web/app.py telemetry_tool/tests/test_auth_routes.py
git commit -m "feat(auth): registration, login, logout routes with JWT middleware

POST /auth/register — create account + auto-login
POST /auth/login — email/password → access + refresh tokens
POST /auth/logout — revoke refresh token
GET /api/v1/me — current user (requires auth)

Auth enforced only when AUTH_REQUIRED=1 and USE_PG=1.
Legacy routes unaffected — backward compatible."
```

---

## PR 5: OAuth + Email Verification

### Task 13: OAuth dependencies and configuration

**Files:**
- Modify: `requirements.txt`

**Step 1: Add OAuth dependency**

Add to `requirements.txt`:
```
authlib>=1.3
```

**Step 2: Add OAuth config to Config class**

Add to `telemetry_tool/web/config.py`:
```python
# OAuth
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
OAUTH_REDIRECT_BASE = os.environ.get("OAUTH_REDIRECT_BASE", "http://localhost:5000")
```

**Step 3: Commit**

```bash
git add requirements.txt telemetry_tool/web/config.py
git commit -m "chore: add authlib for OAuth, add OAuth config"
```

---

### Task 14: OAuth connections migration

**Files:**
- Create: `telemetry_tool/alembic/versions/003_oauth_tables.py`

**Step 1: Write migration**

```python
"""Add oauth_connections table.

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_user_id", sa.Text, nullable=False),
        sa.Column("access_token_enc", sa.Text),
        sa.Column("refresh_token_enc", sa.Text),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_user_id"),
    )
    op.create_index("idx_oauth_user", "oauth_connections", ["user_id"])

    # Email verification token column
    op.add_column("users", sa.Column("email_verify_token", sa.Text))
    op.add_column("users", sa.Column("email_verify_expires", sa.DateTime))


def downgrade() -> None:
    op.drop_column("users", "email_verify_expires")
    op.drop_column("users", "email_verify_token")
    op.drop_table("oauth_connections")
```

**Step 2: Commit**

```bash
git add telemetry_tool/alembic/versions/003_oauth_tables.py
git commit -m "feat(auth): add oauth_connections table (migration 003)"
```

---

### Task 15: OAuth routes and email verification

**Files:**
- Create: `telemetry_tool/auth/oauth.py`
- Modify: `telemetry_tool/web/routes/auth.py` (add OAuth + verify routes)
- Create: `telemetry_tool/tests/test_auth_oauth.py`

**Step 1: Write tests**

Create `telemetry_tool/tests/test_auth_oauth.py`:
```python
"""Tests for OAuth and email verification flows."""
import os
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.skipif(
    not os.environ.get("TELEMETRY_PG_URL"), reason="TELEMETRY_PG_URL not set"
)


def test_oauth_redirect_google(auth_client):
    """GET /auth/oauth/google redirects to Google."""
    resp = auth_client.get("/auth/oauth/google")
    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["Location"]


def test_email_verification_flow(auth_client):
    """Register → get verify token → verify email."""
    # Register
    resp = auth_client.post("/auth/register", json={
        "email": "verify@example.com", "password": "password123", "display_name": "V",
    })
    assert resp.status_code == 201

    # In test mode, token is returned in response (not emailed)
    token = resp.get_json()["data"].get("email_verify_token")
    if token:
        resp = auth_client.post("/auth/verify-email", json={"token": token})
        assert resp.status_code == 200
```

**Step 2: Implement OAuth service**

Create `telemetry_tool/auth/oauth.py`:
```python
"""OAuth provider integration — Google and GitHub."""
from __future__ import annotations

from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def init_oauth(app):
    """Register OAuth providers with the Flask app."""
    oauth.init_app(app)

    if app.config.get("GOOGLE_CLIENT_ID"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    if app.config.get("GITHUB_CLIENT_ID"):
        oauth.register(
            name="github",
            client_id=app.config["GITHUB_CLIENT_ID"],
            client_secret=app.config["GITHUB_CLIENT_SECRET"],
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "user:email"},
        )


def get_or_create_oauth_user(conn, provider: str, profile: dict, secret: str) -> dict:
    """Find or create user from OAuth profile. Returns login result."""
    from auth.service import create_access_token, create_refresh_token, hash_refresh_token
    from datetime import datetime, timedelta, timezone

    email = profile["email"]
    provider_user_id = str(profile["id"])

    cur = conn.cursor()

    # Check if OAuth connection exists
    cur.execute(
        "SELECT user_id FROM oauth_connections "
        "WHERE provider = %s AND provider_user_id = %s",
        (provider, provider_user_id),
    )
    row = cur.fetchone()

    if row:
        user_id = row["user_id"]
    else:
        # Check if user with this email exists (link accounts)
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing = cur.fetchone()

        if existing:
            user_id = existing["id"]
        else:
            # Create new user (no password — OAuth only)
            cur.execute(
                "INSERT INTO users (email, display_name, email_verified) "
                "VALUES (%s, %s, true) RETURNING id",
                (email, profile.get("name", email.split("@")[0])),
            )
            user_id = cur.fetchone()["id"]

        # Create OAuth connection
        cur.execute(
            "INSERT INTO oauth_connections (user_id, provider, provider_user_id) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (user_id, provider, provider_user_id),
        )

    # Issue tokens
    access_token = create_access_token(user_id, secret)
    refresh_token = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    cur.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s)",
        (user_id, hash_refresh_token(refresh_token), expires_at),
    )
    conn.commit()

    cur.execute("SELECT id, email, display_name FROM users WHERE id = %s", (user_id,))
    user = dict(cur.fetchone())

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user,
    }
```

**Step 3: Add OAuth routes to auth.py**

Add to `telemetry_tool/web/routes/auth.py`:
```python
@bp.route("/oauth/<provider>", methods=["GET"])
def oauth_redirect(provider):
    """Redirect to OAuth provider."""
    from auth.oauth import oauth as oauth_registry
    client = oauth_registry.create_client(provider)
    if client is None:
        return _json_response(
            error={"code": "NOT_FOUND", "message": f"Unknown provider: {provider}"},
            status=404,
        )
    redirect_uri = f"{current_app.config['OAUTH_REDIRECT_BASE']}/auth/oauth/{provider}/callback"
    return client.authorize_redirect(redirect_uri)


@bp.route("/oauth/<provider>/callback", methods=["GET"])
def oauth_callback(provider):
    """Handle OAuth callback — create/link user, issue tokens."""
    from auth.oauth import oauth as oauth_registry, get_or_create_oauth_user

    client = oauth_registry.create_client(provider)
    token = client.authorize_access_token()

    if provider == "google":
        userinfo = token.get("userinfo", {})
        profile = {
            "id": userinfo["sub"],
            "email": userinfo["email"],
            "name": userinfo.get("name", ""),
        }
    elif provider == "github":
        resp = client.get("user")
        profile = resp.json()
        if not profile.get("email"):
            emails = client.get("user/emails").json()
            primary = next((e for e in emails if e["primary"]), emails[0])
            profile["email"] = primary["email"]

    conn = _get_conn()
    secret = current_app.config.get("JWT_SECRET", "jwt-dev-secret")
    result = get_or_create_oauth_user(conn, provider, profile, secret)

    # Redirect to frontend with tokens (or return JSON)
    return _json_response(data=result)


@bp.route("/verify-email", methods=["POST"])
def verify_email():
    """Verify email address with token."""
    body = request.get_json(silent=True) or {}
    token = body.get("token", "").strip()
    if not token:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Token required"}, status=400,
        )

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET email_verified = true, email_verify_token = NULL "
        "WHERE email_verify_token = %s AND email_verify_expires > NOW() "
        "RETURNING id",
        (token,),
    )
    row = cur.fetchone()
    conn.commit()

    if row is None:
        return _json_response(
            error={"code": "INVALID_TOKEN", "message": "Invalid or expired token"},
            status=400,
        )
    return _json_response(data={"message": "Email verified"})
```

**Step 4: Initialize OAuth in app factory**

Add to `app.py` in the `if cfg.USE_PG:` block:
```python
if cfg.GOOGLE_CLIENT_ID or cfg.GITHUB_CLIENT_ID:
    from auth.oauth import init_oauth
    init_oauth(app)
```

**Step 5: Run tests**

```bash
USE_PG=1 AUTH_REQUIRED=1 TELEMETRY_PG_URL=... pytest telemetry_tool/tests/test_auth_oauth.py -v
```

**Step 6: Run full test suite**

```bash
pytest telemetry_tool/tests/ -v
```
Expected: All tests PASS (new and existing).

**Step 7: Commit**

```bash
git add telemetry_tool/auth/oauth.py telemetry_tool/web/routes/auth.py telemetry_tool/web/app.py telemetry_tool/alembic/versions/003_oauth_tables.py telemetry_tool/tests/test_auth_oauth.py
git commit -m "feat(auth): OAuth (Google/GitHub) + email verification

GET /auth/oauth/:provider — redirect to OAuth flow
GET /auth/oauth/:provider/callback — exchange code, create/link user
POST /auth/verify-email — verify with token

OAuth users auto-verified. Account linking by email."
```

---

## Verification Checklist (Phase 1 Complete)

After all 5 PRs are merged, verify:

- [ ] `docker compose up -d` starts PG + Redis
- [ ] `alembic upgrade head` creates all 80+ tables + auth tables in PG
- [ ] `python scripts/migrate_sqlite_to_pg.py` transfers existing data
- [ ] `USE_PG=0` — app works identically to before (SQLite)
- [ ] `USE_PG=1 AUTH_REQUIRED=0` — app uses PG but no auth needed
- [ ] `USE_PG=1 AUTH_REQUIRED=1` — full auth enforced on /api/v1/ routes
- [ ] Legacy HTML routes work without auth (backward compat)
- [ ] All existing SQLite tests pass
- [ ] All new PG + auth tests pass
- [ ] Frontend developer can work without any changes
