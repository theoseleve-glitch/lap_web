"""Phase 4 tests: ``/api/v1/coaching/prescriptive`` POST endpoint.

The endpoint is stateless — no DB, no auth (local mode), no tenant
isolation. These tests use a minimal Flask app with only the coaching
blueprint registered (same pattern as ``test_data_api_v2.py``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Minimal Flask app with just the coaching blueprint."""
    from flask import Flask
    from web.routes.coaching import bp
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── payload builders ─────────────────────────────────────────────

def _packet(cid: int, *, td=300.0, ms=-8.0, brake=-6.0, throttle=8.0,
            exit_spd=-6.0, line=0.5, conf=0.8) -> dict:
    return {
        "corner_id": cid, "time_delta_ms": td, "primary_cause": "test",
        "confidence": conf,
        "s_entry_m": cid * 100.0,
        "s_apex_m": cid * 100.0 + 25.0,
        "s_exit_m": cid * 100.0 + 50.0,
        "evidence": {
            "min_speed_delta_kph": ms,
            "brake_point_delta_m": brake,
            "throttle_pickup_delta_m": throttle,
            "exit_speed_delta_kph": exit_spd,
            "line_deviation_rms_m": line,
        },
    }


def _weakness(bid: str, corners=(1, 2, 3), cost=300.0, conf=0.8,
              trend="improving") -> dict:
    return {
        "behavior_id": bid,
        "label": bid.replace("_", " ").title(),
        "occurrence_count": 20,
        "trend": trend,
        "estimated_time_cost_ms": cost,
        "confidence": conf,
        "corners_observed": list(corners),
        "archetypes_observed": ["slow_90deg", "medium_speed"],
        "sessions_observed": ["S1", "S2", "S3"],
    }


# ── happy path ───────────────────────────────────────────────────

class TestHappyPath:
    def test_returns_200_with_envelope(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [_packet(i) for i in (1, 2, 3)],
            "weaknesses": [_weakness("low_minimum_speed")],
            "sessions_analyzed": 3,
            "laps_analyzed": 30,
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "data" in body
        assert "meta" in body

    def test_data_has_coaching_sheet_keys(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [_packet(i) for i in (1, 2, 3)],
            "weaknesses": [_weakness("low_minimum_speed")],
            "sessions_analyzed": 3,
            "laps_analyzed": 30,
        })
        data = resp.get_json()["data"]
        for k in ("version", "source", "global_focus", "corner_coaching",
                  "weakness_playbook_matches", "next_run_plan",
                  "validation_checks", "storyline", "limits"):
            assert k in data, f"sheet missing {k!r}"

    def test_version_is_stable(self, client):
        from track_surface.prescriptive import COACHING_SHEET_VERSION
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [_packet(1)],
            "weaknesses": [_weakness("low_minimum_speed", corners=(1,))],
            "sessions_analyzed": 3,
            "laps_analyzed": 10,
        })
        assert resp.get_json()["data"]["version"] == COACHING_SHEET_VERSION

    def test_source_is_canonical(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [_packet(1)],
            "weaknesses": [_weakness("low_minimum_speed", corners=(1,))],
            "sessions_analyzed": 3,
            "laps_analyzed": 10,
        })
        src = resp.get_json()["data"]["source"]
        assert "bronze" in src.lower()
        assert "beta" not in src.lower()

    def test_empty_inputs_return_empty_sheet(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [],
            "weaknesses": [],
            "sessions_analyzed": 0,
            "laps_analyzed": 0,
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["global_focus"] == []
        assert any(s["type"] == "insufficient_data" for s in data["storyline"])


# ── design deltas surfaced via HTTP ──────────────────────────────

class TestDesignDeltasExposedViaAPI:
    def test_unregistered_weakness_surfaces_in_storyline(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [_packet(i) for i in (1, 2)],
            "weaknesses": [
                _weakness("low_minimum_speed", corners=(1, 2)),
                _weakness("some_future_weakness", corners=(1, 2)),
            ],
            "sessions_analyzed": 3,
            "laps_analyzed": 10,
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        types_ = {s["type"] for s in data["storyline"]}
        assert "unregistered_weakness" in types_

    def test_insufficient_surfaces_when_brake_missing(self, client):
        pkts = []
        for i in (1, 2):
            p = _packet(i)
            p["evidence"]["brake_point_delta_m"] = None  # the required field
            pkts.append(p)
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": pkts,
            "weaknesses": [_weakness("early_braking", corners=(1, 2))],
            "sessions_analyzed": 3,
            "laps_analyzed": 10,
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        types_ = {s["type"] for s in data["storyline"]}
        assert "insufficient_data" in types_


# ── validation / error envelope ──────────────────────────────────

class TestValidationErrors:
    def test_non_json_body_returns_422(self, client):
        resp = client.post("/api/v1/coaching/prescriptive",
                           data="not json",
                           content_type="application/json")
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_empty_body_returns_422(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={})
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["ok"] is False
        details = body["error"].get("details", [])
        fields = {d["field"] for d in details}
        assert {"corner_packets", "weaknesses",
                "sessions_analyzed", "laps_analyzed"} <= fields

    def test_wrong_types_return_422(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": "not a list",
            "weaknesses": None,
            "sessions_analyzed": "three",
            "laps_analyzed": 3.14,  # float is not int
        })
        assert resp.status_code == 422
        body = resp.get_json()
        fields = {d["field"] for d in body["error"].get("details", [])}
        assert {"corner_packets", "weaknesses",
                "sessions_analyzed", "laps_analyzed"} <= fields

    def test_boolean_sessions_analyzed_rejected(self, client):
        """`True` is technically `isinstance(True, int)` in Python — explicitly reject."""
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [],
            "weaknesses": [],
            "sessions_analyzed": True,
            "laps_analyzed": 0,
        })
        assert resp.status_code == 422

    def test_weakness_without_behavior_id_returns_422(self, client):
        """Upstream schema violation — caught by the KeyError handler."""
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [],
            "weaknesses": [{"occurrence_count": 1}],
            "sessions_analyzed": 1,
            "laps_analyzed": 0,
        })
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "behavior_id" in body["error"]["message"]

    def test_packet_without_corner_id_returns_422(self, client):
        resp = client.post("/api/v1/coaching/prescriptive", json={
            "corner_packets": [{"time_delta_ms": 100.0}],  # missing corner_id
            "weaknesses": [],
            "sessions_analyzed": 1,
            "laps_analyzed": 0,
        })
        assert resp.status_code == 422


# ── method routing ───────────────────────────────────────────────

class TestMethodRouting:
    def test_get_returns_405(self, client):
        resp = client.get("/api/v1/coaching/prescriptive")
        assert resp.status_code == 405
