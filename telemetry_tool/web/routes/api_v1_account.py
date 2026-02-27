"""V1 account API endpoints — GDPR data export, deletion, and profile.

Blueprint: ``/api/v1/account/`` — provides endpoints for GDPR compliance
including data export (right of access/portability), account deletion
(right of erasure), and profile rectification.

Usage::

    from web.routes.api_v1_account import bp as api_v1_account_bp
    app.register_blueprint(api_v1_account_bp)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request, send_file

from web.api_utils import ErrorCode, api_error, api_response
from web.middleware.entitlements import (
    entitlement_snapshot,
    require_api_access,
    require_feature,
    require_report_quota,
)

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_account", __name__, url_prefix="/api/v1/account")


# ---- Rate limit import (graceful fallback) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        def decorator(fn):
            return fn
        return decorator


# ---- Idempotency import (graceful fallback) ----
try:
    from web.idempotency import idempotent
except ImportError:
    def idempotent(fn):
        return fn


# ---- PG connection ----
def get_pg_connection():
    """Get PostgreSQL connection. Tests patch this."""
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---- Celery task import (graceful fallback) ----
try:
    from tasks.gdpr_tasks import export_user_data
except ImportError:
    export_user_data = None


# ---------------------------------------------------------------------------
# POST /export — create data export request
# ---------------------------------------------------------------------------

@bp.route("/export", methods=["POST"])
@rate_limit(tier="write")
@idempotent
@require_api_access
@require_feature("exports")
@require_report_quota
def create_export():
    """Create a data export request and dispatch Celery task.

    Returns:
        202 with ``{"export_id": "..."}``
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    # Create data_exports row
    cursor = conn.execute(
        text(
            "INSERT INTO data_exports (user_id, status, format, created_at) "
            "VALUES (:uid, 'pending', 'zip', now()) RETURNING id"
        ),
        {"uid": user_id},
    )
    row = cursor.fetchone()
    export_id = row["id"] if isinstance(row, dict) else dict(row)["id"]
    conn.commit()

    # Dispatch Celery task
    if export_user_data is not None and hasattr(export_user_data, "delay"):
        export_user_data.delay(user_id=user_id, export_id=str(export_id))

    return api_response({"export_id": str(export_id)}, status=202)


@bp.route("/entitlements", methods=["GET"])
@rate_limit(tier="read")
def get_entitlements():
    """Return effective entitlement snapshot for frontend feature gating."""
    return api_response(entitlement_snapshot())


# ---------------------------------------------------------------------------
# GET /export/<id>/status — check export status
# ---------------------------------------------------------------------------

@bp.route("/export/<export_id>/status", methods=["GET"])
@rate_limit(tier="read")
def export_status(export_id: str):
    """Get current status of a data export.

    Returns:
        200 with export status data.
        404 if export not found.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    row = conn.execute(
        text(
            "SELECT id, status, created_at, completed_at "
            "FROM data_exports WHERE id = :eid AND user_id = :uid"
        ),
        {"eid": export_id, "uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Export not found", status=404)

    return api_response(dict(row) if not isinstance(row, dict) else row)


# ---------------------------------------------------------------------------
# GET /export/<id>/download — download export file
# ---------------------------------------------------------------------------

@bp.route("/export/<export_id>/download", methods=["GET"])
@rate_limit(tier="read")
def export_download(export_id: str):
    """Download the exported ZIP file.

    Returns:
        200 with file download if completed.
        404 if export not completed or not found.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    row = conn.execute(
        text(
            "SELECT id, status, file_path "
            "FROM data_exports WHERE id = :eid AND user_id = :uid"
        ),
        {"eid": export_id, "uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Export not found", status=404)

    data = dict(row) if not isinstance(row, dict) else row

    if data["status"] != "completed" or not data.get("file_path"):
        return api_error(ErrorCode.NOT_FOUND, "Export not yet completed", status=404)

    return send_file(
        data["file_path"],
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"data_export_{export_id}.zip",
    )


# ---------------------------------------------------------------------------
# DELETE / — soft-delete account
# ---------------------------------------------------------------------------

@bp.route("/", methods=["DELETE"])
@rate_limit(tier="write")
@idempotent
def delete_account():
    """Soft-delete the authenticated user's account.

    Sets ``deleted_at`` on the user row and revokes tokens. Account is
    hard-purged after 30 days by the ``purge_deleted_accounts`` Celery task.

    Returns:
        200 with ``{"deleted": true}``
        409 if account is already deleted.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    user = conn.execute(
        text("SELECT id, deleted_at FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    data = dict(user) if not isinstance(user, dict) else user

    if data.get("deleted_at") is not None:
        return api_error(ErrorCode.CONFLICT, "Account is already scheduled for deletion", status=409)

    # Set deleted_at
    conn.execute(
        text("UPDATE users SET deleted_at = now() WHERE id = :uid"),
        {"uid": user_id},
    )

    # Revoke all refresh tokens
    conn.execute(
        text("DELETE FROM refresh_tokens WHERE user_id = :uid"),
        {"uid": user_id},
    )
    conn.commit()

    logger.info("Account soft-deleted: user_id=%s", user_id)
    return api_response({"deleted": True})


# ---------------------------------------------------------------------------
# POST /cancel-deletion — cancel pending deletion
# ---------------------------------------------------------------------------

@bp.route("/cancel-deletion", methods=["POST"])
@rate_limit(tier="write")
def cancel_deletion():
    """Cancel a pending account deletion (within 30-day grace period).

    Clears ``deleted_at`` on the user row.

    Returns:
        200 with ``{"restored": true}``
        409 if account is not in deleted state.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    user = conn.execute(
        text("SELECT id, deleted_at FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    data = dict(user) if not isinstance(user, dict) else user

    if data.get("deleted_at") is None:
        return api_error(ErrorCode.CONFLICT, "Account is not in deleted state", status=409)

    # Clear deleted_at
    conn.execute(
        text("UPDATE users SET deleted_at = NULL WHERE id = :uid"),
        {"uid": user_id},
    )
    conn.commit()

    logger.info("Account deletion cancelled: user_id=%s", user_id)
    return api_response({"restored": True})


# ---------------------------------------------------------------------------
# PATCH /profile — update display_name and/or email
# ---------------------------------------------------------------------------

@bp.route("/profile", methods=["PATCH"])
@rate_limit(tier="write")
def update_profile():
    """Update the user's display_name and/or email.

    Email changes set ``email_verified = False`` and trigger re-verification.

    Returns:
        200 with updated profile data.
        400 if body is empty or invalid.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    body = request.get_json(silent=True) or {}
    display_name = body.get("display_name")
    email = body.get("email")

    if not display_name and not email:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "At least one of display_name or email is required",
            status=400,
        )

    user = conn.execute(
        text("SELECT id, display_name, email FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    current = dict(user) if not isinstance(user, dict) else user
    email_verification_required = False

    set_clauses = []
    params = {"uid": user_id}

    if display_name:
        set_clauses.append("display_name = :display_name")
        params["display_name"] = display_name

    if email and email != current.get("email"):
        set_clauses.append("email = :email")
        set_clauses.append("email_verified = false")
        params["email"] = email
        email_verification_required = True

    if set_clauses:
        sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = :uid"
        conn.execute(text(sql), params)
        conn.commit()

    result = {
        "display_name": display_name or current.get("display_name"),
        "email": email or current.get("email"),
    }
    if email_verification_required:
        result["email_verification_required"] = True

    return api_response(result)
