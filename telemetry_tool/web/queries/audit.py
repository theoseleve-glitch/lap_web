"""Audit logging query functions.

Provides a single entry point for recording audit events using
Flask request context (g.current_user_id, g.workspace_id, request.remote_addr).
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def log_audit_event(conn, action: str, details: dict | None = None) -> None:
    """Record an audit event using request context.

    Reads user_id, workspace_id from Flask g and ip_address/user_agent
    from the request. Safe to call outside request context (fields
    default to NULL).
    """
    user_id = None
    workspace_id = None
    ip_address = None
    user_agent = None

    try:
        from flask import g, request
        user_id = getattr(g, "current_user_id", None)
        workspace_id = getattr(g, "workspace_id", None)
        ip_address = request.remote_addr
        user_agent = request.headers.get("User-Agent", "")[:500]
    except (ImportError, RuntimeError):
        pass

    details_json = json.dumps(details) if details else None

    conn.execute(
        "INSERT INTO audit_log (user_id, workspace_id, action, new_value, ip_address, request_id) "
        "VALUES (:uid, :wid, :action, :details, :ip, :rid)",
        {
            "uid": user_id,
            "wid": workspace_id,
            "action": action,
            "details": details_json,
            "ip": ip_address,
            "rid": None,
        },
    )
