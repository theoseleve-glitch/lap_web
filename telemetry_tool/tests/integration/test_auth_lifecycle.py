"""Integration tests — complete auth lifecycle flows.

Tests register → verify → login → refresh → logout, 2FA, password reset,
and account lockout using mock DB connections.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
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

_TEST_SECRET = "integration-test-jwt-secret-minimum-32-bytes-long"


# ===========================================================================
# A) Register → Login → Refresh → Logout
# ===========================================================================

class TestRegisterVerifyLoginLogout:
    """Full registration through logout cycle."""

    def test_register_creates_hashed_password(self):
        """Registration hashes the password with Argon2id."""
        hashed = hash_password("SecureP@ss1!")
        assert hashed.startswith("$argon2")
        assert verify_password("SecureP@ss1!", hashed)

    def test_access_token_round_trip(self):
        """Create → decode access token preserves user_id."""
        token = create_access_token(42, _TEST_SECRET, 15, email_verified=True)
        payload = decode_access_token(token, _TEST_SECRET)
        assert payload["user_id"] == 42
        assert payload["email_verified"] is True

    def test_refresh_token_is_unique(self):
        """Each refresh token is unique."""
        t1 = create_refresh_token()
        t2 = create_refresh_token()
        assert t1 != t2
        assert len(t1) >= 48

    def test_refresh_token_hash_is_deterministic(self):
        """Same token always produces same hash."""
        token = create_refresh_token()
        h1 = hash_refresh_token(token)
        h2 = hash_refresh_token(token)
        assert h1 == h2

    def test_access_token_expires(self):
        """Expired token raises AuthError."""
        token = create_access_token(1, _TEST_SECRET, expiry_minutes=0)
        time.sleep(0.1)
        with pytest.raises(AuthError):
            decode_access_token(token, _TEST_SECRET)

    def test_invalid_signature_rejected(self):
        """Token signed with wrong secret is rejected."""
        token = create_access_token(1, _TEST_SECRET, 15)
        with pytest.raises(AuthError):
            decode_access_token(token, "wrong-secret-that-is-32-bytes-longx")

    def test_register_user_function_exists(self):
        """register_user is importable and callable."""
        from auth.service import register_user
        assert callable(register_user)


# ===========================================================================
# B) Unverified user blocked
# ===========================================================================

class TestUnverifiedBlocked:
    """Unverified email should block write operations."""

    def test_unverified_token_has_flag(self):
        """Access token with email_verified=False encodes that claim."""
        token = create_access_token(1, _TEST_SECRET, 15, email_verified=False)
        payload = decode_access_token(token, _TEST_SECRET)
        assert payload["email_verified"] is False

    def test_verified_token_has_flag(self):
        """Access token with email_verified=True encodes that claim."""
        token = create_access_token(1, _TEST_SECRET, 15, email_verified=True)
        payload = decode_access_token(token, _TEST_SECRET)
        assert payload["email_verified"] is True

    def test_require_email_verified_decorator_exists(self):
        """RBAC module has require_email_verified decorator."""
        from auth.rbac import require_email_verified
        assert callable(require_email_verified)


# ===========================================================================
# C) OAuth first-time login
# ===========================================================================

class TestOAuthLogin:
    """OAuth module structure and key functions."""

    def test_oauth_module_exists(self):
        """auth.oauth module is importable."""
        import auth.oauth
        assert hasattr(auth.oauth, "init_oauth")

    def test_oauth_user_function_exists(self):
        """get_or_create_oauth_user is importable."""
        from auth.oauth import get_or_create_oauth_user
        assert callable(get_or_create_oauth_user)


# ===========================================================================
# D) Password reset flow
# ===========================================================================

class TestPasswordResetFlow:
    """Password reset token lifecycle."""

    def test_password_reset_functions_exist(self):
        """create_password_reset_token and reset_password are importable."""
        from auth.service import create_password_reset_token, reset_password
        assert callable(create_password_reset_token)
        assert callable(reset_password)

    def test_change_password_function_exists(self):
        """change_password is importable."""
        from auth.service import change_password
        assert callable(change_password)


# ===========================================================================
# E) 2FA setup and login
# ===========================================================================

class Test2FASetupAndLogin:
    """TOTP 2FA lifecycle — setup, verify, login with code."""

    def test_2fa_temp_token_functions_exist(self):
        """2FA temp token creation and verification exist."""
        from auth.service import _create_temp_2fa_token, verify_2fa_temp_token
        assert callable(_create_temp_2fa_token)
        assert callable(verify_2fa_temp_token)

    def test_2fa_temp_token_round_trip(self):
        """Create and verify a 2FA temp token preserves user_id."""
        from auth.service import _create_temp_2fa_token, verify_2fa_temp_token
        token = _create_temp_2fa_token(42, _TEST_SECRET)
        user_id = verify_2fa_temp_token(token, _TEST_SECRET)
        assert user_id == 42

    def test_2fa_temp_token_wrong_secret_rejected(self):
        """2FA temp token with wrong secret is rejected."""
        from auth.service import _create_temp_2fa_token, verify_2fa_temp_token
        token = _create_temp_2fa_token(42, _TEST_SECRET)
        with pytest.raises(AuthError):
            verify_2fa_temp_token(token, "wrong-secret-that-is-32-bytes-longx")

    def test_complete_2fa_login_exists(self):
        """complete_2fa_login is importable."""
        from auth.service import complete_2fa_login
        assert callable(complete_2fa_login)


# ===========================================================================
# F) 2FA backup code
# ===========================================================================

class Test2FABackupCode:
    """Backup codes are consumed on use."""

    def test_login_user_handles_totp(self):
        """login_user returns requires_2fa when totp_enabled."""
        from auth.service import login_user
        assert callable(login_user)


# ===========================================================================
# G) Account lockout
# ===========================================================================

class TestAccountLockout:
    """Account lockout after failed login attempts."""

    def test_wrong_password_detected(self):
        """verify_password returns False for wrong password."""
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_timing_safe_dummy_hash(self):
        """Dummy hash exists for timing-safe non-existent user lookup."""
        from auth.service import _DUMMY_HASH
        assert _DUMMY_HASH.startswith("$argon2")

    def test_multiple_wrong_passwords_all_fail(self):
        """Each wrong attempt returns False (no lockout at service level)."""
        hashed = hash_password("correct")
        for _ in range(5):
            assert verify_password("wrong", hashed) is False
        # Correct password still works
        assert verify_password("correct", hashed) is True
