"""Tests for account endpoints — entitlements, usage, retention, OAuth, support (Tasks 8-9).

Validates:
- GET /api/v1/account/entitlements returns plan features
- GET /api/v1/account/usage returns usage snapshot
- GET /api/v1/account/retention returns sessions with expiry dates
- GET /api/v1/account/oauth-connections lists providers
- DELETE /api/v1/account/oauth-connections/<provider> blocks last auth method
- POST /api/v1/account/support/ticket validates description length
- PATCH /api/v1/account/profile handles avatar_url and preferences
- Profile preferences JSONB merge
- ProfileUpdateSchema + UserPreferences schema validation
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class FakeConn:
    """Minimal fake DB connection for tests."""
    def __init__(self, rows_by_query=None):
        self._rows_by_query = rows_by_query or {}
        self._calls = []
        self._committed = False

    def execute(self, sql, params=None):
        self._calls.append((str(sql), params))
        cur = MagicMock()
        for key, rows in self._rows_by_query.items():
            if key in str(sql):
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


def _make_flask_app():
    """Create a minimal Flask app with the account blueprint registered."""
    from flask import Flask
    from web.routes.api_v1_account import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app


# ---------------------------------------------------------------------------
# Test entitlements endpoint
# ---------------------------------------------------------------------------

class TestEntitlements:
    def test_entitlements_returns_plan_features(self):
        """GET /entitlements returns plan name and feature dict."""
        from web.routes.api_v1_account import get_entitlements

        conn = FakeConn({
            "plan_tier": [{"plan_tier": "racer"}],
        })

        app = _make_flask_app()
        with app.test_request_context("/api/v1/account/entitlements"):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = get_entitlements()
                data = response.get_json()

                assert status == 200
                assert data["ok"] is True
                assert data["data"]["plan"] == "racer"
                ent = data["data"]["entitlements"]
                assert ent["reports_per_month"] == 10
                assert ent["raw_retention_days"] == 90
                assert ent["coaching_drills"] is True

    def test_entitlements_free_plan(self):
        """Free/demo plan returns limited features."""
        from web.routes.api_v1_account import get_entitlements

        conn = FakeConn({
            "plan_tier": [{"plan_tier": "demo"}],
        })

        app = _make_flask_app()
        with app.test_request_context("/api/v1/account/entitlements"):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = get_entitlements()
                data = response.get_json()

                assert status == 200
                assert data["data"]["plan"] == "demo"
                assert data["data"]["entitlements"]["reports_per_month"] == 1
                assert data["data"]["entitlements"]["coaching_drills"] is False


# ---------------------------------------------------------------------------
# Test usage endpoint
# ---------------------------------------------------------------------------

class TestUsage:
    def test_usage_returns_snapshot(self):
        """GET /usage returns usage snapshot dict."""
        from web.routes.api_v1_account import get_usage

        conn = FakeConn({
            "plan_tier": [{"plan_tier": "racer"}],
        })

        app = _make_flask_app()
        with app.test_request_context("/api/v1/account/usage"):
            from flask import g
            g.user_id = 1
            g.workspace_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn), \
                 patch("auth.usage.get_usage_count", return_value=5):
                response, status = get_usage()
                data = response.get_json()

                assert status == 200
                assert data["ok"] is True
                # Should have metric keys
                assert "reports" in data["data"]
                assert "uploads" in data["data"]

    def test_usage_requires_workspace(self):
        """GET /usage returns 403 without workspace context."""
        from web.routes.api_v1_account import get_usage

        app = _make_flask_app()
        with app.test_request_context("/api/v1/account/usage"):
            from flask import g
            g.user_id = 1
            # No workspace_id set
            response, status = get_usage()
            data = response.get_json()

            assert status == 403


# ---------------------------------------------------------------------------
# Test retention endpoint
# ---------------------------------------------------------------------------

class TestRetention:
    def test_retention_returns_sessions_with_expiry(self):
        """GET /retention returns sessions with calculated expires_at."""
        from web.routes.api_v1_account import get_retention

        created = datetime.now(timezone.utc) - timedelta(days=10)
        conn = FakeConn({
            "plan_tier": [{"plan_tier": "racer"}],
            "session_id": [{
                "session_id": 42,
                "file_name": "test_session.csv",
                "created_at": created,
            }],
        })

        app = _make_flask_app()
        with app.test_request_context("/api/v1/account/retention"):
            from flask import g
            g.user_id = 1
            g.workspace_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = get_retention()
                data = response.get_json()

                assert status == 200
                assert data["data"]["plan"] == "racer"
                assert data["data"]["raw_retention_days"] == 90
                assert data["data"]["report_retention"] == "indefinite"
                assert len(data["data"]["sessions"]) == 1

                session = data["data"]["sessions"][0]
                assert session["session_id"] == 42
                assert "expires_at" in session

    def test_retention_free_plan_30_days(self):
        """Free plan shows 30-day retention."""
        from web.routes.api_v1_account import get_retention

        conn = FakeConn({
            "plan_tier": [{"plan_tier": "demo"}],
        })

        app = _make_flask_app()
        with app.test_request_context("/api/v1/account/retention"):
            from flask import g
            g.user_id = 1
            g.workspace_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = get_retention()
                data = response.get_json()

                assert status == 200
                assert data["data"]["raw_retention_days"] == 30


# ---------------------------------------------------------------------------
# Test OAuth connections endpoints
# ---------------------------------------------------------------------------

class TestOAuthConnections:
    def test_list_oauth_connections(self):
        """GET /oauth-connections returns provider list."""
        from web.routes.api_v1_account import list_oauth_connections

        conn = FakeConn({
            "oauth_connections": [{
                "provider": "google",
                "provider_user_id": "g_123",
                "created_at": datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
            }],
        })

        app = _make_flask_app()
        with app.test_request_context("/api/v1/account/oauth-connections"):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = list_oauth_connections()
                data = response.get_json()

                assert status == 200
                assert len(data["data"]) == 1
                assert data["data"][0]["provider"] == "google"

    def test_unlink_blocked_when_last_auth_method(self):
        """DELETE /oauth-connections/<provider> returns 400 when it's the last auth method."""
        from web.routes.api_v1_account import unlink_oauth_connection

        conn = FakeConn({
            "password_hash": [{"password_hash": None}],  # No password
            "COUNT": [{"cnt": 1}],  # Only 1 OAuth connection
        })

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/oauth-connections/google",
            method="DELETE",
        ):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = unlink_oauth_connection("google")
                data = response.get_json()

                assert status == 400
                assert "LAST_AUTH_METHOD" in str(data["error"].get("details", ""))

    def test_unlink_allowed_with_password(self):
        """DELETE /oauth-connections/<provider> succeeds when user has a password."""
        from web.routes.api_v1_account import unlink_oauth_connection

        conn = FakeConn({
            "password_hash": [{"password_hash": "$argon2id$hash"}],  # Has password
            "COUNT": [{"cnt": 1}],
            "RETURNING": [{"id": 1}],
        })

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/oauth-connections/google",
            method="DELETE",
        ):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = unlink_oauth_connection("google")
                data = response.get_json()

                assert status == 200
                assert data["data"]["unlinked"] == "google"


# ---------------------------------------------------------------------------
# Test support ticket endpoint
# ---------------------------------------------------------------------------

class TestSupportTicket:
    def test_support_ticket_requires_description(self):
        """POST /support/ticket requires description >= 10 chars."""
        from web.routes.api_v1_account import create_support_ticket

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/support/ticket",
            method="POST",
            content_type="application/json",
            data=json.dumps({"issue_type": "bug", "description": "short"}),
        ):
            from flask import g
            g.user_id = 1
            g.workspace_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=MagicMock()):
                response, status = create_support_ticket()
                data = response.get_json()

                assert status == 400
                assert "at least 10" in data["error"]["message"]

    def test_support_ticket_submitted(self):
        """POST /support/ticket succeeds with valid description."""
        from web.routes.api_v1_account import create_support_ticket

        conn = FakeConn({
            "SELECT email": [{
                "email": "user@test.com",
                "display_name": "Test User",
                "plan_tier": "racer",
            }],
            "RETURNING": [{"id": 42, "created_at": datetime.now(timezone.utc)}],
        })

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/support/ticket",
            method="POST",
            content_type="application/json",
            data=json.dumps({
                "issue_type": "bug",
                "description": "My telemetry data is not loading properly after upload.",
            }),
        ):
            from flask import g
            g.user_id = 1
            g.workspace_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn), \
                 patch("auth.email._send", return_value=True):
                response, status = create_support_ticket()
                data = response.get_json()

                assert status == 201
                assert data["data"]["ticket_id"] == 42
                assert data["data"]["status"] == "open"

    def test_support_ticket_requires_issue_type(self):
        """POST /support/ticket requires issue_type."""
        from web.routes.api_v1_account import create_support_ticket

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/support/ticket",
            method="POST",
            content_type="application/json",
            data=json.dumps({"description": "A valid description here."}),
        ):
            from flask import g
            g.user_id = 1
            g.workspace_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=MagicMock()):
                response, status = create_support_ticket()
                data = response.get_json()

                assert status == 400
                assert "issue_type" in data["error"]["message"]


# ---------------------------------------------------------------------------
# Test profile update with preferences (Task 9)
# ---------------------------------------------------------------------------

class TestProfilePreferences:
    def test_update_profile_with_avatar_url(self):
        """PATCH /profile sets avatar_url."""
        from web.routes.api_v1_account import update_profile

        conn = FakeConn({
            "SELECT id": [{
                "id": 1,
                "display_name": "Test",
                "email": "user@test.com",
                "avatar_url": None,
                "preferences": "{}",
            }],
            "SELECT display_name": [{
                "display_name": "Test",
                "email": "user@test.com",
                "avatar_url": "https://example.com/avatar.jpg",
                "preferences": "{}",
            }],
        })

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/profile",
            method="PATCH",
            content_type="application/json",
            data=json.dumps({"avatar_url": "https://example.com/avatar.jpg"}),
        ):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = update_profile()
                data = response.get_json()

                assert status == 200
                assert data["data"]["avatar_url"] == "https://example.com/avatar.jpg"

    def test_update_profile_with_preferences(self):
        """PATCH /profile merges preferences via JSONB."""
        from web.routes.api_v1_account import update_profile

        conn = FakeConn({
            "SELECT id": [{
                "id": 1,
                "display_name": "Test",
                "email": "user@test.com",
                "avatar_url": None,
                "preferences": json.dumps({"language": "en"}),
            }],
            "SELECT display_name": [{
                "display_name": "Test",
                "email": "user@test.com",
                "avatar_url": None,
                "preferences": json.dumps({"language": "en", "units": "metric", "timezone": "Europe/Rome"}),
            }],
        })

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/profile",
            method="PATCH",
            content_type="application/json",
            data=json.dumps({
                "preferences": {"units": "metric", "timezone": "Europe/Rome"},
            }),
        ):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=conn):
                response, status = update_profile()
                data = response.get_json()

                assert status == 200
                prefs = data["data"]["preferences"]
                assert prefs["language"] == "en"
                assert prefs["units"] == "metric"
                assert prefs["timezone"] == "Europe/Rome"

    def test_update_profile_empty_body_rejected(self):
        """PATCH /profile with no fields returns 400."""
        from web.routes.api_v1_account import update_profile

        app = _make_flask_app()
        with app.test_request_context(
            "/api/v1/account/profile",
            method="PATCH",
            content_type="application/json",
            data=json.dumps({}),
        ):
            from flask import g
            g.user_id = 1
            with patch("web.routes.api_v1_account.get_pg_connection", return_value=MagicMock()):
                response, status = update_profile()
                assert status == 400


# ---------------------------------------------------------------------------
# Test Pydantic schemas (Task 9)
# ---------------------------------------------------------------------------

class TestAccountSchemas:
    def test_profile_update_schema_with_preferences(self):
        """ProfileUpdateSchema accepts avatar_url and preferences."""
        from web.schemas.account import ProfileUpdateSchema

        schema = ProfileUpdateSchema(
            display_name="Test User",
            email="user@test.com",
            avatar_url="https://example.com/avatar.jpg",
            preferences={"units": "metric", "language": "en"},
        )
        assert schema.display_name == "Test User"
        assert schema.avatar_url == "https://example.com/avatar.jpg"
        assert schema.preferences is not None
        assert schema.preferences.units == "metric"
        assert schema.preferences.language == "en"

    def test_notification_preferences_defaults(self):
        """NotificationPreferences has sensible defaults."""
        from web.schemas.account import NotificationPreferences

        prefs = NotificationPreferences()
        assert prefs.report_ready is True
        assert prefs.billing_alerts is True
        assert prefs.product_updates is False
        assert prefs.weekly_digest is True

    def test_user_preferences_with_notifications(self):
        """UserPreferences accepts nested NotificationPreferences."""
        from web.schemas.account import UserPreferences

        prefs = UserPreferences(
            units="imperial",
            timezone="America/New_York",
            notifications={"report_ready": False, "weekly_digest": False},
        )
        assert prefs.units == "imperial"
        assert prefs.notifications.report_ready is False
        assert prefs.notifications.weekly_digest is False
        assert prefs.notifications.billing_alerts is True  # default

    def test_profile_schema_max_lengths(self):
        """ProfileUpdateSchema enforces max_length constraints."""
        from web.schemas.account import ProfileUpdateSchema
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ProfileUpdateSchema(display_name="x" * 201)

        with pytest.raises(ValidationError):
            ProfileUpdateSchema(avatar_url="x" * 2049)

    def test_user_preferences_invalid_units(self):
        """UserPreferences rejects invalid units value."""
        from web.schemas.account import UserPreferences
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UserPreferences(units="hectares")


# ---------------------------------------------------------------------------
# Test retention task (Task 10)
# ---------------------------------------------------------------------------

class TestRetentionTask:
    def test_retention_task_module_imports(self):
        """retention_tasks.py exports enforce_telemetry_retention."""
        from tasks.retention_tasks import enforce_telemetry_retention
        assert callable(enforce_telemetry_retention)

    def test_retention_impl_skips_unlimited(self):
        """Retention enforcement skips workspaces with unlimited retention."""
        from tasks.retention_tasks import _get_workspace_retention

        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur

        # Override returns None (unlimited)
        cur.fetchone.side_effect = [
            {"override_value": "null"},  # entitlement_overrides → None
        ]

        result = _get_workspace_retention(conn, 1)
        assert result is None

    def test_send_retention_warning_sends_email(self):
        """send_retention_warning calls _send with correct content."""
        from auth.email import send_retention_warning

        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            result = send_retention_warning(
                "user@test.com",
                [
                    {"session_id": "s1", "file_name": "race1.csv", "created_at": "2026-01-01"},
                    {"session_id": "s2", "file_name": "race2.csv", "created_at": "2026-01-02"},
                ],
                days_remaining=7,
            )
            assert result is True
            mock_send.assert_called_once()
            to, subject, html = mock_send.call_args[0]
            assert to == "user@test.com"
            assert "retention" in subject.lower() or "expir" in subject.lower()
            assert "race1.csv" in html
