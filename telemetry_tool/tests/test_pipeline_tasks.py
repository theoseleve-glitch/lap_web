"""Tests for tasks.pipeline_tasks — three Celery task groups + helpers.

All external dependencies are mocked:
- PipelineContext (Redis-backed)
- _get_pg_connection / _get_redis
- Stage runner functions
- acquire_workspace_lock / release_workspace_lock / check_worker_memory
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

def _make_mock_ctx(job_id="job-1", workspace_id="ws-1", session_id="sess-1"):
    """Return a MagicMock that behaves like a PipelineContext."""
    ctx = MagicMock()
    ctx.job_id = job_id
    ctx.workspace_id = workspace_id
    ctx.session_id = session_id
    ctx.file_path = "/data/test.csv"
    ctx.current_stage = None
    ctx.stage_status = None
    ctx.errors = []
    return ctx


def _make_mock_conn():
    """Return a MagicMock that behaves like a DB connection."""
    conn = MagicMock()
    conn.execute = MagicMock()
    conn.commit = MagicMock()
    return conn


# ---------------------------------------------------------------------------
# _update_job_progress
# ---------------------------------------------------------------------------


class TestUpdateJobProgress:
    """_update_job_progress writes correct SQL to the PG connection."""

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_updates_with_all_fields(self, mock_get_pg):
        from tasks.pipeline_tasks import _update_job_progress

        conn = _make_mock_conn()
        mock_get_pg.return_value = conn

        _update_job_progress(
            job_id="job-1",
            status="running",
            stage_name="gps_filter",
            stage_index=1,
            stage_total=15,
            error_message=None,
            error_class=None,
            pause_reason=None,
        )

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        # First arg is sqlalchemy.text object
        sql_str = str(call_args[0][0])
        assert "ingestion_jobs" in sql_str
        assert "status" in sql_str
        # Second arg is the params dict
        params = call_args[0][1]
        assert params["job_id"] == "job-1"
        assert params["status"] == "running"
        assert params["stage_name"] == "gps_filter"
        assert params["stage_index"] == 1
        assert params["stage_total"] == 15
        conn.commit.assert_called_once()

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_updates_with_error_fields(self, mock_get_pg):
        from tasks.pipeline_tasks import _update_job_progress

        conn = _make_mock_conn()
        mock_get_pg.return_value = conn

        _update_job_progress(
            job_id="job-2",
            status="failed",
            stage_name="scoring",
            stage_index=10,
            stage_total=15,
            error_message="corrupt data",
            error_class="fatal",
            pause_reason=None,
        )

        params = conn.execute.call_args[0][1]
        assert params["error_message"] == "corrupt data"
        assert params["error_class"] == "fatal"

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_updates_with_pause_reason(self, mock_get_pg):
        from tasks.pipeline_tasks import _update_job_progress

        conn = _make_mock_conn()
        mock_get_pg.return_value = conn

        _update_job_progress(
            job_id="job-3",
            status="paused",
            stage_name="analyze",
            stage_index=5,
            stage_total=15,
            error_message=None,
            error_class=None,
            pause_reason="joker confirmation needed",
        )

        params = conn.execute.call_args[0][1]
        assert params["pause_reason"] == "joker confirmation needed"
        assert params["status"] == "paused"


# ---------------------------------------------------------------------------
# pipeline_ingest
# ---------------------------------------------------------------------------


class TestPipelineIngest:
    """pipeline_ingest task: stages 1-4, acquires workspace lock."""

    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._run_ingest_stages")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_returns_job_id_on_success(
        self, MockCtx, mock_redis, mock_lock, mock_stages, mock_progress
    ):
        from tasks.pipeline_tasks import pipeline_ingest

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx

        result = pipeline_ingest("job-1")

        assert result == "job-1"
        MockCtx.load.assert_called_once_with(mock_redis_client, "job-1")
        mock_lock.assert_called_once_with(mock_redis_client, "ws-1", "job-1")
        mock_stages.assert_called_once_with(ctx)
        ctx.save.assert_called()

    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=False)
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_raises_transient_on_lock_failure(
        self, MockCtx, mock_redis, mock_lock, mock_progress
    ):
        from tasks.pipeline_tasks import pipeline_ingest
        from pipeline_errors import TransientError

        mock_redis.return_value = MagicMock()
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx

        with pytest.raises(TransientError):
            pipeline_ingest("job-1")

    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks._run_ingest_stages")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_marks_failed_on_fatal_error(
        self, MockCtx, mock_redis, mock_lock, mock_stages, mock_release, mock_progress
    ):
        from tasks.pipeline_tasks import pipeline_ingest
        from pipeline_errors import FatalError

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx
        mock_stages.side_effect = FatalError("corrupt CSV")

        with pytest.raises(FatalError):
            pipeline_ingest("job-1")

        # Should have called _update_job_progress with "failed"
        mock_progress.assert_called()
        # Find the failed call
        failed_calls = [
            c for c in mock_progress.call_args_list
            if c.kwargs.get("status") == "failed" or (len(c.args) > 1 and c.args[1] == "failed")
        ]
        # Check via kwargs
        assert any(
            c.kwargs.get("status") == "failed"
            for c in mock_progress.call_args_list
        ), "Expected _update_job_progress to be called with status='failed'"

        # Should release the lock
        mock_release.assert_called_once_with(mock_redis_client, "ws-1", "job-1")


# ---------------------------------------------------------------------------
# pipeline_analyze
# ---------------------------------------------------------------------------


class TestPipelineAnalyze:
    """pipeline_analyze task: stages 5-8, handles InteractionRequired."""

    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._run_analyze_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_returns_job_id_on_success(
        self, MockCtx, mock_redis, mock_stages, mock_progress
    ):
        from tasks.pipeline_tasks import pipeline_analyze

        mock_redis.return_value = MagicMock()
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx

        result = pipeline_analyze("job-1")

        assert result == "job-1"
        mock_stages.assert_called_once_with(ctx)
        ctx.save.assert_called()

    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks._run_analyze_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_returns_none_on_interaction_required(
        self, MockCtx, mock_redis, mock_stages, mock_progress
    ):
        from tasks.pipeline_tasks import pipeline_analyze
        from pipeline_errors import InteractionRequired

        mock_redis.return_value = MagicMock()
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx
        mock_stages.side_effect = InteractionRequired(
            "joker confirmation", {"session_id": "sess-1"}
        )

        result = pipeline_analyze("job-1")

        assert result is None
        # Should set status to "paused"
        assert any(
            c.kwargs.get("status") == "paused"
            for c in mock_progress.call_args_list
        ), "Expected _update_job_progress called with status='paused'"

    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks._run_analyze_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_marks_failed_on_fatal_error(
        self, MockCtx, mock_redis, mock_stages, mock_release, mock_progress
    ):
        from tasks.pipeline_tasks import pipeline_analyze
        from pipeline_errors import FatalError

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx
        mock_stages.side_effect = FatalError("bad data")

        with pytest.raises(FatalError):
            pipeline_analyze("job-1")

        assert any(
            c.kwargs.get("status") == "failed"
            for c in mock_progress.call_args_list
        )
        mock_release.assert_called_once_with(mock_redis_client, "ws-1", "job-1")


# ---------------------------------------------------------------------------
# pipeline_finalize
# ---------------------------------------------------------------------------


class TestPipelineFinalize:
    """pipeline_finalize task: stages 9-15, cleanup, release lock."""

    @patch("tasks.pipeline_tasks._increment_batch_counter")
    @patch("tasks.pipeline_tasks.check_worker_memory", return_value=False)
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._run_finalize_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_returns_job_id_and_cleans_up(
        self, MockCtx, mock_redis, mock_stages, mock_lock, mock_release,
        mock_progress, mock_memory, mock_batch_counter
    ):
        from tasks.pipeline_tasks import pipeline_finalize

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx

        result = pipeline_finalize("job-1")

        assert result == "job-1"
        mock_lock.assert_called_once_with(mock_redis_client, "ws-1", "job-1")
        mock_stages.assert_called_once_with(ctx)
        ctx.cleanup.assert_called_once()
        mock_release.assert_called_once_with(mock_redis_client, "ws-1", "job-1")
        # Should update status to "completed"
        assert any(
            c.kwargs.get("status") == "completed"
            for c in mock_progress.call_args_list
        )
        # Should increment batch completed counter
        mock_batch_counter.assert_called_once_with("job-1", "completed_sessions")

    @patch("tasks.pipeline_tasks.check_worker_memory", return_value=False)
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks._run_finalize_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_handles_none_input_from_paused_chain(
        self, MockCtx, mock_redis, mock_stages, mock_release,
        mock_progress, mock_memory
    ):
        from tasks.pipeline_tasks import pipeline_finalize

        result = pipeline_finalize(None)

        assert result is None
        # Should NOT try to load context or run stages
        MockCtx.load.assert_not_called()
        mock_stages.assert_not_called()

    @patch("tasks.pipeline_tasks._increment_batch_counter")
    @patch("tasks.pipeline_tasks.check_worker_memory", return_value=True)
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._run_finalize_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_checks_worker_memory(
        self, MockCtx, mock_redis, mock_stages, mock_lock, mock_release,
        mock_progress, mock_memory, mock_batch_counter
    ):
        from tasks.pipeline_tasks import pipeline_finalize

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx

        # Should still return job_id; memory check is advisory
        result = pipeline_finalize("job-1")
        assert result == "job-1"
        mock_memory.assert_called_once_with(exit_on_exceed=False)

    @patch("tasks.pipeline_tasks._increment_batch_counter")
    @patch("tasks.pipeline_tasks.check_worker_memory", return_value=False)
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks._run_finalize_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_marks_failed_on_fatal_error(
        self, MockCtx, mock_redis, mock_stages, mock_lock, mock_release,
        mock_progress, mock_memory, mock_batch_counter
    ):
        from tasks.pipeline_tasks import pipeline_finalize
        from pipeline_errors import FatalError

        mock_redis_client = MagicMock()
        mock_redis.return_value = mock_redis_client
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx
        mock_stages.side_effect = FatalError("DB write failed")

        with pytest.raises(FatalError):
            pipeline_finalize("job-1")

        assert any(
            c.kwargs.get("status") == "failed"
            for c in mock_progress.call_args_list
        )
        mock_release.assert_called_once_with(mock_redis_client, "ws-1", "job-1")
        # Should increment batch failed counter
        mock_batch_counter.assert_called_once_with("job-1", "failed_sessions")

    @patch("tasks.pipeline_tasks._increment_batch_counter")
    @patch("tasks.pipeline_tasks.check_worker_memory", return_value=False)
    @patch("tasks.pipeline_tasks._update_job_progress")
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=False)
    @patch("tasks.pipeline_tasks._run_finalize_stages")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_raises_transient_on_lock_failure_resume_path(
        self, MockCtx, mock_redis, mock_stages, mock_lock, mock_release,
        mock_progress, mock_memory, mock_batch_counter
    ):
        """Finalize raises TransientError if workspace lock re-acquisition fails."""
        from tasks.pipeline_tasks import pipeline_finalize
        from pipeline_errors import TransientError

        mock_redis.return_value = MagicMock()
        ctx = _make_mock_ctx()
        MockCtx.load.return_value = ctx

        with pytest.raises(TransientError):
            pipeline_finalize("job-1")


# ---------------------------------------------------------------------------
# build_pipeline_chain
# ---------------------------------------------------------------------------


class TestBuildPipelineChain:
    """build_pipeline_chain returns a Celery chain of three tasks."""

    def test_returns_non_none_chain(self):
        from tasks.pipeline_tasks import build_pipeline_chain

        chain = build_pipeline_chain("job-1")
        assert chain is not None

    def test_chain_is_celery_signature(self):
        from tasks.pipeline_tasks import build_pipeline_chain

        chain = build_pipeline_chain("job-1")
        # Celery chain objects have a .tasks attribute or are Signature objects
        # At minimum, it should be callable
        assert callable(chain) or hasattr(chain, "apply_async")
