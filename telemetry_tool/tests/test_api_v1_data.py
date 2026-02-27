"""Tests for v1 data API endpoints."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask

from web.api_utils import ErrorCode, api_error, api_response, init_request_id
from web.routes.api_v1_data import bp as api_v1_data_bp


# ---------------------------------------------------------------------------
# Helpers
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
# Envelope shape — all v1 endpoints return the standard envelope
# ---------------------------------------------------------------------------

class TestV1EnvelopeFormat:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1, 2, 3])
    def test_laps_gps_returns_envelope(self, mock_laps, mock_db, client):
        """GET /api/v1/sessions/<id>/laps/gps returns ok/data/meta envelope."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/sess_001/laps/gps")
        body = resp.get_json()
        assert "ok" in body
        assert "data" in body
        assert "meta" in body
        assert "request_id" in body["meta"]

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session", return_value=[])
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[])
    def test_speed_trace_returns_envelope(self, mock_gps, mock_laps, mock_sess, mock_db, client):
        """GET /api/v1/sessions/<id>/speed-trace returns envelope."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1", "track_id": "t1"}
        resp = client.get("/api/v1/sessions/sess_001/speed-trace")
        body = resp.get_json()
        assert body["ok"] is True
        assert "data" in body

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session", return_value=[])
    def test_lap_times_returns_envelope(self, mock_laps, mock_db, client):
        """GET /api/v1/sessions/<id>/lap-times returns envelope."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/sess_001/lap-times")
        body = resp.get_json()
        assert body["ok"] is True
        assert "data" in body
        assert "laps" in body["data"]


# ---------------------------------------------------------------------------
# Session GPS laps
# ---------------------------------------------------------------------------

class TestV1LapsGps:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1, 3, 5])
    def test_returns_lap_numbers(self, mock_laps, mock_db, client):
        """Returns list of lap numbers with GPS data."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["laps"] == [1, 3, 5]

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[])
    def test_empty_laps(self, mock_laps, mock_db, client):
        """Returns empty list when no GPS laps exist."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        body = resp.get_json()
        assert body["data"]["laps"] == []


# ---------------------------------------------------------------------------
# Speed trace
# ---------------------------------------------------------------------------

class TestV1SpeedTrace:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id", return_value=None)
    def test_404_when_session_missing(self, mock_sess, mock_db, client):
        """Returns 404 envelope when session does not exist."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/missing/speed-trace")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Lap times
# ---------------------------------------------------------------------------

class TestV1LapTimes:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_returns_lap_times(self, mock_laps, mock_db, client):
        """Returns formatted lap times."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = [
            {"lap_number": 1, "lap_time_s": 62.5, "is_best": True, "is_valid": True,
             "invalid_reason": None, "phase_id": None},
            {"lap_number": 2, "lap_time_s": 63.1, "is_best": False, "is_valid": True,
             "invalid_reason": None, "phase_id": None},
        ]
        resp = client.get("/api/v1/sessions/s1/lap-times")
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["laps"]) == 2
        assert body["data"]["laps"][0]["lap_time_s"] == 62.5


# ---------------------------------------------------------------------------
# GG data
# ---------------------------------------------------------------------------

class TestV1GgData:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[])
    def test_empty_gg_data(self, mock_laps, mock_db, client):
        """Returns empty arrays when no GG data available."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/gg-data")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["n_points"] == 0


# ---------------------------------------------------------------------------
# Theoretical data
# ---------------------------------------------------------------------------

class TestV1Theoretical:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_theoretical_data", return_value=None)
    def test_404_when_no_theoretical(self, mock_theo, mock_db, client):
        """Returns 404 when no theoretical data exists."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/theoretical")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"]["code"] == "NOT_FOUND"

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_theoretical_data")
    def test_returns_theoretical_data(self, mock_theo, mock_db, client):
        """Returns theoretical data in envelope."""
        mock_db.return_value = _mock_conn()
        mock_theo.return_value = {
            "theoretical_time_s": 60.0, "actual_best_time_s": 62.0,
            "gap_pct": 3.3, "simulation_method": "physics",
            "speeds": [10, 20], "distances": [0, 100], "metrics": {},
        }
        resp = client.get("/api/v1/sessions/s1/theoretical")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["theoretical_time_s"] == 60.0


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

class TestV1Fingerprint:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_session_missing(self, mock_db, client):
        """Returns 404 when session not found."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/missing/fingerprint")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reference line
# ---------------------------------------------------------------------------

class TestV1ReferenceLine:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_reference_line", return_value=None)
    def test_404_when_no_reference(self, mock_ref, mock_db, client):
        """Returns 404 when no reference line exists."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/reference-line")
        assert resp.status_code == 404

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_reference_line")
    def test_returns_reference_line(self, mock_ref, mock_db, client):
        """Returns reference line data in envelope."""
        mock_db.return_value = _mock_conn()
        mock_ref.return_value = {"latitudes": [1.0], "longitudes": [2.0]}
        resp = client.get("/api/v1/sessions/s1/reference-line")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["latitudes"] == [1.0]


# ---------------------------------------------------------------------------
# Best lap GPS
# ---------------------------------------------------------------------------

class TestV1BestLapGps:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session", return_value=[])
    def test_404_when_no_best_lap(self, mock_laps, mock_db, client):
        """Returns 404 when no best lap found."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/best-lap-gps")
        assert resp.status_code == 404

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    @patch("web.routes.api_v1_data.get_gps_trace")
    def test_returns_best_lap_gps(self, mock_gps, mock_laps, mock_db, client):
        """Returns GPS trace for best lap."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = [{"lap_number": 3, "is_best": True}]
        mock_gps.return_value = {"latitudes": [1.0], "longitudes": [2.0],
                                  "distances": [0], "speeds": [10]}
        resp = client.get("/api/v1/sessions/s1/best-lap-gps")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["lap_number"] == 3


# ---------------------------------------------------------------------------
# Fatigue
# ---------------------------------------------------------------------------

class TestV1Fatigue:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id", return_value=None)
    def test_404_when_session_missing(self, mock_sess, mock_db, client):
        """Returns 404 when session not found."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/missing/fatigue")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Speed profile
# ---------------------------------------------------------------------------

class TestV1SpeedProfile:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_session_missing(self, mock_db, client):
        """Returns 404 when session not found."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/missing/speed-profile")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Track records
# ---------------------------------------------------------------------------

class TestV1TrackRecords:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_track_records", return_value=[])
    def test_returns_records(self, mock_recs, mock_db, client):
        """Returns track records in envelope."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/tracks/t1/records")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["records"] == []


# ---------------------------------------------------------------------------
# Track evolution
# ---------------------------------------------------------------------------

class TestV1TrackEvolution:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_returns_evolution(self, mock_db, client):
        """Returns evolution data in envelope."""
        conn = _mock_conn()
        conn.execute.return_value.fetchall.return_value = []
        mock_db.return_value = conn
        resp = client.get("/api/v1/tracks/t1/evolution")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["sessions"] == []


# ---------------------------------------------------------------------------
# Track geometry
# ---------------------------------------------------------------------------

class TestV1TrackGeometry:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_no_geometry(self, mock_db, client):
        """Returns 404 when no geometry data exists."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.get("/api/v1/tracks/t1/geometry")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Files list
# ---------------------------------------------------------------------------

class TestV1Files:
    @patch("web.routes.api_v1_data.Path")
    def test_returns_files_envelope(self, mock_path_cls, client, tmp_path):
        """Returns file list in envelope."""
        mock_dir = MagicMock()
        mock_dir.iterdir.return_value = []
        mock_dir.mkdir = MagicMock()
        mock_path_cls.return_value = mock_dir
        resp = client.get("/api/v1/files")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["files"] == []


# ---------------------------------------------------------------------------
# Session DELETE
# ---------------------------------------------------------------------------

class TestV1DeleteSession:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_session_missing(self, mock_db, client):
        """DELETE returns 404 for unknown session."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.delete("/api/v1/sessions/missing")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"]["code"] == "NOT_FOUND"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_delete_success(self, mock_db, client):
        """DELETE returns success envelope for existing session."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {"session_id": "s1"}
        mock_db.return_value = conn
        resp = client.delete("/api/v1/sessions/s1")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["session_id"] == "s1"

# ---------------------------------------------------------------------------
# Karts list
# ---------------------------------------------------------------------------

class TestV1KartsList:
    @patch("web.routes.api_v1_data.validate_karts_schema")
    @patch("web.routes.api_v1_data.get_all_karts", side_effect=Exception("db failure"))
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_returns_internal_error_envelope_on_db_failure(
        self,
        mock_db,
        mock_get_karts,
        mock_validate_schema,
        client,
    ):
        """GET /api/v1/karts returns stable error envelope on DB failure."""
        mock_db.return_value = _mock_conn()

        resp = client.get("/api/v1/karts")

        assert resp.status_code == 500
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == ErrorCode.INTERNAL_ERROR
        assert body["error"]["message"] == "Internal server error"
        assert "request_id" in body["meta"]
        mock_validate_schema.assert_called_once()
