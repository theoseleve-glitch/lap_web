"""Tests for tasks.batch_tasks and web.routes.batch — batch reprocessing.

All external dependencies (PG, Redis, Celery) are mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

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


def _make_batch_row(
    id=1,
    workspace_id=1,
    status="pending",
    total_sessions=0,
    completed_sessions=0,
):
    return {
        "id": id,
        "workspace_id": workspace_id,
        "status": status,
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
    }


def _make_session_row(session_id="sess-1", file_path="/data/s1.csv", file_size=2048):
    return {
        "session_id": session_id,
        "file_path": file_path,
        "file_size": file_size,
    }


# ---------------------------------------------------------------------------
# dispatch_batch Celery task
# ---------------------------------------------------------------------------


class TestDispatchBatch:
    """dispatch_batch creates ingestion_jobs and dispatches pipeline chains."""

    @patch("tasks.batch_tasks._build_and_dispatch_chain")
    @patch("tasks.batch_tasks.create_job")
    @patch("tasks.batch_tasks._get_pg_connection")
    def test_creates_jobs_for_each_session(
        self, mock_pg, mock_create_job, mock_dispatch
    ):
        from tasks.batch_tasks import dispatch_batch

        conn = _make_mock_conn()
        mock_pg.return_value = conn

        # First execute: SELECT batch_jobs row
        batch_cursor = MagicMock()
        batch_cursor.fetchone.return_value = _make_batch_row(
            id=1, workspace_id=1, status="pending"
        )

        # Second execute: UPDATE batch_jobs SET status='running'
        update_cursor = MagicMock()

        # Third execute: SELECT sessions
        sessions_cursor = MagicMock()
        sessions_cursor.fetchall.return_value = [
            _make_session_row(session_id="sess-1"),
            _make_session_row(session_id="sess-2"),
        ]

        # Fourth execute: UPDATE batch_jobs total_sessions
        update2_cursor = MagicMock()

        conn.execute.side_effect = [
            batch_cursor,
            update_cursor,
            sessions_cursor,
            update2_cursor,
        ]

        dispatch_batch(batch_job_id=1, workspace_id=1)

        # Should create an ingestion_jobs row for each session
        assert mock_create_job.call_count == 2
        # Should dispatch a pipeline chain for each session
        assert mock_dispatch.call_count == 2

    @patch("tasks.batch_tasks._build_and_dispatch_chain")
    @patch("tasks.batch_tasks.create_job")
    @patch("tasks.batch_tasks._get_pg_connection")
    def test_empty_sessions_marks_completed(
        self, mock_pg, mock_create_job, mock_dispatch
    ):
        from tasks.batch_tasks import dispatch_batch

        conn = _make_mock_conn()
        mock_pg.return_value = conn

        # First execute: SELECT batch_jobs row
        batch_cursor = MagicMock()
        batch_cursor.fetchone.return_value = _make_batch_row(
            id=1, workspace_id=1, status="pending"
        )

        # Second execute: UPDATE batch_jobs SET status='running'
        update_cursor = MagicMock()

        # Third execute: SELECT sessions (empty)
        sessions_cursor = MagicMock()
        sessions_cursor.fetchall.return_value = []

        # Fourth execute: UPDATE batch_jobs SET status='completed'
        update2_cursor = MagicMock()

        conn.execute.side_effect = [
            batch_cursor,
            update_cursor,
            sessions_cursor,
            update2_cursor,
        ]

        dispatch_batch(batch_job_id=1, workspace_id=1)

        # Should NOT create any jobs or dispatch chains
        mock_create_job.assert_not_called()
        mock_dispatch.assert_not_called()

        # Verify the last UPDATE set status='completed'
        last_call = conn.execute.call_args_list[-1]
        sql_str = str(last_call[0][0])
        assert "completed" in sql_str or "completed" in str(last_call)


# ---------------------------------------------------------------------------
# Batch API routes
# ---------------------------------------------------------------------------


@pytest.fixture
def batch_app():
    """Create a minimal Flask app with the batch blueprint."""
    from flask import Flask, g
    from web.routes.batch import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)

    @app.before_request
    def _set_context():
        g.workspace_id = 1
        g.user_id = 42
        g.current_user_id = 42

    return app


@pytest.fixture
def batch_client(batch_app):
    """Flask test client for batch routes."""
    return batch_app.test_client()


class TestBatchReanalyzeEndpoint:
    """POST /api/v1/batch-reanalyze creates a batch and returns 202."""

    @patch("web.routes.batch._dispatch_batch_task")
    @patch("web.routes.batch.get_pg_connection")
    def test_returns_202_with_batch_job_id(
        self, mock_pg, mock_dispatch, batch_client
    ):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn

        # INSERT RETURNING id
        insert_cursor = MagicMock()
        insert_cursor.fetchone.return_value = {"id": 42}
        mock_conn.execute.return_value = insert_cursor

        resp = batch_client.post("/api/v1/batch-reanalyze", json={})

        assert resp.status_code == 202
        body = resp.get_json()
        assert "batch_job_id" in body["data"]
        assert body["data"]["batch_job_id"] == 42
        mock_dispatch.assert_called_once()


class TestListBatchJobs:
    """GET /api/v1/batch-jobs returns 200 with batches."""

    @patch("web.routes.batch.get_pg_connection")
    def test_returns_200_with_batches_list(self, mock_pg, batch_client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            _make_batch_row(id=1, status="running"),
            _make_batch_row(id=2, status="completed"),
        ]
        mock_conn.execute.return_value = cursor

        resp = batch_client.get("/api/v1/batch-jobs")

        assert resp.status_code == 200
        body = resp.get_json()
        assert "batches" in body["data"]
        assert len(body["data"]["batches"]) == 2


class TestCancelBatchJob:
    """POST /api/v1/batch-jobs/<id>/cancel returns 200."""

    @patch("web.routes.batch._revoke_batch_tasks")
    @patch("web.routes.batch.get_pg_connection")
    def test_returns_200_when_cancelled(
        self, mock_pg, mock_revoke, batch_client
    ):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn

        # SELECT batch_jobs row
        select_cursor = MagicMock()
        select_cursor.fetchone.return_value = _make_batch_row(
            id=1, workspace_id=1, status="running"
        )

        # UPDATE status
        update_cursor = MagicMock()

        mock_conn.execute.side_effect = [select_cursor, update_cursor]

        resp = batch_client.post("/api/v1/batch-jobs/1/cancel")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["cancelled"] is True
        mock_revoke.assert_called_once()

    @patch("web.routes.batch.get_pg_connection")
    def test_returns_404_when_not_found(self, mock_pg, batch_client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn

        cursor = MagicMock()
        cursor.fetchone.return_value = None
        mock_conn.execute.return_value = cursor

        resp = batch_client.post("/api/v1/batch-jobs/999/cancel")

        assert resp.status_code == 404
