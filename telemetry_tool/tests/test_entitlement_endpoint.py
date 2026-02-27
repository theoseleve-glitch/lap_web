"""Tests for entitlement snapshot API endpoint."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from flask import Flask

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.routes.api_v1_account import bp


def test_entitlement_snapshot_endpoint_returns_payload():
    app = Flask(__name__)
    app.register_blueprint(bp)

    with app.test_client() as client:
        with patch("web.routes.api_v1_account.entitlement_snapshot", return_value={"tier": "Racer", "exports": True}):
            resp = client.get("/api/v1/account/entitlements")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["ok"] is True
            assert body["data"]["tier"] == "Racer"
