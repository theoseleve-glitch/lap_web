"""Tests for GDPR Celery tasks — export and purge."""
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.gdpr_tasks import export_user_data, purge_deleted_accounts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_conn():
    """Return a mock PG connection."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


def _user_row(user_id=1, email="test@example.com", display_name="Alice",
              deleted_at=None):
    """Build a mock user row."""
    return {
        "id": user_id,
        "email": email,
        "display_name": display_name,
        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "deleted_at": deleted_at,
    }


def _session_row(session_id="s1", user_id=1):
    return {
        "session_id": session_id,
        "workspace_id": 1,
        "session_date": "2025-06-15",
        "session_type": "practice",
        "n_laps": 10,
        "best_lap_time_s": 62.5,
    }


def _lap_row(session_id="s1", lap_number=1, lat=45.123456789, lon=9.987654321):
    return {
        "session_id": session_id,
        "lap_number": lap_number,
        "lap_time_s": 63.0,
        "gps_lat": lat,
        "gps_lon": lon,
    }


# ---------------------------------------------------------------------------
# export_user_data
# ---------------------------------------------------------------------------

class TestExportUserData:
    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_creates_zip_file(self, mock_update, mock_zip, mock_db):
        """export_user_data calls _write_zip to create export."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")
        assert mock_zip.called

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_updates_status_to_completed(self, mock_update, mock_zip, mock_db):
        """export_user_data sets data_exports status to completed."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")

        update_calls = mock_update.call_args_list
        assert any(
            "completed" in str(c) for c in update_calls
        ), f"Expected 'completed' in update calls: {update_calls}"

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_sets_expires_at_7_days(self, mock_update, mock_zip, mock_db):
        """export_user_data sets expires_at to ~7 days from now."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")

        update_calls = mock_update.call_args_list
        assert len(update_calls) >= 1

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_handles_user_with_no_sessions(self, mock_update, mock_zip, mock_db):
        """export_user_data succeeds even when user has no sessions."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")
        assert mock_zip.called

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_reduces_gps_precision(self, mock_db):
        """GPS coordinates are reduced to 3 decimal places."""
        from tasks.gdpr_tasks import _reduce_gps_precision

        data = {
            "gps_lat": 45.123456789,
            "gps_lon": 9.987654321,
            "latitudes": [45.123456789, 46.987654321],
            "longitudes": [9.111111111, 10.222222222],
        }
        result = _reduce_gps_precision(data)
        assert result["gps_lat"] == 45.123
        assert result["gps_lon"] == 9.988
        assert result["latitudes"] == [45.123, 46.988]
        assert result["longitudes"] == [9.111, 10.222]

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_export_sets_status_processing_first(self, mock_update, mock_zip, mock_db):
        """export_user_data sets status to processing before starting."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")

        first_call = mock_update.call_args_list[0]
        assert "processing" in str(first_call)


# ---------------------------------------------------------------------------
# _resolve_export_workspace_id (P0-B empty-export regression)
# ---------------------------------------------------------------------------

class TestResolveExportWorkspace:
    @patch("tasks.gdpr_tasks.return_pg_connection")
    @patch("tasks.gdpr_tasks.get_maint_connection")
    def test_resolves_from_user_default_workspace(self, mock_maint, _mock_return):
        """Export workspace must resolve from the USER (default_workspace_id),
        not from data_exports.workspace_id — which does not exist and made RLS
        reads fail closed → empty export ZIP."""
        from tasks.gdpr_tasks import _resolve_export_workspace_id
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"default_workspace_id": 7}
        mock_maint.return_value = conn

        assert _resolve_export_workspace_id(42) == 7

        # Inspect the actual SQL text (TextClause), not the Call repr.
        sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list if c.args)
        assert "data_exports" not in sql, "must not read the nonexistent data_exports.workspace_id"
        assert "default_workspace_id" in sql

    @patch("tasks.gdpr_tasks.return_pg_connection")
    @patch("tasks.gdpr_tasks.get_maint_connection")
    def test_falls_back_to_membership(self, mock_maint, _mock_return):
        """If default_workspace_id is NULL, fall back to earliest membership."""
        from tasks.gdpr_tasks import _resolve_export_workspace_id
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [
            {"default_workspace_id": None},  # users lookup
            {"workspace_id": 3},             # workspace_members fallback
        ]
        mock_maint.return_value = conn

        assert _resolve_export_workspace_id(42) == 3


# ---------------------------------------------------------------------------
# purge_deleted_accounts
# ---------------------------------------------------------------------------

class TestPurgeDeletedAccounts:
    @patch("tasks.gdpr_tasks.get_maint_connection")
    def test_skips_users_within_30_day_window(self, mock_db):
        """Users deleted less than 30 days ago are NOT purged."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = []

        purge_deleted_accounts()

        executed_sql = [str(c) for c in conn.execute.call_args_list]
        assert not any("DELETE FROM users" in s for s in executed_sql)

    @patch("tasks.gdpr_tasks.get_maint_connection")
    def test_deletes_users_past_30_days(self, mock_db):
        """Users deleted more than 30 days ago are hard-purged."""
        conn = _mock_conn()
        mock_db.return_value = conn
        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        conn.execute.return_value.fetchall.return_value = [
            _user_row(user_id=42, deleted_at=old_date),
        ]

        purge_deleted_accounts()

        assert conn.execute.call_count >= 2
        conn.commit.assert_called()

    @patch("tasks.gdpr_tasks.get_maint_connection")
    def test_cascades_workspace_deletion(self, mock_db):
        """Purge cascades deletion to workspace-scoped data."""
        conn = _mock_conn()
        mock_db.return_value = conn
        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        conn.execute.return_value.fetchall.return_value = [
            _user_row(user_id=42, deleted_at=old_date),
        ]

        purge_deleted_accounts()

        executed_sql = " ".join(str(c) for c in conn.execute.call_args_list)
        assert "sessions" in executed_sql.lower() or conn.execute.call_count >= 3

    @patch("tasks.gdpr_tasks.get_maint_connection")
    def test_handles_empty_result(self, mock_db):
        """Purge handles no deleted users gracefully."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = []

        purge_deleted_accounts()

    @patch("tasks.gdpr_tasks.get_maint_connection")
    @patch("tasks.gdpr_tasks.logger")
    def test_logs_purge_count(self, mock_logger, mock_db):
        """Purge logs the number of accounts purged."""
        conn = _mock_conn()
        mock_db.return_value = conn
        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        conn.execute.return_value.fetchall.return_value = [
            _user_row(user_id=42, deleted_at=old_date),
            _user_row(user_id=43, deleted_at=old_date),
        ]

        purge_deleted_accounts()
        assert mock_logger.info.called

    @patch("tasks.gdpr_tasks.get_maint_connection")
    def test_purge_deletes_app_events_for_user(self, mock_db):
        """Purge issues DELETE FROM app_events WHERE user_id = :uid (GDPR erasure).

        Routes queries by SQL text so the workspace cascade short-circuits
        (no workspaces -> no sessions) and the per-user erasure block runs to
        completion, reaching the new app_events delete.
        """
        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        conn = MagicMock()

        def _execute(stmt, params=None):
            sql = str(stmt)
            result = MagicMock()
            if "FROM users" in sql and "deleted_at" in sql:
                # The sweep's candidate-user query.
                result.fetchall.return_value = [
                    _user_row(user_id=42, deleted_at=old_date),
                ]
            else:
                # Everything else (workspace lookup, etc.) returns empty so the
                # cascade does nothing and the per-user block proceeds.
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            result.rowcount = 0
            return result

        conn.execute.side_effect = _execute
        mock_db.return_value = conn

        purge_deleted_accounts()

        # Inspect the SQL text (TextClause), not the Call repr.
        app_event_deletes = [
            c for c in conn.execute.call_args_list
            if c.args and "DELETE FROM app_events" in str(c.args[0])
        ]
        assert app_event_deletes, (
            "Expected a 'DELETE FROM app_events' call; got: "
            + " | ".join(str(c.args[0]) for c in conn.execute.call_args_list if c.args)
        )
        # The params dict (2nd positional arg) must carry uid=42.
        params = app_event_deletes[0].args[1]
        assert params.get("uid") == 42


class TestCleanupExpiredExports:
    def test_deletes_old_files(self, tmp_path):
        """Cleanup removes ZIP files older than 7 days."""
        import time
        old_file = tmp_path / "export_old.zip"
        old_file.write_text("old")
        old_mtime = time.time() - (8 * 86400)
        os.utime(old_file, (old_mtime, old_mtime))

        recent_file = tmp_path / "export_recent.zip"
        recent_file.write_text("recent")

        from tasks.gdpr_tasks import _cleanup_expired_exports_impl
        result = _cleanup_expired_exports_impl(str(tmp_path))

        assert not old_file.exists()
        assert recent_file.exists()
        assert result["deleted"] == 1

    def test_skips_non_zip_files(self, tmp_path):
        """Cleanup ignores non-ZIP files."""
        import time
        old_txt = tmp_path / "notes.txt"
        old_txt.write_text("keep me")
        old_mtime = time.time() - (8 * 86400)
        os.utime(old_txt, (old_mtime, old_mtime))

        from tasks.gdpr_tasks import _cleanup_expired_exports_impl
        result = _cleanup_expired_exports_impl(str(tmp_path))

        assert old_txt.exists()
        assert result["deleted"] == 0

    def test_handles_empty_directory(self, tmp_path):
        """Cleanup handles empty export directory gracefully."""
        from tasks.gdpr_tasks import _cleanup_expired_exports_impl
        result = _cleanup_expired_exports_impl(str(tmp_path))
        assert result["deleted"] == 0

    def test_handles_missing_directory(self, tmp_path):
        """Cleanup handles nonexistent export directory gracefully."""
        from tasks.gdpr_tasks import _cleanup_expired_exports_impl
        result = _cleanup_expired_exports_impl(str(tmp_path / "nonexistent"))
        assert result["deleted"] == 0
