# tests/test_marketing_api.py
"""POST /api/v1/marketing-events — anonymous collector."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_app():
    from flask import Flask
    from web.api_utils import init_request_id
    from web.routes.marketing import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    app.config["JWT_SECRET"] = "test-secret"
    init_request_id(app)
    app.register_blueprint(bp)
    return app


class TestMarketingCollector:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = _make_app()
        self.client = self.app.test_client()

    def test_stores_event_without_identity(self):
        with patch("web.routes.marketing._insert_marketing_events") as mock_insert:
            resp = self.client.post(
                "/api/v1/marketing-events",
                json={"events": [{"event": "pricing_viewed", "path": "/pricing",
                                  "properties": {"utm_source": "ig"}}]},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["data"]["accepted"] == 1
            rows = mock_insert.call_args[0][0]
            assert len(rows) == 1
            # No identity fields are ever passed downstream — only the 3 columns.
            assert set(rows[0].keys()) == {"event", "path", "properties"}

    def test_drops_pii_from_properties(self):
        with patch("web.routes.marketing._insert_marketing_events") as mock_insert:
            resp = self.client.post(
                "/api/v1/marketing-events",
                json={"events": [{"event": "signup_clicked", "path": "/",
                                  "properties": {"email": "a@b.com", "utm": "x"}}]},
            )
            assert resp.status_code == 200
            rows = mock_insert.call_args[0][0]
            assert rows[0]["properties"] == {"utm": "x"}

    def test_rejects_oversized_batch(self):
        events = [{"event": "pageview"} for _ in range(51)]
        resp = self.client.post("/api/v1/marketing-events", json={"events": events})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_rate_limited_returns_429(self):
        # Simulate the Redis sliding-window reporting over-limit.
        fake_redis = type("R", (), {"eval": staticmethod(lambda *a, **k: 9999)})()
        with patch("web.rate_limit.get_redis", return_value=fake_redis), \
             patch("web.routes.marketing._insert_marketing_events"):
            resp = self.client.post(
                "/api/v1/marketing-events",
                json={"events": [{"event": "pageview", "path": "/"}]},
            )
            assert resp.status_code == 429
            assert resp.get_json()["error"]["code"] == "RATE_LIMITED"
