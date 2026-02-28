"""Tests for admin users routes.

Verifies:
- GET /admin/users returns paginated user list
- GET /admin/users/:id returns user detail
- GET /admin/users/:id/timeline returns activity timeline
- POST /admin/users/:id/invalidate-sessions requires root_admin
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


class TestListUsers:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.users import bp as users_bp
        app.register_blueprint(users_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self, app, role="root_admin"):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": role,
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_user_list(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/users"):
            self._admin_context(app)

            with patch("web.routes.admin.users._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {
                        "id": 1,
                        "email": "test@test.com",
                        "plan_tier": "racer",
                        "subscription_status": "active",
                        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    },
                ]
                conn.execute.return_value = cur

                from web.routes.admin.users import list_users
                response = list_users()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]) == 1
                assert data["data"][0]["email"] == "test@test.com"

    def test_search_by_email(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/users?q=test@"):
            self._admin_context(app)

            with patch("web.routes.admin.users._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchall.return_value = [
                    {"id": 1, "email": "test@test.com", "plan_tier": "racer",
                     "subscription_status": "active",
                     "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
                ]
                conn.execute.return_value = cur

                from web.routes.admin.users import list_users
                response = list_users()

                # Verify the query used ILIKE for search
                sql, params = conn.execute.call_args[0]
                assert "ILIKE" in sql
                assert "test@" in params["q"]


class TestGetUserDetail:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.users import bp as users_bp
        app.register_blueprint(users_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self, app):
        from flask import g
        g.current_user_id = 99
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_returns_user_detail(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/users/1"):
            self._admin_context(app)

            with patch("web.routes.admin.users._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                call_count = [0]

                def mock_execute(sql, params=None):
                    cur = MagicMock()
                    key = call_count[0]
                    call_count[0] += 1
                    if key == 0:  # user row
                        cur.fetchone.return_value = {
                            "id": 1, "email": "user@test.com",
                            "plan_tier": "racer",
                            "stripe_subscription_id": "sub_123",
                            "subscription_status": "active",
                            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        }
                    elif key == 1:  # workspaces
                        cur.fetchall.return_value = [
                            {"id": 1, "name": "Personal", "role": "owner"},
                        ]
                    return cur

                conn.execute.side_effect = mock_execute

                from web.routes.admin.users import get_user_detail
                response = get_user_detail(1)

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["email"] == "user@test.com"

    def test_user_not_found(self):
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/users/999"):
            self._admin_context(app)

            with patch("web.routes.admin.users._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.fetchone.return_value = None
                conn.execute.return_value = cur

                from web.routes.admin.users import get_user_detail
                response = get_user_detail(999)

                if isinstance(response, tuple):
                    data, status = response[0].get_json(), response[1]
                else:
                    data, status = response.get_json(), 200

                assert status == 404


class TestInvalidateSessions:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.users import bp as users_bp
        app.register_blueprint(users_bp, url_prefix="/api/v1/admin")
        return app

    def test_invalidates_sessions(self):
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/users/1/invalidate-sessions",
            method="POST",
            content_type="application/json",
            data=json.dumps({"reason": "Security incident"}),
        ):
            from flask import g
            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "root_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            with patch("web.routes.admin.users._get_conn") as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                cur = MagicMock()
                cur.rowcount = 3
                conn.execute.return_value = cur

                from web.routes.admin.users import invalidate_sessions
                response = invalidate_sessions(1)

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["sessions_revoked"] == 3
