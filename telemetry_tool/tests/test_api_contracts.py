"""API contract tests — verify every endpoint returns correct response shapes.

Two complementary testing approaches in one file:

1. Integration tests (seeded_client): real SQLite + seeded data. Catch field
   name mismatches, missing columns, broken SQL, NaN leaks, and array parity.

2. Mock-based contract tests (mock_client): controlled responses for error
   shapes, edge cases (unavailable data, 404, 400, 500), pagination echoing,
   server-path stripping, and field type assertions.

Run:
    pytest telemetry_tool/tests/test_api_contracts.py -v
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

SEEDED_SESSION = "s1"


# ── Fixtures ──────────────────────────────────────────────────────


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


@pytest.fixture
def mock_client():
    """Minimal Flask app with data_v2 blueprint — no real DB.

    Tests using this fixture control model responses via unittest.mock to
    exercise error paths and edge cases deterministically.
    """
    from flask import Flask
    from web.routes.data_v2 import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(bp)
    return app.test_client()


# ── Sample data builders (for mock tests) ────────────────────────


def _session(session_id="s1"):
    return {
        "session_id": session_id,
        "csv_filename": f"{session_id}.csv",
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
    }


def _laps():
    return [
        {"session_id": "s1", "lap_number": 1, "lap_time_s": 62.1, "is_valid": 1, "is_best": 0},
        {"session_id": "s1", "lap_number": 2, "lap_time_s": 61.5, "is_valid": 1, "is_best": 0},
        {"session_id": "s1", "lap_number": 3, "lap_time_s": 60.8, "is_valid": 1, "is_best": 1},
    ]


def _gps_trace():
    return {
        "latitudes":  [45.0, 45.001, 45.002],
        "longitudes": [7.0, 7.001, 7.002],
        "distances":  [0.0, 50.0, 100.0],
        "speeds":     [10.0, 15.0, 12.0],
        "accel_lat":  [0.1, -0.2, 0.05],
        "accel_long": [0.5, 0.3, -0.4],
    }


def _score_details():
    return {
        "session_id":        "s1",
        "pace_score":        18,
        "pace_max":          25,
        "consistency_score": 15,
        "consistency_max":   25,
        "execution_score":   20,
        "execution_max":     25,
        "robustness_score":  22,
        "robustness_max":    25,
        "adaptation_score":  None,
        "adaptation_max":    None,
        "strengths_json":    '["Good consistency"]',
        "strengths":         ["Good consistency"],
        "weaknesses_json":   '["Late braking"]',
        "weaknesses":        ["Late braking"],
    }


def _corner_summary():
    return [
        {"corner_id": 1, "entry_speed_mps": 25.0, "apex_speed_mps": 18.0,
         "exit_speed_mps": 22.0, "brake_point_m": 90.0, "time_loss_ms": 75.0},
        {"corner_id": 2, "entry_speed_mps": 21.0, "apex_speed_mps": 15.0,
         "exit_speed_mps": 19.0, "brake_point_m": 390.0, "time_loss_ms": 95.0},
    ]


def _theoretical_data():
    return {
        "session_id":         "s1",
        "theoretical_time_s": 58.0,
        "actual_best_time_s": 60.0,
        "gap_pct":            3.33,
        "simulation_method":  "envelope",
        "corner_coaching": [
            {"corner_id": 1, "s_start": 100.0, "s_end": 200.0,
             "s_apex": 150.0, "direction": "left"},
        ],
        "corner_coaching_json": json.dumps([
            {"corner_id": 1, "s_start": 100.0, "s_end": 200.0,
             "s_apex": 150.0, "direction": "left"},
        ]),
    }


def _dashboard_stats():
    return {
        "total_sessions":     2,
        "total_drivers":      1,
        "total_tracks":       1,
        "total_laps":         25,
        "overall_best_time_s": 58.5,
        "avg_score":          80.0,
        "best_score":         85.0,
    }


# ── Shared envelope assertion helpers ────────────────────────────


def _assert_success_envelope(body: dict, path: str = "") -> None:
    """Assert the standard success envelope fields are present and typed."""
    label = f" [{path}]" if path else ""
    assert "ok" in body,   f"Missing 'ok'{label}"
    assert "data" in body, f"Missing 'data'{label}"
    assert "meta" in body, f"Missing 'meta'{label}"
    assert body["ok"] is True,             f"Expected ok=true{label}, got {body['ok']}"
    assert body["data"] is not None,       f"'data' must not be None on success{label}"
    assert isinstance(body["meta"], dict), f"'meta' must be a dict{label}"


def _assert_error_envelope(body: dict, expected_code: str | None = None,
                            path: str = "") -> None:
    """Assert the standard error envelope fields are present and typed."""
    label = f" [{path}]" if path else ""
    assert "ok" in body,    f"Missing 'ok'{label}"
    assert "error" in body, f"Missing 'error'{label}"
    assert "meta" in body,  f"Missing 'meta'{label}"
    assert body["ok"] is False,                      f"Expected ok=false{label}"
    assert isinstance(body["error"], dict),           f"'error' must be a dict{label}"
    assert "code" in body["error"],                   f"Missing error.code{label}"
    assert "message" in body["error"],                f"Missing error.message{label}"
    assert isinstance(body["error"]["code"], str),    f"error.code must be str{label}"
    assert isinstance(body["error"]["message"], str), f"error.message must be str{label}"
    assert len(body["error"]["message"]) > 0,         f"error.message must be non-empty{label}"
    if expected_code is not None:
        assert body["error"]["code"] == expected_code, (
            f"Expected error code {expected_code!r}, got {body['error']['code']!r}{label}"
        )


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


# ══════════════════════════════════════════════════════════════════
# Integration: envelope + content type on real DB
# ══════════════════════════════════════════════════════════════════


class TestEnvelopeIntegration:
    """Verify helper assertions work against real DB responses."""

    def test_session_list_envelope(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        _assert_success_envelope(resp.get_json(), "/api/v1/sessions")

    def test_session_detail_envelope(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}")
        _assert_success_envelope(resp.get_json(), f"/api/v1/sessions/{SEEDED_SESSION}")

    def test_laps_envelope(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/laps")
        _assert_success_envelope(resp.get_json(), "laps")

    def test_speed_trace_envelope(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/speed-trace?lap=1")
        _assert_success_envelope(resp.get_json(), "speed-trace")

    def test_gps_trace_envelope(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/gps-trace?lap=1")
        _assert_success_envelope(resp.get_json(), "gps-trace")

    def test_gg_data_envelope(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/gg-data?lap=1")
        _assert_success_envelope(resp.get_json(), "gg-data")

    def test_scores_envelope(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/scores")
        _assert_success_envelope(resp.get_json(), "scores")

    def test_corners_envelope(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION}/corners")
        _assert_success_envelope(resp.get_json(), "corners")

    def test_content_type_json_on_all_endpoints(self, seeded_client):
        """All endpoints under test must return application/json."""
        paths = [
            "/api/v1/sessions",
            f"/api/v1/sessions/{SEEDED_SESSION}",
            f"/api/v1/sessions/{SEEDED_SESSION}/laps",
            f"/api/v1/sessions/{SEEDED_SESSION}/speed-trace?lap=1",
            f"/api/v1/sessions/{SEEDED_SESSION}/gps-trace?lap=1",
            f"/api/v1/sessions/{SEEDED_SESSION}/scores",
            f"/api/v1/sessions/{SEEDED_SESSION}/corners",
        ]
        for path in paths:
            resp = seeded_client.get(path)
            assert "application/json" in resp.content_type, (
                f"{path} returned content-type {resp.content_type!r}"
            )


# ══════════════════════════════════════════════════════════════════
# Integration: session list pagination contract
# ══════════════════════════════════════════════════════════════════


class TestSessionListPaginationContract:
    """data.sessions list must carry correct pagination meta fields."""

    def test_pagination_fields_present(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        data = resp.get_json()["data"]
        assert "sessions" in data, "Missing data.sessions"
        assert "total" in data,    "Missing data.total"
        assert "limit" in data,    "Missing data.limit"
        assert "offset" in data,   "Missing data.offset"

    def test_pagination_field_types(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        data = resp.get_json()["data"]
        assert isinstance(data["total"],  int), "total must be int"
        assert isinstance(data["limit"],  int), "limit must be int"
        assert isinstance(data["offset"], int), "offset must be int"
        assert isinstance(data["sessions"], list), "sessions must be list"

    def test_limit_param_echoed(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions?limit=1&offset=0")
        data = resp.get_json()["data"]
        assert data["limit"] == 1
        assert data["offset"] == 0

    def test_total_is_nonnegative(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        assert resp.get_json()["data"]["total"] >= 0

    def test_source_path_never_exposed(self, seeded_client):
        """Internal server path must never appear in the session list."""
        resp = seeded_client.get("/api/v1/sessions")
        sessions = resp.get_json()["data"]["sessions"]
        for s in sessions:
            assert "source_path" not in s, "source_path must not be in list items"
            assert "html_report_path" not in s, "html_report_path must not be in list items"


# ══════════════════════════════════════════════════════════════════
# Integration: session detail field-type contract
# ══════════════════════════════════════════════════════════════════


class TestSessionDetailFieldTypes:
    """Field types in session detail must be predictable."""

    def test_session_id_is_string(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}"
        ).get_json()["data"]
        assert isinstance(data["session_id"], str)

    def test_n_laps_is_int(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}"
        ).get_json()["data"]
        assert isinstance(data["n_laps"], int)

    def test_best_lap_time_s_is_numeric_or_none(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}"
        ).get_json()["data"]
        val = data.get("best_lap_time_s")
        assert val is None or isinstance(val, (int, float))

    def test_source_path_stripped(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}"
        ).get_json()["data"]
        assert "source_path" not in data
        assert "html_report_path" not in data


# ══════════════════════════════════════════════════════════════════
# Integration: lap list field types
# ══════════════════════════════════════════════════════════════════


class TestLapFieldTypes:
    """Lap list items must have typed fields."""

    def test_laps_key_is_list(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/laps"
        ).get_json()["data"]
        assert "laps" in data
        assert isinstance(data["laps"], list)

    def test_lap_time_s_is_numeric(self, seeded_client):
        laps = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/laps"
        ).get_json()["data"]["laps"]
        assert len(laps) > 0
        for lap in laps:
            val = lap["lap_time_s"]
            assert isinstance(val, (int, float)), (
                f"lap_time_s should be numeric, got {type(val)}"
            )

    def test_lap_number_is_int(self, seeded_client):
        laps = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/laps"
        ).get_json()["data"]["laps"]
        for lap in laps:
            assert isinstance(lap["lap_number"], int)


# ══════════════════════════════════════════════════════════════════
# Integration: trace array type contracts
# ══════════════════════════════════════════════════════════════════


class TestTraceArrayTypes:
    """Speed/GPS/GG trace arrays must contain numeric values."""

    def test_speed_trace_values_numeric(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/speed-trace?lap=1"
        ).get_json()["data"]
        for v in data.get("speeds", []):
            assert isinstance(v, (int, float)), f"speed value not numeric: {v!r}"
        for v in data.get("distances", []):
            assert isinstance(v, (int, float)), f"distance value not numeric: {v!r}"

    def test_gps_trace_values_numeric(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/gps-trace?lap=1"
        ).get_json()["data"]
        for v in data.get("latitudes", []):
            assert isinstance(v, (int, float)), f"latitude not numeric: {v!r}"
        for v in data.get("longitudes", []):
            assert isinstance(v, (int, float)), f"longitude not numeric: {v!r}"

    def test_gg_data_values_numeric(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/gg-data?lap=1"
        ).get_json()["data"]
        for v in data.get("accel_lat", []):
            assert isinstance(v, (int, float)), f"accel_lat not numeric: {v!r}"
        for v in data.get("accel_long", []):
            assert isinstance(v, (int, float)), f"accel_long not numeric: {v!r}"


# ══════════════════════════════════════════════════════════════════
# Integration: scores display_scores + badges shape
# ══════════════════════════════════════════════════════════════════


class TestScoresDetailedContract:
    """Scores endpoint must return display_scores and badges in correct shape."""

    def test_display_scores_present(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/scores"
        ).get_json()["data"]
        assert "display_scores" in data, "Missing display_scores"
        assert isinstance(data["display_scores"], dict)

    def test_display_scores_categories(self, seeded_client):
        display = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/scores"
        ).get_json()["data"]["display_scores"]
        for cat in ("pace", "consistency", "execution", "robustness"):
            assert cat in display, f"display_scores missing {cat!r}"
            assert "score" in display[cat], f"display_scores.{cat} missing 'score'"
            assert "max" in display[cat],   f"display_scores.{cat} missing 'max'"

    def test_badges_is_list(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/scores"
        ).get_json()["data"]
        assert "badges" in data, "Missing badges"
        assert isinstance(data["badges"], list)

    def test_available_is_true(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/scores"
        ).get_json()["data"]
        assert data.get("available") is True

    def test_score_values_numeric_or_none(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/scores"
        ).get_json()["data"]
        for field in ("pace_score", "pace_max", "consistency_score", "consistency_max"):
            val = data.get(field)
            assert val is None or isinstance(val, (int, float)), (
                f"{field} should be numeric or None, got {type(val)}"
            )


# ══════════════════════════════════════════════════════════════════
# Integration: corners contract
# ══════════════════════════════════════════════════════════════════


class TestCornersShapeIntegration:
    """Corners endpoint shape with real data."""

    def test_corners_key_present(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/corners"
        ).get_json()["data"]
        assert "corners" in data, "Missing data.corners"
        assert "available" in data, "Missing data.available"

    def test_corner_items_have_corner_id(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/corners"
        ).get_json()["data"]
        if data.get("available") and data["corners"]:
            for c in data["corners"]:
                assert "corner_id" in c, "Corner item missing corner_id"

    def test_corners_list_type(self, seeded_client):
        data = seeded_client.get(
            f"/api/v1/sessions/{SEEDED_SESSION}/corners"
        ).get_json()["data"]
        assert isinstance(data["corners"], list)


# ══════════════════════════════════════════════════════════════════
# Integration: compare sessions shape
# ══════════════════════════════════════════════════════════════════


class TestCompareSessionsIntegration:
    """Compare endpoint with two real seeded sessions."""

    def test_compare_shape(self, seeded_client):
        resp = seeded_client.get("/api/v1/compare/sessions?a=s1&b=s2")
        assert resp.status_code == 200
        body = resp.get_json()
        _assert_success_envelope(body, "compare/sessions")
        data = body["data"]
        assert "session_a" in data, "Missing data.session_a"
        assert "session_b" in data, "Missing data.session_b"

    def test_compare_group_keys(self, seeded_client):
        data = seeded_client.get(
            "/api/v1/compare/sessions?a=s1&b=s2"
        ).get_json()["data"]
        for key in ("session_a", "session_b"):
            group = data[key]
            assert "session" in group, f"Missing {key}.session"
            assert "scores" in group,  f"Missing {key}.scores"
            assert "laps" in group,    f"Missing {key}.laps"
            assert isinstance(group["laps"], list), f"{key}.laps must be list"


# ══════════════════════════════════════════════════════════════════
# Mock-based: error response shapes
# ══════════════════════════════════════════════════════════════════


class TestErrorShapesMock:
    """Use controlled mocks to verify error shapes for 404/400/500."""

    def test_404_not_found_shape(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = mock_client.get("/api/v1/sessions/does-not-exist")

        assert resp.status_code == 404
        _assert_error_envelope(resp.get_json(), expected_code="NOT_FOUND")

    def test_400_missing_compare_params(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models"):
            mock_db.return_value = MagicMock()
            resp = mock_client.get("/api/v1/compare/sessions")  # missing a & b

        assert resp.status_code == 400
        _assert_error_envelope(resp.get_json(), expected_code="VALIDATION_ERROR")

    def test_400_missing_a_param(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models"):
            mock_db.return_value = MagicMock()
            resp = mock_client.get("/api/v1/compare/sessions?b=s2")

        assert resp.status_code == 400
        _assert_error_envelope(resp.get_json(), expected_code="VALIDATION_ERROR")

    def test_400_missing_b_param(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models"):
            mock_db.return_value = MagicMock()
            resp = mock_client.get("/api/v1/compare/sessions?a=s1")

        assert resp.status_code == 400
        _assert_error_envelope(resp.get_json(), expected_code="VALIDATION_ERROR")

    def test_500_internal_error_shape(self, mock_client):
        """Unhandled exceptions must produce 500 INTERNAL_ERROR envelope."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_sessions.side_effect = RuntimeError("Unexpected boom")
            mock_models.count_sessions_filtered.return_value = 0

            resp = mock_client.get("/api/v1/sessions")

        assert resp.status_code == 500
        _assert_error_envelope(resp.get_json(), expected_code="INTERNAL_ERROR")

    def test_error_message_non_empty(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = mock_client.get("/api/v1/sessions/x")

        msg = resp.get_json()["error"]["message"]
        assert isinstance(msg, str) and len(msg) > 0


# ══════════════════════════════════════════════════════════════════
# Mock-based: unavailable data shapes (available=false)
# ══════════════════════════════════════════════════════════════════


class TestUnavailableDataShapes:
    """When optional data is missing the endpoint must return available=false
    with reason_code and message — not a 4xx error."""

    def test_speed_trace_no_data_shape(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _session()
            mock_models.get_laps_for_session.return_value = _laps()
            mock_models.get_gps_trace.return_value = None

            resp = mock_client.get("/api/v1/sessions/s1/speed-trace")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is False
        assert "reason_code" in data
        assert "message" in data

    def test_gps_trace_no_data_shape(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _session()
            mock_models.get_laps_for_session.return_value = _laps()
            mock_models.get_gps_trace.return_value = None

            resp = mock_client.get("/api/v1/sessions/s1/gps-trace")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is False
        assert "reason_code" in data

    def test_gg_data_no_accel_shape(self, mock_client):
        trace_no_accel = {**_gps_trace(), "accel_lat": [], "accel_long": []}
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _session()
            mock_models.get_laps_for_session.return_value = _laps()
            mock_models.get_gps_trace.return_value = trace_no_accel

            resp = mock_client.get("/api/v1/sessions/s1/gg-data")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is False
        assert "reason_code" in data
        assert "message" in data

    def test_scores_no_data_shape(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _session()
            mock_models.get_score_details.return_value = None

            resp = mock_client.get("/api/v1/sessions/s1/scores")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is False
        assert "reason_code" in data

    def test_corners_no_data_shape(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _session()
            mock_models.get_corner_metrics_summary.return_value = []
            mock_models.get_theoretical_data.return_value = None

            resp = mock_client.get("/api/v1/sessions/s1/corners")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["available"] is False
        assert data["corners"] == []
        assert "reason_code" in data


# ══════════════════════════════════════════════════════════════════
# Mock-based: compare sessions full contract
# ══════════════════════════════════════════════════════════════════


class TestCompareSessionsMockContract:
    """Verify compare sessions endpoint shapes with controlled data."""

    def test_success_shape(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = [
                _session("s1"), _session("s2"),
            ]
            mock_models.get_score_details.side_effect = [
                _score_details(), _score_details(),
            ]
            mock_models.get_laps_for_session.side_effect = [
                _laps(), _laps(),
            ]

            resp = mock_client.get("/api/v1/compare/sessions?a=s1&b=s2")

        assert resp.status_code == 200
        body = resp.get_json()
        _assert_success_envelope(body, "compare/sessions")
        data = body["data"]
        assert "session_a" in data
        assert "session_b" in data
        for key in ("session_a", "session_b"):
            group = data[key]
            assert "session" in group
            assert "scores" in group
            assert "laps" in group
            assert isinstance(group["laps"], list)

    def test_session_a_not_found_404(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None

            resp = mock_client.get("/api/v1/compare/sessions?a=bad&b=s2")

        assert resp.status_code == 404
        _assert_error_envelope(resp.get_json(), expected_code="NOT_FOUND")

    def test_session_b_not_found_404(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.side_effect = [_session("s1"), None]

            resp = mock_client.get("/api/v1/compare/sessions?a=s1&b=bad")

        assert resp.status_code == 404
        _assert_error_envelope(resp.get_json(), expected_code="NOT_FOUND")


# ══════════════════════════════════════════════════════════════════
# Mock-based: dashboard stats shapes
# ══════════════════════════════════════════════════════════════════


class TestDashboardStatsMockContract:
    """Dashboard stats must return all required aggregate fields."""

    def test_required_fields_present(self, mock_client):
        required = {
            "total_sessions", "total_drivers", "total_tracks",
            "total_laps", "avg_score", "best_score",
            "recent_sessions", "recent_scores", "recent_times",
        }
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_dashboard_stats.return_value = _dashboard_stats()
            mock_models.get_sessions.return_value = [_session("s1"), _session("s2")]

            resp = mock_client.get("/api/v1/dashboard/stats")

        assert resp.status_code == 200
        body = resp.get_json()
        _assert_success_envelope(body, "dashboard/stats")
        data = body["data"]
        for field in required:
            assert field in data, f"Dashboard stats missing: {field!r}"

    def test_list_fields_are_lists(self, mock_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_dashboard_stats.return_value = _dashboard_stats()
            mock_models.get_sessions.return_value = [_session("s1")]

            resp = mock_client.get("/api/v1/dashboard/stats")

        data = resp.get_json()["data"]
        assert isinstance(data["recent_sessions"], list)
        assert isinstance(data["recent_scores"],   list)
        assert isinstance(data["recent_times"],    list)

    def test_total_laps_coerced_from_none(self, mock_client):
        """Route coerces None total_laps to 0 (must not return null)."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mock_models:
            mock_db.return_value = MagicMock()
            mock_models.get_dashboard_stats.return_value = {
                "total_sessions": 0, "total_drivers": 0,
                "total_tracks": 0, "total_laps": None,
                "overall_best_time_s": None, "avg_score": None, "best_score": None,
            }
            mock_models.get_sessions.return_value = []

            resp = mock_client.get("/api/v1/dashboard/stats")

        data = resp.get_json()["data"]
        assert data["total_laps"] == 0, "None total_laps must be coerced to 0"
