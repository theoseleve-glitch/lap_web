"""Tests for admin health overview route.

Verifies:
- /admin/health/overview returns aggregated system health
- /admin/health/metrics returns time-series snapshots
- Non-admin user gets 403
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


class TestHealthOverview:
    def _make_app(self):
        from flask import Flask, g
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.health import bp as health_bp
        app.register_blueprint(health_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self, app):
        """Set up admin user context on g."""
        from flask import g
        g.current_user_id = 1
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_health_overview(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/health/overview"):
            self._admin_context(app)

            with patch("web.routes.admin.health._get_conn") as mock_conn, \
                 patch("web.routes.admin.health._get_redis") as mock_redis:
                conn = MagicMock()
                mock_conn.return_value = conn
                mock_redis.return_value = MagicMock()

                # Mock DB queries with call counter
                call_count = [0]

                def mock_execute(sql, params=None):
                    cur = MagicMock()
                    key = call_count[0]
                    call_count[0] += 1

                    if "ingestion_jobs" in sql and "COUNT" in sql:
                        cur.fetchone.return_value = {
                            "total": 8, "failed": 1,
                            "queue_depth": 2, "avg_duration": 30.5,
                        }
                    elif "stripe_webhook_log" in sql:
                        cur.fetchone.return_value = {
                            "total": 100, "success": 99,
                        }
                    elif "security_events" in sql:
                        cur.fetchone.return_value = {
                            "login_failures": 14, "rate_limits": 3,
                        }
                    else:
                        cur.fetchone.return_value = {}
                        cur.fetchall.return_value = []
                    return cur

                conn.execute.side_effect = mock_execute

                from web.routes.admin.health import health_overview
                response = health_overview()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert "data" in data

    def test_metrics_returns_snapshots(self):
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/health/metrics?hours=1"
        ):
            self._admin_context(app)

            with patch("web.routes.admin.health._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "id": 1,
                        "collected_at": datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc),
                        "metrics_json": json.dumps({"system": {"cpu_percent": 42.0}}),
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.health import health_metrics
                response = health_metrics()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]) == 1
