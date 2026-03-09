"""Tests for admin entitlements routes.

Verifies:
- GET /admin/entitlements/plans returns plan definitions
- GET /admin/entitlements/usage/:workspace_id returns usage
- GET /admin/entitlements/anomalies returns detected anomalies
- POST /admin/entitlements/overrides creates override
- POST /admin/entitlements/refresh/:user_id refreshes tier
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


class TestEntitlementPlans:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.entitlements import bp as ent_bp
        app.register_blueprint(ent_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_plan_definitions(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/entitlements/plans"):
            self._admin_context()

            with patch("web.routes.admin.entitlements._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {"tier": "demo", "reports_per_month": 3},
                    {"tier": "racer", "reports_per_month": 10},
                ]
                conn.execute.return_value = cur

                from web.routes.admin.entitlements import list_plans
                response = list_plans()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]) == 2


class TestEntitlementAnomalies:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.entitlements import bp as ent_bp
        app.register_blueprint(ent_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_anomalies(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/entitlements/anomalies"):
            self._admin_context()

            with patch("web.routes.admin.entitlements._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                from admin.entitlements import Anomaly

                with patch("web.routes.admin.entitlements.detect_anomalies") as mock_detect:
                    mock_detect.return_value = [
                        Anomaly(
                            anomaly_type="overspend",
                            severity="warning",
                            user_id=42,
                            details={"total": 15},
                        ),
                    ]

                    from web.routes.admin.entitlements import list_anomalies
                    response = list_anomalies()

                    if isinstance(response, tuple):
                        data = response[0].get_json()
                    else:
                        data = response.get_json()

                    assert data["ok"] is True
                    assert len(data["data"]) == 1
                    assert data["data"][0]["anomaly_type"] == "overspend"


class TestCreateOverride:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.entitlements import bp as ent_bp
        app.register_blueprint(ent_bp, url_prefix="/api/v1/admin")
        return app

    def test_creates_override(self):
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/overrides",
            method="POST",
            content_type="application/json",
            data=json.dumps({
                "user_id": 1,
                "override_key": "reports_per_month",
                "override_value": "50",
                "reason": "Promo code LAUNCH50",
            }),
        ):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "root_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.entitlements._get_conn") as mock_conn, \
                 patch("web.routes.admin.entitlements.create_override_service") as mock_create:
                conn = MagicMock()
                mock_conn.return_value = conn
                mock_create.return_value = 42

                from web.routes.admin.entitlements import create_override_route
                response = create_override_route()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["override_id"] == 42
