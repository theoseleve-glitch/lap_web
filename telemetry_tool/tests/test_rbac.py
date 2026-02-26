"""Tests for RBAC permission system (no PG required)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestRoleHierarchy:
    def test_owner_has_all_permissions(self):
        from auth.rbac import has_permission
        assert has_permission("owner", "delete_workspace")
        assert has_permission("owner", "upload_csv")
        assert has_permission("owner", "view_sessions")

    def test_admin_cannot_delete_workspace(self):
        from auth.rbac import has_permission
        assert not has_permission("admin", "delete_workspace")
        assert has_permission("admin", "manage_members")
        assert has_permission("admin", "upload_csv")

    def test_member_limited(self):
        from auth.rbac import has_permission
        assert has_permission("member", "upload_csv")
        assert has_permission("member", "view_sessions")
        assert not has_permission("member", "manage_members")
        assert not has_permission("member", "delete_sessions")

    def test_viewer_read_only(self):
        from auth.rbac import has_permission
        assert has_permission("viewer", "view_sessions")
        assert not has_permission("viewer", "upload_csv")
        assert not has_permission("viewer", "delete_sessions")


class TestRequireRoleDecorator:
    def test_allows_sufficient_role(self):
        from auth.rbac import require_role

        app = Flask(__name__)
        app.config["USE_PG"] = True

        @require_role("member")
        def test_view():
            return "ok"

        with app.test_request_context("/api/v1/test"):
            g.current_user_id = 1
            g.workspace_id = 10
            g.workspace_role = "admin"  # admin >= member
            result = test_view()
            assert result == "ok"

    def test_rejects_insufficient_role(self):
        from auth.rbac import require_role

        app = Flask(__name__)
        app.config["USE_PG"] = True

        @require_role("admin")
        def test_view():
            return "ok"

        with app.test_request_context("/api/v1/test"):
            g.current_user_id = 1
            g.workspace_id = 10
            g.workspace_role = "viewer"
            result, status = test_view()
            assert status == 403
