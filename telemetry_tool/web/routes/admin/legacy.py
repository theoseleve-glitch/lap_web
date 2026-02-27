"""Legacy admin endpoints — migrated from admin.py into the admin package.

Provides user management, audit log viewing, system metrics access,
impersonation, billing overview, and storage monitoring.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from web.middleware.audit import audit_log

logger = logging.getLogger(__name__)

legacy_bp = Blueprint("admin_legacy", __name__)
bp = legacy_bp  # backward compat alias


# ---------------------------------------------------------------------------
# Guard: require platform admin on all routes
# ---------------------------------------------------------------------------


def _get_conn():
    from flask import current_app
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    from web.db import get_db_connection
    return get_db_connection()


@bp.before_request
def require_platform_admin():
    """Block all non-admin requests."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT is_platform_admin FROM users WHERE id = %(uid)s",
            {"uid": user_id},
        ).fetchone()
        is_admin = False
        if row:
            r = dict(row) if not isinstance(row, dict) else row
            is_admin = r.get("is_platform_admin", False)
    except Exception:
        is_admin = False

    if not is_admin:
        return api_error(ErrorCode.FORBIDDEN, "Platform admin required", status=403)

    g.is_platform_admin = True


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@bp.route("/users", methods=["GET"])
def list_users():
    """Paginated user list with search and filters.

    Query params:
        search: email or display_name substring
        plan_tier: filter by plan tier
        status: filter by subscription_status
        limit: max results (default 50)
        offset: pagination offset
    """
    conn = _get_conn()
    search = request.args.get("search", "").strip()
    plan_tier = request.args.get("plan_tier", "").strip()
    status = request.args.get("status", "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if search:
        conditions.append(
            "(email ILIKE %(search)s OR display_name ILIKE %(search)s)"
        )
        params["search"] = f"%{search}%"

    if plan_tier:
        conditions.append("plan_tier = %(plan_tier)s")
        params["plan_tier"] = plan_tier

    if status:
        conditions.append("subscription_status = %(status)s")
        params["status"] = status

    where = " AND ".join(conditions)
    where_clause = f"WHERE {where}" if where else ""

    rows = conn.execute(
        f"SELECT id, email, display_name, plan_tier, subscription_status, "
        f"created_at, email_verified, suspended_at, is_platform_admin "
        f"FROM users {where_clause} "
        f"ORDER BY created_at DESC LIMIT %(limit)s OFFSET %(offset)s",
        params,
    ).fetchall()

    users = [dict(r) if not isinstance(r, dict) else r for r in rows]

    count_row = conn.execute(
        f"SELECT COUNT(*) AS total FROM users {where_clause}",
        params,
    ).fetchone()
    total = (dict(count_row) if count_row and not isinstance(count_row, dict) else (count_row or {})).get("total", 0)

    return api_response({
        "users": users,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@bp.route("/users/<int:user_id>", methods=["GET"])
def get_user_detail(user_id: int):
    """Full user detail: profile, plan, usage, sessions, recent audit."""
    conn = _get_conn()

    row = conn.execute(
        "SELECT id, email, display_name, plan_tier, subscription_status, "
        "stripe_customer_id, stripe_subscription_id, created_at, "
        "email_verified, suspended_at, is_platform_admin, "
        "default_workspace_id, grace_period_end "
        "FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row

    # Recent audit log entries
    audit_rows = conn.execute(
        "SELECT action, details, ip_address, created_at "
        "FROM audit_log WHERE user_id = %(uid)s "
        "ORDER BY created_at DESC LIMIT 20",
        {"uid": user_id},
    ).fetchall()
    user["recent_audit"] = [dict(r) if not isinstance(r, dict) else r for r in audit_rows]

    return api_response(user)


@bp.route("/users/<int:user_id>/suspend", methods=["POST"])
def suspend_user(user_id: int):
    """Suspend a user account. Requires reason in body."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "").strip()

    if not reason:
        return api_error(ErrorCode.VALIDATION_ERROR, "Reason is required", status=422)

    conn.execute(
        "UPDATE users SET suspended_at = NOW() WHERE id = %(uid)s AND suspended_at IS NULL",
        {"uid": user_id},
    )
    conn.commit()

    audit_log(conn, "admin_user_suspended", {
        "target_user_id": user_id,
        "reason": reason,
        "admin_user_id": getattr(g, "current_user_id", None),
    })
    conn.commit()

    return api_response({"suspended": True, "user_id": user_id})


@bp.route("/users/<int:user_id>/unsuspend", methods=["POST"])
def unsuspend_user(user_id: int):
    """Unsuspend a user account."""
    conn = _get_conn()

    conn.execute(
        "UPDATE users SET suspended_at = NULL WHERE id = %(uid)s",
        {"uid": user_id},
    )
    conn.commit()

    audit_log(conn, "admin_user_unsuspended", {
        "target_user_id": user_id,
        "admin_user_id": getattr(g, "current_user_id", None),
    })
    conn.commit()

    return api_response({"unsuspended": True, "user_id": user_id})


@bp.route("/users/<int:user_id>/override", methods=["POST"])
def create_override(user_id: int):
    """Create an entitlement override for a user (support credits, grandfathering)."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}

    feature = body.get("feature", "").strip()
    value = body.get("value")
    reason = body.get("reason", "").strip()
    expires_at = body.get("expires_at")

    if not feature or value is None:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "feature and value are required",
            status=422,
        )

    conn.execute(
        "INSERT INTO entitlement_overrides (user_id, feature, value, reason, expires_at) "
        "VALUES (%(uid)s, %(feature)s, %(value)s, %(reason)s, %(expires)s)",
        {
            "uid": user_id,
            "feature": feature,
            "value": str(value),
            "reason": reason or None,
            "expires": expires_at,
        },
    )
    conn.commit()

    audit_log(conn, "admin_entitlement_override", {
        "target_user_id": user_id,
        "feature": feature,
        "value": value,
        "reason": reason,
        "admin_user_id": getattr(g, "current_user_id", None),
    })
    conn.commit()

    return api_response({"override_created": True, "user_id": user_id, "feature": feature})


@bp.route("/users/<int:user_id>/impersonate", methods=["POST"])
def impersonate_user(user_id: int):
    """Generate a short-lived (15 min) access token for the target user.

    Fully audited — the admin's ID is recorded in the audit log.
    """
    conn = _get_conn()

    # Verify target user exists
    row = conn.execute(
        "SELECT id, email FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    target = dict(row) if not isinstance(row, dict) else row

    # Generate short-lived token
    import jwt
    import os
    secret = os.environ.get("TELEMETRY_JWT_SECRET", "")
    if not secret:
        return api_error(ErrorCode.INTERNAL_ERROR, "JWT secret not configured", status=500)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": target["email"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "impersonated_by": getattr(g, "current_user_id", None),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")

    audit_log(conn, "admin_impersonation", {
        "target_user_id": user_id,
        "target_email": target["email"],
        "admin_user_id": getattr(g, "current_user_id", None),
        "token_expires": (now + timedelta(minutes=15)).isoformat(),
    })
    conn.commit()

    return api_response({
        "access_token": token,
        "expires_in": 900,
        "target_user_id": user_id,
    })


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


@bp.route("/workspaces", methods=["GET"])
def list_workspaces():
    """List all workspaces with owner info."""
    conn = _get_conn()
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    rows = conn.execute(
        "SELECT w.id, w.name, w.slug, w.type, w.owner_user_id, "
        "u.email AS owner_email, w.created_at "
        "FROM workspaces w LEFT JOIN users u ON w.owner_user_id = u.id "
        "ORDER BY w.created_at DESC LIMIT %(limit)s OFFSET %(offset)s",
        {"limit": limit, "offset": offset},
    ).fetchall()

    return api_response({
        "workspaces": [dict(r) if not isinstance(r, dict) else r for r in rows],
    })


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------


@bp.route("/audit-log", methods=["GET"])
def list_audit_log():
    """Paginated audit log with filters.

    Query params:
        action: filter by action type
        user_id: filter by user
        start_date: ISO date start
        end_date: ISO date end
        limit, offset: pagination
    """
    conn = _get_conn()
    action_filter = request.args.get("action", "").strip()
    user_filter = request.args.get("user_id", "").strip()
    start = request.args.get("start_date", "").strip()
    end = request.args.get("end_date", "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if action_filter:
        conditions.append("action = %(action)s")
        params["action"] = action_filter

    if user_filter:
        conditions.append("user_id = %(uid)s")
        params["uid"] = int(user_filter)

    if start:
        conditions.append("created_at >= %(start)s")
        params["start"] = start

    if end:
        conditions.append("created_at <= %(end)s")
        params["end"] = end

    where = " AND ".join(conditions)
    where_clause = f"WHERE {where}" if where else ""

    rows = conn.execute(
        f"SELECT id, user_id, action, details, ip_address, user_agent, created_at "
        f"FROM audit_log {where_clause} "
        f"ORDER BY created_at DESC LIMIT %(limit)s OFFSET %(offset)s",
        params,
    ).fetchall()

    return api_response({
        "entries": [dict(r) if not isinstance(r, dict) else r for r in rows],
    })


# ---------------------------------------------------------------------------
# Billing overview
# ---------------------------------------------------------------------------


@bp.route("/billing/overview", methods=["GET"])
def billing_overview():
    """Aggregate billing metrics: plan distribution, MRR estimate."""
    conn = _get_conn()

    # Plan distribution
    dist_rows = conn.execute(
        "SELECT plan_tier, subscription_status, COUNT(*) AS cnt "
        "FROM users GROUP BY plan_tier, subscription_status "
        "ORDER BY cnt DESC"
    ).fetchall()
    distribution = [dict(r) if not isinstance(r, dict) else r for r in dist_rows]

    # Active subscribers
    active_row = conn.execute(
        "SELECT COUNT(*) AS active FROM users "
        "WHERE subscription_status IN ('active', 'trialing')"
    ).fetchone()
    active = (dict(active_row) if active_row and not isinstance(active_row, dict) else (active_row or {})).get("active", 0)

    return api_response({
        "plan_distribution": distribution,
        "active_subscribers": active,
    })


# ---------------------------------------------------------------------------
# Storage monitoring
# ---------------------------------------------------------------------------


@bp.route("/storage", methods=["GET"])
def storage_stats():
    """Database and disk storage statistics.

    Returns total DB size, per-table sizes, partition info for
    usage_events and audit_log, backup sizes, and disk space.
    """
    conn = _get_conn()
    result: dict = {}

    # Total database size
    row = conn.execute(
        "SELECT pg_database_size(current_database()) AS db_size"
    ).fetchone()
    if row:
        r = dict(row) if not isinstance(row, dict) else row
        result["database_size_mb"] = round((r["db_size"] or 0) / (1024 * 1024), 1)

    # Per-table sizes (top 10)
    rows = conn.execute(
        "SELECT relname AS table_name, "
        "pg_total_relation_size(c.oid) AS total_bytes "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' "
        "ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 10"
    ).fetchall()
    result["table_sizes"] = [
        {
            "table": (dict(r) if not isinstance(r, dict) else r)["table_name"],
            "size_mb": round((dict(r) if not isinstance(r, dict) else r)["total_bytes"] / (1024 * 1024), 2),
        }
        for r in rows
    ]

    # Partition sizes for usage_events and audit_log
    for parent_table in ("usage_events", "audit_log"):
        part_rows = conn.execute(
            "SELECT relname AS part_name, "
            "pg_total_relation_size(c.oid) AS total_bytes "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "AND relname LIKE %(pattern)s "
            "ORDER BY relname",
            {"pattern": f"{parent_table}_%"},
        ).fetchall()
        result[f"{parent_table}_partitions"] = [
            {
                "partition": (dict(r) if not isinstance(r, dict) else r)["part_name"],
                "size_mb": round((dict(r) if not isinstance(r, dict) else r)["total_bytes"] / (1024 * 1024), 2),
            }
            for r in part_rows
        ]

    # Backup size (scan backup directories)
    backup_info = _get_backup_info()
    if backup_info:
        result["backups"] = backup_info

    # Disk space remaining
    disk_info = _get_disk_info()
    if disk_info:
        result["disk"] = disk_info

    # Archive storage size
    archive_info = _get_archive_info()
    if archive_info:
        result["archives"] = archive_info

    return api_response(result)


def _get_backup_info() -> dict | None:
    """Scan backup directories for size info."""
    import os
    backup_base = os.environ.get("BACKUP_DIR", "/opt/lap-api/backups")
    if not os.path.isdir(backup_base):
        return None

    info: dict = {}
    for tier in ("daily", "weekly", "monthly"):
        tier_dir = os.path.join(backup_base, tier)
        if not os.path.isdir(tier_dir):
            info[tier] = {"count": 0, "total_mb": 0}
            continue
        files = [f for f in os.listdir(tier_dir) if os.path.isfile(os.path.join(tier_dir, f))]
        total = sum(os.path.getsize(os.path.join(tier_dir, f)) for f in files)
        info[tier] = {
            "count": len(files),
            "total_mb": round(total / (1024 * 1024), 1),
        }

    return info


def _get_disk_info() -> dict | None:
    """Return disk usage for the data partition."""
    import shutil
    import os
    data_path = os.environ.get("BACKUP_DIR", "/opt/lap-api/backups")
    try:
        usage = shutil.disk_usage(data_path)
        return {
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "used_gb": round(usage.used / (1024 ** 3), 1),
            "free_gb": round(usage.free / (1024 ** 3), 1),
            "used_percent": round(usage.used / usage.total * 100, 1),
        }
    except (OSError, FileNotFoundError):
        return None


def _get_archive_info() -> dict | None:
    """Scan Parquet archive directory for size info."""
    import os
    archive_base = os.environ.get("ARCHIVE_PATH", "/opt/lap-api/archives")
    if not os.path.isdir(archive_base):
        return None

    info: dict = {}
    for subdir in ("usage", "audit"):
        archive_dir = os.path.join(archive_base, subdir)
        if not os.path.isdir(archive_dir):
            info[subdir] = {"count": 0, "total_mb": 0}
            continue
        files = [f for f in os.listdir(archive_dir)
                 if f.endswith(".parquet") and os.path.isfile(os.path.join(archive_dir, f))]
        total = sum(os.path.getsize(os.path.join(archive_dir, f)) for f in files)
        info[subdir] = {
            "count": len(files),
            "total_mb": round(total / (1024 * 1024), 1),
        }

    return info
