"""Team management — create team, manage members, roles."""
from __future__ import annotations

import logging
from auth.service import AuthError

logger = logging.getLogger(__name__)

VALID_ROLES = {"owner", "admin", "member", "viewer"}


def create_team(conn, owner_id: int, name: str, slug: str) -> dict:
    """Create a team with the given owner.
    Owner auto-added as member with role='owner'. Team workspace created.
    Returns dict with team_id and workspace_id.
    """
    try:
        cur = conn.execute(
            "INSERT INTO teams (name, slug, owner_user_id) "
            "VALUES (%(name)s, %(slug)s, %(owner)s) RETURNING id",
            {"name": name, "slug": slug, "owner": owner_id},
        )
        team_id = cur.fetchone()["id"]

        conn.execute(
            "INSERT INTO team_members (team_id, user_id, role, accepted_at) "
            "VALUES (%(tid)s, %(uid)s, 'owner', NOW())",
            {"tid": team_id, "uid": owner_id},
        )

        from auth.workspace import create_team_workspace
        ws_id = create_team_workspace(conn, team_id=team_id, display_name=name)

        conn.commit()
        return {"team_id": team_id, "workspace_id": ws_id}
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise AuthError("Team slug already taken", "CONFLICT")
        raise


def add_member(conn, team_id: int, user_id: int, role: str = "member") -> None:
    """Add a user to a team with the given role."""
    if role not in VALID_ROLES:
        raise AuthError(f"Invalid role: {role}", "VALIDATION_ERROR")

    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role) "
        "VALUES (%(tid)s, %(uid)s, %(role)s) "
        "ON CONFLICT (team_id, user_id) DO NOTHING",
        {"tid": team_id, "uid": user_id, "role": role},
    )
    conn.commit()


def change_member_role(conn, team_id: int, user_id: int, new_role: str) -> None:
    """Change a team member's role."""
    if new_role not in VALID_ROLES:
        raise AuthError(f"Invalid role: {new_role}", "VALIDATION_ERROR")

    cur = conn.execute(
        "UPDATE team_members SET role = %(role)s "
        "WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"role": new_role, "tid": team_id, "uid": user_id},
    )
    if cur.rowcount == 0:
        raise AuthError("Member not found", "NOT_FOUND")
    conn.commit()


def remove_member(conn, team_id: int, user_id: int) -> None:
    """Remove a user from a team. Cannot remove the owner."""
    cur = conn.execute(
        "SELECT role FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": team_id, "uid": user_id},
    )
    row = cur.fetchone()
    if row and row["role"] == "owner":
        raise AuthError("Cannot remove team owner", "FORBIDDEN")

    cur = conn.execute(
        "DELETE FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": team_id, "uid": user_id},
    )
    if cur.rowcount == 0:
        raise AuthError("Member not found", "NOT_FOUND")
    conn.commit()


def get_team_members(conn, team_id: int) -> list[dict]:
    """Return all members of a team with their roles."""
    cur = conn.execute(
        "SELECT u.id, u.email, u.display_name, tm.role, tm.accepted_at "
        "FROM team_members tm "
        "JOIN users u ON u.id = tm.user_id "
        "WHERE tm.team_id = %(tid)s "
        "ORDER BY tm.role, u.display_name",
        {"tid": team_id},
    )
    return [dict(row) for row in cur.fetchall()]


def get_user_role_in_team(conn, team_id: int, user_id: int) -> str | None:
    """Return the user's role in a team, or None if not a member."""
    cur = conn.execute(
        "SELECT role FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": team_id, "uid": user_id},
    )
    row = cur.fetchone()
    return row["role"] if row else None
