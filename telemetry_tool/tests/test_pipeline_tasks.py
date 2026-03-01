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


# ---------------------------------------------------------------------------
# _build_session_meta
# ---------------------------------------------------------------------------


class TestBuildSessionMeta:
    """_build_session_meta builds the session_meta dict from context."""

    def test_returns_correct_keys(self):
        from tasks.pipeline_tasks import _build_session_meta

        ctx = _make_mock_ctx(session_id="sess-42")
        meta = _build_session_meta(ctx)

        assert meta["session_id"] == "sess-42"
        assert meta["session_type"] == "practice"
        assert meta["track_state"] == "dry"

    def test_returns_dict(self):
        from tasks.pipeline_tasks import _build_session_meta

        ctx = _make_mock_ctx()
        meta = _build_session_meta(ctx)
        assert isinstance(meta, dict)


# ---------------------------------------------------------------------------
# _store_theoretical_data
# ---------------------------------------------------------------------------


class TestStoreTheoreticalData:
    """_store_theoretical_data upserts theoretical results to DB."""

    def test_stores_data_with_metrics(self):
        from tasks.pipeline_tasks import _store_theoretical_data

        conn = _make_mock_conn()
        result = {
            "theoretical_metrics": {
                "best_s": 58.5,
                "simulation_method": "percentile_envelope",
            },
            "lap_times": [60.0, 59.5, 61.0],
            "theoretical_lap": None,
            "corner_coaching": None,
            "delta_map": None,
            "session_scalars": None,
        }

        _store_theoretical_data("sess-1", result, conn=conn)

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        sql_str = str(call_args[0][0])
        assert "theoretical_data" in sql_str
        assert "ON CONFLICT" in sql_str
        params = call_args[0][1]
        assert params["session_id"] == "sess-1"
        assert params["theoretical_time_s"] == 58.5
        assert params["actual_best_time_s"] == 59.5
        assert params["simulation_method"] == "percentile_envelope"
        # gap_pct = (59.5 - 58.5) / 58.5 * 100 = 1.71
        assert abs(params["gap_pct"] - 1.71) < 0.01
        conn.commit.assert_called_once()

    def test_skips_when_no_theoretical_metrics(self):
        from tasks.pipeline_tasks import _store_theoretical_data

        conn = _make_mock_conn()
        result = {"theoretical_metrics": None}

        _store_theoretical_data("sess-1", result, conn=conn)

        conn.execute.assert_not_called()
        conn.commit.assert_not_called()

    def test_skips_when_empty_theoretical_metrics(self):
        from tasks.pipeline_tasks import _store_theoretical_data

        conn = _make_mock_conn()
        result = {"theoretical_metrics": {}}

        _store_theoretical_data("sess-1", result, conn=conn)

        conn.execute.assert_not_called()
        conn.commit.assert_not_called()

    def test_handles_no_lap_times(self):
        from tasks.pipeline_tasks import _store_theoretical_data

        conn = _make_mock_conn()
        result = {
            "theoretical_metrics": {"best_s": 58.5},
            "lap_times": [],
        }

        _store_theoretical_data("sess-1", result, conn=conn)

        params = conn.execute.call_args[0][1]
        assert params["actual_best_time_s"] is None
        assert params["gap_pct"] is None

    @patch("tasks.pipeline_tasks._get_pg_connection")
    def test_gets_pg_connection_when_none_provided(self, mock_get_pg):
        from tasks.pipeline_tasks import _store_theoretical_data

        conn = _make_mock_conn()
        mock_get_pg.return_value = conn
        result = {
            "theoretical_metrics": {"best_s": 58.5},
        }

        _store_theoretical_data("sess-1", result, conn=None)

        mock_get_pg.assert_called_once()
        conn.execute.assert_called_once()

    def test_serialises_corner_coaching_as_json(self):
        import json
        from tasks.pipeline_tasks import _store_theoretical_data

        conn = _make_mock_conn()
        coaching = [{"corner": 1, "advice": "brake later"}]
        result = {
            "theoretical_metrics": {"best_s": 58.5},
            "corner_coaching": coaching,
        }

        _store_theoretical_data("sess-1", result, conn=conn)

        params = conn.execute.call_args[0][1]
        assert params["corner_coaching_json"] == json.dumps(coaching)

    def test_serialises_session_scalars_as_json(self):
        import json
        from tasks.pipeline_tasks import _store_theoretical_data

        conn = _make_mock_conn()
        scalars = {"top_speed": 45.2, "avg_accel": 3.1}
        result = {
            "theoretical_metrics": {"best_s": 58.5},
            "session_scalars": scalars,
        }

        _store_theoretical_data("sess-1", result, conn=conn)

        params = conn.execute.call_args[0][1]
        assert params["session_scalars_json"] == json.dumps(scalars)


# ---------------------------------------------------------------------------
# _run_finalize_stages (real pipeline integration)
# ---------------------------------------------------------------------------


class TestRunFinalizeStages:
    """_run_finalize_stages calls run_full_analysis and persists results."""

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_calls_run_full_analysis(self, mock_rfa, mock_store_theo, mock_get_pg):
        from tasks.pipeline_tasks import _run_finalize_stages

        mock_rfa.return_value = {
            "theoretical_metrics": None,
            "score_result": None,
        }
        ctx = _make_mock_ctx()

        _run_finalize_stages(ctx)

        mock_rfa.assert_called_once()
        call_kwargs = mock_rfa.call_args
        assert call_kwargs.kwargs.get("csv_path") == "/data/test.csv" or call_kwargs[1].get("csv_path") == "/data/test.csv"
        assert call_kwargs.kwargs.get("enable_report") is False or call_kwargs[1].get("enable_report") is False

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_stores_theoretical_data_when_present(self, mock_rfa, mock_store_theo, mock_get_pg):
        from tasks.pipeline_tasks import _run_finalize_stages

        mock_get_pg.return_value = _make_mock_conn()
        mock_rfa.return_value = {
            "theoretical_metrics": {"best_s": 58.5},
            "score_result": None,
        }
        ctx = _make_mock_ctx(session_id="sess-99")

        _run_finalize_stages(ctx)

        mock_store_theo.assert_called_once()
        args = mock_store_theo.call_args
        assert args[0][0] == "sess-99"  # session_id

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_does_not_store_theoretical_data_when_absent(self, mock_rfa, mock_store_theo, mock_get_pg):
        from tasks.pipeline_tasks import _run_finalize_stages

        mock_rfa.return_value = {
            "theoretical_metrics": None,
            "score_result": None,
        }
        ctx = _make_mock_ctx()

        _run_finalize_stages(ctx)

        mock_store_theo.assert_not_called()

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_stores_scores_when_present(self, mock_rfa, mock_store_theo, mock_get_pg):
        from tasks.pipeline_tasks import _run_finalize_stages

        conn = _make_mock_conn()
        mock_get_pg.return_value = conn
        mock_rfa.return_value = {
            "theoretical_metrics": None,
            "score_result": {"total_score": 82.5, "grade": "A"},
        }
        ctx = _make_mock_ctx(session_id="sess-99")

        _run_finalize_stages(ctx)

        # Should have called conn.execute for session score update
        conn.execute.assert_called()
        # Find the UPDATE sessions call
        found_score_update = False
        for c in conn.execute.call_args_list:
            sql_str = str(c[0][0])
            if "UPDATE sessions" in sql_str and "total_score" in sql_str:
                params = c[0][1]
                assert params["total_score"] == 82.5
                assert params["grade"] == "A"
                assert params["session_id"] == "sess-99"
                found_score_update = True
                break
        assert found_score_update, "Expected UPDATE sessions with score data"

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_does_not_store_scores_when_absent(self, mock_rfa, mock_store_theo, mock_get_pg):
        from tasks.pipeline_tasks import _run_finalize_stages

        conn = _make_mock_conn()
        mock_get_pg.return_value = conn
        mock_rfa.return_value = {
            "theoretical_metrics": None,
            "score_result": None,
        }
        ctx = _make_mock_ctx()

        _run_finalize_stages(ctx)

        # conn.execute should NOT be called (no theo data, no scores)
        conn.execute.assert_not_called()

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_marks_all_finalize_stages_completed(self, mock_rfa, mock_store_theo, mock_get_pg):
        from tasks.pipeline_tasks import _run_finalize_stages, _FINALIZE_STAGES

        mock_rfa.return_value = {
            "theoretical_metrics": None,
            "score_result": None,
        }
        ctx = _make_mock_ctx()

        _run_finalize_stages(ctx)

        # Verify update_stage was called for each finalize stage with "completed"
        completed_stages = [
            c.args[0]
            for c in ctx.update_stage.call_args_list
            if len(c.args) >= 2 and c.args[1] == "completed"
        ]
        for stage in _FINALIZE_STAGES:
            assert stage in completed_stages, f"Stage {stage} not marked completed"

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_graceful_when_store_theoretical_fails(self, mock_rfa, mock_store_theo, mock_get_pg):
        """Finalize should not raise even if storing theoretical data fails."""
        from tasks.pipeline_tasks import _run_finalize_stages

        mock_get_pg.return_value = _make_mock_conn()
        mock_store_theo.side_effect = Exception("DB write failed")
        mock_rfa.return_value = {
            "theoretical_metrics": {"best_s": 58.5},
            "score_result": None,
        }
        ctx = _make_mock_ctx()

        # Should NOT raise
        _run_finalize_stages(ctx)

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_graceful_when_store_scores_fails(self, mock_rfa, mock_store_theo, mock_get_pg):
        """Finalize should not raise even if storing scores fails."""
        from tasks.pipeline_tasks import _run_finalize_stages

        conn = _make_mock_conn()
        conn.execute.side_effect = Exception("DB write failed")
        mock_get_pg.return_value = conn
        mock_rfa.return_value = {
            "theoretical_metrics": None,
            "score_result": {"total_score": 82.5, "grade": "A"},
        }
        ctx = _make_mock_ctx()

        # Should NOT raise
        _run_finalize_stages(ctx)

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._store_theoretical_data")
    @patch("pipeline.run_full_analysis")
    def test_passes_session_meta_from_context(self, mock_rfa, mock_store_theo, mock_get_pg):
        from tasks.pipeline_tasks import _run_finalize_stages

        mock_rfa.return_value = {
            "theoretical_metrics": None,
            "score_result": None,
        }
        ctx = _make_mock_ctx(session_id="sess-meta-test")

        _run_finalize_stages(ctx)

        call_kwargs = mock_rfa.call_args
        session_meta = call_kwargs.kwargs.get("session_meta") or call_kwargs[1].get("session_meta")
        assert session_meta is not None
        assert session_meta["session_id"] == "sess-meta-test"
        assert session_meta["session_type"] == "practice"
        assert session_meta["track_state"] == "dry"


# ---------------------------------------------------------------------------
# _run_ingest_stages / _run_analyze_stages (pass-through)
# ---------------------------------------------------------------------------


class TestRunIngestStages:
    """_run_ingest_stages marks all ingest stages as completed."""

    def test_marks_all_stages_completed(self):
        from tasks.pipeline_tasks import _run_ingest_stages, _INGEST_STAGES

        ctx = _make_mock_ctx()
        _run_ingest_stages(ctx)

        completed_stages = [
            c.args[0]
            for c in ctx.update_stage.call_args_list
            if len(c.args) >= 2 and c.args[1] == "completed"
        ]
        for stage in _INGEST_STAGES:
            assert stage in completed_stages


class TestRunAnalyzeStages:
    """_run_analyze_stages marks all analyze stages as completed."""

    def test_marks_all_stages_completed(self):
        from tasks.pipeline_tasks import _run_analyze_stages, _ANALYZE_STAGES

        ctx = _make_mock_ctx()
        _run_analyze_stages(ctx)

        completed_stages = [
            c.args[0]
            for c in ctx.update_stage.call_args_list
            if len(c.args) >= 2 and c.args[1] == "completed"
        ]
        for stage in _ANALYZE_STAGES:
            assert stage in completed_stages
