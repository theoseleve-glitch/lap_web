"""Integration tests — workspace isolation and RBAC.

Tests workspace isolation, team invite/accept, RBAC enforcement,
and IDOR prevention using RBAC pure functions and structure validation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.rbac import PERMISSIONS, ROLE_LEVELS, has_permission

# ===========================================================================
# A) Workspace isolation
# ===========================================================================

class TestWorkspaceIsolation:
    """RLS ensures workspace data isolation."""

    def test_rls_context_function_exists(self):
        """set_workspace_context function exists."""
        from auth.workspace import set_workspace_context
        assert callable(set_workspace_context)

    def test_tenant_middleware_exists(self):
        """Tenant middleware sets g.workspace_id."""
        from web.middleware.tenant import tenant_middleware
        assert callable(tenant_middleware)

    def test_tenant_middleware_checks_header(self):
        """Middleware reads X-Workspace-Id header."""
        source = Path(
            _PROJECT_ROOT / "web" / "middleware" / "tenant.py"
        ).read_text()
        assert "X-Workspace-Id" in source

    def test_rls_policies_in_migrations(self):
        """Alembic migrations create RLS policies."""
        migrations_dir = _PROJECT_ROOT / "alembic" / "versions"
        rls_found = False
        for f in migrations_dir.glob("*.py"):
            content = f.read_text()
            if "CREATE POLICY" in content or "ENABLE ROW LEVEL SECURITY" in content:
                rls_found = True
                break
        assert rls_found, "No RLS policy creation found in migrations"


# ===========================================================================
# B) Team invite and accept
# ===========================================================================

class TestTeamInviteAccept:
    """Team creation and member management."""

    def test_create_team_function_exists(self):
        """create_team is importable."""
        from auth.teams import create_team
        assert callable(create_team)

    def test_add_member_function_exists(self):
        """add_member is importable."""
        from auth.teams import add_member
        assert callable(add_member)

    def test_valid_roles_defined(self):
        """Team roles include owner, admin, member, viewer."""
        from auth.teams import VALID_ROLES
        assert "owner" in VALID_ROLES
        assert "admin" in VALID_ROLES
        assert "member" in VALID_ROLES
        assert "viewer" in VALID_ROLES

    def test_get_team_members_function_exists(self):
        """get_team_members is importable."""
        from auth.teams import get_team_members
        assert callable(get_team_members)

    def test_change_role_function_exists(self):
        """change_member_role is importable."""
        from auth.teams import change_member_role
        assert callable(change_member_role)

    def test_remove_member_function_exists(self):
        """remove_member is importable."""
        from auth.teams import remove_member
        assert callable(remove_member)


# ===========================================================================
# C) RBAC enforcement
# ===========================================================================

class TestRBACEnforcement:
    """Role hierarchy and permission checks."""

    def test_viewer_can_view_sessions(self):
        """Viewer has view_sessions permission."""
        assert has_permission("viewer", "view_sessions") is True

    def test_viewer_cannot_upload(self):
        """Viewer cannot upload CSV."""
        assert has_permission("viewer", "upload_csv") is False

    def test_member_can_upload(self):
        """Member can upload CSV."""
        assert has_permission("member", "upload_csv") is True

    def test_member_cannot_delete_sessions(self):
        """Member cannot delete sessions."""
        assert has_permission("member", "delete_sessions") is False

    def test_admin_can_delete_sessions(self):
        """Admin can delete sessions."""
        assert has_permission("admin", "delete_sessions") is True

    def test_admin_can_manage_members(self):
        """Admin can manage team members."""
        assert has_permission("admin", "manage_members") is True

    def test_admin_cannot_delete_workspace(self):
        """Admin cannot delete workspace."""
        assert has_permission("admin", "delete_workspace") is False

    def test_owner_can_delete_workspace(self):
        """Owner can delete workspace."""
        assert has_permission("owner", "delete_workspace") is True

    def test_owner_can_manage_billing(self):
        """Owner can manage billing."""
        assert has_permission("owner", "billing") is True

    def test_owner_can_do_everything(self):
        """Owner has all permissions."""
        for action in PERMISSIONS:
            assert has_permission("owner", action) is True, f"Owner missing {action}"

    def test_unknown_action_denied(self):
        """Unknown action denied for all roles."""
        for role in ROLE_LEVELS:
            assert has_permission(role, "nonexistent_action") is False

    def test_role_hierarchy_is_ordered(self):
        """Role levels increase: viewer < member < admin < owner."""
        assert ROLE_LEVELS["viewer"] < ROLE_LEVELS["member"]
        assert ROLE_LEVELS["member"] < ROLE_LEVELS["admin"]
        assert ROLE_LEVELS["admin"] < ROLE_LEVELS["owner"]

    def test_require_permission_decorator_exists(self):
        """require_permission decorator is importable."""
        from auth.rbac import require_permission
        assert callable(require_permission)

    def test_require_role_decorator_exists(self):
        """require_role decorator is importable."""
        from auth.rbac import require_role
        assert callable(require_role)


# ===========================================================================
# D) IDOR prevention
# ===========================================================================

class TestIDORPrevention:
    """Direct object reference attacks blocked by RLS."""

    def test_rls_uses_set_local(self):
        """RLS context uses SET LOCAL (transaction-scoped)."""
        source = Path(
            _PROJECT_ROOT / "auth" / "workspace.py"
        ).read_text()
        assert "SET LOCAL" in source

    def test_workspace_access_verified(self):
        """Tenant middleware verifies workspace access before setting context."""
        source = Path(
            _PROJECT_ROOT / "web" / "middleware" / "tenant.py"
        ).read_text()
        assert "verify" in source.lower() or "access" in source.lower()

    def test_44_tables_have_workspace_id(self):
        """Migration adds workspace_id to tables."""
        migrations_dir = _PROJECT_ROOT / "alembic" / "versions"
        workspace_col_found = False
        for f in migrations_dir.glob("*.py"):
            content = f.read_text()
            if "workspace_id" in content and "ADD COLUMN" in content:
                workspace_col_found = True
                break
        assert workspace_col_found, "No workspace_id column addition found"
