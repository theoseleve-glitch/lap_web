"""
Schema migration for the telemetry SQLite database.

Applies table-creation statements idempotently (IF NOT EXISTS)
and tracks the schema version so future phases can add ALTER TABLE
or new tables safely.
"""

from __future__ import annotations

import csv
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from .schema import ALL_TABLES, SCHEMA_VERSION

logger = logging.getLogger(__name__)


def ensure_schema(conn: sqlite3.Connection) -> int:
    """
    Create all tables if they do not exist and record the schema version.

    Returns the version number that is now active.
    """
    cur = conn.cursor()

    for table_name, ddl in ALL_TABLES:
        try:
            cur.executescript(ddl)
            logger.debug("Table '%s' ensured.", table_name)
        except sqlite3.Error as exc:
            logger.warning("Failed to create table '%s': %s", table_name, exc)
            raise

    # Record versions (INSERT OR IGNORE so re-runs are harmless).
    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (1, "Phase 1 schema — core tables"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (2, "Phase 2 schema — weekends, track records, condition markers"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (3, "Phase 3 schema — driver profiles, progression, driving style"),
    )

    # Phase 4 migration: add columns to existing tables (idempotent).
    for col in ("accel_lat_json TEXT", "accel_long_json TEXT"):
        try:
            cur.execute(f"ALTER TABLE gps_traces ADD COLUMN {col};")
            logger.debug("Added column gps_traces.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass  # Column already exists.

    # Phase 5 migration: add invalid_reason column to laps (idempotent).
    try:
        cur.execute("ALTER TABLE laps ADD COLUMN invalid_reason TEXT;")
        logger.debug("Added column laps.invalid_reason.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (4, "Phase 4 schema — theoretical data, reference lines, G-G accel"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (5, "Phase 5 schema — session sectors for visualization mode"),
    )

    # Phase 6 migration: add session_subtype column to sessions (idempotent).
    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN session_subtype TEXT;")
        logger.debug("Added column sessions.session_subtype.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (6, "Phase 6 schema — data health, session tags, session subtype"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (7, "Phase 7 schema — corner metrics, corner best practices"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (8, "Phase 8 schema — session_weather"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (9, "Phase 9 schema — vehicle_setups, what_if_scenarios"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (10, "Phase 10 schema — annotations, development plans, dashboards, export templates"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (11, "Phase 11 schema — stint_analysis"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (12, "Phase 12 schema — ingestion_jobs (streaming ingest pipeline)"),
    )

    # Phase 13 migration: add joker lap columns (idempotent).
    for col in (
        "has_joker INTEGER NOT NULL DEFAULT 0",
        "joker_distance_delta_m REAL",
        "joker_time_delta_s REAL",
    ):
        try:
            cur.execute(f"ALTER TABLE tracks ADD COLUMN {col};")
            logger.debug("Added column tracks.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass  # Column already exists.

    try:
        cur.execute("ALTER TABLE laps ADD COLUMN is_joker INTEGER NOT NULL DEFAULT 0;")
        logger.debug("Added column laps.is_joker.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN joker_lap_number INTEGER;")
        logger.debug("Added column sessions.joker_lap_number.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (13, "Phase 13 schema — joker lap columns on tracks, laps, sessions"),
    )

    # Phase 14 migration: add observability columns to ingestion_jobs (idempotent).
    for col in ("peak_rss_mb REAL", "throughput_mb_s REAL"):
        try:
            cur.execute(f"ALTER TABLE ingestion_jobs ADD COLUMN {col};")
            logger.debug("Added column ingestion_jobs.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (14, "Phase 14 schema — ingestion observability (peak_rss_mb, throughput_mb_s)"),
    )

    # Phase 15 migration: add lat/lon/dist_m to track_key_corners (idempotent).
    for col in ("lat REAL", "lon REAL", "dist_m REAL"):
        try:
            cur.execute(f"ALTER TABLE track_key_corners ADD COLUMN {col};")
            logger.debug("Added column track_key_corners.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (15, "Phase 15 schema — key corners lat/lon/dist_m for custom areas of interest"),
    )

    # Phase 16 migration: predefined catalogs, karts, track sectors, FK columns.
    try:
        cur.execute("ALTER TABLE tracks ADD COLUMN predefined_track_id INTEGER;")
        logger.debug("Added column tracks.predefined_track_id.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    try:
        cur.execute("ALTER TABLE tracks ADD COLUMN original_start_lat REAL;")
        logger.debug("Added column tracks.original_start_lat.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    try:
        cur.execute("ALTER TABLE tracks ADD COLUMN original_start_lon REAL;")
        logger.debug("Added column tracks.original_start_lon.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN kart_id INTEGER;")
        logger.debug("Added column sessions.kart_id.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    # Import predefined_track_list.csv (idempotent: skip if already populated).
    project_root = Path(__file__).resolve().parents[2]

    track_count = cur.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
    if track_count == 0:
        track_csv = project_root / "predefined_track_list.csv"
        if track_csv.exists():
            with open(track_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Skip blank rows where Track column is empty.
                    if not row.get("Track", "").strip():
                        continue
                    rental = 1 if row.get("RentalAvailable", "").strip().lower() == "yes" else 0
                    owner = 1 if row.get("OwnerAvailable", "").strip().lower() == "yes" else 0
                    outdoor = 1 if row.get("Outdoor", "").strip().lower() != "no" else 0
                    length_raw = row.get("LayoutLength_m", "").strip()
                    try:
                        length_m = float(length_raw) if length_raw else None
                    except (ValueError, TypeError):
                        length_m = None
                    cur.execute(
                        "INSERT INTO predefined_tracks "
                        "(country, track_name, city, region, layout_name, "
                        " layout_length_m, direction, rental_available, owner_available, "
                        " outdoor, data_quality, source_url) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                        (
                            row.get("Country", "").strip() or None,
                            row.get("Track", "").strip() or None,
                            row.get("City", "").strip() or None,
                            row.get("Region", "").strip() or None,
                            row.get("LayoutName", "").strip() or None,
                            length_m,
                            row.get("Direction", "").strip() or None,
                            rental,
                            owner,
                            outdoor,
                            row.get("DataQuality", "").strip() or None,
                            row.get("Source", "").strip() or None,
                        ),
                    )
            logger.info("Imported predefined tracks from %s.", track_csv)
        else:
            logger.warning("predefined_track_list.csv not found at %s; skipping import.", track_csv)

    # Import predefined_kart_list.csv (idempotent: skip if already populated).
    kart_count = cur.execute("SELECT COUNT(*) FROM predefined_karts").fetchone()[0]
    if kart_count == 0:
        kart_csv = project_root / "predefined_kart_list.csv"
        if kart_csv.exists():
            with open(kart_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Skip blank rows where model column is empty.
                    if not row.get("model", "").strip():
                        continue

                    def _val(key: str) -> str | None:
                        """Return stripped value or None for empty / 'NA'."""
                        v = row.get(key, "").strip()
                        return None if (not v or v.upper() == "NA") else v

                    def _float(key: str) -> float | None:
                        v = _val(key)
                        try:
                            return float(v) if v is not None else None
                        except (ValueError, TypeError):
                            return None

                    def _int(key: str) -> int | None:
                        v = _val(key)
                        try:
                            return int(v) if v is not None else None
                        except (ValueError, TypeError):
                            return None

                    cur.execute(
                        "INSERT INTO predefined_karts "
                        "(segment, manufacturer, model, model_year_start, "
                        " use_or_championship, engine, power_hp, engine_type, "
                        " kart_weight_kg, top_speed_kmh, zero_to_100_s, "
                        " power_to_weight, braking_g_est, lateral_g_est, weight_source) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                        (
                            _val("segment"),
                            _val("manufacturer"),
                            _val("model"),
                            _int("model_year_start"),
                            _val("use_or_championship"),
                            _val("engine"),
                            _float("power_hp"),
                            _val("engine_type"),
                            _float("kart_weight_kg_no_driver"),
                            _float("top_speed_kmh"),
                            _float("zero_to_100_kmh_s"),
                            _float("power_to_weight_hp_per_kg"),
                            _float("braking_g_est"),
                            _float("lateral_g_est"),
                            _val("weight_source"),
                        ),
                    )
            logger.info("Imported predefined karts from %s.", kart_csv)
        else:
            logger.warning("predefined_kart_list.csv not found at %s; skipping import.", kart_csv)

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (16, "Phase 16 schema — predefined tracks/karts catalogs, karts table, track sectors"),
    )

    # Phase 17 migration: add contact fields to driver_profiles (idempotent).
    for col in ("email TEXT", "phone TEXT", "id_code TEXT"):
        try:
            cur.execute(f"ALTER TABLE driver_profiles ADD COLUMN {col};")
            logger.debug("Added column driver_profiles.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass  # Column already exists.

    # Phase 17 migration: add condition-specific reference lines to tracks.
    for col in ("dry_ref_session_id TEXT", "wet_ref_session_id TEXT"):
        try:
            cur.execute(f"ALTER TABLE tracks ADD COLUMN {col};")
            logger.debug("Added column tracks.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (17, "Phase 17 schema — driver contact fields, track condition reference lines"),
    )

    # Phase 18 migration: completed_at on development_plans, coaching linking tables.
    try:
        cur.execute("ALTER TABLE development_plans ADD COLUMN completed_at TEXT;")
        logger.debug("Added column development_plans.completed_at.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (18, "Phase 18 schema — coaching linking (plan_drill_sessions, driver_badges, completed_at)"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (19, "Phase 19 schema — predefined_track_coords geocoding cache"),
    )

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (20, "Phase 15 schema — race strategy (race_configs, race_drivers, race_stints, race_pit_stops)"),
    )

    # Phase 21 migration: add com_channel to race_drivers (idempotent).
    try:
        cur.execute("ALTER TABLE race_drivers ADD COLUMN com_channel TEXT;")
        logger.debug("Added column race_drivers.com_channel.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (21, "Phase 16 — race messages + driver com_channel"),
    )

    # Phase 22 migration: Tier 4 — fuel-aware ballast, quick pit stops.
    try:
        cur.execute("ALTER TABLE race_configs ADD COLUMN quick_pit_stop_s INTEGER;")
        logger.debug("Added column race_configs.quick_pit_stop_s.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    for col in ("ballast_base_kg REAL", "ballast_fuel_offset_kg REAL", "fuel_burn_rate_kgs REAL"):
        try:
            cur.execute(f"ALTER TABLE race_stints ADD COLUMN {col};")
            logger.debug("Added column race_stints.%s.", col.split()[0])
        except sqlite3.OperationalError:
            pass  # Column already exists.

    try:
        cur.execute("ALTER TABLE race_pit_stops ADD COLUMN pit_type TEXT NOT NULL DEFAULT 'full';")
        logger.debug("Added column race_pit_stops.pit_type.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (22, "Phase 22 schema — Tier 4 fuel-aware ballast, quick pit stops"),
    )

    # Phase 23 migration: Tier 5 — race windows, driver colors.
    # Create race_windows table (idempotent via IF NOT EXISTS).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_windows (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id               INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
            window_type           TEXT NOT NULL,
            label                 TEXT,
            start_s               INTEGER NOT NULL,
            end_s                 INTEGER NOT NULL,
            refuel_allowed        INTEGER NOT NULL DEFAULT 1,
            driver_change_allowed INTEGER NOT NULL DEFAULT 1,
            window_order          INTEGER NOT NULL DEFAULT 1
        );
    """)
    logger.debug("Ensured race_windows table exists.")

    try:
        cur.execute("ALTER TABLE race_drivers ADD COLUMN color_hex TEXT;")
        logger.debug("Added column race_drivers.color_hex.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (23, "Phase 23 schema — Tier 5 race windows, driver colors"),
    )

    # Phase 24 migration: Tier 6 — neutralizations, rivals, rival events.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_neutralizations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
            start_s    INTEGER NOT NULL,
            end_s      INTEGER,
            reason     TEXT    NOT NULL DEFAULT 'safety_car',
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_rivals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id     INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
            team_name   TEXT    NOT NULL,
            car_number  TEXT    NOT NULL,
            notes       TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_rival_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id     INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
            rival_id    INTEGER NOT NULL REFERENCES race_rivals(id) ON DELETE CASCADE,
            event_type  TEXT    NOT NULL,
            at_s        INTEGER NOT NULL,
            detail      TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    logger.debug("Ensured race_neutralizations, race_rivals, race_rival_events tables exist.")

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (24, "Phase 24 schema — Tier 6 neutralizations, rivals, rival events"),
    )

    conn.commit()

    logger.info("Database schema at version %d.", SCHEMA_VERSION)
    return SCHEMA_VERSION


def get_current_version(conn: sqlite3.Connection) -> Optional[int]:
    """Return the highest applied schema version, or None if no DB."""
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version;"
        ).fetchone()
        return row[0] if row and row[0] is not None else None
    except sqlite3.OperationalError:
        return None
