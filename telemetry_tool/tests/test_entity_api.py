"""Tests for /api/v1/ entity endpoints — drivers and tracks."""
import json
import sqlite3

import pytest

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Alice')")
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Bob')")
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES ('trk1', 'Spa', 7004.0)"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date) "
        "VALUES ('s1', 'test.csv', 1, 'trk1', '2026-01-01')"
    )
    conn.commit()
    return conn


@pytest.fixture
def client(db):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    os.environ.setdefault("TELEMETRY_DB_PATH", ":memory:")
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    import web.routes.api_v1_entities as ent
    ent._get_conn = lambda: db
    with app.test_client() as c:
        yield c


def test_list_drivers(client):
    resp = client.get("/api/v1/drivers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    drivers = data["data"]
    assert len(drivers) >= 2
    names = [d["name"] for d in drivers]
    assert "Alice" in names
    assert "Bob" in names


def test_get_driver_detail(client):
    resp = client.get("/api/v1/drivers/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["name"] == "Alice"


def test_get_driver_not_found(client):
    resp = client.get("/api/v1/drivers/9999")
    assert resp.status_code == 404


def test_patch_driver(client):
    resp = client.patch("/api/v1/drivers/1", json={"notes": "Fast driver"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["notes"] == "Fast driver"


def test_list_tracks(client):
    resp = client.get("/api/v1/tracks")
    assert resp.status_code == 200
    data = resp.get_json()
    tracks = data["data"]
    assert len(tracks) >= 1
    assert tracks[0]["name"] == "Spa"


def test_get_track_detail(client):
    resp = client.get("/api/v1/tracks/trk1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["name"] == "Spa"
    assert data["data"]["session_count"] >= 1


def test_list_drivers_has_enriched_fields(client, db):
    """List should include has_profile, style_label, total_laps."""
    resp = client.get("/api/v1/drivers")
    assert resp.status_code == 200
    drivers = resp.get_json()["data"]
    alice = next(d for d in drivers if d["name"] == "Alice")
    assert "has_profile" in alice
    assert "style_label" in alice
    assert "total_laps" in alice
    assert isinstance(alice["has_profile"], bool)
    assert isinstance(alice["total_laps"], int)


def test_get_track_not_found(client):
    resp = client.get("/api/v1/tracks/nonexistent")
    assert resp.status_code == 404
