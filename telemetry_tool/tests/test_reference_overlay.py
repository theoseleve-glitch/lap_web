"""Tests for cross-session reference overlay endpoints."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def seeded_client_with_ref(seeded_db):
    """Flask test client backed by a seeded SQLite DB with an extra reference session."""
    from web.app import create_app

    conn = seeded_db
    # seeded_db already has track 't1' (TestTrack) and sessions s1/s2 with track_id='t1'
    # Insert a third session on the same track owned by a different driver
    import uuid
    second_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO sessions (session_id, csv_filename, driver_id, track_id,
           session_date, n_laps, best_lap_time_s, session_type, track_state)
           VALUES (?, 'ref.csv', 2, 't1', '2026-04-10', 12, 44.8, 'practice', 'dry')""",
        (second_id,),
    )
    conn.execute(
        """INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid)
           VALUES (?, 1, 44.8, 1)""",
        (second_id,),
    )
    conn.commit()

    app = create_app()
    app.config["TESTING"] = True

    with patch("web.routes.data_v2.get_db_connection", return_value=conn):
        with app.test_client() as client:
            yield client, second_id


def test_reference_candidates_returns_same_track_sessions(seeded_client_with_ref):
    client, second_id = seeded_client_with_ref
    resp = client.get("/api/v1/sessions/s1/reference-candidates")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    candidates = body["data"]
    candidate_ids = [c["session_id"] for c in candidates]
    # The newly inserted session (second_id) should appear
    assert second_id in candidate_ids
    # The queried session itself must be excluded
    assert "s1" not in candidate_ids
    match = next(c for c in candidates if c["session_id"] == second_id)
    assert match["driver_name"] == "RivalDriver"
    assert match["best_lap_time_s"] == 44.8


def test_reference_candidates_excludes_self(seeded_client_with_ref):
    client, second_id = seeded_client_with_ref
    resp = client.get("/api/v1/sessions/s1/reference-candidates")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = [c["session_id"] for c in body["data"]]
    assert "s1" not in ids


def test_reference_candidates_404_for_unknown_session(seeded_client_with_ref):
    client, _ = seeded_client_with_ref
    resp = client.get("/api/v1/sessions/nonexistent/reference-candidates")
    assert resp.status_code == 404


def test_reference_candidates_limit_param(seeded_client_with_ref):
    client, _ = seeded_client_with_ref
    resp = client.get("/api/v1/sessions/s1/reference-candidates?limit=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["data"]) <= 1


def test_reference_candidates_response_fields(seeded_client_with_ref):
    client, second_id = seeded_client_with_ref
    resp = client.get("/api/v1/sessions/s1/reference-candidates")
    assert resp.status_code == 200
    body = resp.get_json()
    candidates = body["data"]
    assert len(candidates) >= 1
    for c in candidates:
        assert "session_id" in c
        assert "driver_name" in c
        assert "session_date" in c
        assert "best_lap_time_s" in c
        assert "n_laps" in c
        assert "session_type" in c
