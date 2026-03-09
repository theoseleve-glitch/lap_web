"""Tests for tasks.job_registry — PG-based job management.

All DB access is mocked via MagicMock connections.
Celery revoke is mocked via patch.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_conn():
    """Return a MagicMock that behaves like a DB connection."""
    conn = MagicMock()
    conn.execute = MagicMock()
    conn.commit = MagicMock()
    return conn


def _make_job_row(
    job_id="job-1",
    workspace_id=1,
    status="running",
    celery_task_id="celery-abc",
    file_path="/data/test.csv",
    file_size=1024,
    batch_job_id=None,
):
    """Return a dict mimicking a row from ingestion_jobs."""
    return {
        "job_id": job_id,
        "workspace_id": workspace_id,
        "status": status,
        "celery_task_id": celery_task_id,
        "file_path": file_path,
        "file_size": file_size,
        "batch_job_id": batch_job_id,
        "stage_name": None,
        "stage_index": None,
        "stage_total": None,
        "error_message": None,
        "error_class": None,
        "pause_reason": None,
    }


# ---------------------------------------------------------------------------
# create_job
# ---------------------------------------------------------------------------


class TestCreateJob:
    """create_job inserts a row into ingestion_jobs."""

    def test_inserts_row_and_commits(self):
        from tasks.job_registry import create_job

        conn = _make_mock_conn()

        create_job(
            conn,
            job_id="job-1",
            workspace_id=1,
            file_path="/data/test.csv",
            file_size=2048,
            celery_task_id="celery-xyz",
        )

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        sql_str = str(call_args[0][0])
        assert "INSERT" in sql_str.upper()
        assert "ingestion_jobs" in sql_str

        params = call_args[0][1]
        assert params["job_id"] == "job-1"
        assert params["workspace_id"] == 1
        assert params["file_path"] == "/data/test.csv"
        assert params["file_size"] == 2048
        assert params["celery_task_id"] == "celery-xyz"
        conn.commit.assert_called_once()

    def test_inserts_with_batch_job_id(self):
        from tasks.job_registry import create_job

        conn = _make_mock_conn()

        create_job(
            conn,
            job_id="job-2",
            workspace_id=1,
            file_path="/data/test2.csv",
            file_size=4096,
            batch_job_id=42,
        )

        params = conn.execute.call_args[0][1]
        assert params["batch_job_id"] == 42

    def test_default_celery_task_id_is_empty_string(self):
        from tasks.job_registry import create_job

        conn = _make_mock_conn()

        create_job(
            conn,
            job_id="job-3",
            workspace_id=1,
            file_path="/data/test3.csv",
            file_size=512,
        )

        params = conn.execute.call_args[0][1]
        assert params["celery_task_id"] == ""


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------


class TestGetJob:
    """get_job returns a dict for existing jobs, None otherwise."""

    def test_returns_dict_for_existing_job(self):
        from tasks.job_registry import get_job

        conn = _make_mock_conn()
        row = _make_job_row(job_id="job-1", workspace_id=1)
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        conn.execute.return_value = cursor

        result = get_job(conn, job_id="job-1", workspace_id=1)

        assert result is not None
        assert result["job_id"] == "job-1"
        assert result["workspace_id"] == 1

        # Verify SQL includes both job_id and workspace_id
        call_args = conn.execute.call_args
        sql_str = str(call_args[0][0])
        assert "job_id" in sql_str
        assert "workspace_id" in sql_str

    def test_returns_none_for_wrong_workspace(self):
        from tasks.job_registry import get_job

        conn = _make_mock_conn()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn.execute.return_value = cursor

        result = get_job(conn, job_id="job-1", workspace_id=999)
        assert result is None

    def test_returns_none_for_missing_job(self):
        from tasks.job_registry import get_job

        conn = _make_mock_conn()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn.execute.return_value = cursor

        result = get_job(conn, job_id="nonexistent", workspace_id=1)
        assert result is None


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------


class TestListJobs:
    """list_jobs returns a list of dicts scoped to workspace."""

    def test_returns_list_scoped_to_workspace(self):
        from tasks.job_registry import list_jobs

        conn = _make_mock_conn()
        rows = [
            _make_job_row(job_id="job-1", workspace_id=1),
            _make_job_row(job_id="job-2", workspace_id=1),
        ]
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        conn.execute.return_value = cursor

        result = list_jobs(conn, workspace_id=1)

        assert len(result) == 2
        assert result[0]["job_id"] == "job-1"
        assert result[1]["job_id"] == "job-2"

        # Verify SQL includes workspace_id and LIMIT
        call_args = conn.execute.call_args
        sql_str = str(call_args[0][0])
        assert "workspace_id" in sql_str
        assert "LIMIT" in sql_str.upper() or "limit" in sql_str

    def test_returns_empty_list_for_no_jobs(self):
        from tasks.job_registry import list_jobs

        conn = _make_mock_conn()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn.execute.return_value = cursor

        result = list_jobs(conn, workspace_id=1)
        assert result == []

    def test_respects_limit_parameter(self):
        from tasks.job_registry import list_jobs

        conn = _make_mock_conn()
        cursor = MagicMock()
        cursor.fetchall.return_value = [_make_job_row()]
        conn.execute.return_value = cursor

        list_jobs(conn, workspace_id=1, limit=10)

        params = conn.execute.call_args[0][1]
        assert params["limit"] == 10


# ---------------------------------------------------------------------------
# cancel_job
# ---------------------------------------------------------------------------


class TestCancelJob:
    """cancel_job revokes Celery task and updates status."""

    @patch("tasks.job_registry._revoke_celery_task")
    def test_cancels_running_job(self, mock_revoke):
        from tasks.job_registry import cancel_job

        conn = _make_mock_conn()
        row = _make_job_row(
            job_id="job-1", workspace_id=1, status="running",
            celery_task_id="celery-abc"
        )

        # First execute returns the SELECT result
        select_cursor = MagicMock()
        select_cursor.fetchone.return_value = row
        # Second execute is the UPDATE
        update_cursor = MagicMock()
        conn.execute.side_effect = [select_cursor, update_cursor]

        result = cancel_job(conn, job_id="job-1", workspace_id=1)

        assert result is True
        mock_revoke.assert_called_once_with("celery-abc")
        # Second call should be the UPDATE
        update_call = conn.execute.call_args_list[1]
        sql_str = str(update_call[0][0])
        assert "cancelled" in sql_str or "cancelled" in str(update_call[0][1])
        conn.commit.assert_called()

    @patch("tasks.job_registry._revoke_celery_task")
    def test_returns_false_for_missing_job(self, mock_revoke):
        from tasks.job_registry import cancel_job

        conn = _make_mock_conn()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn.execute.return_value = cursor

        result = cancel_job(conn, job_id="nonexistent", workspace_id=1)

        assert result is False
        mock_revoke.assert_not_called()

    @patch("tasks.job_registry._revoke_celery_task")
    def test_returns_false_for_terminal_status(self, mock_revoke):
        from tasks.job_registry import cancel_job

        conn = _make_mock_conn()

        for status in ("completed", "failed", "cancelled"):
            conn.reset_mock()
            mock_revoke.reset_mock()

            row = _make_job_row(
                job_id="job-done", workspace_id=1, status=status,
            )
            cursor = MagicMock()
            cursor.fetchone.return_value = row
            conn.execute.return_value = cursor

            result = cancel_job(conn, job_id="job-done", workspace_id=1)

            assert result is False, f"Expected False for status={status}"
            mock_revoke.assert_not_called()

    @patch("tasks.job_registry._revoke_celery_task")
    def test_returns_false_for_wrong_workspace(self, mock_revoke):
        from tasks.job_registry import cancel_job

        conn = _make_mock_conn()
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # workspace mismatch → no row
        conn.execute.return_value = cursor

        result = cancel_job(conn, job_id="job-1", workspace_id=999)

        assert result is False
        mock_revoke.assert_not_called()


# ---------------------------------------------------------------------------
# _TERMINAL_STATUSES constant
# ---------------------------------------------------------------------------


class TestTerminalStatuses:
    """Verify the _TERMINAL_STATUSES constant."""

    def test_contains_expected_statuses(self):
        from tasks.job_registry import _TERMINAL_STATUSES

        assert "completed" in _TERMINAL_STATUSES
        assert "failed" in _TERMINAL_STATUSES
        assert "cancelled" in _TERMINAL_STATUSES

    def test_is_a_set(self):
        from tasks.job_registry import _TERMINAL_STATUSES

        assert isinstance(_TERMINAL_STATUSES, (set, frozenset))
