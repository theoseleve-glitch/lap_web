"""Test upload flow with optional kart_id."""
import sqlite3
import pytest
from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Unknown')")
    conn.execute("INSERT INTO karts (kart_name) VALUES ('TestKart')")
    conn.commit()
    return conn


def test_upload_meta_includes_kart_id(db):
    """When kart_id is in session_meta, upsert_session stores it."""
    from web.models import upsert_session
    summary = {
        "csv_path": "test.csv",
        "session_meta": {
            "session_id": "test-upload-kart",
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "Unknown",
            "kart_id": 1,
        },
    }
    sid = upsert_session(db, summary, 1)
    db.commit()
    row = db.execute(
        "SELECT kart_id FROM sessions WHERE session_id = :sid",
        {"sid": sid},
    ).fetchone()
    assert row["kart_id"] == 1


def test_upload_meta_without_kart_id(db):
    """When kart_id is not in session_meta, kart_id is NULL."""
    from web.models import upsert_session
    summary = {
        "csv_path": "test2.csv",
        "session_meta": {
            "session_id": "test-upload-no-kart",
            "session_type": "practice",
            "track_state": "dry",
            "driver_name": "Unknown",
        },
    }
    sid = upsert_session(db, summary, 1)
    db.commit()
    row = db.execute(
        "SELECT kart_id FROM sessions WHERE session_id = :sid",
        {"sid": sid},
    ).fetchone()
    assert row["kart_id"] is None
