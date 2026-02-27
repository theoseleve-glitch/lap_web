"""Admin 2FA routes — TOTP setup, verification, and challenge.

These endpoints let superadmins set up TOTP 2FA, verify their setup,
and pass the admin challenge to get an admin_verified JWT.
"""
from __future__ import annotations

import json
import logging
import os

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from admin.totp import (
    generate_totp_secret,
    encrypt_secret,
    decrypt_secret,
    get_provisioning_uri,
    verify_totp,
    generate_recovery_codes,
    verify_recovery_code,
)
from admin.audit import log_admin_action

logger = logging.getLogger(__name__)

bp = Blueprint("admin_auth", __name__)


def _get_conn():
    from flask import current_app

    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection

        return get_pg_connection()
    from web.db import get_db_connection

    return get_db_connection()


def _get_admin_key() -> str:
    """Get the AES encryption key for TOTP secrets."""
    key = os.environ.get("TELEMETRY_ADMIN_KEY", "")
    if not key:
        raise RuntimeError("TELEMETRY_ADMIN_KEY not configured")
    return key


@bp.route("/2fa/setup", methods=["POST"])
def setup_2fa():
    """Generate TOTP secret and recovery codes for admin user.

    Returns the provisioning URI (for QR code) and recovery codes.
    The secret is encrypted and stored but totp_enabled remains False
    until the user verifies with a valid code via /2fa/verify.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=403)

    conn = _get_conn()

    # Check user is a superadmin
    row = conn.execute(
        "SELECT is_superadmin, email, totp_enabled "
        "FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row

    if not user.get("is_superadmin"):
        return api_error(
            ErrorCode.FORBIDDEN, "Superadmin required", status=403
        )

    if user.get("totp_enabled"):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "2FA already enabled — disable first",
            status=400,
        )

    # Generate and store encrypted secret + recovery codes
    secret = generate_totp_secret()
    admin_key = _get_admin_key()
    encrypted = encrypt_secret(secret, admin_key)
    recovery_codes = generate_recovery_codes()

    conn.execute(
        "UPDATE users SET totp_secret = %(secret)s, "
        "totp_backup_codes = %(codes)s "
        "WHERE id = %(uid)s",
        {
            "secret": encrypted,
            "codes": json.dumps(recovery_codes),
            "uid": user_id,
        },
    )
    conn.commit()

    uri = get_provisioning_uri(secret, user["email"])

    return api_response(
        {
            "provisioning_uri": uri,
            "recovery_codes": recovery_codes,
        }
    )


@bp.route("/2fa/verify", methods=["POST"])
def verify_2fa_setup():
    """Verify TOTP setup with a valid code.

    After successful verification, totp_enabled is set to True.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=403)

    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    if not code:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "code is required", status=400
        )

    conn = _get_conn()
    row = conn.execute(
        "SELECT totp_secret, totp_enabled FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row

    if user.get("totp_enabled"):
        return api_error(
            ErrorCode.VALIDATION_ERROR, "2FA already enabled", status=400
        )

    if not user.get("totp_secret"):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Call /2fa/setup first",
            status=400,
        )

    # Decrypt and verify
    admin_key = _get_admin_key()
    secret = decrypt_secret(user["totp_secret"], admin_key)

    if not verify_totp(secret, code):
        return api_error(
            ErrorCode.VALIDATION_ERROR, "Invalid TOTP code", status=400
        )

    # Enable 2FA
    conn.execute(
        "UPDATE users SET totp_enabled = TRUE WHERE id = %(uid)s",
        {"uid": user_id},
    )
    conn.commit()

    try:
        log_admin_action(
            conn, admin_user_id=user_id, action="2fa_enabled"
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log 2FA enable", exc_info=True)

    return api_response({"totp_enabled": True})


@bp.route("/2fa/challenge", methods=["POST"])
def challenge_2fa():
    """Verify TOTP code and issue new JWT with admin_verified=True."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=403)

    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    if not code:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "code is required", status=400
        )

    conn = _get_conn()
    row = conn.execute(
        "SELECT totp_secret, totp_enabled, totp_backup_codes "
        "FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row

    if not user.get("totp_enabled"):
        return api_error(
            ErrorCode.VALIDATION_ERROR, "2FA not enabled", status=400
        )

    admin_key = _get_admin_key()
    secret = decrypt_secret(user["totp_secret"], admin_key)

    # Try TOTP first, then recovery code
    valid = verify_totp(secret, code)
    if not valid and user.get("totp_backup_codes"):
        valid, updated_codes = verify_recovery_code(
            user["totp_backup_codes"], code
        )
        if valid:
            conn.execute(
                "UPDATE users SET totp_backup_codes = %(codes)s "
                "WHERE id = %(uid)s",
                {"codes": updated_codes, "uid": user_id},
            )
            conn.commit()

    if not valid:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "Invalid code", status=400
        )

    # Issue new JWT with admin_verified claim
    from auth.service import create_access_token

    jwt_secret = os.environ.get("TELEMETRY_JWT_SECRET", "")
    if not jwt_secret:
        return api_error(
            ErrorCode.INTERNAL_ERROR,
            "JWT secret not configured",
            status=500,
        )

    token = create_access_token(
        user_id=user_id,
        secret=jwt_secret,
        admin_verified=True,
    )

    return api_response(
        {"access_token": token, "admin_verified": True}
    )


@bp.route("/2fa", methods=["DELETE"])
def disable_2fa():
    """Disable 2FA for an admin user. root_admin only.

    Body: {"user_id": <int>, "reason": "<string>"}
    """
    admin_user = getattr(g, "admin_user", None)
    if not admin_user or admin_user.get("admin_role") != "root_admin":
        return api_error(
            ErrorCode.FORBIDDEN, "root_admin required", status=403
        )

    body = request.get_json(silent=True) or {}
    target_user_id = body.get("user_id")
    reason = body.get("reason", "").strip()

    if not target_user_id or not reason:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "user_id and reason are required",
            status=400,
        )

    conn = _get_conn()
    conn.execute(
        "UPDATE users SET totp_enabled = FALSE, totp_secret = NULL, "
        "totp_backup_codes = NULL WHERE id = %(uid)s",
        {"uid": target_user_id},
    )
    conn.commit()

    try:
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="2fa_disabled",
            target_type="user",
            target_id=str(target_user_id),
            reason=reason,
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log 2FA disable", exc_info=True)

    return api_response(
        {"totp_disabled": True, "user_id": target_user_id}
    )
