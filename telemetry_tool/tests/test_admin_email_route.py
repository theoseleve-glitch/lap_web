"""Tests for admin email routes.

Verifies:
- GET /admin/email/stats returns delivery statistics
- POST /admin/email/resend-verification/:user_id triggers resend
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestEmailStats:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.email import bp as email_bp
        app.register_blueprint(email_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "support_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_delivery_stats(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/email/stats"):
            self._admin_context()

            with patch("web.routes.admin.email._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                # Mock: count emails from email_verification table
                call_count = [0]

                def mock_execute(sql, params=None):
                    cur = MagicMock()
                    key = call_count[0]
                    call_count[0] += 1
                    if key == 0:
                        cur.fetchone.return_value = {
                            "total_sent": 50,
                            "verified": 42,
                        }
                    return cur

                conn.execute.side_effect = mock_execute

                from web.routes.admin.email import email_stats
                response = email_stats()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["total_sent"] == 50


class TestResendVerification:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.email import bp as email_bp
        app.register_blueprint(email_bp, url_prefix="/api/v1/admin")
        return app

    def test_triggers_resend(self):
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/email/resend-verification/1",
            method="POST",
            content_type="application/json",
            data=json.dumps({"reason": "User requested"}),
        ):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "support_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.email._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                # User exists
                cur = MagicMock()
                cur.fetchone.return_value = {
                    "id": 1, "email": "user@test.com",
                    "email_verified": False,
                }
                conn.execute.return_value = cur

                from web.routes.admin.email import resend_verification
                response = resend_verification(1)

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
