"""Tests for cross-tenant data access prevention (#0770).

Verifies that the tenant middleware prevents users from
accessing other workspaces' data through the API.
Uses unit tests against the middleware function directly.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import init_request_id
from web.middleware.tenant import tenant_middleware


def _make_app(**config_overrides):
    """Minimal Flask app with tenant middleware registered."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    app.config.update(config_overrides)
    init_request_id(app)

    @app.route("/api/v1/sessions")
    def sessions():
        from web.api_utils import api_response
        return api_response({"ws": getattr(g, "workspace_id", None)})

    return app


class TestNonNumericWorkspaceId:
    def test_rejects_non_numeric(self):
        app = _make_app()
        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "abc"},
        ):
            g.current_user_id = 1
            result = tenant_middleware()
            assert result is not None
            resp, status = result
            assert status == 400


class TestForeignWorkspaceBlocked:
    @patch("web.middleware.tenant._verify_workspace_access", return_value=False)
    def test_foreign_workspace_returns_403(self, mock_verify):
        app = _make_app()
        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "999"},
        ):
            g.current_user_id = 1
            result = tenant_middleware()
            assert result is not None
            resp, status = result
            assert status == 403

    @patch("web.middleware.tenant._verify_workspace_access", return_value=True)
    @patch("web.middleware.tenant._set_rls_context")
    @patch("web.middleware.tenant._resolve_workspace_role", return_value="member")
    @patch("web.db_pg.get_pg_connection")
    def test_own_workspace_allowed(self, mock_conn, mock_role, mock_rls, mock_verify):
        mock_conn.return_value = MagicMock()
        app = _make_app()
        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "1"},
        ):
            g.current_user_id = 1
            result = tenant_middleware()
            assert result is None  # No error = allowed


class TestRLSContextSetup:
    @patch("web.middleware.tenant._verify_workspace_access", return_value=True)
    @patch("web.middleware.tenant._set_rls_context")
    @patch("web.middleware.tenant._resolve_workspace_role", return_value="admin")
    @patch("web.db_pg.get_pg_connection")
    def test_rls_context_set_with_correct_workspace(self, mock_conn, mock_role, mock_rls, mock_verify):
        mock_conn.return_value = MagicMock()
        app = _make_app()
        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "42"},
        ):
            g.current_user_id = 1
            tenant_middleware()
            mock_rls.assert_called_once_with(42)

    @patch("web.middleware.tenant._verify_workspace_access", return_value=True)
    @patch("web.middleware.tenant._set_rls_context")
    @patch("web.middleware.tenant._resolve_workspace_role", return_value=None)
    @patch("web.db_pg.get_pg_connection")
    def test_no_role_returns_403(self, mock_conn, mock_role, mock_rls, mock_verify):
        mock_conn.return_value = MagicMock()
        app = _make_app()
        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "42"},
        ):
            g.current_user_id = 1
            result = tenant_middleware()
            assert result is not None
            resp, status = result
            assert status == 403


class TestDefaultWorkspaceResolution:
    @patch("web.middleware.tenant.get_default_workspace_id", return_value=7)
    @patch("web.middleware.tenant._set_rls_context")
    @patch("web.middleware.tenant._resolve_workspace_role", return_value="owner")
    @patch("web.db_pg.get_pg_connection")
    def test_uses_default_when_no_header(self, mock_conn, mock_role, mock_rls, mock_default):
        mock_conn.return_value = MagicMock()
        app = _make_app()
        with app.test_request_context("/api/v1/sessions"):
            g.current_user_id = 1
            tenant_middleware()
            assert g.workspace_id == 7

    @patch("web.middleware.tenant.get_default_workspace_id", return_value=None)
    @patch("web.db_pg.get_pg_connection")
    def test_no_default_workspace_returns_404(self, mock_conn, mock_default):
        mock_conn.return_value = MagicMock()
        app = _make_app()
        with app.test_request_context("/api/v1/sessions"):
            g.current_user_id = 1
            result = tenant_middleware()
            assert result is not None
            resp, status = result
            assert status == 404


class TestSQLiteModeSkipsTenancy:
    def test_sqlite_mode_returns_none(self):
        app = _make_app(USE_PG=False)
        with app.test_request_context("/api/v1/sessions"):
            result = tenant_middleware()
            assert result is None

    def test_non_api_route_skipped(self):
        app = _make_app()
        with app.test_request_context("/healthz"):
            result = tenant_middleware()
            assert result is None


class TestLegacyModeDefaultWorkspace:
    def test_legacy_mode_uses_system_default(self):
        app = _make_app(AUTH_REQUIRED=False, DEFAULT_WORKSPACE_ID=99)
        with app.test_request_context("/api/v1/sessions"):
            with patch("web.middleware.tenant._set_rls_context"):
                tenant_middleware()
                assert g.workspace_id == 99
                assert g.workspace_role == "owner"
