"""Tests for pipeline_context — per-job state management with Redis + temp dir."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers: dict-backed mock Redis
# ---------------------------------------------------------------------------

def _make_mock_redis():
    """Return a MagicMock that behaves like a minimal redis.Redis client.

    Backed by an in-memory dict so set/get/delete/exists actually work.
    """
    store: dict[str, str] = {}
    mock = MagicMock()

    def _set(key, value, ex=None):
        store[key] = value

    def _get(key):
        return store.get(key)

    def _delete(key):
        store.pop(key, None)

    def _exists(key):
        return 1 if key in store else 0

    mock.set = MagicMock(side_effect=_set)
    mock.get = MagicMock(side_effect=_get)
    mock.delete = MagicMock(side_effect=_delete)
    mock.exists = MagicMock(side_effect=_exists)
    mock._store = store  # expose for assertions
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineContextCreate:
    """Verify create() stores metadata in Redis and creates temp dir."""

    def test_create_stores_metadata_in_redis(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-001",
            workspace_id="ws-1",
            session_id="sess-1",
            file_path="/data/session.csv",
            temp_root=str(tmp_path),
        )

        # Redis should contain the key
        key = "pipeline:ctx:job-001"
        assert key in mock_redis._store
        stored = json.loads(mock_redis._store[key])
        assert stored["workspace_id"] == "ws-1"
        assert stored["session_id"] == "sess-1"
        assert stored["file_path"] == "/data/session.csv"

    def test_create_creates_temp_dir(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-002",
            workspace_id="ws-1",
            session_id="sess-1",
            file_path="/data/session.csv",
            temp_root=str(tmp_path),
        )

        expected_dir = tmp_path / "pipeline" / "job-002"
        assert expected_dir.is_dir()

    def test_create_returns_pipeline_context(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-003",
            workspace_id="ws-1",
            session_id="sess-1",
            file_path="/data/session.csv",
            temp_root=str(tmp_path),
        )
        assert isinstance(ctx, PipelineContext)
        assert ctx.job_id == "job-003"
        assert ctx.workspace_id == "ws-1"


class TestPipelineContextLoad:
    """Verify load() reads from Redis correctly."""

    def test_load_reads_from_redis(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        # Create first
        PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-010",
            workspace_id="ws-2",
            session_id="sess-2",
            file_path="/data/s2.csv",
            temp_root=str(tmp_path),
        )

        # Load
        ctx = PipelineContext.load(
            redis_client=mock_redis,
            job_id="job-010",
            temp_root=str(tmp_path),
        )
        assert ctx is not None
        assert ctx.job_id == "job-010"
        assert ctx.workspace_id == "ws-2"
        assert ctx.session_id == "sess-2"
        assert ctx.file_path == "/data/s2.csv"

    def test_load_returns_none_for_missing_job(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.load(
            redis_client=mock_redis,
            job_id="nonexistent",
            temp_root=str(tmp_path),
        )
        assert ctx is None


class TestPipelineContextSaveLoadRoundTrip:
    """Verify save/load round-trip preserves all fields."""

    def test_round_trip_preserves_all_fields(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-020",
            workspace_id="ws-3",
            session_id="sess-3",
            file_path="/data/s3.csv",
            temp_root=str(tmp_path),
        )

        # Mutate state
        ctx.update_stage("gps_filter", "running")
        ctx.add_error("gps_filter", "bad satellite fix at row 42")
        ctx.set_joker_decision("use_previous")
        ctx.save()

        # Reload from scratch
        ctx2 = PipelineContext.load(
            redis_client=mock_redis,
            job_id="job-020",
            temp_root=str(tmp_path),
        )
        assert ctx2.workspace_id == "ws-3"
        assert ctx2.session_id == "sess-3"
        assert ctx2.file_path == "/data/s3.csv"
        assert ctx2.current_stage == "gps_filter"
        assert ctx2.stage_status == "running"
        assert len(ctx2.errors) == 1
        assert ctx2.errors[0]["stage"] == "gps_filter"
        assert ctx2.errors[0]["message"] == "bad satellite fix at row 42"
        assert ctx2.joker_decision == "use_previous"


class TestPipelineContextDataFrames:
    """Verify save_dataframe/load_dataframe round-trip."""

    def test_save_load_dataframe_round_trip(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-030",
            workspace_id="ws-4",
            session_id="sess-4",
            file_path="/data/s4.csv",
            temp_root=str(tmp_path),
        )

        df = pd.DataFrame({
            "time_s": [0.0, 0.1, 0.2, 0.3],
            "speed_mps": [10.0, 12.5, 15.0, 14.8],
            "lat": [51.5074, 51.5075, 51.5076, 51.5077],
        })
        ctx.save_dataframe("gps_filtered", df)

        loaded = ctx.load_dataframe("gps_filtered")
        assert loaded is not None
        pd.testing.assert_frame_equal(loaded, df)

    def test_load_dataframe_returns_none_for_missing(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-031",
            workspace_id="ws-4",
            session_id="sess-4",
            file_path="/data/s4.csv",
            temp_root=str(tmp_path),
        )

        result = ctx.load_dataframe("nonexistent_frame")
        assert result is None


class TestPipelineContextCleanup:
    """Verify cleanup removes temp dir and Redis key."""

    def test_cleanup_removes_temp_dir(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-040",
            workspace_id="ws-5",
            session_id="sess-5",
            file_path="/data/s5.csv",
            temp_root=str(tmp_path),
        )

        temp_dir = tmp_path / "pipeline" / "job-040"
        assert temp_dir.is_dir()

        ctx.cleanup()
        assert not temp_dir.exists()

    def test_cleanup_deletes_redis_key(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-041",
            workspace_id="ws-5",
            session_id="sess-5",
            file_path="/data/s5.csv",
            temp_root=str(tmp_path),
        )

        ctx.cleanup()
        mock_redis.delete.assert_called_with("pipeline:ctx:job-041")
        assert "pipeline:ctx:job-041" not in mock_redis._store


class TestPipelineContextJokerDecision:
    """Verify set_joker_decision persists through save/load."""

    def test_joker_decision_default_is_none(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-050",
            workspace_id="ws-6",
            session_id="sess-6",
            file_path="/data/s6.csv",
            temp_root=str(tmp_path),
        )
        assert ctx.joker_decision is None

    def test_joker_decision_persists_through_save_load(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-051",
            workspace_id="ws-6",
            session_id="sess-6",
            file_path="/data/s6.csv",
            temp_root=str(tmp_path),
        )
        ctx.set_joker_decision("skip_stage")
        ctx.save()

        ctx2 = PipelineContext.load(
            redis_client=mock_redis,
            job_id="job-051",
            temp_root=str(tmp_path),
        )
        assert ctx2.joker_decision == "skip_stage"


class TestPipelineContextUpdateStage:
    """Verify update_stage tracks current stage and status."""

    def test_update_stage_sets_current_stage(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-060",
            workspace_id="ws-7",
            session_id="sess-7",
            file_path="/data/s7.csv",
            temp_root=str(tmp_path),
        )
        ctx.update_stage("corner_detection", "completed")
        assert ctx.current_stage == "corner_detection"
        assert ctx.stage_status == "completed"

    def test_update_stage_persists_through_save(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-061",
            workspace_id="ws-7",
            session_id="sess-7",
            file_path="/data/s7.csv",
            temp_root=str(tmp_path),
        )
        ctx.update_stage("resampling", "running")
        ctx.save()

        ctx2 = PipelineContext.load(
            redis_client=mock_redis,
            job_id="job-061",
            temp_root=str(tmp_path),
        )
        assert ctx2.current_stage == "resampling"
        assert ctx2.stage_status == "running"


class TestPipelineContextAddError:
    """Verify add_error accumulates errors."""

    def test_add_multiple_errors(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-070",
            workspace_id="ws-8",
            session_id="sess-8",
            file_path="/data/s8.csv",
            temp_root=str(tmp_path),
        )
        ctx.add_error("gps_filter", "bad fix row 10")
        ctx.add_error("corner_detection", "no corners found")
        assert len(ctx.errors) == 2
        assert ctx.errors[0]["stage"] == "gps_filter"
        assert ctx.errors[1]["stage"] == "corner_detection"

    def test_errors_persist_through_save_load(self, tmp_path):
        mock_redis = _make_mock_redis()
        from pipeline_context import PipelineContext

        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="job-071",
            workspace_id="ws-8",
            session_id="sess-8",
            file_path="/data/s8.csv",
            temp_root=str(tmp_path),
        )
        ctx.add_error("scoring", "missing reference lap")
        ctx.save()

        ctx2 = PipelineContext.load(
            redis_client=mock_redis,
            job_id="job-071",
            temp_root=str(tmp_path),
        )
        assert len(ctx2.errors) == 1
        assert ctx2.errors[0]["message"] == "missing reference lap"
