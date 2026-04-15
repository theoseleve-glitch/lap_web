"""Lap Oracle Data Lake -- SQLite job queue + file-based model storage.

Thread-safe (WAL mode, timeout=30).  Used by ALL oracle workers.
Serialization is JSON-only -- no unsafe binary formats.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from telemetry_tool.lap_oracle.config import (
    ORACLE_DATA,
    ORACLE_DB,
    OCPSolution,
    OracleConfig,
    PacejkaParams,
    SetupParams,
    TrackModel,
    VehicleParams,
    WeatherConditions,
)

# Valid job types and statuses ------------------------------------------------
_JOB_TYPES = {"harvest", "identify", "solve", "sweep", "train", "ac_drive"}
_JOB_STATUSES = {"pending", "running", "completed", "failed"}

# SQL DDL --------------------------------------------------------------------
_CREATE_JOBS = """\
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type    TEXT    NOT NULL,
    sim         TEXT,
    car         TEXT,
    track       TEXT,
    status      TEXT    DEFAULT 'pending',
    priority    REAL    DEFAULT 0.0,
    payload     TEXT    DEFAULT '{}',
    result      TEXT    DEFAULT '{}',
    created_at  REAL,
    started_at  REAL,
    completed_at REAL,
    worker_id   TEXT,
    error       TEXT
);
"""

_CREATE_JOBS_IDX1 = (
    "CREATE INDEX IF NOT EXISTS idx_jobs_status_prio "
    "ON jobs (status, priority DESC);"
)
_CREATE_JOBS_IDX2 = (
    "CREATE INDEX IF NOT EXISTS idx_jobs_type_status "
    "ON jobs (job_type, status);"
)

_CREATE_PROGRESS = """\
CREATE TABLE IF NOT EXISTS progress (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           REAL,
    phase               TEXT,
    combos_solved       INTEGER DEFAULT 0,
    setups_optimized    INTEGER DEFAULT 0,
    ac_laps_completed   INTEGER DEFAULT 0,
    neural_loss         REAL,
    details             TEXT DEFAULT '{}'
);
"""


class DataLake:
    """Central data store for the Lap Oracle system.

    Parameters
    ----------
    config : OracleConfig | None
        If *None*, uses default paths from ``config.py``.
    """

    def __init__(self, config: Optional[OracleConfig] = None) -> None:
        cfg = config or OracleConfig()
        self.data_dir: Path = cfg.data_dir
        self.db_path: Path = cfg.db_path

        # Create subdirectories
        for sub in (
            "telemetry", "tracks", "vehicles", "solutions",
            "setups", "models", "reports",
        ):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)

        # Initialise SQLite (WAL, 30s timeout)
        self._init_db()

    # -- private helpers ---------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute(_CREATE_JOBS)
            conn.execute(_CREATE_JOBS_IDX1)
            conn.execute(_CREATE_JOBS_IDX2)
            conn.execute(_CREATE_PROGRESS)
            conn.commit()
        finally:
            conn.close()

    # =====================================================================
    # Jobs
    # =====================================================================

    def add_job(
        self,
        job_type: str,
        sim: Optional[str] = None,
        car: Optional[str] = None,
        track: Optional[str] = None,
        priority: float = 0.0,
        payload: Optional[dict] = None,
    ) -> int:
        """Insert a new job and return its id."""
        if job_type not in _JOB_TYPES:
            raise ValueError(f"Invalid job_type: {job_type}")
        payload_json = json.dumps(payload or {}, default=str)
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO jobs "
                "(job_type, sim, car, track, priority, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?);",
                (job_type, sim, car, track, priority, payload_json, time.time()),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        finally:
            conn.close()

    def claim_job(
        self, job_type: str, worker_id: str,
    ) -> Optional[Dict]:
        """Atomically claim the highest-priority pending job of *job_type*.

        Returns the job row as a dict, or *None* if nothing available.
        Uses ``BEGIN IMMEDIATE`` to serialize concurrent claims.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT id FROM jobs "
                "WHERE job_type = ? AND status = 'pending' "
                "ORDER BY priority DESC, id ASC LIMIT 1;",
                (job_type,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            job_id = row["id"]
            now = time.time()
            conn.execute(
                "UPDATE jobs SET status = 'running', "
                "worker_id = ?, started_at = ? WHERE id = ?;",
                (worker_id, now, job_id),
            )
            conn.commit()
            # Re-fetch full row
            claimed = conn.execute(
                "SELECT * FROM jobs WHERE id = ?;", (job_id,)
            ).fetchone()
            return dict(claimed)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete_job(
        self,
        job_id: int,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark a job as completed (or failed if *error* is set)."""
        status = "failed" if error else "completed"
        result_json = json.dumps(result or {}, default=str)
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE jobs SET status = ?, result = ?, error = ?, "
                "completed_at = ? WHERE id = ?;",
                (status, result_json, error, time.time(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def count_jobs(
        self, job_type: Optional[str] = None, status: Optional[str] = None,
    ) -> int:
        """Count jobs matching optional *job_type* and/or *status*."""
        clauses: list[str] = []
        params: list = []
        if job_type is not None:
            clauses.append("job_type = ?")
            params.append(job_type)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM jobs{where};", params,
            ).fetchone()
            return row["cnt"]
        finally:
            conn.close()

    def job_exists(
        self, job_type: str, sim: str, car: str, track: str,
    ) -> bool:
        """True if a non-failed job with these identifiers already exists."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM jobs "
                "WHERE job_type = ? AND sim = ? AND car = ? AND track = ? "
                "AND status != 'failed';",
                (job_type, sim, car, track),
            ).fetchone()
            return row["cnt"] > 0
        finally:
            conn.close()

    # =====================================================================
    # Vehicle Models
    # =====================================================================

    def save_vehicle(self, vehicle: VehicleParams) -> Path:
        """Persist *vehicle* as JSON.  Returns the written path."""
        dest = self.data_dir / "vehicles" / f"{vehicle.sim}_{vehicle.car_name}.json"
        dest.write_text(
            json.dumps(vehicle.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        return dest

    def load_vehicle(
        self, sim: str, car_name: str,
    ) -> Optional[VehicleParams]:
        """Load a vehicle model from disk, or *None* if not found."""
        path = self.data_dir / "vehicles" / f"{sim}_{car_name}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return VehicleParams.from_dict(data)

    def list_vehicles(self) -> List[Tuple[str, str]]:
        """Return ``(sim, car_name)`` pairs for all saved vehicles."""
        result: list[tuple[str, str]] = []
        vehicles_dir = self.data_dir / "vehicles"
        for p in sorted(vehicles_dir.glob("*.json")):
            stem = p.stem
            # First underscore separates sim from car_name
            parts = stem.split("_", 1)
            if len(parts) == 2:
                result.append((parts[0], parts[1]))
        return result

    # =====================================================================
    # Track Models
    # =====================================================================

    def save_track(self, track: TrackModel) -> Path:
        """Persist *track* as a compressed npz file.  Atomic write via temp file."""
        dest = self.data_dir / "tracks" / f"{track.sim}_{track.name}.npz"
        # np.savez_compressed appends .npz if not present, so use .tmp as stem
        tmp_stem = self.data_dir / "tracks" / f"_tmp_{track.sim}_{track.name}"
        np.savez_compressed(
            str(tmp_stem),
            centerline_xy=track.centerline_xy,
            width_left=track.width_left,
            width_right=track.width_right,
            curvature=track.curvature,
            elevation=track.elevation,
            banking=track.banking,
            grip_map=track.grip_map,
            sector_boundaries=np.array(track.sector_boundaries, dtype=np.int64),
            meta=np.array([track.total_length_m], dtype=np.float64),
        )
        tmp_file = tmp_stem.with_suffix(".npz")  # savez_compressed adds .npz
        try:
            tmp_file.replace(dest)
        except OSError:
            # Windows: target may be locked; fall back to copy+delete
            import shutil
            shutil.copy2(str(tmp_file), str(dest))
            tmp_file.unlink(missing_ok=True)
        return dest

    def load_track(
        self, sim: str, name: str,
    ) -> Optional[TrackModel]:
        """Load a track model from disk, or *None* if not found."""
        path = self.data_dir / "tracks" / f"{sim}_{name}.npz"
        if not path.exists():
            return None
        try:
            data = np.load(str(path), allow_pickle=False)
        except (EOFError, OSError, ValueError) as exc:
            logger.warning("Corrupted track file %s: %s — removing", path, exc)
            path.unlink(missing_ok=True)
            return None
        total_length = float(data["meta"][0])
        sector_boundaries = data["sector_boundaries"].tolist()
        return TrackModel(
            name=name,
            sim=sim,
            centerline_xy=data["centerline_xy"],
            width_left=data["width_left"],
            width_right=data["width_right"],
            curvature=data["curvature"],
            elevation=data["elevation"],
            banking=data["banking"],
            grip_map=data["grip_map"],
            sector_boundaries=sector_boundaries,
            total_length_m=total_length,
        )

    def list_tracks(self) -> List[Tuple[str, str]]:
        """Return ``(sim, name)`` pairs for all saved tracks."""
        result: list[tuple[str, str]] = []
        tracks_dir = self.data_dir / "tracks"
        for p in sorted(tracks_dir.glob("*.npz")):
            stem = p.stem
            parts = stem.split("_", 1)
            if len(parts) == 2:
                result.append((parts[0], parts[1]))
        return result

    # =====================================================================
    # OCP Solutions
    # =====================================================================

    def save_solution(self, sol: OCPSolution) -> Path:
        """Persist an OCP solution (arrays as npz, metadata as JSON).

        Directory structure: ``solutions/{sim}/{track}/{car}/``
        Filename suffix encodes weather: ``dry_25c`` or ``wet_15c``.
        """
        base = (
            self.data_dir / "solutions"
            / sol.sim / sol.track_name / sol.car_name
        )
        base.mkdir(parents=True, exist_ok=True)

        # Build filename suffix from weather
        w = sol.weather
        condition = "wet" if w.is_wet else "dry"
        temp = int(w.air_temp_c)
        suffix = f"{condition}_{temp}c"

        # Save arrays
        npz_path = base / f"{suffix}.npz"
        np.savez_compressed(
            str(npz_path),
            distance_m=sol.distance_m,
            speed_mps=sol.speed_mps,
            throttle=sol.throttle,
            brake=sol.brake,
            steering_rad=sol.steering_rad,
            lateral_offset_m=sol.lateral_offset_m,
        )

        # Save metadata
        meta: dict = {
            "sim": sol.sim,
            "track_name": sol.track_name,
            "car_name": sol.car_name,
            "weather": asdict(sol.weather),
            "optimal_lap_time_s": sol.optimal_lap_time_s,
            "sector_times_s": sol.sector_times_s,
            "solver_status": sol.solver_status,
            "solver_time_s": sol.solver_time_s,
        }
        if sol.vehicle_params is not None:
            meta["vehicle_params"] = sol.vehicle_params.to_dict()
        meta_path = base / f"{suffix}_meta.json"
        meta_path.write_text(
            json.dumps(meta, indent=2, default=str), encoding="utf-8",
        )
        return npz_path

    def count_solutions(self) -> int:
        """Count the total number of saved OCP solution npz files."""
        solutions_dir = self.data_dir / "solutions"
        if not solutions_dir.exists():
            return 0
        return sum(1 for _ in solutions_dir.rglob("*.npz"))

    # =====================================================================
    # Progress
    # =====================================================================

    def log_progress(self, phase: str, **kwargs) -> None:
        """Insert a progress record.

        Accepted kwargs: combos_solved, setups_optimized,
        ac_laps_completed, neural_loss, details (dict).
        """
        details = json.dumps(kwargs.pop("details", {}), default=str)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO progress "
                "(timestamp, phase, combos_solved, setups_optimized, "
                "ac_laps_completed, neural_loss, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?);",
                (
                    time.time(),
                    phase,
                    kwargs.get("combos_solved", 0),
                    kwargs.get("setups_optimized", 0),
                    kwargs.get("ac_laps_completed", 0),
                    kwargs.get("neural_loss"),
                    details,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_progress_summary(self) -> Dict:
        """Aggregate job counts by type/status + asset counts.

        Returns a dict with keys:
        - ``jobs``: ``{job_type: {status: count}}``
        - ``vehicles``: int
        - ``tracks``: int
        - ``solutions``: int
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT job_type, status, COUNT(*) AS cnt "
                "FROM jobs GROUP BY job_type, status;"
            ).fetchall()
        finally:
            conn.close()

        jobs: Dict[str, Dict[str, int]] = {}
        for r in rows:
            jt = r["job_type"]
            if jt not in jobs:
                jobs[jt] = {}
            jobs[jt][r["status"]] = r["cnt"]

        return {
            "jobs": jobs,
            "vehicles": len(self.list_vehicles()),
            "tracks": len(self.list_tracks()),
            "solutions": self.count_solutions(),
        }
