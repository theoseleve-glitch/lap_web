"""Team management API routes."""
import logging
import re
from flask import Blueprint, request, jsonify, g
from auth.rbac import require_role
from auth.service import AuthError

logger = logging.getLogger(__name__)

bp = Blueprint("teams", __name__, url_prefix="/api/v1/teams")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")

ALLOWED_INVITE_ROLES = {"viewer", "member", "admin"}


def _json_response(data=None, error=None, status=200):
    if error:
        return jsonify({"ok": False, "error": error, "meta": {}}), status
    return jsonify({"ok": True, "data": data, "meta": {}}), status


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
def create_team():
    """Create a new team. Requires authenticated user."""
    from auth.teams import create_team as svc_create_team
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return _json_response(error={"code": "UNAUTHORIZED", "message": "Auth required"}, status=401)

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    slug = (body.get("slug") or "").strip().lower()

    if not name or len(name) > 100:
        return _json_response(error={"code": "VALIDATION_ERROR", "message": "Team name required (max 100 characters)"}, status=400)
    if not slug or not _SLUG_RE.match(slug):
        return _json_response(
            error={"code": "VALIDATION_ERROR",
                   "message": "Slug must be 3-50 lowercase alphanumeric characters with hyphens"},
            status=400,
        )

    conn = _get_conn()
    try:
        result = svc_create_team(conn, owner_id=user_id, name=name, slug=slug)
        return _json_response(data=result, status=201)
    except AuthError as e:
        status_code = 409 if e.code == "CONFLICT" else 400
        return _json_response(error={"code": e.code, "message": str(e)}, status=status_code)
    except Exception:
        logger.exception("Team creation failed")
        return _json_response(error={"code": "INTERNAL_ERROR", "message": "Team creation failed"}, status=500)


@bp.route("/<int:team_id>/members", methods=["GET"])
@require_role("viewer")
def list_members(team_id):
    """List members of a team."""
    from auth.teams import get_team_members
    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return _json_response(
            error={"code": "NOT_FOUND", "message": "Team not found in workspace"},
            status=404,
        )
    try:
        members = get_team_members(conn, team_id)
        return _json_response(data={"members": members})
    except Exception:
        logger.exception("Failed to list team members")
        return _json_response(error={"code": "INTERNAL_ERROR", "message": "Failed to list members"}, status=500)


@bp.route("/<int:team_id>/members", methods=["POST"])
@require_role("admin")
def invite_member(team_id):
    """Add a member to a team."""
    from auth.teams import add_member
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    role = body.get("role", "member")

    if not user_id:
        return _json_response(error={"code": "VALIDATION_ERROR", "message": "user_id required"}, status=400)

    if role not in ALLOWED_INVITE_ROLES:
        return _json_response(
            error={"code": "VALIDATION_ERROR",
                   "message": f"Role must be one of: {', '.join(sorted(ALLOWED_INVITE_ROLES))}"},
            status=400,
        )

    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return _json_response(
            error={"code": "NOT_FOUND", "message": "Team not found in workspace"},
            status=404,
        )
    try:
        add_member(conn, team_id=team_id, user_id=user_id, role=role)
        return _json_response(data={"message": "Member added"}, status=201)
    except AuthError as e:
        return _json_response(error={"code": e.code, "message": str(e)}, status=400)
    except Exception:
        logger.exception("Failed to invite team member")
        return _json_response(error={"code": "INTERNAL_ERROR", "message": "Failed to invite member"}, status=500)


@bp.route("/<int:team_id>/members/<int:user_id>", methods=["DELETE"])
@require_role("admin")
def remove_team_member(team_id, user_id):
    """Remove a member from a team."""
    from auth.teams import remove_member
    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return _json_response(
            error={"code": "NOT_FOUND", "message": "Team not found in workspace"},
            status=404,
        )
    try:
        remove_member(conn, team_id=team_id, user_id=user_id)
        return _json_response(data={"message": "Member removed"})
    except AuthError as e:
        code = 403 if e.code == "FORBIDDEN" else 404
        return _json_response(error={"code": e.code, "message": str(e)}, status=code)
    except Exception:
        logger.exception("Failed to remove team member")
        return _json_response(error={"code": "INTERNAL_ERROR", "message": "Failed to remove member"}, status=500)
