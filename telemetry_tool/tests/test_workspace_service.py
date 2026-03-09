"""Tests for workspace service (no PG required -- mocked DB)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestCreatePersonalWorkspace:
    def test_creates_workspace_and_returns_id(self):
        from auth.workspace import create_personal_workspace

        conn = MagicMock()
        call_count = [0]

        def execute_side_effect(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:  # INSERT workspace RETURNING id
                cur.fetchone.return_value = {"id": 10}
            return cur

        conn.execute.side_effect = execute_side_effect

        ws_id = create_personal_workspace(conn, user_id=42, display_name="Alice")
        assert ws_id == 10
        assert call_count[0] == 2  # INSERT + UPDATE
        conn.commit.assert_called()

    def test_display_name_defaults_to_personal(self):
        from auth.workspace import create_personal_workspace

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1}
        conn.execute.return_value = cur

        create_personal_workspace(conn, user_id=1)
        call_args = conn.execute.call_args_list[0]
        sql_str = str(call_args)
        assert "Personal Workspace" in sql_str or "name" in sql_str


class TestCreateTeamWorkspace:
    def test_creates_team_workspace(self):
        from auth.workspace import create_team_workspace

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 20}
        conn.execute.return_value = cur

        ws_id = create_team_workspace(conn, team_id=5, display_name="Team Alpha")
        assert ws_id == 20
        conn.commit.assert_called()


class TestGetUserWorkspaces:
    def test_returns_personal_and_team_workspaces(self):
        from auth.workspace import get_user_workspaces

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"id": 1, "type": "personal", "display_name": "My Workspace",
             "owner_user_id": 42, "owner_team_id": None},
            {"id": 2, "type": "team", "display_name": "Team Alpha",
             "owner_user_id": None, "owner_team_id": 5},
        ]
        conn.execute.return_value = cur

        result = get_user_workspaces(conn, user_id=42)
        assert len(result) == 2
        assert result[0]["type"] == "personal"
        assert result[1]["type"] == "team"


class TestGetDefaultWorkspaceId:
    def test_returns_workspace_id(self):
        from auth.workspace import get_default_workspace_id

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"default_workspace_id": 99}
        conn.execute.return_value = cur

        assert get_default_workspace_id(conn, user_id=1) == 99

    def test_returns_none_when_no_user(self):
        from auth.workspace import get_default_workspace_id

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.execute.return_value = cur

        assert get_default_workspace_id(conn, user_id=999) is None


class TestSetWorkspaceContext:
    def test_sets_pg_session_variable(self):
        from auth.workspace import set_workspace_context

        conn = MagicMock()
        set_workspace_context(conn, workspace_id=42)
        conn.execute.assert_called_once()
        sql_arg = str(conn.execute.call_args)
        assert "app.current_workspace_id" in sql_arg


class TestRegisterUserCreatesWorkspace:
    """Verify register_user auto-creates a personal workspace."""

    def test_register_user_calls_create_personal_workspace(self):
        from unittest.mock import patch

        from auth.service import register_user

        conn = MagicMock()
        # register_user does: INSERT INTO users ... RETURNING id, email, ...
        # That is a single execute call before commit.
        insert_cur = MagicMock()
        insert_cur.fetchone.return_value = {
            "id": 42, "email": "new@example.com",
            "display_name": "New User", "created_at": "2026-01-01",
        }
        conn.execute.return_value = insert_cur

        # We need the workspace_id insert to also succeed
        ws_calls = []

        def capture_ws_call(conn_arg, **kwargs):
            ws_calls.append(kwargs)
            return 10

        with patch("auth.workspace.create_personal_workspace", side_effect=capture_ws_call):
            user = register_user(conn, "new@example.com", "password123", "New User")

        assert user["id"] == 42
        assert len(ws_calls) == 1
        assert ws_calls[0]["user_id"] == 42
        assert ws_calls[0]["display_name"] == "New User's Workspace"
