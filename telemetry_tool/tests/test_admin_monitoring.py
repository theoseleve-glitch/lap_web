"""Tests for admin monitoring blueprint.

Verifies:
- _get_totals returns system-wide aggregates
- _get_user_resources returns per-user aggregation
- _get_user_resources validates sort column against allowlist
- _get_user_timeseries returns daily time series
- Sort injection attempt falls back to safe default
- Routes return proper envelope responses
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.routes.admin.monitoring import (
    _VALID_SORT_COLUMNS,
    _get_totals,
    _get_user_resources,
    _get_user_timeseries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeCursor:
    """Minimal cursor returning pre-set rows."""

    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    """Minimal PG connection mock."""

    def __init__(self, rows=None):
        self._cursor = FakeCursor(rows)

    def execute(self, sql, params=None):
        return self._cursor


# ---------------------------------------------------------------------------
# _get_totals
# ---------------------------------------------------------------------------


class TestGetTotals:
    def test_returns_system_totals(self):
        """Returns totals for users, sessions, storage, compute."""
        row = {
            "total_users": 42,
            "total_sessions": 500,
            "total_storage_bytes": 1073741824,
            "total_compute_seconds": 3600.5,
        }
        conn = FakeConn([row])

        with patch("web.routes.admin.monitoring._get_conn", return_value=conn):
            result = _get_totals()

        assert result["total_users"] == 42
        assert result["total_sessions"] == 500
        assert result["total_storage_bytes"] == 1073741824
        assert result["total_compute_seconds"] == 3600.5

    def test_serializes_datetime_fields(self):
        """Datetime values are serialized to ISO format."""
        dt = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        row = {
            "total_users": 1,
            "total_sessions": 1,
            "total_storage_bytes": 0,
            "total_compute_seconds": 0,
            "some_date": dt,
        }
        conn = FakeConn([row])

        with patch("web.routes.admin.monitoring._get_conn", return_value=conn):
            result = _get_totals()

        assert result["some_date"] == "2026-03-01T12:00:00+00:00"


# ---------------------------------------------------------------------------
# _get_user_resources
# ---------------------------------------------------------------------------


class TestGetUserResources:
    def test_returns_user_list(self):
        """Returns list of user resource dicts."""
        rows = [
            {
                "user_id": 1,
                "email": "alice@example.com",
                "display_name": "Alice",
                "user_created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "session_count": 10,
                "total_storage_bytes": 5000000,
                "total_compute_seconds": 120.5,
                "last_upload": datetime(2026, 3, 1, tzinfo=timezone.utc),
            },
        ]
        conn = FakeConn(rows)

        with patch("web.routes.admin.monitoring._get_conn", return_value=conn):
            result = _get_user_resources("total_storage_bytes", 100)

        assert len(result) == 1
        assert result[0]["email"] == "alice@example.com"
        assert result[0]["total_storage_bytes"] == 5000000

    def test_falls_back_to_default_sort_on_invalid(self):
        """Invalid sort column falls back to total_storage_bytes."""
        conn = FakeConn([])

        with patch("web.routes.admin.monitoring._get_conn", return_value=conn):
            # Should not raise, should fallback
            result = _get_user_resources("DROP TABLE users;--", 100)

        assert result == []

    def test_accepts_all_valid_sort_columns(self):
        """All valid sort columns are accepted without error."""
        for col in _VALID_SORT_COLUMNS:
            conn = FakeConn([])
            with patch("web.routes.admin.monitoring._get_conn", return_value=conn):
                result = _get_user_resources(col, 10)
            assert isinstance(result, list)

    def test_passes_limit_to_query(self):
        """Limit parameter is passed to the SQL query."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
            _get_user_resources("total_storage_bytes", 50)

        call_args = mock_conn.execute.call_args
        assert call_args[0][1]["limit"] == 50


# ---------------------------------------------------------------------------
# _get_user_timeseries
# ---------------------------------------------------------------------------


class TestGetUserTimeseries:
    def test_returns_daily_timeseries(self):
        """Returns list of daily aggregation dicts."""
        rows = [
            {
                "day": datetime(2026, 2, 28, tzinfo=timezone.utc),
                "job_count": 3,
                "storage_bytes": 1500000,
                "compute_seconds": 45.0,
            },
            {
                "day": datetime(2026, 3, 1, tzinfo=timezone.utc),
                "job_count": 5,
                "storage_bytes": 2500000,
                "compute_seconds": 60.0,
            },
        ]
        conn = FakeConn(rows)

        with patch("web.routes.admin.monitoring._get_conn", return_value=conn):
            result = _get_user_timeseries(user_id=1, days=30)

        assert len(result) == 2
        assert result[0]["job_count"] == 3
        assert result[1]["job_count"] == 5
        # Dates should be serialized
        assert "2026-02-28" in result[0]["day"]
        assert "2026-03-01" in result[1]["day"]

    def test_returns_empty_for_no_data(self):
        """Returns empty list when no ingestion jobs exist."""
        conn = FakeConn([])

        with patch("web.routes.admin.monitoring._get_conn", return_value=conn):
            result = _get_user_timeseries(user_id=999, days=30)

        assert result == []

    def test_passes_user_id_and_days_params(self):
        """user_id and days are passed to the SQL query."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
            _get_user_timeseries(user_id=42, days=7)

        call_args = mock_conn.execute.call_args
        assert call_args[0][1]["user_id"] == 42
        assert call_args[0][1]["days"] == 7


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------


class TestMonitoringRoutes:
    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True

        from web.routes.admin.monitoring import bp as monitoring_bp
        app.register_blueprint(monitoring_bp, url_prefix="/api/v1/admin")
        return app

    def _admin_context(self, app):
        from flask import g
        g.current_user_id = 1
        g.admin_user = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }
        g.admin_verified = True

    def test_totals_route(self):
        """GET /monitoring/totals returns system totals."""
        app = self._make_app()

        with app.test_request_context("/api/v1/admin/monitoring/totals"):
            self._admin_context(app)

            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = {
                "total_users": 10,
                "total_sessions": 100,
                "total_storage_bytes": 1000000,
                "total_compute_seconds": 500.0,
            }
            mock_conn.execute.return_value = mock_cursor

            with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
                from web.routes.admin.monitoring import monitoring_totals
                response = monitoring_totals()

            if isinstance(response, tuple):
                data = response[0].get_json()
            else:
                data = response.get_json()

            assert data["ok"] is True
            assert data["data"]["total_users"] == 10

    def test_users_route_invalid_sort(self):
        """GET /monitoring/users with invalid sort returns 400."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/monitoring/users?sort=DROP+TABLE+users"
        ):
            self._admin_context(app)

            from web.routes.admin.monitoring import monitoring_users
            response = monitoring_users()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert data["ok"] is False
            assert status == 400

    def test_users_route_valid_sort(self):
        """GET /monitoring/users with valid sort returns 200."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/monitoring/users?sort=session_count&limit=10"
        ):
            self._admin_context(app)

            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_conn.execute.return_value = mock_cursor

            with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
                from web.routes.admin.monitoring import monitoring_users
                response = monitoring_users()

            if isinstance(response, tuple):
                data = response[0].get_json()
                status = response[1]
            else:
                data = response.get_json()
                status = 200

            assert data["ok"] is True
            assert status == 200

    def test_timeseries_route(self):
        """GET /monitoring/users/<id>/timeseries returns time series."""
        app = self._make_app()

        with app.test_request_context(
            "/api/v1/admin/monitoring/users/1/timeseries?days=7"
        ):
            self._admin_context(app)

            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [
                {
                    "day": datetime(2026, 3, 1, tzinfo=timezone.utc),
                    "job_count": 2,
                    "storage_bytes": 500000,
                    "compute_seconds": 30.0,
                },
            ]
            mock_conn.execute.return_value = mock_cursor

            with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
                from web.routes.admin.monitoring import monitoring_user_timeseries
                response = monitoring_user_timeseries(user_id=1)

            if isinstance(response, tuple):
                data = response[0].get_json()
            else:
                data = response.get_json()

            assert data["ok"] is True
            assert data["data"]["user_id"] == 1
            assert data["data"]["days"] == 7
            assert len(data["data"]["timeseries"]) == 1
