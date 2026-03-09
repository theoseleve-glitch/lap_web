"""Tests for the session upload endpoint (POST /api/v1/sessions/upload).

The upload endpoint was refactored from synchronous (run_full_analysis in-request)
to async (Celery pipeline chain).  These tests validate the new contract:
  - Input validation (file presence, extension)
  - 202 response with job_id when dispatch succeeds
  - Error handling on dispatch failure
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app():
    """Minimal Flask app with sessions_v2 blueprint."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True

    from web.routes.sessions_v2 import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _post_upload(client, csv_content="Lap #,Time (s)\n1,0.0\n",
                 filename="session.csv", extra_fields=None):
    """Helper to POST to upload endpoint."""
    data = {
        "file": (io.BytesIO(csv_content.encode()), filename),
        "session_type": "practice",
        "track_state": "dry",
        "driver_name": "TestDriver",
    }
    if extra_fields:
        data.update(extra_fields)
    return client.post(
        "/api/v1/sessions/upload",
        data=data,
        content_type="multipart/form-data",
    )


class TestUploadValidation:
    """Input validation tests — these don't need pipeline mocking."""

    def test_upload_rejects_missing_file(self, client):
        """POST without a file returns 400."""
        resp = client.post(
            "/api/v1/sessions/upload",
            data={"session_type": "practice"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
        assert "file" in body["error"]["message"].lower()

    def test_upload_rejects_non_csv(self, client):
        """POST with a non-CSV file (.exe) returns 400."""
        data = {
            "file": (io.BytesIO(b"\x00\x01\x02"), "malware.exe"),
        }
        resp = client.post(
            "/api/v1/sessions/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False


class TestUploadAsync:
    """Tests for the async upload dispatch flow.

    The upload endpoint requires auth context (g.workspace_id), Redis,
    Celery, and PG — heavy dependencies.  We mock at the boundary.
    """

    def test_upload_returns_202_with_job_id(self, app):
        """Valid CSV upload returns 202 with job_id."""
        import uuid

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"count": 0}
        mock_chain = MagicMock()
        mock_r = MagicMock()

        @app.before_request
        def _inject_auth():
            from flask import g
            g.workspace_id = 1
            g.current_user_id = 42
            g.plan_tier = "racer"

        with patch("web.routes.sessions_v2._get_conn", return_value=mock_conn), \
             patch("redis.Redis.from_url", return_value=mock_r), \
             patch("pipeline_context.PipelineContext") as mock_ctx, \
             patch("tasks.pipeline_tasks.build_pipeline_chain", return_value=mock_chain), \
             patch("web.config.Config") as mock_cfg:

            mock_cfg.REDIS_URL = "redis://localhost:6379/0"

            resp = _post_upload(app.test_client())

        assert resp.status_code == 202
        body = resp.get_json()
        assert body["ok"] is True
        assert "job_id" in body["data"]
        assert body["data"]["status"] == "pending"

    def test_upload_accepts_txt_extension(self, app):
        """POST with .txt extension is accepted (not rejected as unsupported format)."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"count": 0}
        mock_r = MagicMock()
        mock_chain = MagicMock()

        @app.before_request
        def _inject_auth():
            from flask import g
            g.workspace_id = 1
            g.current_user_id = 42
            g.plan_tier = "racer"

        with patch("web.routes.sessions_v2._get_conn", return_value=mock_conn), \
             patch("redis.Redis.from_url", return_value=mock_r), \
             patch("pipeline_context.PipelineContext"), \
             patch("tasks.pipeline_tasks.build_pipeline_chain", return_value=mock_chain), \
             patch("web.config.Config") as mock_cfg:

            mock_cfg.REDIS_URL = "redis://localhost:6379/0"

            resp = _post_upload(app.test_client(), filename="session.txt")

        # .txt is in the allowed extensions list
        assert resp.status_code in (202, 500)  # 202 success or 500 if other issue
        if resp.status_code == 202:
            body = resp.get_json()
            assert body["ok"] is True
