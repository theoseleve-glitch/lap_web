"""AC Driver worker -- launches Assetto Corsa for autonomous data collection.

Manages the AC process lifecycle: writes ``race.ini``, launches the game,
connects the RL environment, collects telemetry for N laps, then kills AC
and processes the collected data.

Falls back to SHM-only data collection if the TCP bridge cannot connect.
"""
from __future__ import annotations

import configparser
import io
import logging
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from telemetry_tool.lap_oracle.config import OracleConfig, VehicleParams
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.workers.base import BaseWorker

logger = logging.getLogger(__name__)

# Number of laps to collect per AC session
_LAPS_PER_SESSION = 5


class ACDriverWorker(BaseWorker):
    """Launches AC sessions and collects telemetry via RL env.

    Priority queue of car/track combos is derived from the data lake:
    combos that have never been driven are prioritised.
    """

    worker_type: str = "ac_driver"

    def __init__(
        self,
        worker_id: str,
        lake: DataLake,
        config: OracleConfig,
    ) -> None:
        super().__init__(worker_id, lake, config)
        self._ac_running = False
        self._ac_process: Optional[subprocess.Popen] = None

    def tick(self) -> bool:
        """Run one AC session: pick combo, launch, collect, process.

        Returns True if work was performed.
        """
        if not self.config.enable_ac_driver:
            return False

        if self._ac_running:
            # AC still running from previous tick -- wait
            return False

        # Pick next car/track combo
        combo = self._pick_next_combo()
        if combo is None:
            return False

        car, track = combo
        logger.info("AC session: %s @ %s", car, track)

        try:
            self._write_race_ini(car, track)
            self._launch_ac()
            telemetry = self._collect_telemetry()
            self._kill_ac()
            self._process_telemetry(car, track, telemetry)
            return True
        except Exception as exc:
            logger.exception("AC session failed: %s", exc)
            self._kill_ac()
            return True

    # -- Combo selection ---------------------------------------------------

    def _pick_next_combo(self) -> Optional[Tuple[str, str]]:
        """Pick a car/track combo that needs data.

        Returns (car_name, track_name) or None if nothing to do.
        """
        vehicles = self.lake.list_vehicles()
        tracks = self.lake.list_tracks()

        # Prefer AC vehicles+tracks
        ac_vehicles = [(s, c) for s, c in vehicles if s == "ac"]
        ac_tracks = [(s, t) for s, t in tracks if s == "ac"]

        for _, car in ac_vehicles:
            for _, track in ac_tracks:
                if not self.lake.job_exists("solve", "ac", car, track):
                    return (car, track)

        # Fall back to any vehicle+track pair
        for _, car in vehicles[:5]:
            for _, track in tracks[:5]:
                return (car, track)

        return None

    # -- race.ini ----------------------------------------------------------

    def _write_race_ini(self, car: str, track: str) -> Path:
        """Write AC race.ini for the requested car/track combo.

        Returns the path to the written file.
        """
        cfg_dir = Path(self.config.ac_cfg_dir)
        cfg_dir.mkdir(parents=True, exist_ok=True)
        race_ini = cfg_dir / "race.ini"

        cp = configparser.ConfigParser()
        cp.optionxform = str  # preserve case

        cp["RACE"] = {
            "MODEL": car,
            "MODEL_CONFIG": "",
            "SKIN": "",
            "TRACK": track,
            "CONFIG_TRACK": "",
            "AI_LEVEL": "0",
            "PENALTIES": "0",
            "LAPS": str(_LAPS_PER_SESSION + 1),
        }
        cp["CAR_0"] = {
            "MODEL": car,
            "SKIN": "",
            "SETUP": "",
            "BALLAST": "0",
            "RESTRICTOR": "0",
            "DRIVER_NAME": "Lap Oracle",
            "NATIONALITY": "",
        }
        cp["SESSION_0"] = {
            "NAME": "Practice",
            "TYPE": "1",
            "DURATION_MINUTES": "30",
            "SPAWN_SET": "START",
        }

        buf = io.StringIO()
        cp.write(buf)
        race_ini.write_text(buf.getvalue(), encoding="utf-8")
        logger.debug("Wrote race.ini: %s", race_ini)
        return race_ini

    # -- AC lifecycle ------------------------------------------------------

    def _launch_ac(self) -> None:
        """Launch the AC executable and wait for SHM to appear."""
        ac_exe = Path(self.config.ac_exe)
        if not ac_exe.exists():
            logger.warning("AC exe not found: %s", ac_exe)
            return

        self._ac_process = subprocess.Popen(
            [str(ac_exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._ac_running = True
        logger.info("Launched AC (pid=%d)", self._ac_process.pid)

        # Wait for SHM to become available
        timeout = self.config.ac_launch_timeout
        start = time.time()
        while time.time() - start < timeout:
            try:
                import mmap
                shm = mmap.mmap(-1, 4096, "acpmf_physics", access=mmap.ACCESS_READ)
                shm.close()
                logger.info("AC SHM detected after %.1f s", time.time() - start)
                return
            except (OSError, ValueError):
                time.sleep(2.0)

        logger.warning("AC SHM not detected within %d s", timeout)

    def _kill_ac(self) -> None:
        """Kill the AC process forcefully."""
        self._ac_running = False
        if self._ac_process is not None:
            try:
                self._ac_process.terminate()
                self._ac_process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass

        # taskkill as backup
        for exe_name in ("acs.exe", "AssettoCorsa.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name],
                    capture_output=True, timeout=10,
                )
            except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
                pass

        self._ac_process = None
        logger.info("AC process killed")

    # -- Telemetry collection ----------------------------------------------

    def _collect_telemetry(self) -> List[np.ndarray]:
        """Collect telemetry via the RL environment.

        Returns a list of observation arrays (one per step).
        Falls back to SHM-only if bridge doesn't connect.
        """
        try:
            from telemetry_tool.lap_oracle.rl.ac_env import ACGymEnv
        except ImportError:
            logger.warning("ACGymEnv not available")
            return []

        env = ACGymEnv(port=self.config.ac_bridge_port)
        connected = env.connect()

        frames: List[np.ndarray] = []
        max_steps = _LAPS_PER_SESSION * 5000  # ~5000 steps per lap

        try:
            obs, _ = env.reset()
            for _ in range(max_steps):
                if not self._ac_running:
                    break

                if connected:
                    # Simple constant-throttle policy for data collection
                    action = np.array([0.0, 0.8, 0.0], dtype=np.float32)
                    obs, reward, terminated, truncated, info = env.step(action)
                else:
                    # SHM-only: just read state
                    obs = env._read_state()
                    time.sleep(0.02)

                frames.append(obs.copy())
        finally:
            env.close()

        logger.info("Collected %d frames", len(frames))
        return frames

    # -- Post-processing ---------------------------------------------------

    def _process_telemetry(
        self,
        car: str,
        track: str,
        telemetry: List[np.ndarray],
    ) -> None:
        """Build VehicleParams from telemetry and enqueue solve jobs."""
        if not telemetry:
            return

        # Save raw telemetry
        tel_dir = self.lake.data_dir / "telemetry" / "ac"
        tel_dir.mkdir(parents=True, exist_ok=True)
        tel_path = tel_dir / f"{car}_{track}.npz"
        np.savez_compressed(
            str(tel_path),
            frames=np.array(telemetry, dtype=np.float32),
        )

        # Enqueue solve job if vehicle exists
        vehicle = self.lake.load_vehicle("ac", car)
        if vehicle is not None and not self.lake.job_exists(
            "solve", "ac", car, track,
        ):
            self.lake.add_job(
                "solve", sim="ac", car=car, track=track, priority=7.0,
            )

        self.lake.log_progress(
            "ac_driver",
            ac_laps_completed=_LAPS_PER_SESSION,
            details={"car": car, "track": track, "frames": len(telemetry)},
        )
