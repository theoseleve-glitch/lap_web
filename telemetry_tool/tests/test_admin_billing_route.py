"""Tests for admin billing routes.

Verifies:
- GET /admin/billing/subscriptions returns subscription list
- GET /admin/billing/webhooks returns webhook log
- GET /admin/billing/revenue returns revenue snapshot
- GET /admin/billing/reconciliation returns mismatches
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


class TestBillingSubscriptions:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.billing import bp as billing_bp
        app.register_blueprint(billing_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "billing_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_subscription_list(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/billing/subscriptions"):
            self._admin_context()

            with patch("web.routes.admin.billing._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "id": 1, "email": "user@test.com",
                        "plan_tier": "racer",
                        "stripe_subscription_id": "sub_123",
                        "subscription_status": "active",
                        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.billing import list_subscriptions
                response = list_subscriptions()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]) == 1
                assert data["data"][0]["plan_tier"] == "racer"


class TestBillingWebhooks:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.billing import bp as billing_bp
        app.register_blueprint(billing_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "billing_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_webhook_log(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/billing/webhooks"):
            self._admin_context()

            with patch("web.routes.admin.billing._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "id": 1,
                        "stripe_event_id": "evt_123",
                        "event_type": "checkout.session.completed",
                        "processing_status": "processed",
                        "created_at": datetime(2026, 2, 28, tzinfo=timezone.utc),
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.billing import list_webhooks
                response = list_webhooks()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"][0]["stripe_event_id"] == "evt_123"


class TestBillingRevenue:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.billing import bp as billing_bp
        app.register_blueprint(billing_bp, url_prefix="/api/v1/admin")
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

    def test_returns_revenue_snapshot(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/billing/revenue"):
            self._admin_context()

            with patch("web.routes.admin.billing._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                call_count = [0]

                def mock_execute(sql, params=None):
                    cur = MagicMock()
                    key = call_count[0]
                    call_count[0] += 1
                    if key == 0:  # active subs count + tier breakdown
                        cur.fetchall.return_value = [
                            {"plan_tier": "racer", "cnt": 5},
                            {"plan_tier": "world-class", "cnt": 2},
                        ]
                    elif key == 1:  # churn
                        cur.fetchone.return_value = {"churned": 1}
                    return cur

                conn.execute.side_effect = mock_execute

                from web.routes.admin.billing import revenue_snapshot
                response = revenue_snapshot()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert "tier_breakdown" in data["data"]
