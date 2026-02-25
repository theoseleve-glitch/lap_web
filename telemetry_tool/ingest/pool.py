"""
pool.py
-------
Bounded write queue and thread pool for parallel chunk flushing.

The ``WriteQueue`` decouples CSV chunk reading (main thread) from Parquet
disk writes (background thread).  Backpressure is enforced via a bounded
``queue.Queue`` — when the queue is full, the main thread blocks until
the writer drains a slot.

Public API
~~~~~~~~~~
- ``WriteQueue(cache, max_depth)`` — bounded Parquet write queue.
- ``WriteQueue.put(chunk_idx, df)`` — enqueue a chunk for flushing.
- ``WriteQueue.drain()`` — block until all pending writes are done.
- ``WriteQueue.close()`` — shut down the writer thread.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pandas as pd

from telemetry_tool.ingest.cache import IngestCache
from telemetry_tool.ingest.progress import IngestionProgress, ProgressCallback, null_progress

logger = logging.getLogger(__name__)

# Safety limits
MAX_WORKERS: int = min(4, os.cpu_count() or 2)
_SENTINEL = None  # poison pill for shutdown


class WriteQueue:
    """Bounded queue that flushes DataFrame chunks to Parquet in a background
    thread.

    The queue depth controls backpressure: when ``max_depth`` items are
    pending, ``put()`` blocks the caller (the CSV reader) until the writer
    thread catches up.  This keeps memory bounded to
    ``max_depth * chunk_size * n_columns * 8 bytes``.

    Parameters
    ----------
    cache : IngestCache
        The cache instance whose ``flush_chunk`` method will be called.
    max_depth : int
        Maximum number of chunks that can be enqueued before blocking.
    progress_cb : ProgressCallback, optional
        Called after each chunk is flushed (from the writer thread).
    """

    def __init__(
        self,
        cache: IngestCache,
        max_depth: int = 2,
        progress_cb: ProgressCallback | None = None,
    ) -> None:
        self._cache = cache
        self._queue: queue.Queue[Optional[tuple[int, pd.DataFrame]]] = queue.Queue(
            maxsize=max_depth
        )
        self._progress_cb = progress_cb or null_progress
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
        self._chunks_flushed = 0
        self._thread = threading.Thread(
            target=self._writer_loop,
            name="ingest-writer",
            daemon=True,
        )
        self._thread.start()

    def _writer_loop(self) -> None:
        """Consume items from the queue and flush to disk.

        On error, the loop stores the exception, drains all remaining
        queued items (so blocked ``put()`` callers are unblocked), and
        exits.  The next ``put()`` call will see the error and raise.
        """
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                self._queue.task_done()
                break
            chunk_idx, df = item
            try:
                self._cache.flush_chunk(chunk_idx, df)
                with self._lock:
                    self._chunks_flushed += 1
                self._progress_cb(IngestionProgress(
                    phase="flushing",
                    chunk_idx=chunk_idx,
                    chunks_flushed=self._chunks_flushed,
                ))
                self._queue.task_done()
            except Exception as exc:
                logger.error("Writer thread failed on chunk %d: %s", chunk_idx, exc)
                with self._lock:
                    self._error = exc
                self._queue.task_done()
                # Drain remaining items to unblock any producer stuck on put()
                self._drain_on_error()
                return  # Exit the writer thread

    def _drain_on_error(self) -> None:
        """Drain all pending items from the queue after an error.

        Calls ``task_done()`` for each item so that any thread blocked on
        ``put()`` (backpressure) is released and can observe the error on
        its next ``put()`` call.
        """
        drained = 0
        while True:
            try:
                item = self._queue.get_nowait()
                self._queue.task_done()
                drained += 1
                if item is _SENTINEL:
                    break
            except queue.Empty:
                break
        if drained:
            logger.debug("Writer thread drained %d items after error.", drained)

    def put(self, chunk_idx: int, df: pd.DataFrame) -> None:
        """Enqueue a chunk for background flushing.

        Blocks if the queue is full (backpressure).

        Raises
        ------
        RuntimeError
            If the writer thread has encountered an error on a previous chunk.
        """
        with self._lock:
            if self._error is not None:
                raise RuntimeError(
                    f"Writer thread failed: {self._error}"
                ) from self._error
        self._queue.put((chunk_idx, df))

    def drain(self) -> int:
        """Block until all enqueued chunks are flushed.

        Returns the total number of chunks flushed.

        Raises
        ------
        RuntimeError
            If the writer thread encountered an error.
        """
        self._queue.join()
        with self._lock:
            if self._error is not None:
                raise RuntimeError(
                    f"Writer thread failed: {self._error}"
                ) from self._error
            return self._chunks_flushed

    @property
    def chunks_flushed(self) -> int:
        with self._lock:
            return self._chunks_flushed

    def close(self) -> None:
        """Send the shutdown sentinel, join the writer thread, and re-raise errors."""
        if self._thread.is_alive():
            self._queue.put(_SENTINEL)
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                logger.warning("Writer thread did not shut down cleanly.")
        # Propagate deferred errors so callers in finally-blocks see them.
        # Check error even if thread is dead (it may have exited due to error).
        with self._lock:
            if self._error is not None:
                raise RuntimeError(
                    f"Writer thread failed: {self._error}"
                ) from self._error
