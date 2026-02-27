"""Centralized audit logging helper for mutation routes.

Usage in route handlers::

    from web.middleware.audit import audit_log
    audit_log(conn, "team_created", {"team_id": 42, "name": "My Team"})
"""
import json
import logging

from flask import g, request

logger = logging.getLogger(__name__)


def audit_log(conn, action: str, details: dict | None = None):
    """Log an auditable action for the current request context.

    Pulls user_id from ``g.current_user_id``, IP from X-Forwarded-For
    (or remote_addr), User-Agent from request headers.
    """
    user_id = getattr(g, "current_user_id", None)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ua = request.headers.get("User-Agent", "")

    conn.execute(
        "INSERT INTO audit_log (user_id, action, details, ip_address, user_agent) "
        "VALUES (%(uid)s, %(action)s, %(details)s, %(ip)s, %(ua)s)",
        {
            "uid": user_id,
            "action": action,
            "details": json.dumps(details or {}),
            "ip": ip[:45] or None,
            "ua": ua[:500] or None,
        },
    )
