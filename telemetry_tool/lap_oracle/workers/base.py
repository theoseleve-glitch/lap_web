"""Base worker ABC for the Lap Oracle system.

All oracle workers inherit from :class:`BaseWorker`, which provides
daemon-thread lifecycle management and a run-loop with error handling.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.data_lake import DataLake

logger = logging.getLogger(__name__)


class BaseWorker:
    """Abstract base for oracle workers.

    Subclasses must override :meth:`tick` to perform one unit of work.

    Parameters
    ----------
    worker_id:
        Unique identifier for this worker instance (e.g.
        ``"harvest-0"``).
    lake:
        Shared data lake for job claiming and storage.
    config:
        Oracle runtime configuration.
    """

    worker_type: str = "base"

    def __init__(
        self,
        worker_id: str,
        lake: DataLake,
        config: OracleConfig,
    ) -> None:
        self.worker_id = worker_id
        self.lake = lake
        self.config = config
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._error_count = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Spawn the worker's daemon thread.

        Does nothing if already running.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning(
                "Worker %s already running", self.worker_id,
            )
            return
        self._running = True
        self._error_count = 0
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"oracle-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Worker %s started", self.worker_id)

    def stop(self) -> None:
        """Signal the worker to stop and wait up to 10 s for the thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning(
                    "Worker %s did not stop within 10 s", self.worker_id,
                )
            else:
                logger.info("Worker %s stopped", self.worker_id)
        self._thread = None

    @property
    def alive(self) -> bool:
        """``True`` if the worker thread is currently alive."""
        return self._thread is not None and self._thread.is_alive()

    # -- run loop ----------------------------------------------------------

    def _run_loop(self) -> None:
        """Main loop: call ``tick()`` repeatedly until stopped."""
        logger.info(
            "Worker %s (%s) entering run loop",
            self.worker_id, self.worker_type,
        )
        while self._running:
            try:
                did_work = self.tick()
                self._error_count = 0
                if not did_work:
                    # No work available -- back off
                    time.sleep(2.0)
            except Exception:
                self._error_count += 1
                logger.exception(
                    "Worker %s tick error (#%d)",
                    self.worker_id, self._error_count,
                )
                # Exponential back-off on repeated errors, capped at 30 s
                backoff = min(5.0 * self._error_count, 30.0)
                time.sleep(backoff)

        logger.info("Worker %s run loop exiting", self.worker_id)

    # -- abstract ----------------------------------------------------------

    def tick(self) -> bool:
        """Perform one unit of work.

        Returns
        -------
        bool
            ``True`` if work was performed, ``False`` if idle.

        Raises
        ------
        NotImplementedError
            Subclasses must override this method.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement tick()"
        )
