"""Tests for weekends, leaderboard, and dev-plans entity APIs."""
import sqlite3

import pytest

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Alice')")
    conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Spa', 7004)")
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date, best_lap_time_s, total_score) "
        "VALUES ('s1', 'test.csv', 1, 't1', '2026-01-01', 88.5, 75.0)"
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


# ── Weekends ──────────────────────────────────────────────────

def test_list_weekends_empty(client):
    resp = client.get("/api/v1/weekends")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"weekends": []}


def test_create_weekend(client):
    resp = client.post("/api/v1/weekends", json={
        "name": "Spa Weekend", "track_id": "t1",
        "start_date": "2026-03-01", "end_date": "2026-03-02"
    })
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Spa Weekend"
    assert data["id"] > 0


def test_create_weekend_missing_name(client):
    resp = client.post("/api/v1/weekends", json={"track_id": "t1"})
    assert resp.status_code == 400


def test_get_weekend_detail(client, db):
    db.execute(
        "INSERT INTO weekends (name, track_id, start_date, end_date) "
        "VALUES ('W1', 't1', '2026-03-01', '2026-03-02')"
    )
    db.commit()
    wid = db.execute("SELECT weekend_id FROM weekends WHERE name='W1'").fetchone()["weekend_id"]
    resp = client.get(f"/api/v1/weekends/{wid}")
    assert resp.status_code == 200


def test_delete_weekend(client, db):
    db.execute(
        "INSERT INTO weekends (name, track_id, start_date, end_date) "
        "VALUES ('W2', 't1', '2026-04-01', '2026-04-02')"
    )
    db.commit()
    wid = db.execute("SELECT weekend_id FROM weekends WHERE name='W2'").fetchone()["weekend_id"]
    resp = client.delete(f"/api/v1/weekends/{wid}")
    assert resp.status_code == 200


# ── Leaderboard ──────────────────────────────────────────────

def test_leaderboard(client):
    resp = client.get("/api/v1/leaderboard")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) >= 1
    assert data[0]["driver_name"] == "Alice"


def test_leaderboard_with_track_filter(client):
    resp = client.get("/api/v1/leaderboard?track_id=t1")
    assert resp.status_code == 200


# ── Dev Plans ────────────────────────────────────────────────

def test_list_dev_plans_empty(client):
    resp = client.get("/api/v1/dev-plans")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []
