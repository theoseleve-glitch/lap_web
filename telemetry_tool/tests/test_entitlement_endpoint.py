"""Tests for entitlement snapshot API endpoint."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.routes.api_v1_account import bp


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)

    @app.before_request
    def _inject_user():
        g.current_user_id = 42

    return app


def test_entitlement_endpoint_returns_plan_and_entitlements():
    app = _make_app()
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"plan_tier": "racer"}

    with app.test_client() as client:
        with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
            resp = client.get("/api/v1/account/entitlements")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["ok"] is True
            assert body["data"]["plan"] == "racer"
            assert body["data"]["entitlements"]["coaching_drills"] is True
            assert body["data"]["entitlements"]["api_access"] is False


def test_entitlement_endpoint_defaults_to_locked_for_null_tier():
    app = _make_app()
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"plan_tier": None}

    with app.test_client() as client:
        with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
            resp = client.get("/api/v1/account/entitlements")
            assert resp.status_code == 200
            body = resp.get_json()
            # No-subscription floor: null/missing tier resolves to 'locked'
            # (no free tier in the one-membership model) with zero access.
            assert body["data"]["plan"] == "locked"
            assert body["data"]["entitlements"]["analyses_per_month"] == 0
