"""Tenant middleware — resolves workspace_id and sets RLS context."""
from flask import request, g, current_app, jsonify

from auth.workspace import get_default_workspace_id


def tenant_middleware():
    """Before-request hook: resolve workspace and set RLS context.

    When AUTH_REQUIRED is False (legacy mode), uses DEFAULT_WORKSPACE_ID
    for all requests.  Otherwise resolves from X-Workspace-Id header or
    user's default workspace.
    """
    if not current_app.config.get("USE_PG"):
        return  # SQLite mode — no tenancy

    # Only apply to API routes
    if not request.path.startswith("/api/v1/"):
        return

    # Legacy mode: use system default workspace
    if not current_app.config.get("AUTH_REQUIRED"):
        g.workspace_id = current_app.config.get("DEFAULT_WORKSPACE_ID", 1)
        _set_rls_context(g.workspace_id)
        return

    # Auth mode: resolve workspace for authenticated user
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return  # Auth middleware will handle the 401

    # Check for explicit workspace header
    ws_header = request.headers.get("X-Workspace-Id")
    if ws_header:
        try:
            workspace_id = int(ws_header)
        except (ValueError, TypeError):
            return jsonify({
                "ok": False,
                "error": {"code": "VALIDATION_ERROR",
                          "message": "Invalid X-Workspace-Id header"},
                "meta": {},
            }), 400

        if not _verify_workspace_access(user_id, workspace_id):
            return jsonify({
                "ok": False,
                "error": {"code": "FORBIDDEN",
                          "message": "No access to this workspace"},
                "meta": {},
            }), 403

        g.workspace_id = workspace_id
    else:
        # Fall back to user's default workspace
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()
        default_ws = get_default_workspace_id(conn, user_id)
        if default_ws is None:
            return jsonify({
                "ok": False,
                "error": {"code": "NOT_FOUND",
                          "message": "No default workspace. Create one first."},
                "meta": {},
            }), 404
        g.workspace_id = default_ws

    _set_rls_context(g.workspace_id)


def _verify_workspace_access(user_id: int, workspace_id: int) -> bool:
    """Check if user has access to the given workspace."""
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT 1 FROM workspaces w "
        "LEFT JOIN team_members tm ON w.owner_team_id = tm.team_id "
        "WHERE w.id = %(ws)s AND (w.owner_user_id = %(uid)s OR tm.user_id = %(uid)s) "
        "LIMIT 1",
        {"ws": workspace_id, "uid": user_id},
    )
    return cur.fetchone() is not None


def _set_rls_context(workspace_id: int) -> None:
    """Set the PostgreSQL session variable for RLS filtering."""
    from web.db_pg import get_pg_connection
    from auth.workspace import set_workspace_context
    conn = get_pg_connection()
    set_workspace_context(conn, workspace_id)
