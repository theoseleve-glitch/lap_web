"""V1 account API endpoints — GDPR, profile, sessions, 2FA, preferences, OAuth, activity, data, support.

Blueprint: ``/api/v1/account/`` — provides endpoints for GDPR compliance,
profile management, session management, two-factor authentication,
user preferences, OAuth linking, login activity, data management,
and support tickets.

Usage::

    from web.routes.api_v1_account import bp as api_v1_account_bp
    app.register_blueprint(api_v1_account_bp)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta, date

from flask import Blueprint, g, request, send_file

from web.api_utils import ErrorCode, api_error, api_response
from web.middleware.entitlements import (
    entitlement_snapshot,
    require_api_access,
    require_feature,
    require_report_quota,
)

# Current terms version — bump when terms change
TERMS_VERSION = "2026-02-27-v1"

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

    user_id = getattr(g, "current_user_id", None)
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

    user_id = getattr(g, "current_user_id", None)
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

    user_id = getattr(g, "current_user_id", None)
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

    user_id = getattr(g, "current_user_id", None)
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

    user_id = getattr(g, "current_user_id", None)
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
    """Update the user's profile: display_name, email, avatar_url, preferences.

    Email changes set ``email_verified = False`` and trigger re-verification.
    Preferences are merged (not replaced) with existing JSONB preferences.

    Returns:
        200 with updated profile data.
        400 if body is empty or invalid.
    """
    from sqlalchemy import text

    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    body = request.get_json(silent=True) or {}
    display_name = body.get("display_name")
    email = body.get("email")
    avatar_url = body.get("avatar_url")
    preferences = body.get("preferences")

    if not display_name and not email and avatar_url is None and preferences is None:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "At least one of display_name, email, avatar_url, or preferences is required",
            status=400,
        )

    # Validate preferences if provided
    if preferences is not None:
        try:
            from web.schemas.account import UserPreferences
            UserPreferences(**preferences)
        except Exception as e:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                f"Invalid preferences: {e}",
                status=400,
            )

    user = conn.execute(
        text("SELECT id, display_name, email, avatar_url, preferences FROM users WHERE id = :uid"),
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

    if avatar_url is not None:
        set_clauses.append("avatar_url = :avatar_url")
        params["avatar_url"] = avatar_url if avatar_url else None

    if preferences is not None:
        # JSONB merge: existing || new (new keys overwrite, existing preserved)
        set_clauses.append("preferences = COALESCE(preferences, '{}'::jsonb) || :prefs::jsonb")
        params["prefs"] = json.dumps(preferences)

    if set_clauses:
        sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = :uid"
        conn.execute(text(sql), params)
        conn.commit()

    # Re-read to get merged preferences
    updated = conn.execute(
        text("SELECT display_name, email, avatar_url, preferences FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    updated_data = dict(updated) if not isinstance(updated, dict) else updated

    prefs = updated_data.get("preferences")
    if isinstance(prefs, str):
        prefs = json.loads(prefs)

    result = {
        "display_name": updated_data.get("display_name"),
        "email": updated_data.get("email"),
        "avatar_url": updated_data.get("avatar_url"),
        "preferences": prefs or {},
    }
    if email_verification_required:
        result["email_verification_required"] = True

    return api_response(result)


# ---------------------------------------------------------------------------
# POST /change-password — change password (authenticated)
# ---------------------------------------------------------------------------

_PASSWORD_MAX = 1024


@bp.route("/change-password", methods=["POST"])
@rate_limit(tier="write")
def change_password_route():
    """Change password for the current user.

    Requires current_password verification. Revokes all sessions except current.
    """
    from auth.service import change_password, hash_refresh_token, AuthError

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    body = request.get_json(silent=True) or {}
    current_password = body.get("current_password", "")
    new_password = body.get("new_password", "")

    if not current_password or not new_password:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "current_password and new_password required",
            status=400,
        )

    if len(new_password) > _PASSWORD_MAX:
        return api_error(ErrorCode.VALIDATION_ERROR, "Password too long", status=400)

    if len(new_password) < 8:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Password must be at least 8 characters",
            status=400,
        )

    # Identify current session's refresh token hash (to keep it alive)
    current_token_hash = None
    refresh_cookie = request.cookies.get("lap_refresh_token")
    if refresh_cookie:
        current_token_hash = hash_refresh_token(refresh_cookie)

    conn = get_pg_connection()
    try:
        change_password(
            conn, user_id, current_password, new_password,
            current_token_hash=current_token_hash,
        )
        return api_response({"message": "Password changed"})
    except AuthError as e:
        return api_error(ErrorCode.INVALID_CREDENTIALS, str(e), status=401)


# ---------------------------------------------------------------------------
# GET /sessions — list active sessions
# ---------------------------------------------------------------------------

@bp.route("/sessions", methods=["GET"])
@rate_limit(tier="read")
def list_sessions():
    """List active sessions (from refresh_tokens table)."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    rows = conn.execute(
        text(
            "SELECT id, user_agent, ip_address, created_at, last_used_at "
            "FROM refresh_tokens "
            "WHERE user_id = :uid AND revoked_at IS NULL AND expires_at > now() "
            "ORDER BY created_at DESC"
        ),
        {"uid": user_id},
    ).fetchall()

    # Identify current session
    from auth.service import hash_refresh_token
    current_hash = None
    refresh_cookie = request.cookies.get("lap_refresh_token")
    if refresh_cookie:
        current_hash = hash_refresh_token(refresh_cookie)

    sessions = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        s = {
            "id": r["id"],
            "user_agent": r.get("user_agent"),
            "ip_address": r.get("ip_address"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "last_used_at": r["last_used_at"].isoformat() if r.get("last_used_at") else None,
        }
        # Check if this is the current session
        if current_hash:
            cur = conn.execute(
                text("SELECT token_hash FROM refresh_tokens WHERE id = :id"),
                {"id": r["id"]},
            ).fetchone()
            if cur:
                stored_hash = dict(cur)["token_hash"] if not isinstance(cur, dict) else cur["token_hash"]
                s["is_current"] = (stored_hash == current_hash)
            else:
                s["is_current"] = False
        else:
            s["is_current"] = False
        sessions.append(s)

    return api_response(sessions)


# ---------------------------------------------------------------------------
# DELETE /sessions/<token_id> — revoke a specific session
# ---------------------------------------------------------------------------

@bp.route("/sessions/<int:token_id>", methods=["DELETE"])
@rate_limit(tier="write")
def revoke_session(token_id: int):
    """Revoke a specific session by its refresh token ID."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    result = conn.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = now() "
            "WHERE id = :tid AND user_id = :uid AND revoked_at IS NULL "
            "RETURNING id"
        ),
        {"tid": token_id, "uid": user_id},
    ).fetchone()

    if result is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    conn.commit()
    return api_response({"revoked": True})


# ---------------------------------------------------------------------------
# POST /sessions/revoke-all — revoke all sessions except current
# ---------------------------------------------------------------------------

@bp.route("/sessions/revoke-all", methods=["POST"])
@rate_limit(tier="write")
def revoke_all_sessions():
    """Revoke all sessions except the current one (logout everywhere)."""
    from sqlalchemy import text
    from auth.service import hash_refresh_token

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    # Identify current session to exclude
    refresh_cookie = request.cookies.get("lap_refresh_token")
    if refresh_cookie:
        current_hash = hash_refresh_token(refresh_cookie)
        conn.execute(
            text(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE user_id = :uid AND revoked_at IS NULL "
                "AND token_hash != :keep"
            ),
            {"uid": user_id, "keep": current_hash},
        )
    else:
        conn.execute(
            text(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        )

    conn.commit()
    return api_response({"message": "All other sessions revoked"})


# ---------------------------------------------------------------------------
# POST /2fa/setup — generate TOTP secret + QR URI
# ---------------------------------------------------------------------------

@bp.route("/2fa/setup", methods=["POST"])
@rate_limit(tier="write")
def setup_2fa():
    """Generate TOTP secret, QR URI and QR code image.

    Stores the secret on the user row but does NOT enable 2FA yet --
    the caller must confirm with a valid TOTP code via ``/2fa/confirm``.
    """
    from sqlalchemy import text
    from auth.totp import generate_totp_secret, generate_totp_uri, generate_qr_data_uri

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    # Check if already enabled
    row = conn.execute(
        text("SELECT email, totp_enabled FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    if user.get("totp_enabled"):
        return api_error(ErrorCode.CONFLICT, "2FA is already enabled", status=409)

    secret = generate_totp_secret()
    uri = generate_totp_uri(secret, user["email"])

    # Store secret temporarily (not enabled yet — will be enabled on confirm)
    conn.execute(
        text("UPDATE users SET totp_secret = :secret WHERE id = :uid"),
        {"secret": secret, "uid": user_id},
    )
    conn.commit()

    result = {
        "secret": secret,
        "provisioning_uri": uri,
    }

    # Generate QR code data URI (graceful — None when qrcode lib missing)
    qr = generate_qr_data_uri(uri)
    if qr is not None:
        result["qr_code"] = qr

    return api_response(result)


# ---------------------------------------------------------------------------
# POST /2fa/confirm — verify code to activate 2FA, return backup codes
# ---------------------------------------------------------------------------

@bp.route("/2fa/confirm", methods=["POST"])
@rate_limit(tier="auth")
def confirm_2fa():
    """Verify a TOTP code to activate 2FA.  Returns backup codes (shown once).

    The caller must have called ``/2fa/setup`` first to generate a secret.
    """
    from sqlalchemy import text
    from auth.totp import verify_totp, generate_backup_codes, hash_backup_code

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    body = request.get_json(silent=True) or {}
    code = (body.get("code") or body.get("totp_code") or "").strip()
    if not code:
        return api_error(ErrorCode.VALIDATION_ERROR, "code required", status=400)

    conn = get_pg_connection()

    row = conn.execute(
        text("SELECT email, totp_secret, totp_enabled FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    if user.get("totp_enabled"):
        return api_error(ErrorCode.CONFLICT, "2FA is already enabled", status=409)

    if not user.get("totp_secret"):
        return api_error(ErrorCode.VALIDATION_ERROR, "Call /2fa/setup first", status=400)

    if not verify_totp(user["totp_secret"], code):
        return api_error(ErrorCode.INVALID_CREDENTIALS, "Invalid TOTP code", status=401)

    # Generate backup codes
    backup_codes = generate_backup_codes()
    hashed_codes = [hash_backup_code(c) for c in backup_codes]

    # Enable 2FA + record verified timestamp
    conn.execute(
        text(
            "UPDATE users SET totp_enabled = true, totp_backup_codes = :codes, "
            "totp_verified_at = NOW() WHERE id = :uid"
        ),
        {"codes": json.dumps(hashed_codes), "uid": user_id},
    )
    conn.commit()

    from auth.service import _log_audit
    _log_audit(conn, user_id, "2fa_enabled", {})

    # Send security notification email (non-blocking)
    try:
        from auth.email import send_2fa_enabled_email
        send_2fa_enabled_email(user["email"])
    except Exception:
        logger.warning("Failed to send 2FA-enabled email", exc_info=True)

    return api_response({
        "enabled": True,
        "backup_codes": backup_codes,
    })


# ---------------------------------------------------------------------------
# POST /2fa/disable — disable 2FA (requires password + TOTP)
# ---------------------------------------------------------------------------

@bp.route("/2fa/disable", methods=["POST"])
@rate_limit(tier="auth")
def disable_2fa():
    """Disable 2FA.  Requires current password + valid TOTP *or* backup code."""
    from sqlalchemy import text
    from auth.service import verify_password, _log_audit
    from auth.totp import verify_totp, verify_backup_code

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    body = request.get_json(silent=True) or {}
    password = body.get("password", "")
    code = (body.get("code") or body.get("totp_code") or "").strip()

    if not password or not code:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "password and code required", status=400,
        )

    conn = get_pg_connection()

    row = conn.execute(
        text(
            "SELECT email, password_hash, totp_secret, totp_enabled, totp_backup_codes "
            "FROM users WHERE id = :uid"
        ),
        {"uid": user_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    if not user.get("totp_enabled"):
        return api_error(ErrorCode.CONFLICT, "2FA is not enabled", status=409)

    # Verify password
    if not user.get("password_hash") or not verify_password(password, user["password_hash"]):
        return api_error(ErrorCode.INVALID_CREDENTIALS, "Invalid password", status=401)

    # Verify TOTP code or backup code
    verified = False
    if len(code) == 6 and code.isdigit():
        verified = verify_totp(user["totp_secret"], code)
    if not verified:
        # Try as backup code
        hashed_codes = json.loads(user.get("totp_backup_codes") or "[]")
        idx = verify_backup_code(code, hashed_codes)
        if idx is not None:
            verified = True

    if not verified:
        return api_error(ErrorCode.INVALID_CREDENTIALS, "Invalid 2FA code", status=401)

    # Disable 2FA -- clear all TOTP columns
    conn.execute(
        text(
            "UPDATE users SET totp_enabled = false, totp_secret = NULL, "
            "totp_backup_codes = NULL, totp_verified_at = NULL WHERE id = :uid"
        ),
        {"uid": user_id},
    )
    conn.commit()

    _log_audit(conn, user_id, "2fa_disabled", {})

    # Send security notification email (non-blocking)
    try:
        from auth.email import send_2fa_disabled_email
        send_2fa_disabled_email(user["email"])
    except Exception:
        logger.warning("Failed to send 2FA-disabled email", exc_info=True)

    return api_response({"disabled": True})


# ---------------------------------------------------------------------------
# POST /2fa/backup-codes — regenerate backup codes (requires TOTP)
# ---------------------------------------------------------------------------

@bp.route("/2fa/backup-codes", methods=["POST"])
@rate_limit(tier="auth")
def regenerate_backup_codes():
    """Regenerate backup codes.  Requires password + valid TOTP code.

    Returns the new plaintext backup codes (shown once).
    """
    from sqlalchemy import text
    from auth.service import verify_password
    from auth.totp import verify_totp, generate_backup_codes, hash_backup_code

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    body = request.get_json(silent=True) or {}
    password = body.get("password", "")
    code = (body.get("code") or body.get("totp_code") or "").strip()

    if not password or not code:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "password and code required", status=400,
        )

    conn = get_pg_connection()

    row = conn.execute(
        text("SELECT password_hash, totp_secret, totp_enabled FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    if not user.get("totp_enabled"):
        return api_error(ErrorCode.CONFLICT, "2FA is not enabled", status=409)

    # Verify password
    if not user.get("password_hash") or not verify_password(password, user["password_hash"]):
        return api_error(ErrorCode.INVALID_CREDENTIALS, "Invalid password", status=401)

    # Verify TOTP
    if not verify_totp(user["totp_secret"], code):
        return api_error(ErrorCode.INVALID_CREDENTIALS, "Invalid TOTP code", status=401)

    backup_codes = generate_backup_codes()
    hashed_codes = [hash_backup_code(c) for c in backup_codes]

    conn.execute(
        text("UPDATE users SET totp_backup_codes = :codes WHERE id = :uid"),
        {"codes": json.dumps(hashed_codes), "uid": user_id},
    )
    conn.commit()

    return api_response({"backup_codes": backup_codes})


# ---------------------------------------------------------------------------
# GET/PATCH /preferences — user preferences
# ---------------------------------------------------------------------------

_VALID_PREFERENCE_KEYS = {
    "units", "speed_unit", "timezone", "language", "notifications",
}


@bp.route("/preferences", methods=["GET"])
@rate_limit(tier="read")
def get_preferences():
    """Return current user preferences."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    row = conn.execute(
        text("SELECT preferences FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    prefs = dict(row)["preferences"] if not isinstance(row, dict) else row["preferences"]
    if isinstance(prefs, str):
        prefs = json.loads(prefs)

    return api_response(prefs or {})


@bp.route("/preferences", methods=["PATCH"])
@rate_limit(tier="write")
def update_preferences():
    """Partial merge into user preferences JSONB column."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    body = request.get_json(silent=True) or {}
    if not body:
        return api_error(ErrorCode.VALIDATION_ERROR, "Request body required", status=400)

    # Validate keys
    unknown = set(body.keys()) - _VALID_PREFERENCE_KEYS
    if unknown:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown preference keys: {', '.join(sorted(unknown))}",
            status=400,
        )

    conn = get_pg_connection()

    # JSONB merge: existing || new (new keys overwrite, existing keys preserved)
    conn.execute(
        text(
            "UPDATE users SET preferences = COALESCE(preferences, '{}'::jsonb) || :patch::jsonb "
            "WHERE id = :uid"
        ),
        {"patch": json.dumps(body), "uid": user_id},
    )
    conn.commit()

    # Return merged preferences
    row = conn.execute(
        text("SELECT preferences FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    prefs = dict(row)["preferences"] if not isinstance(row, dict) else row["preferences"]
    if isinstance(prefs, str):
        prefs = json.loads(prefs)

    return api_response(prefs or {})


# ---------------------------------------------------------------------------
# GET /connections — list OAuth connections
# ---------------------------------------------------------------------------

@bp.route("/connections", methods=["GET"])
@rate_limit(tier="read")
def list_connections():
    """List linked OAuth providers."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    rows = conn.execute(
        text(
            "SELECT provider, provider_user_id, created_at "
            "FROM oauth_connections WHERE user_id = :uid "
            "ORDER BY created_at"
        ),
        {"uid": user_id},
    ).fetchall()

    connections = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        connections.append({
            "provider": r["provider"],
            "provider_user_id": r["provider_user_id"],
            "connected_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })

    return api_response(connections)


# ---------------------------------------------------------------------------
# DELETE /connections/<provider> — unlink OAuth provider
# ---------------------------------------------------------------------------

@bp.route("/connections/<provider>", methods=["DELETE"])
@rate_limit(tier="write")
def unlink_connection(provider: str):
    """Unlink an OAuth provider.

    Safety check: must have password set OR another OAuth provider linked
    to prevent orphaned accounts.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    # Check user has password or another OAuth connection
    user_row = conn.execute(
        text("SELECT password_hash FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user_row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(user_row) if not isinstance(user_row, dict) else user_row
    has_password = bool(user.get("password_hash"))

    other_oauth = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM oauth_connections "
            "WHERE user_id = :uid AND provider != :provider"
        ),
        {"uid": user_id, "provider": provider},
    ).fetchone()

    other_count = (dict(other_oauth)["cnt"] if not isinstance(other_oauth, dict)
                   else other_oauth["cnt"])

    if not has_password and other_count == 0:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Cannot unlink: you must have a password or another OAuth provider linked",
            status=400,
        )

    # Delete the connection
    result = conn.execute(
        text(
            "DELETE FROM oauth_connections "
            "WHERE user_id = :uid AND provider = :provider "
            "RETURNING id"
        ),
        {"uid": user_id, "provider": provider},
    ).fetchone()

    if result is None:
        return api_error(ErrorCode.NOT_FOUND, "Connection not found", status=404)

    conn.commit()
    return api_response({"unlinked": provider})


# ---------------------------------------------------------------------------
# GET /activity — login activity log
# ---------------------------------------------------------------------------

@bp.route("/activity", methods=["GET"])
@rate_limit(tier="read")
def login_activity():
    """Return paginated login activity from audit_log."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    limit = min(int(request.args.get("limit", 20)), 100)
    offset = max(int(request.args.get("offset", 0)), 0)

    conn = get_pg_connection()
    rows = conn.execute(
        text(
            "SELECT action, details, ip_address, user_agent, created_at "
            "FROM audit_log "
            "WHERE user_id = :uid "
            "ORDER BY created_at DESC "
            "LIMIT :lim OFFSET :off"
        ),
        {"uid": user_id, "lim": limit, "off": offset},
    ).fetchall()

    events = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        details = r.get("details")
        if isinstance(details, str):
            details = json.loads(details)
        events.append({
            "action": r["action"],
            "details": details,
            "ip_address": r.get("ip_address"),
            "user_agent": r.get("user_agent"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })

    return api_response(events)


# ---------------------------------------------------------------------------
# GET /data-summary — overview of user's stored data
# ---------------------------------------------------------------------------

@bp.route("/data-summary", methods=["GET"])
@rate_limit(tier="read")
def data_summary():
    """Return summary of user's stored data: sessions, storage, retention, exports."""
    from sqlalchemy import text
    from auth.entitlements import get_user_entitlements

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    conn = get_pg_connection()

    # Session count + oldest session + total storage
    stats = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt, "
            "MIN(created_at) AS oldest, "
            "COALESCE(SUM(file_size_bytes), 0) AS total_bytes "
            "FROM sessions WHERE user_id = :uid"
        ),
        {"uid": user_id},
    ).fetchone()

    stats_d = dict(stats) if not isinstance(stats, dict) else stats
    sessions_count = stats_d.get("cnt", 0)
    total_bytes = stats_d.get("total_bytes", 0)
    oldest = stats_d.get("oldest")
    total_storage_mb = round(total_bytes / (1024 * 1024), 1)

    # Get retention info from entitlements
    ents = get_user_entitlements(conn, user_id, workspace_id)
    retention_days = ents.get("telemetry_retention_days", 90)
    plan_tier = ents.get("plan_tier", "demo")

    # Find sessions expiring within 14 days
    expiring_sessions = []
    if retention_days and retention_days > 0:
        cutoff_soon = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        cutoff_expire = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        rows = conn.execute(
            text(
                "SELECT id, file_name, created_at "
                "FROM sessions WHERE user_id = :uid "
                "AND created_at < :cutoff_soon "
                "AND created_at >= :cutoff_expire "
                "ORDER BY created_at ASC LIMIT 20"
            ),
            {"uid": user_id, "cutoff_soon": cutoff_soon, "cutoff_expire": cutoff_expire},
        ).fetchall()

        for row in rows:
            r = dict(row) if not isinstance(row, dict) else row
            created = r["created_at"]
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            expires_at = created + timedelta(days=retention_days)
            days_remaining = max(0, (expires_at - datetime.now(timezone.utc)).days)
            if days_remaining <= 14:
                expiring_sessions.append({
                    "id": r["id"],
                    "name": r.get("file_name", f"Session {r['id']}"),
                    "expires_at": expires_at.date().isoformat(),
                    "days_remaining": days_remaining,
                })

    # Recent exports
    exports = []
    export_rows = conn.execute(
        text(
            "SELECT id, status, created_at, completed_at "
            "FROM data_exports WHERE user_id = :uid "
            "ORDER BY created_at DESC LIMIT 5"
        ),
        {"uid": user_id},
    ).fetchall()

    for row in export_rows:
        r = dict(row) if not isinstance(row, dict) else row
        created = r.get("created_at")
        expires_at = None
        if created:
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            expires_at = (created + timedelta(days=7)).date().isoformat()
            created = created.isoformat() if hasattr(created, "isoformat") else str(created)
        exports.append({
            "id": str(r["id"]),
            "status": r.get("status", "unknown"),
            "created_at": created,
            "expires_at": expires_at,
        })

    return api_response({
        "sessions_count": sessions_count,
        "total_storage_mb": total_storage_mb,
        "oldest_session": oldest.date().isoformat() if oldest and hasattr(oldest, "date") else (oldest if oldest else None),
        "retention_policy": {
            "plan_tier": plan_tier,
            "raw_retention_days": retention_days,
            "sessions_expiring_soon": expiring_sessions,
        },
        "exports": exports,
    })


# ---------------------------------------------------------------------------
# POST /data/delete-sessions — 2-step session deletion
# ---------------------------------------------------------------------------

_DELETE_TOKEN_EXPIRY_MINUTES = 5


def _make_delete_token(user_id: int, session_ids: list[int]) -> str:
    """Create a short-lived confirmation token for session deletion.

    Uses HMAC-SHA256 with the JWT secret to sign the payload.
    Token format: base64({user_id}:{session_ids}:{expires_ts}):signature
    """
    import hmac
    import base64

    secret = os.environ.get("TELEMETRY_JWT_SECRET", "dev-secret")
    expires = int((datetime.now(timezone.utc) + timedelta(minutes=_DELETE_TOKEN_EXPIRY_MINUTES)).timestamp())
    ids_str = ",".join(str(s) for s in sorted(session_ids))
    payload = f"{user_id}:{ids_str}:{expires}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()
    return token


def _verify_delete_token(user_id: int, token: str) -> list[int] | None:
    """Verify and decode a delete confirmation token.

    Returns session IDs on success, None on failure/expiry.
    """
    import hmac
    import base64

    secret = os.environ.get("TELEMETRY_JWT_SECRET", "dev-secret")
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.rsplit(":", 1)
        if len(parts) != 2:
            return None
        payload, sig = parts
        # Verify signature
        expected_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        # Parse payload
        fields = payload.split(":")
        if len(fields) != 3:
            return None
        token_uid, ids_str, expires_str = fields
        if int(token_uid) != user_id:
            return None
        if int(expires_str) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return [int(i) for i in ids_str.split(",") if i]
    except Exception:
        return None


@bp.route("/data/delete-sessions", methods=["POST"])
@rate_limit(tier="write")
def delete_sessions():
    """Batch-delete sessions with 2-step confirmation.

    Step 1 (no confirmation_token): returns confirmation_token + sessions info.
    Step 2 (with confirmation_token): actually deletes sessions.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    body = request.get_json(silent=True) or {}
    session_ids = body.get("session_ids", [])
    confirmation_token = body.get("confirmation_token")

    if not session_ids and not confirmation_token:
        return api_error(ErrorCode.VALIDATION_ERROR, "session_ids required", status=400)

    conn = get_pg_connection()

    # Step 2: confirm deletion
    if confirmation_token:
        verified_ids = _verify_delete_token(user_id, confirmation_token)
        if verified_ids is None:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Invalid or expired confirmation token",
                status=400,
            )

        # Delete sessions owned by user
        deleted = conn.execute(
            text(
                "DELETE FROM sessions WHERE id = ANY(:ids) AND user_id = :uid "
                "RETURNING id"
            ),
            {"ids": verified_ids, "uid": user_id},
        ).fetchall()

        conn.commit()
        deleted_ids = [dict(r)["id"] if not isinstance(r, dict) else r["id"] for r in deleted]

        logger.info("Sessions deleted: user_id=%s, sessions=%s", user_id, deleted_ids)
        return api_response({
            "deleted": True,
            "deleted_count": len(deleted_ids),
            "deleted_session_ids": deleted_ids,
        })

    # Step 1: generate confirmation token
    if not isinstance(session_ids, list) or not all(isinstance(i, int) for i in session_ids):
        return api_error(ErrorCode.VALIDATION_ERROR, "session_ids must be a list of integers", status=400)

    if len(session_ids) > 100:
        return api_error(ErrorCode.VALIDATION_ERROR, "Maximum 100 sessions per delete", status=400)

    # Verify sessions exist and belong to user
    rows = conn.execute(
        text(
            "SELECT id, file_name, created_at "
            "FROM sessions WHERE id = ANY(:ids) AND user_id = :uid"
        ),
        {"ids": session_ids, "uid": user_id},
    ).fetchall()

    valid_sessions = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        valid_sessions.append({
            "id": r["id"],
            "name": r.get("file_name", f"Session {r['id']}"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })

    if not valid_sessions:
        return api_error(ErrorCode.NOT_FOUND, "No matching sessions found", status=404)

    valid_ids = [s["id"] for s in valid_sessions]
    token = _make_delete_token(user_id, valid_ids)

    return api_response({
        "confirmation_token": token,
        "expires_in_seconds": _DELETE_TOKEN_EXPIRY_MINUTES * 60,
        "sessions_to_delete": valid_sessions,
    })


# ---------------------------------------------------------------------------
# GET /data/retention-schedule — upcoming deletions timeline
# ---------------------------------------------------------------------------

@bp.route("/data/retention-schedule", methods=["GET"])
@rate_limit(tier="read")
def retention_schedule():
    """Return full schedule of upcoming automatic data deletions."""
    from sqlalchemy import text
    from auth.entitlements import get_user_entitlements

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    conn = get_pg_connection()

    ents = get_user_entitlements(conn, user_id, workspace_id)
    retention_days = ents.get("telemetry_retention_days", 90)

    if retention_days is None or retention_days < 0:
        return api_response({
            "retention_days": None,
            "deletions": [],
            "export_recommended": False,
        })

    # Find all sessions that will expire within the retention window
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        text(
            "SELECT id, file_name, created_at "
            "FROM sessions WHERE user_id = :uid "
            "ORDER BY created_at ASC"
        ),
        {"uid": user_id},
    ).fetchall()

    # Group by deletion date
    deletions_by_date: dict[str, list[dict]] = {}
    has_expiring = False

    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        created = r["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        expires_at = created + timedelta(days=retention_days)
        if expires_at <= now:
            continue  # Already expired / will be cleaned up by purge task

        date_key = expires_at.date().isoformat()
        if date_key not in deletions_by_date:
            deletions_by_date[date_key] = []
        deletions_by_date[date_key].append({
            "id": r["id"],
            "name": r.get("file_name", f"Session {r['id']}"),
        })
        has_expiring = True

    deletions = [
        {"date": d, "sessions": sessions}
        for d, sessions in sorted(deletions_by_date.items())
    ]

    # Recommend export if any sessions expire within 30 days
    export_recommended = False
    cutoff_30d = (now + timedelta(days=30)).date().isoformat()
    for d in deletions:
        if d["date"] <= cutoff_30d:
            export_recommended = True
            break

    return api_response({
        "retention_days": retention_days,
        "deletions": deletions,
        "export_recommended": export_recommended,
    })


# ---------------------------------------------------------------------------
# POST /terms/accept — record terms acceptance
# ---------------------------------------------------------------------------

@bp.route("/terms/accept", methods=["POST"])
@rate_limit(tier="write")
def accept_terms():
    """Record that the user accepted the current terms version."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    conn.execute(
        text(
            "UPDATE users SET terms_accepted_at = now(), terms_version = :ver "
            "WHERE id = :uid"
        ),
        {"ver": TERMS_VERSION, "uid": user_id},
    )
    conn.commit()

    return api_response({
        "accepted": True,
        "terms_version": TERMS_VERSION,
    })


# ---------------------------------------------------------------------------
# GET /terms/status — check if user needs to re-accept terms
# ---------------------------------------------------------------------------

@bp.route("/terms/status", methods=["GET"])
@rate_limit(tier="read")
def terms_status():
    """Check if the user's terms acceptance is current."""
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    row = conn.execute(
        text("SELECT terms_accepted_at, terms_version FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    data = dict(row) if not isinstance(row, dict) else row
    accepted_version = data.get("terms_version")
    accepted_at = data.get("terms_accepted_at")

    needs_acceptance = (accepted_version != TERMS_VERSION)

    return api_response({
        "current_version": TERMS_VERSION,
        "accepted_version": accepted_version,
        "accepted_at": accepted_at.isoformat() if accepted_at else None,
        "needs_acceptance": needs_acceptance,
    })


# ---------------------------------------------------------------------------
# GET /entitlements — plan-based feature entitlements
# ---------------------------------------------------------------------------

@bp.route("/entitlements", methods=["GET"])
@rate_limit(tier="read")
def get_entitlements():
    """Return plan-based feature entitlements for the current user.

    Returns:
        200 with ``{plan, entitlements}``
    """
    from auth.entitlements import get_plan_entitlements

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT plan_tier FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    plan = (dict(row) if not isinstance(row, dict) else row).get("plan_tier") or "demo"
    entitlements = get_plan_entitlements(plan)

    return api_response({
        "plan": plan,
        "entitlements": entitlements,
    })


# ---------------------------------------------------------------------------
# GET /usage — current month usage snapshot
# ---------------------------------------------------------------------------

@bp.route("/usage", methods=["GET"])
@rate_limit(tier="read")
def get_usage():
    """Return usage snapshot for the current billing period.

    Uses the entitlements-aware ``get_usage_snapshot()`` function.

    Returns:
        200 with usage dict.
    """
    from auth.usage import get_usage_snapshot

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.FORBIDDEN, "No workspace context", status=403)

    conn = get_pg_connection()
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT plan_tier FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    plan = "demo"
    if row is not None:
        plan = (dict(row) if not isinstance(row, dict) else row).get("plan_tier") or "demo"

    snapshot = get_usage_snapshot(conn, workspace_id, plan)

    return api_response(snapshot)


# ---------------------------------------------------------------------------
# GET /retention — data retention schedule per session
# ---------------------------------------------------------------------------

@bp.route("/retention", methods=["GET"])
@rate_limit(tier="read")
def get_retention():
    """Return data retention info: per-session expiry dates.

    Lists the 100 most recent sessions with their calculated ``expires_at``
    based on the plan's ``raw_retention_days``.

    Returns:
        200 with ``{plan, raw_retention_days, report_retention, sessions}``
    """
    from auth.entitlements import get_plan_entitlements
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)

    conn = get_pg_connection()

    row = conn.execute(
        text("SELECT plan_tier FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    plan = "demo"
    if row is not None:
        plan = (dict(row) if not isinstance(row, dict) else row).get("plan_tier") or "demo"

    ent = get_plan_entitlements(plan)
    retention_days = ent.get("raw_retention_days", 30)
    report_retention = ent.get("report_retention", "indefinite")

    # Query sessions (workspace-scoped if available, otherwise user-scoped)
    if workspace_id is not None:
        rows = conn.execute(
            text(
                "SELECT session_id, file_name, created_at "
                "FROM sessions "
                "WHERE workspace_id = :wsid "
                "ORDER BY created_at DESC LIMIT 100"
            ),
            {"wsid": workspace_id},
        ).fetchall()
    else:
        rows = conn.execute(
            text(
                "SELECT session_id, file_name, created_at "
                "FROM sessions "
                "WHERE user_id = :uid "
                "ORDER BY created_at DESC LIMIT 100"
            ),
            {"uid": user_id},
        ).fetchall()

    sessions = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        created = r.get("created_at")
        if created is None:
            continue
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if hasattr(created, "tzinfo") and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        expires_at = created + timedelta(days=retention_days)
        sessions.append({
            "session_id": r.get("session_id"),
            "file_name": r.get("file_name"),
            "created_at": created.isoformat(),
            "expires_at": expires_at.isoformat(),
        })

    return api_response({
        "plan": plan,
        "raw_retention_days": retention_days,
        "report_retention": report_retention,
        "sessions": sessions,
    })


# ---------------------------------------------------------------------------
# GET /oauth-connections — list OAuth connections (alias for /connections)
# ---------------------------------------------------------------------------

@bp.route("/oauth-connections", methods=["GET"])
@rate_limit(tier="read")
def list_oauth_connections():
    """List linked OAuth providers.

    Returns:
        200 with list of ``{provider, provider_user_id, created_at}``
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()
    rows = conn.execute(
        text(
            "SELECT provider, provider_user_id, created_at "
            "FROM oauth_connections WHERE user_id = :uid "
            "ORDER BY created_at"
        ),
        {"uid": user_id},
    ).fetchall()

    connections = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        connections.append({
            "provider": r["provider"],
            "provider_user_id": r["provider_user_id"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })

    return api_response(connections)


# ---------------------------------------------------------------------------
# DELETE /oauth-connections/<provider> — unlink OAuth provider
# ---------------------------------------------------------------------------

@bp.route("/oauth-connections/<provider>", methods=["DELETE"])
@rate_limit(tier="write")
def unlink_oauth_connection(provider: str):
    """Unlink an OAuth provider.

    Safety check: cannot unlink if this is the user's last auth method
    (no password set AND only one OAuth connection remaining).

    Returns:
        200 with ``{unlinked: provider}``
        400 with LAST_AUTH_METHOD if this is the only login method
        404 if connection not found
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    # Check if user has a password
    user_row = conn.execute(
        text("SELECT password_hash FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user_row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(user_row) if not isinstance(user_row, dict) else user_row
    has_password = bool(user.get("password_hash"))

    # Count remaining OAuth connections
    count_row = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM oauth_connections "
            "WHERE user_id = :uid"
        ),
        {"uid": user_id},
    ).fetchone()

    total_count = (dict(count_row)["cnt"] if not isinstance(count_row, dict)
                   else count_row["cnt"])

    if not has_password and total_count <= 1:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Cannot unlink: this is your last authentication method. Set a password first.",
            status=400,
            details=[{"code": "LAST_AUTH_METHOD"}],
        )

    # Delete the connection
    result = conn.execute(
        text(
            "DELETE FROM oauth_connections "
            "WHERE user_id = :uid AND provider = :provider "
            "RETURNING id"
        ),
        {"uid": user_id, "provider": provider},
    ).fetchone()

    if result is None:
        return api_error(ErrorCode.NOT_FOUND, "Connection not found", status=404)

    conn.commit()
    return api_response({"unlinked": provider})


# ---------------------------------------------------------------------------
# POST /support/ticket — create support ticket
# ---------------------------------------------------------------------------

@bp.route("/support/ticket", methods=["POST"])
@rate_limit(tier="write")
def create_support_ticket():
    """Create a support ticket from the account settings page.

    Stores in support_tickets table and sends notification email.

    Accepts:
        issue_type: str (required)
        description: str (required, min 10 chars)
        session_id: int (optional)
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    workspace_id = getattr(g, "workspace_id", None)

    body = request.get_json(silent=True) or {}
    issue_type = (body.get("issue_type") or "").strip()
    description = (body.get("description") or "").strip()
    session_id = body.get("session_id")

    if not issue_type:
        return api_error(ErrorCode.VALIDATION_ERROR, "issue_type is required", status=400)

    if not description or len(description) < 10:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "description must be at least 10 characters",
            status=400,
        )

    if len(description) > 5000:
        return api_error(ErrorCode.VALIDATION_ERROR, "description too long (max 5000)", status=400)

    conn = get_pg_connection()

    # Get user email for the notification
    user_row = conn.execute(
        text("SELECT email, display_name, plan_tier FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    user_data = dict(user_row) if user_row and not isinstance(user_row, dict) else (user_row or {})

    # Insert ticket
    row = conn.execute(
        text(
            "INSERT INTO support_tickets "
            "(user_id, workspace_id, issue_type, description, session_id, status) "
            "VALUES (:uid, :wsid, :type, :desc, :sid, 'open') "
            "RETURNING id, created_at"
        ),
        {
            "uid": user_id,
            "wsid": workspace_id,
            "type": issue_type,
            "desc": description,
            "sid": session_id,
        },
    ).fetchone()

    ticket_data = dict(row) if not isinstance(row, dict) else row
    ticket_id = ticket_data["id"]
    conn.commit()

    # Send notification email to support
    try:
        from auth.email import _send
        email = user_data.get("email", "unknown") if isinstance(user_data, dict) else "unknown"
        plan = user_data.get("plan_tier", "unknown") if isinstance(user_data, dict) else "unknown"
        name = user_data.get("display_name", "User") if isinstance(user_data, dict) else "User"

        subject = f"[LAP Support #{ticket_id}] {issue_type}: {description[:60]}"
        html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">New Support Ticket #{ticket_id}</h2>
  <table style="border-collapse: collapse; margin: 12px 0;">
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">User:</td>
      <td style="color: #F3F0E8;">{name} ({email})</td>
    </tr>
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">Plan:</td>
      <td style="color: #F3F0E8;">{plan}</td>
    </tr>
    <tr>
      <td style="color: #8A8F98; padding: 4px 12px 4px 0;">Type:</td>
      <td style="color: #F3F0E8;">{issue_type}</td>
    </tr>
  </table>
  <h3 style="color: #F3F0E8;">Description</h3>
  <p style="color: #8A8F98; white-space: pre-wrap;">{description}</p>
</div>"""
        _send("support@lap-coach.racing", subject, html)
    except Exception:
        logger.exception("Failed to send support notification email for ticket %s", ticket_id)

    logger.info("Support ticket created: id=%s, user=%s, type=%s", ticket_id, user_id, issue_type)

    return api_response({
        "ticket_id": ticket_id,
        "status": "open",
        "message": "Your support ticket has been submitted. We'll respond within 24 hours.",
    }, status=201)
