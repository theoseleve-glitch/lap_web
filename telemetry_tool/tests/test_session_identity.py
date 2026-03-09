"""Tests for session identity columns (display_name, source_filename, source_path)."""
import sqlite3

import pytest

from db.migrate import ensure_schema


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def test_session_table_has_identity_columns(test_db):
    """Schema must include display_name, source_filename, source_path."""
    cursor = test_db.execute("PRAGMA table_info(sessions)")
    cols = {row["name"] for row in cursor.fetchall()}
    assert "display_name" in cols, "Missing display_name column"
    assert "source_filename" in cols, "Missing source_filename column"
    assert "source_path" in cols, "Missing source_path column"


def test_insert_session_with_identity_fields(test_db):
    """Can insert a session with the new identity columns."""
    test_db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    test_db.execute("""
        INSERT INTO sessions (session_id, csv_filename, driver_id,
                              session_type, track_state, session_date,
                              display_name, source_filename, source_path)
        VALUES ('s1', 'OK_R3.csv', 1, 'practice', 'dry', '2026-03-01',
                'OK_R3', 'OK_R3.csv', '/tmp/telemetry_upload_xyz/OK_R3.csv')
    """)
    test_db.commit()
    row = test_db.execute("SELECT * FROM sessions WHERE session_id = 's1'").fetchone()
    assert row["display_name"] == "OK_R3"
    assert row["source_filename"] == "OK_R3.csv"
    assert row["source_path"] == "/tmp/telemetry_upload_xyz/OK_R3.csv"


def test_display_name_defaults_to_null(test_db):
    """display_name should be NULL if not provided (backwards compat)."""
    test_db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    test_db.execute("""
        INSERT INTO sessions (session_id, csv_filename, driver_id,
                              session_type, track_state, session_date)
        VALUES ('s2', 'test.csv', 1, 'practice', 'dry', '2026-03-01')
    """)
    row = test_db.execute("SELECT display_name FROM sessions WHERE session_id = 's2'").fetchone()
    assert row["display_name"] is None
