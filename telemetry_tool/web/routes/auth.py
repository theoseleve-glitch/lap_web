"""Auth routes -- register, login, refresh, logout, me."""
import logging

from flask import Blueprint, make_response, request, current_app, g

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit
from web.validation import validate_body
from web.schemas.auth import RegisterSchema, LoginSchema

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")

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

    body = g.body  # validated LoginSchema
    email = body.email.strip().lower()
    password = body.password

    if len(password) > _PASSWORD_MAX:
        return api_error(ErrorCode.VALIDATION_ERROR, "Password too long", status=400)

    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]
    try:
        result = login_user(conn, email, password, secret)
        resp = make_response(api_response(result))
        if result.get("refresh_token"):
            _set_refresh_cookie(resp, result["refresh_token"])
        return resp
    except AuthError as e:
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
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
            "VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s)",
            {"user_id": user_id, "token_hash": hash_refresh_token(new_refresh),
             "expires_at": expires_at},
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
        # Redirect to frontend OAuth callback with access token in hash fragment.
        # Hash fragments never leave the browser (not in server logs or referrer).
        redirect_url = f"{frontend_url}/oauth-callback#access_token={result['access_token']}"
        resp = make_response(flask_redirect(redirect_url))
        if result.get("refresh_token"):
            _set_refresh_cookie(resp, result["refresh_token"])
        return resp
    except Exception as e:
        from auth.service import AuthError
        if isinstance(e, AuthError):
            return flask_redirect(f"{frontend_url}/login?error=oauth_denied")
        logger.exception("OAuth user creation failed for %s", provider)
        return flask_redirect(f"{frontend_url}/login?error=oauth_failed")


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


# ---------------------------------------------------------------------------
# /api/v1/me — separate blueprint for authenticated API routes
# ---------------------------------------------------------------------------

api_v1_bp = Blueprint("api_v1_auth", __name__, url_prefix="/api/v1")


@api_v1_bp.route("/me", methods=["GET"])
def me():
    """Return current user profile. Requires auth."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(
            ErrorCode.FORBIDDEN, "Authentication required", status=401,
        )

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, email, display_name, created_at FROM users WHERE id = %(user_id)s",
        {"user_id": user_id},
    )
    user = cur.fetchone()
    if user is None:
        return api_error(
            ErrorCode.NOT_FOUND, "User not found", status=404,
        )
    return api_response(dict(user))
