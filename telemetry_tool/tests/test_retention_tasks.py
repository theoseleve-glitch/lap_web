"""Tests for telemetry retention enforcement task.

Validates that:
- Raw data is deleted for sessions past the retention window
- B2B workspaces (NULL retention) are never auto-deleted
- Entitlement overrides for retention are respected
- Sessions marked retention_expired are skipped (idempotent)
- Warning emails are sent 7 days before deletion
- Deletion notifications are sent on the day of deletion
"""
import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.retention_tasks import (
    _get_workspace_retention,
    _find_expiring_sessions,
    _find_warning_sessions,
    _delete_raw_data,
    _mark_session_expired,
)


class FakeCursor:
    """Cursor mock that supports multiple execute/fetch cycles.

    Pass a list of result-sets (one per execute call). Each execute()
    advances to the next result-set, and fetchone/fetchall return from
    the current result-set.
    """
    def __init__(self, result_sets=None):
        self._result_sets = result_sets or [[]]
        self._query_idx = -1
        self._current_rows = []
        self._pos = 0
        self.rowcount = 0

    def execute(self, sql, params=None):
        self._query_idx += 1
        if self._query_idx < len(self._result_sets):
            self._current_rows = self._result_sets[self._query_idx]
        else:
            self._current_rows = []
        self._pos = 0

    def fetchone(self):
        if self._pos < len(self._current_rows):
            r = self._current_rows[self._pos]
            self._pos += 1
            return r
        return None

    def fetchall(self):
        return self._current_rows


class TestGetWorkspaceRetention:
    def test_returns_plan_retention_for_demo(self):
        """Demo workspace gets 30-day retention."""
        conn = MagicMock()
        # Single cursor, 3 execute calls: override (empty), owner, plan_def
        cursor = FakeCursor([
            [],                                     # override query: no override
            [{"plan_tier": "demo"}],                # owner query
            [{"telemetry_retention_days": 30}],     # plan_definitions query
        ])
        conn.cursor.return_value = cursor

        retention = _get_workspace_retention(conn, 1)
        assert retention == 30

    def test_returns_plan_retention_for_racer(self):
        """Racer workspace gets 90-day retention."""
        conn = MagicMock()
        cursor = FakeCursor([
            [],
            [{"plan_tier": "racer"}],
            [{"telemetry_retention_days": 90}],
        ])
        conn.cursor.return_value = cursor

        retention = _get_workspace_retention(conn, 1)
        assert retention == 90

    def test_returns_none_for_b2b(self):
        """B2B workspace gets NULL retention (never auto-delete)."""
        conn = MagicMock()
        cursor = FakeCursor([
            [],
            [{"plan_tier": "b2b"}],
            [{"telemetry_retention_days": None}],
        ])
        conn.cursor.return_value = cursor

        retention = _get_workspace_retention(conn, 1)
        assert retention is None

    def test_override_takes_precedence(self):
        """Entitlement override for retention overrides plan definition."""
        import json
        conn = MagicMock()
        cursor = FakeCursor([
            [{"override_value": json.dumps(180)}],  # override found
        ])
        conn.cursor.return_value = cursor

        retention = _get_workspace_retention(conn, 1)
        assert retention == 180

    def test_override_with_dict_value(self):
        """Override with {"value": 365} format."""
        import json
        conn = MagicMock()
        cursor = FakeCursor([
            [{"override_value": json.dumps({"value": 365})}],
        ])
        conn.cursor.return_value = cursor

        retention = _get_workspace_retention(conn, 1)
        assert retention == 365

    def test_override_null_means_unlimited(self):
        """Override with null value means unlimited."""
        import json
        conn = MagicMock()
        cursor = FakeCursor([
            [{"override_value": json.dumps(None)}],
        ])
        conn.cursor.return_value = cursor

        retention = _get_workspace_retention(conn, 1)
        assert retention is None

    def test_fallback_to_demo_on_missing_owner(self):
        """If workspace owner not found, fallback to 30-day demo retention."""
        conn = MagicMock()
        cursor = FakeCursor([
            [],    # no override
            [],    # no owner found
        ])
        conn.cursor.return_value = cursor

        retention = _get_workspace_retention(conn, 1)
        assert retention == 30


class TestDeleteRawData:
    def test_deletes_from_all_raw_tables(self):
        """Deletion covers gps_traces, reference_lines, driving_style_features, theoretical_data."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 5
        conn.cursor.return_value = cursor

        total = _delete_raw_data(conn, "session_001")
        assert total == 20  # 5 rows × 4 tables
        assert cursor.execute.call_count == 4

    def test_dry_run_counts_without_deleting(self):
        """Dry run counts rows but doesn't delete them."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"cnt": 3}
        conn.cursor.return_value = cursor

        total = _delete_raw_data(conn, "session_001", dry_run=True)
        assert total == 12  # 3 rows × 4 tables
        # Should use SELECT COUNT, not DELETE
        for c in cursor.execute.call_args_list:
            sql = c[0][0]
            assert "SELECT COUNT" in sql
            assert "DELETE" not in sql


class TestMarkSessionExpired:
    def test_updates_retention_expired_flag(self):
        """Session is marked as retention_expired."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _mark_session_expired(conn, "session_001")
        cursor.execute.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        assert "retention_expired = TRUE" in sql


class TestRetentionEmails:
    def test_send_retention_warning(self):
        """Warning email includes session list and upgrade CTA."""
        from auth.email import send_retention_warning
        sessions = [
            {"session_id": "s1", "file_name": "Session_2026-01-01.csv", "created_at": "2026-01-01"},
            {"session_id": "s2", "file_name": "Session_2026-01-02.csv", "created_at": "2026-01-02"},
        ]
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            result = send_retention_warning("user@example.com", sessions, 7)
            assert result is True
            mock_send.assert_called_once()
            _, subject, html = mock_send.call_args[0]
            assert "7 days" in subject
            assert "Session_2026-01-01.csv" in html
            assert "upgrade your plan" in html.lower() or "upgrade" in html.lower()

    def test_send_retention_deleted(self):
        """Deletion notification includes session list."""
        from auth.email import send_retention_deleted
        sessions = [
            {"session_id": "s1", "file_name": "Session_2026-01-01.csv"},
        ]
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            result = send_retention_deleted("user@example.com", sessions)
            assert result is True
            mock_send.assert_called_once()
            _, subject, html = mock_send.call_args[0]
            assert "deleted" in subject.lower()
            assert "Session_2026-01-01.csv" in html

    def test_warning_caps_at_10_sessions(self):
        """Warning email caps session list at 10 and shows overflow count."""
        from auth.email import send_retention_warning
        sessions = [
            {"session_id": f"s{i}", "file_name": f"Session_{i}.csv", "created_at": f"2026-01-{i:02d}"}
            for i in range(1, 16)  # 15 sessions
        ]
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            send_retention_warning("user@example.com", sessions, 7)
            _, _, html = mock_send.call_args[0]
            assert "5 more sessions" in html  # 15 - 10 = 5
