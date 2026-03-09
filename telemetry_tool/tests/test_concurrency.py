"""Tests for tasks.concurrency — workspace lock, queue depth, memory guard."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.concurrency import (
    QueueFullError,
    acquire_workspace_lock,
    check_queue_depth,
    check_worker_memory,
    release_workspace_lock,
)

# ---------------------------------------------------------------------------
# Helpers: mock Redis
# ---------------------------------------------------------------------------

def _make_mock_redis():
    """Return a MagicMock that behaves like a minimal redis.Redis client."""
    store: dict[str, str] = {}
    mock = MagicMock()

    def _set(key, value, nx=False, ex=None):
        if nx and key in store:
            return False
        store[key] = value
        return True

    def _get(key):
        val = store.get(key)
        return val

    def _delete(key):
        store.pop(key, None)

    def _llen(key):
        return store.get(key, 0)

    mock.set = MagicMock(side_effect=_set)
    mock.get = MagicMock(side_effect=_get)
    mock.delete = MagicMock(side_effect=_delete)
    mock.llen = MagicMock(side_effect=_llen)
    mock._store = store
    return mock


# ---------------------------------------------------------------------------
# Tests: acquire_workspace_lock
# ---------------------------------------------------------------------------


class TestAcquireWorkspaceLock:
    """Verify SETNX-based workspace locking."""

    def test_acquire_success(self):
        redis = _make_mock_redis()
        result = acquire_workspace_lock(redis, workspace_id=1, job_id="job-1")
        assert result is True
        redis.set.assert_called_once()
        # Verify the key pattern
        call_args = redis.set.call_args
        assert call_args[0][0] == "pipeline:lock:1"
        assert call_args[0][1] == "job-1"
        assert call_args[1]["nx"] is True

    def test_acquire_failure_already_locked(self):
        redis = _make_mock_redis()
        # First lock succeeds
        acquire_workspace_lock(redis, workspace_id=1, job_id="job-1")
        # Second lock fails (nx=True with existing key)
        result = acquire_workspace_lock(redis, workspace_id=1, job_id="job-2")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: release_workspace_lock
# ---------------------------------------------------------------------------


class TestReleaseWorkspaceLock:
    """Verify atomic owner-checked lock release via Redis Lua script."""

    def test_release_calls_redis_eval_with_lua_script(self):
        """release uses redis server-side Lua for atomicity."""
        r = _make_mock_redis()
        # redis.eval sends Lua to the Redis server (NOT Python eval)
        r.eval = MagicMock(return_value=1)  # noqa: S307
        acquire_workspace_lock(r, workspace_id=5, job_id="job-abc")
        release_workspace_lock(r, workspace_id=5, job_id="job-abc")
        r.eval.assert_called_once()  # noqa: S307
        call_args = r.eval.call_args  # noqa: S307
        # Args: lua_script, 1, key, job_id
        assert call_args[0][1] == 1  # numkeys
        assert call_args[0][2] == "pipeline:lock:5"  # key
        assert call_args[0][3] == "job-abc"  # value to compare

    def test_release_passes_correct_job_id(self):
        """Different job_id is passed to the Lua script for comparison."""
        r = _make_mock_redis()
        r.eval = MagicMock(return_value=0)  # noqa: S307
        acquire_workspace_lock(r, workspace_id=5, job_id="job-abc")
        release_workspace_lock(r, workspace_id=5, job_id="job-OTHER")
        call_args = r.eval.call_args  # noqa: S307
        assert call_args[0][3] == "job-OTHER"

    def test_release_noop_if_no_lock(self):
        """Release on non-existent lock still calls server-side Lua (handles nil)."""
        r = _make_mock_redis()
        r.eval = MagicMock(return_value=0)  # noqa: S307
        release_workspace_lock(r, workspace_id=99, job_id="job-xyz")
        r.eval.assert_called_once()  # noqa: S307


# ---------------------------------------------------------------------------
# Tests: check_queue_depth
# ---------------------------------------------------------------------------


class TestCheckQueueDepth:
    """Verify queue depth gating."""

    def test_passes_when_below_limit(self):
        redis = _make_mock_redis()
        redis._store["pipeline"] = 10
        # Should not raise
        check_queue_depth(redis, max_depth=50)

    def test_raises_at_limit(self):
        redis = _make_mock_redis()
        redis._store["pipeline"] = 50
        with pytest.raises(QueueFullError):
            check_queue_depth(redis, max_depth=50)

    def test_raises_above_limit(self):
        redis = _make_mock_redis()
        redis._store["pipeline"] = 100
        with pytest.raises(QueueFullError):
            check_queue_depth(redis, max_depth=50)

    def test_custom_queue_name(self):
        redis = _make_mock_redis()
        redis._store["custom_queue"] = 5
        # Should not raise — below limit
        check_queue_depth(redis, max_depth=10, queue_name="custom_queue")

    def test_custom_queue_name_raises(self):
        redis = _make_mock_redis()
        redis._store["custom_queue"] = 15
        with pytest.raises(QueueFullError):
            check_queue_depth(redis, max_depth=10, queue_name="custom_queue")


# ---------------------------------------------------------------------------
# Tests: check_worker_memory
# ---------------------------------------------------------------------------


class TestCheckWorkerMemory:
    """Verify RSS memory guard with mocked psutil."""

    @patch("tasks.concurrency.psutil")
    def test_returns_false_below_threshold(self, mock_psutil):
        # 500 MB RSS — below 1500 MB default
        mock_proc = MagicMock()
        mock_proc.memory_info.return_value.rss = 500 * 1024 * 1024
        mock_psutil.Process.return_value = mock_proc
        assert check_worker_memory(exit_on_exceed=False) is False

    @patch("tasks.concurrency.psutil")
    def test_returns_true_above_threshold(self, mock_psutil):
        # 2000 MB RSS — above 1500 MB default (exit disabled for test)
        mock_proc = MagicMock()
        mock_proc.memory_info.return_value.rss = 2000 * 1024 * 1024
        mock_psutil.Process.return_value = mock_proc
        assert check_worker_memory(exit_on_exceed=False) is True

    @patch("tasks.concurrency.psutil")
    def test_custom_threshold(self, mock_psutil):
        # 800 MB RSS, threshold 700 MB — should be over
        mock_proc = MagicMock()
        mock_proc.memory_info.return_value.rss = 800 * 1024 * 1024
        mock_psutil.Process.return_value = mock_proc
        assert check_worker_memory(max_rss_mb=700, exit_on_exceed=False) is True

    @patch("tasks.concurrency.psutil")
    def test_exactly_at_threshold(self, mock_psutil):
        # Exactly at threshold — should NOT exceed (> not >=)
        mock_proc = MagicMock()
        mock_proc.memory_info.return_value.rss = 1500 * 1024 * 1024
        mock_psutil.Process.return_value = mock_proc
        assert check_worker_memory(max_rss_mb=1500, exit_on_exceed=False) is False

    @patch("tasks.concurrency.sys")
    @patch("tasks.concurrency.psutil")
    def test_exits_when_exceeded_and_exit_enabled(self, mock_psutil, mock_sys):
        """Default behavior: sys.exit(0) when memory exceeds threshold."""
        mock_proc = MagicMock()
        mock_proc.memory_info.return_value.rss = 2000 * 1024 * 1024
        mock_psutil.Process.return_value = mock_proc
        check_worker_memory()
        mock_sys.exit.assert_called_once_with(0)


    @patch("tasks.concurrency.psutil", None)
    @patch("tasks.concurrency.resource")
    def test_fallback_to_resource_when_psutil_missing(self, mock_resource):
        mock_resource.RUSAGE_SELF = 0
        # On Linux ru_maxrss is in KB: 800 MB -> 819200 KB
        mock_resource.getrusage.return_value = SimpleNamespace(ru_maxrss=800 * 1024)
        with patch("tasks.concurrency.sys.platform", "linux"):
            assert check_worker_memory(max_rss_mb=700, exit_on_exceed=False) is True

    @patch("tasks.concurrency.psutil", None)
    @patch("tasks.concurrency.resource", None)
    def test_returns_false_when_no_memory_provider_available(self):
        assert check_worker_memory(exit_on_exceed=False) is False
