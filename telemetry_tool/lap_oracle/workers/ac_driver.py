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
        """Pick a validated car/track combo from AC's installed content.

        Returns (car_folder_name, track_spec) or None.
        track_spec is "track_folder" or "track_folder/layout" if layouts exist.
        Only returns combos where the car has a .kn5 model and the track has ui/.
        """
        from telemetry_tool.lap_oracle.config import SIM_PATHS

        ac_cars: List[str] = []
        ac_tracks: List[str] = []  # "track" or "track/layout"

        for base in SIM_PATHS.get("ac", []):
            # Validate cars: must have at least one .kn5 3D model
            cars_dir = base / "content" / "cars"
            if cars_dir.is_dir():
                for d in sorted(cars_dir.iterdir()):
                    if not d.is_dir() or d.name in ac_cars:
                        continue
                    has_model = any(d.glob("*.kn5"))
                    has_data = (d / "data.acd").exists() or (d / "data").is_dir()
                    if has_model and has_data:
                        ac_cars.append(d.name)

            # Validate tracks: must have ui/ folder. Check for layouts.
            tracks_dir = base / "content" / "tracks"
            if tracks_dir.is_dir():
                for d in sorted(tracks_dir.iterdir()):
                    if not d.is_dir():
                        continue
                    # Check for layout subfolders (e.g. ks_monza66/road, ks_monza66/junior)
                    layouts_found = False
                    for sub in sorted(d.iterdir()):
                        if sub.is_dir() and (sub / "ui").is_dir():
                            spec = d.name + "/" + sub.name
                            if spec not in ac_tracks:
                                ac_tracks.append(spec)
                                layouts_found = True
                    # If no layouts, check if top-level has ui/
                    if not layouts_found and (d / "ui").is_dir():
                        if d.name not in ac_tracks:
                            ac_tracks.append(d.name)

        if not ac_cars or not ac_tracks:
            logger.warning("No valid AC cars (%d) or tracks (%d)", len(ac_cars), len(ac_tracks))
            return None

        logger.info("AC content: %d cars, %d tracks", len(ac_cars), len(ac_tracks))

        # Pick first combo not yet driven
        for track_spec in ac_tracks:
            for car in ac_cars[:10]:
                track_key = track_spec.replace("/", "_")
                if not self.lake.job_exists("solve", "ac", car, track_key):
                    return (car, track_spec)

        return (ac_cars[0], ac_tracks[0])

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

        # Track spec can be "track_name" or "track_name/layout"
        if "/" in track:
            track_name, config_track = track.split("/", 1)
        else:
            track_name, config_track = track, ""

        cp["RACE"] = {
            "MODEL": car,
            "MODEL_CONFIG": "",
            "SKIN": "",
            "TRACK": track_name,
            "CONFIG_TRACK": config_track,
            "AI_LEVEL": "0",
            "PENALTIES": "0",
            "LAPS": str(_LAPS_PER_SESSION + 1),
            "CARS": "1",
            "FIXED_SETUP": "0",
        }
        # Find first available skin
        skin = ""
        from telemetry_tool.lap_oracle.config import SIM_PATHS
        for base in SIM_PATHS.get("ac", []):
            skins_dir = base / "content" / "cars" / car / "skins"
            if skins_dir.is_dir():
                for s in sorted(skins_dir.iterdir()):
                    if s.is_dir():
                        skin = s.name
                        break
                if skin:
                    break

        cp["CAR_0"] = {
            "MODEL": car,
            "SKIN": skin,
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
        """Launch AC via Content Manager or Steam launcher.

        Content Manager handles CSP patching and proper session setup.
        Falls back to Steam launch if CM not found.
        """
        cm_exe = Path("C:/Users/Admin/Desktop/Content Manager.exe")
        ac_exe = Path(self.config.ac_exe)

        if cm_exe.exists():
            # Content Manager: launch with race preset via command line
            # CM reads race.ini and starts the session directly
            self._ac_process = subprocess.Popen(
                [str(cm_exe), "--race"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ac_running = True
            logger.info("Launched AC via Content Manager (pid=%d)", self._ac_process.pid)
        elif ac_exe.exists():
            # Fallback: launch via AssettoCorsa.exe (the launcher)
            self._ac_process = subprocess.Popen(
                [str(ac_exe)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ac_running = True
            logger.info("Launched AC via launcher (pid=%d)", self._ac_process.pid)
        else:
            logger.warning("Neither Content Manager nor AC exe found")
            return

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
