"""Harvest worker -- discovers and ingests data from all sources.

On first tick, enqueues discovery jobs for all configured data sources.
Then processes each harvest job: AC tracks/cars, iRacing telemetry,
F1 open-data ZIPs, ACC setups, LMU vehicles, and existing TUMFTM data.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from telemetry_tool.lap_oracle.config import (
    DATA_ZIPS,
    ORACLE_DATA,
    OracleConfig,
    VehicleParams,
)
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.extractors.ac_files import (
    discover_ac_cars,
    parse_ac_car_data,
)
from telemetry_tool.lap_oracle.extractors.acc_files import discover_acc_setups
from telemetry_tool.lap_oracle.extractors.f1_zips import process_f1_zip
from telemetry_tool.lap_oracle.extractors.iracing_ibt import extract_positions
from telemetry_tool.lap_oracle.extractors.lmu_files import (
    discover_lmu_vehicles,
    parse_lmu_hdv,
)
from telemetry_tool.lap_oracle.track.extractor import (
    discover_ac_tracks,
    extract_ac_track,
    extract_from_telemetry_xy,
)
from telemetry_tool.lap_oracle.workers.base import BaseWorker

logger = logging.getLogger(__name__)

# Data sources supported by the harvest worker
_DATA_SOURCES = [
    "ac_tracks",
    "ac_cars",
    "iracing_ibt",
    "f1_zips",
    "acc_setups",
    "lmu_vehicles",
    "existing_data",
]


class HarvestWorker(BaseWorker):
    """Discovers and ingests data from simulators and external sources.

    On the first ``tick()``, enqueues one harvest job per data source.
    Subsequent ticks claim and process those jobs.
    """

    worker_type: str = "harvest"

    def __init__(
        self,
        worker_id: str,
        lake: DataLake,
        config: OracleConfig,
    ) -> None:
        super().__init__(worker_id, lake, config)
        self._discovery_enqueued = False

    def tick(self) -> bool:
        """Perform one unit of harvest work.

        Returns ``True`` if a job was processed, ``False`` if idle.
        """
        if not self._discovery_enqueued:
            self._enqueue_discovery_jobs()
            self._discovery_enqueued = True
            return True

        # Claim next harvest job
        job = self.lake.claim_job("harvest", self.worker_id)
        if job is None:
            return False

        job_id = job["id"]
        source = job.get("track") or ""
        try:
            result = self._dispatch(source, job)
            self.lake.complete_job(job_id, result=result)
            return True
        except Exception as exc:
            logger.exception(
                "Harvest job %d (%s) failed", job_id, source,
            )
            self.lake.complete_job(job_id, error=str(exc))
            return True

    # -- discovery ---------------------------------------------------------

    def _enqueue_discovery_jobs(self) -> None:
        """Enqueue one harvest job per data source."""
        for source in _DATA_SOURCES:
            if not self.lake.job_exists("harvest", "multi", "", source):
                self.lake.add_job(
                    "harvest",
                    sim="multi",
                    car="",
                    track=source,
                    priority=10.0,
                    payload={"source": source},
                )
                logger.info("Enqueued harvest job: %s", source)

    # -- dispatch ----------------------------------------------------------

    def _dispatch(self, source: str, job: dict) -> dict:
        """Route to the correct harvest method based on source key."""
        dispatch_map = {
            "ac_tracks": self._harvest_ac_tracks,
            "ac_cars": self._harvest_ac_cars,
            "iracing_ibt": self._harvest_iracing_ibt,
            "f1_zips": self._harvest_f1_zips,
            "acc_setups": self._harvest_acc_setups,
            "lmu_vehicles": self._harvest_lmu_vehicles,
            "existing_data": self._harvest_existing_data,
        }
        handler = dispatch_map.get(source)
        if handler is None:
            return {"error": f"Unknown source: {source}"}
        return handler()

    # -- source handlers ---------------------------------------------------

    def _harvest_ac_tracks(self) -> dict:
        """Discover and extract AC tracks."""
        tracks = discover_ac_tracks()
        saved = 0
        for name, path in tracks:
            # Skip if already in lake
            existing = self.lake.load_track("ac", name)
            if existing is not None:
                continue
            model = extract_ac_track(path)
            if model is not None:
                self.lake.save_track(model)
                saved += 1
                logger.info("Saved AC track: %s (%d pts)", name, model.n_points)
        return {"discovered": len(tracks), "saved": saved}

    def _harvest_ac_cars(self) -> dict:
        """Discover and extract AC car physics data."""
        cars = discover_ac_cars()
        saved = 0
        for name, path in cars:
            existing = self.lake.load_vehicle("ac", name)
            if existing is not None:
                continue
            params = parse_ac_car_data(path)
            if params is not None:
                vehicle = VehicleParams(
                    sim="ac",
                    car_name=name,
                    mass_kg=params.get("mass_kg", 1300.0),
                    wheelbase_m=params.get("wheelbase_m", 2.65),
                    cg_height_m=params.get("cg_height_m", 0.35),
                    track_width_front_m=params.get("track_width_front_m", 1.6),
                    track_width_rear_m=params.get("track_width_rear_m", 1.6),
                    max_power_w=params.get("max_power_w", 400_000.0),
                    weight_dist_front=params.get("weight_dist_front", 0.47),
                )
                self.lake.save_vehicle(vehicle)
                saved += 1
        return {"discovered": len(cars), "saved": saved}

    def _harvest_iracing_ibt(self) -> dict:
        """Scan iRacing telemetry dir, extract positions, build tracks."""
        tel_dirs = [
            Path("C:/Users/Admin/Documents/iRacing/telemetry"),
        ]
        processed = 0
        tracks_saved = 0

        for tel_dir in tel_dirs:
            if not tel_dir.is_dir():
                continue
            for ibt_path in sorted(tel_dir.glob("*.ibt")):
                # Parse car_track from filename: car_track YYYY-MM-DD...
                stem = ibt_path.stem
                parts = stem.split("_", 1)
                if len(parts) < 2:
                    continue
                car_name = parts[0]
                # Track name is between first _ and first space
                rest = parts[1]
                space_idx = rest.find(" ")
                track_name = rest[:space_idx] if space_idx != -1 else rest
                track_key = f"iracing_{track_name}"

                # Skip if track already exists
                if self.lake.load_track("iracing", track_key) is not None:
                    processed += 1
                    continue

                positions = extract_positions(ibt_path)
                if positions is None:
                    continue

                # Convert GPS lat/lon to local XY (simple equirectangular)
                xy = _latlon_to_xy(positions)
                if xy is None or xy.shape[0] < 20:
                    continue

                model = extract_from_telemetry_xy(
                    xy, name=track_key, sim="iracing",
                )
                if model is not None:
                    self.lake.save_track(model)
                    tracks_saved += 1
                    logger.info(
                        "Saved iRacing track: %s (%d pts)",
                        track_key, model.n_points,
                    )
                processed += 1

        return {"processed": processed, "tracks_saved": tracks_saved}

    def _harvest_f1_zips(self) -> dict:
        """Process all configured F1 data ZIPs."""
        total_laps = 0
        tracks_saved = 0

        for zip_key, zip_path in DATA_ZIPS.items():
            if not zip_key.startswith("f1_"):
                continue
            if not zip_path.is_file():
                logger.debug("F1 ZIP not found: %s", zip_path)
                continue

            laps = process_f1_zip(zip_path, max_laps=200)
            total_laps += len(laps)

            # Group laps by GP name to build track models
            gp_laps: dict = {}
            for lap in laps:
                gp = lap.get("gp_name", "unknown")
                if gp not in gp_laps:
                    gp_laps[gp] = []
                gp_laps[gp].append(lap)

            for gp_name, gp_lap_list in gp_laps.items():
                track_key = f"f1_{gp_name}".replace(" ", "_").lower()
                if self.lake.load_track("f1", track_key) is not None:
                    continue
                # Use the lap with the most data points for track extraction
                best_lap = max(gp_lap_list, key=lambda l: len(l.get("x", [])))
                x = best_lap.get("x", [])
                y = best_lap.get("y", [])
                if len(x) < 20:
                    continue
                xy = np.column_stack((x, y))
                model = extract_from_telemetry_xy(
                    xy, name=track_key, sim="f1",
                )
                if model is not None:
                    self.lake.save_track(model)
                    tracks_saved += 1

        return {"total_laps": total_laps, "tracks_saved": tracks_saved}

    def _harvest_acc_setups(self) -> dict:
        """Import ACC setup files as vehicle configuration data."""
        setups = discover_acc_setups()
        saved = 0
        for setup in setups:
            car_name = setup.get("car_name", "")
            if not car_name:
                continue
            # Only save one vehicle entry per car (first seen)
            existing = self.lake.load_vehicle("acc", car_name)
            if existing is not None:
                continue
            vehicle = VehicleParams(
                sim="acc",
                car_name=car_name,
            )
            self.lake.save_vehicle(vehicle)
            saved += 1
        return {"discovered": len(setups), "vehicles_saved": saved}

    def _harvest_lmu_vehicles(self) -> dict:
        """Import LMU vehicle data from .hdv files."""
        vehicles = discover_lmu_vehicles()
        saved = 0
        for name, path in vehicles:
            existing = self.lake.load_vehicle("lmu", name)
            if existing is not None:
                continue
            params = parse_lmu_hdv(path)
            if params is None:
                continue
            vehicle = VehicleParams(
                sim="lmu",
                car_name=name,
                mass_kg=params.get("mass_kg", 1300.0),
                cg_height_m=params.get("cg_height_m", 0.35),
            )
            self.lake.save_vehicle(vehicle)
            saved += 1
        return {"discovered": len(vehicles), "saved": saved}

    def _harvest_existing_data(self) -> dict:
        """Load TUMFTM reference tracks from data/external/tumftm_tracks/."""
        tumftm_dir = (
            Path(__file__).resolve().parents[2] / "data" / "external"
            / "tumftm_tracks"
        )
        if not tumftm_dir.is_dir():
            # Fallback: relative to project root
            from telemetry_tool.lap_oracle.config import PROJECT_ROOT
            tumftm_dir = PROJECT_ROOT / "data" / "external" / "tumftm_tracks"

        saved = 0
        if not tumftm_dir.is_dir():
            logger.info("TUMFTM tracks dir not found: %s", tumftm_dir)
            return {"saved": 0}

        for csv_path in sorted(tumftm_dir.glob("*.csv")):
            track_name = csv_path.stem
            if self.lake.load_track("tumftm", track_name) is not None:
                continue
            try:
                data = np.loadtxt(
                    str(csv_path), delimiter=",", skiprows=1,
                    dtype=np.float64,
                )
            except Exception as exc:
                logger.warning("Cannot read %s: %s", csv_path, exc)
                continue

            if data.ndim != 2 or data.shape[0] < 10 or data.shape[1] < 2:
                continue

            xy = data[:, :2]
            model = extract_from_telemetry_xy(
                xy, name=track_name, sim="tumftm",
            )
            if model is not None:
                # If CSV has width columns, use them
                if data.shape[1] >= 4:
                    n = model.n_points
                    # Columns: x_m, y_m, w_tr_right_m, w_tr_left_m
                    if data.shape[0] == n:
                        model.width_right = data[:, 2].copy()
                        model.width_left = data[:, 3].copy()
                self.lake.save_track(model)
                saved += 1
                logger.info(
                    "Saved TUMFTM track: %s (%d pts)",
                    track_name, model.n_points,
                )

        return {"saved": saved}


# -- helpers ---------------------------------------------------------------

def _latlon_to_xy(positions: np.ndarray) -> Optional[np.ndarray]:
    """Convert lat/lon (degrees) to local XY (metres) via equirectangular.

    Uses the centroid as origin.  Accurate enough for circuit-scale
    distances (<10 km).

    Parameters
    ----------
    positions:
        Shape ``(N, 2)`` array of ``[lat, lon]`` in decimal degrees.

    Returns
    -------
    np.ndarray or None
        Shape ``(N, 2)`` array of ``[x_m, y_m]``, or ``None`` if input
        is invalid.
    """
    if positions.ndim != 2 or positions.shape[1] < 2:
        return None

    lat = positions[:, 0]
    lon = positions[:, 1]

    lat_ref = np.mean(lat)
    lon_ref = np.mean(lon)

    # Metres per degree at reference latitude
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_132.0 * np.cos(np.radians(lat_ref))

    x = (lon - lon_ref) * m_per_deg_lon
    y = (lat - lat_ref) * m_per_deg_lat

    return np.column_stack((x, y))
