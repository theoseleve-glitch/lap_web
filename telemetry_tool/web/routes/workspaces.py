"""Workspace management API routes.

Single-user model: every user has exactly one personal workspace resolved
server-side.  The list endpoint returns only that workspace; the current
endpoint reflects what the tenant middleware already resolved.
"""
import logging

from flask import Blueprint, g

from web.api_utils import ErrorCode, api_error, api_response
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("workspaces", __name__, url_prefix="/api/v1/workspaces")


@bp.route("", methods=["GET"])
@rate_limit(tier="read")
def list_workspaces():
    """Return the user's single personal workspace."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)

    ws_id = getattr(g, "workspace_id", None)
    workspaces = [{"workspace_id": ws_id, "role": "owner"}] if ws_id else []
    return api_response({"workspaces": workspaces})


@bp.route("/current", methods=["GET"])
@rate_limit(tier="read")
def current_workspace():
    """Return the current workspace context."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)
    ws_id = getattr(g, "workspace_id", None)
    ws_role = getattr(g, "workspace_role", "owner")
    return api_response({
        "workspace_id": ws_id,
        "role": ws_role,
    })
