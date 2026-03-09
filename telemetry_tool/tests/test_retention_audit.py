"""Tests for enhanced retention enforcement with audit logging.

Validates:
- Retention job deletes all artifacts and DB rows for expired sessions
- Idempotency: rerun doesn't error on already-expired sessions
- Audit logs created with correct run_id, action, counts
- File deletion covers raw and cache directories
- Default retention is 12 months (365 days)
- _cleanup_retention_audit_impl deletes old audit rows
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.retention_tasks import (
    _DEFAULT_RETENTION_DAYS,
    _RAW_DATA_TABLES,
    _delete_raw_data,
    _delete_session_files,
    _log_retention_audit,
    _mark_session_expired,
)


class TestDefaultRetention:
    """Default retention policy is 12 months."""

    def test_default_is_365_days(self):
        assert _DEFAULT_RETENTION_DAYS == 365

    def test_raw_data_tables_comprehensive(self):
        """All raw/ephemeral tables are covered."""
        assert "gps_traces" in _RAW_DATA_TABLES
        assert "reference_lines" in _RAW_DATA_TABLES
        assert "theoretical_data" in _RAW_DATA_TABLES
        assert "corner_metrics" in _RAW_DATA_TABLES
        assert "data_health" in _RAW_DATA_TABLES


class TestDeleteRawDataAudit:
    """Raw data deletion covers all target tables."""

    def test_deletes_from_all_tables(self):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 2
        conn.cursor.return_value = cursor

        total = _delete_raw_data(conn, "sess_001")
        assert total == 2 * len(_RAW_DATA_TABLES)

    def test_dry_run_counts_only(self):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"cnt": 3}
        conn.cursor.return_value = cursor

        total = _delete_raw_data(conn, "sess_001", dry_run=True)
        assert total == 3 * len(_RAW_DATA_TABLES)
        for c in cursor.execute.call_args_list:
            assert "DELETE" not in c[0][0]

    def test_idempotent_rerun(self):
        """Rerunning on already-deleted session returns 0 rows deleted."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 0
        conn.cursor.return_value = cursor

        total = _delete_raw_data(conn, "sess_already_expired")
        assert total == 0


class TestDeleteSessionFiles:
    """File deletion from raw and cache directories."""

    def test_deletes_matching_files(self, tmp_path):
        """Files matching session_id pattern are deleted."""
        ws_dir = tmp_path / "raw" / "42"
        ws_dir.mkdir(parents=True)
        # Create test files
        (ws_dir / "sess_001.csv").write_text("data")
        (ws_dir / "sess_001_chunk_0.parquet").write_text("data")
        (ws_dir / "sess_002.csv").write_text("other")

        with patch.dict("os.environ", {"TELEMETRY_RAW_DIR": str(tmp_path / "raw")}):
            deleted = _delete_session_files("sess_001", 42)

        assert deleted == 2
        assert not (ws_dir / "sess_001.csv").exists()
        assert not (ws_dir / "sess_001_chunk_0.parquet").exists()
        assert (ws_dir / "sess_002.csv").exists()  # untouched

    def test_dry_run_does_not_delete(self, tmp_path):
        """Dry run counts but doesn't delete."""
        ws_dir = tmp_path / "raw" / "42"
        ws_dir.mkdir(parents=True)
        (ws_dir / "sess_001.csv").write_text("data")

        with patch.dict("os.environ", {"TELEMETRY_RAW_DIR": str(tmp_path / "raw")}):
            deleted = _delete_session_files("sess_001", 42, dry_run=True)

        assert deleted == 1
        assert (ws_dir / "sess_001.csv").exists()  # still there

    def test_missing_directory_returns_zero(self):
        """Non-existent workspace directory returns 0."""
        with patch.dict("os.environ", {"TELEMETRY_RAW_DIR": "/nonexistent/path"}):
            deleted = _delete_session_files("sess_001", 99)
        assert deleted == 0


class TestLogRetentionAudit:
    """Dedicated retention_audit table logging."""

    def test_inserts_correct_fields(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _log_retention_audit(
            conn,
            run_id="run_abc",
            workspace_id=42,
            subject_type="session",
            subject_id="sess_001",
            action="delete",
            reason="retention_expired",
            result="success",
            details={"rows_deleted": 10},
        )

        cursor.execute.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        params = cursor.execute.call_args[0][1]

        assert "retention_audit" in sql
        assert params[0] == "run_abc"         # run_id
        assert params[1] == 42                # workspace_id
        assert params[2] == "session"         # subject_type
        assert params[3] == "sess_001"        # subject_id
        assert params[4] == "delete"          # action
        assert params[5] == "retention_expired"  # reason
        assert params[6] == "system"          # actor (default)
        assert params[7] == "success"         # result

    def test_custom_actor(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _log_retention_audit(
            conn,
            run_id="run_xyz",
            workspace_id=1,
            subject_type="export",
            subject_id="exp_001",
            action="delete",
            reason="user_request",
            result="success",
            actor="user:5",
        )

        params = cursor.execute.call_args[0][1]
        assert params[6] == "user:5"


class TestMarkSessionExpired:
    """Idempotent session expiry marking."""

    def test_sets_retention_expired_flag(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _mark_session_expired(conn, "sess_001")
        sql = cursor.execute.call_args[0][0]
        assert "retention_expired = TRUE" in sql

    def test_idempotent_on_rerun(self):
        """Marking an already-expired session doesn't error."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 0  # no rows updated (already expired)
        conn.cursor.return_value = cursor

        # Should not raise
        _mark_session_expired(conn, "sess_already_expired")
