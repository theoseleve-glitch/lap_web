"""Workspace management — create, list, set context."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_personal_workspace(
    conn, user_id: int, display_name: str = "Personal Workspace"
) -> int:
    """Create a personal workspace for a user and set it as their default.
    Returns the new workspace ID.
    """
    cur = conn.execute(
        "INSERT INTO workspaces (type, owner_user_id, display_name) "
        "VALUES (%(type)s, %(uid)s, %(name)s) RETURNING id",
        {"type": "personal", "uid": user_id, "name": display_name},
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to create personal workspace — INSERT returned no rows")
    ws_id = row["id"]

    conn.execute(
        "UPDATE users SET default_workspace_id = %(ws)s WHERE id = %(uid)s",
        {"ws": ws_id, "uid": user_id},
    )
    conn.commit()
    return ws_id


def create_team_workspace(conn, team_id: int, display_name: str) -> int:
    """Create a workspace for a team. Returns the new workspace ID."""
    cur = conn.execute(
        "INSERT INTO workspaces (type, owner_team_id, display_name) "
        "VALUES (%(type)s, %(tid)s, %(name)s) RETURNING id",
        {"type": "team", "tid": team_id, "name": display_name},
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to create team workspace — INSERT returned no rows")
    ws_id = row["id"]
    conn.commit()
    return ws_id


def get_user_workspaces(conn, user_id: int) -> list[dict]:
    """Return all workspaces a user can access (personal + team memberships)."""
    cur = conn.execute(
        "SELECT w.id, w.type, w.display_name, w.owner_user_id, w.owner_team_id "
        "FROM workspaces w "
        "LEFT JOIN team_members tm ON w.owner_team_id = tm.team_id "
        "WHERE w.owner_user_id = %(uid)s "
        "   OR tm.user_id = %(uid)s "
        "ORDER BY w.type, w.display_name",
        {"uid": user_id},
    )
    return [dict(row) for row in cur.fetchall()]


def get_default_workspace_id(conn, user_id: int) -> int | None:
    """Return the user's default workspace ID."""
    cur = conn.execute(
        "SELECT default_workspace_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    row = cur.fetchone()
    return row["default_workspace_id"] if row else None


def set_workspace_context(conn, workspace_id: int) -> None:
    """Set the PostgreSQL session variable for RLS.
    Must be called at the start of each request.
    Uses SET LOCAL so setting is scoped to current transaction.
    """
    conn.execute(
        "SET LOCAL app.current_workspace_id = %(ws)s",
        {"ws": str(workspace_id)},
    )
