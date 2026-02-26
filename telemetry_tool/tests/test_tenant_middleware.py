"""Tests for tenant middleware (no PG required -- mocked)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestTenantMiddleware:
    def test_sets_workspace_from_header(self):
        """X-Workspace-Id header sets g.workspace_id."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        mock_conn = MagicMock()
        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "42"},
        ):
            g.current_user_id = 1
            with patch("web.middleware.tenant._verify_workspace_access", return_value=True), \
                 patch("web.middleware.tenant._set_rls_context") as mock_rls, \
                 patch("web.middleware.tenant._resolve_workspace_role", return_value="admin"), \
                 patch("web.db_pg.get_pg_connection", return_value=mock_conn):
                tenant_middleware()
                assert g.workspace_id == 42
                assert g.workspace_role == "admin"
                mock_rls.assert_called_once_with(42)

    def test_falls_back_to_default_workspace(self):
        """Without header, uses user's default workspace."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        mock_conn = MagicMock()
        with app.test_request_context("/api/v1/sessions"):
            g.current_user_id = 1
            with patch("web.middleware.tenant.get_default_workspace_id", return_value=99), \
                 patch("web.middleware.tenant._set_rls_context") as mock_rls, \
                 patch("web.middleware.tenant._resolve_workspace_role", return_value="member"), \
                 patch("web.db_pg.get_pg_connection", return_value=mock_conn):
                tenant_middleware()
                assert g.workspace_id == 99
                mock_rls.assert_called_once_with(99)

    def test_skips_non_api_routes(self):
        """Non-/api/v1/ routes don't need workspace resolution."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context("/static/main.css"):
            result = tenant_middleware()
            assert result is None
            assert not hasattr(g, "workspace_id")

    def test_legacy_mode_uses_default_workspace(self):
        """When AUTH_REQUIRED=False, use default workspace for all requests."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = False
        app.config["USE_PG"] = True
        app.config["DEFAULT_WORKSPACE_ID"] = 1

        with app.test_request_context("/api/v1/sessions"):
            with patch("web.middleware.tenant._set_rls_context") as mock_rls:
                tenant_middleware()
                assert g.workspace_id == 1
                mock_rls.assert_called_once_with(1)

    def test_returns_403_when_no_workspace_access(self):
        """Returns 403 if user doesn't have access to requested workspace."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "999"},
        ):
            g.current_user_id = 1
            with patch("web.middleware.tenant._verify_workspace_access", return_value=False):
                result = tenant_middleware()
                assert result is not None
                response, status_code = result
                assert status_code == 403

    def test_skips_when_sqlite_mode(self):
        """When USE_PG is False, middleware is a no-op."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["USE_PG"] = False

        with app.test_request_context("/api/v1/sessions"):
            result = tenant_middleware()
            assert result is None
            assert not hasattr(g, "workspace_id")

    def test_invalid_workspace_header_returns_400(self):
        """Non-integer X-Workspace-Id returns 400."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "not-a-number"},
        ):
            g.current_user_id = 1
            result = tenant_middleware()
            assert result is not None
            response, status_code = result
            assert status_code == 400

    def test_no_default_workspace_returns_404(self):
        """When user has no default workspace, returns 404."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        mock_conn = MagicMock()
        with app.test_request_context("/api/v1/sessions"):
            g.current_user_id = 1
            with patch("web.middleware.tenant.get_default_workspace_id", return_value=None), \
                 patch("web.db_pg.get_pg_connection", return_value=mock_conn):
                result = tenant_middleware()
                assert result is not None
                response, status_code = result
                assert status_code == 404

    def test_no_user_id_defers_to_auth_middleware(self):
        """When g.current_user_id is not set, returns None (auth handles 401)."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context("/api/v1/sessions"):
            # Do NOT set g.current_user_id
            result = tenant_middleware()
            assert result is None
            assert not hasattr(g, "workspace_id")


class TestWorkspaceRoleResolution:
    def test_personal_workspace_owner_gets_owner_role(self):
        """Owner of personal workspace gets 'owner' role."""
        from web.middleware.tenant import _resolve_workspace_role
        from flask import Flask, g

        app = Flask(__name__)
        with app.test_request_context():
            conn = MagicMock()
            # Workspace owned by user
            cur = MagicMock()
            cur.fetchone.return_value = {"type": "personal", "owner_user_id": 1, "owner_team_id": None}
            conn.execute.return_value = cur

            role = _resolve_workspace_role(conn, user_id=1, workspace_id=10)
            assert role == "owner"

    def test_team_member_gets_team_role(self):
        """Team member gets their role from team_members."""
        from web.middleware.tenant import _resolve_workspace_role
        from flask import Flask, g

        app = Flask(__name__)
        with app.test_request_context():
            conn = MagicMock()
            call_count = [0]

            def execute_side(sql, params=None):
                cur = MagicMock()
                call_count[0] += 1
                if call_count[0] == 1:  # workspace lookup
                    cur.fetchone.return_value = {"type": "team", "owner_user_id": None, "owner_team_id": 5}
                elif call_count[0] == 2:  # team_members role
                    cur.fetchone.return_value = {"role": "admin"}
                return cur

            conn.execute.side_effect = execute_side
            role = _resolve_workspace_role(conn, user_id=10, workspace_id=20)
            assert role == "admin"
