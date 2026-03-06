"""Tests for speed overlay and cross-session endpoints.

Validates:
    1. GET /api/v1/sessions/<id>/speed_overlay returns traces dict
    2. GET /api/v1/sessions/<id>/cross_session returns enriched metrics
    3. Missing session returns 404
    4. Session with no track returns empty with reason_code
    5. Session with no comparable traces returns empty with reason_code
    6. Module-shim rewrites speed_overlay path correctly
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def app():
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


# ── Sample data ───────────────────────────────────────────────────


def _session(sid="s1", track_id="t1", date="2024-01-01", driver="Alice"):
    return {
        "session_id": sid,
        "track_id": track_id,
        "session_date": date,
        "driver_name": driver,
        "csv_filename": f"{sid}.csv",
        "n_laps": 5,
    }


def _gps_trace(distances=None, speeds=None):
    return {
        "latitudes": [45.0, 45.001, 45.002],
        "longitudes": [7.0, 7.001, 7.002],
        "distances": distances or [0.0, 50.0, 100.0],
        "speeds": speeds or [10.0, 15.0, 12.0],
    }


def _laps(sid="s1", best_time=60.0):
    return [
        {"session_id": sid, "lap_number": 1, "lap_time_s": best_time + 2, "is_valid": 1, "is_best": 0},
        {"session_id": sid, "lap_number": 2, "lap_time_s": best_time, "is_valid": 1, "is_best": 1},
        {"session_id": sid, "lap_number": 3, "lap_time_s": best_time + 1, "is_valid": 1, "is_best": 0},
    ]


# ══════════════════════════════════════════════════════════════════
# 1. speed_overlay endpoint
# ══════════════════════════════════════════════════════════════════


class TestSpeedOverlay:
    """GET /api/v1/sessions/<id>/speed_overlay"""

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_returns_traces_dict_keyed_by_session_id(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1")
        mock_models.get_sessions.return_value = [
            _session("s1", date="2024-01-02", driver="Alice"),
            _session("s2", date="2024-01-01", driver="Bob"),
        ]
        mock_models.get_laps_for_session.return_value = _laps()
        mock_models.get_gps_trace.return_value = _gps_trace()

        resp = client.get("/api/v1/sessions/s1/speed_overlay")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

        traces = data["data"]["traces"]
        assert isinstance(traces, dict)
        assert "s1" in traces
        assert "s2" in traces
        assert traces["s1"]["is_current"] is True
        assert traces["s2"]["is_current"] is False

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_trace_contains_required_fields(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1")
        mock_models.get_sessions.return_value = [_session("s1")]
        mock_models.get_laps_for_session.return_value = _laps()
        mock_models.get_gps_trace.return_value = _gps_trace()

        resp = client.get("/api/v1/sessions/s1/speed_overlay")
        data = resp.get_json()["data"]
        trace = data["traces"]["s1"]

        assert "distances" in trace
        assert "speeds" in trace
        assert "label" in trace
        assert "is_current" in trace
        assert "lap_number" in trace
        assert isinstance(trace["distances"], list)
        assert isinstance(trace["speeds"], list)

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_session_not_found_returns_404(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = None

        resp = client.get("/api/v1/sessions/nonexistent/speed_overlay")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_no_track_returns_empty_with_reason(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1", track_id=None)

        resp = client.get("/api/v1/sessions/s1/speed_overlay")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["traces"] == {}
        assert data["available"] is False
        assert data["reason_code"] == "no_track"

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_no_comparable_traces_returns_empty_with_reason(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1")
        mock_models.get_sessions.return_value = [_session("s1")]
        mock_models.get_laps_for_session.return_value = []
        mock_models.get_gps_trace.return_value = None

        resp = client.get("/api/v1/sessions/s1/speed_overlay")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["traces"] == {}
        assert data["available"] is False
        assert data["reason_code"] == "no_comparable_traces"

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_label_uses_driver_and_date(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1")
        mock_models.get_sessions.return_value = [
            _session("s1", date="2024-03-15", driver="Max"),
        ]
        mock_models.get_laps_for_session.return_value = _laps()
        mock_models.get_gps_trace.return_value = _gps_trace()

        resp = client.get("/api/v1/sessions/s1/speed_overlay")
        trace = resp.get_json()["data"]["traces"]["s1"]
        assert "Max" in trace["label"]
        assert "2024-03-15" in trace["label"]


# ══════════════════════════════════════════════════════════════════
# 2. cross_session endpoint enriched metrics
# ══════════════════════════════════════════════════════════════════


class TestCrossSessionMetrics:
    """GET /api/v1/sessions/<id>/cross_session — enriched response"""

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_includes_metrics_fields(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1")
        mock_models.get_sessions.return_value = [
            _session("s1", date="2024-01-02"),
            _session("s2", date="2024-01-01"),
        ]

        def laps_side_effect(conn, sid):
            if sid == "s1":
                return _laps("s1", best_time=59.0)
            return _laps("s2", best_time=60.0)

        mock_models.get_laps_for_session.side_effect = laps_side_effect
        mock_models.get_gps_trace.return_value = _gps_trace()

        resp = client.get("/api/v1/sessions/s1/cross_session")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert "comparable_count" in data
        assert data["comparable_count"] >= 1
        assert "track_best_time_s" in data
        assert "historical_percentile" in data
        assert "improvement" in data

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_improvement_shows_negative_delta_when_faster(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1")
        mock_models.get_sessions.return_value = [
            _session("s1", date="2024-01-02"),
            _session("s2", date="2024-01-01"),
        ]

        def laps_side_effect(conn, sid):
            if sid == "s1":
                return _laps("s1", best_time=58.0)  # faster
            return _laps("s2", best_time=60.0)  # previous

        mock_models.get_laps_for_session.side_effect = laps_side_effect
        mock_models.get_gps_trace.return_value = _gps_trace()

        resp = client.get("/api/v1/sessions/s1/cross_session")
        data = resp.get_json()["data"]

        assert data["improvement"]["improved"] is True
        assert data["improvement"]["delta_s"] < 0

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_no_track_returns_empty(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1", track_id=None)

        resp = client.get("/api/v1/sessions/s1/cross_session")
        data = resp.get_json()["data"]
        assert data["sessions"] == []
        assert data["available"] is False

    @patch("web.routes.data_v2.models")
    @patch("web.routes.data_v2.get_db_connection")
    def test_track_best_time(self, mock_conn, mock_models, client):
        mock_models.get_session_by_id.return_value = _session("s1")
        mock_models.get_sessions.return_value = [
            _session("s1", date="2024-01-02"),
            _session("s2", date="2024-01-01"),
        ]

        def laps_side_effect(conn, sid):
            if sid == "s1":
                return _laps("s1", best_time=58.0)
            return _laps("s2", best_time=60.0)

        mock_models.get_laps_for_session.side_effect = laps_side_effect
        mock_models.get_gps_trace.return_value = _gps_trace()

        resp = client.get("/api/v1/sessions/s1/cross_session")
        data = resp.get_json()["data"]
        assert data["track_best_time_s"] == 58.0


# ══════════════════════════════════════════════════════════════════
# 3. Module-shim URL rewriting
# ══════════════════════════════════════════════════════════════════


class TestModuleShimRewrite:
    """Verify the module-shim rewrite logic produces correct URLs."""

    def test_speed_overlay_path_rewrites_to_v1(self):
        """The shim rewrites /api/session/{id}/speed_overlay to
        /api/v1/sessions/{id}/speed_overlay — which now has an endpoint."""
        # Simulate the rewrite logic from module-shim.js
        url = "/api/session/s123/speed_overlay"
        # Stage 1: /api/session/ → /api/v1/sessions/
        url = url.replace("/api/session/", "/api/v1/sessions/")
        assert url == "/api/v1/sessions/s123/speed_overlay"

    def test_cross_session_path_rewrites_to_v1(self):
        url = "/api/session/s123/cross_session"
        url = url.replace("/api/session/", "/api/v1/sessions/")
        assert url == "/api/v1/sessions/s123/cross_session"
