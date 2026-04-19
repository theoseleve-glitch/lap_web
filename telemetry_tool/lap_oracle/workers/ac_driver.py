"""AC Driver worker -- launches Assetto Corsa for autonomous data collection.

Manages the AC process lifecycle: writes ``race.ini``, launches the game,
connects the RL environment, collects telemetry for N laps, then kills AC
and processes the collected data.

Falls back to SHM-only data collection if the TCP bridge cannot connect.
"""
from __future__ import annotations

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

# Track names/patterns to skip (not real circuits)
_SKIP_TRACKS = {"drift", "drag", "dragstrip", "hillclimb", "test", "showroom"}


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

            # Validate tracks: must have ui/ + data/ + ai/ (complete track)
            tracks_dir = base / "content" / "tracks"
            if tracks_dir.is_dir():
                for d in sorted(tracks_dir.iterdir()):
                    if not d.is_dir():
                        continue

                    def _is_valid_track(track_dir: Path) -> bool:
                        """Check track has essential physics/AI files."""
                        return (
                            (track_dir / "ui").is_dir()
                            and (track_dir / "data").is_dir()
                            and (track_dir / "ai").is_dir()
                            and (track_dir / "ai" / "fast_lane.ai").exists()
                        )

                    # Check for layout subfolders
                    layouts_found = False
                    for sub in sorted(d.iterdir()):
                        if sub.is_dir() and _is_valid_track(sub):
                            spec = d.name + "/" + sub.name
                            if spec not in ac_tracks:
                                ac_tracks.append(spec)
                                layouts_found = True
                    # If no layouts, check top-level
                    if not layouts_found and _is_valid_track(d):
                        if d.name not in ac_tracks:
                            ac_tracks.append(d.name)

        # Filter out non-circuit tracks (drift arenas, drag strips, etc.)
        ac_tracks = [
            t for t in ac_tracks
            if not any(skip in t.lower() for skip in _SKIP_TRACKS)
        ]

        if not ac_cars or not ac_tracks:
            logger.warning("No valid AC cars (%d) or tracks (%d)", len(ac_cars), len(ac_tracks))
            return None

        logger.info("AC content: %d cars, %d tracks", len(ac_cars), len(ac_tracks))

        # Pick first combo not yet driven (check ac_drive jobs, not solve)
        for track_spec in ac_tracks:
            for car in ac_cars[:10]:
                track_key = track_spec.replace("/", "_")
                if not self.lake.job_exists("ac_drive", "ac", car, track_key):
                    return (car, track_spec)

        return None  # all combos driven

    # -- race.ini ----------------------------------------------------------

    def _write_race_ini(self, car: str, track: str) -> Path:
        """Write AC race.ini for the requested car/track combo.

        Uses plain string output (no configparser) because AC's INI reader
        requires ``KEY=VALUE`` with no spaces around ``=``.
        """
        cfg_dir = Path(self.config.ac_cfg_dir)
        cfg_dir.mkdir(parents=True, exist_ok=True)
        race_ini = cfg_dir / "race.ini"

        # Track spec can be "track_name" or "track_name/layout"
        if "/" in track:
            track_name, config_track = track.split("/", 1)
        else:
            track_name, config_track = track, ""

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

        content = (
            "[HEADER]\n"
            "VERSION=2\n"
            "\n"
            "[RACE]\n"
            f"MODEL={car}\n"
            "MODEL_CONFIG=\n"
            f"SKIN={skin}\n"
            f"TRACK={track_name}\n"
            f"CONFIG_TRACK={config_track}\n"
            "AI_LEVEL=0\n"
            "PENALTIES=0\n"
            f"LAPS={_LAPS_PER_SESSION + 1}\n"
            "CARS=1\n"
            "FIXED_SETUP=0\n"
            "DRIFT_MODE=0\n"
            "\n"
            "[CAR_0]\n"
            f"MODEL={car}\n"
            f"SKIN={skin}\n"
            "SETUP=\n"
            "BALLAST=0\n"
            "RESTRICTOR=0\n"
            "DRIVER_NAME=Lap Oracle\n"
            "NATIONALITY=\n"
            "\n"
            "[SESSION_0]\n"
            "NAME=Practice\n"
            "TYPE=1\n"
            "DURATION_MINUTES=30\n"
            "SPAWN_SET=START\n"
        )
        race_ini.write_text(content, encoding="utf-8")
        logger.debug("Wrote race.ini: %s", race_ini)
        return race_ini

    # -- AC lifecycle ------------------------------------------------------

    def _launch_ac(self) -> None:
        """Launch AC via Content Manager or Steam.

        Direct acs.exe launch crashes in SharedMemoryWriter::writeStatic
        because CSP requires Content Manager's initialization chain.
        Falls back to Steam launch (steam://rungameid/244210) if CM
        is not found.
        """
        cm_exe = Path("C:/Users/Admin/Desktop/Content Manager.exe")

        if cm_exe.exists():
            # CM reads race.ini from Documents and launches AC properly
            self._ac_process = subprocess.Popen(
                [str(cm_exe), "--run=race"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ac_running = True
            logger.info("Launched AC via Content Manager (pid=%d)", self._ac_process.pid)
        else:
            # Fall back to Steam launch — handles CSP initialization
            subprocess.Popen(
                ["cmd", "/c", "start", "steam://rungameid/244210"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ac_running = True
            self._ac_process = None  # Steam manages the process
            logger.info("Launched AC via Steam")

        # Wait for AC to be fully running.
        # CRITICAL: Do NOT touch shared memory (mmap) during AC startup.
        # Any SHM access before AC finishes initializing can corrupt the
        # memory-mapped region and crash SharedMemoryWriter::writeStatic.
        # Instead, just wait and check process liveness.
        timeout = self.config.ac_launch_timeout
        start = time.time()
        wait_secs = min(30.0, timeout * 0.3)

        logger.info("Waiting %.0f s for AC to initialize...", wait_secs)
        while time.time() - start < wait_secs:
            time.sleep(2.0)
            if self._ac_process is not None and self._ac_process.poll() is not None:
                logger.warning("AC process died during startup (exit code %d)", self._ac_process.returncode)
                self._ac_running = False
                return

        # After initial wait, check if process is still alive
        if self._ac_process is not None and self._ac_process.poll() is not None:
            logger.warning("AC process died after init wait (exit code %d)", self._ac_process.returncode)
            self._ac_running = False
            return

        logger.info("AC startup wait complete (%.1f s), process alive (pid=%d)",
                     time.time() - start, self._ac_process.pid)

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
        for exe_name in ("acs.exe", "acs_x86.exe", "AssettoCorsa.exe"):
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
        """Save telemetry, mark combo as driven, enqueue solve if possible."""
        track_key = track.replace("/", "_")

        if not telemetry:
            # Mark combo as driven even with no data (prevents retry loop)
            self.lake.add_job(
                "ac_drive", sim="ac", car=car, track=track_key, priority=0.0,
            )
            return

        # Save raw telemetry
        tel_dir = self.lake.data_dir / "telemetry" / "ac"
        tel_dir.mkdir(parents=True, exist_ok=True)
        tel_path = tel_dir / f"{car}_{track_key}.npz"
        np.savez_compressed(
            str(tel_path),
            frames=np.array(telemetry, dtype=np.float32),
        )

        # Always mark combo as driven so we don't repeat it
        self.lake.add_job(
            "ac_drive", sim="ac", car=car, track=track_key, priority=0.0,
        )

        # Enqueue solve job if vehicle model exists
        vehicle = self.lake.load_vehicle("ac", car)
        if vehicle is not None and not self.lake.job_exists(
            "solve", "ac", car, track_key,
        ):
            self.lake.add_job(
                "solve", sim="ac", car=car, track=track_key, priority=7.0,
            )

        self.lake.log_progress(
            "ac_driver",
            ac_laps_completed=_LAPS_PER_SESSION,
            details={"car": car, "track": track_key, "frames": len(telemetry)},
        )
