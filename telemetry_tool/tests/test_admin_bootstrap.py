"""Tests for admin bootstrap CLI.

Validates:
- promote_to_superadmin sets is_superadmin=True and admin_role
- Returns False when user not found
- Supports all valid admin roles
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class FakeConn:
    """Fake DB connection for bootstrap tests."""

    def __init__(self, user_exists=True):
        self._calls = []
        self._committed = False
        self._user_exists = user_exists

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        cur = MagicMock()
        if "UPDATE" in sql.upper():
            cur.rowcount = 1 if self._user_exists else 0
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        return cur

    def commit(self):
        self._committed = True


class TestPromoteToSuperadmin:
    def test_promotes_existing_user(self):
        from admin.bootstrap import promote_to_superadmin

        conn = FakeConn(user_exists=True)
        result = promote_to_superadmin(conn, "admin@lap-coach.racing")

        assert result is True
        assert conn._committed is True
        # Verify the UPDATE SQL
        sql, params = conn._calls[0]
        assert "UPDATE" in sql.upper()
        assert "is_superadmin" in sql
        assert "admin_role" in sql
        assert params["email"] == "admin@lap-coach.racing"
        assert params["admin_role"] == "root_admin"

    def test_returns_false_for_missing_user(self):
        from admin.bootstrap import promote_to_superadmin

        conn = FakeConn(user_exists=False)
        result = promote_to_superadmin(conn, "nobody@test.com")

        assert result is False

    def test_custom_role(self):
        from admin.bootstrap import promote_to_superadmin

        conn = FakeConn(user_exists=True)
        result = promote_to_superadmin(
            conn, "sre@lap-coach.racing", admin_role="sre_admin"
        )

        assert result is True
        params = conn._calls[0][1]
        assert params["admin_role"] == "sre_admin"

    @pytest.mark.parametrize("role", [
        "root_admin", "support_admin", "billing_admin", "sre_admin", "auditor",
    ])
    def test_all_valid_roles(self, role):
        from admin.bootstrap import promote_to_superadmin

        conn = FakeConn(user_exists=True)
        result = promote_to_superadmin(conn, "test@test.com", admin_role=role)
        assert result is True
        assert conn._calls[0][1]["admin_role"] == role
