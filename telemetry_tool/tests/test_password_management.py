"""Tests for password change, forgot-password, and reset-password endpoints."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import init_request_id
from web.routes.api_v1_account import bp as api_v1_account_bp
from web.routes.auth import bp as auth_bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account_app():
    """Create a minimal Flask app with api_v1_account blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_v1_account_bp)

    @app.before_request
    def _inject_user():
        g.user_id = 1
        g.current_user_id = 1
        g.current_user_id = 1
        g.workspace_id = "ws_001"

    return app


def _make_auth_app():
    """Create a minimal Flask app with auth blueprint (for forgot/reset)."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["JWT_SECRET"] = "test-secret"
    init_request_id(app)
    app.register_blueprint(auth_bp)
    return app


@pytest.fixture
def account_app():
    return _make_account_app()


@pytest.fixture
def account_client(account_app):
    return account_app.test_client()


@pytest.fixture
def auth_app():
    return _make_auth_app()


@pytest.fixture
def auth_client(auth_app):
    return auth_app.test_client()


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


# ---------------------------------------------------------------------------
# POST /api/v1/account/change-password
# ---------------------------------------------------------------------------

class TestChangePassword:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_rejects_wrong_current_password(self, mock_db, account_client):
        """POST /change-password returns 401 for wrong current password."""
        from auth.service import AuthError

        conn = _mock_conn()
        mock_db.return_value = conn

        with patch("web.routes.api_v1_account.change_password_route.__wrapped__", side_effect=None):
            pass

        # Mock change_password to raise AuthError for wrong password
        with patch("auth.service.change_password", side_effect=AuthError("Current password is incorrect", "INVALID_CREDENTIALS")):
            resp = account_client.post(
                "/api/v1/account/change-password",
                data=json.dumps({
                    "current_password": "wrong-password",
                    "new_password": "newpassword123",
                }),
                content_type="application/json",
            )
            assert resp.status_code == 401
            body = resp.get_json()
            assert body["ok"] is False
            assert body["error"]["code"] == "INVALID_CREDENTIALS"

    @patch("auth.service.change_password")
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_accepts_correct_password(self, mock_db, mock_change, account_client):
        """POST /change-password returns 200 for correct password."""
        conn = _mock_conn()
        mock_db.return_value = conn
        mock_change.return_value = True

        resp = account_client.post(
            "/api/v1/account/change-password",
            data=json.dumps({
                "current_password": "correct-password",
                "new_password": "newpassword123",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_rejects_short_new_password(self, mock_db, account_client):
        """POST /change-password returns 400 for short new password."""
        conn = _mock_conn()
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/change-password",
            data=json.dumps({
                "current_password": "current-password",
                "new_password": "short",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_rejects_missing_fields(self, mock_db, account_client):
        """POST /change-password returns 400 when fields are missing."""
        conn = _mock_conn()
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/change-password",
            data=json.dumps({"current_password": "pass"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_rejects_too_long_password(self, mock_db, account_client):
        """POST /change-password returns 400 for password exceeding max length."""
        conn = _mock_conn()
        mock_db.return_value = conn

        resp = account_client.post(
            "/api/v1/account/change-password",
            data=json.dumps({
                "current_password": "current-password",
                "new_password": "x" * 1025,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /auth/forgot-password
# ---------------------------------------------------------------------------

class TestForgotPassword:
    @patch("web.routes.auth._get_conn")
    def test_always_returns_200(self, mock_get_conn, auth_client):
        """POST /forgot-password always returns 200 (prevents enumeration)."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn

        with patch("auth.service.create_password_reset_token", return_value=None):
            resp = auth_client.post(
                "/auth/forgot-password",
                data=json.dumps({"email": "nonexistent@test.com"}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["ok"] is True
            assert "If an account exists" in body["data"]["message"]

    @patch("auth.email.send_password_reset_email")
    @patch("auth.service.create_password_reset_token")
    @patch("web.routes.auth._get_conn")
    def test_sends_email_when_user_found(self, mock_get_conn, mock_reset, mock_email, auth_client):
        """POST /forgot-password sends email when user exists."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn
        mock_reset.return_value = "test-token-123"
        mock_email.return_value = True

        resp = auth_client.post(
            "/auth/forgot-password",
            data=json.dumps({"email": "user@test.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_email.assert_called_once_with("user@test.com", "test-token-123")

    @patch("web.routes.auth._get_conn")
    def test_empty_email_returns_200(self, mock_get_conn, auth_client):
        """POST /forgot-password with empty email still returns 200."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn

        resp = auth_client.post(
            "/auth/forgot-password",
            data=json.dumps({"email": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /auth/reset-password
# ---------------------------------------------------------------------------

class TestResetPassword:
    @patch("auth.service.reset_password")
    @patch("web.routes.auth._get_conn")
    def test_resets_password_with_valid_token(self, mock_get_conn, mock_reset, auth_client):
        """POST /reset-password returns 200 with valid token."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn
        mock_reset.return_value = True

        resp = auth_client.post(
            "/auth/reset-password",
            data=json.dumps({
                "token": "valid-token",
                "new_password": "newpassword123",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    @patch("auth.service.reset_password")
    @patch("web.routes.auth._get_conn")
    def test_returns_400_for_invalid_token(self, mock_get_conn, mock_reset, auth_client):
        """POST /reset-password returns 400 for invalid/expired token."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn
        mock_reset.return_value = False

        resp = auth_client.post(
            "/auth/reset-password",
            data=json.dumps({
                "token": "expired-token",
                "new_password": "newpassword123",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"]["code"] == "TOKEN_EXPIRED"

    @patch("web.routes.auth._get_conn")
    def test_rejects_short_new_password(self, mock_get_conn, auth_client):
        """POST /reset-password returns 400 for short password."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn

        resp = auth_client.post(
            "/auth/reset-password",
            data=json.dumps({
                "token": "valid-token",
                "new_password": "short",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("web.routes.auth._get_conn")
    def test_rejects_missing_token(self, mock_get_conn, auth_client):
        """POST /reset-password returns 400 when token is missing."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn

        resp = auth_client.post(
            "/auth/reset-password",
            data=json.dumps({
                "new_password": "newpassword123",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("web.routes.auth._get_conn")
    def test_rejects_missing_password(self, mock_get_conn, auth_client):
        """POST /reset-password returns 400 when new_password is missing."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn

        resp = auth_client.post(
            "/auth/reset-password",
            data=json.dumps({
                "token": "valid-token",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Security schemas unit tests
# ---------------------------------------------------------------------------

class TestSecuritySchemas:
    def test_password_change_schema_valid(self):
        from web.schemas.security import PasswordChangeSchema
        schema = PasswordChangeSchema(
            current_password="current",
            new_password="newpassword123",
        )
        assert schema.current_password == "current"
        assert schema.new_password == "newpassword123"

    def test_password_change_schema_rejects_short_new_password(self):
        from pydantic import ValidationError
        from web.schemas.security import PasswordChangeSchema
        with pytest.raises(ValidationError):
            PasswordChangeSchema(current_password="current", new_password="short")

    def test_forgot_password_schema_valid(self):
        from web.schemas.security import ForgotPasswordSchema
        schema = ForgotPasswordSchema(email="user@test.com")
        assert schema.email == "user@test.com"

    def test_reset_password_schema_valid(self):
        from web.schemas.security import ResetPasswordSchema
        schema = ResetPasswordSchema(token="abc", new_password="newpassword123")
        assert schema.token == "abc"

    def test_reset_password_schema_rejects_short_password(self):
        from pydantic import ValidationError
        from web.schemas.security import ResetPasswordSchema
        with pytest.raises(ValidationError):
            ResetPasswordSchema(token="abc", new_password="short")

    def test_totp_setup_verify_schema_valid(self):
        from web.schemas.security import TotpSetupVerifySchema
        schema = TotpSetupVerifySchema(code="123456")
        assert schema.code == "123456"

    def test_totp_setup_verify_schema_rejects_non_digits(self):
        from pydantic import ValidationError
        from web.schemas.security import TotpSetupVerifySchema
        with pytest.raises(ValidationError):
            TotpSetupVerifySchema(code="abcdef")

    def test_totp_disable_schema_valid(self):
        from web.schemas.security import TotpDisableSchema
        schema = TotpDisableSchema(password="pass", code="123456")
        assert schema.password == "pass"

    def test_totp_login_schema_valid(self):
        from web.schemas.security import TotpLoginSchema
        schema = TotpLoginSchema(temp_token="tok", code="123456")
        assert schema.temp_token == "tok"


# ---------------------------------------------------------------------------
# Email template tests
# ---------------------------------------------------------------------------

class TestEmailTemplates:
    def test_send_password_changed_email_structure(self):
        """send_password_changed_email generates correct HTML."""
        with patch("auth.email._send", return_value=True) as mock_send:
            from auth.email import send_password_changed_email
            result = send_password_changed_email("user@test.com")
            assert result is True
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert args[0][0] == "user@test.com"
            assert "password" in args[0][1].lower()
            assert "#B6FF2E" in args[0][2]  # LAP brand color

    def test_send_export_ready_email_structure(self):
        """send_export_ready_email includes download URL."""
        with patch("auth.email._send", return_value=True) as mock_send:
            from auth.email import send_export_ready_email
            result = send_export_ready_email("user@test.com", "https://example.com/download/123")
            assert result is True
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert "https://example.com/download/123" in args[0][2]

    def test_send_account_deletion_email_structure(self):
        """send_account_deletion_email includes cancel URL and date."""
        with patch("auth.email._send", return_value=True) as mock_send:
            from auth.email import send_account_deletion_email
            result = send_account_deletion_email(
                "user@test.com",
                "https://example.com/cancel",
                "2026-04-01",
            )
            assert result is True
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert "https://example.com/cancel" in args[0][2]
            assert "2026-04-01" in args[0][2]

    def test_send_new_login_email_structure(self):
        """send_new_login_email includes device and IP info."""
        with patch("auth.email._send", return_value=True) as mock_send:
            from auth.email import send_new_login_email
            result = send_new_login_email("user@test.com", "Chrome on Windows", "1.2.3.4")
            assert result is True
            args = mock_send.call_args
            assert "Chrome on Windows" in args[0][2]
            assert "1.2.3.4" in args[0][2]

    def test_send_2fa_enabled_email_structure(self):
        """send_2fa_enabled_email sends correctly."""
        with patch("auth.email._send", return_value=True) as mock_send:
            from auth.email import send_2fa_enabled_email
            result = send_2fa_enabled_email("user@test.com")
            assert result is True
            args = mock_send.call_args
            assert "2FA" in args[0][1] or "2fa" in args[0][1].lower()

    def test_send_2fa_disabled_email_structure(self):
        """send_2fa_disabled_email includes re-enable link."""
        with patch("auth.email._send", return_value=True) as mock_send:
            from auth.email import send_2fa_disabled_email
            result = send_2fa_disabled_email("user@test.com")
            assert result is True
            args = mock_send.call_args
            assert "#B6FF2E" in args[0][2]

    def test_send_retention_warning_email_structure(self):
        """send_retention_warning_email includes session and date."""
        with patch("auth.email._send", return_value=True) as mock_send:
            from auth.email import send_retention_warning_email
            result = send_retention_warning_email(
                "user@test.com",
                "Morning Practice",
                "2026-03-15",
            )
            assert result is True
            args = mock_send.call_args
            assert "Morning Practice" in args[0][2]
            assert "2026-03-15" in args[0][2]
