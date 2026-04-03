"""Sweep worker -- searches setup space using Latin Hypercube Sampling.

Claims ``sweep`` jobs from the data lake, generates N setup variations
via LHS, solves the OCP for each, and saves the best result.
"""
from __future__ import annotations

import json
import logging
from dataclasses import fields
from typing import Optional

import numpy as np

from telemetry_tool.lap_oracle.config import (
    OracleConfig,
    SetupParams,
    VehicleParams,
)
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.setup.mapping import apply_setup_delta
from telemetry_tool.lap_oracle.solver.fallback_qss import solve_qss
from telemetry_tool.lap_oracle.solver.ocp import solve_minimum_time
from telemetry_tool.lap_oracle.workers.base import BaseWorker

logger = logging.getLogger(__name__)

# -- Setup parameter bounds for LHS sampling -------------------------------
# Each entry: (min, max) for the corresponding SetupParams field
_SETUP_BOUNDS = {
    "front_wing": (0.0, 15.0),
    "rear_wing": (0.0, 15.0),
    "front_arb": (1.0, 10.0),
    "rear_arb": (1.0, 10.0),
    "front_spring": (40_000.0, 200_000.0),
    "rear_spring": (40_000.0, 200_000.0),
    "front_ride_height": (0.020, 0.060),
    "rear_ride_height": (0.025, 0.070),
    "front_camber": (-5.0, 0.0),
    "rear_camber": (-4.0, 0.0),
    "front_toe": (-0.5, 0.5),
    "rear_toe": (-0.2, 0.5),
    "brake_bias": (0.50, 0.65),
    "brake_pressure": (80.0, 100.0),
    "diff_preload": (10.0, 100.0),
    "diff_power_ramp": (20.0, 80.0),
    "diff_coast_ramp": (10.0, 60.0),
    "front_pressure_psi": (22.0, 30.0),
    "rear_pressure_psi": (21.0, 29.0),
}


def _generate_setups_lhs(n_samples: int) -> list[SetupParams]:
    """Generate *n_samples* setup configurations via Latin Hypercube.

    Uses ``scipy.stats.qmc.LatinHypercube`` if available; falls back
    to uniform random sampling otherwise.
    """
    param_names = [f.name for f in fields(SetupParams)]
    n_dims = len(param_names)

    try:
        from scipy.stats.qmc import LatinHypercube

        sampler = LatinHypercube(d=n_dims)
        samples = sampler.random(n=n_samples)  # shape (n_samples, n_dims)
    except ImportError:
        logger.debug("scipy not available -- using uniform random for LHS")
        samples = np.random.random((n_samples, n_dims))

    setups: list[SetupParams] = []
    for i in range(n_samples):
        kwargs = {}
        for j, name in enumerate(param_names):
            lo, hi = _SETUP_BOUNDS.get(name, (0.0, 1.0))
            kwargs[name] = lo + samples[i, j] * (hi - lo)
        setups.append(SetupParams(**kwargs))

    return setups


class SweepWorker(BaseWorker):
    """Searches setup space for optimal configuration.

    Claims ``sweep`` jobs and evaluates multiple setups via OCP/QSS
    solving, saving the best result to the data lake.
    """

    worker_type: str = "sweep"

    def tick(self) -> bool:
        """Claim and process one ``sweep`` job.

        Returns True if a job was processed, False if idle.
        """
        job = self.lake.claim_job("sweep", self.worker_id)
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
                    job_id, error=f"Vehicle not found: {sim}/{car}",
                )
                return True

            track = self.lake.load_track(sim, track_name)
            if track is None:
                # Cross-sim track lookup
                for t_sim, t_name in self.lake.list_tracks():
                    if t_name == track_name:
                        track = self.lake.load_track(t_sim, t_name)
                        break

            if track is None:
                self.lake.complete_job(
                    job_id, error=f"Track not found: {track_name}",
                )
                return True

            n_samples = self.config.sweep_n_samples
            setups = _generate_setups_lhs(n_samples)

            best_time = float("inf")
            best_solution = None
            best_setup: Optional[SetupParams] = None

            for i, setup in enumerate(setups):
                modified = apply_setup_delta(vehicle, setup)
                try:
                    sol = solve_qss(track, modified)
                    if sol.optimal_lap_time_s < best_time:
                        best_time = sol.optimal_lap_time_s
                        best_solution = sol
                        best_setup = setup
                except Exception as exc:
                    logger.debug("Sweep sample %d failed: %s", i, exc)

            result: dict = {
                "n_samples": n_samples,
                "best_lap_time_s": best_time,
            }
            if best_solution is not None:
                self.lake.save_solution(best_solution)
                if best_setup is not None:
                    result["best_setup"] = best_setup.to_dict()

            self.lake.complete_job(job_id, result=result)
            self.lake.log_progress(
                "sweep",
                setups_optimized=1,
                details=result,
            )
            logger.info(
                "Sweep %s/%s @ %s: best %.3f s from %d samples",
                sim, car, track_name, best_time, n_samples,
            )

        except Exception as exc:
            logger.exception("Sweep job %d failed", job_id)
            self.lake.complete_job(job_id, error=str(exc))

        return True
