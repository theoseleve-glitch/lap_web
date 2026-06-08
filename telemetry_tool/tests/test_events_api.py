"""Tests for the events blueprint (POST /api/v1/events, GET /api/v1/usage,
GET /api/v1/analytics/engagement).

All DB calls and entitlement lookups are mocked — no real DB interaction.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── App factory ───────────────────────────────────────────────────────────────


def _make_app():
    from flask import Flask, g

    from web.api_utils import init_request_id
    from web.routes.events import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    app.config["JWT_SECRET"] = "test-secret"
    init_request_id(app)

    @app.before_request
    def _set_fake_user():
        g.current_user_id = 1
        g.workspace_id = 1

    app.register_blueprint(bp)
    return app


# ── TestPostEvents ────────────────────────────────────────────────────────────


class TestPostEvents:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = _make_app()
        self.client = self.app.test_client()

    def test_accepts_single_event(self):
        """_insert_events is called with the accepted event payload."""
        with patch("web.routes.events.analytics_consent_granted", return_value=True), \
             patch("web.routes.events._insert_events") as mock_insert:
            resp = self.client.post(
                "/api/v1/events",
                json={"events": [{"event": "page.view", "path": "/dashboard"}]},
            )
            data = resp.get_json()
            assert resp.status_code == 200
            assert data["ok"] is True
            assert data["data"]["accepted"] == 1
            mock_insert.assert_called_once()
            call_args = mock_insert.call_args
            events_arg = call_args[0][0]
            assert len(events_arg) == 1
            assert events_arg[0]["event"] == "page.view"
            assert call_args[0][1] == 1  # user_id
            assert call_args[0][2] == 1  # workspace_id

    def test_rejects_empty_events(self):
        """An empty events array returns 400."""
        resp = self.client.post("/api/v1/events", json={"events": []})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_rejects_oversized_batch(self):
        """A batch of 51 events returns 400."""
        events = [{"event": "page.view"} for _ in range(51)]
        resp = self.client.post("/api/v1/events", json={"events": events})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_rejects_missing_event_field(self):
        """An event without the 'event' key returns 400."""
        resp = self.client.post(
            "/api/v1/events",
            json={"events": [{"path": "/somewhere"}]},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_strips_unknown_event_types(self):
        """Events with unknown prefixes are dropped; valid ones are kept."""
        with patch("web.routes.events.analytics_consent_granted", return_value=True), \
             patch("web.routes.events._insert_events") as mock_insert:
            resp = self.client.post(
                "/api/v1/events",
                json={
                    "events": [
                        {"event": "page.view"},           # valid
                        {"event": "unknown.click"},        # invalid prefix — drop
                        {"event": "chart.zoom"},           # valid
                        {"event": "internal.debug.thing"}, # invalid prefix — drop
                    ]
                },
            )
            data = resp.get_json()
            assert resp.status_code == 200
            assert data["data"]["accepted"] == 2
            mock_insert.assert_called_once()
            accepted = mock_insert.call_args[0][0]
            assert len(accepted) == 2
            assert {e["event"] for e in accepted} == {"page.view", "chart.zoom"}


# ── TestGetUsage ──────────────────────────────────────────────────────────────


class TestGetUsage:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = _make_app()
        self.client = self.app.test_client()

    def test_returns_usage_snapshot(self):
        """GET /api/v1/usage returns plan_tier, analyses_used, analyses_limit, max_upload_size_mb."""
        fake_snapshot = {
            "plan_tier": "racer",
            "analyses_used": 12,
            "analyses_per_month": 50,
            "max_upload_size_mb": 100,
        }
        with patch("web.routes.events.entitlement_snapshot", return_value=fake_snapshot):
            resp = self.client.get("/api/v1/usage")
            data = resp.get_json()
            assert resp.status_code == 200
            assert data["ok"] is True
            payload = data["data"]
            assert payload["plan_tier"] == "racer"
            assert payload["analyses_used"] == 12
            assert payload["analyses_limit"] == 50
            assert payload["max_upload_size_mb"] == 100
