"""Centralized audit logging helper for mutation routes.

Usage in route handlers::

    from web.middleware.audit import audit_log
    audit_log(conn, "team_created", {"team_id": 42, "name": "My Team"})
"""
import json
import logging

from flask import g, has_request_context, request

logger = logging.getLogger(__name__)


def audit_log(conn, action: str, details: dict | None = None):
    """Log an auditable action for the current request context.

    Pulls user_id from ``g.current_user_id``, IP from request.remote_addr
    (already corrected by ProxyFix), User-Agent from request headers.  Gracefully
    handles missing request context (e.g. Celery tasks, direct calls).
    """
    if has_request_context():
        user_id = getattr(g, "current_user_id", None)
        workspace_id = getattr(g, "workspace_id", None)
        ip = request.remote_addr or ""
        request_id = request.headers.get("X-Request-Id", "")
    else:
        user_id = None
        workspace_id = None
        ip = ""
        request_id = ""

    try:
        conn.execute(
            "INSERT INTO audit_log "
            "(workspace_id, user_id, action, new_value, ip_address, request_id) "
            "VALUES (:wsid, :uid, :action, :details, :ip, :rid)",
            {
                "wsid": workspace_id,
                "uid": user_id,
                "action": action,
                "details": json.dumps(details or {}),
                "ip": ip[:45] or None,
                "rid": request_id[:255] or None,
            },
        )
    except Exception:
        logger.debug("audit_log skipped (table may not exist): %s", action)
