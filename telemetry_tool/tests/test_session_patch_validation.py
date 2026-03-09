"""Tests for session PATCH validation and kart_id support.

Validates:
  - Enum checks for session_type and track_state
  - FK existence checks for driver_id, track_id, kart_id
  - Date format check for session_date
  - String length checks for display_name and notes
  - kart_id linking and unlinking
  - kart_name resolved in session response via LEFT JOIN
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.migrate import ensure_schema


@pytest.fixture
def db():
    """In-memory SQLite with full schema, one driver, one session, one kart."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('TestDriver')")
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES ('t1', 'TestTrack', 1000.0)"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
        "VALUES ('s1', 'test.csv', 1, '2026-01-01')"
    )
    conn.execute("INSERT INTO karts (kart_name) VALUES ('TestKart')")
    conn.commit()
    return conn


@pytest.fixture
def client(db):
    """Flask test client wired to the in-memory DB."""
    import os
    os.environ["TELEMETRY_DB_PATH"] = ":memory:"
    os.environ.pop("USE_PG", None)

    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    # Monkey-patch get_db_connection in data_v2 to return our fixture DB.
    import web.routes.data_v2 as dv2
    _orig = dv2.get_db_connection
    dv2.get_db_connection = lambda: db

    with app.test_client() as c:
        yield c

    dv2.get_db_connection = _orig


# ══════════════════════════════════════════════════════════════════
# Enum validation — session_type
# ══════════════════════════════════════════════════════════════════

def test_patch_rejects_invalid_session_type(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"session_type": "banana"},
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_patch_accepts_valid_session_types(client):
    for stype in ("practice", "qualifying", "race", "test"):
        resp = client.patch(
            "/api/v1/sessions/s1",
            json={"session_type": stype},
            content_type="application/json",
        )
        assert resp.status_code == 200, f"session_type={stype!r} should be accepted"


# ══════════════════════════════════════════════════════════════════
# Enum validation — track_state
# ══════════════════════════════════════════════════════════════════

def test_patch_rejects_invalid_track_state(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"track_state": "snowy"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_accepts_valid_track_states(client):
    for state in ("dry", "wet", "damp", "mixed"):
        resp = client.patch(
            "/api/v1/sessions/s1",
            json={"track_state": state},
            content_type="application/json",
        )
        assert resp.status_code == 200, f"track_state={state!r} should be accepted"


# ══════════════════════════════════════════════════════════════════
# FK existence — driver_id
# ══════════════════════════════════════════════════════════════════

def test_patch_rejects_nonexistent_driver_id(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"driver_id": 9999},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_accepts_valid_driver_id(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"driver_id": 1},
        content_type="application/json",
    )
    assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════
# FK existence — track_id
# ══════════════════════════════════════════════════════════════════

def test_patch_rejects_nonexistent_track_id(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"track_id": "nonexistent_track"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_accepts_valid_track_id(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"track_id": "t1"},
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_patch_accepts_null_track_id(client):
    """Setting track_id to null unlinks the track."""
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"track_id": None},
        content_type="application/json",
    )
    assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════
# FK existence — kart_id
# ══════════════════════════════════════════════════════════════════

def test_patch_rejects_nonexistent_kart_id(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"kart_id": 9999},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_accepts_valid_kart_id(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"kart_id": 1},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True


def test_patch_accepts_null_kart_id(client):
    """Setting kart_id to null unlinks the kart."""
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"kart_id": None},
        content_type="application/json",
    )
    assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════
# Date format — session_date
# ══════════════════════════════════════════════════════════════════

def test_patch_validates_session_date_format(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"session_date": "not-a-date"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_rejects_partial_date(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"session_date": "2026-3-1"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_accepts_valid_session_date(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"session_date": "2026-03-15"},
        content_type="application/json",
    )
    assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════
# String length — display_name and notes
# ══════════════════════════════════════════════════════════════════

def test_patch_rejects_display_name_too_long(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"display_name": "x" * 201},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_accepts_display_name_at_limit(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"display_name": "x" * 200},
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_patch_rejects_notes_too_long(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"notes": "n" * 2001},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_accepts_notes_at_limit(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"notes": "n" * 2000},
        content_type="application/json",
    )
    assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════
# Multiple validation errors returned at once
# ══════════════════════════════════════════════════════════════════

def test_patch_returns_all_errors_at_once(client):
    """Validation collects all errors, not just the first."""
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"session_type": "bad", "track_state": "snowy", "kart_id": 9999},
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    details = data["error"].get("details", [])
    # Should have at least 3 distinct errors
    assert len(details) >= 3


# ══════════════════════════════════════════════════════════════════
# kart_name resolved in response via JOIN
# ══════════════════════════════════════════════════════════════════

def test_patch_response_includes_kart_name(client, db):
    """After linking a kart, the re-fetched session includes kart_name."""
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"kart_id": 1},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"].get("kart_name") == "TestKart"


def test_session_detail_includes_kart_name(client, db):
    """GET session detail includes kart_name when kart_id is set."""
    # First link a kart
    db.execute("UPDATE sessions SET kart_id = 1 WHERE session_id = 's1'")
    db.commit()

    resp = client.get("/api/v1/sessions/s1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"].get("kart_name") == "TestKart"
