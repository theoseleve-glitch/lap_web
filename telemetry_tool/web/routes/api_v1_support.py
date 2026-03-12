"""V1 support API — ticket creation and listing.

Blueprint: ``/api/v1/support/`` — creates support tickets, sends notification
emails via Resend, and provides ticket listing.

Usage::

    from web.routes.api_v1_support import bp as api_v1_support_bp
    app.register_blueprint(api_v1_support_bp)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_support", __name__, url_prefix="/api/v1/support")

# ---- Rate limit import (graceful fallback) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        def decorator(fn):
            return fn
        return decorator


# ---- PG connection ----
def _get_pg_conn():
    """Get PostgreSQL connection. Tests patch this."""
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---- Valid issue types ----
_VALID_ISSUE_TYPES = {"bug", "feature_request", "billing", "account", "general"}


# ---------------------------------------------------------------------------
# POST /ticket — create a support ticket
# ---------------------------------------------------------------------------

@bp.route("/ticket", methods=["POST"])
@rate_limit(tier="upload")  # 10 per hour (tightest standard tier)
def create_ticket():
    """Create a support ticket.

    Stores in support_tickets table and sends notification email to support.

    Accepts:
        issue_type: str (bug|feature_request|billing|account|general)
        description: str (required, max 5000 chars)
        session_id: int (optional, relevant session)
        diagnostics: dict (optional, browser/OS info)
    """
    from sqlalchemy import text

    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.FORBIDDEN, "No workspace context", status=403)

    body = request.get_json(silent=True) or {}
    issue_type = body.get("issue_type", "general")
    description = (body.get("description") or "").strip()
    session_id = body.get("session_id")
    diagnostics = body.get("diagnostics")

    if not description:
        return api_error(ErrorCode.VALIDATION_ERROR, "description is required", status=400)

    if len(description) > 5000:
        return api_error(ErrorCode.VALIDATION_ERROR, "description too long (max 5000)", status=400)

    if issue_type not in _VALID_ISSUE_TYPES:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"issue_type must be one of: {', '.join(sorted(_VALID_ISSUE_TYPES))}",
            status=400,
        )

    conn = _get_pg_conn()

    # Get user info for the email
    user_row = conn.execute(
        text("SELECT email, display_name, plan_tier FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    user_data = dict(user_row) if user_row and not isinstance(user_row, dict) else (user_row or {})

    # Insert ticket
    diagnostics_json = json.dumps(diagnostics) if diagnostics else None
    row = conn.execute(
        text(
            "INSERT INTO support_tickets "
            "(user_id, workspace_id, issue_type, description, session_id, diagnostics, status) "
            "VALUES (:uid, :wsid, :type, :desc, :sid, :diag::jsonb, 'open') "
            "RETURNING id, created_at"
        ),
        {
            "uid": user_id,
            "wsid": workspace_id,
            "type": issue_type,
            "desc": description,
            "sid": session_id,
            "diag": diagnostics_json,
        },
    ).fetchone()

    ticket_data = dict(row) if not isinstance(row, dict) else row
    ticket_id = ticket_data["id"]
    conn.commit()

    # Send notification email to support
    try:
        from auth.email import _send
        email = user_data.get("email", "unknown")
        plan = user_data.get("plan_tier", "unknown")
        name = user_data.get("display_name", "User")

        from html import escape as _h
        subject = f"[LAP Support #{ticket_id}] {issue_type}: {description[:60]}"
        html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">New Support Ticket #{ticket_id}</h2>
  <table style="border-collapse: collapse; margin: 12px 0;">
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">User:</td>
      <td style="color: #F3F0E8;">{_h(str(name))} ({_h(str(email))})</td>
    </tr>
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">Plan:</td>
      <td style="color: #F3F0E8;">{_h(str(plan))}</td>
    </tr>
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">Type:</td>
      <td style="color: #F3F0E8;">{_h(str(issue_type))}</td>
    </tr>
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">Workspace:</td>
      <td style="color: #F3F0E8;">{_h(str(workspace_id))}</td>
    </tr>
  </table>
  <h3 style="color: #F3F0E8;">Description</h3>
  <p style="color: #8A8F98; white-space: pre-wrap;">{_h(str(description))}</p>
  {f'<h3 style="color: #F3F0E8;">Diagnostics</h3><pre style="color: #8A8F98; font-size: 12px;">{_h(json.dumps(diagnostics, indent=2))}</pre>' if diagnostics else ''}
</div>"""
        import os
        support_email = os.environ.get("SUPPORT_EMAIL", "support@lap-coach.racing")
        _send(support_email, subject, html)
    except Exception:
        logger.exception("Failed to send support notification email for ticket %s", ticket_id)

    logger.info("Support ticket created: id=%s, user=%s, type=%s", ticket_id, user_id, issue_type)

    return api_response({
        "ticket_id": ticket_id,
        "status": "open",
        "message": "Your support ticket has been submitted. We'll respond within 24 hours.",
    }, status=201)


# ---------------------------------------------------------------------------
# GET /tickets — list user's support tickets
# ---------------------------------------------------------------------------

@bp.route("/tickets", methods=["GET"])
@rate_limit(tier="read")
def list_tickets():
    """List the current user's support tickets."""
    from sqlalchemy import text

    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = _get_pg_conn()

    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except (ValueError, TypeError):
        limit = 20
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except (ValueError, TypeError):
        offset = 0

    rows = conn.execute(
        text(
            "SELECT id, issue_type, description, status, created_at "
            "FROM support_tickets WHERE user_id = :uid "
            "ORDER BY created_at DESC "
            "LIMIT :lim OFFSET :off"
        ),
        {"uid": user_id, "lim": limit, "off": offset},
    ).fetchall()

    tickets = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        tickets.append({
            "id": r["id"],
            "issue_type": r["issue_type"],
            "description": r["description"][:200],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })

    return api_response(tickets)
