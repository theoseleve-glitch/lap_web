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
        """Returns 404 when no GPS trace exists for the lap."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = None

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1")

        assert resp.status_code == 404

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
        assert body["data"]["lat"] == [45.0, 45.001, 45.002]
        assert body["data"]["lon"] == [7.0, 7.001, 7.002]
        assert body["data"]["distances"] == [0.0, 50.0, 100.0]
        assert body["data"]["speeds"] == [10.0, 15.0, 12.0]
        assert body["data"]["lap_number"] == 1

    def test_gps_trace_no_data(self, client):
        """Returns 404 when no GPS trace for that lap."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = None

            resp = client.get("/api/v1/sessions/s1/gps-trace?lap=99")

        assert resp.status_code == 404


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
        assert body["data"]["lat_g"] == [0.1, -0.2, 0.05]
        assert body["data"]["lon_g"] == [0.5, 0.3, -0.4]
        assert body["data"]["lap_number"] == 1

    def test_gg_data_missing_accel(self, client):
        """Returns 404 when GPS trace has no acceleration data."""
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

        assert resp.status_code == 404

    def test_gg_data_no_trace(self, client):
        """Returns 404 when no GPS trace for that lap."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_gps_trace.return_value = None

            resp = client.get("/api/v1/sessions/s1/gg-data?lap=1")

        assert resp.status_code == 404


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
        """Returns 404 when no score details exist."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_score_details.return_value = None

            resp = client.get("/api/v1/sessions/s1/scores")

        assert resp.status_code == 404

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

    def test_corners_returns_coaching(self, client):
        """Returns corner coaching data from theoretical_data."""
        theo = _sample_theoretical_data()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_theoretical_data.return_value = theo

            resp = client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert isinstance(body["data"]["corners"], list)
        assert len(body["data"]["corners"]) == 2
        assert body["data"]["corners"][0]["corner_id"] == 1

    def test_corners_no_theoretical_data(self, client):
        """Returns 404 when no theoretical data exists."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_theoretical_data.return_value = None

            resp = client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 404

    def test_corners_no_coaching_in_data(self, client):
        """Returns 404 when theoretical data has no corner_coaching."""
        theo = _sample_theoretical_data()
        theo["corner_coaching"] = None
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _sample_session()
            mock_models.get_theoretical_data.return_value = theo

            resp = client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 404

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
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.return_value = _sample_session()

            resp = client.delete("/api/v1/sessions/s1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["deleted"] == "s1"
        # Should have called execute for DELETE statements and commit
        assert mock_conn.execute.called
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
        # Create a temporary HTML report file
        report_file = tmp_path / "report.html"
        report_file.write_text("<html><body>Report</body></html>")

        session = _sample_session()
        session["html_report_path"] = str(report_file)

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
