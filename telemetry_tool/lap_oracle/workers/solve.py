"""Solve worker -- runs OCP/QSS solvers to produce optimal lap solutions.

Claims ``solve`` jobs from the data lake, loads the corresponding
:class:`VehicleParams` and :class:`TrackModel`, and runs
:func:`solve_minimum_time`.  On OCP failure, falls back to the QSS
solver automatically.
"""
from __future__ import annotations

import json
import logging

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.solver.fallback_qss import solve_qss
from telemetry_tool.lap_oracle.solver.ocp import solve_minimum_time
from telemetry_tool.lap_oracle.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class SolveWorker(BaseWorker):
    """Solves optimal laps for vehicle+track combinations.

    Claims ``solve`` jobs and produces :class:`OCPSolution` objects
    persisted to the data lake.
    """

    worker_type: str = "solve"

    def tick(self) -> bool:
        """Claim and process one ``solve`` job.

        Returns ``True`` if a job was processed, ``False`` if idle.
        """
        job = self.lake.claim_job("solve", self.worker_id)
        if job is None:
            return False

        job_id: int = job["id"]
        sim: str = job.get("sim") or ""
        car: str = job.get("car") or ""
        track_name: str = job.get("track") or ""

        try:
            vehicle = self.lake.load_vehicle(sim, car)
            if vehicle is None:
                self.lake.complete_job(
                    job_id,
                    error=f"Vehicle not found: {sim}/{car}",
                )
                return True

            track = self.lake.load_track(sim, track_name)
            if track is None:
                # Try loading from other sims (cross-sim solving)
                for t_sim, t_name in self.lake.list_tracks():
                    if t_name == track_name:
                        track = self.lake.load_track(t_sim, t_name)
                        break

            if track is None:
                self.lake.complete_job(
                    job_id,
                    error=f"Track not found: {track_name}",
                )
                return True

            solution = self._solve(vehicle, track)
            self.lake.save_solution(solution)

            result = {
                "lap_time_s": solution.optimal_lap_time_s,
                "solver_status": solution.solver_status,
                "solver_time_s": solution.solver_time_s,
            }
            self.lake.complete_job(job_id, result=result)
            logger.info(
                "Solved %s/%s @ %s: %.3f s (%s)",
                sim, car, track_name,
                solution.optimal_lap_time_s,
                solution.solver_status,
            )

        except Exception as exc:
            logger.exception("Solve job %d failed", job_id)
            self.lake.complete_job(job_id, error=str(exc))

        return True

    # -- internal helpers --------------------------------------------------

    def _solve(self, vehicle, track):
        """Run OCP solver; fall back to QSS on any failure."""
        try:
            solution = solve_minimum_time(
                track,
                vehicle,
                n_points=self.config.ocp_n_points,
                max_time_s=self.config.ocp_max_solve_time,
            )
            return solution
        except Exception as exc:
            logger.warning(
                "OCP failed for %s/%s @ %s, trying QSS: %s",
                vehicle.sim, vehicle.car_name, track.name, exc,
            )
            return solve_qss(track, vehicle)
