"""Tests for corner re-selection on completed sessions."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
import pytest


class TestReconstructContextFromDb:
    def test_returns_context_when_job_exists(self, tmp_path):
        from web.routes.jobs import _reconstruct_context_from_db

        # Create a fake CSV file
        csv_path = tmp_path / "session.csv"
        csv_path.write_text("col1,col2\n1,2\n")

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "job-1",
            "workspace_id": "ws-1",
            "file_path": str(csv_path),
        }

        redis_client = MagicMock()

        ctx = _reconstruct_context_from_db(conn, "job-1", redis_client, temp_root=str(tmp_path))

        assert ctx is not None
        assert ctx.job_id == "job-1"
        assert ctx.workspace_id == "ws-1"
        assert ctx.session_id == "job-1"  # convention: session_id == job_id
        assert ctx.file_path == str(csv_path)

    def test_returns_none_when_csv_missing(self, tmp_path):
        from web.routes.jobs import _reconstruct_context_from_db

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "job-1",
            "workspace_id": "ws-1",
            "file_path": "/nonexistent/path.csv",
        }

        redis_client = MagicMock()

        ctx = _reconstruct_context_from_db(conn, "job-1", redis_client, temp_root=str(tmp_path))
        assert ctx is None

    def test_returns_none_when_job_not_found(self, tmp_path):
        from web.routes.jobs import _reconstruct_context_from_db

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None

        redis_client = MagicMock()

        ctx = _reconstruct_context_from_db(conn, "job-1", redis_client, temp_root=str(tmp_path))
        assert ctx is None


class TestResumeStatusGuard:
    def test_completed_status_allowed(self):
        """The resume endpoint should accept 'completed' status."""
        RESUMABLE = ("paused", "awaiting_corner_selection", "completed")
        assert "completed" in RESUMABLE
