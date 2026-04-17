"""Tenant middleware — resolves workspace_id and sets RLS context.

Single-user model: every authenticated user owns their personal workspace.
No X-Workspace-Id header, no team membership validation.
"""
from __future__ import annotations

import logging

from flask import current_app, g, request
from flask.wrappers import Response

logger = logging.getLogger(__name__)


def tenant_middleware() -> Response | tuple | None:
    """Before-request hook: resolve workspace and set RLS context.

    When AUTH_REQUIRED is False (legacy mode), uses DEFAULT_WORKSPACE_ID
    for all requests.  Otherwise auto-resolves from the authenticated user's
    personal workspace — no X-Workspace-Id header needed.
    """
    if not current_app.config.get("USE_PG"):
        return None  # SQLite mode — no tenancy

    # Only apply to API routes
    if not request.path.startswith("/api/v1/"):
        return None

    # Legacy mode: use system default workspace
    if not current_app.config.get("AUTH_REQUIRED"):
        g.workspace_id = current_app.config.get("DEFAULT_WORKSPACE_ID", 1)
        g.workspace_role = "owner"
        _set_rls_context(g.workspace_id)
        return None

    # Single-user model: every authenticated user owns their personal workspace.
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return None  # Auth middleware will handle the 401

    from auth.workspace import get_default_workspace_id, set_workspace_context
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()

    ws_id = get_default_workspace_id(conn, user_id)
    if not ws_id:
        # New user whose personal workspace hasn't been created yet (rare:
        # only possible if registration failed mid-way). Auto-create it now
        # so the request can proceed with correct RLS context.
        try:
            from auth.workspace import create_personal_workspace
            ws_id = create_personal_workspace(conn, user_id)
            conn.commit()
            logger.info("Auto-created personal workspace for user %s", user_id)
        except Exception:
            logger.warning("Failed to auto-create workspace for user %s", user_id, exc_info=True)

    if ws_id:
        set_workspace_context(conn, ws_id)
        g.workspace_id = ws_id
        g.workspace_role = "owner"
    else:
        # Last resort: set a safe default so downstream code doesn't crash.
        g.workspace_id = "default"
        g.workspace_role = "owner"

    # Resolve plan tier (used by rate limiter and feature gating)
    if ws_id:
        try:
            from auth.entitlements import get_user_plan_tier
            g.plan_tier = get_user_plan_tier(conn, user_id)
        except Exception as exc:
            logger.warning(
                "Failed to resolve plan_tier for user %s: %s: %s",
                user_id, type(exc).__name__, exc,
            )
            g.plan_tier = "demo"

    return None


def _set_rls_context(workspace_id: int) -> None:
    """Set the PostgreSQL session variable for RLS filtering."""
    from auth.workspace import set_workspace_context
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()
    set_workspace_context(conn, workspace_id)
