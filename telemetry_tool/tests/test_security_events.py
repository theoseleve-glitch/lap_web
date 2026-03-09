"""Tests for security event instrumentation.

Verifies that log_security_event() is called at:
- Login failure (auth/service.py)
- Login success (auth/service.py)
- Auth denied / token expired (middleware/auth.py)
- Rate limited (rate_limit.py)
- Webhook signature invalid (billing.py)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestLoginSecurityEvents:
    """Verify auth/service.py logs security events on login."""

    def test_login_failure_user_not_found(self):
        from auth.service import AuthError, login_user

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.execute.return_value = cur

        with patch("auth.service.log_security_event") as mock_log:
            with pytest.raises(AuthError, match="Invalid credentials"):
                login_user(conn, "bad@test.com", "wrong", "secret")

            mock_log.assert_called_once()
            _, kwargs = mock_log.call_args
            # auth/service.py passes (conn, event_type, **kwargs)
            args = mock_log.call_args[0]
            assert args[0] is conn
            assert args[1] == "login_failed"
            assert kwargs["details"]["email"] == "bad@test.com"

    def test_login_failure_wrong_password(self):
        from auth.service import AuthError, hash_password, login_user

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {
            "id": 1,
            "email": "user@test.com",
            "password_hash": hash_password("correct"),
            "display_name": "User",
            "totp_enabled": False,
        }
        conn.execute.return_value = cur

        with patch("auth.service.log_security_event") as mock_log:
            with pytest.raises(AuthError, match="Invalid credentials"):
                login_user(conn, "user@test.com", "wrong", "secret")

            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[1] == "login_failed"

    def test_login_success_logs_event(self):
        from auth.service import hash_password, login_user

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {
            "id": 1,
            "email": "user@test.com",
            "password_hash": hash_password("correct"),
            "display_name": "User",
            "totp_enabled": False,
            "email_verified": True,
        }
        conn.execute.return_value = cur

        with patch("auth.service.log_security_event") as mock_log:
            result = login_user(
                conn, "user@test.com", "correct",
                "test-secret-key-1234567890123456",
                ip_address="1.2.3.4",
            )

            assert result["access_token"]
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[1] == "login_success"
            assert mock_log.call_args[1]["ip_address"] == "1.2.3.4"

    def test_security_event_failure_doesnt_break_login(self):
        """Security logging must never break the main flow."""
        from auth.service import hash_password, login_user

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {
            "id": 1,
            "email": "user@test.com",
            "password_hash": hash_password("correct"),
            "display_name": "User",
            "totp_enabled": False,
            "email_verified": True,
        }
        conn.execute.return_value = cur

        # Patch the inner import so the wrapper catches the error
        with patch("admin.audit.log_security_event", side_effect=Exception("DB down")):
            result = login_user(
                conn, "user@test.com", "correct",
                "test-secret-key-1234567890123456",
            )
            assert result["access_token"]


class TestAuthMiddlewareSecurityEvents:
    """Verify middleware/auth.py logs security events."""

    def _make_app(self):
        from flask import Flask

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["JWT_SECRET"] = "test-secret-key-1234567890123456"
        return app

    def test_missing_token_logs_auth_denied(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/sessions", headers={}):
            with patch("web.middleware.auth.log_security_event") as mock_log:
                from web.middleware.auth import auth_middleware

                result = auth_middleware()

                assert result is not None
                mock_log.assert_called_once()
                # Middleware uses (event_type, **kwargs) — no conn
                args = mock_log.call_args[0]
                assert args[0] == "auth_denied"

    def test_expired_token_logs_event(self):
        from datetime import datetime, timedelta, timezone

        import jwt as pyjwt

        app = self._make_app()
        secret = "test-secret-key-1234567890123456"

        expired_payload = {
            "user_id": 1,
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = pyjwt.encode(expired_payload, secret, algorithm="HS256")

        with app.test_request_context(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {expired_token}"},
        ):
            with patch("web.middleware.auth.log_security_event") as mock_log:
                from web.middleware.auth import auth_middleware

                result = auth_middleware()

                assert result is not None
                mock_log.assert_called_once()
                args = mock_log.call_args[0]
                assert args[0] == "token_expired"


class TestRateLimitSecurityEvents:
    """Verify rate_limit.py logs security events when rate limited."""

    def test_rate_limited_logs_event(self):
        from flask import Flask, g

        app = Flask(__name__)

        mock_redis = MagicMock()
        mock_redis.eval.return_value = 21  # > auth tier limit of 20

        with patch("web.rate_limit.log_security_event") as mock_log:
            with patch("web.rate_limit.get_redis", return_value=mock_redis):
                from web.rate_limit import rate_limit

                @rate_limit(tier="auth")
                def dummy_endpoint():
                    return "ok"

                with app.test_request_context("/test"):
                    resp = dummy_endpoint()

                    mock_log.assert_called_once()
                    args = mock_log.call_args[0]
                    assert args[0] == "rate_limited"


class TestWebhookSecurityEvents:
    """Verify billing.py logs security events on invalid webhook signature."""

    def test_invalid_signature_logs_event(self):
        from flask import Flask

        app = Flask(__name__)
        app.config["TESTING"] = True

        with patch.dict("os.environ", {
            "STRIPE_SECRET_KEY": "sk_test_123",
            "STRIPE_WEBHOOK_SECRET": "whsec_test_123",
        }):
            import importlib

            import web.routes.billing as billing_mod
            importlib.reload(billing_mod)

            mock_stripe = MagicMock()
            mock_stripe.error = type("error", (), {
                "SignatureVerificationError": type(
                    "SignatureVerificationError", (Exception,), {}
                ),
            })()
            mock_stripe.Webhook.construct_event.side_effect = (
                mock_stripe.error.SignatureVerificationError("bad sig")
            )

            with patch.object(billing_mod, "stripe", mock_stripe):
                with patch.object(billing_mod, "STRIPE_SECRET_KEY", "sk_test_123"):
                    with patch.object(billing_mod, "STRIPE_WEBHOOK_SECRET", "whsec_test_123"):
                        with app.test_request_context(
                            "/api/v1/billing/webhook",
                            method="POST",
                            data=b"{}",
                            headers={"Stripe-Signature": "bad"},
                        ):
                            with patch.object(billing_mod, "log_security_event") as mock_log:
                                resp = billing_mod.stripe_webhook()

                                mock_log.assert_called_once()
                                args = mock_log.call_args[0]
                                assert args[0] == "webhook_signature_invalid"
