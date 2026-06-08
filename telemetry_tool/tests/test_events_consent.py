# tests/test_events_consent.py
"""Consent gate + PII guard for POST /api/v1/events."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


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


class TestConsentGate:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = _make_app()
        self.client = self.app.test_client()

    def test_drops_batch_without_consent(self):
        with patch("web.routes.events.analytics_consent_granted", return_value=False), \
             patch("web.routes.events._insert_events") as mock_insert:
            resp = self.client.post(
                "/api/v1/events",
                json={"events": [{"event": "page.view", "path": "/dashboard"}]},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["data"]["accepted"] == 0
            assert data["data"]["reason"] == "no_consent"
            mock_insert.assert_not_called()

    def test_accepts_batch_with_consent(self):
        with patch("web.routes.events.analytics_consent_granted", return_value=True), \
             patch("web.routes.events._insert_events") as mock_insert:
            resp = self.client.post(
                "/api/v1/events",
                json={"events": [{"event": "page.view", "path": "/dashboard"}]},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["data"]["accepted"] == 1
            assert "reason" not in data["data"]
            mock_insert.assert_called_once()


class TestPiiGuardOnIngest:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = _make_app()
        self.client = self.app.test_client()

    def test_strips_denylisted_keys_from_properties(self):
        with patch("web.routes.events.analytics_consent_granted", return_value=True), \
             patch("web.routes.events._insert_events") as mock_insert:
            resp = self.client.post(
                "/api/v1/events",
                json={"events": [{
                    "event": "chart.zoom",
                    "path": "/app",
                    "properties": {"email": "a@b.com", "zoom": 2, "ip": "1.2.3.4"},
                }]},
            )
            assert resp.status_code == 200
            accepted = mock_insert.call_args[0][0]
            assert accepted[0]["properties"] == {"zoom": 2}
