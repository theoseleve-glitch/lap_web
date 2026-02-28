"""Tests for admin security routes.

Verifies:
- GET /admin/security/events returns security events
- GET /admin/security/audit-log returns audit log
- GET /admin/security/auth-failures returns auth failure aggregation
- POST /admin/incidents creates incident note
- GET /admin/incidents lists incidents
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


class TestSecurityEvents:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.security import bp as sec_bp
        app.register_blueprint(sec_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self, role="root_admin"):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": role,
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_security_events(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/security/events"):
            self._admin_context()

            with patch("web.routes.admin.security._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "id": 1,
                        "event_type": "login_failed",
                        "user_id": 42,
                        "ip_address": "1.2.3.4",
                        "severity": "warning",
                        "created_at": datetime(2026, 2, 28, tzinfo=timezone.utc),
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.security import list_security_events
                response = list_security_events()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]) == 1

    def test_returns_audit_log(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/security/audit-log"):
            self._admin_context("auditor")

            with patch("web.routes.admin.security._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "id": 1,
                        "admin_user_id": 99,
                        "action": "sessions_invalidated",
                        "target_type": "user",
                        "target_id": "42",
                        "created_at": datetime(2026, 2, 28, tzinfo=timezone.utc),
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.security import list_audit_log
                response = list_audit_log()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True

    def test_returns_auth_failures(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/security/auth-failures"):
            self._admin_context()

            with patch("web.routes.admin.security._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                call_count = [0]

                def mock_execute(sql, params=None):
                    cur = MagicMock()
                    key = call_count[0]
                    call_count[0] += 1
                    if key == 0:  # top IPs
                        cur.fetchall.return_value = [
                            {"ip_address": "1.2.3.4", "cnt": 10},
                        ]
                    elif key == 1:  # top users
                        cur.fetchall.return_value = [
                            {"user_id": 42, "cnt": 5},
                        ]
                    return cur

                conn.execute.side_effect = mock_execute

                from web.routes.admin.security import auth_failures
                response = auth_failures()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert "top_ips" in data["data"]


class TestIncidents:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.security import bp as sec_bp
        app.register_blueprint(sec_bp, url_prefix="/api/v1/admin")
        return app

    def test_creates_incident(self):
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/incidents",
            method="POST",
            content_type="application/json",
            data=json.dumps({
                "title": "Payment processing down",
                "body": "Stripe webhook failures spiking",
                "severity": "p1",
            }),
        ):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "sre_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.security._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchone.return_value = {"id": 1}
                conn.execute.return_value = cur

                from web.routes.admin.security import create_incident
                response = create_incident()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["incident_id"] == 1

    def test_lists_incidents(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/incidents"):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "sre_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.security._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "id": 1,
                        "title": "Test incident",
                        "severity": "p2",
                        "status": "open",
                        "created_at": datetime(2026, 2, 28, tzinfo=timezone.utc),
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.security import list_incidents
                response = list_incidents()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]) == 1
