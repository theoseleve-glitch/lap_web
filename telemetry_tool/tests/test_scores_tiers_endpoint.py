import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _seed(conn):
    # Full schema: get_scores -> get_session_by_id JOINs beyond phase-1 (karts).
    from db.schema import ALL_TABLES
    for _, sql in ALL_TABLES:
        conn.execute(sql)
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1,'X')")
    conn.execute("INSERT INTO sessions (session_id, csv_filename, driver_id, session_date, "
                 "track_state, total_score, grade) VALUES "
                 "('s1','f.csv',1,'2026-07-02','dry',80.0,'A')")
    conn.execute("INSERT INTO score_details (session_id, pace_score, pace_max, "
                 "consistency_score, consistency_max, execution_score, execution_max, "
                 "robustness_score, robustness_max, adaptation_score, strengths_json, weaknesses_json) "
                 "VALUES ('s1',20,25,15,25,18,20,12,15,15,'[]','[]')")


@pytest.fixture
def client(monkeypatch):
    from flask import Flask
    from web.routes.data_v2 import bp
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed(conn)
    monkeypatch.setattr("web.routes.data_v2.get_db_connection", lambda: conn)
    monkeypatch.setattr("web.routes.data_v2.chart_cached", lambda **k: (lambda f: f), raising=False)
    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/api/v1")
    return app.test_client(), conn


def test_zero_feeling_absolute_equals_today(client):
    c, _ = client
    data = json.loads(c.get("/api/v1/sessions/s1/scores").data)["data"]
    # Existing fields intact
    assert data["pace_score"] == 20
    assert data["available"] is True
    # New tiers, absolute == persisted
    assert data["tiers"]["absolute"]["total_score"] == 80.0
    assert data["tiers"]["contextualized"]["total_score"] == 80.0
    assert data["tiers"]["competition"] is None
    assert data["tiers"]["reflection_present"] is False


def test_dnf_reflection_changes_contextual_and_adds_competition(client):
    c, conn = client
    from web.repos.reflection_repo import upsert_reflection, replace_competitors
    upsert_reflection(conn, "s1", {"result_tags": ["dnf"], "race_position": 3,
                                   "race_total_competitors": 12, "race_is_dnf": True})
    replace_competitors(conn, "s1", [{"competitor_name": "A", "final_position": 1}])
    conn.commit()
    data = json.loads(c.get("/api/v1/sessions/s1/scores").data)["data"]
    assert data["tiers"]["contextualized"]["total_score"] == 68.0
    assert data["tiers"]["competition"]["is_dnf"] is True
    assert data["tiers"]["reflection_present"] is True
    assert any(a["code"] == "DNF_ROBUSTNESS_ZERO"
               for a in data["tiers"]["contextualized"]["adjustments"])
