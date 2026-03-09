"""Admin security routes — events, audit log, auth failures, incidents.

Endpoints:
- GET  /admin/security/events — security events with filters
- GET  /admin/security/audit-log — admin audit log
- GET  /admin/security/auth-failures — auth failure aggregation
- POST /admin/incidents — create incident note
- PATCH /admin/incidents/:id — update incident
- GET  /admin/incidents — list incidents
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response

from .middleware import require_admin_role, require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_security", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@bp.route("/security/events", methods=["GET"])
@require_superadmin
def list_security_events():
    """Query security_events with filters."""
    conn = _get_conn()
    event_type = request.args.get("type")
    severity = request.args.get("severity")
    ip = request.args.get("ip")
    user_id = request.args.get("user_id", type=int)
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)

    conditions = []
    params = {"limit": limit}

    if event_type:
        conditions.append("event_type = %(event_type)s")
        params["event_type"] = event_type

    if severity:
        conditions.append("severity = %(severity)s")
        params["severity"] = severity

    if ip:
        conditions.append("ip_address = %(ip)s")
        params["ip"] = ip

    if user_id:
        conditions.append("user_id = %(user_id)s")
        params["user_id"] = user_id

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = conn.execute(
        f"SELECT id, event_type, user_id, ip_address, severity, "
        f"details_json, created_at "
        f"FROM security_events {where} "
        f"ORDER BY created_at DESC LIMIT %(limit)s",
        params,
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/security/audit-log", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "auditor")
def list_audit_log():
    """Query admin_audit_log. Immutable, append-only."""
    conn = _get_conn()
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)
    action = request.args.get("action")

    conditions = []
    params = {"limit": limit}

    if action:
        conditions.append("action = %(action)s")
        params["action"] = action

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = conn.execute(
        f"SELECT id, admin_user_id, action, target_type, target_id, "
        f"reason, details_json, ip_address, created_at "
        f"FROM admin_audit_log {where} "
        f"ORDER BY created_at DESC LIMIT %(limit)s",
        params,
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/security/auth-failures", methods=["GET"])
@require_superadmin
def auth_failures():
    """Auth failure aggregation: top IPs, top users, trends."""
    conn = _get_conn()

    # Top IPs with most failures in last 24h
    ip_rows = conn.execute(
        "SELECT ip_address, COUNT(*) AS cnt "
        "FROM security_events "
        "WHERE event_type = 'login_failed' "
        "AND created_at > NOW() - INTERVAL '24 hours' "
        "GROUP BY ip_address ORDER BY cnt DESC LIMIT 10"
    ).fetchall()

    # Top users with most failures
    user_rows = conn.execute(
        "SELECT user_id, COUNT(*) AS cnt "
        "FROM security_events "
        "WHERE event_type = 'login_failed' "
        "AND user_id IS NOT NULL "
        "AND created_at > NOW() - INTERVAL '24 hours' "
        "GROUP BY user_id ORDER BY cnt DESC LIMIT 10"
    ).fetchall()

    return api_response({
        "top_ips": [_serialize_row(r) for r in ip_rows],
        "top_users": [_serialize_row(r) for r in user_rows],
    })


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


@bp.route("/incidents", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def create_incident():
    """Create an incident note."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}

    title = body.get("title")
    if not title:
        return api_error(ErrorCode.VALIDATION_ERROR, "title is required", status=400)

    cur = conn.execute(
        "INSERT INTO incident_notes (admin_user_id, title, body, severity, status) "
        "VALUES (%(admin)s, %(title)s, %(body)s, %(severity)s, 'open') "
        "RETURNING id",
        {
            "admin": getattr(g, "current_user_id", 0),
            "title": title,
            "body": body.get("body"),
            "severity": body.get("severity", "p3"),
        },
    )
    row = cur.fetchone()
    r = dict(row) if not isinstance(row, dict) else row
    conn.commit()

    return api_response({"incident_id": r["id"]})


@bp.route("/incidents/<int:incident_id>", methods=["PATCH"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def update_incident(incident_id: int):
    """Update incident status or body."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}

    updates = []
    params = {"iid": incident_id}

    if "status" in body:
        updates.append("status = %(status)s")
        params["status"] = body["status"]

    if "body" in body:
        updates.append("body = %(body)s")
        params["body"] = body["body"]

    if "severity" in body:
        updates.append("severity = %(severity)s")
        params["severity"] = body["severity"]

    if body.get("status") == "resolved":
        updates.append("resolved_at = NOW()")

    updates.append("updated_at = NOW()")

    if not updates:
        return api_error(ErrorCode.VALIDATION_ERROR, "No fields to update", status=400)

    set_clause = ", ".join(updates)
    conn.execute(
        f"UPDATE incident_notes SET {set_clause} WHERE id = %(iid)s",
        params,
    )
    conn.commit()

    return api_response({"incident_id": incident_id, "updated": True})


@bp.route("/incidents", methods=["GET"])
@require_superadmin
def list_incidents():
    """List incident notes with filters."""
    conn = _get_conn()
    status = request.args.get("status")
    severity = request.args.get("severity")
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)

    conditions = []
    params = {"limit": limit}

    if status:
        conditions.append("status = %(status)s")
        params["status"] = status

    if severity:
        conditions.append("severity = %(severity)s")
        params["severity"] = severity

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = conn.execute(
        f"SELECT id, admin_user_id, title, severity, status, "
        f"created_at, resolved_at "
        f"FROM incident_notes {where} "
        f"ORDER BY created_at DESC LIMIT %(limit)s",
        params,
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])
