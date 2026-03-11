"""Tests for /api/v1/karts entity endpoints."""
import sqlite3

import pytest

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Test')")
    conn.execute("INSERT INTO karts (kart_name, manufacturer) VALUES ('K1', 'Tony Kart')")
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


def test_list_karts(client):
    resp = client.get("/api/v1/karts")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["name"] == "K1"


def test_create_kart(client):
    resp = client.post("/api/v1/karts", json={"name": "K2", "manufacturer": "CRG"})
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "K2"
    assert data["id"] > 0


def test_create_kart_missing_name(client):
    resp = client.post("/api/v1/karts", json={"manufacturer": "CRG"})
    assert resp.status_code == 400


def test_get_kart_detail(client):
    resp = client.get("/api/v1/karts/1")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["name"] == "K1"


def test_patch_kart(client):
    resp = client.patch("/api/v1/karts/1", json={"notes": "Primary kart"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["notes"] == "Primary kart"


def test_delete_kart_no_sessions(client):
    resp = client.delete("/api/v1/karts/1")
    assert resp.status_code == 200


def test_delete_kart_with_sessions_unlinks(client, db):
    """Karts linked to sessions are deleted; sessions get kart_id set to NULL."""
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date, kart_id) "
        "VALUES ('s1', 'test.csv', 1, '2026-01-01', 1)"
    )
    db.commit()
    resp = client.delete("/api/v1/karts/1")
    assert resp.status_code == 200
    # Session still exists but kart_id is unlinked
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id = 's1'").fetchone()
    assert row is not None
    assert row["kart_id"] is None


def test_delete_kart_not_found(client):
    resp = client.delete("/api/v1/karts/9999")
    assert resp.status_code == 404
