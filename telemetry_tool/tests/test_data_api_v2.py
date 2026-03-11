"""Tests for data-serving API endpoints (Tasks 1.3 + 1.5).

Endpoints under test:
    GET    /api/v1/sessions                       - List sessions
    GET    /api/v1/sessions/<id>                   - Session detail
    GET    /api/v1/sessions/<id>/laps              - Lap list
    GET    /api/v1/sessions/<id>/speed-trace?lap=N - Speed vs distance
    GET    /api/v1/sessions/<id>/gps-trace?lap=N   - GPS coordinates + speed
    GET    /api/v1/sessions/<id>/gg-data?lap=N     - GG diagram data
    GET    /api/v1/sessions/<id>/scores            - Score breakdown
    GET    /api/v1/sessions/<id>/corners           - Corner coaching
    DELETE /api/v1/sessions/<id>                   - Delete session
    GET    /api/v1/compare/sessions?a=X&b=Y        - Session comparison
    GET    /api/v1/sessions/<id>/report?format=html - Report download
    PATCH  /api/v1/sessions/<id>                   - Update session fields

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
    """Minimal Flask app with data_v2 blueprint."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False

    from web.routes.data_v2 import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── Sample data builders ─────────────────────────────────────────


def _sample_sessions():
    """Two sample session dicts as returned by models.get_sessions()."""
    return [
        {
            "session_id": "s1",
            "csv_filename": "test1.csv",
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
        },
        {
            "session_id": "s2",
            "csv_filename": "test2.csv",
            "driver_id": 1,
            "driver_name": "TestDriver",
            "track_id": "t1",
            "track_name": "TestTrack",
            "session_type": "qualifying",
            "track_state": "dry",
            "session_date": "2024-01-02",
            "n_laps": 15,
            "best_lap_time_s": 58.5,
            "mean_lap_time_s": 59.5,
            "total_score": 85.0,
            "grade": "A",
        },
    ]


def _sample_session():
    return _sample_sessions()[0]


def _sample_laps():
    return [
        {"session_id": "s1", "lap_number": 1, "lap_time_s": 62.1, "is_valid": 1, "is_best": 0},
        {"session_id": "s1", "lap_number": 2, "lap_time_s": 61.5, "is_valid": 1, "is_best": 0},
        {"session_id": "s1", "lap_number": 3, "lap_time_s": 60.8, "is_valid": 1, "is_best": 1},
    ]


def _sample_gps_trace():
    return {
        "latitudes": [45.0, 45.001, 45.002],
        "longitudes": [7.0, 7.001, 7.002],
        "distances": [0.0, 50.0, 100.0],
        "speeds": [10.0, 15.0, 12.0],
        "accel_lat": [0.1, -0.2, 0.05],
        "accel_long": [0.5, 0.3, -0.4],
    }


def _sample_score_details():
    return {
        "session_id": "s1",
        "pace_score": 18,
        "pace_max": 25,
        "consistency_score": 15,
        "consistency_max": 25,
        "execution_score": 20,
        "execution_max": 25,
        "robustness_score": 22,
        "robustness_max": 25,
        "strengths_json": '["Good consistency"]',
        "strengths": ["Good consistency"],
        "weaknesses_json": '["Late braking"]',
        "weaknesses": ["Late braking"],
        "adaptation_score": None,
    }


def _sample_theoretical_data():
    return {
        "session_id": "s1",
        "theoretical_time_s": 58.0,
        "actual_best_time_s": 60.0,
        "gap_pct": 3.45,
        "simulation_method": "min_curvature",
        "speed_profile_json": "[10, 15, 12]",
        "speeds": [10, 15, 12],
        "distance_json": "[0, 50, 100]",
        "distances": [0, 50, 100],
        "metrics_json": '{"top_speed": 120}',
        "metrics": {"top_speed": 120},
        "corner_coaching_json": json.dumps([
            {"corner_id": 1, "advice": "Brake later", "time_loss_ms": 50},
            {"corner_id": 2, "advice": "Earlier throttle", "time_loss_ms": 30},
        ]),
        "corner_coaching": [
            {"corner_id": 1, "advice": "Brake later", "time_loss_ms": 50},
            {"corner_id": 2, "advice": "Earlier throttle", "time_loss_ms": 30},
        ],
        "delta_map_json": None,
        "session_scalars_json": None,
    }


# ══════════════════════════════════════════════════════════════════
# 1. GET /api/v1/sessions — List sessions
# ══════════════════════════════════════════════════════════════════


class TestListSessions:

    def test_list_sessions_returns_envelope(self, client):
        """GET /api/v1/sessions returns {ok, data} with a list."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_sessions.return_value = _sample_sessions()
            mock_models.count_sessions.return_value = 2
            mock_models.count_sessions_filtered.return_value = 2

            resp = client.get("/api/v1/sessions")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert isinstance(body["data"]["sessions"], list)
        assert len(body["data"]["sessions"]) == 2
        assert body["data"]["sessions"][0]["session_id"] == "s1"

    def test_list_sessions_pagination_meta(self, client):
        """Response includes pagination metadata (total, limit, offset)."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_sessions.return_value = _sample_sessions()[:1]
            mock_models.count_sessions.return_value = 50
            mock_models.count_sessions_filtered.return_value = 50

            resp = client.get("/api/v1/sessions?limit=1&offset=0")

        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["total"] == 50

    def test_list_sessions_empty(self, client):
        """Returns empty list when no sessions exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_sessions.return_value = []
            mock_models.count_sessions.return_value = 0
            mock_models.count_sessions_filtered.return_value = 0

            resp = client.get("/api/v1/sessions")

        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["sessions"] == []
        assert body["data"]["total"] == 0


# ══════════════════════════════════════════════════════════════════
# 2. GET /api/v1/sessions/<id> — Session detail
# ══════════════════════════════════════════════════════════════════


class TestGetSession:

    def test_get_session_found(self, client):
        """Returns session data when session exists."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()

            resp = client.get("/api/v1/sessions/s1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["session_id"] == "s1"
        assert body["data"]["driver_name"] == "TestDriver"

    def test_get_session_not_found(self, client):
        """Returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/nonexistent")

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════
# 3. GET /api/v1/sessions/<id>/laps — Lap list
# ══════════════════════════════════════════════════════════════════


class TestGetLaps:

    def test_get_laps_returns_list(self, client):
        """Returns list of laps for a session."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_laps_for_session.return_value = _sample_laps()

            resp = client.get("/api/v1/sessions/s1/laps")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert isinstance(body["data"]["laps"], list)
        assert len(body["data"]["laps"]) == 3

    def test_get_laps_session_not_found(self, client):
        """Returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/nonexistent/laps")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 4. GET /api/v1/sessions/<id>/speed-trace?lap=N
# ══════════════════════════════════════════════════════════════════


class TestSpeedTrace:

    def test_speed_trace_explicit_lap(self, client):
        """Returns distances and speeds arrays for a given lap."""
        trace = _sample_gps_trace()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["distances"] == [0.0, 50.0, 100.0]
        assert body["data"]["speeds"] == [10.0, 15.0, 12.0]
        assert body["data"]["lap_number"] == 2

    def test_speed_trace_best_lap_fallback(self, client):
        """When no lap param, uses best lap from laps list."""
        laps = _sample_laps()  # lap 3 has is_best=1
        trace = _sample_gps_trace()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_laps_for_session.return_value = laps
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/speed-trace")

        assert resp.status_code == 200
        body = resp.get_json()
        # Should have selected lap 3 (the best lap)
        assert body["data"]["lap_number"] == 3

    def test_speed_trace_no_data(self, client):
        """Returns 200 with available:false when no GPS trace exists."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = None

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_speed_trace"

    def test_speed_trace_session_not_found(self, client):
        """Returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/nonexistent/speed-trace?lap=1")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 5. GET /api/v1/sessions/<id>/gps-trace?lap=N
# ══════════════════════════════════════════════════════════════════


class TestGpsTrace:

    def test_gps_trace_returns_coords(self, client):
        """Returns lat, lon, distances, speeds arrays."""
        trace = _sample_gps_trace()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/gps-trace?lap=1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["latitudes"] == [45.0, 45.001, 45.002]
        assert body["data"]["longitudes"] == [7.0, 7.001, 7.002]
        assert body["data"]["distances"] == [0.0, 50.0, 100.0]
        assert body["data"]["speeds"] == [10.0, 15.0, 12.0]
        assert body["data"]["lap_number"] == 1

    def test_gps_trace_no_data(self, client):
        """Returns 200 with available:false when no GPS trace for that lap."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = None

            resp = client.get("/api/v1/sessions/s1/gps-trace?lap=99")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_gps_data"


# ══════════════════════════════════════════════════════════════════
# 6. GET /api/v1/sessions/<id>/gg-data?lap=N
# ══════════════════════════════════════════════════════════════════


class TestGGData:

    def test_gg_data_returns_accel_arrays(self, client):
        """Returns lat_g and lon_g arrays for GG diagram."""
        trace = _sample_gps_trace()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/gg-data?lap=1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["accel_lat"] == [0.1, -0.2, 0.05]
        assert body["data"]["accel_long"] == [0.5, 0.3, -0.4]
        assert body["data"]["lap_number"] == 1

    def test_gg_data_missing_accel(self, client):
        """Returns 200 with empty arrays and available=false when no accel data."""
        trace = {
            "latitudes": [45.0],
            "longitudes": [7.0],
            "distances": [0.0],
            "speeds": [10.0],
            # No accel_lat or accel_long
        }
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/gg-data?lap=1")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["accel_lat"] == []
        assert data["accel_long"] == []
        assert data["available"] is False

    def test_gg_data_no_trace(self, client):
        """Returns 200 with available=false when no GPS trace for that lap."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = None

            resp = client.get("/api/v1/sessions/s1/gg-data?lap=1")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is False


# ══════════════════════════════════════════════════════════════════
# 7. GET /api/v1/sessions/<id>/scores
# ══════════════════════════════════════════════════════════════════


class TestScores:

    def test_scores_returns_breakdown(self, client):
        """Returns score details with sub-scores."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_score_details.return_value = _sample_score_details()

            resp = client.get("/api/v1/sessions/s1/scores")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]
        assert data["pace_score"] == 18
        assert data["pace_max"] == 25
        assert data["consistency_score"] == 15
        assert data["strengths"] == ["Good consistency"]

    def test_scores_not_found(self, client):
        """Returns 200 with available:false when no score details exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_score_details.return_value = None

            resp = client.get("/api/v1/sessions/s1/scores")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "NO_SCORE_DATA"

    def test_scores_session_not_found(self, client):
        """Returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/nonexistent/scores")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 8. GET /api/v1/sessions/<id>/corners
# ══════════════════════════════════════════════════════════════════


class TestCorners:

    def test_corners_boundaries_with_coaching(self, client):
        """Boundaries from corner_metrics merged with coaching from theoretical."""
        theo = _sample_theoretical_data()
        # Coaching entries with CornerPerformance.to_dict() field names
        theo["corner_coaching"] = [
            {
                "corner_id": 1, "s_start": 100.0, "s_end": 200.0,
                "s_apex": 150.0, "direction": "L",
                "actual_entry_speed_mps": 25.0,
                "theoretical_entry_speed_mps": 27.0,
                "actual_apex_speed_mps": 18.0,
                "theoretical_apex_speed_mps": 20.0,
                "actual_exit_speed_mps": 22.0,
                "theoretical_exit_speed_mps": 24.0,
                "time_loss_s": 0.35,
                "grip_utilisation_pct": 82.0,
                "primary_cause": "late_braking",
                "coaching_hint": "Brake 5m earlier",
            },
            {
                "corner_id": 2, "s_start": 350.0, "s_end": 450.0,
                "s_apex": 400.0, "direction": "R",
                "actual_entry_speed_mps": 30.0,
                "theoretical_entry_speed_mps": 31.0,
                "actual_apex_speed_mps": 22.0,
                "theoretical_apex_speed_mps": 23.0,
                "actual_exit_speed_mps": 28.0,
                "theoretical_exit_speed_mps": 29.0,
                "time_loss_s": 0.12,
                "grip_utilisation_pct": 91.0,
                "primary_cause": None,
                "coaching_hint": "Well driven",
            },
        ]
        boundary_rows = [
            {"corner_id": 1, "n_laps": 5, "avg_entry_speed": 25.0,
             "avg_apex_speed": 18.0, "avg_exit_speed": 22.0,
             "avg_grip": 0.82, "avg_time_loss_ms": 350.0,
             "total_time_loss_ms": 1750.0},
            {"corner_id": 2, "n_laps": 5, "avg_entry_speed": 30.0,
             "avg_apex_speed": 22.0, "avg_exit_speed": 28.0,
             "avg_grip": 0.91, "avg_time_loss_ms": 120.0,
             "total_time_loss_ms": 600.0},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_corner_metrics_summary.return_value = boundary_rows
            mock_models.get_theoretical_data.return_value = theo
            mock_models.get_analysis_json.return_value = None

            resp = client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]
        assert data["available"] is True
        assert isinstance(data["corners"], list)
        assert len(data["corners"]) == 2
        c1 = data["corners"][0]
        assert c1["corner_id"] == 1
        assert c1["available"] is True
        assert c1["s_start"] == 100.0
        assert c1["direction"] == "L"
        assert c1["entry_speed_actual"] == 25.0
        assert c1["entry_speed_theory"] == 27.0
        assert c1["coaching_hint"] == "Brake 5m earlier"

    def test_corners_boundaries_without_coaching(self, client):
        """Boundaries exist but no theoretical data -- corners still returned."""
        boundary_rows = [
            {"corner_id": 1, "n_laps": 3, "avg_entry_speed": 25.0,
             "avg_apex_speed": 18.0, "avg_exit_speed": 22.0,
             "avg_grip": 0.80, "avg_time_loss_ms": 300.0,
             "total_time_loss_ms": 900.0},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_corner_metrics_summary.return_value = boundary_rows
            mock_models.get_theoretical_data.return_value = None
            mock_models.get_analysis_json.return_value = None

            resp = client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is True
        assert len(data["corners"]) == 1
        c = data["corners"][0]
        assert c["corner_id"] == 1
        assert c["available"] is False
        assert c["coaching_hint"] == "Theoretical data unavailable for this corner"
        assert c["entry_speed_actual"] is None
        assert c["time_loss_total_s"] is None

    def test_corners_no_boundaries_coaching_fallback(self, client):
        """No boundary data but coaching exists -- uses coaching as fallback."""
        theo = _sample_theoretical_data()
        theo["corner_coaching"] = [
            {
                "corner_id": 1, "s_start": 100.0, "s_end": 200.0,
                "s_apex": 150.0, "direction": "L",
                "actual_entry_speed_mps": 25.0,
                "theoretical_entry_speed_mps": 27.0,
                "actual_apex_speed_mps": 18.0,
                "theoretical_apex_speed_mps": 20.0,
                "actual_exit_speed_mps": 22.0,
                "theoretical_exit_speed_mps": 24.0,
                "time_loss_s": 0.35,
                "grip_utilisation_pct": 82.0,
                "primary_cause": "late_braking",
                "coaching_hint": "Brake 5m earlier",
            },
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_corner_metrics_summary.return_value = []
            mock_models.get_theoretical_data.return_value = theo
            mock_models.get_analysis_json.return_value = None

            resp = client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is True
        assert len(data["corners"]) == 1
        assert data["corners"][0]["available"] is True
        assert data["corners"][0]["corner_id"] == 1

    def test_corners_no_data_at_all(self, client):
        """No boundaries and no coaching -- returns empty with available=false."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_corner_metrics_summary.return_value = []
            mock_models.get_theoretical_data.return_value = None
            mock_models.get_analysis_json.return_value = None

            resp = client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["corners"] == []
        assert data["available"] is False
        assert data["reason_code"] == "NO_CORNER_DATA"

    def test_corners_session_not_found(self, client):
        """Returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/nonexistent/corners")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 9. DELETE /api/v1/sessions/<id>
# ══════════════════════════════════════════════════════════════════


class TestDeleteSession:

    def test_delete_session_success(self, client):
        """DELETE removes session and returns 200."""
        mock_conn = MagicMock()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models, \
             patch("web.routes.data_v2.soft_delete_session") as mock_soft_del:
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.return_value = _sample_session()

            resp = client.delete("/api/v1/sessions/s1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["deleted"] == "s1"
        mock_soft_del.assert_called_once_with(mock_conn, "s1")
        mock_conn.commit.assert_called_once()

    def test_delete_session_not_found(self, client):
        """DELETE returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.delete("/api/v1/sessions/nonexistent")

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False


# ══════════════════════════════════════════════════════════════════
# 10. GET /api/v1/compare/sessions?a=X&b=Y — Session comparison
# ══════════════════════════════════════════════════════════════════


class TestCompareSessions:

    def test_compare_both_found(self, client):
        """Returns side-by-side data when both sessions exist."""
        sessions = _sample_sessions()  # s1 and s2
        laps_a = _sample_laps()
        laps_b = [
            {"session_id": "s2", "lap_number": 1, "lap_time_s": 59.0, "is_valid": 1, "is_best": 1},
        ]
        score_a = _sample_score_details()
        score_b = {
            "session_id": "s2",
            "pace_score": 22,
            "pace_max": 25,
            "consistency_score": 20,
            "consistency_max": 25,
            "execution_score": 22,
            "execution_max": 25,
            "robustness_score": 21,
            "robustness_max": 25,
        }
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = lambda conn, sid: (
                sessions[0] if sid == "s1" else sessions[1] if sid == "s2" else None
            )
            mock_models.get_score_details.side_effect = lambda conn, sid: (
                score_a if sid == "s1" else score_b if sid == "s2" else None
            )
            mock_models.get_laps_for_session.side_effect = lambda conn, sid: (
                laps_a if sid == "s1" else laps_b if sid == "s2" else []
            )

            resp = client.get("/api/v1/compare/sessions?a=s1&b=s2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]
        assert "session_a" in data
        assert "session_b" in data
        assert data["session_a"]["session"]["session_id"] == "s1"
        assert data["session_b"]["session"]["session_id"] == "s2"
        assert data["session_a"]["scores"]["pace_score"] == 18
        assert data["session_b"]["scores"]["pace_score"] == 22
        assert len(data["session_a"]["laps"]) == 3
        assert len(data["session_b"]["laps"]) == 1

    def test_compare_missing_param_a(self, client):
        """Returns 400 when ?a= is missing."""
        resp = client.get("/api/v1/compare/sessions?b=s2")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
        assert "required" in body["error"]["message"].lower()

    def test_compare_missing_param_b(self, client):
        """Returns 400 when ?b= is missing."""
        resp = client.get("/api/v1/compare/sessions?a=s1")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False

    def test_compare_missing_both_params(self, client):
        """Returns 400 when both ?a= and ?b= are missing."""
        resp = client.get("/api/v1/compare/sessions")
        assert resp.status_code == 400

    def test_compare_session_a_not_found(self, client):
        """Returns 404 when session A does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = lambda conn, sid: (
                None if sid == "s1" else _sample_sessions()[1]
            )

            resp = client.get("/api/v1/compare/sessions?a=s1&b=s2")

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
        assert "s1" in body["error"]["message"]

    def test_compare_session_b_not_found(self, client):
        """Returns 404 when session B does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = lambda conn, sid: (
                _sample_sessions()[0] if sid == "s1" else None
            )

            resp = client.get("/api/v1/compare/sessions?a=s1&b=s2")

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
        assert "s2" in body["error"]["message"]

    def test_compare_no_scores_still_works(self, client):
        """Comparison succeeds even when sessions have no scores."""
        sessions = _sample_sessions()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = lambda conn, sid: (
                sessions[0] if sid == "s1" else sessions[1] if sid == "s2" else None
            )
            mock_models.get_score_details.return_value = None
            mock_models.get_laps_for_session.return_value = []

            resp = client.get("/api/v1/compare/sessions?a=s1&b=s2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["session_a"]["scores"] is None
        assert body["data"]["session_b"]["scores"] is None


# ══════════════════════════════════════════════════════════════════
# 11. GET /api/v1/sessions/<id>/report?format=html — Report download
# ══════════════════════════════════════════════════════════════════


class TestReportDownload:

    def test_report_download_success(self, client, tmp_path):
        """Returns the HTML report file when it exists."""
        # Create a temporary HTML report file under a results subdirectory
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        report_file = results_dir / "report.html"
        report_file.write_text("<html><body>Report</body></html>")

        session = _sample_session()
        session["html_report_path"] = str(report_file)

        # Set RESULTS_DIR so the path traversal check allows this path
        client.application.config["RESULTS_DIR"] = str(results_dir)

        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = session

            resp = client.get("/api/v1/sessions/s1/report?format=html")

        assert resp.status_code == 200
        assert b"<html><body>Report</body></html>" in resp.data

    def test_report_download_no_path(self, client):
        """Returns 404 when session has no html_report_path."""
        session = _sample_session()
        session["html_report_path"] = None

        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = session

            resp = client.get("/api/v1/sessions/s1/report?format=html")

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
        assert "not available" in body["error"]["message"].lower()

    def test_report_download_file_missing(self, client):
        """Returns 404 when html_report_path points to a nonexistent file."""
        session = _sample_session()
        session["html_report_path"] = "/nonexistent/path/report.html"

        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = session

            resp = client.get("/api/v1/sessions/s1/report?format=html")

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False

    def test_report_download_session_not_found(self, client):
        """Returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/nonexistent/report?format=html")

        assert resp.status_code == 404

    def test_report_download_unsupported_format(self, client):
        """Returns 400 when format is not 'html'."""
        session = _sample_session()
        session["html_report_path"] = "/some/path/report.html"

        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = session

            resp = client.get("/api/v1/sessions/s1/report?format=pdf")

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False


# ══════════════════════════════════════════════════════════════════
# 12. PATCH /api/v1/sessions/<id> — Update session fields
# ══════════════════════════════════════════════════════════════════


class TestUpdateSession:

    def test_update_session_type(self, client):
        """PATCH updates session_type and returns updated session."""
        session = _sample_session()
        updated = {**session, "session_type": "qualifying"}
        mock_conn = MagicMock()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.side_effect = [session, updated]

            resp = client.patch(
                "/api/v1/sessions/s1",
                json={"session_type": "qualifying"},
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["session_type"] == "qualifying"
        mock_models.update_session_field.assert_called_once_with(
            mock_conn, "s1", "session_type", "qualifying"
        )
        mock_conn.commit.assert_called_once()

    def test_update_notes(self, client):
        """PATCH updates notes field."""
        session = _sample_session()
        updated = {**session, "notes": "Good session"}
        mock_conn = MagicMock()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.side_effect = [session, updated]

            resp = client.patch(
                "/api/v1/sessions/s1",
                json={"notes": "Good session"},
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        mock_models.update_session_field.assert_called_once_with(
            mock_conn, "s1", "notes", "Good session"
        )

    def test_update_multiple_fields(self, client):
        """PATCH updates multiple fields at once."""
        session = _sample_session()
        updated = {**session, "session_type": "race", "track_state": "wet"}
        mock_conn = MagicMock()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.side_effect = [session, updated]

            resp = client.patch(
                "/api/v1/sessions/s1",
                json={"session_type": "race", "track_state": "wet"},
            )

        assert resp.status_code == 200
        assert mock_models.update_session_field.call_count == 2

    def test_update_driver_name(self, client):
        """PATCH with driver_name upserts driver and updates driver_id."""
        session = _sample_session()
        updated = {**session, "driver_name": "NewDriver"}
        mock_conn = MagicMock()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.side_effect = [session, updated]
            mock_models.upsert_driver.return_value = 42

            resp = client.patch(
                "/api/v1/sessions/s1",
                json={"driver_name": "NewDriver"},
            )

        assert resp.status_code == 200
        mock_models.upsert_driver.assert_called_once_with(mock_conn, "NewDriver")
        mock_models.update_session_field.assert_called_once_with(
            mock_conn, "s1", "driver_id", 42
        )

    def test_update_session_not_found(self, client):
        """PATCH returns 404 when session does not exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.patch(
                "/api/v1/sessions/nonexistent",
                json={"notes": "test"},
            )

        assert resp.status_code == 404

    def test_update_empty_body(self, client):
        """PATCH returns 400 when no updatable fields in body."""
        session = _sample_session()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = session

            resp = client.patch(
                "/api/v1/sessions/s1",
                json={},
            )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False

    def test_update_disallowed_field(self, client):
        """PATCH ignores non-updatable fields and returns 400 if none are valid."""
        session = _sample_session()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = session

            resp = client.patch(
                "/api/v1/sessions/s1",
                json={"session_id": "hacked", "total_score": 100},
            )

        assert resp.status_code == 400

    def test_update_no_json_body(self, client):
        """PATCH returns 400 when body is not JSON."""
        session = _sample_session()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = session

            resp = client.patch(
                "/api/v1/sessions/s1",
                data="not json",
                content_type="text/plain",
            )

        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════
# CONTRACT TESTS — Verify exact response shapes the frontend expects
# ══════════════════════════════════════════════════════════════════


class TestSpeedTraceContract:
    """Speed trace response must match:
    {ok: true, data: {lap_number: int, distances: list, speeds: list}}
    """

    def test_speed_trace_contract(self, client):
        """Verify speed trace response has the exact keys and types."""
        trace = _sample_gps_trace()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1")

        body = resp.get_json()

        # Envelope shape
        assert "ok" in body
        assert body["ok"] is True
        assert "data" in body
        assert "meta" in body

        # Data shape
        data = body["data"]
        assert "lap_number" in data, "Contract: must have lap_number"
        assert "distances" in data, "Contract: must have distances"
        assert "speeds" in data, "Contract: must have speeds"

        # Types
        assert isinstance(data["lap_number"], int)
        assert isinstance(data["distances"], list)
        assert isinstance(data["speeds"], list)

        # No extra unexpected keys
        expected_keys = {"lap_number", "distances", "speeds", "available"}
        assert set(data.keys()) == expected_keys, \
            f"Speed trace data keys should be {expected_keys}, got {set(data.keys())}"


class TestGpsTraceContract:
    """GPS trace response must match:
    {ok: true, data: {lap_number: int, latitudes: list, longitudes: list, distances: list, speeds: list}}
    """

    def test_gps_trace_contract(self, client):
        """Verify GPS trace response has the exact keys and types."""
        trace = _sample_gps_trace()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/gps-trace?lap=1")

        body = resp.get_json()

        # Envelope shape
        assert body["ok"] is True
        assert "data" in body

        # Data shape
        data = body["data"]
        assert "lap_number" in data, "Contract: must have lap_number"
        assert "latitudes" in data, "Contract: must have latitudes"
        assert "longitudes" in data, "Contract: must have longitudes"
        assert "distances" in data, "Contract: must have distances"
        assert "speeds" in data, "Contract: must have speeds"

        # Types
        assert isinstance(data["lap_number"], int)
        assert isinstance(data["latitudes"], list)
        assert isinstance(data["longitudes"], list)
        assert isinstance(data["distances"], list)
        assert isinstance(data["speeds"], list)

        # Verify array lengths match
        assert len(data["latitudes"]) == len(data["longitudes"]) == len(data["distances"]) == len(data["speeds"]), \
            "All arrays in GPS trace should have equal length"

        # No extra unexpected keys
        expected_keys = {"lap_number", "latitudes", "longitudes", "distances", "speeds", "available"}
        assert set(data.keys()) == expected_keys, \
            f"GPS trace data keys should be {expected_keys}, got {set(data.keys())}"


class TestGGDataContract:
    """GG data response must match:
    {ok: true, data: {lap_number: int, accel_lat: list, accel_long: list}}
    """

    def test_gg_data_contract(self, client):
        """Verify GG data response has the exact keys and types."""
        trace = _sample_gps_trace()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = trace

            resp = client.get("/api/v1/sessions/s1/gg-data?lap=1")

        body = resp.get_json()

        # Envelope shape
        assert body["ok"] is True
        assert "data" in body

        # Data shape
        data = body["data"]
        assert "lap_number" in data, "Contract: must have lap_number"
        assert "accel_lat" in data, "Contract: must have accel_lat"
        assert "accel_long" in data, "Contract: must have accel_long"

        # Types
        assert isinstance(data["lap_number"], int)
        assert isinstance(data["accel_lat"], list)
        assert isinstance(data["accel_long"], list)

        # Verify array lengths match
        assert len(data["accel_lat"]) == len(data["accel_long"]), \
            "accel_lat and accel_long arrays should have equal length"

        # Availability flag
        assert "available" in data, "Contract: must have available flag"
        assert isinstance(data["available"], bool)

        # No extra unexpected keys
        expected_keys = {"lap_number", "accel_lat", "accel_long", "distances", "available"}
        assert set(data.keys()) == expected_keys, \
            f"GG data keys should be {expected_keys}, got {set(data.keys())}"


class TestSessionsListContract:
    """Sessions list response must match:
    {ok: true, data: {sessions: list, total: int, ...}, meta: {total: int}}
    """

    def test_sessions_list_contract(self, client):
        """Verify sessions list response has the exact structure."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_sessions.return_value = _sample_sessions()
            mock_models.count_sessions.return_value = 2
            mock_models.count_sessions_filtered.return_value = 2

            resp = client.get("/api/v1/sessions")

        body = resp.get_json()

        # Envelope shape
        assert body["ok"] is True
        assert "data" in body
        assert "meta" in body

        # Data shape
        data = body["data"]
        assert "sessions" in data, "Contract: must have sessions"
        assert "total" in data, "Contract: must have total"

        # Types
        assert isinstance(data["sessions"], list)
        assert isinstance(data["total"], int)

        # Each session has required keys
        if len(data["sessions"]) > 0:
            session = data["sessions"][0]
            required_keys = {"session_id", "total_score", "grade"}
            for key in required_keys:
                assert key in session, \
                    f"Contract: each session must have '{key}'"

    def test_sessions_list_empty_contract(self, client):
        """Empty sessions list still has the correct shape."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_sessions.return_value = []
            mock_models.count_sessions.return_value = 0
            mock_models.count_sessions_filtered.return_value = 0

            resp = client.get("/api/v1/sessions")

        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["sessions"] == []
        assert body["data"]["total"] == 0


class TestCompareSessionsContract:
    """Compare response must match:
    {ok: true, data: {
        session_a: {session: dict, scores: dict|null, laps: list},
        session_b: {session: dict, scores: dict|null, laps: list}
    }}
    """

    def test_compare_contract(self, client):
        """Verify compare response has the exact structure."""
        sessions = _sample_sessions()
        laps_a = _sample_laps()
        laps_b = [
            {"session_id": "s2", "lap_number": 1, "lap_time_s": 59.0, "is_valid": 1, "is_best": 1},
        ]
        score_a = _sample_score_details()
        score_b = {
            "session_id": "s2",
            "pace_score": 22,
            "pace_max": 25,
            "consistency_score": 20,
            "consistency_max": 25,
            "execution_score": 22,
            "execution_max": 25,
            "robustness_score": 21,
            "robustness_max": 25,
        }

        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = lambda conn, sid: (
                sessions[0] if sid == "s1" else sessions[1] if sid == "s2" else None
            )
            mock_models.get_score_details.side_effect = lambda conn, sid: (
                score_a if sid == "s1" else score_b if sid == "s2" else None
            )
            mock_models.get_laps_for_session.side_effect = lambda conn, sid: (
                laps_a if sid == "s1" else laps_b if sid == "s2" else []
            )

            resp = client.get("/api/v1/compare/sessions?a=s1&b=s2")

        body = resp.get_json()

        # Envelope shape
        assert body["ok"] is True
        assert "data" in body

        data = body["data"]

        # Top-level keys
        assert "session_a" in data, "Contract: must have session_a"
        assert "session_b" in data, "Contract: must have session_b"

        # session_a shape
        sa = data["session_a"]
        assert "session" in sa, "Contract: session_a must have session"
        assert "scores" in sa, "Contract: session_a must have scores"
        assert "laps" in sa, "Contract: session_a must have laps"

        # session_b shape
        sb = data["session_b"]
        assert "session" in sb, "Contract: session_b must have session"
        assert "scores" in sb, "Contract: session_b must have scores"
        assert "laps" in sb, "Contract: session_b must have laps"

        # Types
        assert isinstance(sa["session"], dict)
        assert isinstance(sa["scores"], dict)
        assert isinstance(sa["laps"], list)
        assert isinstance(sb["session"], dict)
        assert isinstance(sb["scores"], dict)
        assert isinstance(sb["laps"], list)

        # Session objects have session_id
        assert "session_id" in sa["session"]
        assert "session_id" in sb["session"]

        # Scores have required sub-score keys
        for side_label, side in [("session_a", sa), ("session_b", sb)]:
            scores = side["scores"]
            if scores is not None:
                assert "pace_score" in scores, \
                    f"Contract: {side_label}.scores must have pace_score"
                assert "pace_max" in scores, \
                    f"Contract: {side_label}.scores must have pace_max"

    def test_compare_null_scores_contract(self, client):
        """Compare response with null scores still has correct shape."""
        sessions = _sample_sessions()

        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = lambda conn, sid: (
                sessions[0] if sid == "s1" else sessions[1] if sid == "s2" else None
            )
            mock_models.get_score_details.return_value = None
            mock_models.get_laps_for_session.return_value = []

            resp = client.get("/api/v1/compare/sessions?a=s1&b=s2")

        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]

        # With null scores, the structure should still be present
        assert "session_a" in data
        assert "session_b" in data
        assert data["session_a"]["scores"] is None
        assert data["session_b"]["scores"] is None
        assert isinstance(data["session_a"]["laps"], list)
        assert isinstance(data["session_b"]["laps"], list)


class TestErrorEnvelopeContract:
    """Error responses must match:
    {ok: false, error: {code: str, message: str}, meta: {...}}
    """

    def test_404_error_contract(self, client):
        """Verify 404 error responses have the correct envelope."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/nonexistent")

        assert resp.status_code == 404
        body = resp.get_json()

        # Envelope shape
        assert "ok" in body
        assert body["ok"] is False
        assert "error" in body
        assert "meta" in body

        # Error shape
        error = body["error"]
        assert "code" in error, "Contract: error must have code"
        assert "message" in error, "Contract: error must have message"
        assert isinstance(error["code"], str)
        assert isinstance(error["message"], str)

    def test_400_error_contract(self, client):
        """Verify 400 error responses have the correct envelope."""
        resp = client.get("/api/v1/compare/sessions")  # Missing a and b

        assert resp.status_code == 400
        body = resp.get_json()

        assert body["ok"] is False
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]


# ══════════════════════════════════════════════════════════════════
# NEW ENDPOINTS — Tests for 15 added endpoints (Phase 2)
# ══════════════════════════════════════════════════════════════════


def _sample_corner_metrics():
    return [
        {"session_id": "s1", "lap_number": 1, "corner_id": 1,
         "brake_point_m": 50.0, "brake_intensity": 0.8,
         "entry_speed_mps": 20.0, "apex_speed_mps": 15.0,
         "exit_speed_mps": 18.0, "throttle_onset_m": 55.0,
         "exit_accel_mps2": 3.0, "grip_utilization": 0.9,
         "time_loss_ms": 50.0, "coaching_hint": "Brake later"},
        {"session_id": "s1", "lap_number": 1, "corner_id": 2,
         "brake_point_m": 120.0, "brake_intensity": 0.7,
         "entry_speed_mps": 22.0, "apex_speed_mps": 16.0,
         "exit_speed_mps": 19.0, "throttle_onset_m": 125.0,
         "exit_accel_mps2": 2.5, "grip_utilization": 0.85,
         "time_loss_ms": 30.0, "coaching_hint": "Earlier throttle"},
        {"session_id": "s1", "lap_number": 2, "corner_id": 1,
         "brake_point_m": 51.0, "brake_intensity": 0.8,
         "entry_speed_mps": 20.5, "apex_speed_mps": 15.2,
         "exit_speed_mps": 18.5, "throttle_onset_m": 56.0,
         "exit_accel_mps2": 3.1, "grip_utilization": 0.91,
         "time_loss_ms": 45.0, "coaching_hint": "Good"},
    ]


def _sample_corner_summary():
    return [
        {"corner_id": 1, "n_laps": 2, "avg_brake_point_m": 50.5,
         "min_brake_point_m": 50.0, "max_brake_point_m": 51.0,
         "avg_entry_speed": 20.25, "avg_apex_speed": 15.1,
         "avg_exit_speed": 18.25, "avg_grip": 0.905,
         "avg_time_loss_ms": 47.5, "total_time_loss_ms": 95.0},
        {"corner_id": 2, "n_laps": 1, "avg_brake_point_m": 120.0,
         "min_brake_point_m": 120.0, "max_brake_point_m": 120.0,
         "avg_entry_speed": 22.0, "avg_apex_speed": 16.0,
         "avg_exit_speed": 19.0, "avg_grip": 0.85,
         "avg_time_loss_ms": 30.0, "total_time_loss_ms": 30.0},
    ]


def _sample_driving_style():
    return {
        "driver_id": 1, "session_id": "s1",
        "trail_braking_depth": 0.6, "brake_point_consistency": 0.85,
        "brake_pressure_buildup_rate": 0.7, "apex_speed_ratio": 0.92,
        "turn_in_aggressiveness": 0.65, "throttle_onset_delay_m": 2.5,
        "exit_acceleration_efficiency": 0.88, "line_variation_index": 0.15,
        "early_vs_late_stint_pace": 0.02, "smoothness_composite": 0.78,
        "style_label": "Smooth Precision", "style_confidence": 0.85,
        "strengths_json": '["Consistent braking"]',
        "strengths": ["Consistent braking"],
        "weaknesses_json": '["Late throttle"]',
        "weaknesses": ["Late throttle"],
    }


def _sample_analysis_json():
    return {
        "sector_analysis": {
            "n_sectors": 3, "n_laps": 5,
            "ideal_lap_time_s": 59.5, "actual_best_lap_time_s": 60.0,
            "ideal_gap_s": 0.5, "weakest_sector": 1, "strongest_sector": 0,
            "sector_stats": [], "sector_timings": [], "coaching": "Focus on sector 2",
        },
        "robustness_metrics": {"early_mean_s": 61.2, "late_mean_s": 61.8},
        "consistency_metrics": {"cv_pct": 1.2, "std_dev_s": 0.7},
    }


def _sample_reference_line():
    return {
        "latitudes": [45.0, 45.001, 45.002, 45.003],
        "longitudes": [7.0, 7.001, 7.002, 7.003],
        "distances": [0.0, 50.0, 100.0, 150.0],
        "speeds": [10.0, 15.0, 12.0, 14.0],
    }


class TestTheoreticalEndpoint:

    def test_returns_theoretical_data(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = _sample_theoretical_data()

            resp = client.get("/api/v1/sessions/s1/theoretical")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["theoretical_time_s"] == 58.0
        assert "speeds" in body["data"]
        assert "distances" in body["data"]

    def test_404_no_session(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/FAKE/theoretical")

        assert resp.status_code == 404

    def test_structured_unavailability_no_theoretical_data(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = None

            resp = client.get("/api/v1/sessions/s1/theoretical")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_theoretical_data"


class TestReferenceLineEndpoint:

    def test_returns_reference_line(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_reference_line.return_value = _sample_reference_line()

            resp = client.get("/api/v1/sessions/s1/reference_line")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "latitudes" in body["data"]
        assert "longitudes" in body["data"]

    def test_404_no_session(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/FAKE/reference_line")

        assert resp.status_code == 404


class TestBestLapGpsEndpoint:

    def test_returns_best_lap_gps(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()

            resp = client.get("/api/v1/sessions/s1/best_lap_gps")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["lap_number"] == 3  # is_best lap


class TestCornerPositionsEndpoint:

    def test_returns_from_theoretical(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = _sample_theoretical_data()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_corner_metrics_summary.return_value = []

            resp = client.get("/api/v1/sessions/s1/corner-positions")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["corners"]) == 2

    def test_falls_back_to_corner_metrics(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = None
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_corner_metrics_summary.return_value = _sample_corner_summary()

            resp = client.get("/api/v1/sessions/s1/corner-positions")

        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["data"]["corners"]) == 2

    def test_404_no_data(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = None
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_corner_metrics_summary.return_value = []

            resp = client.get("/api/v1/sessions/s1/corner-positions")

        assert resp.status_code == 404

    def test_corners_have_lat_lon_from_gps(self, client):
        """Corner positions include lat/lon interpolated from best lap GPS trace."""
        theo = _sample_theoretical_data()
        # Add distance fields to coaching entries
        theo["corner_coaching"] = [
            {"corner_id": 1, "advice": "Brake later", "s_apex": 50.0,
             "s_start": 30.0, "s_end": 70.0, "direction": "left"},
            {"corner_id": 2, "advice": "Earlier throttle", "s_apex": 100.0,
             "s_start": 80.0, "s_end": 120.0, "direction": "right"},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = theo
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_corner_metrics_summary.return_value = []

            resp = client.get("/api/v1/sessions/s1/corner-positions")

        assert resp.status_code == 200
        body = resp.get_json()
        corners = body["data"]["corners"]
        assert len(corners) == 2
        for c in corners:
            assert "lat" in c
            assert "lon" in c
            assert c["lat"] is not None
            assert c["lon"] is not None

    def test_corners_have_brake_point_m(self, client):
        """Corner positions include brake_point_m from corner_metrics summary."""
        theo = _sample_theoretical_data()
        theo["corner_coaching"] = [
            {"corner_id": 1, "s_apex": 50.0},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = theo
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_corner_metrics_summary.return_value = [
                {"corner_id": 1, "avg_brake_point_m": 45.5,
                 "min_brake_point_m": 44.0, "max_brake_point_m": 47.0,
                 "n_laps": 3, "avg_entry_speed": 20.0,
                 "avg_apex_speed": 15.0, "avg_exit_speed": 18.0,
                 "avg_grip": 0.9, "avg_time_loss_ms": 50.0,
                 "total_time_loss_ms": 150.0},
            ]

            resp = client.get("/api/v1/sessions/s1/corner-positions")

        body = resp.get_json()
        c1 = body["data"]["corners"][0]
        assert c1["brake_point_m"] == 45.5


class TestCornerMetricsEndpoint:

    def test_returns_metrics(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_corner_metrics_for_session.return_value = _sample_corner_metrics()

            resp = client.get("/api/v1/sessions/s1/corner-metrics")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["corners"]) == 3

    def test_404_no_metrics(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_corner_metrics_for_session.return_value = []

            resp = client.get("/api/v1/sessions/s1/corner-metrics")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["corners"] == []
        assert data["available"] is False


class TestCornerMetricsSummaryEndpoint:

    def test_returns_summary(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_corner_metrics_summary.return_value = _sample_corner_summary()

            resp = client.get("/api/v1/sessions/s1/corner-metrics/summary")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["corners"]) == 2


class TestDeltaEndpoint:

    def test_computes_delta(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_gps_trace.side_effect = [_sample_gps_trace(), _sample_gps_trace()]

            resp = client.get("/api/v1/sessions/s1/delta?lap_a=1&lap_b=2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "distances" in body["data"]
        assert "delta_s" in body["data"]
        assert body["data"]["lap_a"] == 1
        assert body["data"]["lap_b"] == 2

    def test_400_missing_params(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()

            resp = client.get("/api/v1/sessions/s1/delta")

        assert resp.status_code == 400

    def test_structured_unavailability_missing_trace(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_gps_trace.return_value = None

            resp = client.get("/api/v1/sessions/s1/delta?lap_a=1&lap_b=99")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_gps_trace"


class TestFingerprintEndpoint:

    def test_returns_fingerprint(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_score_details.return_value = _sample_score_details()
            mm.get_driving_style.return_value = _sample_driving_style()

            resp = client.get("/api/v1/sessions/s1/fingerprint")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["dimensions"]) == 6
        assert len(body["data"]["values"]) == 6

    def test_structured_unavailability_no_scores(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_score_details.return_value = None

            resp = client.get("/api/v1/sessions/s1/fingerprint")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_score_data"


class TestDrivingStyleEndpoint:

    def test_returns_style(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_driving_style.return_value = _sample_driving_style()

            resp = client.get("/api/v1/sessions/s1/driving-style")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["style_label"] == "Smooth Precision"
        assert len(body["data"]["features"]) > 0

    def test_structured_unavailability_no_driver(self, client):
        session = _sample_session()
        session["driver_id"] = None
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = session

            resp = client.get("/api/v1/sessions/s1/driving-style")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_driver_linked"


class TestLapDistributionEndpoint:

    def test_returns_distribution(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()

            resp = client.get("/api/v1/sessions/s1/lap-distribution")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "bins" in body["data"]
        assert "counts" in body["data"]
        assert body["data"]["n_valid"] == 3

    def test_structured_unavailability_no_valid_laps(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = []

            resp = client.get("/api/v1/sessions/s1/lap-distribution")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_valid_lap_times"


class TestLapProgressEndpoint:

    def test_returns_progress(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()

            resp = client.get("/api/v1/sessions/s1/lap-progress")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "lap_numbers" in body["data"]
        assert "times" in body["data"]
        assert "rolling_avg" in body["data"]
        assert "trend_slope" in body["data"]
        assert isinstance(body["data"]["is_improving"], bool)

    def test_improving_trend(self, client):
        """Laps with decreasing times should show is_improving=True."""
        improving_laps = [
            {"session_id": "s1", "lap_number": 1, "lap_time_s": 63.0, "is_valid": 1, "is_best": 0},
            {"session_id": "s1", "lap_number": 2, "lap_time_s": 62.0, "is_valid": 1, "is_best": 0},
            {"session_id": "s1", "lap_number": 3, "lap_time_s": 61.0, "is_valid": 1, "is_best": 1},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = improving_laps

            resp = client.get("/api/v1/sessions/s1/lap-progress")

        body = resp.get_json()
        assert body["data"]["is_improving"] is True
        assert body["data"]["trend_slope"] < 0


class TestSpeedProfileEndpoint:

    def test_returns_profile(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_theoretical_data.return_value = _sample_theoretical_data()

            resp = client.get("/api/v1/sessions/s1/speed-profile")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "actual_speeds_kmh" in body["data"]
        assert "distances" in body["data"]


class TestBrakePrecisionEndpoint:

    def test_returns_brake_precision(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_corner_metrics_for_session.return_value = _sample_corner_metrics()

            resp = client.get("/api/v1/sessions/s1/brake-precision")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["corners"]) == 2  # 2 unique corner_ids
        c1 = body["data"]["corners"][0]
        assert "mean_m" in c1
        assert "std_m" in c1
        assert "cv_pct" in c1

    def test_empty_no_metrics(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_corner_metrics_for_session.return_value = []

            resp = client.get("/api/v1/sessions/s1/brake-precision")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["corners"] == []
        assert data["available"] is False


class TestStintAnalysisEndpoint:

    def test_returns_stints(self, client):
        stints = [
            {"stint_number": 1, "lap_start": 1, "lap_end": 5,
             "lap_count": 5, "best_time_s": 60.0, "mean_time_s": 61.0},
            {"stint_number": 2, "lap_start": 6, "lap_end": 10,
             "lap_count": 5, "best_time_s": 60.5, "mean_time_s": 61.5},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_stint_analysis.return_value = stints

            resp = client.get("/api/v1/sessions/s1/stint-analysis")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["stints"]) == 2

    def test_falls_back_to_analysis_json(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_stint_analysis.return_value = []
            mm.get_analysis_json.return_value = _sample_analysis_json()

            resp = client.get("/api/v1/sessions/s1/stint-analysis")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "robustness_metrics" in body["data"]

    def test_structured_unavailability_no_data(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_stint_analysis.return_value = []
            mm.get_analysis_json.return_value = None

            resp = client.get("/api/v1/sessions/s1/stint-analysis")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "no_stint_analysis"


class TestSectorTimesEndpoint:

    def test_returns_from_analysis_json(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_analysis_json.return_value = _sample_analysis_json()

            resp = client.get("/api/v1/sessions/s1/sector_times")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["n_sectors"] == 3

    def test_computes_on_fly_when_no_analysis_json(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_analysis_json.return_value = None
            mm.get_laps_for_session.return_value = _sample_laps()

            resp = client.get("/api/v1/sessions/s1/sector_times")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "n_sectors" in body["data"]

    def test_404_insufficient_laps(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_analysis_json.return_value = None
            mm.get_laps_for_session.return_value = [
                {"session_id": "s1", "lap_number": 1, "lap_time_s": 62.1,
                 "is_valid": 1, "is_best": 1},
            ]

            resp = client.get("/api/v1/sessions/s1/sector_times")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["available"] is False
        assert body["data"]["reason_code"] == "NO_SECTOR_DATA"


# ══════════════════════════════════════════════════════════════════
# Track Map Bundle Endpoint
# ══════════════════════════════════════════════════════════════════


class TestTrackMapEndpoint:

    def test_track_map_best_lap(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_gps_lap_numbers.return_value = [1, 2, 3]
            mm.get_theoretical_data.return_value = None
            mm.get_corner_metrics_summary.return_value = []

            resp = client.get("/api/v1/sessions/s1/track-map?lap=best")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "laps" in body["data"]
        assert "best_lap" in body["data"]
        assert "corners" in body["data"]
        assert str(body["data"]["best_lap"]) in body["data"]["laps"]

    def test_track_map_all_laps(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_gps_lap_numbers.return_value = [1, 2, 3]
            mm.get_theoretical_data.return_value = None
            mm.get_corner_metrics_summary.return_value = []

            resp = client.get("/api/v1/sessions/s1/track-map?lap=all")

        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["data"]["laps"]) == 3

    def test_track_map_404(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/FAKE/track-map")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# Speed Trace Ref Overlay
# ══════════════════════════════════════════════════════════════════


class TestSpeedTraceRef:

    def test_speed_trace_with_ref(self, client):
        """Speed trace with ?ref=Y returns ref_speeds interpolated."""
        trace_a = _sample_gps_trace()
        trace_b = {**_sample_gps_trace(), "speeds": [12.0, 17.0, 14.0]}
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.side_effect = [trace_a, trace_b]

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1&ref=2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "ref_speeds" in body["data"]
        assert body["data"]["ref_lap_number"] == 2
        assert len(body["data"]["ref_speeds"]) == len(body["data"]["distances"])

    def test_speed_trace_without_ref(self, client):
        """Speed trace without ref still works normally."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert "ref_speeds" not in body["data"]


# ══════════════════════════════════════════════════════════════════
# Sectors Alias Endpoint
# ══════════════════════════════════════════════════════════════════


class TestSectorsEndpoint:

    def test_sectors_returns_sector_analysis(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_analysis_json.return_value = _sample_analysis_json()

            resp = client.get("/api/v1/sessions/s1/sectors")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "n_sectors" in body["data"]

    def test_sectors_404(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/FAKE/sectors")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# Cross-Session Compare Overlay
# ══════════════════════════════════════════════════════════════════


class TestSessionCompareOverlay:

    def test_compare_returns_overlay(self, client):
        sessions = _sample_sessions()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.side_effect = [sessions[0], sessions[1]]
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()

            resp = client.get("/api/v1/sessions/s1/compare?sessionKeyB=s2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "distances" in body["data"]
        assert "speeds_a" in body["data"]
        assert "speeds_b" in body["data"]
        assert "delta_s" in body["data"]
        assert "gps_a" in body["data"]
        assert "gps_b" in body["data"]

    def test_compare_missing_session_b_param(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()

            resp = client.get("/api/v1/sessions/s1/compare")

        assert resp.status_code == 400

    def test_compare_session_b_not_found(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.side_effect = [_sample_session(), None]

            resp = client.get("/api/v1/sessions/s1/compare?sessionKeyB=FAKE")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# Dev Plans JSON API
# ══════════════════════════════════════════════════════════════════


class TestDevPlansEndpoint:

    @pytest.fixture
    def entities_client(self):
        """Client with api_v1_entities blueprint (where dev-plans routes live)."""
        from flask import Flask
        from web.routes.api_v1_entities import bp as entities_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["USE_PG"] = False
        app.register_blueprint(entities_bp)
        return app.test_client()

    def test_list_dev_plans(self, entities_client):
        with patch("web.routes.api_v1_entities._get_conn") as mock_db:
            conn = MagicMock()
            mock_db.return_value = conn
            conn.execute.return_value.fetchall.return_value = [
                {"id": 1, "driver_id": 1, "plan_name": "Beginner Plan",
                 "level": "beginner", "status": "active",
                 "weeks_json": "[]", "progress_json": "{}",
                 "created_at": "2026-01-01", "updated_at": "2026-01-01"},
            ]

            resp = entities_client.get("/api/v1/dev-plans")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        # list endpoint returns array directly in data
        plans = body["data"]
        assert isinstance(plans, list)
        assert len(plans) == 1
        assert plans[0]["plan_name"] == "Beginner Plan"

    def test_get_dev_plan_detail(self, entities_client):
        with patch("web.routes.api_v1_entities._get_conn") as mock_db:
            conn = MagicMock()
            mock_db.return_value = conn
            conn.execute.return_value.fetchone.return_value = {
                "id": 1, "driver_id": 1, "plan_name": "Beginner Plan",
                "level": "beginner", "status": "active",
                "weeks_json": '[{"week": 1, "drills": []}]',
                "progress_json": '{"completed_drills": 0}',
                "created_at": "2026-01-01", "updated_at": "2026-01-01",
            }

            resp = entities_client.get("/api/v1/dev-plans/1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["plan_name"] == "Beginner Plan"

    def test_get_dev_plan_not_found(self, entities_client):
        with patch("web.routes.api_v1_entities._get_conn") as mock_db:
            conn = MagicMock()
            mock_db.return_value = conn
            conn.execute.return_value.fetchone.return_value = None

            resp = entities_client.get("/api/v1/dev-plans/999")

        assert resp.status_code == 404


class TestNewEndpoints404ForMissingSession:
    """All new endpoints should return 404 for non-existent sessions."""

    NEW_PATHS = [
        "/api/v1/sessions/FAKE/theoretical",
        "/api/v1/sessions/FAKE/reference_line",
        "/api/v1/sessions/FAKE/best_lap_gps",
        "/api/v1/sessions/FAKE/corner-positions",
        "/api/v1/sessions/FAKE/corner-metrics",
        "/api/v1/sessions/FAKE/corner-metrics/summary",
        "/api/v1/sessions/FAKE/delta?lap_a=1&lap_b=2",
        "/api/v1/sessions/FAKE/fingerprint",
        "/api/v1/sessions/FAKE/driving-style",
        "/api/v1/sessions/FAKE/lap-distribution",
        "/api/v1/sessions/FAKE/lap-progress",
        "/api/v1/sessions/FAKE/speed-profile",
        "/api/v1/sessions/FAKE/brake-precision",
        "/api/v1/sessions/FAKE/stint-analysis",
        "/api/v1/sessions/FAKE/sector_times",
        "/api/v1/sessions/FAKE/track-map",
        "/api/v1/sessions/FAKE/sectors",
        "/api/v1/sessions/FAKE/compare?sessionKeyB=OTHER",
    ]

    @pytest.mark.parametrize("path", NEW_PATHS)
    def test_404_for_missing_session(self, client, path):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = None

            resp = client.get(path)

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
