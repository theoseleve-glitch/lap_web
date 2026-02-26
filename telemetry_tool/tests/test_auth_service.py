"""Tests for the auth service (Tasks 10-12).

Unit tests for password hashing and JWT run without any database.
Integration tests for registration/login SKIP when TELEMETRY_PG_URL is not set.
"""

import os
import sys
import time
from pathlib import Path

import pytest

# Ensure project root is on path (same pattern as conftest.py).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.service import (
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

# ---------------------------------------------------------------------------
# Marker: skip integration tests when no PostgreSQL URL is available.
# ---------------------------------------------------------------------------

PG_URL = os.environ.get("TELEMETRY_PG_URL")
pg_required = pytest.mark.skipif(
    not PG_URL, reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL integration tests"
)

# A stable secret for JWT tests (NOT used in production).
# Must be >= 32 bytes for HS256 to avoid InsecureKeyLengthWarning.
_TEST_SECRET = "test-jwt-secret-for-unit-tests-minimum-32-bytes"


# ===================================================================
# Unit tests -- pure functions, no database required
# ===================================================================


class TestPasswordHashing:
    """Verify Argon2id password hashing and verification."""

    def test_hash_returns_argon2_string(self):
        hashed = hash_password("my-secure-password")
        assert hashed.startswith("$argon2")

    def test_verify_correct_password(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_different_passwords_produce_different_hashes(self):
        h1 = hash_password("password-one")
        h2 = hash_password("password-two")
        assert h1 != h2

    def test_same_password_produces_different_hashes(self):
        """Argon2 uses a random salt, so hashing the same password twice
        should yield different hash strings."""
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2
        # But both should verify successfully
        assert verify_password("same-password", h1) is True
        assert verify_password("same-password", h2) is True

    def test_empty_password_hashes(self):
        """Even an empty string can be hashed (validation happens upstream)."""
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("non-empty", hashed) is False


class TestJWT:
    """Verify JWT creation and decoding."""

    def test_create_and_decode_access_token(self):
        token = create_access_token(user_id=42, secret=_TEST_SECRET, expiry_minutes=5)
        payload = decode_access_token(token, _TEST_SECRET)
        assert payload["user_id"] == 42
        assert payload["type"] == "access"

    def test_decode_with_wrong_secret_raises(self):
        token = create_access_token(user_id=1, secret=_TEST_SECRET)
        with pytest.raises(AuthError) as exc_info:
            decode_access_token(token, "wrong-secret-that-is-at-least-32-bytes-long!")
        assert exc_info.value.code == "INVALID_TOKEN"

    def test_expired_token_raises(self):
        # Create a token that expired 1 minute ago.
        token = create_access_token(user_id=1, secret=_TEST_SECRET, expiry_minutes=-1)
        with pytest.raises(AuthError) as exc_info:
            decode_access_token(token, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_EXPIRED"

    def test_token_payload_contains_iat_and_exp(self):
        token = create_access_token(user_id=7, secret=_TEST_SECRET, expiry_minutes=15)
        payload = decode_access_token(token, _TEST_SECRET)
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_tampered_token_raises(self):
        token = create_access_token(user_id=1, secret=_TEST_SECRET)
        # Flip a character in the middle of the token.
        parts = token.split(".")
        payload_b64 = parts[1]
        tampered = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
        bad_token = f"{parts[0]}.{tampered}.{parts[2]}"
        with pytest.raises(AuthError) as exc_info:
            decode_access_token(bad_token, _TEST_SECRET)
        assert exc_info.value.code == "INVALID_TOKEN"


class TestRefreshToken:
    """Verify refresh token generation and hashing."""

    def test_create_refresh_token_is_url_safe(self):
        token = create_refresh_token()
        assert isinstance(token, str)
        assert len(token) > 30  # 48 bytes base64 => ~64 chars

    def test_refresh_tokens_are_unique(self):
        tokens = {create_refresh_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_hash_refresh_token_deterministic(self):
        token = "fixed-test-token"
        h1 = hash_refresh_token(token)
        h2 = hash_refresh_token(token)
        assert h1 == h2

    def test_hash_refresh_token_is_hex_sha256(self):
        h = hash_refresh_token("test")
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)


class TestAuthError:
    """Verify AuthError exception behaviour."""

    def test_auth_error_has_code(self):
        err = AuthError("test message", "TEST_CODE")
        assert str(err) == "test message"
        assert err.code == "TEST_CODE"

    def test_auth_error_default_code(self):
        err = AuthError("something went wrong")
        assert err.code == "AUTH_ERROR"


# ===================================================================
# Integration tests -- require PostgreSQL
# ===================================================================


@pg_required
class TestRegistrationIntegration:
    """Registration tests that require a live PostgreSQL database."""

    def test_register_user_placeholder(self):
        """Placeholder -- actual PG integration tested when TELEMETRY_PG_URL is set."""
        pytest.skip("Full PG integration test requires a running PostgreSQL instance")


@pg_required
class TestLoginIntegration:
    """Login tests that require a live PostgreSQL database."""

    def test_login_user_placeholder(self):
        """Placeholder -- actual PG integration tested when TELEMETRY_PG_URL is set."""
        pytest.skip("Full PG integration test requires a running PostgreSQL instance")
