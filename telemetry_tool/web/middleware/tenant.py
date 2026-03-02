"""Tenant middleware — resolves workspace_id and sets RLS context."""
import logging

from flask import request, g, current_app, jsonify

from auth.workspace import get_default_workspace_id

logger = logging.getLogger(__name__)


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
        g.workspace_role = "owner"
        _set_rls_context(g.workspace_id)
        return

    # Auth mode: resolve workspace for authenticated user
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return  # Auth middleware will handle the 401

    # Check for explicit workspace header
    from web.api_utils import api_error, ErrorCode
    ws_header = request.headers.get("X-Workspace-Id")
    if ws_header:
        try:
            workspace_id = int(ws_header)
        except (ValueError, TypeError):
            return api_error(ErrorCode.VALIDATION_ERROR,
                             "Invalid X-Workspace-Id header", status=400)

        if not _verify_workspace_access(user_id, workspace_id):
            return api_error(ErrorCode.FORBIDDEN,
                             "No access to this workspace", status=403)

        g.workspace_id = workspace_id
    else:
        # Fall back to user's default workspace
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()
        default_ws = get_default_workspace_id(conn, user_id)
        if default_ws is None:
            return api_error(ErrorCode.NOT_FOUND,
                             "No default workspace. Create one first.",
                             status=404)
        g.workspace_id = default_ws

    _set_rls_context(g.workspace_id)

    # Resolve workspace role
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()
    g.workspace_role = _resolve_workspace_role(conn, user_id, g.workspace_id)
    if g.workspace_role is None:
        return api_error(ErrorCode.FORBIDDEN,
                         "No role in this workspace", status=403)

    # Resolve plan tier (used by rate limiter and feature gating)
    try:
        from auth.entitlements import get_user_plan_tier
        g.plan_tier = get_user_plan_tier(conn, user_id)
    except Exception as exc:
        logger.warning(
            "Failed to resolve plan_tier for user %s: %s: %s",
            user_id, type(exc).__name__, exc,
        )
        g.plan_tier = "demo"


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


def _resolve_workspace_role(conn, user_id: int, workspace_id: int) -> str | None:
    """Determine the user's role in a workspace.

    Personal workspace owner -> 'owner'.
    Team workspace -> look up role in team_members.
    """
    cur = conn.execute(
        "SELECT type, owner_user_id, owner_team_id FROM workspaces WHERE id = %(ws)s",
        {"ws": workspace_id},
    )
    ws = cur.fetchone()
    if ws is None:
        return None

    if ws["type"] == "personal":
        return "owner" if ws["owner_user_id"] == user_id else None

    # Team workspace — look up team membership
    cur = conn.execute(
        "SELECT role FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": ws["owner_team_id"], "uid": user_id},
    )
    row = cur.fetchone()
    return row["role"] if row else None
