"""Core auth service -- registration, login, JWT, password hashing."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

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
) -> str:
    """Create a signed JWT access token for *user_id*."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
    }
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
) -> dict:
    """Authenticate a user by email/password and return access + refresh tokens."""
    cur = conn.execute(
        "SELECT id, email, password_hash, display_name "
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

    # Issue tokens
    access_token = create_access_token(user["id"], secret, access_expiry_minutes)
    refresh_token = create_refresh_token()

    # Store refresh token hash
    expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_expiry_days)
    conn.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
        "VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s)",
        {
            "user_id": user["id"],
            "token_hash": hash_refresh_token(refresh_token),
            "expires_at": expires_at,
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
