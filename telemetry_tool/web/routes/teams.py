"""Team management API routes."""
import logging
from flask import Blueprint, g
from auth.rbac import require_role
from auth.service import AuthError

from web.api_utils import api_response, api_error, ErrorCode
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
        return api_response({"message": "Member removed"})
    except AuthError as e:
        code = 403 if e.code == "FORBIDDEN" else 404
        return api_error(ErrorCode.FORBIDDEN if e.code == "FORBIDDEN" else ErrorCode.NOT_FOUND, str(e), status=code)
    except Exception:
        logger.exception("Failed to remove team member")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to remove member", status=500)
