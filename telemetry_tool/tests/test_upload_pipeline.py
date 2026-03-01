"""Tests for pipeline dispatch after CSV upload.

Verifies that the POST /api/v1/files/upload endpoint dispatches the
Celery pipeline chain after saving the file, and that dispatch failure
does not break the upload response.
"""

import io
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_app(tmp_dir):
    """Create a minimal Flask app with the api_v1_data blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["DATA_RAW_DIR"] = tmp_dir
    app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024

    from web.routes.api_v1_data import bp

    app.register_blueprint(bp)
    return app


def _upload(client, filename, content):
    """Helper to POST a file upload via the v1 endpoint."""
    data = {"file": (io.BytesIO(content), filename)}
    return client.post(
        "/api/v1/files/upload",
        data=data,
        content_type="multipart/form-data",
    )


VALID_CSV = b"speed,time,lat,lon\n100,1.0,45.0,9.0\n"


class TestUploadPipelineDispatch:
    """Pipeline chain is dispatched after a successful CSV upload."""

    @pytest.fixture(autouse=True)
    def _setup_teardown(self, tmp_path):
        self.tmp_dir = str(tmp_path)
        self.app = _make_app(self.tmp_dir)

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_upload_dispatches_pipeline(self, mock_db):
        """Upload dispatches the pipeline chain and returns job_id."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        mock_redis_instance = MagicMock()
        mock_chain_instance = MagicMock()

        with patch("redis.Redis.from_url", return_value=mock_redis_instance), \
             patch(
                 "tasks.pipeline_tasks.build_pipeline_chain",
                 return_value=mock_chain_instance,
             ) as mock_build, \
             patch(
                 "pipeline_context.PipelineContext.create",
             ) as mock_ctx_create:

            with self.app.test_client() as c:
                resp = _upload(c, "session_01.csv", VALID_CSV)

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert "job_id" in data["data"]
            assert data["data"]["pipeline_status"] == "dispatched"
            assert data["data"]["filename"] == "session_01.csv"

            # Pipeline chain was built and dispatched
            mock_build.assert_called_once()
            mock_chain_instance.apply_async.assert_called_once()

            # PipelineContext.create was called with correct params
            mock_ctx_create.assert_called_once()
            call_kwargs = mock_ctx_create.call_args
            assert call_kwargs.kwargs["redis_client"] is mock_redis_instance
            assert call_kwargs.kwargs["session_id"] == "session_01"
            assert call_kwargs.kwargs["file_path"].endswith("session_01.csv")

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_upload_succeeds_when_pipeline_fails(self, mock_db):
        """Upload still returns 200 even if pipeline dispatch raises."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        # Make redis import fail to simulate missing dependency
        with patch("redis.Redis.from_url", side_effect=ConnectionError("no redis")):
            with self.app.test_client() as c:
                resp = _upload(c, "session_02.csv", VALID_CSV)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["data"]["filename"] == "session_02.csv"
        assert data["data"]["size_bytes"] > 0
        # No pipeline fields when dispatch failed
        assert "job_id" not in data["data"]
        assert "pipeline_status" not in data["data"]

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_response_includes_job_id_uuid(self, mock_db):
        """The returned job_id is a valid UUID4 string."""
        import uuid

        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        mock_redis_instance = MagicMock()
        mock_chain_instance = MagicMock()

        with patch("redis.Redis.from_url", return_value=mock_redis_instance), \
             patch(
                 "tasks.pipeline_tasks.build_pipeline_chain",
                 return_value=mock_chain_instance,
             ), \
             patch("pipeline_context.PipelineContext.create"):

            with self.app.test_client() as c:
                resp = _upload(c, "session_03.csv", VALID_CSV)

            data = resp.get_json()
            job_id = data["data"]["job_id"]
            # Should be parseable as UUID
            parsed = uuid.UUID(job_id)
            assert str(parsed) == job_id
            assert parsed.version == 4

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_pipeline_context_created_with_correct_params(self, mock_db):
        """PipelineContext.create receives workspace_id, session_id, file_path."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        mock_redis_instance = MagicMock()
        mock_chain_instance = MagicMock()

        with patch("redis.Redis.from_url", return_value=mock_redis_instance), \
             patch(
                 "tasks.pipeline_tasks.build_pipeline_chain",
                 return_value=mock_chain_instance,
             ), \
             patch(
                 "pipeline_context.PipelineContext.create",
             ) as mock_ctx_create:

            with self.app.test_client() as c:
                resp = _upload(c, "my_race_data.csv", VALID_CSV)

            assert resp.status_code == 200

            call_kwargs = mock_ctx_create.call_args.kwargs
            # session_id derived from filename without .csv
            assert call_kwargs["session_id"] == "my_race_data"
            # file_path points to the saved file
            assert call_kwargs["file_path"].endswith("my_race_data.csv")
            # workspace_id defaults to "default" when g.workspace_id is None
            assert call_kwargs["workspace_id"] == "default"
            # redis_client is the mocked instance
            assert call_kwargs["redis_client"] is mock_redis_instance

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_session_row_created_before_pipeline(self, mock_db):
        """A session row is inserted in the DB before pipeline dispatch."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        mock_redis_instance = MagicMock()
        mock_chain_instance = MagicMock()

        with patch("redis.Redis.from_url", return_value=mock_redis_instance), \
             patch(
                 "tasks.pipeline_tasks.build_pipeline_chain",
                 return_value=mock_chain_instance,
             ), \
             patch("pipeline_context.PipelineContext.create"):

            with self.app.test_client() as c:
                resp = _upload(c, "test_session.csv", VALID_CSV)

            assert resp.status_code == 200

            # Verify session row INSERT was attempted
            mock_conn.execute.assert_called()
            insert_calls = [
                c for c in mock_conn.execute.call_args_list
                if "INSERT" in str(c) and "sessions" in str(c)
            ]
            assert len(insert_calls) >= 1, "Expected INSERT INTO sessions call"
            mock_conn.commit.assert_called()

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_pipeline_dispatch_with_workspace_id(self, mock_db):
        """When g.workspace_id is set, it is passed to PipelineContext."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        mock_redis_instance = MagicMock()
        mock_chain_instance = MagicMock()

        with patch("redis.Redis.from_url", return_value=mock_redis_instance), \
             patch(
                 "tasks.pipeline_tasks.build_pipeline_chain",
                 return_value=mock_chain_instance,
             ), \
             patch(
                 "pipeline_context.PipelineContext.create",
             ) as mock_ctx_create:

            with self.app.test_client() as c:
                # Simulate tenant middleware setting workspace_id
                @self.app.before_request
                def _set_workspace():
                    g.workspace_id = 42

                resp = _upload(c, "ws_session.csv", VALID_CSV)

            assert resp.status_code == 200
            call_kwargs = mock_ctx_create.call_args.kwargs
            assert call_kwargs["workspace_id"] == "42"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_file_saved_even_when_pipeline_dispatch_fails(self, mock_db):
        """The CSV file is saved to disk regardless of pipeline dispatch outcome."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        with patch("redis.Redis.from_url", side_effect=Exception("boom")):
            with self.app.test_client() as c:
                resp = _upload(c, "saved_file.csv", VALID_CSV)

        assert resp.status_code == 200
        # File should exist on disk
        saved = os.path.join(self.tmp_dir, "saved_file.csv")
        assert os.path.exists(saved)
        with open(saved, "rb") as fh:
            assert fh.read() == VALID_CSV
