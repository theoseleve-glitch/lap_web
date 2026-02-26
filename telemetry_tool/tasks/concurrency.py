"""Pipeline concurrency controls: workspace lock, queue depth, memory guard."""
from __future__ import annotations
import logging
from typing import Any
import psutil

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 1800  # 30 minutes
_DEFAULT_MAX_DEPTH = 50
_DEFAULT_MAX_RSS_MB = 1500

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
    """Release lock only if current holder matches job_id."""
    key = f"pipeline:lock:{workspace_id}"
    current = redis_client.get(key)
    if current is not None:
        current_str = current.decode() if isinstance(current, bytes) else str(current)
        if current_str == job_id:
            redis_client.delete(key)

def check_queue_depth(redis_client, max_depth: int = _DEFAULT_MAX_DEPTH, queue_name: str = "pipeline") -> None:
    """Raise QueueFullError if queue depth >= max_depth."""
    depth = redis_client.llen(queue_name)
    if depth >= max_depth:
        raise QueueFullError(f"Pipeline queue has {depth} pending tasks (limit: {max_depth})")

def check_worker_memory(max_rss_mb: int = _DEFAULT_MAX_RSS_MB) -> bool:
    """Return True if current process RSS exceeds threshold."""
    rss_bytes = psutil.Process().memory_info().rss
    rss_mb = rss_bytes / (1024 * 1024)
    return rss_mb > max_rss_mb
