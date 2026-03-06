"""Checkpoint 2 integration: entity APIs work end-to-end after upload.

Verifies ALL checkpoint 2 requirements:
  - Entity list endpoints (drivers, tracks, karts) return populated data
  - Session PATCH persists changes and returns resolved names
  - Leaderboard returns data
  - Weekends returns clean empty state
  - No 404s on any entity endpoint
"""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.migrate import ensure_schema


@pytest.fixture
def seeded_db():
    """In-memory SQLite with schema + seed data for integration tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Alice')")
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES ('t1', 'Spa', 7004)"
    )
    conn.execute(
        "INSERT INTO karts (kart_name, manufacturer) VALUES ('K1', 'Tony Kart')"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "session_date, best_lap_time_s, total_score, kart_id) "
        "VALUES ('s1', 'test.csv', 1, 't1', '2026-01-01', 88.5, 75.0, 1)"
    )
    conn.commit()
    return conn


@pytest.fixture
def client(seeded_db):
    """Flask test client with seeded DB wired into all route modules."""
    from flask import Flask
    from web.routes.data_v2 import bp as data_bp
    from web.routes.api_v1_entities import bp as entities_bp
    import web.routes.api_v1_entities as ent_mod
    import web.routes.data_v2 as dv2_mod
    import web.db as db_mod

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(data_bp)
    app.register_blueprint(entities_bp)

    # Wire all connection paths to the seeded in-memory DB.
    _orig_ent_get_conn = ent_mod._get_conn
    _orig_db_get_conn = db_mod.get_db_connection

    ent_mod._get_conn = lambda: seeded_db
    db_mod.get_db_connection = lambda *a, **kw: seeded_db
    # data_v2 imports get_db_connection at module level, so also patch
    # the module-level reference used inside route handlers.
    dv2_mod.get_db_connection = lambda *a, **kw: seeded_db

    with app.test_client() as c:
        yield c

    # Restore originals (good hygiene for test isolation).
    ent_mod._get_conn = _orig_ent_get_conn
    db_mod.get_db_connection = _orig_db_get_conn


# ══════════════════════════════════════════════════════════════════
# Entity list endpoints return populated data
# ══════════════════════════════════════════════════════════════════


def test_drivers_list_populated(client):
    resp = client.get("/api/v1/drivers")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["session_count"] >= 1


def test_tracks_list_populated(client):
    resp = client.get("/api/v1/tracks")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["session_count"] >= 1


def test_karts_list_populated(client):
    resp = client.get("/api/v1/karts")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["session_count"] >= 1


# ══════════════════════════════════════════════════════════════════
# Session PATCH persists and returns resolved names
# ══════════════════════════════════════════════════════════════════


def test_session_patch_persists(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"display_name": "My Race"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["display_name"] == "My Race"


def test_session_patch_returns_resolved_names(client):
    resp = client.patch(
        "/api/v1/sessions/s1",
        json={"notes": "good session"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    # The PATCH response must include JOINed driver_name and track_name.
    assert "driver_name" in data
    assert data["driver_name"] == "Alice"
    assert "track_name" in data
    assert data["track_name"] == "Spa"


# ══════════════════════════════════════════════════════════════════
# Leaderboard returns data
# ══════════════════════════════════════════════════════════════════


def test_leaderboard_returns_data(client):
    resp = client.get("/api/v1/leaderboard")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    # Each entry should include driver_name from the JOIN.
    assert "driver_name" in data[0]


# ══════════════════════════════════════════════════════════════════
# Weekends returns clean empty state
# ══════════════════════════════════════════════════════════════════


def test_weekends_empty_state(client):
    resp = client.get("/api/v1/weekends")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


# ══════════════════════════════════════════════════════════════════
# No 404s for any entity endpoint
# ══════════════════════════════════════════════════════════════════


def test_no_404s_for_entity_endpoints(client):
    """All entity list endpoints return 200, not 404."""
    for path in [
        "/api/v1/drivers",
        "/api/v1/tracks",
        "/api/v1/karts",
        "/api/v1/weekends",
        "/api/v1/leaderboard",
        "/api/v1/dev-plans",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
