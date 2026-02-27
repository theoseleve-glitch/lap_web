"""Core auth service -- registration, login, JWT, password hashing, reset, 2FA."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

logger = logging.getLogger(__name__)

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)

# Pre-computed dummy hash used to prevent timing-based user enumeration.
# When a user is not found (or has no password), we still run the hasher
# so that the response time is indistinguishable from a real verify.
_DUMMY_HASH = _ph.hash("dummy-password-for-timing-equalization")


class AuthError(Exception):
    """Authentication/authorization error with user-safe message."""
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        super().__init__(message)
        self.code = code


# -- Password ---------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against an Argon2id hash."""
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


# -- JWT --------------------------------------------------------------------

def create_access_token(
    user_id: int,
    secret: str,
    expiry_minutes: int = 15,
    email_verified: bool = True,
    admin_verified: bool = False,
) -> str:
    """Create a signed JWT access token for *user_id*.

    *email_verified* lets middleware enforce verification without a DB
    lookup (15-min TTL is acceptable).  *admin_verified* indicates the
    user has passed the admin 2FA challenge.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
        "email_verified": email_verified,
    }
    if admin_verified:
        payload["admin_verified"] = True
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict:
    """Decode and validate a JWT access token.

    Raises :class:`AuthError` on expiry, invalid signature, or wrong type.
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired", "TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid token", "INVALID_TOKEN")

    if payload.get("type") != "access":
        raise AuthError("Invalid token type", "INVALID_TOKEN")

    return payload


def create_refresh_token() -> str:
    """Generate a cryptographically secure refresh token."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hash of a refresh token (stored in the database)."""
    return hashlib.sha256(token.encode()).hexdigest()


# -- Registration -----------------------------------------------------------

def register_user(conn, email: str, password: str, display_name: str) -> dict:
    """Create a new user account.

    Returns the new user row as a dict.  Raises :class:`AuthError` with
    code ``CONFLICT`` if the email is already registered.
    """
    password_hash = hash_password(password)

    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, display_name) "
            "VALUES (%(email)s, %(password_hash)s, %(display_name)s) "
            "RETURNING id, email, display_name, created_at",
            {"email": email, "password_hash": password_hash, "display_name": display_name},
        )
        row = cur.fetchone()
        conn.commit()

        # Auto-create personal workspace for the new user.
        from auth.workspace import create_personal_workspace
        create_personal_workspace(conn, user_id=row["id"],
                                  display_name=f"{display_name}'s Workspace")

        return dict(row)
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise AuthError("Email already registered", "CONFLICT")
        raise


# -- Login ------------------------------------------------------------------

def login_user(
    conn,
    email: str,
    password: str,
    secret: str,
    access_expiry_minutes: int = 15,
    refresh_expiry_days: int = 30,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Authenticate a user by email/password and return access + refresh tokens.

    If the user has 2FA enabled, returns ``{"requires_2fa": True, "temp_token": "..."}``
    instead of full tokens.  The temp_token must be exchanged via ``/auth/2fa/verify``.
    """
    cur = conn.execute(
        "SELECT id, email, password_hash, display_name, totp_enabled "
        "FROM users WHERE email = %(email)s AND deleted_at IS NULL",
        {"email": email},
    )
    user = cur.fetchone()

    # Constant-time check: always run the hasher to prevent timing-based
    # user enumeration.  Also guards against NULL password_hash (OAuth-only
    # accounts where password_hash column is intentionally nullable).
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthError("Invalid credentials", "INVALID_CREDENTIALS")

    if not user["password_hash"] or not verify_password(password, user["password_hash"]):
        raise AuthError("Invalid credentials", "INVALID_CREDENTIALS")

    # If 2FA is enabled, return a temporary token instead of full auth
    if user.get("totp_enabled"):
        temp_token = _create_temp_2fa_token(user["id"], secret)
        return {
            "requires_2fa": True,
            "temp_token": temp_token,
        }

    # Issue tokens
    return _issue_tokens(
        conn, user, secret,
        access_expiry_minutes=access_expiry_minutes,
        refresh_expiry_days=refresh_expiry_days,
        user_agent=user_agent,
        ip_address=ip_address,
    )


def _issue_tokens(
    conn,
    user: dict,
    secret: str,
    *,
    access_expiry_minutes: int = 15,
    refresh_expiry_days: int = 30,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Issue access + refresh tokens and store refresh token in DB."""
    email_verified = bool(user.get("email_verified", True))
    access_token = create_access_token(
        user["id"], secret, access_expiry_minutes,
        email_verified=email_verified,
    )
    refresh_token = create_refresh_token()

    expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_expiry_days)
    conn.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, user_agent, ip_address) "
        "VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s, %(user_agent)s, %(ip_address)s)",
        {
            "user_id": user["id"],
            "token_hash": hash_refresh_token(refresh_token),
            "expires_at": expires_at,
            "user_agent": (user_agent or "")[:500],
            "ip_address": (ip_address or "")[:45],
        },
    )
    conn.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
        },
    }


def _create_temp_2fa_token(user_id: int, secret: str) -> str:
    """Create a short-lived JWT for the 2FA verification step (5 min)."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "type": "2fa_temp",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_2fa_temp_token(token: str, secret: str) -> int:
    """Decode a 2FA temp token and return the user_id.

    Raises AuthError on invalid/expired token.
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError("2FA token expired", "TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid 2FA token", "INVALID_TOKEN")

    if payload.get("type") != "2fa_temp":
        raise AuthError("Invalid token type", "INVALID_TOKEN")

    return payload["user_id"]


def complete_2fa_login(
    conn,
    user_id: int,
    secret: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Issue full tokens after successful 2FA verification."""
    cur = conn.execute(
        "SELECT id, email, display_name FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    user = cur.fetchone()
    if user is None:
        raise AuthError("User not found", "NOT_FOUND")

    return _issue_tokens(
        conn, dict(user), secret,
        user_agent=user_agent,
        ip_address=ip_address,
    )


# -- Password reset ---------------------------------------------------------

def create_password_reset_token(conn, email: str) -> str | None:
    """Generate a time-limited reset token (1 hour expiry).

    Returns token if user exists, None otherwise (don't leak user existence).
    Store SHA-256 hash of token in password_reset_tokens table.
    """
    cur = conn.execute(
        "SELECT id FROM users WHERE email = %(email)s AND deleted_at IS NULL",
        {"email": email},
    )
    user = cur.fetchone()
    if user is None:
        return None

    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    # Clean up any existing tokens for this user (one active at a time)
    conn.execute(
        "DELETE FROM password_reset_tokens WHERE user_id = %(uid)s",
        {"uid": user["id"]},
    )
    conn.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
        "VALUES (%(uid)s, %(hash)s, %(exp)s)",
        {"uid": user["id"], "hash": token_hash, "exp": expires_at},
    )
    conn.commit()

    return token


def reset_password(conn, token: str, new_password: str) -> bool:
    """Verify token, update password_hash, revoke all refresh tokens.

    Single-use: delete token after use. Returns True on success, False if
    token is invalid or expired.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    cur = conn.execute(
        "SELECT id, user_id FROM password_reset_tokens "
        "WHERE token_hash = %(hash)s AND expires_at > NOW()",
        {"hash": token_hash},
    )
    row = cur.fetchone()
    if row is None:
        return False

    user_id = row["user_id"]
    new_hash = hash_password(new_password)

    # Update password
    conn.execute(
        "UPDATE users SET password_hash = %(hash)s WHERE id = %(uid)s",
        {"hash": new_hash, "uid": user_id},
    )

    # Revoke all refresh tokens (force re-auth everywhere)
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() "
        "WHERE user_id = %(uid)s AND revoked_at IS NULL",
        {"uid": user_id},
    )

    # Delete the used reset token
    conn.execute(
        "DELETE FROM password_reset_tokens WHERE id = %(id)s",
        {"id": row["id"]},
    )

    # Log in audit
    _log_audit(conn, user_id, "password_reset", {})

    conn.commit()
    return True


def change_password(
    conn,
    user_id: int,
    current_password: str,
    new_password: str,
    *,
    current_token_hash: str | None = None,
) -> bool:
    """Change password for an authenticated user.

    Verifies current password first (timing-safe). Revokes all refresh tokens
    EXCEPT the one identified by current_token_hash.
    Returns True on success, raises AuthError on failure.
    """
    cur = conn.execute(
        "SELECT password_hash FROM users WHERE id = %(uid)s AND deleted_at IS NULL",
        {"uid": user_id},
    )
    user = cur.fetchone()

    if user is None:
        verify_password(current_password, _DUMMY_HASH)
        raise AuthError("User not found", "NOT_FOUND")

    if not user["password_hash"] or not verify_password(current_password, user["password_hash"]):
        raise AuthError("Current password is incorrect", "INVALID_CREDENTIALS")

    new_hash = hash_password(new_password)

    conn.execute(
        "UPDATE users SET password_hash = %(hash)s WHERE id = %(uid)s",
        {"hash": new_hash, "uid": user_id},
    )

    # Revoke all refresh tokens EXCEPT the current one
    if current_token_hash:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = NOW() "
            "WHERE user_id = %(uid)s AND revoked_at IS NULL "
            "AND token_hash != %(keep)s",
            {"uid": user_id, "keep": current_token_hash},
        )
    else:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = NOW() "
            "WHERE user_id = %(uid)s AND revoked_at IS NULL",
            {"uid": user_id},
        )

    _log_audit(conn, user_id, "password_changed", {})

    conn.commit()
    return True


# -- Audit helper -----------------------------------------------------------

def _log_audit(
    conn,
    user_id: int | None,
    action: str,
    details: dict,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Insert a row into audit_log."""
    import json
    conn.execute(
        "INSERT INTO audit_log (user_id, action, details, ip_address, user_agent) "
        "VALUES (%(uid)s, %(action)s, %(details)s, %(ip)s, %(ua)s)",
        {
            "uid": user_id,
            "action": action,
            "details": json.dumps(details),
            "ip": (ip_address or "")[:45] or None,
            "ua": (user_agent or "")[:500] or None,
        },
    )
