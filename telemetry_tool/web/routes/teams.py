"""Team management API routes — CRUD + invitation flow."""
import logging
from flask import Blueprint, g, request
from auth.rbac import require_role
from auth.service import AuthError

from web.api_utils import api_response, api_error, ErrorCode
from web.middleware.audit import audit_log
from web.rate_limit import rate_limit
from web.validation import validate_body
from web.schemas.teams import CreateTeamSchema, InviteMemberSchema

logger = logging.getLogger(__name__)

bp = Blueprint("teams", __name__, url_prefix="/api/v1/teams")


def _get_conn():
    from flask import current_app
    if not current_app.config.get("USE_PG"):
        raise RuntimeError("Team routes require PostgreSQL (USE_PG=1)")
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _verify_team_in_workspace(conn, team_id):
    """Verify that team_id belongs to the current workspace."""
    cur = conn.execute(
        "SELECT 1 FROM workspaces "
        "WHERE owner_team_id = %(tid)s AND id = %(ws)s",
        {"tid": team_id, "ws": g.workspace_id},
    )
    return cur.fetchone() is not None


@bp.route("", methods=["POST"])
@rate_limit(tier="write")
@validate_body(CreateTeamSchema)
def create_team():
    """Create a new team. Requires authenticated user."""
    from auth.teams import create_team as svc_create_team
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)

    body = g.body  # validated CreateTeamSchema
    conn = _get_conn()
    try:
        result = svc_create_team(conn, owner_id=user_id, name=body.name, slug=body.slug)
        audit_log(conn, "team_created", {"team_id": result.get("id"), "name": body.name})
        return api_response(result, status=201)
    except AuthError as e:
        status_code = 409 if e.code == "CONFLICT" else 400
        return api_error(ErrorCode.CONFLICT if e.code == "CONFLICT" else ErrorCode.VALIDATION_ERROR, str(e), status=status_code)
    except Exception:
        logger.exception("Team creation failed")
        return api_error(ErrorCode.INTERNAL_ERROR, "Team creation failed", status=500)


@bp.route("/<int:team_id>/members", methods=["GET"])
@require_role("viewer")
@rate_limit(tier="read")
def list_members(team_id):
    """List members of a team."""
    from auth.teams import get_team_members
    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return api_error(ErrorCode.NOT_FOUND, "Team not found in workspace", status=404)
    try:
        members = get_team_members(conn, team_id)
        return api_response({"members": members})
    except Exception:
        logger.exception("Failed to list team members")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to list members", status=500)


@bp.route("/<int:team_id>/members", methods=["POST"])
@require_role("admin")
@rate_limit(tier="write")
@validate_body(InviteMemberSchema)
def invite_member(team_id):
    """Add a member to a team."""
    from auth.teams import add_member
    body = g.body  # validated InviteMemberSchema

    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return api_error(ErrorCode.NOT_FOUND, "Team not found in workspace", status=404)
    try:
        add_member(conn, team_id=team_id, user_id=body.user_id, role=body.role)
        audit_log(conn, "team_member_added", {"team_id": team_id, "user_id": body.user_id, "role": body.role})
        return api_response({"message": "Member added"}, status=201)
    except AuthError as e:
        return api_error(ErrorCode.VALIDATION_ERROR, str(e), status=400)
    except Exception:
        logger.exception("Failed to invite team member")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to invite member", status=500)


@bp.route("/<int:team_id>/members/<int:user_id>", methods=["DELETE"])
@require_role("admin")
@rate_limit(tier="write")
def remove_team_member(team_id, user_id):
    """Remove a member from a team."""
    from auth.teams import remove_member
    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return api_error(ErrorCode.NOT_FOUND, "Team not found in workspace", status=404)
    try:
        remove_member(conn, team_id=team_id, user_id=user_id)
        audit_log(conn, "team_member_removed", {"team_id": team_id, "target_user_id": user_id})
        return api_response({"message": "Member removed"})
    except AuthError as e:
        code = 403 if e.code == "FORBIDDEN" else 404
        return api_error(ErrorCode.FORBIDDEN if e.code == "FORBIDDEN" else ErrorCode.NOT_FOUND, str(e), status=code)
    except Exception:
        logger.exception("Failed to remove team member")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to remove member", status=500)


# ---------------------------------------------------------------------------
# Invitation routes
# ---------------------------------------------------------------------------

@bp.route("/<int:team_id>/invitations", methods=["POST"])
@require_role("admin")
@rate_limit(tier="write")
def create_invitation(team_id):
    """Create a team invitation. Sends email to invitee."""
    from auth.invites import create_invite

    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return api_error(ErrorCode.NOT_FOUND, "Team not found in workspace", status=404)

    inviter_id = getattr(g, "current_user_id", None)
    if inviter_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    role = body.get("role", "member")

    if not email:
        return api_error(ErrorCode.VALIDATION_ERROR, "email is required", status=400)

    valid_roles = {"viewer", "member", "admin"}
    if role not in valid_roles:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"role must be one of: {', '.join(sorted(valid_roles))}",
            status=400,
        )

    try:
        token = create_invite(conn, team_id, inviter_id, email, role)
        audit_log(conn, "invitation_created", {"team_id": team_id, "email": email, "role": role})

        # Send invitation email
        try:
            from auth.email import send_team_invite_email

            # Get team name and inviter name for the email
            team_row = conn.execute(
                "SELECT t.name AS team_name, u.display_name AS inviter_name "
                "FROM teams t, users u "
                "WHERE t.id = %(tid)s AND u.id = %(uid)s",
                {"tid": team_id, "uid": inviter_id},
            ).fetchone()

            team_data = dict(team_row) if team_row and not isinstance(team_row, dict) else (team_row or {})
            send_team_invite_email(
                email,
                token,
                team_name=team_data.get("team_name", "a team"),
                inviter_name=team_data.get("inviter_name", "Someone"),
            )
        except Exception:
            logger.exception("Failed to send invitation email to %s", email)

        return api_response({"message": "Invitation sent", "email": email}, status=201)
    except Exception:
        logger.exception("Failed to create invitation")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to create invitation", status=500)


@bp.route("/<int:team_id>/invitations", methods=["GET"])
@require_role("admin")
@rate_limit(tier="read")
def list_invitations(team_id):
    """List pending invitations for a team."""
    from auth.invites import list_pending_invites

    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return api_error(ErrorCode.NOT_FOUND, "Team not found in workspace", status=404)

    invites = list_pending_invites(conn, team_id)
    return api_response({"invitations": invites})


@bp.route("/<int:team_id>/invitations/<int:invite_id>", methods=["DELETE"])
@require_role("admin")
@rate_limit(tier="write")
def cancel_invitation(team_id, invite_id):
    """Cancel a pending invitation."""
    from auth.invites import cancel_invite

    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return api_error(ErrorCode.NOT_FOUND, "Team not found in workspace", status=404)

    if cancel_invite(conn, invite_id, team_id):
        audit_log(conn, "invitation_cancelled", {"team_id": team_id, "invite_id": invite_id})
        return api_response({"message": "Invitation cancelled"})

    return api_error(ErrorCode.NOT_FOUND, "Invitation not found", status=404)


# ---------------------------------------------------------------------------
# Accept/decline — these are user-facing, not team-scoped
# ---------------------------------------------------------------------------

invitations_bp = Blueprint("invitations", __name__, url_prefix="/api/v1/invitations")


@invitations_bp.route("/accept", methods=["POST"])
@rate_limit(tier="write")
def accept_invitation():
    """Accept a team invitation using the token from the email."""
    from auth.invites import accept_invite

    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)

    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return api_error(ErrorCode.VALIDATION_ERROR, "token is required", status=400)

    from flask import current_app
    if not current_app.config.get("USE_PG"):
        return api_error(ErrorCode.INTERNAL_ERROR, "Requires PostgreSQL", status=500)
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()

    try:
        result = accept_invite(conn, token, user_id)
        audit_log(conn, "invitation_accepted", {"token_prefix": token[:8]})
        return api_response(result)
    except ValueError as e:
        return api_error(ErrorCode.VALIDATION_ERROR, str(e), status=400)


@invitations_bp.route("/decline", methods=["POST"])
@rate_limit(tier="write")
def decline_invitation():
    """Decline a team invitation."""
    from auth.invites import decline_invite

    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return api_error(ErrorCode.VALIDATION_ERROR, "token is required", status=400)

    from flask import current_app
    if not current_app.config.get("USE_PG"):
        return api_error(ErrorCode.INTERNAL_ERROR, "Requires PostgreSQL", status=500)
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()

    if decline_invite(conn, token):
        return api_response({"message": "Invitation declined"})

    return api_error(ErrorCode.NOT_FOUND, "Invitation not found", status=404)
