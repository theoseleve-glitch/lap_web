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


# ---------------------------------------------------------------------------
# FIX-003: Fatigue div-by-zero guard
# ---------------------------------------------------------------------------

class TestV1FatigueDivByZero:
    """FIX-003: When all lap times are 0, /fatigue must not crash."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_fatigue_all_zero_times(self, mock_laps, mock_sess, mock_db, client):
        """All lap times = 0 should not cause ZeroDivisionError."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1"}
        mock_laps.return_value = [
            {"lap_number": 1, "lap_time_s": 0, "is_valid": True},
            {"lap_number": 2, "lap_time_s": 0, "is_valid": True},
            {"lap_number": 3, "lap_time_s": 0, "is_valid": True},
        ]
        resp = client.get("/api/v1/sessions/s1/fatigue")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["fatigue_index"]) == 3
        # All fatigue values should be finite (no crash)
        for v in body["data"]["fatigue_index"]:
            assert v is not None

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_fatigue_normal_times(self, mock_laps, mock_sess, mock_db, client):
        """Normal lap times produce valid fatigue data."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1"}
        mock_laps.return_value = [
            {"lap_number": 1, "lap_time_s": 60.0, "is_valid": True},
            {"lap_number": 2, "lap_time_s": 61.0, "is_valid": True},
        ]
        resp = client.get("/api/v1/sessions/s1/fatigue")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["fatigue_index"]) == 2


# ---------------------------------------------------------------------------
# FIX-006: Missing driver_badges table in /badges
# ---------------------------------------------------------------------------

class TestV1BadgesMissingTable:
    """FIX-006/008: /badges gracefully handles missing tables and missing driver_id."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    def test_badges_missing_driver_id(self, mock_sess, mock_db, client):
        """Session without driver_id returns empty badges, no crash."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1"}  # no driver_id key
        resp = client.get("/api/v1/sessions/s1/badges")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["badges"] == []

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    def test_badges_table_does_not_exist(self, mock_sess, mock_db, client):
        """If driver_badges table doesn't exist, return empty badges."""
        conn = _mock_conn()
        # First call to execute (badge query) raises, second (tags) also raises
        conn.execute.side_effect = Exception("no such table: driver_badges")
        mock_db.return_value = conn
        mock_sess.return_value = {"session_id": "s1", "driver_id": "d1"}
        resp = client.get("/api/v1/sessions/s1/badges")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["badges"] == []
        assert body["data"]["tags"] == []


# ---------------------------------------------------------------------------
# FIX-009: Weather column access (PG dict compat)
# ---------------------------------------------------------------------------

class TestV1WeatherColumnAccess:
    """FIX-009: /weather uses column names for PG RealDictCursor compat."""

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_weather_with_dict_row(self, mock_db, client):
        """Dict row (PG) is handled by column names."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "air_temp_c": 25.0,
            "track_temp_c": 35.0,
            "humidity_pct": 60,
            "wind_speed_mps": 5.0,
        }
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/s1/weather")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["temperature"] == [25.0]
        assert body["data"]["humidity"] == [60]
        assert body["data"]["wind_speed"] == [18.0]  # 5.0 * 3.6

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_weather_no_data(self, mock_db, client):
        """No weather row returns empty arrays."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/s1/weather")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["temperature"] == []


# ---------------------------------------------------------------------------
# FIX-001/002: Energy and workload best-lap lookup
# ---------------------------------------------------------------------------

class TestV1EnergyBestLapLookup:
    """FIX-001: /energy uses laps-table for best lap, not session dict."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    @patch("web.routes.api_v1_data.get_gps_trace")
    def test_energy_no_laps_returns_empty(self, mock_gps, mock_laps, mock_sess, mock_db, client):
        """No laps returns empty energy data, not crash."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1"}
        mock_laps.return_value = []
        resp = client.get("/api/v1/sessions/s1/energy")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["distances"] == []
        mock_gps.assert_not_called()

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    @patch("web.routes.api_v1_data.get_gps_trace")
    def test_energy_uses_best_lap_from_laps_table(self, mock_gps, mock_laps, mock_sess, mock_db, client):
        """Energy endpoint finds best lap via is_best flag."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1"}
        mock_laps.return_value = [
            {"lap_number": 1, "is_best": False},
            {"lap_number": 3, "is_best": True},
        ]
        mock_gps.return_value = {"distances": [0, 10], "speeds": [10.0, 15.0]}
        resp = client.get("/api/v1/sessions/s1/energy")
        assert resp.status_code == 200
        # Verify get_gps_trace was called with lap_number=3 (the best lap)
        mock_gps.assert_called_once_with(mock_db.return_value, "s1", 3)


class TestV1WorkloadBestLapLookup:
    """FIX-002: /workload uses laps-table for best lap, not session dict."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_workload_no_laps_returns_empty(self, mock_laps, mock_sess, mock_db, client):
        """No laps returns empty workload data."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1"}
        mock_laps.return_value = []
        resp = client.get("/api/v1/sessions/s1/workload")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["timestamps"] == []


# ---------------------------------------------------------------------------
# FIX-007: Cross-session missing driver_id
# ---------------------------------------------------------------------------

class TestV1CrossSessionMissingDriverId:
    """FIX-007: /cross-session returns empty comparisons if driver_id is missing."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    def test_cross_session_no_driver_id(self, mock_sess, mock_db, client):
        """Session without driver_id returns empty comparisons."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1", "track_id": "t1"}  # no driver_id
        resp = client.get("/api/v1/sessions/s1/cross-session")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["comparisons"] == []

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    def test_cross_session_no_track_id(self, mock_sess, mock_db, client):
        """Session without track_id returns empty comparisons."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1", "driver_id": "d1"}  # no track_id
        resp = client.get("/api/v1/sessions/s1/cross-session")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["comparisons"] == []


# ---------------------------------------------------------------------------
# EXTRA-FIX-A: Tyre data div-by-zero
# ---------------------------------------------------------------------------

class TestV1TyreDataDivByZero:
    """EXTRA-FIX-A: /tyre-data handles all-zero lap times."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_tyre_data_all_zero_times(self, mock_laps, mock_db, client):
        """All lap times = 0 should not cause ZeroDivisionError."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = [
            {"lap_number": 1, "lap_time_s": 0, "is_valid": True},
            {"lap_number": 2, "lap_time_s": 0, "is_valid": True},
        ]
        resp = client.get("/api/v1/sessions/s1/tyre-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["laps"]) == 2


# ---------------------------------------------------------------------------
# FIX-005: Corner coaching missing table
# ---------------------------------------------------------------------------

class TestV1CornerCoachingMissingTable:
    """FIX-005: /corner-coaching handles missing corner_best_practices table."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    def test_corner_coaching_missing_best_practices_table(self, mock_sess, mock_db, client):
        """Missing corner_best_practices table returns coaching without best_practice."""
        conn = _mock_conn()
        # First call (corner_metrics query) returns rows
        corner_row = MagicMock()
        corner_row.__getitem__ = lambda self, k: {"corner_id": 1, "coaching_hint": "brake later"}.get(k)
        corner_row.keys = lambda: ["corner_id", "coaching_hint", "avg_entry_speed_mps",
                                    "avg_apex_speed_mps", "avg_exit_speed_mps", "avg_time_loss_ms"]

        def _dict_from_row(r):
            return {"corner_id": 1, "coaching_hint": "brake later",
                    "avg_entry_speed_mps": 15.0, "avg_apex_speed_mps": 12.0,
                    "avg_exit_speed_mps": 16.0, "avg_time_loss_ms": 50}

        call_count = [0]
        def mock_execute(sql, params=None):
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # corner_metrics query
                mock_row = MagicMock()
                mock_row.__iter__ = lambda s: iter([])
                mock_row.keys.return_value = ["corner_id", "coaching_hint"]

                def make_dict(r):
                    return {"corner_id": 1, "coaching_hint": "brake later",
                            "avg_entry_speed_mps": 15.0, "avg_apex_speed_mps": 12.0,
                            "avg_exit_speed_mps": 16.0, "avg_time_loss_ms": 50}
                result_row = MagicMock()
                result_row.__getitem__ = lambda self, k: make_dict(None).get(k)
                result_row.keys.return_value = list(make_dict(None).keys())
                result.fetchall.return_value = [result_row]
            elif call_count[0] == 2:
                # corner_best_practices query — table missing
                raise Exception("no such table: corner_best_practices")
            return result

        conn.execute = mock_execute
        mock_db.return_value = conn
        mock_sess.return_value = {"session_id": "s1", "track_id": "t1"}
        resp = client.get("/api/v1/sessions/s1/corner-coaching")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["coaching"]) == 1
        assert "best_practice" not in body["data"]["coaching"][0]


# ---------------------------------------------------------------------------
# EXTRA-FIX-B: Energy speed unit (m/s not km/h)
# ---------------------------------------------------------------------------

class TestV1EnergySpeedUnit:
    """EXTRA-FIX-B: Energy uses speeds directly (m/s), no /3.6 conversion."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    @patch("web.routes.api_v1_data.get_gps_trace")
    def test_energy_calculation_uses_mps(self, mock_gps, mock_laps, mock_sess, mock_db, client):
        """Energy calculated with v^2 directly (m/s), not (v/3.6)^2."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1"}
        mock_laps.return_value = [{"lap_number": 1, "is_best": True}]
        # Speed of 10 m/s, mass 80 kg → KE = 0.5 * 80 * 100 = 4000 J
        mock_gps.return_value = {"distances": [0], "speeds": [10.0]}
        resp = client.get("/api/v1/sessions/s1/energy")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        # 0.5 * 80 * 10^2 = 4000.0
        assert body["data"]["kinetic_energy"] == [4000.0]


# ---------------------------------------------------------------------------
# SHAPE-008: Corner mastery score normalized to 0-1
# ---------------------------------------------------------------------------

class TestV1CornerMasteryScoreScale:
    """SHAPE-008: Corner mastery score must be 0-1, not 0-100."""

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corner_mastery_score_is_0_to_1(self, mock_db, client):
        """Mastery score returned in 0-1 range for frontend consumption."""
        conn = _mock_conn()
        row = MagicMock()
        row_dict = {
            "corner_id": 1,
            "lap_count": 5,
            "avg_entry_mps": 20.0,
            "avg_apex_mps": 15.0,
            "avg_exit_mps": 22.0,
            "avg_time_loss_ms": 50.0,
            "min_time_loss_ms": 10.0,
            "max_time_loss_ms": 100.0,
            "avg_grip_util": 0.85,
        }
        row.__getitem__ = lambda self, k: row_dict[k]
        row.keys = lambda: list(row_dict.keys())
        # Make dict(row) work
        row.__iter__ = lambda self: iter(row_dict)
        type(row).__len__ = lambda self: len(row_dict)

        def dict_from_mock(m):
            return dict(row_dict)

        conn.execute.return_value.fetchall.return_value = [row]
        mock_db.return_value = conn

        with patch("web.routes.api_v1_data.dict", side_effect=lambda r: dict(row_dict)):
            resp = client.get("/api/v1/sessions/s1/corner-mastery")

        body = resp.get_json()
        assert body["ok"] is True
        corners = body["data"]["corners"]
        assert len(corners) == 1
        score = corners[0]["score"]
        # Score must be between 0 and 1 (not 0-100)
        assert 0 <= score <= 1.0, f"Score {score} not in 0-1 range"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corner_mastery_max_score_is_1(self, mock_db, client):
        """Perfect corner mastery should be 1.0 (not 100)."""
        conn = _mock_conn()
        # Perfect grip utilization, no time loss → mastery = 50 + 0.85*30 = 75.5
        row_dict = {
            "corner_id": 2,
            "lap_count": 10,
            "avg_entry_mps": 25.0,
            "avg_apex_mps": 18.0,
            "avg_exit_mps": 27.0,
            "avg_time_loss_ms": 0.0,
            "min_time_loss_ms": 0.0,
            "max_time_loss_ms": 0.0,
            "avg_grip_util": 1.0,
        }
        row = MagicMock()
        row.__getitem__ = lambda self, k: row_dict[k]
        row.keys = lambda: list(row_dict.keys())
        row.__iter__ = lambda self: iter(row_dict)
        type(row).__len__ = lambda self: len(row_dict)

        conn.execute.return_value.fetchall.return_value = [row]
        mock_db.return_value = conn

        with patch("web.routes.api_v1_data.dict", side_effect=lambda r: dict(row_dict)):
            resp = client.get("/api/v1/sessions/s1/corner-mastery")

        body = resp.get_json()
        corners = body["data"]["corners"]
        score = corners[0]["score"]
        assert score <= 1.0, f"Score {score} exceeds 1.0 — not normalized"


# ---------------------------------------------------------------------------
# SHAPE-010: Session details missing condition and kart_name fields
# ---------------------------------------------------------------------------

class TestV1SessionDetailsMissingFields:
    """SHAPE-010: Session detail must include condition and kart_name."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_score_details")
    def test_session_details_includes_condition(self, mock_scores, mock_sess, mock_db, client):
        """Session detail response includes 'condition' field."""
        conn = _mock_conn()
        mock_db.return_value = conn
        mock_sess.return_value = {
            "session_id": "s1",
            "session_date": "2026-01-15",
            "track_name": "Monza",
            "driver_name": "Test Driver",
            "n_laps": 10,
            "best_lap_time_s": 60.5,
            "mean_lap_time_s": 62.0,
            "total_score": 78,
            "grade": "B",
            "session_type": "practice",
            "track_state": "dry",
            "kart_name": "Rotax Senior #42",
        }
        mock_scores.return_value = {}

        resp = client.get("/api/v1/sessions/s1/details")
        body = resp.get_json()
        assert body["ok"] is True
        detail = body["data"]
        assert "condition" in detail, "Missing 'condition' field in session detail"
        assert detail["condition"] == "dry"

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_score_details")
    def test_session_details_includes_kart_name(self, mock_scores, mock_sess, mock_db, client):
        """Session detail response includes 'kart_name' field."""
        conn = _mock_conn()
        mock_db.return_value = conn
        mock_sess.return_value = {
            "session_id": "s1",
            "session_date": "2026-01-15",
            "track_name": "Monza",
            "driver_name": "Test Driver",
            "n_laps": 10,
            "best_lap_time_s": 60.5,
            "mean_lap_time_s": 62.0,
            "total_score": 78,
            "grade": "B",
            "session_type": "practice",
            "track_state": "dry",
            "kart_name": "Rotax Senior #42",
        }
        mock_scores.return_value = {}

        resp = client.get("/api/v1/sessions/s1/details")
        body = resp.get_json()
        assert body["ok"] is True
        detail = body["data"]
        assert "kart_name" in detail, "Missing 'kart_name' field in session detail"
        assert detail["kart_name"] == "Rotax Senior #42"

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_score_details")
    def test_session_details_missing_fields_are_none(self, mock_scores, mock_sess, mock_db, client):
        """When session lacks track_state/kart_name, fields are present but None."""
        conn = _mock_conn()
        mock_db.return_value = conn
        mock_sess.return_value = {
            "session_id": "s1",
            "session_date": "2026-01-15",
            "track_name": "Monza",
            "driver_name": "Test Driver",
            "n_laps": 5,
            "best_lap_time_s": 61.0,
            "mean_lap_time_s": 63.0,
            "total_score": 70,
            "grade": "C",
            "session_type": "race",
        }
        mock_scores.return_value = {}

        resp = client.get("/api/v1/sessions/s1/details")
        body = resp.get_json()
        assert body["ok"] is True
        detail = body["data"]
        assert "condition" in detail, "Missing 'condition' field"
        assert detail["condition"] is None
        assert "kart_name" in detail, "Missing 'kart_name' field"
        assert detail["kart_name"] is None


# ---------------------------------------------------------------------------
# MISSING-001: GET /sessions/<id>/pit-window
# ---------------------------------------------------------------------------

class TestV1PitWindow:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_pit_window_returns_envelope(self, mock_db, client):
        """GET /api/v1/sessions/<id>/pit-window returns ok/data envelope."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/pit-window")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True
        assert "data" in body

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_pit_window_expected_fields(self, mock_db, client):
        """Response has current_lap, window_open, window_close, optimal_lap, time_loss_per_lap."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/pit-window")
        body = resp.get_json()
        data = body["data"]
        for key in ("current_lap", "window_open", "window_close", "optimal_lap", "time_loss_per_lap"):
            assert key in data, f"Missing key '{key}' in pit-window response"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_pit_window_with_lap_data(self, mock_db, client):
        """When laps exist, pit-window computes from them."""
        conn = _mock_conn()
        mock_db.return_value = conn
        # Return 10 laps
        lap_rows = [
            {"lap_number": i, "lap_time_s": 60.0 + i * 0.1, "is_valid": 1}
            for i in range(1, 11)
        ]
        conn.execute.return_value.fetchall.return_value = lap_rows
        resp = client.get("/api/v1/sessions/sess_001/pit-window")
        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]
        assert data["current_lap"] == 10


# ---------------------------------------------------------------------------
# MISSING-002: GET /sessions/<id>/rival-gap
# ---------------------------------------------------------------------------

class TestV1RivalGap:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_rival_gap_returns_envelope(self, mock_db, client):
        """GET /api/v1/sessions/<id>/rival-gap returns ok/data envelope."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/rival-gap")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_rival_gap_has_expected_arrays(self, mock_db, client):
        """Response has lap_numbers and gap_seconds as arrays."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/rival-gap")
        body = resp.get_json()
        data = body["data"]
        assert isinstance(data["lap_numbers"], list)
        assert isinstance(data["gap_seconds"], list)

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_rival_gap_returns_empty_arrays(self, mock_db, client):
        """No rival data exists, so arrays should be empty."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/rival-gap")
        body = resp.get_json()
        data = body["data"]
        assert data["lap_numbers"] == []
        assert data["gap_seconds"] == []


# ---------------------------------------------------------------------------
# MISSING-003: GET /sessions/<id>/corners
# ---------------------------------------------------------------------------

class TestV1Corners:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corners_returns_envelope(self, mock_db, client):
        """GET /api/v1/sessions/<id>/corners returns ok/data envelope."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/corners")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corners_has_corners_list(self, mock_db, client):
        """Response has 'corners' key with a list."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/corners")
        body = resp.get_json()
        assert isinstance(body["data"]["corners"], list)

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corners_with_data(self, mock_db, client):
        """When corner_metrics has data, returns aggregated corners."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            {
                "corner_id": 1,
                "avg_entry_speed_mps": 20.0,
                "avg_apex_speed_mps": 15.0,
                "avg_exit_speed_mps": 22.0,
            },
            {
                "corner_id": 2,
                "avg_entry_speed_mps": 25.0,
                "avg_apex_speed_mps": 18.0,
                "avg_exit_speed_mps": 27.0,
            },
        ]
        resp = client.get("/api/v1/sessions/sess_001/corners")
        body = resp.get_json()
        corners = body["data"]["corners"]
        assert len(corners) == 2
        assert corners[0]["corner_id"] == 1
        for key in ("name", "entry_speed", "apex_speed", "exit_speed"):
            assert key in corners[0], f"Missing key '{key}' in corner"


# ---------------------------------------------------------------------------
# MISSING-004: GET /sessions/<id>/corner-replay
# ---------------------------------------------------------------------------

class TestV1CornerReplay:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corner_replay_returns_envelope(self, mock_db, client):
        """GET /api/v1/sessions/<id>/corner-replay returns ok/data envelope."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/corner-replay")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_corner_replay_has_frames(self, mock_db, client):
        """Response has 'frames' key with a list."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/sess_001/corner-replay")
        body = resp.get_json()
        assert isinstance(body["data"]["frames"], list)


# ---------------------------------------------------------------------------
# MISSING-005: GET /setup/status
# ---------------------------------------------------------------------------

class TestV1SetupStatus:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_setup_status_returns_envelope(self, mock_db, client):
        """GET /api/v1/setup/status returns ok/data envelope."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/setup/status")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_setup_status_has_steps(self, mock_db, client):
        """Response has 'steps' key with a list of step objects."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/setup/status")
        body = resp.get_json()
        steps = body["data"]["steps"]
        assert isinstance(steps, list)
        assert len(steps) > 0
        for step in steps:
            assert "id" in step
            assert "label" in step
            assert "status" in step

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_setup_status_step_values(self, mock_db, client):
        """Setup steps have valid statuses: 'complete' or 'pending'."""
        conn = _mock_conn()
        mock_db.return_value = conn
        resp = client.get("/api/v1/setup/status")
        body = resp.get_json()
        for step in body["data"]["steps"]:
            assert step["status"] in ("complete", "pending"), \
                f"Invalid status '{step['status']}' for step '{step['id']}'"


# ---------------------------------------------------------------------------
# MISSING-006: GET /data-health/jobs/<job_id>
# ---------------------------------------------------------------------------

class TestV1DataHealthJobDetail:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_job_detail_returns_envelope(self, mock_db, client):
        """GET /api/v1/data-health/jobs/<job_id> returns ok/data envelope."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "j1",
            "file_path": "/tmp/data.csv",
            "file_size": 1024,
            "status": "completed",
            "n_rows_total": 100,
            "n_rows_loaded": 100,
            "n_chunks": 1,
            "error_message": None,
            "elapsed_s": 1.5,
            "started_at": "2026-01-01T00:00:00",
            "completed_at": "2026-01-01T00:00:01",
            "sha256_partial": "abc123",
        }
        resp = client.get("/api/v1/data-health/jobs/j1")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_job_detail_not_found(self, mock_db, client):
        """Returns 404 when job does not exist."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = None
        resp = client.get("/api/v1/data-health/jobs/nonexistent")
        body = resp.get_json()
        assert resp.status_code == 404
        assert body["ok"] is False

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_job_detail_strips_file_path(self, mock_db, client):
        """Response has file_name but not file_path (security)."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "j1",
            "file_path": "/home/user/data/my_session.csv",
            "file_size": 2048,
            "status": "completed",
            "n_rows_total": 200,
            "n_rows_loaded": 200,
            "n_chunks": 2,
            "error_message": None,
            "elapsed_s": 3.0,
            "started_at": "2026-01-01T00:00:00",
            "completed_at": "2026-01-01T00:00:03",
            "sha256_partial": "def456",
        }
        resp = client.get("/api/v1/data-health/jobs/j1")
        body = resp.get_json()
        data = body["data"]
        assert "file_name" in data
        assert data["file_name"] == "my_session.csv"
        assert "file_path" not in data


# ---------------------------------------------------------------------------
# PATCH /sessions/<id> — inline edit session metadata
# ---------------------------------------------------------------------------

class TestV1PatchSession:
    """Tests for PATCH /api/v1/sessions/<session_id>."""

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id", return_value=None)
    def test_404_when_session_missing(self, mock_sess, mock_db, client):
        """Returns 404 when session does not exist."""
        mock_db.return_value = _mock_conn()
        resp = client.patch(
            "/api/v1/sessions/missing",
            data=json.dumps({"notes": "hello"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_400_when_body_empty(self, mock_db, client):
        """Returns 400 when body is empty or missing."""
        conn = _mock_conn()
        mock_db.return_value = conn
        # Need to pass the session-exists check
        with patch("web.routes.api_v1_data.get_session_by_id", return_value={"session_id": "s1"}):
            resp = client.patch(
                "/api/v1/sessions/s1",
                data=json.dumps({}),
                content_type="application/json",
            )
        assert resp.status_code == 400

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_400_on_unknown_fields(self, mock_db, client):
        """Returns 400 if body contains unknown fields."""
        conn = _mock_conn()
        mock_db.return_value = conn
        with patch("web.routes.api_v1_data.get_session_by_id", return_value={"session_id": "s1"}):
            resp = client.patch(
                "/api/v1/sessions/s1",
                data=json.dumps({"unknown_field": "x"}),
                content_type="application/json",
            )
        body = resp.get_json()
        assert resp.status_code == 400
        assert "unknown_field" in body.get("error", {}).get("message", "").lower()

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.update_session_field")
    def test_patch_notes(self, mock_update, mock_db, client):
        """PATCH with notes field calls update_session_field and returns updated session."""
        conn = _mock_conn()
        mock_db.return_value = conn
        updated_session = {
            "session_id": "s1",
            "session_date": "2026-02-28",
            "track_name": "Monza",
            "driver_name": "Max",
            "session_type": "practice",
            "track_state": "dry",
            "notes": "Good session",
        }
        with patch("web.routes.api_v1_data.get_session_by_id", side_effect=[
            {"session_id": "s1"},   # first call: existence check
            updated_session,         # second call: return updated
        ]):
            resp = client.patch(
                "/api/v1/sessions/s1",
                data=json.dumps({"notes": "Good session"}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["notes"] == "Good session"
        mock_update.assert_called_once_with(conn, "s1", "notes", "Good session")

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.update_session_field")
    def test_patch_session_type(self, mock_update, mock_db, client):
        """PATCH with session_type updates the correct DB column."""
        conn = _mock_conn()
        mock_db.return_value = conn
        updated = {
            "session_id": "s1", "session_date": "2026-02-28",
            "track_name": "Monza", "driver_name": "Max",
            "session_type": "qualifying", "track_state": "dry", "notes": None,
        }
        with patch("web.routes.api_v1_data.get_session_by_id", side_effect=[
            {"session_id": "s1"}, updated,
        ]):
            resp = client.patch(
                "/api/v1/sessions/s1",
                data=json.dumps({"session_type": "qualifying"}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        mock_update.assert_called_once_with(conn, "s1", "session_type", "qualifying")

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.update_session_field")
    def test_patch_condition(self, mock_update, mock_db, client):
        """PATCH with condition maps to track_state DB column."""
        conn = _mock_conn()
        mock_db.return_value = conn
        updated = {
            "session_id": "s1", "session_date": "2026-02-28",
            "track_name": "Monza", "driver_name": "Max",
            "session_type": "practice", "track_state": "wet", "notes": None,
        }
        with patch("web.routes.api_v1_data.get_session_by_id", side_effect=[
            {"session_id": "s1"}, updated,
        ]):
            resp = client.patch(
                "/api/v1/sessions/s1",
                data=json.dumps({"condition": "wet"}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["condition"] == "wet"
        mock_update.assert_called_once_with(conn, "s1", "track_state", "wet")

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_patch_driver_name_resolves_to_driver_id(self, mock_db, client):
        """PATCH with driver_name upserts driver and updates driver_id."""
        conn = _mock_conn()
        # Make execute().fetchone() return driver_id=7
        conn.execute.return_value.fetchone.return_value = {"driver_id": 7}
        mock_db.return_value = conn
        updated = {
            "session_id": "s1", "session_date": "2026-02-28",
            "track_name": "Monza", "driver_name": "New Driver",
            "session_type": "practice", "track_state": "dry", "notes": None,
        }
        with patch("web.routes.api_v1_data.get_session_by_id", side_effect=[
            {"session_id": "s1"}, updated,
        ]):
            with patch("web.routes.api_v1_data.update_session_field") as mock_update:
                resp = client.patch(
                    "/api/v1/sessions/s1",
                    data=json.dumps({"driver_name": "New Driver"}),
                    content_type="application/json",
                )
        assert resp.status_code == 200
        # Should have called update_session_field with driver_id
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        assert call_args[0][2] == "driver_id"  # field_name
        assert call_args[0][3] == 7  # value = driver_id

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.update_session_field")
    def test_patch_multiple_fields(self, mock_update, mock_db, client):
        """PATCH with multiple fields updates all of them."""
        conn = _mock_conn()
        mock_db.return_value = conn
        updated = {
            "session_id": "s1", "session_date": "2026-02-28",
            "track_name": "Monza", "driver_name": "Max",
            "session_type": "race", "track_state": "wet", "notes": "Rain race",
        }
        with patch("web.routes.api_v1_data.get_session_by_id", side_effect=[
            {"session_id": "s1"}, updated,
        ]):
            resp = client.patch(
                "/api/v1/sessions/s1",
                data=json.dumps({
                    "session_type": "race",
                    "condition": "wet",
                    "notes": "Rain race",
                }),
                content_type="application/json",
            )
        assert resp.status_code == 200
        assert mock_update.call_count == 3
