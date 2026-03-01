"""Parametrized API contract tests — verify response shape for all key endpoints.

Each test checks:
1. HTTP 200 status code
2. JSON envelope has ``ok: true``
3. ``data`` key exists in response
4. Expected keys are present inside ``data``

Uses mocked DB connections and model functions to isolate shape validation
from actual data fetching.
"""
import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask

from web.api_utils import api_response, init_request_id
from web.routes.api_v1_data import bp as api_v1_data_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_app():
    """Create a minimal Flask app with api_v1_data blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_v1_data_bp)
    return app


@pytest.fixture
def app():
    return _make_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_conn():
    """Return a mock DB connection with configurable execute results."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


# ---------------------------------------------------------------------------
# Mock data builders
# ---------------------------------------------------------------------------

_MOCK_SESSION = {
    "session_id": "s1",
    "csv_filename": "test.csv",
    "driver_id": 1,
    "driver_name": "TestDriver",
    "track_id": "t1",
    "track_name": "TestTrack",
    "session_type": "practice",
    "track_state": "dry",
    "session_date": "2024-01-01",
    "n_laps": 10,
    "best_lap_time_s": 60.0,
    "mean_lap_time_s": 61.5,
    "total_score": 75.0,
    "grade": "B",
    "kart_name": None,
    "notes": None,
}

_MOCK_LAPS = [
    {
        "lap_number": i,
        "lap_time_s": 60.0 + i * 0.3,
        "is_best": i == 1,
        "is_valid": True,
        "invalid_reason": None,
        "phase_id": None,
        "speed_mean_mps": 15.0,
        "speed_max_mps": 25.0,
        "braking_max_mps2": -8.0,
        "accel_max_mps2": 5.0,
    }
    for i in range(1, 11)
]

_MOCK_GPS = {
    "distances": [0.0, 10.0, 20.0, 30.0, 40.0],
    "speeds": [10.0, 15.0, 20.0, 18.0, 22.0],
    "latitudes": [45.0, 45.001, 45.002, 45.003, 45.004],
    "longitudes": [7.0, 7.001, 7.002, 7.003, 7.004],
    "accel_lat": [0.1, 0.2, -0.1, 0.3, -0.2],
    "accel_long": [0.5, -0.3, 0.2, -0.4, 0.1],
}

_MOCK_SCORE_DETAILS = {
    "pace_score": 18,
    "pace_max": 25,
    "consistency_score": 15,
    "consistency_max": 25,
    "execution_score": 20,
    "execution_max": 25,
    "robustness_score": 22,
    "robustness_max": 25,
    "strengths": ["braking"],
    "weaknesses": ["consistency"],
    "adaptation_score": 0.85,
}


# ---------------------------------------------------------------------------
# Contract test: endpoints that need session + laps + GPS
# ---------------------------------------------------------------------------

class TestSessionEndpointContracts:
    """Verify response shape for session-scoped data endpoints."""

    @pytest.mark.parametrize("endpoint,expected_keys", [
        # Speed trace: distances + speeds arrays
        ("/api/v1/sessions/s1/speed-trace", ["distances", "speeds"]),
        # GG scatter data: lat/lon G arrays
        ("/api/v1/sessions/s1/gg-data", ["lat_g", "lon_g", "per_lap", "n_points"]),
        # Energy balance: distance + kinetic + braking arrays
        ("/api/v1/sessions/s1/energy", ["distances", "kinetic_energy", "braking_energy"]),
        # Fatigue analysis: laps + fatigue index + reaction time
        ("/api/v1/sessions/s1/fatigue", ["laps", "fatigue_index", "reaction_time"]),
        # Workload: timestamps + steering + braking + throttle + total
        ("/api/v1/sessions/s1/workload", ["timestamps", "steering", "braking", "throttle", "total"]),
        # Speed profile: distances + best/avg/worst
        ("/api/v1/sessions/s1/speed-profile", ["distances", "best_lap", "average", "worst_lap"]),
        # GPS trace: lat/lon/speed
        ("/api/v1/sessions/s1/gps-trace", ["lat", "lon", "speed"]),
    ])
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    @patch("web.routes.api_v1_data.get_gps_trace")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers")
    def test_session_data_shape(
        self, mock_gps_laps, mock_gps, mock_laps, mock_session,
        mock_db, client, endpoint, expected_keys
    ):
        mock_db.return_value = _mock_conn()
        mock_session.return_value = _MOCK_SESSION
        mock_laps.return_value = _MOCK_LAPS
        mock_gps.return_value = _MOCK_GPS
        mock_gps_laps.return_value = [1, 2, 3]

        resp = client.get(endpoint)
        assert resp.status_code == 200, f"{endpoint}: expected 200, got {resp.status_code}"

        body = resp.get_json()
        assert body is not None, f"{endpoint}: response is not JSON"
        assert body["ok"] is True, f"{endpoint}: ok is not True"
        assert "data" in body, f"{endpoint}: missing 'data' key"
        assert "meta" in body, f"{endpoint}: missing 'meta' key"

        for key in expected_keys:
            assert key in body["data"], (
                f"{endpoint}: missing expected key '{key}' in data. "
                f"Got keys: {list(body['data'].keys())}"
            )


# ---------------------------------------------------------------------------
# Contract test: endpoints that need session + score details
# ---------------------------------------------------------------------------

class TestScoreEndpointContracts:
    """Verify response shape for score/style/fingerprint endpoints."""

    @pytest.mark.parametrize("endpoint,expected_keys", [
        # Fingerprint: metrics + strengths + weaknesses
        ("/api/v1/sessions/s1/fingerprint", ["metrics", "strengths", "weaknesses", "adaptation_score"]),
        # Driving style: labels + values (radar chart)
        ("/api/v1/sessions/s1/style", ["labels", "values"]),
    ])
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_score_details")
    @patch("web.routes.api_v1_data.get_driving_style")
    def test_score_shape(
        self, mock_style, mock_scores, mock_session,
        mock_db, client, endpoint, expected_keys
    ):
        mock_db.return_value = _mock_conn()
        mock_session.return_value = _MOCK_SESSION
        mock_scores.return_value = _MOCK_SCORE_DETAILS
        # Driving style returns None => falls back to score_details radar
        mock_style.return_value = None

        resp = client.get(endpoint)
        assert resp.status_code == 200, f"{endpoint}: expected 200, got {resp.status_code}"

        body = resp.get_json()
        assert body is not None, f"{endpoint}: response is not JSON"
        assert body["ok"] is True, f"{endpoint}: ok is not True"
        assert "data" in body, f"{endpoint}: missing 'data' key"

        for key in expected_keys:
            assert key in body["data"], (
                f"{endpoint}: missing expected key '{key}' in data. "
                f"Got keys: {list(body['data'].keys())}"
            )


# ---------------------------------------------------------------------------
# Contract test: session details (complex shape)
# ---------------------------------------------------------------------------

class TestSessionDetailsContract:
    """Verify the /details endpoint returns all expected fields."""

    EXPECTED_KEYS = [
        "id", "date", "track_name", "driver_name", "laps",
        "best_time", "mean_time", "score", "grade",
        "session_type", "track_state", "condition",
        "pace_score", "consistency_score", "execution_score", "robustness_score",
        "condition_phases", "data_health", "weather",
    ]

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_score_details")
    def test_details_shape(self, mock_scores, mock_session, mock_db, client):
        conn = _mock_conn()
        mock_db.return_value = conn
        mock_session.return_value = _MOCK_SESSION
        mock_scores.return_value = _MOCK_SCORE_DETAILS
        # condition_phases, data_health, weather queries return empty
        conn.execute.return_value.fetchall.return_value = []
        conn.execute.return_value.fetchone.return_value = None

        resp = client.get("/api/v1/sessions/s1/details")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "data" in body

        for key in self.EXPECTED_KEYS:
            assert key in body["data"], (
                f"/details: missing expected key '{key}'. "
                f"Got keys: {list(body['data'].keys())}"
            )


# ---------------------------------------------------------------------------
# Contract test: endpoints with DB-direct queries (corner-mastery, corners)
# ---------------------------------------------------------------------------

class TestCornerEndpointContracts:
    """Verify response shape for corner-related endpoints."""

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corner_mastery_shape(self, mock_db, client):
        """Corner mastery returns {corners: [...]}."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # Simulate corner_metrics query returning rows
        mock_row = MagicMock()
        mock_row.__iter__ = MagicMock(return_value=iter([]))
        row_dict = {
            "corner_id": 1,
            "lap_count": 5,
            "avg_entry_mps": 20.0,
            "avg_apex_mps": 15.0,
            "avg_exit_mps": 18.0,
            "avg_time_loss_ms": 50.0,
            "min_time_loss_ms": 30.0,
            "max_time_loss_ms": 80.0,
            "avg_grip_util": 0.9,
        }
        mock_row_obj = MagicMock()
        mock_row_obj.keys.return_value = row_dict.keys()
        mock_row_obj.__iter__ = MagicMock(return_value=iter(row_dict.items()))
        # Make dict(r) work
        type(mock_row_obj).__getitem__ = lambda self, key: row_dict[key]
        type(mock_row_obj).get = lambda self, key, default=None: row_dict.get(key, default)

        # Use a real dict-like row
        conn.execute.return_value.fetchall.return_value = [row_dict]

        resp = client.get("/api/v1/sessions/s1/corner-mastery")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "corners" in body["data"]

        # If corners are returned, verify sub-keys
        if body["data"]["corners"]:
            corner = body["data"]["corners"][0]
            for key in ["name", "score", "entry_speed", "apex_speed", "exit_speed"]:
                assert key in corner, f"corner missing key '{key}'"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corners_shape(self, mock_db, client):
        """Raw corners returns {corners: [...]}."""
        conn = _mock_conn()
        mock_db.return_value = conn

        row_dict = {
            "corner_id": 1,
            "avg_entry_speed_mps": 20.0,
            "avg_apex_speed_mps": 15.0,
            "avg_exit_speed_mps": 18.0,
        }
        conn.execute.return_value.fetchall.return_value = [row_dict]

        resp = client.get("/api/v1/sessions/s1/corners")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "corners" in body["data"]

        if body["data"]["corners"]:
            corner = body["data"]["corners"][0]
            for key in ["corner_id", "name", "entry_speed", "apex_speed", "exit_speed"]:
                assert key in corner, f"corner missing key '{key}'"


# ---------------------------------------------------------------------------
# Contract test: simple / stub endpoints
# ---------------------------------------------------------------------------

class TestSimpleEndpointContracts:
    """Verify shape for endpoints that return simple/static structures."""

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corner_replay_shape(self, mock_db, client):
        """Corner replay returns 404 when session not found (mock conn)."""
        mock_db.return_value = _mock_conn()

        resp = client.get("/api/v1/sessions/s1/corner-replay")
        assert resp.status_code == 404

        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_rival_gap_shape(self, mock_db, client):
        """Rival gap returns {lap_numbers, gap_seconds}."""
        mock_db.return_value = _mock_conn()

        resp = client.get("/api/v1/sessions/s1/rival-gap")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "lap_numbers" in body["data"]
        assert "gap_seconds" in body["data"]

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_setup_status_shape(self, mock_db, client):
        """Setup status returns {steps: [...]}."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # Make the count queries return a dict with cnt
        count_row = {"cnt": 3}
        conn.execute.return_value.fetchone.return_value = count_row

        resp = client.get("/api/v1/setup/status")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "steps" in body["data"]

        # Verify step sub-keys
        if body["data"]["steps"]:
            step = body["data"]["steps"][0]
            for key in ["id", "label", "status"]:
                assert key in step, f"step missing key '{key}'"


# ---------------------------------------------------------------------------
# Contract test: lap-related endpoints
# ---------------------------------------------------------------------------

class TestLapEndpointContracts:
    """Verify response shape for lap data endpoints."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_lap_times_shape(self, mock_laps, mock_db, client):
        """Lap times returns {laps: [...]}."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = _MOCK_LAPS

        resp = client.get("/api/v1/sessions/s1/lap-times")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "laps" in body["data"]

        if body["data"]["laps"]:
            lap = body["data"]["laps"][0]
            for key in ["lap_number", "lap_time_s", "is_best", "is_valid"]:
                assert key in lap, f"lap missing key '{key}'"

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers")
    def test_laps_gps_shape(self, mock_gps_laps, mock_db, client):
        """GPS laps returns {laps: [int, ...]}."""
        mock_db.return_value = _mock_conn()
        mock_gps_laps.return_value = [1, 2, 3]

        resp = client.get("/api/v1/sessions/s1/laps/gps")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "laps" in body["data"]
        assert isinstance(body["data"]["laps"], list)

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_consistency_shape(self, mock_laps, mock_db, client):
        """Consistency returns {laps, sectors, deltas}."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = _MOCK_LAPS

        resp = client.get("/api/v1/sessions/s1/consistency")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        for key in ["laps", "sectors", "deltas"]:
            assert key in body["data"], f"consistency missing key '{key}'"

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_trends_shape(self, mock_laps, mock_db, client):
        """Trends returns {distances, pace_delta, consistency_index}."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = _MOCK_LAPS

        resp = client.get("/api/v1/sessions/s1/trends")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        for key in ["distances", "pace_delta", "consistency_index"]:
            assert key in body["data"], f"trends missing key '{key}'"


# ---------------------------------------------------------------------------
# Contract test: pit-window (DB-direct queries)
# ---------------------------------------------------------------------------

class TestPitWindowContract:
    """Verify pit-window endpoint shape."""

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_pit_window_with_data(self, mock_db, client):
        """Pit window with data returns all expected keys."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # Simulate laps query returning rows
        lap_rows = [
            {"lap_number": i, "lap_time_s": 60.0 + i * 0.3}
            for i in range(1, 11)
        ]
        conn.execute.return_value.fetchall.return_value = lap_rows

        resp = client.get("/api/v1/sessions/s1/pit-window")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        for key in ["current_lap", "window_open", "window_close", "optimal_lap", "time_loss_per_lap"]:
            assert key in body["data"], f"pit-window missing key '{key}'"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_pit_window_empty(self, mock_db, client):
        """Pit window with no laps still returns all keys (null values)."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/v1/sessions/s1/pit-window")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        for key in ["current_lap", "window_open", "window_close", "optimal_lap", "time_loss_per_lap"]:
            assert key in body["data"], f"pit-window (empty) missing key '{key}'"


# ---------------------------------------------------------------------------
# Contract test: session badges
# ---------------------------------------------------------------------------

class TestBadgesContract:
    """Verify badges endpoint shape."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    def test_badges_shape(self, mock_session, mock_db, client):
        """Badges returns {session_id, badges, tags}."""
        conn = _mock_conn()
        mock_db.return_value = conn
        mock_session.return_value = _MOCK_SESSION
        conn.execute.return_value.fetchall.return_value = []

        resp = client.get("/api/v1/sessions/s1/badges")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        for key in ["session_id", "badges", "tags"]:
            assert key in body["data"], f"badges missing key '{key}'"


# ---------------------------------------------------------------------------
# Contract test: stints
# ---------------------------------------------------------------------------

class TestStintsContract:
    """Verify stints endpoint shape."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_stint_analysis")
    def test_stints_shape(self, mock_stints, mock_db, client):
        """Stints returns {stints: [...]}."""
        mock_db.return_value = _mock_conn()
        mock_stints.return_value = []

        resp = client.get("/api/v1/sessions/s1/stints")
        assert resp.status_code == 200

        body = resp.get_json()
        assert body["ok"] is True
        assert "stints" in body["data"]


# ---------------------------------------------------------------------------
# Contract test: envelope structure on all endpoints
# ---------------------------------------------------------------------------

class TestEnvelopeStructure:
    """Verify the standard {ok, data, meta} envelope on every endpoint."""

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/sessions/s1/laps/gps",
        "/api/v1/sessions/s1/lap-times",
        "/api/v1/sessions/s1/gg-data",
        "/api/v1/sessions/s1/fatigue",
        "/api/v1/sessions/s1/energy",
        "/api/v1/sessions/s1/workload",
        "/api/v1/sessions/s1/corner-mastery",
        # corner-replay excluded: uses direct SQL queries that need real DB;
        # tested in test_corner_replay_api.py
        "/api/v1/sessions/s1/corners",
        "/api/v1/sessions/s1/rival-gap",
        "/api/v1/sessions/s1/consistency",
        "/api/v1/sessions/s1/trends",
        "/api/v1/sessions/s1/stints",
        "/api/v1/sessions/s1/badges",
        "/api/v1/sessions/s1/pit-window",
        "/api/v1/setup/status",
    ])
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    @patch("web.routes.api_v1_data.get_gps_trace")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers")
    @patch("web.routes.api_v1_data.get_score_details")
    @patch("web.routes.api_v1_data.get_stint_analysis")
    def test_envelope_shape(
        self, mock_stints, mock_scores, mock_gps_laps, mock_gps,
        mock_laps, mock_session, mock_db, client, endpoint
    ):
        """Every successful response has {ok: true, data: ..., meta: {request_id}}."""
        conn = _mock_conn()
        # Make count queries work for setup/status
        conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        conn.execute.return_value.fetchall.return_value = []
        mock_db.return_value = conn
        mock_session.return_value = _MOCK_SESSION
        mock_laps.return_value = _MOCK_LAPS
        mock_gps.return_value = _MOCK_GPS
        mock_gps_laps.return_value = [1, 2, 3]
        mock_scores.return_value = _MOCK_SCORE_DETAILS
        mock_stints.return_value = []

        resp = client.get(endpoint)
        assert resp.status_code == 200, f"{endpoint}: got {resp.status_code}"

        body = resp.get_json()
        assert body is not None, f"{endpoint}: not JSON"
        assert "ok" in body, f"{endpoint}: missing 'ok'"
        assert body["ok"] is True, f"{endpoint}: ok != True"
        assert "data" in body, f"{endpoint}: missing 'data'"
        assert "meta" in body, f"{endpoint}: missing 'meta'"
        assert "request_id" in body["meta"], f"{endpoint}: missing 'request_id' in meta"


# ---------------------------------------------------------------------------
# Contract test: 404 shape on missing session
# ---------------------------------------------------------------------------

class TestNotFoundContracts:
    """Verify 404 responses also follow the standard error envelope."""

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/sessions/missing/speed-trace",
        "/api/v1/sessions/missing/fatigue",
        "/api/v1/sessions/missing/energy",
        "/api/v1/sessions/missing/workload",
        "/api/v1/sessions/missing/speed-profile",
        "/api/v1/sessions/missing/details",
        "/api/v1/sessions/missing/gps-trace",
        "/api/v1/sessions/missing/best-lap-gps",
    ])
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id", return_value=None)
    @patch("web.routes.api_v1_data.get_laps_for_session", return_value=[])
    def test_404_envelope(self, mock_laps, mock_session, mock_db, client, endpoint):
        """404 responses have {ok: false, error: {code, message}}."""
        mock_db.return_value = _mock_conn()

        resp = client.get(endpoint)
        assert resp.status_code == 404, f"{endpoint}: expected 404, got {resp.status_code}"

        body = resp.get_json()
        assert body is not None, f"{endpoint}: not JSON"
        assert body["ok"] is False, f"{endpoint}: ok should be False for 404"
        assert "error" in body, f"{endpoint}: missing 'error' key"
        assert "code" in body["error"], f"{endpoint}: missing error code"
