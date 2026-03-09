"""Tests for admin retention queue endpoint.

Verifies:
- GET /admin/entitlements/retention/pending returns expiring sessions and pending purges
- Endpoint returns empty lists when no data matches
- Endpoint returns partial results when one query fails
- Endpoint requires superadmin access
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestRetentionPending:
    """Tests for GET /admin/entitlements/retention/pending."""

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

    def test_returns_expiring_sessions_and_pending_purges(self):
        """Endpoint returns both expiring_sessions and pending_purges."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            self._admin_context()

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=3)
            purge_at = now + timedelta(days=5)
            deleted_at = now - timedelta(days=35)

            with patch(
                "web.routes.admin.entitlements._get_conn"
            ) as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                # First execute call -> expiring sessions
                expiring_cursor = MagicMock()
                expiring_cursor.fetchall.return_value = [
                    {
                        "session_id": "sess-001",
                        "csv_filename": "race1.csv",
                        "created_at": now - timedelta(days=27),
                        "plan_tier": "demo",
                        "user_id": 42,
                        "expires_at": expires_at,
                    },
                ]

                # Second execute call -> pending purges
                purge_cursor = MagicMock()
                purge_cursor.fetchall.return_value = [
                    {
                        "id": 7,
                        "email": "deleted@example.com",
                        "deleted_at": deleted_at,
                        "purge_at": purge_at,
                    },
                ]

                conn.execute.side_effect = [expiring_cursor, purge_cursor]

                from web.routes.admin.entitlements import retention_pending

                response = retention_pending()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]["expiring_sessions"]) == 1
                assert len(data["data"]["pending_purges"]) == 1

                session = data["data"]["expiring_sessions"][0]
                assert session["session_id"] == "sess-001"
                assert session["plan_tier"] == "demo"
                assert session["user_id"] == 42

                purge = data["data"]["pending_purges"][0]
                assert purge["id"] == 7
                assert purge["email"] == "deleted@example.com"

    def test_returns_empty_lists_on_no_data(self):
        """Endpoint returns empty lists when no data matches."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            self._admin_context()

            with patch(
                "web.routes.admin.entitlements._get_conn"
            ) as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                empty_cursor = MagicMock()
                empty_cursor.fetchall.return_value = []
                conn.execute.return_value = empty_cursor

                from web.routes.admin.entitlements import retention_pending

                response = retention_pending()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["expiring_sessions"] == []
                assert data["data"]["pending_purges"] == []

    def test_partial_result_on_expiring_query_failure(self):
        """If the expiring sessions query fails, pending purges still returned."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            self._admin_context()

            now = datetime.now(timezone.utc)

            with patch(
                "web.routes.admin.entitlements._get_conn"
            ) as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                # First call (expiring sessions) raises, second succeeds
                purge_cursor = MagicMock()
                purge_cursor.fetchall.return_value = [
                    {
                        "id": 3,
                        "email": "old@example.com",
                        "deleted_at": now - timedelta(days=40),
                        "purge_at": now - timedelta(days=10),
                    },
                ]

                conn.execute.side_effect = [
                    RuntimeError("PG connection lost"),
                    purge_cursor,
                ]

                from web.routes.admin.entitlements import retention_pending

                response = retention_pending()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert data["data"]["expiring_sessions"] == []
                assert len(data["data"]["pending_purges"]) == 1

    def test_partial_result_on_purge_query_failure(self):
        """If the purge query fails, expiring sessions still returned."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            self._admin_context()

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=2)

            with patch(
                "web.routes.admin.entitlements._get_conn"
            ) as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                expiring_cursor = MagicMock()
                expiring_cursor.fetchall.return_value = [
                    {
                        "session_id": "sess-005",
                        "csv_filename": "quali.csv",
                        "created_at": now - timedelta(days=28),
                        "plan_tier": "demo",
                        "user_id": 10,
                        "expires_at": expires_at,
                    },
                ]

                conn.execute.side_effect = [
                    expiring_cursor,
                    RuntimeError("PG connection lost"),
                ]

                from web.routes.admin.entitlements import retention_pending

                response = retention_pending()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                assert data["ok"] is True
                assert len(data["data"]["expiring_sessions"]) == 1
                assert data["data"]["pending_purges"] == []

    def test_requires_superadmin(self):
        """Endpoint returns 403 without superadmin access."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            from flask import g

            # Set up a non-superadmin user
            g.current_user_id = 5
            g.admin_user = {
                "is_superadmin": False,
                "admin_role": "support_admin",
                "totp_enabled": True,
            }
            g.admin_verified = True

            from web.routes.admin.entitlements import retention_pending

            response = retention_pending()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert status == 403
            assert data["ok"] is False

    def test_requires_totp_enabled(self):
        """Endpoint returns 403 without 2FA enabled."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            from flask import g

            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "root_admin",
                "totp_enabled": False,
            }
            g.admin_verified = True

            from web.routes.admin.entitlements import retention_pending

            response = retention_pending()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert status == 403
            assert data["ok"] is False

    def test_requires_admin_verified(self):
        """Endpoint returns 403 without admin_verified JWT claim."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            from flask import g

            g.current_user_id = 99
            g.admin_user = {
                "is_superadmin": True,
                "admin_role": "root_admin",
                "totp_enabled": True,
            }
            g.admin_verified = False  # JWT claim missing

            from web.routes.admin.entitlements import retention_pending

            response = retention_pending()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert status == 403
            assert data["ok"] is False

    def test_serializes_datetime_fields(self):
        """Datetime fields are serialized to ISO format strings."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/entitlements/retention/pending"
        ):
            self._admin_context()

            now = datetime(2026, 2, 28, 12, 0, 0, tzinfo=timezone.utc)
            created = datetime(2026, 1, 29, 12, 0, 0, tzinfo=timezone.utc)
            expires = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
            deleted = datetime(2026, 1, 20, 10, 0, 0, tzinfo=timezone.utc)
            purge = datetime(2026, 2, 19, 10, 0, 0, tzinfo=timezone.utc)

            with patch(
                "web.routes.admin.entitlements._get_conn"
            ) as mock_conn:
                conn = MagicMock()
                mock_conn.return_value = conn

                expiring_cursor = MagicMock()
                expiring_cursor.fetchall.return_value = [
                    {
                        "session_id": "sess-dt",
                        "csv_filename": "test.csv",
                        "created_at": created,
                        "plan_tier": "demo",
                        "user_id": 1,
                        "expires_at": expires,
                    },
                ]

                purge_cursor = MagicMock()
                purge_cursor.fetchall.return_value = [
                    {
                        "id": 2,
                        "email": "purge@example.com",
                        "deleted_at": deleted,
                        "purge_at": purge,
                    },
                ]

                conn.execute.side_effect = [expiring_cursor, purge_cursor]

                from web.routes.admin.entitlements import retention_pending

                response = retention_pending()

                if isinstance(response, tuple):
                    data = response[0].get_json()
                else:
                    data = response.get_json()

                session = data["data"]["expiring_sessions"][0]
                assert isinstance(session["created_at"], str)
                assert "2026-01-29" in session["created_at"]
                assert isinstance(session["expires_at"], str)
                assert "2026-03-01" in session["expires_at"]

                purge_entry = data["data"]["pending_purges"][0]
                assert isinstance(purge_entry["deleted_at"], str)
                assert "2026-01-20" in purge_entry["deleted_at"]
                assert isinstance(purge_entry["purge_at"], str)
                assert "2026-02-19" in purge_entry["purge_at"]
