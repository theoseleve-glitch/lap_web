"""Tests for team service (no PG required -- mocked DB)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.service import AuthError


class TestCreateTeam:
    def test_creates_team_and_workspace(self):
        from auth.teams import create_team

        conn = MagicMock()
        call_count = [0]

        def execute_side_effect(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:  # INSERT team RETURNING id
                cur.fetchone.return_value = {"id": 5}
            elif call_count[0] == 3:  # INSERT workspace RETURNING id (via create_team_workspace)
                cur.fetchone.return_value = {"id": 20}
            return cur

        conn.execute.side_effect = execute_side_effect

        result = create_team(conn, owner_id=1, name="Alpha Racing", slug="alpha-racing")
        assert result["team_id"] == 5
        assert result["workspace_id"] == 20

    def test_slug_must_be_unique(self):
        from auth.teams import create_team

        conn = MagicMock()
        conn.execute.side_effect = Exception("duplicate key value violates unique constraint")

        with pytest.raises(AuthError) as exc_info:
            create_team(conn, owner_id=1, name="Dup", slug="dup-slug")
        assert exc_info.value.code == "CONFLICT"


class TestAddMember:
    def test_adds_member_with_role(self):
        from auth.teams import add_member

        conn = MagicMock()
        add_member(conn, team_id=5, user_id=10, role="member")
        conn.execute.assert_called_once()
        conn.commit.assert_called()

    def test_rejects_invalid_role(self):
        from auth.teams import add_member

        conn = MagicMock()
        with pytest.raises(AuthError, match="Invalid role"):
            add_member(conn, team_id=5, user_id=10, role="superadmin")


class TestChangeMemberRole:
    def test_changes_role(self):
        from auth.teams import change_member_role

        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 1
        conn.execute.return_value = cur

        change_member_role(conn, team_id=5, user_id=10, new_role="admin")
        conn.commit.assert_called()

    def test_rejects_invalid_role(self):
        from auth.teams import change_member_role

        conn = MagicMock()
        with pytest.raises(AuthError, match="Invalid role"):
            change_member_role(conn, team_id=5, user_id=10, new_role="dictator")

    def test_member_not_found(self):
        from auth.teams import change_member_role

        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.execute.return_value = cur

        with pytest.raises(AuthError, match="Member not found"):
            change_member_role(conn, team_id=5, user_id=999, new_role="admin")


class TestRemoveMember:
    def test_removes_member(self):
        from auth.teams import remove_member

        conn = MagicMock()
        call_count = [0]

        def execute_side(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:  # SELECT role
                cur.fetchone.return_value = {"role": "member"}
            elif call_count[0] == 2:  # DELETE
                cur.rowcount = 1
            return cur

        conn.execute.side_effect = execute_side
        remove_member(conn, team_id=5, user_id=10)
        conn.commit.assert_called()

    def test_cannot_remove_owner(self):
        from auth.teams import remove_member

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"role": "owner"}
        conn.execute.return_value = cur

        with pytest.raises(AuthError, match="Cannot remove team owner"):
            remove_member(conn, team_id=5, user_id=1)


class TestGetUserRoleInTeam:
    def test_returns_role(self):
        from auth.teams import get_user_role_in_team

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"role": "admin"}
        conn.execute.return_value = cur

        assert get_user_role_in_team(conn, team_id=5, user_id=10) == "admin"

    def test_returns_none_for_non_member(self):
        from auth.teams import get_user_role_in_team

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.execute.return_value = cur

        assert get_user_role_in_team(conn, team_id=5, user_id=999) is None
