"""API contract tests — verify every endpoint returns correct response shapes.

Uses seeded_db fixture (real SQLite with sample data) to catch field name
mismatches, missing columns, and broken SQL.  NOT mocks.

Run:
    pytest telemetry_tool/tests/test_api_contracts.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SEEDED_SESSION = "s1"


@pytest.fixture
def seeded_client(seeded_db):
    """Flask test client backed by a real seeded SQLite DB."""
    from web.app import create_app

    app = create_app()
    app.config["TESTING"] = True

    # Patch at the import site — data_v2.py does
    # `from web.db import get_db_connection` so the reference lives there.
    with patch("web.routes.data_v2.get_db_connection", return_value=seeded_db):
        with app.test_client() as client:
            yield client


# ── Envelope contract ────────────────────────────────────────────


class TestEnvelopeContract:
    """Every response has {ok, data, meta} with request_id."""

    PATHS = [
        f"/api/v1/sessions",
        f"/api/v1/sessions/{SEEDED_SESSION}",
        f"/api/v1/sessions/{SEEDED_SESSION}/laps",
        f"/api/v1/sessions/{SEEDED_SESSION}/speed-trace?lap=1",
        f"/api/v1/sessions/{SEEDED_SESSION}/gps-trace?lap=1",
        f"/api/v1/sessions/{SEEDED_SESSION}/gg-data?lap=1",
        f"/api/v1/sessions/{SEEDED_SESSION}/scores",
        f"/api/v1/sessions/{SEEDED_SESSION}/corners",
        f"/api/v1/sessions/{SEEDED_SESSION}/corner-positions",
        f"/api/v1/sessions/{SEEDED_SESSION}/track-map?lap=best",
        f"/api/v1/sessions/{SEEDED_SESSION}/theoretical",
        f"/api/v1/sessions/{SEEDED_SESSION}/reference_line",
        f"/api/v1/sessions/{SEEDED_SESSION}/best_lap_gps",
    ]

    @pytest.mark.parametrize("path", PATHS)
    def test_envelope_shape(self, seeded_client, path):
        resp = seeded_client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
        body = resp.get_json()
        assert body["ok"] is True, f"{path}: ok={body.get('ok')}"
        assert "data" in body, f"{path}: missing 'data'"
        meta = body.get("meta", {})
        assert "request_id" in meta, f"{path}: missing request_id in meta"

    @pytest.mark.parametrize("path", PATHS)
    def test_no_nan_in_json(self, seeded_client, path):
        resp = seeded_client.get(path)
        raw = resp.data.decode("utf-8")
        assert "NaN" not in raw, f"{path}: contains NaN"
        assert "Infinity" not in raw, f"{path}: contains Infinity"


# ── Trace contracts ──────────────────────────────────────────────


class TestTraceContracts:
    """Trace endpoints return parallel arrays of equal length."""

    def test_speed_trace_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/speed-trace?lap=1"
        )
        data = resp.get_json()["data"]
        assert "distances" in data
        assert "speeds" in data
        assert "lap_number" in data
        assert len(data["distances"]) == len(data["speeds"])

    def test_speed_trace_distance_monotonic(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/speed-trace?lap=1"
        )
        dists = resp.get_json()["data"]["distances"]
        assert len(dists) > 0
        for i in range(1, len(dists)):
            assert dists[i] >= dists[i - 1], (
                f"distance[{i}]={dists[i]} < distance[{i-1}]={dists[i-1]}"
            )

    def test_gps_trace_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/gps-trace?lap=1"
        )
        data = resp.get_json()["data"]
        required = {"latitudes", "longitudes", "distances", "speeds", "lap_number"}
        assert required <= set(data.keys()), f"Missing keys: {required - set(data.keys())}"
        n = len(data["distances"])
        assert len(data["latitudes"]) == n
        assert len(data["longitudes"]) == n
        assert len(data["speeds"]) == n

    def test_gg_data_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/gg-data?lap=1"
        )
        data = resp.get_json()["data"]
        assert "accel_lat" in data
        assert "accel_long" in data
        assert "lap_number" in data

    def test_reference_line_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/reference_line"
        )
        data = resp.get_json()["data"]
        assert "latitudes" in data
        assert "longitudes" in data
        assert "distances" in data

    def test_best_lap_gps_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/best_lap_gps"
        )
        data = resp.get_json()["data"]
        assert "latitudes" in data
        assert "longitudes" in data
        assert "distances" in data
        n = len(data["distances"])
        assert len(data["latitudes"]) == n


# ── Corner contracts ─────────────────────────────────────────────


class TestCornerContracts:
    """Corner endpoints return expected fields."""

    def test_corner_positions_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/corner-positions"
        )
        data = resp.get_json()["data"]
        assert "corners" in data
        assert len(data["corners"]) > 0
        for c in data["corners"]:
            assert "corner_id" in c
            # Should have GPS coords from interpolation
            assert "s_apex" in c or "lat" in c

    def test_corner_metrics_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/corner-metrics"
        )
        data = resp.get_json()["data"]
        assert "corners" in data
        assert len(data["corners"]) > 0

    def test_corner_metrics_summary_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/corner-metrics/summary"
        )
        data = resp.get_json()["data"]
        assert "corners" in data


# ── Track map contract ───────────────────────────────────────────


class TestTrackMapContract:
    """Track map endpoint returns bundled lap data + corners."""

    def test_track_map_best(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/track-map?lap=best"
        )
        data = resp.get_json()["data"]
        assert "laps" in data
        assert "best_lap" in data
        assert "corners" in data

    def test_track_map_all(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/track-map?lap=all"
        )
        data = resp.get_json()["data"]
        assert "laps" in data
        assert len(data["laps"]) >= 1


# ── Theoretical + derived contracts ──────────────────────────────


class TestTheoreticalContract:
    """Theoretical data endpoint returns expected fields."""

    def test_theoretical_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/theoretical"
        )
        data = resp.get_json()["data"]
        assert "theoretical_time_s" in data
        assert "actual_best_time_s" in data
        assert "corner_coaching" in data

    def test_corners_coaching_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/corners"
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert isinstance(data, (dict, list))


# ── Sectors contract ─────────────────────────────────────────────


class TestSectorsContract:
    """Sectors endpoint returns sector analysis from analysis_json."""

    def test_sectors_shape(self, seeded_client):
        resp = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/sectors"
        )
        # May return 200 or 404 depending on whether analysis_json is present
        if resp.status_code == 200:
            data = resp.get_json()["data"]
            assert isinstance(data, dict)


# ── Session detail contracts ─────────────────────────────────────


class TestSessionDetailContract:
    """Session detail and laps return expected shapes."""

    def test_session_detail_shape(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}")
        data = resp.get_json()["data"]
        assert "session_id" in data
        assert "driver_name" in data or "driver_id" in data
        assert "track_id" in data or "track_name" in data

    def test_laps_shape(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/laps")
        data = resp.get_json()["data"]
        # Laps endpoint wraps in {"laps": [...]}
        laps = data["laps"] if isinstance(data, dict) else data
        assert isinstance(laps, list)
        assert len(laps) > 0
        assert "lap_number" in laps[0]
        assert "lap_time_s" in laps[0]

    def test_scores_shape(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/scores")
        data = resp.get_json()["data"]
        assert "pace_score" in data or "total_score" in data
