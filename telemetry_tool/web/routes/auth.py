"""Auth routes -- register, login, refresh, logout, me."""
import logging

from flask import Blueprint, make_response, request, current_app, g

from web.api_utils import api_response, api_error, ErrorCode
from web.middleware.csrf import generate_csrf_token, set_csrf_cookie
from web.rate_limit import rate_limit
from web.validation import validate_body
from web.schemas.auth import RegisterSchema, LoginSchema

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.after_request
def _no_cache_auth(response):
    """Prevent caching of auth responses (tokens, user info)."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


# Password max — Argon2 DoS prevention (still checked on non-schema routes).
_PASSWORD_MAX = 1024

_REFRESH_COOKIE = "lap_refresh_token"
_REFRESH_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


def _set_refresh_cookie(resp, refresh_token: str):
    """Set the refresh token as an httpOnly secure cookie."""
    resp.set_cookie(
        _REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path="/auth/refresh",
    )
    return resp


def _clear_refresh_cookie(resp):
    """Remove the refresh token cookie."""
    resp.set_cookie(
        _REFRESH_COOKIE,
        "",
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=0,
        path="/auth/refresh",
    )
    return resp


def _get_conn():
    """Get DB connection (PG in SaaS mode).

    Auth routes require PostgreSQL — they use PG-native SQL (RETURNING,
    NOW(), %(name)s params).  Raises RuntimeError if called without USE_PG=1.
    """
    if not current_app.config.get("USE_PG"):
        raise RuntimeError(
            "Auth routes require PostgreSQL (USE_PG=1). "
            "Auth blueprints should not be registered without USE_PG."
        )
    from web.db import get_db_connection
    return get_db_connection()


def _check_suspension(conn, user_id: int) -> str | None:
    """Return suspension reason if user is suspended, else None."""
    try:
        row = conn.execute(
            "SELECT suspension_reason FROM users "
            "WHERE id = %(uid)s AND suspended_at IS NOT NULL",
            {"uid": user_id},
        ).fetchone()
        if row:
            data = dict(row) if not isinstance(row, dict) else row
            return data.get("suspension_reason") or "Account suspended"
        return None
    except Exception:
        logger.exception("Suspension check failed")
        return None


def _check_login_anomaly(conn, user_id: int, ip: str, user_agent: str) -> None:
    """Detect login from a new country and send notification email.

    Uses a simple IP-based approach: checks if this IP has been seen before
    for this user in the audit_log. If not, sends a notification.
    """
    try:
        # Check if this IP has been used before by this user
        row = conn.execute(
            "SELECT 1 FROM audit_log "
            "WHERE user_id = %(uid)s AND ip_address = %(ip)s "
            "AND action IN ('login_password', 'login_oauth', 'login_2fa') "
            "LIMIT 1",
            {"uid": user_id, "ip": ip},
        ).fetchone()

        if row is not None:
            return  # Known IP — no anomaly

        # New IP detected — check if user has any previous logins at all
        prev = conn.execute(
            "SELECT COUNT(*) AS cnt FROM audit_log "
            "WHERE user_id = %(uid)s "
            "AND action IN ('login_password', 'login_oauth', 'login_2fa')",
            {"uid": user_id},
        ).fetchone()
        prev_data = dict(prev) if prev and not isinstance(prev, dict) else (prev or {})

        if prev_data.get("cnt", 0) <= 1:
            return  # First or second login — don't alert on initial logins

        # Get user email for notification
        user_row = conn.execute(
            "SELECT email FROM users WHERE id = %(uid)s",
            {"uid": user_id},
        ).fetchone()
        if not user_row:
            return
        user_data = dict(user_row) if not isinstance(user_row, dict) else user_row

        from auth.email import send_new_login_email
        send_new_login_email(
            user_data["email"],
            device_info=user_agent[:200] if user_agent else "Unknown",
            ip_address=ip or "Unknown",
        )
        logger.info("Login anomaly: new IP %s for user %s", ip, user_id)
    except Exception:
        logger.exception("Login anomaly check failed (non-fatal)")


@bp.route("/register", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(RegisterSchema)
def register():
    from auth.service import (
        register_user, create_access_token, create_refresh_token,
        hash_refresh_token, AuthError,
    )
    from datetime import datetime, timedelta, timezone

    body = g.body  # validated RegisterSchema
    email = body.email
    password = body.password
    display_name = body.display_name

    conn = _get_conn()
    try:
        user = register_user(conn, email, password, display_name or email.split("@")[0])
        secret = current_app.config["JWT_SECRET"]
        access_token = create_access_token(user["id"], secret)
        refresh_token = create_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=current_app.config.get("JWT_REFRESH_EXPIRY_DAYS", 30)
        )
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
            "VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s)",
            {"user_id": user["id"], "token_hash": hash_refresh_token(refresh_token),
             "expires_at": expires_at},
        )
        conn.commit()

        # Send verification email (non-blocking — failure doesn't stop registration)
        try:
            from auth.email import send_verification_email
            import secrets
            from datetime import datetime, timedelta, timezone as tz
            verify_token = secrets.token_urlsafe(32)
            verify_expires = datetime.now(tz.utc) + timedelta(hours=24)
            conn.execute(
                "UPDATE users SET email_verify_token = %(token)s, "
                "email_verify_expires = %(expires)s WHERE id = %(uid)s",
                {"token": verify_token, "expires": verify_expires, "uid": user["id"]},
            )
            conn.commit()
            send_verification_email(email, verify_token)
        except Exception:
            logger.warning("Verification email failed for %s — user can still log in", email, exc_info=True)

        result = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user,
        }
        resp = make_response(api_response(result, status=201))
        _set_refresh_cookie(resp, refresh_token)
        set_csrf_cookie(resp, generate_csrf_token())
        return resp
    except AuthError as e:
        status_code = 409 if e.code == "CONFLICT" else 400
        return api_error(ErrorCode.CONFLICT if e.code == "CONFLICT" else ErrorCode.VALIDATION_ERROR, str(e), status=status_code)
    except Exception:
        logger.exception("Registration failed unexpectedly")
        return api_error(ErrorCode.INTERNAL_ERROR, "Registration failed", status=500)


@bp.route("/login", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(LoginSchema)
def login():
    from auth.service import login_user, AuthError
    from auth.lockout import check_lockout, record_failed_attempt, clear_attempts

    body = g.body  # validated LoginSchema
    email = body.email.strip().lower()
    password = body.password

    if len(password) > _PASSWORD_MAX:
        return api_error(ErrorCode.VALIDATION_ERROR, "Password too long", status=400)

    # Check account lockout before attempting auth
    retry_after = check_lockout(email)
    if retry_after is not None:
        resp = make_response(api_error(
            ErrorCode.RATE_LIMITED, "Too many failed attempts. Try again later.",
            status=429,
        ))
        resp.headers["Retry-After"] = str(retry_after)
        return resp

    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]
    ua = request.headers.get("User-Agent", "")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    try:
        result = login_user(
            conn, email, password, secret,
            user_agent=ua, ip_address=ip,
        )

        # Check suspension
        user_id = result.get("user", {}).get("id") if not result.get("requires_2fa") else None
        if user_id:
            suspended = _check_suspension(conn, user_id)
            if suspended:
                return api_error(
                    ErrorCode.FORBIDDEN,
                    f"Account suspended: {suspended}",
                    status=403,
                )

        # Clear lockout on successful login
        clear_attempts(email)

        # If 2FA is required, return the temp token (no cookies set yet)
        if result.get("requires_2fa"):
            return api_response(result)

        # Log successful login + anomaly detection
        from auth.service import _log_audit
        _log_audit(conn, result["user"]["id"], "login_password",
                   {"ip": ip}, ip_address=ip, user_agent=ua)
        _check_login_anomaly(conn, result["user"]["id"], ip, ua)

        resp = make_response(api_response(result))
        if result.get("refresh_token"):
            _set_refresh_cookie(resp, result["refresh_token"])
        set_csrf_cookie(resp, generate_csrf_token())
        return resp
    except AuthError as e:
        record_failed_attempt(email)
        return api_error(ErrorCode.INVALID_CREDENTIALS, str(e), status=401)
    except Exception:
        logger.exception("Login failed unexpectedly")
        return api_error(ErrorCode.INTERNAL_ERROR, "Login failed", status=500)


@bp.route("/logout", methods=["POST"])
def logout():
    from auth.service import hash_refresh_token

    body = request.get_json(silent=True) or {}
    refresh_token = (
        request.cookies.get(_REFRESH_COOKIE)
        or body.get("refresh_token")
    )
    if not refresh_token:
        resp = make_response(api_response({"message": "Logged out"}))
        _clear_refresh_cookie(resp)
        return resp

    conn = _get_conn()
    token_hash = hash_refresh_token(refresh_token)
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = %(token_hash)s",
        {"token_hash": token_hash},
    )
    conn.commit()
    resp = make_response(api_response({"message": "Logged out"}))
    _clear_refresh_cookie(resp)
    return resp


@bp.route("/refresh", methods=["POST"])
@rate_limit(tier="auth")
def refresh():
    """Exchange a valid refresh token for a new access + refresh token pair.

    Implements single-use rotation: the old refresh token is revoked and a
    new one is issued.  This limits the window of abuse if a refresh token
    is compromised.
    """
    from auth.service import (
        create_access_token, create_refresh_token,
        hash_refresh_token, AuthError,
    )
    from datetime import datetime, timedelta, timezone

    body = request.get_json(silent=True) or {}
    refresh_token = (
        request.cookies.get(_REFRESH_COOKIE)
        or body.get("refresh_token", "")
    ).strip()
    if not refresh_token:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "Refresh token required", status=400,
        )

    conn = _get_conn()
    token_hash = hash_refresh_token(refresh_token)

    try:
        # Find and validate the refresh token (must be active and not expired)
        cur = conn.execute(
            "SELECT id, user_id FROM refresh_tokens "
            "WHERE token_hash = %(token_hash)s "
            "AND revoked_at IS NULL "
            "AND expires_at > NOW()",
            {"token_hash": token_hash},
        )
        row = cur.fetchone()

        if row is None:
            return api_error(
                ErrorCode.TOKEN_EXPIRED, "Invalid or expired refresh token",
                status=401,
            )

        user_id = row["user_id"]
        old_token_id = row["id"]

        ua = request.headers.get("User-Agent", "")
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")

        # Revoke the old refresh token (single-use rotation)
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = NOW() WHERE id = %(id)s",
            {"id": old_token_id},
        )

        # Issue new token pair
        secret = current_app.config["JWT_SECRET"]
        new_access = create_access_token(user_id, secret)
        new_refresh = create_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=current_app.config.get("JWT_REFRESH_EXPIRY_DAYS", 30)
        )
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, user_agent, ip_address) "
            "VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s, %(ua)s, %(ip)s)",
            {"user_id": user_id, "token_hash": hash_refresh_token(new_refresh),
             "expires_at": expires_at, "ua": ua[:500], "ip": ip[:45]},
        )
        conn.commit()

        # Fetch user info
        cur = conn.execute(
            "SELECT id, email, display_name FROM users WHERE id = %(user_id)s",
            {"user_id": user_id},
        )
        user = cur.fetchone()

        result = {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "user": dict(user) if user else {},
        }
        resp = make_response(api_response(result))
        _set_refresh_cookie(resp, new_refresh)
        set_csrf_cookie(resp, generate_csrf_token())
        return resp
    except Exception:
        logger.exception("Token refresh failed")
        return api_error(
            ErrorCode.INTERNAL_ERROR, "Token refresh failed", status=500,
        )


@bp.route("/oauth/<provider>", methods=["GET"])
def oauth_redirect(provider):
    """Redirect to OAuth provider."""
    from auth.oauth import oauth as oauth_registry
    client = oauth_registry.create_client(provider)
    if client is None:
        return api_error(
            ErrorCode.NOT_FOUND, "Unknown OAuth provider", status=404,
        )
    redirect_uri = f"{current_app.config['OAUTH_REDIRECT_BASE']}/auth/oauth/{provider}/callback"
    return client.authorize_redirect(redirect_uri)


@bp.route("/oauth/<provider>/callback", methods=["GET"])
def oauth_callback(provider):
    """Handle OAuth callback -- create/link user, redirect to frontend.

    This is a browser redirect flow (not AJAX), so we redirect the user
    back to the frontend after setting the httpOnly refresh cookie.
    The access token is passed in the URL hash fragment (never reaches
    server logs) and is read client-side by the OAuth callback page.
    """
    from flask import redirect as flask_redirect
    from auth.oauth import oauth as oauth_registry, get_or_create_oauth_user

    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:3000")

    client = oauth_registry.create_client(provider)
    if client is None:
        return flask_redirect(f"{frontend_url}/login?error=unknown_provider")

    try:
        token = client.authorize_access_token()
    except Exception:
        logger.exception("OAuth token exchange failed for %s", provider)
        return flask_redirect(f"{frontend_url}/login?error=oauth_failed")

    if provider == "google":
        userinfo = token.get("userinfo", {})
        profile = {
            "id": userinfo["sub"],
            "email": userinfo["email"],
            "name": userinfo.get("name", ""),
            "email_verified": userinfo.get("email_verified", False),
        }
    elif provider == "github":
        resp = client.get("user")
        profile = resp.json()
        email_verified = False
        if not profile.get("email"):
            emails = client.get("user/emails").json()
            if not emails:
                return flask_redirect(f"{frontend_url}/login?error=no_github_email")
            primary = next((e for e in emails if e["primary"]), emails[0])
            profile["email"] = primary["email"]
            email_verified = primary.get("verified", False)
        else:
            emails = client.get("user/emails").json()
            match = next((e for e in emails if e["email"] == profile["email"]), None)
            email_verified = match.get("verified", False) if match else False
        profile["email_verified"] = email_verified
    else:
        return flask_redirect(f"{frontend_url}/login?error=unsupported_provider")

    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]
    try:
        result = get_or_create_oauth_user(conn, provider, profile, secret)

        # Log OAuth login in audit
        ua = request.headers.get("User-Agent", "")
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        from auth.service import _log_audit
        _log_audit(
            conn, result["user"]["id"], f"login_oauth_{provider}",
            {"ip": ip, "provider": provider},
            ip_address=ip, user_agent=ua,
        )

        # Redirect to frontend OAuth callback with access token in hash fragment.
        # Hash fragments never leave the browser (not in server logs or referrer).
        redirect_url = f"{frontend_url}/oauth-callback#access_token={result['access_token']}"
        resp = make_response(flask_redirect(redirect_url))
        if result.get("refresh_token"):
            _set_refresh_cookie(resp, result["refresh_token"])
        set_csrf_cookie(resp, generate_csrf_token())
        return resp
    except Exception as e:
        from auth.service import AuthError
        if isinstance(e, AuthError):
            return flask_redirect(f"{frontend_url}/login?error=oauth_denied")
        logger.exception("OAuth user creation failed for %s", provider)
        return flask_redirect(f"{frontend_url}/login?error=oauth_failed")


@bp.route("/forgot-password", methods=["POST"])
@rate_limit(tier="auth")
def forgot_password():
    """Send a password-reset link if the email exists.

    Always returns 200 to prevent email enumeration (timing-safe).
    """
    from auth.service import create_password_reset_token

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    if not email:
        # Still return 200 for timing safety
        return api_response({"message": "If an account exists, a reset link has been sent"})

    conn = _get_conn()
    token = create_password_reset_token(conn, email)

    if token:
        try:
            from auth.email import send_password_reset_email
            send_password_reset_email(email, token)
        except Exception:
            logger.warning("Password reset email failed for %s", email, exc_info=True)

    return api_response({"message": "If an account exists, a reset link has been sent"})


@bp.route("/reset-password", methods=["POST"])
@rate_limit(tier="auth")
def reset_password_route():
    """Reset password using a valid reset token."""
    from auth.service import reset_password

    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    new_password = body.get("new_password") or ""

    if not token or not new_password:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "Token and new_password required", status=400,
        )

    if len(new_password) > _PASSWORD_MAX:
        return api_error(ErrorCode.VALIDATION_ERROR, "Password too long", status=400)

    if len(new_password) < 8:
        return api_error(ErrorCode.VALIDATION_ERROR, "Password must be at least 8 characters", status=400)

    conn = _get_conn()
    success = reset_password(conn, token, new_password)

    if not success:
        return api_error(
            ErrorCode.TOKEN_EXPIRED, "Invalid or expired reset token", status=400,
        )
    return api_response({"message": "Password has been reset"})


@bp.route("/2fa/verify", methods=["POST"])
@rate_limit(tier="auth")
def verify_2fa():
    """Complete login by verifying TOTP code after password auth.

    Accepts temp_token (from login) + totp_code or backup_code.
    """
    from auth.service import (
        verify_2fa_temp_token, complete_2fa_login, AuthError, _log_audit,
    )

    body = request.get_json(silent=True) or {}
    temp_token = (body.get("temp_token") or "").strip()
    totp_code = (body.get("totp_code") or "").strip()
    backup_code = (body.get("backup_code") or "").strip()

    if not temp_token:
        return api_error(ErrorCode.VALIDATION_ERROR, "temp_token required", status=400)
    if not totp_code and not backup_code:
        return api_error(ErrorCode.VALIDATION_ERROR, "totp_code or backup_code required", status=400)

    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]

    try:
        user_id = verify_2fa_temp_token(temp_token, secret)
    except AuthError as e:
        return api_error(ErrorCode.TOKEN_EXPIRED, str(e), status=401)

    # Fetch user TOTP secret
    cur = conn.execute(
        "SELECT totp_secret, totp_backup_codes FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    user = cur.fetchone()
    if user is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    verified = False

    if totp_code:
        from auth.totp import verify_totp
        verified = verify_totp(user["totp_secret"], totp_code)
    elif backup_code:
        import json
        from auth.totp import verify_backup_code
        hashed_codes = json.loads(user["totp_backup_codes"] or "[]")
        idx = verify_backup_code(backup_code, hashed_codes)
        if idx is not None:
            verified = True
            # Consume the backup code (single-use)
            hashed_codes.pop(idx)
            conn.execute(
                "UPDATE users SET totp_backup_codes = %(codes)s WHERE id = %(uid)s",
                {"codes": json.dumps(hashed_codes), "uid": user_id},
            )

    if not verified:
        return api_error(ErrorCode.INVALID_CREDENTIALS, "Invalid 2FA code", status=401)

    # Log successful 2FA
    ua = request.headers.get("User-Agent", "")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    _log_audit(conn, user_id, "login_2fa", {"ip": ip}, ip_address=ip, user_agent=ua)

    result = complete_2fa_login(
        conn, user_id, secret,
        user_agent=ua,
        ip_address=ip,
    )
    resp = make_response(api_response(result))
    if result.get("refresh_token"):
        _set_refresh_cookie(resp, result["refresh_token"])
    set_csrf_cookie(resp, generate_csrf_token())
    return resp


@bp.route("/verify-email", methods=["POST"])
def verify_email():
    """Verify email address with token."""
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return api_error(
            ErrorCode.VALIDATION_ERROR, "Token required", status=400,
        )

    conn = _get_conn()
    cur = conn.execute(
        "UPDATE users SET email_verified = true, email_verify_token = NULL "
        "WHERE email_verify_token = %(token)s AND email_verify_expires > NOW() "
        "RETURNING id",
        {"token": token},
    )
    row = cur.fetchone()
    conn.commit()

    if row is None:
        return api_error(
            ErrorCode.TOKEN_EXPIRED, "Invalid or expired token", status=400,
        )
    return api_response({"message": "Email verified"})


@bp.route("/resend-verification", methods=["POST"])
@rate_limit(tier="auth")
def resend_verification():
    """Resend email verification link. Requires auth, rate-limited to 3/hour."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=401)

    conn = _get_conn()
    row = conn.execute(
        "SELECT email, email_verified FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    user = dict(row) if not isinstance(row, dict) else row
    if user.get("email_verified"):
        return api_response({"message": "Email is already verified"})

    # Generate new verification token
    import secrets
    token = secrets.token_urlsafe(32)
    from datetime import datetime, timedelta, timezone
    expires = datetime.now(timezone.utc) + timedelta(hours=24)

    conn.execute(
        "UPDATE users SET email_verify_token = %(token)s, "
        "email_verify_expires = %(exp)s WHERE id = %(uid)s",
        {"token": token, "exp": expires, "uid": user_id},
    )
    conn.commit()

    try:
        from auth.email import send_verification_email
        send_verification_email(user["email"], token)
    except Exception:
        logger.exception("Failed to resend verification email to %s", user["email"])

    return api_response({"message": "Verification email sent"})


# ---------------------------------------------------------------------------
# /api/v1/me — separate blueprint for authenticated API routes
# ---------------------------------------------------------------------------

api_v1_bp = Blueprint("api_v1_auth", __name__, url_prefix="/api/v1")


@api_v1_bp.route("/me", methods=["GET"])
def me():
    """Return current user profile with resolved entitlements. Requires auth."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(
            ErrorCode.FORBIDDEN, "Authentication required", status=401,
        )

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, email, display_name, created_at, plan_tier, subscription_status "
        "FROM users WHERE id = %(user_id)s",
        {"user_id": user_id},
    )
    user = cur.fetchone()
    if user is None:
        return api_error(
            ErrorCode.NOT_FOUND, "User not found", status=404,
        )

    result = dict(user)

    # Resolve entitlements if PG is available (entitlements tables exist)
    try:
        from auth.entitlements import get_user_entitlements
        workspace_id = getattr(g, "workspace_id", None)
        result["entitlements"] = get_user_entitlements(conn, user_id, workspace_id)
    except Exception:
        # Graceful fallback — entitlements tables may not exist yet
        pass

    return api_response(result)
