"""Tests for cross-session reference overlay endpoints."""
from __future__ import annotations

import json
import math
import sys
import uuid
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


# ── Fixtures for reference-data endpoint tests ────────────────────────────────


def _insert_gps_trace(conn, session_id, lap_number, n_points=100, lap_length=1000.0):
    """Insert a synthetic GPS trace row for the given session/lap."""
    distances = [i * lap_length / n_points for i in range(n_points)]
    speeds = [20.0 + 5.0 * math.sin(2 * math.pi * d / lap_length) for d in distances]
    latitudes = [45.0 + 0.001 * math.cos(2 * math.pi * d / lap_length) for d in distances]
    longitudes = [7.0 + 0.002 * math.sin(2 * math.pi * d / lap_length) for d in distances]
    accel_lat = [1.5 * math.sin(4 * math.pi * d / lap_length) for d in distances]
    accel_long = [0.8 * math.cos(4 * math.pi * d / lap_length) for d in distances]
    conn.execute(
        "INSERT INTO gps_traces (session_id, lap_number, "
        "latitudes_json, longitudes_json, distances_json, speeds_json, "
        "accel_lat_json, accel_long_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, lap_number,
            json.dumps(latitudes), json.dumps(longitudes),
            json.dumps(distances), json.dumps(speeds),
            json.dumps(accel_lat), json.dumps(accel_long),
        ),
    )


@pytest.fixture
def two_sessions_same_track(seeded_db):
    """Yield (primary_session_id, reference_session_id, conn).

    primary is 's1' (from seeded_db, already has GPS trace for lap 1).
    reference is a new session on the same track with GPS trace for lap 1.
    """
    conn = seeded_db
    second_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO sessions (session_id, csv_filename, driver_id, track_id,
           session_date, n_laps, best_lap_time_s, session_type, track_state)
           VALUES (?, 'ref2.csv', 2, 't1', '2026-04-10', 10, 44.8, 'practice', 'dry')""",
        (second_id,),
    )
    conn.execute(
        "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) "
        "VALUES (?, 1, 44.8, 1)",
        (second_id,),
    )
    _insert_gps_trace(conn, second_id, 1)
    conn.commit()
    yield "s1", second_id, conn


@pytest.fixture
def client(seeded_db):
    """Flask test client patched to use the seeded in-memory DB."""
    from web.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with patch("web.routes.data_v2.get_db_connection", return_value=seeded_db):
        with app.test_client() as c:
            yield c


# ── reference-data endpoint tests ─────────────────────────────────────────────


def test_reference_data_returns_aligned_composite(client, two_sessions_same_track):
    existing_id, second_id, _ = two_sessions_same_track
    resp = client.get(
        f"/api/v1/sessions/{existing_id}/reference-data"
        f"?ref_session={second_id}&ref_lap=1&primary_lap=1"
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    d = body["data"]
    assert "distances" in d
    assert "speed" in d
    assert "gps" in d
    assert "gg" in d
    assert "primary" in d
    assert "reference" in d
    dists = d["distances"]
    assert len(dists) > 0
    assert dists == sorted(dists)
    n = len(dists)
    assert len(d["speed"]["primary"]) == n
    assert len(d["speed"]["reference"]) == n
    assert len(d["speed"]["delta_s"]) == n
    assert len(d["gps"]["primary"]["latitudes"]) == n
    assert len(d["gps"]["reference"]["latitudes"]) == n
    assert len(d["gg"]["primary"]["accel_lat"]) == n
    assert len(d["gg"]["reference"]["accel_lat"]) == n
    assert d["reference"]["session_id"] == second_id


def test_reference_data_missing_ref_session_returns_400(client, two_sessions_same_track):
    existing_id, _, _ = two_sessions_same_track
    resp = client.get(
        f"/api/v1/sessions/{existing_id}/reference-data?ref_lap=1&primary_lap=1"
    )
    assert resp.status_code == 400


def test_reference_data_cross_track_returns_400(client, seeded_db):
    conn = seeded_db
    other_id = str(uuid.uuid4())
    conn.execute(
        "INSERT OR IGNORE INTO tracks (track_id, track_name) "
        "VALUES ('other_track', 'Other Track')"
    )
    conn.execute(
        """INSERT INTO sessions (session_id, csv_filename, driver_id, track_id,
           session_date, n_laps, best_lap_time_s, session_type)
           VALUES (?, 'other.csv', 1, 'other_track', '2026-04-10', 5, 50.0, 'practice')""",
        (other_id,),
    )
    conn.commit()
    existing_id = conn.execute(
        "SELECT session_id FROM sessions WHERE track_id != 'other_track' LIMIT 1"
    ).fetchone()["session_id"]
    resp = client.get(
        f"/api/v1/sessions/{existing_id}/reference-data"
        f"?ref_session={other_id}&ref_lap=1&primary_lap=1"
    )
    assert resp.status_code == 400
    assert "track" in resp.get_json()["error"]["message"].lower()
