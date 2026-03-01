"""Tests that optional data endpoints return structured unavailability, not 404/500.

A session exists with no computed data (no laps, no scores, no GPS traces, etc.).
Each endpoint that serves computed data should return 200 + available:false + reason_code
instead of 404 when the session is real but the data was not generated.

Run:
    pytest telemetry_tool/tests/test_structured_unavailability.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

BARE_SESSION = "bare-sess-001"


@pytest.fixture
def bare_db(test_db):
    """A database with one session that has NO computed data at all."""
    conn = test_db
    conn.execute(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (99, 'BareDriver')"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
        "track_state, session_date) "
        "VALUES (?, 'bare.csv', 99, 'practice', 'dry', '2026-03-01')",
        (BARE_SESSION,),
    )
    conn.commit()
    return conn


@pytest.fixture
def bare_client(bare_db):
    """Flask test client backed by a bare session DB (no computed data)."""
    from web.app import create_app

    app = create_app()
    app.config["TESTING"] = True

    with patch("web.routes.data_v2.get_db_connection", return_value=bare_db):
        with app.test_client() as client:
            yield client


# ── Structured unavailability contract ───────────────────────────


_UNAVAILABLE_ENDPOINTS = [
    f"/api/v1/sessions/{BARE_SESSION}/theoretical",
    f"/api/v1/sessions/{BARE_SESSION}/reference_line",
    f"/api/v1/sessions/{BARE_SESSION}/fingerprint",
    f"/api/v1/sessions/{BARE_SESSION}/driving-style",
    f"/api/v1/sessions/{BARE_SESSION}/lap-distribution",
    f"/api/v1/sessions/{BARE_SESSION}/lap-progress",
    f"/api/v1/sessions/{BARE_SESSION}/stint-analysis",
    f"/api/v1/sessions/{BARE_SESSION}/best_lap_gps",
    f"/api/v1/sessions/{BARE_SESSION}/speed-profile",
    f"/api/v1/sessions/{BARE_SESSION}/track-map",
]


@pytest.mark.parametrize("path", _UNAVAILABLE_ENDPOINTS)
def test_missing_computed_data_returns_structured_unavailability(bare_client, path):
    """Endpoint returns 200 + ok:true + data.available:false + reason_code."""
    resp = bare_client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}"
    body = resp.get_json()
    assert body["ok"] is True, f"{path} returned ok:false — body: {body}"
    assert body["data"]["available"] is False, f"{path} missing available:false"
    assert "reason_code" in body["data"], f"{path} missing reason_code"


# ── True 404 still works ────────────────────────────────────────


_404_ENDPOINTS = [
    "/api/v1/sessions/does-not-exist/theoretical",
    "/api/v1/sessions/does-not-exist/reference_line",
    "/api/v1/sessions/does-not-exist/fingerprint",
    "/api/v1/sessions/does-not-exist/driving-style",
    "/api/v1/sessions/does-not-exist/lap-distribution",
    "/api/v1/sessions/does-not-exist/lap-progress",
    "/api/v1/sessions/does-not-exist/stint-analysis",
]


@pytest.mark.parametrize("path", _404_ENDPOINTS)
def test_nonexistent_session_still_returns_404(bare_client, path):
    """When the session itself does not exist, we still get a proper 404."""
    resp = bare_client.get(path)
    assert resp.status_code == 404, f"{path} returned {resp.status_code}"
    body = resp.get_json()
    assert body["ok"] is False, f"{path} should have ok:false"
