"""Admin users routes — search, detail, timeline, session invalidation.

Endpoints:
- GET  /admin/users — search/list users
- GET  /admin/users/:id — user detail
- GET  /admin/users/:id/timeline — activity timeline
- GET  /admin/users/:id/workspaces — workspace memberships
- POST /admin/users/:id/invalidate-sessions — revoke all sessions
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_users", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    """Convert a row dict, handling datetime serialization."""
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@bp.route("/users", methods=["GET"])
@require_superadmin
def list_users():
    """Search and list users. Supports email search, plan_tier filter, pagination."""
    conn = _get_conn()
    q = request.args.get("q")
    plan_tier = request.args.get("plan_tier")
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)
    cursor = request.args.get("cursor", type=int)

    conditions = ["deleted_at IS NULL"]
    params = {"limit": limit}

    if q:
        conditions.append("email ILIKE %(q)s")
        params["q"] = f"%{q}%"

    if plan_tier:
        conditions.append("plan_tier = %(plan_tier)s")
        params["plan_tier"] = plan_tier

    if cursor:
        conditions.append("id < %(cursor)s")
        params["cursor"] = cursor

    where = " AND ".join(conditions)

    rows = conn.execute(
        f"SELECT id, email, plan_tier, subscription_status, "
        f"created_at, last_login_at "
        f"FROM users WHERE {where} "
        f"ORDER BY id DESC LIMIT %(limit)s",
        params,
    ).fetchall()

    users = [_serialize_row(r) for r in rows]
    return api_response(users)


@bp.route("/users/<int:user_id>", methods=["GET"])
@require_superadmin
def get_user_detail(user_id: int):
    """Detailed user view: plan, subscription, usage, workspaces."""
    conn = _get_conn()

    row = conn.execute(
        "SELECT id, email, display_name, plan_tier, stripe_customer_id, "
        "stripe_subscription_id, subscription_status, "
        "is_superadmin, admin_role, totp_enabled, "
        "created_at, last_login_at, email_verified "
        "FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = _serialize_row(row)

    # Workspaces
    ws_rows = conn.execute(
        "SELECT w.id, w.name, wm.role "
        "FROM workspace_members wm "
        "JOIN workspaces w ON w.id = wm.workspace_id "
        "WHERE wm.user_id = %(uid)s",
        {"uid": user_id},
    ).fetchall()
    user["workspaces"] = [_serialize_row(w) for w in ws_rows]

    return api_response(user)


@bp.route("/users/<int:user_id>/timeline", methods=["GET"])
@require_superadmin
def get_user_timeline(user_id: int):
    """Aggregate activity timeline from multiple event sources."""
    conn = _get_conn()
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)

    events = []

    # Security events
    try:
        rows = conn.execute(
            "SELECT 'security' AS source, event_type, details_json, "
            "created_at FROM security_events "
            "WHERE user_id = %(uid)s "
            "ORDER BY created_at DESC LIMIT %(limit)s",
            {"uid": user_id, "limit": limit},
        ).fetchall()
        events.extend([_serialize_row(r) for r in rows])
    except Exception:
        logger.debug("Timeline: security events query failed", exc_info=True)

    # Ingestion jobs
    try:
        rows = conn.execute(
            "SELECT 'job' AS source, status AS event_type, "
            "file_name AS details_json, created_at "
            "FROM ingestion_jobs "
            "WHERE user_id = %(uid)s "
            "ORDER BY created_at DESC LIMIT %(limit)s",
            {"uid": user_id, "limit": limit},
        ).fetchall()
        events.extend([_serialize_row(r) for r in rows])
    except Exception:
        logger.debug("Timeline: jobs query failed", exc_info=True)

    # Sort by created_at descending, take top N
    events.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    events = events[:limit]

    return api_response(events)


@bp.route("/users/<int:user_id>/workspaces", methods=["GET"])
@require_superadmin
def get_user_workspaces(user_id: int):
    """List workspace memberships for a user."""
    conn = _get_conn()

    rows = conn.execute(
        "SELECT w.id, w.name, w.workspace_type, wm.role, wm.joined_at "
        "FROM workspace_members wm "
        "JOIN workspaces w ON w.id = wm.workspace_id "
        "WHERE wm.user_id = %(uid)s "
        "ORDER BY wm.joined_at",
        {"uid": user_id},
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/users/<int:user_id>/invalidate-sessions", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin")
def invalidate_sessions(user_id: int):
    """Revoke all refresh tokens for a user. Root admin only. Audited."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "Admin action")

    cur = conn.execute(
        "DELETE FROM refresh_tokens WHERE user_id = %(uid)s",
        {"uid": user_id},
    )
    revoked = cur.rowcount
    conn.commit()

    # Audit log
    try:
        from admin.audit import log_admin_action
        admin_id = getattr(request, "current_user_id", None)
        from flask import g
        admin_id = getattr(g, "current_user_id", admin_id)
        log_admin_action(
            conn, admin_user_id=admin_id, action="sessions_invalidated",
            target_type="user", target_id=str(user_id),
            reason=reason, details={"sessions_revoked": revoked},
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log session invalidation", exc_info=True)

    return api_response({"user_id": user_id, "sessions_revoked": revoked})
