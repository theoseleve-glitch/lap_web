# tests/test_consent_api.py
"""POST /api/v1/consent — upsert user_consent + write audit_log row."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_app():
    from flask import Flask, g
    from web.api_utils import init_request_id
    from web.routes.consent import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    app.config["JWT_SECRET"] = "test-secret"
    init_request_id(app)

    @app.before_request
    def _set_fake_user():
        g.current_user_id = 7
        g.workspace_id = 3

    app.register_blueprint(bp)
    return app


class TestPostConsent:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = _make_app()
        self.client = self.app.test_client()

    def test_upsert_and_audit_written(self):
        fake_conn = MagicMock()
        with patch("web.routes.consent._get_conn", return_value=fake_conn):
            resp = self.client.post(
                "/api/v1/consent",
                json={"analytics": True, "marketing": False, "version": 2},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["data"] == {"analytics": True, "marketing": False, "version": 2}

            # Two writes: the user_consent upsert and the audit_log insert.
            sqls = [c.args[0] for c in fake_conn.execute.call_args_list]
            assert any("INTO user_consent" in s and "ON CONFLICT" in s for s in sqls)
            audit_calls = [c for c in fake_conn.execute.call_args_list
                           if "INTO audit_log" in c.args[0]]
            assert len(audit_calls) == 1
            audit_params = audit_calls[0].args[1]
            assert audit_params["action"] == "consent_changed"
            assert json.loads(audit_params["details"]) == {
                "analytics": True, "marketing": False, "version": 2,
            }
            fake_conn.commit.assert_called_once()

    def test_rejects_non_boolean_analytics(self):
        resp = self.client.post(
            "/api/v1/consent",
            json={"analytics": "yes", "marketing": False, "version": 1},
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_rejects_missing_version(self):
        resp = self.client.post(
            "/api/v1/consent",
            json={"analytics": True, "marketing": False},
        )
        assert resp.status_code == 422
