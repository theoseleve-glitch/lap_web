"""Identify worker -- builds VehicleParams from harvested data.

Claims ``identify`` jobs from the data lake and constructs
:class:`VehicleParams` for each car.  After saving a vehicle model,
enqueues ``solve`` jobs for all known track+vehicle combinations that
have not been solved yet.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from telemetry_tool.lap_oracle.config import (
    OracleConfig,
    PacejkaParams,
    VehicleParams,
)
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.workers.base import BaseWorker

logger = logging.getLogger(__name__)


def _try_sim_optimizer_result(payload: dict) -> Optional[VehicleParams]:
    """Attempt to build VehicleParams from sim_optimizer param_id results.

    Returns ``None`` if the payload does not contain usable param_id data.
    """
    param_id = payload.get("param_id_result")
    if not param_id or not isinstance(param_id, dict):
        return None

    try:
        vp = VehicleParams(
            sim=param_id.get("sim", ""),
            car_name=param_id.get("car_name", ""),
            mass_kg=float(param_id.get("mass_kg", 1300.0)),
            max_power_w=float(param_id.get("max_power_w", 400_000.0)),
            max_brake_decel=float(param_id.get("max_brake_decel", 12.0)),
            cda=float(param_id.get("cda", 0.80)),
            cla=float(param_id.get("cla", 2.5)),
        )
        if "tyre_lat" in param_id and isinstance(param_id["tyre_lat"], dict):
            vp.tyre_lat = PacejkaParams.from_dict(param_id["tyre_lat"])
        if "tyre_long" in param_id and isinstance(param_id["tyre_long"], dict):
            vp.tyre_long = PacejkaParams.from_dict(param_id["tyre_long"])
        return vp
    except (TypeError, ValueError) as exc:
        logger.warning("sim_optimizer param_id parse failed: %s", exc)
        return None


def _vehicle_from_extractor(
    sim: str, car: str, payload: dict,
) -> VehicleParams:
    """Build VehicleParams from extractor harvest data in *payload*.

    Falls back to sensible defaults for any missing field.
    """
    ext = payload.get("extractor_data", {})
    return VehicleParams(
        sim=sim,
        car_name=car,
        mass_kg=float(ext.get("mass_kg", 1300.0)),
        wheelbase_m=float(ext.get("wheelbase_m", 2.65)),
        track_width_front_m=float(ext.get("track_width_front_m", 1.6)),
        track_width_rear_m=float(ext.get("track_width_rear_m", 1.6)),
        cg_height_m=float(ext.get("cg_height_m", 0.35)),
        weight_dist_front=float(ext.get("weight_dist_front", 0.47)),
        cda=float(ext.get("cda", 0.80)),
        cla=float(ext.get("cla", 2.5)),
        max_power_w=float(ext.get("max_power_w", 400_000.0)),
        max_brake_decel=float(ext.get("max_brake_decel", 12.0)),
    )


class IdentifyWorker(BaseWorker):
    """Builds VehicleParams from harvested car data.

    After saving a vehicle, enqueues ``solve`` jobs for every known
    track that does not yet have a solution for this car.
    """

    worker_type: str = "identify"

    def tick(self) -> bool:
        """Claim and process one ``identify`` job.

        Returns ``True`` if a job was processed, ``False`` if idle.
        """
        job = self.lake.claim_job("identify", self.worker_id)
        if job is None:
            return False

        job_id: int = job["id"]
        sim: str = job.get("sim") or ""
        car: str = job.get("car") or ""

        try:
            payload = json.loads(job.get("payload") or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}

        try:
            vehicle = self._build_vehicle(sim, car, payload)
            self.lake.save_vehicle(vehicle)
            logger.info(
                "Saved vehicle %s/%s (%.0f kg, %.0f kW)",
                sim, car, vehicle.mass_kg, vehicle.max_power_w / 1000,
            )
            self._enqueue_solve_jobs(vehicle)
            self.lake.complete_job(
                job_id,
                result={"sim": sim, "car": car, "mass_kg": vehicle.mass_kg},
            )
        except Exception as exc:
            logger.exception("Identify job %d failed", job_id)
            self.lake.complete_job(job_id, error=str(exc))

        return True

    # -- internal helpers --------------------------------------------------

    def _build_vehicle(
        self, sim: str, car: str, payload: dict,
    ) -> VehicleParams:
        """Try sim_optimizer result first, fall back to extractor data."""
        # 1. Check for existing vehicle in lake
        existing = self.lake.load_vehicle(sim, car)
        if existing is not None:
            logger.debug("Vehicle %s/%s already in lake", sim, car)
            return existing

        # 2. Try sim_optimizer param_id output
        vehicle = _try_sim_optimizer_result(payload)
        if vehicle is not None:
            logger.info(
                "Built %s/%s from sim_optimizer param_id", sim, car,
            )
            return vehicle

        # 3. Fall back to extractor data
        return _vehicle_from_extractor(sim, car, payload)

    def _enqueue_solve_jobs(self, vehicle: VehicleParams) -> None:
        """Enqueue ``solve`` jobs for all tracks that lack a solution."""
        tracks = self.lake.list_tracks()
        enqueued = 0
        for track_sim, track_name in tracks:
            if not self.lake.job_exists(
                "solve", vehicle.sim, vehicle.car_name, track_name,
            ):
                self.lake.add_job(
                    "solve",
                    sim=vehicle.sim,
                    car=vehicle.car_name,
                    track=track_name,
                    priority=5.0,
                )
                enqueued += 1
        if enqueued:
            logger.info(
                "Enqueued %d solve jobs for %s/%s",
                enqueued, vehicle.sim, vehicle.car_name,
            )
