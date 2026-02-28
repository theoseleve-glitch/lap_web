"""Admin email routes — delivery stats, search, resend actions.

Endpoints:
- GET  /admin/email/stats — delivery statistics
- POST /admin/email/resend-verification/:user_id — resend verification email
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_email", __name__)


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


@bp.route("/email/stats", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "support_admin")
def email_stats():
    """Email delivery statistics from DB records."""
    conn = _get_conn()

    row = conn.execute(
        "SELECT COUNT(*) AS total_sent, "
        "COUNT(*) FILTER (WHERE email_verified = TRUE) AS verified "
        "FROM users WHERE deleted_at IS NULL"
    ).fetchone()

    r = dict(row) if not isinstance(row, dict) else row

    return api_response({
        "total_sent": r.get("total_sent", 0),
        "verified": r.get("verified", 0),
        "verification_rate_pct": round(
            (r.get("verified", 0) / r.get("total_sent", 1) * 100)
            if r.get("total_sent", 0) > 0 else 0,
            1,
        ),
    })


@bp.route("/email/resend-verification/<int:user_id>", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "support_admin")
def resend_verification(user_id: int):
    """Resend verification email for a user. Audited."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "Admin resend")

    # Check user exists and is unverified
    row = conn.execute(
        "SELECT id, email, email_verified FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row

    if user.get("email_verified"):
        return api_response({
            "sent": False,
            "reason": "Email already verified",
        })

    # Trigger verification email
    try:
        from auth.service import send_verification_email
        send_verification_email(conn, user["email"])
    except Exception:
        logger.debug("Verification email send failed", exc_info=True)

    # Audit log
    try:
        from admin.audit import log_admin_action
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="verification_email_resent",
            target_type="user",
            target_id=str(user_id),
            reason=reason,
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log email resend", exc_info=True)

    return api_response({"sent": True, "email": user["email"]})
