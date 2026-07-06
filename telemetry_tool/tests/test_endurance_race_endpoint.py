"""Tests for POST /api/v1/sessions/<id>/endurance-race — the session-to-race
bridge endpoint.

Verifies the endpoint resolves the plan-based race duration limit
server-side from entitlements, rather than trusting a client-supplied
max_duration_s (which would let any tier bypass its cap).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app():
    """Flask app with the data_v2 blueprint and a fake authenticated request
    context (the real auth middleware normally sets g.current_user_id /
    g.workspace_id before the route runs)."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False

    @app.before_request
    def _fake_auth():
        g.current_user_id = 7
        g.workspace_id = 3

    from web.routes.data_v2 import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestCreateEnduranceRaceDurationLimit:
    """create_endurance_race must resolve max_duration_s from entitlements,
    not from the client-supplied request body."""

    def test_ignores_client_supplied_max_duration_uses_entitlements(self, app, client):
        """A client claiming max_duration_s=999999 must NOT override the
        server-resolved racer-tier 24h (86400s) cap."""
        fake_session = {"session_id": "sess-1"}
        fake_entitlements = {
            "plan_tier": "racer",
            "race_strategy_max_duration_s": 86400,
        }

        with patch("web.routes.data_v2.models.get_session_by_id", return_value=fake_session), \
             patch("web.routes.data_v2.get_db_connection", return_value=MagicMock()), \
             patch("auth.entitlements.get_user_entitlements", return_value=fake_entitlements), \
             patch("services.race_strategy_bridge.create_race_from_session", return_value=42) as mock_bridge:

            response = client.post(
                "/api/v1/sessions/sess-1/endurance-race",
                json={
                    "race": {"race_name": "Test 24h"},
                    "driver_map": {"1": "Alice", "2": "Bob"},
                    "max_duration_s": 999999,  # client tries to bypass the cap
                },
            )

            assert response.status_code == 201
            mock_bridge.assert_called_once()
            _, kwargs = mock_bridge.call_args
            assert kwargs["max_duration_s"] == 86400  # server-resolved, not 999999


class TestCreateEnduranceRaceNoAuthContext:
    """Without an authenticated request context (desktop/no-auth mode), the
    endpoint must not raise — it falls back to no duration limit, matching
    create_race_endpoint's existing fail-open behavior."""

    def test_no_user_context_allows_unlimited(self):
        from flask import Flask

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["USE_PG"] = False
        from web.routes.data_v2 import bp
        app.register_blueprint(bp)
        client = app.test_client()

        fake_session = {"session_id": "sess-1"}
        with patch("web.routes.data_v2.models.get_session_by_id", return_value=fake_session), \
             patch("web.routes.data_v2.get_db_connection", return_value=MagicMock()), \
             patch("services.race_strategy_bridge.create_race_from_session", return_value=99) as mock_bridge:

            response = client.post(
                "/api/v1/sessions/sess-1/endurance-race",
                json={
                    "race": {"race_name": "No Auth Test"},
                    "driver_map": {"1": "Alice", "2": "Bob"},
                },
            )

            assert response.status_code == 201
            _, kwargs = mock_bridge.call_args
            assert kwargs["max_duration_s"] is None
