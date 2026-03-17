"""
Venue database module — SQLite-backed storage for the PIP venue registry.
"""

import sqlite3
import uuid
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("/sessions/wonderful-sleepy-feynman/pip-data/venues.db")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create the venues table and indexes."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS venues (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            slug            TEXT,
            country         TEXT NOT NULL,
            city            TEXT,
            latitude        REAL,
            longitude       REAL,
            address         TEXT,

            -- Timing system
            timing_system   TEXT NOT NULL DEFAULT 'unknown',
            timing_slug     TEXT,
            live_timing_url TEXT,
            timing_verified INTEGER DEFAULT 0,

            -- Metadata
            sws_id          TEXT,
            sws_url         TEXT,
            sws_categories  TEXT,        -- JSON array
            website_url     TEXT,
            google_place_id TEXT,
            phone           TEXT,
            rating          REAL,

            -- Status
            status          TEXT DEFAULT 'unverified',
            last_seen_live  TEXT,
            source          TEXT,

            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_venues_country ON venues(country);
        CREATE INDEX IF NOT EXISTS idx_venues_timing ON venues(timing_system);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_venues_timing_slug
            ON venues(timing_system, timing_slug)
            WHERE timing_slug IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_venues_sws_id
            ON venues(sws_id)
            WHERE sws_id IS NOT NULL;
    """)
    conn.commit()
    conn.close()


def upsert_venue(venue: dict) -> str:
    """Insert or update a venue. Returns the venue ID."""
    conn = get_connection()

    # Check if venue exists by id, sws_id, or (timing_system, timing_slug)
    existing = None
    if venue.get("id"):
        existing = conn.execute(
            "SELECT id FROM venues WHERE id = ?", (venue["id"],)
        ).fetchone()
    if not existing and venue.get("sws_id"):
        existing = conn.execute(
            "SELECT id FROM venues WHERE sws_id = ?", (venue["sws_id"],)
        ).fetchone()
    if not existing and venue.get("timing_slug"):
        existing = conn.execute(
            "SELECT id FROM venues WHERE timing_system = ? AND timing_slug = ?",
            (venue.get("timing_system", "unknown"), venue["timing_slug"]),
        ).fetchone()

    if existing:
        venue_id = existing["id"]
        # Update existing venue with new data (merge, don't overwrite nulls)
        updates = []
        values = []
        for key, val in venue.items():
            if key == "id" or val is None:
                continue
            if key == "sws_categories" and isinstance(val, list):
                val = json.dumps(val)
            updates.append(f"{key} = ?")
            values.append(val)
        updates.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(venue_id)
        conn.execute(
            f"UPDATE venues SET {', '.join(updates)} WHERE id = ?", values
        )
    else:
        venue_id = venue.get("id", str(uuid.uuid4()))
        cats = venue.get("sws_categories")
        if isinstance(cats, list):
            cats = json.dumps(cats)
        conn.execute(
            """INSERT INTO venues (id, name, slug, country, city, latitude, longitude,
               address, timing_system, timing_slug, live_timing_url, timing_verified,
               sws_id, sws_url, sws_categories, website_url, source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                venue_id,
                venue["name"],
                venue.get("slug"),
                venue["country"],
                venue.get("city"),
                venue.get("latitude"),
                venue.get("longitude"),
                venue.get("address"),
                venue.get("timing_system", "unknown"),
                venue.get("timing_slug"),
                venue.get("live_timing_url"),
                venue.get("timing_verified", False),
                venue.get("sws_id"),
                venue.get("sws_url"),
                cats,
                venue.get("website_url"),
                venue.get("source", "unknown"),
                venue.get("status", "unverified"),
            ),
        )

    conn.commit()
    conn.close()
    return venue_id


def get_venues(country: str = None, timing_system: str = None, unresolved_only: bool = False) -> list[dict]:
    """Query venues with optional filters."""
    conn = get_connection()
    query = "SELECT * FROM venues WHERE 1=1"
    params = []
    if country:
        query += " AND country = ?"
        params.append(country)
    if timing_system:
        query += " AND timing_system = ?"
        params.append(timing_system)
    if unresolved_only:
        query += " AND (timing_slug IS NULL OR timing_verified = 0)"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_venue_count(country: str = None) -> int:
    conn = get_connection()
    query = "SELECT COUNT(*) as cnt FROM venues"
    params = []
    if country:
        query += " WHERE country = ?"
        params.append(country)
    result = conn.execute(query, params).fetchone()
    conn.close()
    return result["cnt"]


def get_stats() -> dict:
    """Return summary statistics about the venue database."""
    conn = get_connection()
    stats = {}
    stats["total"] = conn.execute("SELECT COUNT(*) as c FROM venues").fetchone()["c"]
    stats["by_country"] = {
        row["country"]: row["c"]
        for row in conn.execute(
            "SELECT country, COUNT(*) as c FROM venues GROUP BY country ORDER BY c DESC"
        ).fetchall()
    }
    stats["timing_verified"] = conn.execute(
        "SELECT COUNT(*) as c FROM venues WHERE timing_verified = 1"
    ).fetchone()["c"]
    stats["with_slug"] = conn.execute(
        "SELECT COUNT(*) as c FROM venues WHERE timing_slug IS NOT NULL"
    ).fetchone()["c"]
    stats["by_source"] = {
        row["source"]: row["c"]
        for row in conn.execute(
            "SELECT source, COUNT(*) as c FROM venues GROUP BY source ORDER BY c DESC"
        ).fetchall()
    }
    conn.close()
    return stats
