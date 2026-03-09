"""Tests for TOTP two-factor authentication.

Covers:
- TOTP service module (pure Python, no DB needed)
  - Secret generation, URI format, QR code data URI
  - TOTP verification (current step, clock skew, invalid code, empty inputs)
  - Backup codes: format, uniqueness, hash+verify roundtrip, consumption
- 2FA endpoints (Flask test client + mocks)
  - POST /api/v1/account/2fa/setup
  - POST /api/v1/account/2fa/confirm
  - POST /api/v1/account/2fa/disable
  - POST /api/v1/account/2fa/backup-codes
- 2FA login flow (Flask test client + mocks)
  - Login with 2FA → temp_token
  - POST /auth/2fa/verify with TOTP code
  - POST /auth/2fa/verify with backup code (single-use)
"""
import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===================================================================
# Part 1: TOTP Service Tests (pure Python, no mocks needed)
# ===================================================================

class TestGenerateSecret:
    def test_secret_is_base32_32_chars(self):
        """Secret should be base32-encoded, 32 chars (20 bytes)."""
        from auth.totp import generate_totp_secret
        secret = generate_totp_secret()
        assert len(secret) == 32
        decoded = base64.b32decode(secret)
        assert len(decoded) == 20

    def test_secrets_are_unique(self):
        """Each call should produce a different secret."""
        from auth.totp import generate_totp_secret
        secrets_set = {generate_totp_secret() for _ in range(20)}
        assert len(secrets_set) == 20


class TestGenerateUri:
    def test_uri_format(self):
        """URI should be valid otpauth:// format with all parameters."""
        from auth.totp import generate_totp_uri
        uri = generate_totp_uri("JBSWY3DPEHPK3PXP", "user@example.com")
        assert uri.startswith("otpauth://totp/")
        assert "secret=JBSWY3DPEHPK3PXP" in uri
        assert "issuer=LAP" in uri
        assert "digits=6" in uri
        assert "period=30" in uri
        assert "user%40example.com" in uri

    def test_uri_contains_issuer_label(self):
        """URI label should include issuer:email."""
        from auth.totp import generate_totp_uri
        uri = generate_totp_uri("AAAA", "bob@test.com")
        assert "LAP%20Coach" in uri
        assert "bob%40test.com" in uri


class TestQrCodeGeneration:
    def test_qr_data_uri_starts_with_png_prefix(self):
        """QR code should be a PNG data URI."""
        from auth.totp import generate_qr_data_uri
        uri = generate_qr_data_uri("otpauth://totp/Test:test@test.com?secret=ABC")
        if uri is None:
            pytest.skip("qrcode library not available")
        assert uri.startswith("data:image/png;base64,")

    def test_qr_data_uri_is_valid_base64(self):
        """The base64 portion should be decodable."""
        from auth.totp import generate_qr_data_uri
        uri = generate_qr_data_uri("otpauth://totp/Test:x@y.com?secret=ZZZ")
        if uri is None:
            pytest.skip("qrcode library not available")
        b64_part = uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        # PNG magic bytes
        assert decoded[:4] == b"\x89PNG"


class TestVerifyTotp:
    def test_current_step_accepted(self):
        """Code for the current time step should verify."""
        from auth.totp import _current_counter, _hotp, generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        counter = _current_counter()
        code = _hotp(secret, counter)
        assert verify_totp(secret, code)

    def test_previous_step_accepted(self):
        """Code for previous time step (clock skew) should verify."""
        from auth.totp import _current_counter, _hotp, generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        counter = _current_counter()
        code = _hotp(secret, counter - 1)
        assert verify_totp(secret, code)

    def test_next_step_accepted(self):
        """Code for next time step (clock skew) should verify."""
        from auth.totp import _current_counter, _hotp, generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        counter = _current_counter()
        code = _hotp(secret, counter + 1)
        assert verify_totp(secret, code)

    def test_old_step_rejected(self):
        """Code for 2 steps ago should be rejected."""
        from auth.totp import _current_counter, _hotp, generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        counter = _current_counter()
        code = _hotp(secret, counter - 2)
        assert not verify_totp(secret, code)

    def test_invalid_code_rejected(self):
        """Arbitrary code should be rejected."""
        from auth.totp import generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        assert not verify_totp(secret, "000000")

    def test_empty_secret_returns_false(self):
        """Empty secret should return False."""
        from auth.totp import verify_totp
        assert not verify_totp("", "123456")

    def test_empty_code_returns_false(self):
        """Empty code should return False."""
        from auth.totp import verify_totp
        assert not verify_totp("AAAA", "")

    def test_both_empty_returns_false(self):
        """Both empty should return False."""
        from auth.totp import verify_totp
        assert not verify_totp("", "")


class TestBackupCodes:
    def test_generates_10_codes(self):
        """Should generate exactly 10 backup codes."""
        from auth.totp import generate_backup_codes
        codes = generate_backup_codes()
        assert len(codes) == 10

    def test_codes_are_unique(self):
        """All 10 codes should be distinct."""
        from auth.totp import generate_backup_codes
        codes = generate_backup_codes()
        assert len(set(codes)) == 10

    def test_code_format_xxxx_xxxx(self):
        """Each code should be in xxxx-xxxx hex format."""
        from auth.totp import generate_backup_codes
        codes = generate_backup_codes()
        for code in codes:
            assert len(code) == 9  # 4 + 1 (hyphen) + 4
            assert code[4] == "-"
            # Both halves should be valid hex
            int(code[:4], 16)
            int(code[5:], 16)

    def test_hash_verify_roundtrip(self):
        """Hashing then verifying the same code returns the correct index."""
        from auth.totp import generate_backup_codes, hash_backup_code, verify_backup_code
        codes = generate_backup_codes()
        hashed = [hash_backup_code(c) for c in codes]
        # Verify each code
        for i, code in enumerate(codes):
            idx = verify_backup_code(code, hashed)
            assert idx == i

    def test_hash_is_case_insensitive(self):
        """Upper/lower case should produce same hash (normalisation)."""
        from auth.totp import hash_backup_code
        h1 = hash_backup_code("abcd-ef01")
        h2 = hash_backup_code("ABCD-EF01")
        assert h1 == h2

    def test_invalid_code_returns_none(self):
        """Invalid backup code should return None."""
        from auth.totp import hash_backup_code, verify_backup_code
        hashed = [hash_backup_code("abcd-1234")]
        assert verify_backup_code("wrong-code", hashed) is None

    def test_empty_list_returns_none(self):
        """Verifying against empty list should return None."""
        from auth.totp import verify_backup_code
        assert verify_backup_code("abcd-1234", []) is None


# ===================================================================
# Part 2: 2FA Endpoint Tests (Flask test client + mocks)
# ===================================================================

from flask import Flask, g

from web.api_utils import init_request_id
from web.routes.api_v1_account import bp as api_v1_account_bp


def _make_account_app():
    """Minimal Flask app with api_v1_account blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_v1_account_bp)

    @app.before_request
    def _inject_user():
        g.user_id = 42
        g.current_user_id = 42
        g.current_user_id = 42
        g.workspace_id = "ws_001"

    return app


@pytest.fixture
def account_app():
    return _make_account_app()


@pytest.fixture
def account_client(account_app):
    return account_app.test_client()


def _mock_conn():
    """Create a mock DB connection."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


class TestSetup2FA:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_setup_returns_secret_and_uri(self, mock_db, account_client):
        """POST /2fa/setup returns secret + provisioning_uri."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        resp = account_client.post("/api/v1/account/2fa/setup")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "secret" in data
        assert "provisioning_uri" in data
        assert data["provisioning_uri"].startswith("otpauth://totp/")
        assert "user%40test.com" in data["provisioning_uri"]

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_setup_includes_qr_code(self, mock_db, account_client):
        """POST /2fa/setup returns qr_code if qrcode lib available."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        resp = account_client.post("/api/v1/account/2fa/setup")
        data = resp.get_json()["data"]
        # qrcode is installed, so qr_code should be present
        if "qr_code" in data:
            assert data["qr_code"].startswith("data:image/png;base64,")

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_setup_409_when_already_enabled(self, mock_db, account_client):
        """POST /2fa/setup returns 409 if 2FA already enabled."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_enabled": True,
        }
        mock_db.return_value = conn

        resp = account_client.post("/api/v1/account/2fa/setup")
        assert resp.status_code == 409

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_setup_stores_secret_in_db(self, mock_db, account_client):
        """POST /2fa/setup writes totp_secret to users table."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        account_client.post("/api/v1/account/2fa/setup")

        # Check that UPDATE users SET totp_secret was called
        # call_args_list entries have positional args; first arg is text()
        sql_strs = [str(c[0][0]) for c in conn.execute.call_args_list]
        assert any("totp_secret" in s for s in sql_strs)
        assert conn.commit.called


class TestConfirm2FA:
    @patch("auth.totp.verify_totp", return_value=True)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_confirm_returns_backup_codes(self, mock_db, mock_verify, account_client):
        """POST /2fa/confirm returns backup codes on success."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_secret": "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567",
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/confirm",
            json={"code": "123456"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["enabled"] is True
        assert len(data["backup_codes"]) == 10
        # Check xxxx-xxxx format
        for code in data["backup_codes"]:
            assert "-" in code

    @patch("auth.totp.verify_totp", return_value=False)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_confirm_rejects_invalid_code(self, mock_db, mock_verify, account_client):
        """POST /2fa/confirm returns 401 for invalid TOTP code."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_secret": "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567",
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/confirm",
            json={"code": "000000"},
        )
        assert resp.status_code == 401

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_confirm_409_when_already_enabled(self, mock_db, account_client):
        """POST /2fa/confirm returns 409 if 2FA already enabled."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_secret": "SECRET",
            "totp_enabled": True,
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/confirm",
            json={"code": "123456"},
        )
        assert resp.status_code == 409

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_confirm_400_without_setup(self, mock_db, account_client):
        """POST /2fa/confirm returns 400 if setup not called."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_secret": None,
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/confirm",
            json={"code": "123456"},
        )
        assert resp.status_code == 400

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_confirm_400_missing_code(self, mock_db, account_client):
        """POST /2fa/confirm returns 400 if code missing."""
        conn = _mock_conn()
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/confirm",
            json={},
        )
        assert resp.status_code == 400

    @patch("auth.totp.verify_totp", return_value=True)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_confirm_sends_email(self, mock_db, mock_verify, account_client):
        """POST /2fa/confirm sends 2FA-enabled email."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "totp_secret": "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567",
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        with patch("auth.email.send_2fa_enabled_email") as mock_email:
            mock_email.return_value = True
            resp = account_client.post(
                "/api/v1/account/2fa/confirm",
                json={"code": "123456"},
            )
            assert resp.status_code == 200
            mock_email.assert_called_once_with("user@test.com")


class TestDisable2FA:
    @patch("auth.service.verify_password", return_value=True)
    @patch("auth.totp.verify_totp", return_value=True)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_disable_with_totp_code(self, mock_db, mock_verify_totp, mock_verify_pw, account_client):
        """POST /2fa/disable with valid password + TOTP code returns success."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "password_hash": "$argon2id$...",
            "totp_secret": "SECRET",
            "totp_enabled": True,
            "totp_backup_codes": "[]",
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/disable",
            json={"password": "mypassword", "code": "123456"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["disabled"] is True

    @patch("auth.service.verify_password", return_value=True)
    @patch("auth.totp.verify_totp", return_value=False)
    @patch("auth.totp.verify_backup_code", return_value=0)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_disable_with_backup_code(self, mock_db, mock_backup, mock_totp, mock_pw, account_client):
        """POST /2fa/disable accepts backup code when TOTP fails."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "password_hash": "$argon2id$...",
            "totp_secret": "SECRET",
            "totp_enabled": True,
            "totp_backup_codes": json.dumps(["hash1"]),
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/disable",
            json={"password": "mypassword", "code": "abcd-1234"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["disabled"] is True

    @patch("auth.service.verify_password", return_value=False)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_disable_rejects_wrong_password(self, mock_db, mock_pw, account_client):
        """POST /2fa/disable returns 401 for wrong password."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "password_hash": "$argon2id$...",
            "totp_secret": "SECRET",
            "totp_enabled": True,
            "totp_backup_codes": "[]",
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/disable",
            json={"password": "wrong", "code": "123456"},
        )
        assert resp.status_code == 401

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_disable_409_when_not_enabled(self, mock_db, account_client):
        """POST /2fa/disable returns 409 if 2FA is not enabled."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "password_hash": "$argon2id$...",
            "totp_secret": None,
            "totp_enabled": False,
            "totp_backup_codes": "[]",
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/disable",
            json={"password": "mypassword", "code": "123456"},
        )
        assert resp.status_code == 409

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_disable_400_missing_fields(self, mock_db, account_client):
        """POST /2fa/disable returns 400 if password or code missing."""
        conn = _mock_conn()
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/disable",
            json={"password": "mypassword"},
        )
        assert resp.status_code == 400

    @patch("auth.service.verify_password", return_value=True)
    @patch("auth.totp.verify_totp", return_value=True)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_disable_sends_email(self, mock_db, mock_totp, mock_pw, account_client):
        """POST /2fa/disable sends 2FA-disabled email."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "password_hash": "$argon2id$...",
            "totp_secret": "SECRET",
            "totp_enabled": True,
            "totp_backup_codes": "[]",
        }
        mock_db.return_value = conn

        with patch("auth.email.send_2fa_disabled_email") as mock_email:
            mock_email.return_value = True
            resp = account_client.post(
                "/api/v1/account/2fa/disable",
                json={"password": "mypassword", "code": "123456"},
            )
            assert resp.status_code == 200
            mock_email.assert_called_once_with("user@test.com")


class TestRegenerateBackupCodes:
    @patch("auth.service.verify_password", return_value=True)
    @patch("auth.totp.verify_totp", return_value=True)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_regenerate_returns_new_codes(self, mock_db, mock_totp, mock_pw, account_client):
        """POST /2fa/backup-codes returns 10 new backup codes."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "password_hash": "$argon2id$...",
            "totp_secret": "SECRET",
            "totp_enabled": True,
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/backup-codes",
            json={"password": "mypassword", "code": "123456"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert len(data["backup_codes"]) == 10
        for code in data["backup_codes"]:
            assert "-" in code

    @patch("auth.service.verify_password", return_value=False)
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_regenerate_rejects_wrong_password(self, mock_db, mock_pw, account_client):
        """POST /2fa/backup-codes returns 401 for wrong password."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "password_hash": "$argon2id$...",
            "totp_secret": "SECRET",
            "totp_enabled": True,
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/backup-codes",
            json={"password": "wrong", "code": "123456"},
        )
        assert resp.status_code == 401

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_regenerate_409_when_not_enabled(self, mock_db, account_client):
        """POST /2fa/backup-codes returns 409 if 2FA not enabled."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "password_hash": "$argon2id$...",
            "totp_secret": None,
            "totp_enabled": False,
        }
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/2fa/backup-codes",
            json={"password": "mypassword", "code": "123456"},
        )
        assert resp.status_code == 409


# ===================================================================
# Part 3: 2FA Login Flow Tests (service layer)
# ===================================================================

class FakeConn:
    """Minimal fake DB connection for service-layer tests."""
    def __init__(self, rows_by_query=None):
        self._rows_by_query = rows_by_query or {}
        self._calls = []
        self._committed = False

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        cur = MagicMock()
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


class TestLoginWith2FA:
    def test_login_returns_requires_2fa(self):
        """login_user with 2FA enabled returns requires_2fa + temp_token."""
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
        assert "refresh_token" not in result

    def test_login_without_2fa_returns_tokens(self):
        """login_user without 2FA returns access + refresh tokens."""
        from auth.service import hash_password, login_user
        pw_hash = hash_password("password123")
        conn = FakeConn({
            "SELECT id, email, password_hash, display_name, totp_enabled": [{
                "id": 1,
                "email": "user@test.com",
                "password_hash": pw_hash,
                "display_name": "Test",
                "totp_enabled": False,
            }],
        })
        result = login_user(conn, "user@test.com", "password123", "test-secret")
        assert "requires_2fa" not in result
        assert "access_token" in result
        assert "refresh_token" in result

    def test_temp_token_roundtrip(self):
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

    def test_complete_2fa_login_issues_tokens(self):
        """complete_2fa_login returns access + refresh tokens."""
        from auth.service import complete_2fa_login
        conn = FakeConn({
            "SELECT id, email, display_name": [{
                "id": 42,
                "email": "user@test.com",
                "display_name": "Test",
            }],
        })
        result = complete_2fa_login(conn, 42, "test-secret")
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"]["id"] == 42


# ===================================================================
# Part 4: 2FA Verify Endpoint Tests (Flask test client)
# ===================================================================

from web.routes.auth import bp as auth_bp


def _make_auth_app():
    """Minimal Flask app with auth blueprint for 2FA verify endpoint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["JWT_SECRET"] = "test-jwt-secret"
    init_request_id(app)
    app.register_blueprint(auth_bp)
    return app


@pytest.fixture
def auth_app():
    return _make_auth_app()


@pytest.fixture
def auth_client(auth_app):
    return auth_app.test_client()


class TestVerify2FAEndpoint:
    @patch("web.routes.auth._get_conn")
    def test_verify_with_valid_totp(self, mock_get_conn, auth_client):
        """POST /auth/2fa/verify with valid TOTP code returns tokens."""
        from auth.service import _create_temp_2fa_token

        conn = FakeConn({
            "SELECT totp_secret, totp_backup_codes": [{
                "totp_secret": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
                "totp_backup_codes": "[]",
            }],
            "SELECT id, email, display_name": [{
                "id": 99,
                "email": "user@test.com",
                "display_name": "Test",
            }],
        })
        mock_get_conn.return_value = conn

        temp_token = _create_temp_2fa_token(99, "test-jwt-secret")

        with patch("auth.totp.verify_totp", return_value=True):
            resp = auth_client.post(
                "/auth/2fa/verify",
                json={"temp_token": temp_token, "totp_code": "123456"},
            )
            assert resp.status_code == 200
            data = resp.get_json()["data"]
            assert "access_token" in data
            assert "refresh_token" in data

    @patch("web.routes.auth._get_conn")
    def test_verify_with_backup_code(self, mock_get_conn, auth_client):
        """POST /auth/2fa/verify with valid backup code returns tokens and consumes code."""
        from auth.service import _create_temp_2fa_token
        from auth.totp import generate_backup_codes, hash_backup_code

        codes = generate_backup_codes()
        hashed = [hash_backup_code(c) for c in codes]

        conn = FakeConn({
            "SELECT totp_secret, totp_backup_codes": [{
                "totp_secret": "SECRET",
                "totp_backup_codes": json.dumps(hashed),
            }],
            "SELECT id, email, display_name": [{
                "id": 99,
                "email": "user@test.com",
                "display_name": "Test",
            }],
        })
        mock_get_conn.return_value = conn

        temp_token = _create_temp_2fa_token(99, "test-jwt-secret")

        resp = auth_client.post(
            "/auth/2fa/verify",
            json={"temp_token": temp_token, "backup_code": codes[3]},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "access_token" in data

        # Verify backup code was consumed (UPDATE called)
        sql_calls = [str(c[0]) for c in conn._calls]
        assert any("UPDATE users SET totp_backup_codes" in s for s in sql_calls)

    @patch("web.routes.auth._get_conn")
    def test_verify_rejects_invalid_totp(self, mock_get_conn, auth_client):
        """POST /auth/2fa/verify with invalid TOTP returns 401."""
        from auth.service import _create_temp_2fa_token

        conn = FakeConn({
            "SELECT totp_secret, totp_backup_codes": [{
                "totp_secret": "SECRET",
                "totp_backup_codes": "[]",
            }],
        })
        mock_get_conn.return_value = conn

        temp_token = _create_temp_2fa_token(99, "test-jwt-secret")

        with patch("auth.totp.verify_totp", return_value=False):
            resp = auth_client.post(
                "/auth/2fa/verify",
                json={"temp_token": temp_token, "totp_code": "000000"},
            )
            assert resp.status_code == 401

    def test_verify_rejects_missing_temp_token(self, auth_client):
        """POST /auth/2fa/verify without temp_token returns 400."""
        resp = auth_client.post(
            "/auth/2fa/verify",
            json={"totp_code": "123456"},
        )
        assert resp.status_code == 400

    def test_verify_rejects_missing_code(self, auth_client):
        """POST /auth/2fa/verify without code returns 400."""
        resp = auth_client.post(
            "/auth/2fa/verify",
            json={"temp_token": "some-token"},
        )
        assert resp.status_code == 400

    def test_verify_rejects_expired_temp_token(self, auth_client):
        """POST /auth/2fa/verify with expired temp token returns 401."""
        from datetime import datetime, timedelta, timezone

        import jwt

        expired_payload = {
            "user_id": 99,
            "type": "2fa_temp",
            "iat": datetime.now(timezone.utc) - timedelta(minutes=10),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
        expired_token = jwt.encode(expired_payload, "test-jwt-secret", algorithm="HS256")

        with patch("web.routes.auth._get_conn"):
            resp = auth_client.post(
                "/auth/2fa/verify",
                json={"temp_token": expired_token, "totp_code": "123456"},
            )
            assert resp.status_code == 401
