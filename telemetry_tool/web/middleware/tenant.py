"""Tenant middleware — resolves workspace_id and sets RLS context.

Single-user model: every authenticated user owns their personal workspace.
No X-Workspace-Id header, no team membership validation.
"""
from __future__ import annotations

import logging

from flask import current_app, g, request
from flask.wrappers import Response

logger = logging.getLogger(__name__)

# Kept in sync with web.middleware.auth._AUTH_ENFORCED_PREFIXES -- any path
# that requires a JWT must also get workspace_id resolved + RLS context set,
# otherwise handlers either crash on an unset g.workspace_id or (worse) fall
# back to an unscoped query. /api/ingest/ was missing here, which is how the
# ingestion_jobs cross-tenant IDOR was possible (see migration 083).
_TENANT_ENFORCED_PREFIXES = ("/api/v1/", "/api/ingest/")


def tenant_middleware() -> Response | tuple | None:
    """Before-request hook: resolve workspace and set RLS context.

    When AUTH_REQUIRED is False (legacy mode), uses DEFAULT_WORKSPACE_ID
    for all requests.  Otherwise auto-resolves from the authenticated user's
    personal workspace — no X-Workspace-Id header needed.
    """
    if not current_app.config.get("USE_PG"):
        return None  # SQLite mode — no tenancy

    # Only apply to API routes
    if not request.path.startswith(_TENANT_ENFORCED_PREFIXES):
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

    if not ws_id:
        # Cannot resolve or auto-create a workspace. Returning a safe error
        # is preferable to setting a bogus string like "default" — downstream
        # code calls ``int(g.workspace_id)`` (see data_v2.refresh_rollups)
        # and leaves RLS session state unset, which would either 500 or leak
        # data across tenants.
        logger.error(
            "Cannot resolve workspace_id for user %s — refusing request", user_id
        )
        from web.api_utils import ErrorCode, api_error
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Workspace unavailable. Please try again.",
            status=503,
        )

    set_workspace_context(conn, ws_id)
    g.workspace_id = ws_id
    g.workspace_role = "owner"

    # Resolve plan tier (used by rate limiter and feature gating)
    try:
        from auth.entitlements import get_user_plan_tier
        g.plan_tier = get_user_plan_tier(conn, user_id)
    except Exception as exc:
        logger.warning(
            "Failed to resolve plan_tier for user %s: %s: %s",
            user_id, type(exc).__name__, exc,
        )
        g.plan_tier = "locked"

    return None


def _set_rls_context(workspace_id: int) -> None:
    """Set the PostgreSQL session variable for RLS filtering."""
    from auth.workspace import set_workspace_context
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()
    set_workspace_context(conn, workspace_id)
