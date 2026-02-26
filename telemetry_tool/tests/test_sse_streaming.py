"""Tests for web.routes.jobs — SSE streaming + Job API.

Uses a minimal Flask app with the jobs blueprint registered.
All DB access is mocked via MagicMock connections.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a minimal Flask app with the jobs blueprint."""
    from flask import Flask, g
    from web.routes.jobs import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)

    @app.before_request
    def _set_context():
        g.workspace_id = 1
        g.user_id = 42

    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job_dict(
    job_id="job-1",
    workspace_id=1,
    status="running",
    stage_name="gps_filter",
    stage_index=2,
    stage_total=15,
    error_message=None,
    celery_task_id="celery-abc",
):
    return {
        "job_id": job_id,
        "workspace_id": workspace_id,
        "status": status,
        "stage_name": stage_name,
        "stage_index": stage_index,
        "stage_total": stage_total,
        "error_message": error_message,
        "celery_task_id": celery_task_id,
        "file_path": "/data/test.csv",
        "file_size": 1024,
        "batch_job_id": None,
        "pause_reason": None,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/jobs — list jobs
# ---------------------------------------------------------------------------


class TestListJobs:
    """GET /api/v1/jobs returns 200 with jobs list."""

    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.list_jobs")
    def test_returns_200_with_jobs_list(self, mock_list, mock_pg, client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_list.return_value = [
            _make_job_dict(job_id="job-1"),
            _make_job_dict(job_id="job-2"),
        ]

        resp = client.get("/api/v1/jobs")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]
        assert "jobs" in data
        assert len(data["jobs"]) == 2
        mock_list.assert_called_once_with(mock_conn, 1, limit=50)


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/<job_id>/status — get job status
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    """GET /api/v1/jobs/<job_id>/status returns 200 or 404."""

    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.get_job")
    def test_returns_200_with_job_data(self, mock_get, mock_pg, client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_get.return_value = _make_job_dict(job_id="job-1")

        resp = client.get("/api/v1/jobs/job-1/status")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]
        assert data["job_id"] == "job-1"
        assert data["status"] == "running"
        mock_get.assert_called_once_with(mock_conn, "job-1", 1)

    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.get_job")
    def test_returns_404_when_not_found(self, mock_get, mock_pg, client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_get.return_value = None

        resp = client.get("/api/v1/jobs/nonexistent/status")

        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/<job_id>/cancel — cancel job
# ---------------------------------------------------------------------------


class TestCancelJob:
    """POST /api/v1/jobs/<job_id>/cancel returns 200 or 404."""

    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.cancel_job")
    def test_returns_200_when_cancelled(self, mock_cancel, mock_pg, client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_cancel.return_value = True

        resp = client.post("/api/v1/jobs/job-1/cancel")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["cancelled"] is True
        mock_cancel.assert_called_once_with(mock_conn, "job-1", 1)

    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.cancel_job")
    def test_returns_404_when_not_cancellable(self, mock_cancel, mock_pg, client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_cancel.return_value = False

        resp = client.post("/api/v1/jobs/job-1/cancel")

        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/<job_id>/resume — resume paused job
# ---------------------------------------------------------------------------


class TestResumeJob:
    """POST /api/v1/jobs/<job_id>/resume returns 200 or 409."""

    @patch("web.routes.jobs._dispatch_finalize")
    @patch("web.routes.jobs._load_pipeline_context")
    @patch("web.routes.jobs._get_redis")
    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.get_job")
    def test_returns_200_when_paused_job_resumed(
        self, mock_get, mock_pg, mock_redis, mock_load_ctx, mock_dispatch, client
    ):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_get.return_value = _make_job_dict(
            job_id="job-1", status="paused"
        )

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client

        mock_ctx = MagicMock()
        mock_load_ctx.return_value = mock_ctx

        resp = client.post(
            "/api/v1/jobs/job-1/resume",
            json={"joker_decision": "accept"},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["resumed"] is True

        # Verify joker decision stored in context
        mock_ctx.set_joker_decision.assert_called_once_with("accept")
        mock_ctx.save.assert_called_once()

        # Verify finalize task dispatched
        mock_dispatch.assert_called_once_with("job-1")

    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.get_job")
    def test_returns_409_when_not_paused(self, mock_get, mock_pg, client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_get.return_value = _make_job_dict(
            job_id="job-1", status="running"
        )

        resp = client.post(
            "/api/v1/jobs/job-1/resume",
            json={"joker_decision": "accept"},
        )

        assert resp.status_code == 409
        data = resp.get_json()
        assert "error" in data

    @patch("web.routes.jobs.get_pg_connection")
    @patch("web.routes.jobs.get_job")
    def test_returns_404_when_job_not_found(self, mock_get, mock_pg, client):
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn
        mock_get.return_value = None

        resp = client.post(
            "/api/v1/jobs/job-1/resume",
            json={"joker_decision": "accept"},
        )

        assert resp.status_code == 404
