"""Tests that upload populates identity fields and API exposes them correctly."""
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.migrate import ensure_schema


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    conn.execute("""
        INSERT INTO tracks (track_id, track_name, lap_length_m)
        VALUES ('adria-karting', 'Adria Karting', 1200.0)
    """)
    conn.execute("""
        INSERT INTO sessions (session_id, csv_filename, driver_id,
                              session_type, track_state, session_date,
                              display_name, source_filename, source_path)
        VALUES ('test-001', 'OK_R3.csv', 1, 'practice', 'dry', '2026-03-01',
                'OK_R3', 'OK_R3.csv', '/tmp/telemetry_upload_xyz/OK_R3.csv')
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def client(test_db):
    # Set env var BEFORE importing create_app so Config picks it up.
    old_val = os.environ.get("TELEMETRY_DB_PATH")
    os.environ["TELEMETRY_DB_PATH"] = test_db
    os.environ.pop("USE_PG", None)

    # Import fresh — config reads env at class body time.
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    # Also override DB_PATH in app config directly.
    app.config["DB_PATH"] = test_db

    yield app.test_client()

    # Restore
    if old_val is None:
        os.environ.pop("TELEMETRY_DB_PATH", None)
    else:
        os.environ["TELEMETRY_DB_PATH"] = old_val


def test_session_detail_never_exposes_source_path(client):
    resp = client.get("/api/v1/sessions/test-001")
    body = resp.get_json()
    assert body["ok"] is True, f"API returned error: {body}"
    data = body["data"]
    assert "source_path" not in data, "source_path must never be in API response"
    assert "html_report_path" not in data, "html_report_path must not be in API response"


def test_csv_filename_is_just_filename(client):
    resp = client.get("/api/v1/sessions/test-001")
    body = resp.get_json()
    assert body["ok"] is True, f"API returned error: {body}"
    data = body["data"]
    fn = data.get("csv_filename", "")
    assert "/" not in fn, f"csv_filename should not contain /: {fn}"
    assert "\\" not in fn, f"csv_filename should not contain \\: {fn}"


def test_patch_session_display_name(client):
    resp = client.patch(
        "/api/v1/sessions/test-001",
        data=json.dumps({"display_name": "My Best Session"}),
        content_type="application/json",
    )
    body = resp.get_json()
    assert body["ok"] is True, f"PATCH returned error: {body}"
    # Verify it stuck
    resp2 = client.get("/api/v1/sessions/test-001")
    body2 = resp2.get_json()
    assert body2["data"].get("display_name") == "My Best Session"


def test_patch_session_track_id(client):
    resp = client.patch(
        "/api/v1/sessions/test-001",
        data=json.dumps({"track_id": "adria-karting"}),
        content_type="application/json",
    )
    body = resp.get_json()
    assert body["ok"] is True, f"PATCH returned error: {body}"
