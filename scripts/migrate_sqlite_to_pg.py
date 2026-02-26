#!/usr/bin/env python
"""
Migrate data from SQLite to PostgreSQL.

Reads all rows from the SQLite database and inserts them into a PostgreSQL
database using ``INSERT ... ON CONFLICT DO NOTHING`` for idempotency.

Tables are processed in foreign-key dependency order (parents before
children) so that referential integrity is never violated.

Usage::

    python scripts/migrate_sqlite_to_pg.py [--sqlite PATH] [--pg-url URL]

Defaults:
    --sqlite  telemetry.db  (or TELEMETRY_DB_PATH env var)
    --pg-url  from TELEMETRY_PG_URL env var, falling back to
              postgresql://telemetry:telemetry@localhost:5432/telemetry
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table order: parents before children (FK dependency order).
# This must list every table from SQLite schema phases 1-17.
# ---------------------------------------------------------------------------

TABLE_ORDER: list[str] = [
    # Phase 1 (core)
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
]

# Columns that are INTEGER in SQLite but BOOLEAN in PostgreSQL.
# The migration must cast 0/1 -> False/True for psycopg2.
BOOLEAN_COLUMNS: dict[str, set[str]] = {
    "tracks": {"has_joker"},
    "laps": {"is_valid", "is_best", "is_joker"},
    "custom_dashboards": {"is_default"},
    "predefined_tracks": {"rental_available", "owner_available", "outdoor"},
    "race_configs": {
        "weigh_on_pit_exit",
        "refuel_after_quali",
        "mandatory_driver_change",
        "refueling_allowed",
    },
    "race_pit_stops": {"driver_change", "refueled", "ballast_changed"},
    "race_windows": {"refuel_allowed", "driver_change_allowed"},
}

# Columns that are TEXT in SQLite but JSONB in PostgreSQL.
# Values that are valid JSON strings are passed as-is (psycopg2 handles
# the TEXT -> JSONB cast via ``Json`` wrapper).  Non-JSON values are
# left as NULL.
JSONB_COLUMNS: dict[str, set[str]] = {
    "sessions": {"weather_json"},
    "gps_traces": {
        "latitudes_json",
        "longitudes_json",
        "distances_json",
        "speeds_json",
        "accel_lat_json",
        "accel_long_json",
    },
    "score_details": {"strengths_json", "weaknesses_json"},
    "driving_style_features": {"strengths_json", "weaknesses_json"},
    "theoretical_data": {"speed_profile_json", "distance_json", "metrics_json"},
    "reference_lines": {
        "latitudes_json",
        "longitudes_json",
        "distances_json",
        "speeds_json",
    },
    "data_health": {"report_json"},
    "vehicle_setups": {"gear_ratios_json"},
    "what_if_scenarios": {"adjustments_json"},
    "session_annotations": {"tags_json"},
    "development_plans": {"weeks_json", "progress_json"},
    "driver_badges": {"metadata_json"},
    "custom_dashboards": {"layout_json"},
    "export_templates": {"sections_json"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return True if the table exists in the SQLite database."""
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cur.fetchone() is not None


def _sqlite_column_names(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Return the ordered column names for a SQLite table."""
    cur = conn.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]


def _pg_column_names(pg_conn, table_name: str) -> list[str]:
    """Return the ordered column names for a PostgreSQL table."""
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "ORDER BY ordinal_position",
        (table_name,),
    )
    return [row[0] for row in cur.fetchall()]


def _convert_value(
    table_name: str, col_name: str, value: Any
) -> Any:
    """Convert a SQLite value for PostgreSQL insertion.

    - INTEGER 0/1 -> Python bool for BOOLEAN columns
    - TEXT JSON -> psycopg2.extras.Json for JSONB columns
    - None stays None (NULL)
    """
    if value is None:
        return value

    # Boolean conversion
    bool_cols = BOOLEAN_COLUMNS.get(table_name, set())
    if col_name in bool_cols:
        return bool(value)

    # JSONB conversion
    jsonb_cols = JSONB_COLUMNS.get(table_name, set())
    if col_name in jsonb_cols:
        from psycopg2.extras import Json

        if isinstance(value, str):
            # Validate it is actually JSON; if not, pass as NULL.
            try:
                parsed = json.loads(value)
                return Json(parsed)
            except (json.JSONDecodeError, TypeError):
                return None
        # Already a Python object (unlikely from SQLite, but defensive).
        return Json(value)

    return value


def _build_upsert_sql(table_name: str, columns: list[str]) -> str:
    """Build ``INSERT INTO ... ON CONFLICT DO NOTHING`` SQL for psycopg2."""
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    return (
        f'INSERT INTO "{table_name}" ({col_list}) '
        f"VALUES ({placeholders}) "
        f"ON CONFLICT DO NOTHING"
    )


def _reset_sequences(pg_conn) -> None:
    """Reset all auto-increment sequences to MAX(pk) + 1.

    After migrating rows with explicit integer PKs, PostgreSQL sequences
    still point at their initial value.  Without this step the next
    INSERT without an explicit ID would collide with migrated data.
    """
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT c.relname AS table_name, "
        "       a.attname AS column_name, "
        "       pg_get_serial_sequence(c.relname::text, a.attname) AS seq_name "
        "FROM pg_class c "
        "JOIN pg_attribute a ON a.attrelid = c.oid "
        "JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum "
        "WHERE c.relkind = 'r' "
        "  AND pg_get_serial_sequence(c.relname::text, a.attname) IS NOT NULL "
        "  AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')"
    )
    sequences = cur.fetchall()

    for table_name, column_name, seq_name in sequences:
        cur.execute(
            f'SELECT setval(%s, COALESCE((SELECT MAX("{column_name}") '
            f'FROM "{table_name}"), 0) + 1, false)',
            (seq_name,),
        )
        logger.debug("Reset sequence %s for %s.%s", seq_name, table_name, column_name)

    pg_conn.commit()
    cur.close()
    logger.info("Reset %d auto-increment sequences", len(sequences))


# ---------------------------------------------------------------------------
# Core migration
# ---------------------------------------------------------------------------

def migrate(
    sqlite_path: str | Path,
    pg_url: str,
    *,
    tables: list[str] | None = None,
    batch_size: int = 500,
) -> dict[str, int]:
    """
    Migrate data from SQLite to PostgreSQL.

    Parameters
    ----------
    sqlite_path : path to the SQLite database file
    pg_url : PostgreSQL connection URL
    tables : optional subset of tables to migrate (default: all in TABLE_ORDER)
    batch_size : rows per INSERT batch (default 500)

    Returns
    -------
    dict mapping table_name -> number of rows attempted for insertion.
    Rows skipped by ON CONFLICT DO NOTHING are still counted (use
    PostgreSQL row counts to determine actual inserts).
    """
    import psycopg2
    import psycopg2.extras

    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    # Open SQLite connection.
    sq_conn = sqlite3.connect(str(sqlite_path))
    sq_conn.row_factory = sqlite3.Row

    # Open PostgreSQL connection.
    pg_conn = psycopg2.connect(pg_url)

    result: dict[str, int] = {}
    target_tables = tables or TABLE_ORDER

    try:
        for table_name in target_tables:
            # Skip tables that don't exist in this SQLite DB (older schema).
            if not _sqlite_table_exists(sq_conn, table_name):
                logger.info("Skipping %s (not in SQLite)", table_name)
                result[table_name] = 0
                continue

            # Get column intersection (SQLite cols that also exist in PG).
            sq_cols = _sqlite_column_names(sq_conn, table_name)
            pg_cols = _pg_column_names(pg_conn, table_name)
            pg_col_set = set(pg_cols)
            common_cols = [c for c in sq_cols if c in pg_col_set]

            if not common_cols:
                logger.warning("No common columns for %s — skipping", table_name)
                result[table_name] = 0
                continue

            # Read all rows from SQLite.
            col_select = ", ".join(f'"{c}"' for c in common_cols)
            sq_cur = sq_conn.execute(f'SELECT {col_select} FROM "{table_name}"')
            rows = sq_cur.fetchall()

            if not rows:
                logger.info("Table %s: 0 rows (empty)", table_name)
                result[table_name] = 0
                continue

            # Build the INSERT statement.
            insert_sql = _build_upsert_sql(table_name, common_cols)

            # Insert in batches.
            pg_cur = pg_conn.cursor()
            inserted = 0

            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                converted_batch = []
                for row in batch:
                    converted_row = tuple(
                        _convert_value(table_name, col, row[col])
                        for col in common_cols
                    )
                    converted_batch.append(converted_row)

                psycopg2.extras.execute_batch(pg_cur, insert_sql, converted_batch)
                inserted += len(converted_batch)

            pg_cur.close()
            pg_conn.commit()
            result[table_name] = inserted
            logger.info("Table %s: %d rows attempted", table_name, inserted)

        # Reset auto-increment sequences so new inserts don't collide.
        _reset_sequences(pg_conn)

    except Exception:
        pg_conn.rollback()
        raise
    finally:
        sq_conn.close()
        pg_conn.close()

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line interface for the migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate data from SQLite to PostgreSQL."
    )
    parser.add_argument(
        "--sqlite",
        default=os.environ.get(
            "TELEMETRY_DB_PATH", "telemetry.db"
        ),
        help="Path to the SQLite database (default: telemetry.db or TELEMETRY_DB_PATH)",
    )
    parser.add_argument(
        "--pg-url",
        default=os.environ.get(
            "TELEMETRY_PG_URL",
            "postgresql://telemetry:telemetry@localhost:5432/telemetry",
        ),
        help="PostgreSQL connection URL (default: TELEMETRY_PG_URL env var)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per INSERT batch (default: 500)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    result = migrate(args.sqlite, args.pg_url, batch_size=args.batch_size)

    total = sum(result.values())
    print(f"\nMigration complete: {total} total rows across {len(result)} tables.")
    for table, count in result.items():
        if count > 0:
            print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
