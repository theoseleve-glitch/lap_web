"""Team invitation service — create, accept, decline, list invitations.

Invitations use a token-based flow: the invite generates a secret token
that's emailed to the invitee. The token_hash (SHA-256) is stored in
the ``invitations`` table. Accepting uses the raw token to find and
consume the invitation.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_INVITE_EXPIRY_DAYS = 7


def _hash_token(token: str) -> str:
    """SHA-256 hash of an invitation token."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_invite(
    conn,
    team_id: int,
    inviter_id: int,
    email: str,
    role: str = "member",
) -> str:
    """Create a team invitation and return the raw invite token.

    The caller is responsible for sending the invitation email.
    """
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=_INVITE_EXPIRY_DAYS)

    # Remove any existing pending invite for same email+team
    conn.execute(
        "DELETE FROM invitations WHERE team_id = %(tid)s AND email = %(email)s",
        {"tid": team_id, "email": email.lower()},
    )

    conn.execute(
        "INSERT INTO invitations (team_id, email, role, token_hash, inviter_id, expires_at) "
        "VALUES (%(tid)s, %(email)s, %(role)s, %(thash)s, %(inv)s, %(exp)s)",
        {
            "tid": team_id,
            "email": email.lower(),
            "role": role,
            "thash": token_hash,
            "inv": inviter_id,
            "exp": expires_at,
        },
    )
    conn.commit()

    return token


def accept_invite(conn, token: str, user_id: int) -> dict:
    """Accept an invitation. Adds user to the team.

    Returns ``{"team_id": int, "role": str}`` on success.
    Raises ``ValueError`` if token is invalid or expired.
    """
    token_hash = _hash_token(token)
    row = conn.execute(
        "SELECT id, team_id, email, role, inviter_id, expires_at "
        "FROM invitations WHERE token_hash = %(thash)s",
        {"thash": token_hash},
    ).fetchone()

    if row is None:
        raise ValueError("Invalid invitation token")

    invite = dict(row) if not isinstance(row, dict) else row

    if invite["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        # Clean up expired invite
        conn.execute(
            "DELETE FROM invitations WHERE id = %(id)s", {"id": invite["id"]},
        )
        conn.commit()
        raise ValueError("Invitation has expired")

    team_id = invite["team_id"]
    role = invite["role"]

    # Get the workspace_id for this team (workspaces.owner_team_id → teams.id)
    ws_row = conn.execute(
        "SELECT id AS workspace_id FROM workspaces WHERE owner_team_id = %(tid)s",
        {"tid": team_id},
    ).fetchone()

    if ws_row is None:
        raise ValueError("Team workspace not found")

    ws_data = dict(ws_row) if not isinstance(ws_row, dict) else ws_row
    workspace_id = ws_data["workspace_id"]

    # Add user to team_members (idempotent)
    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role) "
        "VALUES (%(tid)s, %(uid)s, %(role)s) "
        "ON CONFLICT (team_id, user_id) DO UPDATE SET role = %(role)s",
        {"tid": team_id, "uid": user_id, "role": role},
    )

    # Add user to workspace_members
    conn.execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role) "
        "VALUES (%(wsid)s, %(uid)s, %(role)s) "
        "ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = %(role)s",
        {"wsid": workspace_id, "uid": user_id, "role": role},
    )

    # Delete the invitation
    conn.execute(
        "DELETE FROM invitations WHERE id = %(id)s", {"id": invite["id"]},
    )
    conn.commit()

    logger.info(
        "Invitation accepted: user=%s team=%s role=%s",
        user_id, team_id, role,
    )

    return {"team_id": team_id, "role": role, "workspace_id": workspace_id}


def decline_invite(conn, token: str) -> bool:
    """Decline (delete) an invitation. Returns True if found."""
    token_hash = _hash_token(token)
    row = conn.execute(
        "DELETE FROM invitations WHERE token_hash = %(thash)s RETURNING id",
        {"thash": token_hash},
    ).fetchone()
    conn.commit()
    return row is not None


def list_pending_invites(conn, team_id: int) -> list[dict]:
    """List all pending (non-expired) invitations for a team."""
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT i.id, i.email, i.role, i.created_at, i.expires_at, "
        "u.display_name AS inviter_name "
        "FROM invitations i "
        "LEFT JOIN users u ON u.id = i.inviter_id "
        "WHERE i.team_id = %(tid)s AND i.expires_at > %(now)s "
        "ORDER BY i.created_at DESC",
        {"tid": team_id, "now": now},
    ).fetchall()

    return [
        {
            "id": (dict(r) if not isinstance(r, dict) else r)["id"],
            "email": (dict(r) if not isinstance(r, dict) else r)["email"],
            "role": (dict(r) if not isinstance(r, dict) else r)["role"],
            "inviter_name": (dict(r) if not isinstance(r, dict) else r).get("inviter_name"),
            "created_at": (dict(r) if not isinstance(r, dict) else r)["created_at"].isoformat()
                if (dict(r) if not isinstance(r, dict) else r).get("created_at") else None,
            "expires_at": (dict(r) if not isinstance(r, dict) else r)["expires_at"].isoformat()
                if (dict(r) if not isinstance(r, dict) else r).get("expires_at") else None,
        }
        for r in rows
    ]


def cancel_invite(conn, invite_id: int, team_id: int) -> bool:
    """Cancel a specific invitation. Returns True if found and deleted."""
    row = conn.execute(
        "DELETE FROM invitations WHERE id = %(id)s AND team_id = %(tid)s RETURNING id",
        {"id": invite_id, "tid": team_id},
    ).fetchone()
    conn.commit()
    return row is not None
