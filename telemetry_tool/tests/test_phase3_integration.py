"""Integration tests for Phase 3 Celery pipeline (eager mode, no real broker)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestPipelineChainFlow:
    """Verify chain orchestration: ingest -> analyze -> finalize."""

    @patch("tasks.pipeline_tasks._increment_batch_counter")
    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    @patch("tasks.pipeline_tasks._run_ingest_stages")
    @patch("tasks.pipeline_tasks._run_analyze_stages")
    @patch("tasks.pipeline_tasks._run_finalize_stages")
    @patch("tasks.pipeline_tasks.acquire_workspace_lock", return_value=True)
    @patch("tasks.pipeline_tasks.release_workspace_lock")
    @patch("tasks.pipeline_tasks.check_worker_memory", return_value=False)
    def test_full_chain_happy_path(
        self, mock_mem, mock_release, mock_lock,
        mock_finalize, mock_analyze, mock_ingest,
        MockCtx, mock_redis, mock_pg, mock_batch_counter,
    ):
        from tasks.pipeline_tasks import (
            pipeline_analyze,
            pipeline_finalize,
            pipeline_ingest,
        )

        ctx = MagicMock()
        ctx.job_id = "j-full"
        ctx.workspace_id = 1
        ctx.errors = []
        MockCtx.load.return_value = ctx

        conn = MagicMock()
        mock_pg.return_value = conn
        mock_redis.return_value = MagicMock()

        mock_ingest.return_value = {}
        mock_analyze.return_value = {"joker_blocked": False}
        mock_finalize.return_value = {"score": 85.0}

        # Run chain sequentially (simulating eager mode)
        r1 = pipeline_ingest("j-full")
        assert r1 == "j-full"

        r2 = pipeline_analyze("j-full")
        assert r2 == "j-full"

        r3 = pipeline_finalize("j-full")
        assert r3 == "j-full"

        ctx.cleanup.assert_called_once()
        mock_release.assert_called()
        # acquire_workspace_lock called once by ingest + once by finalize
        assert mock_lock.call_count == 2


class TestJobRegistryIntegration:
    """Verify job registry create + get round-trip."""

    def test_create_and_query(self):
        from tasks.job_registry import create_job, get_job

        conn = MagicMock()

        # create_job should call execute + commit
        create_job(conn, job_id="j1", workspace_id=42,
                   file_path="/test.csv", file_size=100)
        conn.execute.assert_called()
        conn.commit.assert_called()

        # get_job should call execute
        conn.reset_mock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "j1", "status": "pending", "workspace_id": 42,
        }
        result = get_job(conn, "j1", workspace_id=42)
        assert result is not None
        assert result["job_id"] == "j1"


class TestErrorClassificationIntegration:
    """Verify all error types classify correctly end-to-end."""

    def test_all_error_types(self):
        from pipeline_errors import (
            FatalError,
            InteractionRequired,
            TransientError,
            classify_error,
        )

        assert classify_error(TransientError("x")) == "transient"
        assert classify_error(FatalError("x")) == "fatal"
        assert classify_error(InteractionRequired("r", {})) == "interaction"
        assert classify_error(ConnectionError("x")) == "transient"
        assert classify_error(TimeoutError("x")) == "transient"
        assert classify_error(ValueError("x")) == "fatal"
        assert classify_error(RuntimeError("x")) == "fatal"


class TestConcurrencyIntegration:
    """Verify concurrency controls work together."""

    def test_lock_acquire_release_cycle(self):
        from tasks.concurrency import acquire_workspace_lock, release_workspace_lock

        store = {}
        r = MagicMock()
        r.set.side_effect = lambda k, v, **kw: (
            store.__setitem__(k, v) or True if k not in store else False
        )
        # Simulate atomic Lua compare-and-delete via eval mock
        def _eval_lua(script, numkeys, key, value):  # noqa: S307
            if store.get(key) == value:
                store.pop(key, None)
                return 1
            return 0
        r.eval = MagicMock(side_effect=_eval_lua)  # noqa: S307

        # Acquire
        assert acquire_workspace_lock(r, workspace_id=1, job_id="j1") is True
        # Second acquire fails
        assert acquire_workspace_lock(r, workspace_id=1, job_id="j2") is False
        # Release by owner (atomic via Lua)
        release_workspace_lock(r, workspace_id=1, job_id="j1")
        # Now acquire succeeds
        assert acquire_workspace_lock(r, workspace_id=1, job_id="j3") is True


class TestPipelineVersionIntegration:
    """Verify version + staleness end-to-end."""

    def test_version_staleness(self):
        from pipeline_version import PIPELINE_VERSION, is_stale

        assert PIPELINE_VERSION >= 1
        assert is_stale(None) is True
        assert is_stale(0) is True
        assert is_stale(PIPELINE_VERSION) is False
        assert is_stale(PIPELINE_VERSION + 1) is False
