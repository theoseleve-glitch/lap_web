"""Workspace management API routes."""
import logging
from flask import Blueprint, g
from auth.rbac import require_role

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("workspaces", __name__, url_prefix="/api/v1/workspaces")


def _get_conn():
    from flask import current_app
    if not current_app.config.get("USE_PG"):
        raise RuntimeError("Workspace routes require PostgreSQL (USE_PG=1)")
    from web.db_pg import get_pg_connection
    return get_pg_connection()


@bp.route("", methods=["GET"])
@rate_limit(tier="read")
def list_workspaces():
    """List all workspaces the current user can access."""
    from auth.workspace import get_user_workspaces
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)

    conn = _get_conn()
    try:
        workspaces = get_user_workspaces(conn, user_id)
        return api_response({"workspaces": workspaces})
    except Exception:
        logger.exception("Failed to list workspaces")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to list workspaces", status=500)


@bp.route("/current", methods=["GET"])
@rate_limit(tier="read")
def current_workspace():
    """Return the current workspace context."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)
    ws_id = getattr(g, "workspace_id", None)
    ws_role = getattr(g, "workspace_role", None)
    return api_response({
        "workspace_id": ws_id,
        "role": ws_role,
    })
