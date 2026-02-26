"""Pipeline concurrency controls: workspace lock, queue depth, memory guard."""
from __future__ import annotations
import logging
import sys
from typing import Any
import psutil

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 1800  # 30 minutes
_DEFAULT_MAX_DEPTH = 50
_DEFAULT_MAX_RSS_MB = 1500

# Lua script for atomic compare-and-delete.  Prevents a race condition
# where another job acquires the lock between our GET and DELETE.
# redis_client.eval() sends this script to the Redis server for
# atomic execution — this is NOT Python's eval().
_RELEASE_LOCK_LUA = """\
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

class WorkspaceBusyError(Exception):
    pass

class QueueFullError(Exception):
    pass

def acquire_workspace_lock(redis_client, workspace_id: int, job_id: str, ttl: int = _LOCK_TTL_SECONDS) -> bool:
    """SETNX on pipeline:lock:{workspace_id} with TTL. Returns True if acquired."""
    key = f"pipeline:lock:{workspace_id}"
    acquired = redis_client.set(key, job_id, nx=True, ex=ttl)
    return bool(acquired)

def release_workspace_lock(redis_client, workspace_id: int, job_id: str) -> None:
    """Atomically release lock only if current holder matches job_id.

    Uses a Redis Lua script to ensure the GET + DELETE is atomic,
    preventing a race where another job acquires the lock between
    our check and delete.
    """
    key = f"pipeline:lock:{workspace_id}"
    # redis eval() sends Lua script to Redis server for atomic execution
    redis_client.eval(_RELEASE_LOCK_LUA, 1, key, job_id)  # noqa: S307

def check_queue_depth(redis_client, max_depth: int = _DEFAULT_MAX_DEPTH, queue_name: str = "pipeline") -> None:
    """Raise QueueFullError if queue depth >= max_depth."""
    depth = redis_client.llen(queue_name)
    if depth >= max_depth:
        raise QueueFullError(f"Pipeline queue has {depth} pending tasks (limit: {max_depth})")

def check_worker_memory(max_rss_mb: int = _DEFAULT_MAX_RSS_MB, exit_on_exceed: bool = True) -> bool:
    """Check if current process RSS exceeds threshold.

    Returns True if memory exceeded. When ``exit_on_exceed`` is True (default),
    also calls ``sys.exit(0)`` so Celery's autoscaler can replace the worker
    with a fresh one — preventing unbounded memory growth over long batch runs.
    """
    rss_bytes = psutil.Process().memory_info().rss
    rss_mb = rss_bytes / (1024 * 1024)
    exceeded = rss_mb > max_rss_mb
    if exceeded and exit_on_exceed:
        logger.warning(
            "Worker RSS %.0f MB exceeds %d MB threshold — exiting for replacement",
            rss_mb, max_rss_mb,
        )
        sys.exit(0)
    return exceeded
