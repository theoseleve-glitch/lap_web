"""Tests for session_date derivation and driver/track resolution."""
import sqlite3

import pytest

from db.migrate import ensure_schema


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def test_session_date_from_telemetry_timestamps(test_db):
    from web.models import upsert_driver, upsert_session
    driver_id = upsert_driver(test_db, "Test Driver")
    summary = {
        "csv_path": "/tmp/test.csv",
        "session_meta": {
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "Test Driver",
        },
        "session_context": None,
        "score_result": {},
        "lap_times": [60.0, 61.0],
        "resampled_laps": {},
        "telemetry_start_time": "2026-02-15T14:30:00",
    }
    session_id = upsert_session(test_db, summary, driver_id)
    test_db.commit()
    row = test_db.execute(
        "SELECT session_date FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    assert row["session_date"].startswith("2026-02-15"), \
        f"session_date should be from telemetry, got {row['session_date']}"


def test_track_null_when_detection_fails(test_db):
    from web.models import upsert_driver, upsert_session
    driver_id = upsert_driver(test_db, "Test Driver")
    summary = {
        "csv_path": "/tmp/test.csv",
        "session_meta": {"session_type": "practice", "track_state": "dry"},
        "session_context": None,
        "score_result": {},
        "lap_times": [60.0],
        "resampled_laps": {},
        "track_id": None,
    }
    session_id = upsert_session(test_db, summary, driver_id)
    test_db.commit()
    row = test_db.execute(
        "SELECT track_id FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    assert row["track_id"] is None


def test_csv_filename_stored_as_name_only(test_db):
    from web.models import upsert_driver, upsert_session
    driver_id = upsert_driver(test_db, "Test Driver")
    summary = {
        "csv_path": "/tmp/telemetry_upload_xyz/OK_R3.csv",
        "session_meta": {"session_type": "practice", "track_state": "dry"},
        "session_context": None,
        "score_result": {},
        "lap_times": [60.0],
        "resampled_laps": {},
    }
    session_id = upsert_session(test_db, summary, driver_id)
    test_db.commit()
    row = test_db.execute(
        "SELECT csv_filename, display_name, source_filename, source_path FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    assert row["csv_filename"] == "OK_R3.csv", f"Expected just filename, got {row['csv_filename']}"
    assert row["display_name"] == "OK_R3"
    assert row["source_filename"] == "OK_R3.csv"
    assert "/tmp/" in row["source_path"]
