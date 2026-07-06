import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def client(monkeypatch):
    from flask import Flask
    from web.routes.data_v2 import bp
    from db.schema import ALL_TABLES

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Full schema: the route's models.get_session_by_id JOINs beyond phase-1
    # (e.g. karts/tracks), so PHASE_1_TABLES alone is insufficient here.
    for _, sql in ALL_TABLES:
        conn.execute(sql)
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1,'X')")
    conn.execute("INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
                 "VALUES ('s1','f.csv',1,'2026-07-02')")

    monkeypatch.setattr("web.routes.data_v2.get_db_connection", lambda: conn)
    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/api/v1")
    return app.test_client()


def test_reflection_saves_feeling_and_competitors(client):
    r = client.post("/api/v1/sessions/s1/reflection", json={
        "result_tags": ["traffic", "completed"],
        "driver_perceived_conditions": "damp",
        "felt_performance_rating": 8,
        "race_position": 4, "race_total_competitors": 15,
        "competitors": [{"competitor_name": "Rival A", "final_position": 3,
                         "gap_to_this_driver_s": 0.9, "notes": "close"}],
    })
    assert r.status_code == 200
    body = json.loads(r.data)["data"]
    assert body["saved"] is True
    assert body["competitors"] == 1


def test_reflection_rejects_unknown_tag(client):
    r = client.post("/api/v1/sessions/s1/reflection", json={"result_tags": ["banana"]})
    assert r.status_code == 400


def test_reflection_rejects_bad_rating(client):
    r = client.post("/api/v1/sessions/s1/reflection", json={"felt_performance_rating": 99})
    assert r.status_code == 400


def test_reflection_404_unknown_session(client):
    r = client.post("/api/v1/sessions/nope/reflection", json={"result_tags": []})
    assert r.status_code == 404
