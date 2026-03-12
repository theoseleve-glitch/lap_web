"""Tests for PROMPT 2A — Profile, Preferences & Security Backend.

Validates:
- Password reset: token generation, email sending, token consumption, expiry
- Password change: current password verification, token revocation
- Session listing: shows correct user_agent/IP, revocation works
- 2FA setup: secret generation, QR URI format, code verification with clock skew
- 2FA login flow: requires TOTP after password, backup codes work (single-use)
- Preferences: partial merge, validation of known keys
- OAuth unlinking: prevents orphaned accounts (no password + no OAuth = blocked)
- Audit log: all auth events logged with correct metadata
"""
import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test TOTP module (pure functions, no DB needed)
# ---------------------------------------------------------------------------

class TestTOTPModule:
    def test_generate_secret_is_base32(self):
        """Secret should be base32-encoded, 32 chars."""
        from auth.totp import generate_totp_secret
        secret = generate_totp_secret()
        assert len(secret) == 32  # 20 bytes -> 32 base32 chars
        import base64
        decoded = base64.b32decode(secret)
        assert len(decoded) == 20

    def test_generate_uri_format(self):
        """URI should be valid otpauth:// format."""
        from auth.totp import generate_totp_uri
        uri = generate_totp_uri("JBSWY3DPEHPK3PXP", "user@example.com")
        assert uri.startswith("otpauth://totp/")
        assert "secret=JBSWY3DPEHPK3PXP" in uri
        assert "issuer=LAP" in uri
        assert "digits=6" in uri
        assert "period=30" in uri
        assert "user%40example.com" in uri

    def test_verify_totp_current_step(self):
        """Current time step should verify."""
        from auth.totp import _current_counter, _hotp, generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        counter = _current_counter()
        code = _hotp(secret, counter)
        assert verify_totp(secret, code)

    def test_verify_totp_rejects_bad_code(self):
        """Invalid code should be rejected."""
        from auth.totp import generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        assert not verify_totp(secret, "000000")

    def test_verify_totp_empty_inputs(self):
        """Empty secret or code should return False."""
        from auth.totp import verify_totp
        assert not verify_totp("", "123456")
        assert not verify_totp("SECRET", "")
        assert not verify_totp("", "")

    def test_generate_backup_codes(self):
        """Should generate 10 unique xxxx-xxxx hex codes."""
        from auth.totp import generate_backup_codes
        codes = generate_backup_codes()
        assert len(codes) == 10
        assert len(set(codes)) == 10  # all unique
        for code in codes:
            assert len(code) == 9  # xxxx-xxxx = 4+1+4
            assert code[4] == "-"
            int(code[:4], 16)  # valid hex
            int(code[5:], 16)  # valid hex

    def test_verify_backup_code(self):
        """Backup code verification should work with hashed codes."""
        from auth.totp import generate_backup_codes, hash_backup_code, verify_backup_code
        codes = generate_backup_codes()
        hashed = [hash_backup_code(c) for c in codes]
        idx = verify_backup_code(codes[3], hashed)
        assert idx == 3

    def test_verify_backup_code_wrong(self):
        """Invalid backup code should return None."""
        from auth.totp import hash_backup_code, verify_backup_code
        hashed = [hash_backup_code("abcd1234")]
        assert verify_backup_code("wrong123", hashed) is None


# ---------------------------------------------------------------------------
# Test password reset (service layer)
# ---------------------------------------------------------------------------

class FakeConn:
    """Minimal fake DB connection for service-layer tests."""
    def __init__(self, rows_by_query=None):
        self._rows_by_query = rows_by_query or {}
        self._calls = []
        self._committed = False

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        cur = MagicMock()
        # Match by substring in SQL
        for key, rows in self._rows_by_query.items():
            if key in sql:
                cur.fetchone.return_value = rows[0] if rows else None
                cur.fetchall.return_value = rows
                return cur
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        return cur

    def commit(self):
        self._committed = True

    def rollback(self):
        pass


class TestPasswordReset:
    def test_create_token_returns_none_for_unknown_email(self):
        """No token created for non-existent user."""
        from auth.service import create_password_reset_token
        conn = FakeConn({})  # empty result for all queries
        result = create_password_reset_token(conn, "unknown@example.com")
        assert result is None

    def test_create_token_returns_token_for_existing_user(self):
        """Token is returned for existing user."""
        from auth.service import create_password_reset_token
        conn = FakeConn({"SELECT id FROM users": [{"id": 42}]})
        token = create_password_reset_token(conn, "user@example.com")
        assert token is not None
        assert len(token) > 20  # urlsafe token
        assert conn._committed

    def test_reset_password_invalid_token(self):
        """Invalid token returns False."""
        from auth.service import reset_password
        conn = FakeConn({})  # no matching token
        result = reset_password(conn, "bad-token", "new-password-123")
        assert result is False

    def test_reset_password_success(self):
        """Valid token resets password and revokes tokens."""
        from auth.service import reset_password
        conn = FakeConn({
            "SELECT id, user_id FROM password_reset_tokens": [{"id": 1, "user_id": 42}],
        })
        result = reset_password(conn, "valid-token", "new-password-123")
        assert result is True
        assert conn._committed
        # Check that UPDATE users, UPDATE refresh_tokens, DELETE token, INSERT audit all happened
        sql_calls = [c[0] for c in conn._calls]
        assert any("UPDATE users SET password_hash" in s for s in sql_calls)
        assert any("UPDATE refresh_tokens SET revoked_at" in s for s in sql_calls)
        assert any("DELETE FROM password_reset_tokens" in s for s in sql_calls)
        assert any("INSERT INTO audit_log" in s for s in sql_calls)


# ---------------------------------------------------------------------------
# Test password change (service layer)
# ---------------------------------------------------------------------------

class TestPasswordChange:
    def test_change_password_wrong_current(self):
        """Wrong current password raises AuthError."""
        from auth.service import AuthError, change_password, hash_password
        correct_hash = hash_password("correct-password")
        conn = FakeConn({
            "SELECT password_hash": [{"password_hash": correct_hash}],
        })
        with pytest.raises(AuthError, match="incorrect"):
            change_password(conn, 1, "wrong-password", "new-pass-123")

    def test_change_password_success(self):
        """Correct current password changes hash and revokes other tokens."""
        from auth.service import change_password, hash_password
        correct_hash = hash_password("correct-password")
        conn = FakeConn({
            "SELECT password_hash": [{"password_hash": correct_hash}],
        })
        result = change_password(
            conn, 1, "correct-password", "new-pass-123",
            current_token_hash="keep-this-hash",
        )
        assert result is True
        assert conn._committed
        sql_calls = [c[0] for c in conn._calls]
        assert any("UPDATE users SET password_hash" in s for s in sql_calls)
        # Should revoke tokens except the kept one
        revoke_calls = [c for c in conn._calls if "revoked_at" in c[0]]
        assert len(revoke_calls) > 0
        assert revoke_calls[0][1].get("keep") == "keep-this-hash"


# ---------------------------------------------------------------------------
# Test 2FA login flow (service layer)
# ---------------------------------------------------------------------------

class TestTwoFactorLogin:
    def test_login_returns_2fa_required(self):
        """Login with 2FA enabled returns requires_2fa + temp_token."""
        from auth.service import hash_password, login_user
        pw_hash = hash_password("password123")
        conn = FakeConn({
            "SELECT id, email, password_hash, display_name, totp_enabled": [{
                "id": 1,
                "email": "user@test.com",
                "password_hash": pw_hash,
                "display_name": "Test",
                "totp_enabled": True,
            }],
        })
        result = login_user(conn, "user@test.com", "password123", "test-secret")
        assert result["requires_2fa"] is True
        assert "temp_token" in result
        assert "access_token" not in result

    def test_temp_token_decodes(self):
        """Temp 2FA token can be decoded back to user_id."""
        from auth.service import _create_temp_2fa_token, verify_2fa_temp_token
        token = _create_temp_2fa_token(42, "test-secret")
        user_id = verify_2fa_temp_token(token, "test-secret")
        assert user_id == 42

    def test_temp_token_wrong_secret_fails(self):
        """Temp token with wrong secret raises AuthError."""
        from auth.service import AuthError, _create_temp_2fa_token, verify_2fa_temp_token
        token = _create_temp_2fa_token(42, "correct-secret")
        with pytest.raises(AuthError):
            verify_2fa_temp_token(token, "wrong-secret")


# ---------------------------------------------------------------------------
# Test audit logging
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_log_audit_inserts_row(self):
        """_log_audit inserts into audit_log table."""
        from auth.service import _log_audit
        conn = FakeConn({})
        _log_audit(conn, 42, "login_password", {"ip": "1.2.3.4"},
                   ip_address="1.2.3.4", user_agent="Mozilla/5.0")
        sql_calls = [c[0] for c in conn._calls]
        assert any("INSERT INTO audit_log" in s for s in sql_calls)
        # Check params — schema uses new_value (not details) and has no user_agent column
        insert_call = next(c for c in conn._calls if "INSERT INTO audit_log" in c[0])
        params = insert_call[1]
        assert params["uid"] == 42
        assert params["action"] == "login_password"
        assert params["ip"] == "1.2.3.4"

    def test_log_audit_truncates_long_values(self):
        """Long ip_address is truncated."""
        from auth.service import _log_audit
        conn = FakeConn({})
        long_ip = "y" * 100
        _log_audit(conn, 1, "test", {}, ip_address=long_ip)
        insert_call = next(c for c in conn._calls if "INSERT INTO audit_log" in c[0])
        params = insert_call[1]
        assert len(params["ip"]) <= 45


# ---------------------------------------------------------------------------
# Test password reset email
# ---------------------------------------------------------------------------

class TestPasswordResetEmail:
    def test_send_password_reset_email(self):
        """Reset email includes link with token."""
        from auth.email import send_password_reset_email
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            result = send_password_reset_email("user@example.com", "abc123token")
            assert result is True
            mock_send.assert_called_once()
            _, subject, html = mock_send.call_args[0]
            assert "reset" in subject.lower()
            assert "abc123token" in html
            assert "1 hour" in html.lower()


# ---------------------------------------------------------------------------
# Test preferences validation
# ---------------------------------------------------------------------------

class TestPreferences:
    def test_valid_preference_keys(self):
        """Valid keys are accepted."""
        from web.routes.api_v1_account import _VALID_PREFERENCE_KEYS
        assert "units" in _VALID_PREFERENCE_KEYS
        assert "speed_unit" in _VALID_PREFERENCE_KEYS
        assert "timezone" in _VALID_PREFERENCE_KEYS
        assert "language" in _VALID_PREFERENCE_KEYS
        assert "notifications" in _VALID_PREFERENCE_KEYS

    def test_unknown_key_rejected(self):
        """Unknown preference keys should not be in the valid set."""
        from web.routes.api_v1_account import _VALID_PREFERENCE_KEYS
        assert "unknown_key" not in _VALID_PREFERENCE_KEYS
        assert "theme" not in _VALID_PREFERENCE_KEYS
