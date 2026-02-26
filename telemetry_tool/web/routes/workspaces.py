"""Workspace management API routes."""
import logging
from flask import Blueprint, request, jsonify, g
from auth.rbac import require_role

logger = logging.getLogger(__name__)

bp = Blueprint("workspaces", __name__, url_prefix="/api/v1/workspaces")


def _json_response(data=None, error=None, status=200):
    if error:
        return jsonify({"ok": False, "error": error, "meta": {}}), status
    return jsonify({"ok": True, "data": data, "meta": {}}), status


def _get_conn():
    from flask import current_app
    if not current_app.config.get("USE_PG"):
        raise RuntimeError("Workspace routes require PostgreSQL (USE_PG=1)")
    from web.db_pg import get_pg_connection
    return get_pg_connection()


@bp.route("", methods=["GET"])
def list_workspaces():
    """List all workspaces the current user can access."""
    from auth.workspace import get_user_workspaces
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return _json_response(error={"code": "UNAUTHORIZED", "message": "Auth required"}, status=401)

    conn = _get_conn()
    workspaces = get_user_workspaces(conn, user_id)
    return _json_response(data={"workspaces": workspaces})


@bp.route("/current", methods=["GET"])
def current_workspace():
    """Return the current workspace context."""
    ws_id = getattr(g, "workspace_id", None)
    ws_role = getattr(g, "workspace_role", None)
    return _json_response(data={
        "workspace_id": ws_id,
        "role": ws_role,
    })
