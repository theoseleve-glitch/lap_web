"""Auth routes -- register, login, refresh, logout, me."""
import logging
import re

from flask import Blueprint, request, jsonify, current_app, g

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")

# Basic email format check — intentionally permissive (real validation
# happens via verification email).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Password length limits.  Max prevents Argon2 DoS via multi-MB strings.
_PASSWORD_MIN = 8
_PASSWORD_MAX = 1024


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


def _json_response(data=None, error=None, status=200):
    """Consistent response envelope."""
    if error:
        return jsonify({"ok": False, "error": error, "meta": {}}), status
    return jsonify({"ok": True, "data": data, "meta": {}}), status


@bp.route("/register", methods=["POST"])
def register():
    from auth.service import (
        register_user, create_access_token, create_refresh_token,
        hash_refresh_token, AuthError,
    )
    from datetime import datetime, timedelta, timezone

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or "").strip()

    if not email or not _EMAIL_RE.match(email):
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Valid email address required"},
            status=400,
        )

    if not password:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Password required"},
            status=400,
        )

    if len(password) < _PASSWORD_MIN or len(password) > _PASSWORD_MAX:
        return _json_response(
            error={"code": "VALIDATION_ERROR",
                   "message": f"Password must be {_PASSWORD_MIN}-{_PASSWORD_MAX} characters"},
            status=400,
        )

    conn = _get_conn()
    try:
        user = register_user(conn, email, password, display_name or email.split("@")[0])
        # Issue tokens directly — avoids re-hashing the password via login_user().
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
        result = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user,
        }
        return _json_response(data=result, status=201)
    except AuthError as e:
        status_code = 409 if e.code == "CONFLICT" else 400
        return _json_response(error={"code": e.code, "message": str(e)}, status=status_code)
    except Exception:
        logger.exception("Registration failed unexpectedly")
        return _json_response(
            error={"code": "INTERNAL_ERROR", "message": "Registration failed"},
            status=500,
        )


@bp.route("/login", methods=["POST"])
def login():
    from auth.service import login_user, AuthError

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Email and password required"},
            status=400,
        )

    if len(password) > _PASSWORD_MAX:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Password too long"},
            status=400,
        )

    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]
    try:
        result = login_user(conn, email, password, secret)
        return _json_response(data=result)
    except AuthError as e:
        return _json_response(
            error={"code": e.code, "message": str(e)}, status=401,
        )
    except Exception:
        logger.exception("Login failed unexpectedly")
        return _json_response(
            error={"code": "INTERNAL_ERROR", "message": "Login failed"},
            status=500,
        )


@bp.route("/logout", methods=["POST"])
def logout():
    from auth.service import hash_refresh_token

    body = request.get_json(silent=True) or {}
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        return _json_response(data={"message": "Logged out"})

    conn = _get_conn()
    token_hash = hash_refresh_token(refresh_token)
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = %(token_hash)s",
        {"token_hash": token_hash},
    )
    conn.commit()
    return _json_response(data={"message": "Logged out"})


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
    refresh_token = body.get("refresh_token", "").strip()
    if not refresh_token:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Refresh token required"},
            status=400,
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
            return _json_response(
                error={"code": "INVALID_TOKEN", "message": "Invalid or expired refresh token"},
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

        return _json_response(data={
            "access_token": new_access,
            "refresh_token": new_refresh,
            "user": dict(user) if user else {},
        })
    except Exception:
        logger.exception("Token refresh failed")
        return _json_response(
            error={"code": "INTERNAL_ERROR", "message": "Token refresh failed"},
            status=500,
        )


@bp.route("/oauth/<provider>", methods=["GET"])
def oauth_redirect(provider):
    """Redirect to OAuth provider."""
    from auth.oauth import oauth as oauth_registry
    client = oauth_registry.create_client(provider)
    if client is None:
        return _json_response(
            error={"code": "NOT_FOUND", "message": "Unknown OAuth provider"},
            status=404,
        )
    redirect_uri = f"{current_app.config['OAUTH_REDIRECT_BASE']}/auth/oauth/{provider}/callback"
    return client.authorize_redirect(redirect_uri)


@bp.route("/oauth/<provider>/callback", methods=["GET"])
def oauth_callback(provider):
    """Handle OAuth callback -- create/link user, issue tokens."""
    from auth.oauth import oauth as oauth_registry, get_or_create_oauth_user

    client = oauth_registry.create_client(provider)
    if client is None:
        return _json_response(
            error={"code": "NOT_FOUND", "message": "Unknown OAuth provider"},
            status=404,
        )

    try:
        token = client.authorize_access_token()
    except Exception:
        logger.exception("OAuth token exchange failed for %s", provider)
        return _json_response(
            error={"code": "OAUTH_ERROR", "message": "OAuth authentication failed"},
            status=400,
        )

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
                return _json_response(
                    error={"code": "OAUTH_ERROR",
                           "message": "No email address found on GitHub account"},
                    status=400,
                )
            primary = next((e for e in emails if e["primary"]), emails[0])
            profile["email"] = primary["email"]
            email_verified = primary.get("verified", False)
        else:
            # If email came from /user directly, fetch /user/emails to check verified status
            emails = client.get("user/emails").json()
            match = next((e for e in emails if e["email"] == profile["email"]), None)
            email_verified = match.get("verified", False) if match else False
        profile["email_verified"] = email_verified
    else:
        return _json_response(
            error={"code": "NOT_FOUND", "message": "Unsupported OAuth provider"},
            status=404,
        )

    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]
    try:
        result = get_or_create_oauth_user(conn, provider, profile, secret)
        return _json_response(data=result)
    except Exception as e:
        from auth.service import AuthError
        if isinstance(e, AuthError):
            return _json_response(
                error={"code": e.code, "message": str(e)}, status=403,
            )
        logger.exception("OAuth user creation failed for %s", provider)
        return _json_response(
            error={"code": "INTERNAL_ERROR", "message": "OAuth login failed"},
            status=500,
        )


@bp.route("/verify-email", methods=["POST"])
def verify_email():
    """Verify email address with token."""
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Token required"}, status=400,
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
        return _json_response(
            error={"code": "INVALID_TOKEN", "message": "Invalid or expired token"},
            status=400,
        )
    return _json_response(data={"message": "Email verified"})


# ---------------------------------------------------------------------------
# /api/v1/me — separate blueprint for authenticated API routes
# ---------------------------------------------------------------------------

api_v1_bp = Blueprint("api_v1_auth", __name__, url_prefix="/api/v1")


@api_v1_bp.route("/me", methods=["GET"])
def me():
    """Return current user profile. Requires auth."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return _json_response(
            error={"code": "UNAUTHORIZED", "message": "Authentication required"},
            status=401,
        )

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, email, display_name, created_at FROM users WHERE id = %(user_id)s",
        {"user_id": user_id},
    )
    user = cur.fetchone()
    if user is None:
        return _json_response(
            error={"code": "NOT_FOUND", "message": "User not found"}, status=404,
        )
    return _json_response(data=dict(user))
