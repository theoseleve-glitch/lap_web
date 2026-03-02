"""Tests for rich telemetry channel endpoints (Task 7).

Endpoints under test:
    GET /api/v1/sessions/<id>/channels          - Available channels list
    GET /api/v1/sessions/<id>/pedals?lap=N       - Throttle, brake, steering
    GET /api/v1/sessions/<id>/tire-temps?lap=N   - Per-corner tire temperatures
    GET /api/v1/sessions/<id>/wheel-slip?lap=N   - Per-corner slip ratios
    GET /api/v1/sessions/<id>/rpm-gear?lap=N     - RPM + gear + speed
    GET /api/v1/sessions/<id>/brake-temps?lap=N  - Per-corner brake temperatures
    GET /api/v1/sessions/<id>/fuel               - Fuel level per lap

All model functions are mocked -- no real DB interaction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Minimal Flask app with data_v2_channels blueprint."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False

    from web.routes.data_v2_channels import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── Sample data builders ─────────────────────────────────────────


def _sample_session():
    return {
        "session_id": "s1",
        "csv_filename": "test1.csv",
        "driver_id": 1,
        "driver_name": "TestDriver",
        "track_id": "t1",
        "track_name": "TestTrack",
        "session_type": "practice",
        "track_state": "dry",
        "session_date": "2024-01-01",
        "n_laps": 5,
        "best_lap_time_s": 60.0,
        "mean_lap_time_s": 61.5,
        "total_score": 75.0,
        "grade": "B",
    }


def _sample_laps():
    return [
        {"session_id": "s1", "lap_number": 1, "lap_time_s": 62.0, "is_valid": 1, "is_best": 0},
        {"session_id": "s1", "lap_number": 2, "lap_time_s": 60.0, "is_valid": 1, "is_best": 1},
        {"session_id": "s1", "lap_number": 3, "lap_time_s": 61.0, "is_valid": 1, "is_best": 0},
    ]


def _full_channel_data():
    """Channel data with all channels populated."""
    return {
        "distances": [0.0, 50.0, 100.0, 150.0, 200.0],
        "speeds": [10.0, 15.0, 20.0, 18.0, 12.0],
        "throttle": [0.0, 50.0, 100.0, 80.0, 0.0],
        "brake": [100.0, 0.0, 0.0, 20.0, 90.0],
        "steering": [0.0, -5.0, -10.0, 2.0, 8.0],
        "rpm": [3000, 5000, 7000, 6500, 4000],
        "gear": [2, 3, 4, 4, 3],
        "fuel": [45.0, 44.8, 44.5, 44.3, 44.0],
        "tire_temps": {
            "fl": {"i": [80.0, 82.0, 85.0, 84.0, 81.0],
                   "m": [78.0, 80.0, 83.0, 82.0, 79.0],
                   "o": [76.0, 78.0, 81.0, 80.0, 77.0]},
            "fr": {"i": [79.0, 81.0, 84.0, 83.0, 80.0],
                   "m": [77.0, 79.0, 82.0, 81.0, 78.0],
                   "o": [75.0, 77.0, 80.0, 79.0, 76.0]},
            "rl": {"i": [82.0, 84.0, 87.0, 86.0, 83.0],
                   "m": [80.0, 82.0, 85.0, 84.0, 81.0],
                   "o": [78.0, 80.0, 83.0, 82.0, 79.0]},
            "rr": {"i": [81.0, 83.0, 86.0, 85.0, 82.0],
                   "m": [79.0, 81.0, 84.0, 83.0, 80.0],
                   "o": [77.0, 79.0, 82.0, 81.0, 78.0]},
        },
        "tire_pressures": {
            "fl": [180.0, 182.0, 185.0, 184.0, 181.0],
            "fr": [179.0, 181.0, 184.0, 183.0, 180.0],
            "rl": [175.0, 177.0, 180.0, 179.0, 176.0],
            "rr": [174.0, 176.0, 179.0, 178.0, 175.0],
        },
        "brake_temps": {
            "fl": [300.0, 350.0, 400.0, 380.0, 320.0],
            "fr": [290.0, 340.0, 390.0, 370.0, 310.0],
            "rl": [250.0, 300.0, 350.0, 330.0, 270.0],
            "rr": [240.0, 290.0, 340.0, 320.0, 260.0],
        },
        "wheel_slip": {
            "fl": [0.01, 0.02, 0.05, 0.03, 0.02],
            "fr": [0.01, 0.02, 0.04, 0.03, 0.02],
            "rl": [0.02, 0.03, 0.06, 0.04, 0.03],
            "rr": [0.02, 0.03, 0.05, 0.04, 0.03],
        },
    }


def _minimal_channel_data():
    """Channel data with only basic GPS — no rich channels."""
    return {
        "distances": [0.0, 50.0, 100.0],
        "speeds": [10.0, 15.0, 12.0],
    }


def _full_availability():
    return {
        "throttle": True,
        "brake": True,
        "steering": True,
        "rpm": True,
        "gear": True,
        "tire_temps": True,
        "tire_pressures": True,
        "brake_temps": True,
        "wheel_slip": True,
        "fuel": True,
    }


def _empty_availability():
    return {
        "throttle": False,
        "brake": False,
        "steering": False,
        "rpm": False,
        "gear": False,
        "tire_temps": False,
        "tire_pressures": False,
        "brake_temps": False,
        "wheel_slip": False,
        "fuel": False,
    }


# ══════════════════════════════════════════════════════════════════
# 1. /channels endpoint
# ══════════════════════════════════════════════════════════════════


class TestChannelsEndpoint:

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_channels_full(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_channel_availability.return_value = _full_availability()
        resp = client.get("/api/v1/sessions/s1/channels")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["has_rich_data"] is True
        assert body["data"]["channels"]["throttle"] is True

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_channels_none(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_channel_availability.return_value = _empty_availability()
        resp = client.get("/api/v1/sessions/s1/channels")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["has_rich_data"] is False

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_channels_no_session(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = None
        resp = client.get("/api/v1/sessions/nosuch/channels")
        assert resp.status_code == 404

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_channels_no_traces(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_channel_availability.return_value = {}
        resp = client.get("/api/v1/sessions/s1/channels")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["has_rich_data"] is False
        assert "No telemetry trace data" in body["data"]["message"]


# ══════════════════════════════════════════════════════════════════
# 2. /pedals endpoint
# ══════════════════════════════════════════════════════════════════


class TestPedalsEndpoint:

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_pedals_with_data(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _full_channel_data()
        resp = client.get("/api/v1/sessions/s1/pedals?lap=2")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is True
        assert body["data"]["throttle"] == [0.0, 50.0, 100.0, 80.0, 0.0]
        assert body["data"]["brake"] == [100.0, 0.0, 0.0, 20.0, 90.0]
        assert body["data"]["steering"] == [0.0, -5.0, -10.0, 2.0, 8.0]
        assert body["data"]["lap_number"] == 2

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_pedals_no_data(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _minimal_channel_data()
        resp = client.get("/api/v1/sessions/s1/pedals?lap=2")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_pedals_no_session(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = None
        resp = client.get("/api/v1/sessions/nosuch/pedals?lap=1")
        assert resp.status_code == 404

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_pedals_default_lap(self, mock_conn, mock_models, client):
        """Without ?lap=, should fall back to best lap (lap 2)."""
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _full_channel_data()
        resp = client.get("/api/v1/sessions/s1/pedals")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["lap_number"] == 2  # best lap


# ══════════════════════════════════════════════════════════════════
# 3. /tire-temps endpoint
# ══════════════════════════════════════════════════════════════════


class TestTireTempsEndpoint:

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_tire_temps_with_data(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _full_channel_data()
        resp = client.get("/api/v1/sessions/s1/tire-temps?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is True
        assert "fl" in body["data"]["tire_temps"]
        assert "i" in body["data"]["tire_temps"]["fl"]

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_tire_temps_unavailable(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _minimal_channel_data()
        resp = client.get("/api/v1/sessions/s1/tire-temps?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False


# ══════════════════════════════════════════════════════════════════
# 4. /wheel-slip endpoint
# ══════════════════════════════════════════════════════════════════


class TestWheelSlipEndpoint:

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_wheel_slip_with_data(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _full_channel_data()
        resp = client.get("/api/v1/sessions/s1/wheel-slip?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is True
        assert "fl" in body["data"]["wheel_slip"]

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_wheel_slip_unavailable(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _minimal_channel_data()
        resp = client.get("/api/v1/sessions/s1/wheel-slip?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False


# ══════════════════════════════════════════════════════════════════
# 5. /rpm-gear endpoint
# ══════════════════════════════════════════════════════════════════


class TestRpmGearEndpoint:

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_rpm_gear_with_data(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _full_channel_data()
        resp = client.get("/api/v1/sessions/s1/rpm-gear?lap=2")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is True
        assert body["data"]["rpm"] == [3000, 5000, 7000, 6500, 4000]
        assert body["data"]["gear"] == [2, 3, 4, 4, 3]
        assert body["data"]["speeds"] == [10.0, 15.0, 20.0, 18.0, 12.0]

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_rpm_gear_unavailable(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _minimal_channel_data()
        resp = client.get("/api/v1/sessions/s1/rpm-gear?lap=2")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False


# ══════════════════════════════════════════════════════════════════
# 6. /brake-temps endpoint
# ══════════════════════════════════════════════════════════════════


class TestBrakeTempsEndpoint:

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_brake_temps_with_data(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _full_channel_data()
        resp = client.get("/api/v1/sessions/s1/brake-temps?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is True
        assert "fl" in body["data"]["brake_temps"]
        assert body["data"]["brake_temps"]["fl"][0] == 300.0

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_brake_temps_unavailable(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_laps_for_session.return_value = _sample_laps()
        mock_models.get_channel_data.return_value = _minimal_channel_data()
        resp = client.get("/api/v1/sessions/s1/brake-temps?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False


# ══════════════════════════════════════════════════════════════════
# 7. /fuel endpoint
# ══════════════════════════════════════════════════════════════════


class TestFuelEndpoint:

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_fuel_single_lap(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_channel_data.return_value = _full_channel_data()
        resp = client.get("/api/v1/sessions/s1/fuel?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is True
        assert body["data"]["fuel"] == [45.0, 44.8, 44.5, 44.3, 44.0]

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_fuel_summary(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_gps_lap_numbers.return_value = [1, 2, 3]
        mock_models.get_channel_data.side_effect = [
            _full_channel_data(),    # lap 1 has fuel
            _minimal_channel_data(), # lap 2 no fuel
            _full_channel_data(),    # lap 3 has fuel
        ]
        resp = client.get("/api/v1/sessions/s1/fuel")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is True
        assert len(body["data"]["laps"]) == 2  # laps 1 and 3 have fuel
        assert body["data"]["laps"][0]["lap_number"] == 1
        assert body["data"]["laps"][0]["fuel_start"] == 45.0

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_fuel_no_data(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        mock_models.get_channel_data.return_value = _minimal_channel_data()
        resp = client.get("/api/v1/sessions/s1/fuel?lap=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_fuel_no_session(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = None
        resp = client.get("/api/v1/sessions/nosuch/fuel")
        assert resp.status_code == 404

    @patch("web.routes.data_v2_channels.models")
    @patch("web.routes.data_v2_channels.get_db_connection")
    def test_fuel_invalid_lap(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _sample_session()
        resp = client.get("/api/v1/sessions/s1/fuel?lap=abc")
        assert resp.status_code == 400
