"""tracks.canonical_id must exist in the SQLite schema (parity with PG).

Regression for the desktop/CLI crash: upsert_session's canonical guard did
``SELECT t_existing.canonical_id`` but the column existed only in PG, so SQLite
raised ``no such column: t_existing.canonical_id``.
"""
import sqlite3

from db.migrate import ensure_schema


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def test_fresh_schema_has_canonical_id():
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    assert "canonical_id" in _cols(conn, "tracks")


def test_migration_adds_canonical_id_to_old_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE tracks (track_id TEXT PRIMARY KEY, "
        "track_name TEXT NOT NULL, lap_length_m REAL NOT NULL);"
    )
    conn.commit()
    ensure_schema(conn)  # idempotent self-heal must add the column
    assert "canonical_id" in _cols(conn, "tracks")


def test_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    ensure_schema(conn)  # second run must not raise on the ALTER
    assert "canonical_id" in _cols(conn, "tracks")
