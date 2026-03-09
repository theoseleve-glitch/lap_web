"""Tests for admin infrastructure routes.

Verifies:
- GET /admin/infra/storage returns storage breakdown
- POST /admin/infra/maintenance toggles maintenance mode
- GET /admin/infra/maintenance returns maintenance status
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestInfraStorage:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.infra import bp as infra_bp
        app.register_blueprint(infra_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "sre_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_storage_breakdown(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/infra/storage"):
            self._admin_context()

            with patch("web.routes.admin.infra._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchone.return_value = {"size": 52428800}
                conn.execute.return_value = cur

                from web.routes.admin.infra import storage_breakdown
                response = storage_breakdown()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["db_size_bytes"] == 52428800


class TestMaintenanceMode:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.infra import bp as infra_bp
        app.register_blueprint(infra_bp, url_prefix="/api/v1/admin")
        return app

    def test_enable_maintenance(self):
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/infra/maintenance",
            method="POST",
            content_type="application/json",
            data=json.dumps({
                "enabled": True,
                "message": "Scheduled maintenance: upgrading database",
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

            with patch("web.routes.admin.infra._get_redis") as mock_redis:
                r = MagicMock()
                mock_redis.return_value = r

                from web.routes.admin.infra import toggle_maintenance
                response = toggle_maintenance()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                r.set.assert_called_once()

    def test_get_maintenance_status(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/infra/maintenance"):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "sre_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.infra._get_redis") as mock_redis:
                r = MagicMock()
                r.get.return_value = json.dumps({
                    "enabled": True,
                    "message": "Maintenance",
                    "started_at": "2026-02-28T12:00:00Z",
                })
                mock_redis.return_value = r

                from web.routes.admin.infra import get_maintenance_status
                response = get_maintenance_status()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["enabled"] is True
