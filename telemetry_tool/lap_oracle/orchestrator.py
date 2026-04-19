"""Lap Oracle Orchestrator -- phase-scheduled multi-worker runner.

Manages the full 48-hour (or shorter) oracle run.  Workers are spawned
and scaled based on which phase the run is in.  Progress is written to
``reports/progress.json`` every tick (30 s) and a final markdown report
is generated on shutdown.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Type

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.workers.base import BaseWorker
from telemetry_tool.lap_oracle.workers.harvest import HarvestWorker
from telemetry_tool.lap_oracle.workers.identify import IdentifyWorker
from telemetry_tool.lap_oracle.workers.solve import SolveWorker
from telemetry_tool.lap_oracle.workers.train import TrainWorker
from telemetry_tool.lap_oracle.workers.ac_driver import ACDriverWorker
from telemetry_tool.lap_oracle.workers.sweep import SweepWorker

logger = logging.getLogger(__name__)

# Phase boundaries as fraction of total run time
_PHASE_FRACTIONS = [
    (0.04, "harvest"),    # first 4% (~2h of 48h)
    (0.125, "identify"),  # next 8% (~6h of 48h)
    (0.50, "solve"),      # next 38% (~24h of 48h)
    (0.83, "full"),       # next 33% (~40h of 48h)
    (0.96, "refine"),     # next 13% (~46h of 48h)
]


class Orchestrator:
    """Phase-scheduled orchestrator for the Lap Oracle system.

    Parameters
    ----------
    config : OracleConfig
        Runtime configuration (hours, worker counts, feature flags).
    resume : bool
        If *True*, reuse existing DataLake state (checkpoint resume).
    """

    def __init__(self, config: OracleConfig, resume: bool = False) -> None:
        self.config = config
        self.lake = DataLake(config)
        self._workers: List[BaseWorker] = []
        self._start_time: float = 0.0
        self._running: bool = False

    # -- public API --------------------------------------------------------

    def run(self) -> None:
        """Main loop -- runs for ``config.run_hours`` then stops."""
        self._start_time = time.time()
        self._running = True
        end_time = self._start_time + self.config.run_hours * 3600

        logger.info(
            "Orchestrator starting -- %.1f hour run", self.config.run_hours,
        )

        try:
            while self._running and time.time() < end_time:
                elapsed_hours = (time.time() - self._start_time) / 3600
                phase = self._get_phase(elapsed_hours)
                self._ensure_workers_for_phase(phase)
                self._monitor_workers()
                self._write_progress(phase, elapsed_hours)
                time.sleep(30)
        finally:
            self.stop()
            self._generate_final_report()

    def stop(self) -> None:
        """Signal all workers to stop and wait for them."""
        self._running = False
        for w in self._workers:
            w.stop()
        logger.info(
            "Orchestrator stopped -- %d workers shut down",
            len(self._workers),
        )

    # -- phase logic -------------------------------------------------------

    def _get_phase(self, elapsed_hours: float) -> str:
        """Return the current phase name for *elapsed_hours*."""
        total = self.config.run_hours
        for fraction, phase in _PHASE_FRACTIONS:
            if elapsed_hours < fraction * total:
                return phase
        return "report"

    def _ensure_workers_for_phase(self, phase: str) -> None:
        """Spawn workers appropriate for the current phase.

        Phase scheduling:

        * **harvest** (0--2 h): harvest workers only
        * **identify** (2--6 h): harvest + identify + ac_driver starts
        * **solve** (6--24 h): harvest + identify + solve + train
        * **full** (24--40 h): all workers including sweep
        * **refine** (40--46 h): solve + sweep + train on top combos
        * **report** (46--48 h): wind down, generate reports
        """
        if phase == "harvest":
            self._ensure_worker_type(
                HarvestWorker, "harvest", self.config.harvest_workers,
            )
        elif phase == "identify":
            self._ensure_worker_type(HarvestWorker, "harvest", 2)
            self._ensure_worker_type(
                IdentifyWorker, "identify", self.config.identify_workers,
            )
            if self.config.enable_ac_driver:
                self._ensure_worker_type(ACDriverWorker, "ac_driver", 1)
        elif phase in ("solve", "full", "refine"):
            self._ensure_worker_type(HarvestWorker, "harvest", 1)
            self._ensure_worker_type(IdentifyWorker, "identify", 1)
            self._ensure_worker_type(
                SolveWorker, "solve", self.config.solve_workers,
            )
            if self.config.enable_neural_training:
                self._ensure_worker_type(TrainWorker, "train", 1)
            if self.config.enable_ac_driver:
                self._ensure_worker_type(ACDriverWorker, "ac_driver", 1)
            if phase in ("full", "refine"):
                self._ensure_worker_type(
                    SweepWorker, "sweep", self.config.sweep_workers,
                )
        # "report" phase: no new workers -- existing ones drain naturally

    def _ensure_worker_type(
        self,
        worker_cls: Type[BaseWorker],
        worker_type: str,
        count: int,
    ) -> None:
        """Ensure at least *count* alive workers of *worker_type*."""
        alive = [
            w for w in self._workers
            if w.worker_type == worker_type and w.alive
        ]
        needed = count - len(alive)
        for _ in range(needed):
            wid = f"{worker_type}-{len(self._workers)}"
            w = worker_cls(wid, self.lake, self.config)
            w.start()
            self._workers.append(w)
            logger.info("Spawned worker %s (phase needs %d)", wid, count)

    # -- monitoring --------------------------------------------------------

    def _monitor_workers(self) -> None:
        """Log any dead workers.

        Dead workers are replaced on the next call to
        ``_ensure_workers_for_phase``.
        """
        for w in self._workers:
            if not w.alive and self._running:
                logger.warning(
                    "Worker %s (%s) is dead -- will be replaced next cycle",
                    w.worker_id, w.worker_type,
                )

    def _write_progress(self, phase: str, elapsed_hours: float) -> None:
        """Write a JSON progress snapshot to ``reports/progress.json``."""
        summary = self.lake.get_progress_summary()
        progress: Dict = {
            "elapsed_hours": round(elapsed_hours, 2),
            "remaining_hours": round(
                self.config.run_hours - elapsed_hours, 2,
            ),
            "phase": phase,
            "active_workers": len([w for w in self._workers if w.alive]),
            "total_workers_spawned": len(self._workers),
        }
        progress.update(summary)

        report_path = self.config.data_dir / "reports" / "progress.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(progress, indent=2, default=str), encoding="utf-8",
        )

    # -- final report ------------------------------------------------------

    def _generate_final_report(self) -> None:
        """Generate the final markdown report on shutdown."""
        from telemetry_tool.lap_oracle.report import generate_final_report

        try:
            path = generate_final_report(self.lake, self.config)
            logger.info("Final report written to %s", path)
        except Exception:
            logger.exception("Failed to generate final report")
