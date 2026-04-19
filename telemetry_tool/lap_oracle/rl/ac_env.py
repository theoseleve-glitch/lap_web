"""Gymnasium environment wrapping Assetto Corsa via shared memory + TCP.

Connects to the AC process via Windows shared memory (SHM) for
observations and a TCP bridge for control injection.  Requires
the ``lap_oracle_bridge`` AC Python app to be installed.

Gracefully degrades if ``gymnasium`` is not available.
"""
from __future__ import annotations

import json
import logging
import socket
import struct
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# -- Optional imports ------------------------------------------------------
try:
    import gymnasium as gym
    from gymnasium import spaces

    HAS_GYM = True
except ImportError:
    HAS_GYM = False

try:
    import mmap

    HAS_MMAP = True
except ImportError:
    HAS_MMAP = False

# -- Constants -------------------------------------------------------------
OBS_DIM = 23
ACT_DIM = 3
DEFAULT_PORT = 9876
SHM_PHYSICS = "acpmf_physics"
SHM_GRAPHICS = "acpmf_graphics"


# -- Environment -----------------------------------------------------------

if HAS_GYM:
    _BASE_ENV = gym.Env
else:
    _BASE_ENV = object  # type: ignore[misc,assignment]


class ACGymEnv(_BASE_ENV):
    """Gymnasium environment for Assetto Corsa.

    Observation space (23 dims):
      [0]     speed (m/s)
      [1]     lateral acceleration (g)
      [2]     longitudinal acceleration (g)
      [3]     yaw rate (rad/s)
      [4]     lap distance percent (0-1)
      [5]     track offset (m, signed)
      [6-9]   tyre temperatures (4 wheels, normalized)
      [10-19] upcoming curvature (10 samples ahead)
      [20]    gear (normalized)
      [21]    rpm (normalized 0-1)
      [22]    fuel percent (0-1)

    Action space (3 dims):
      [0] steering (-1 to 1)
      [1] throttle (0 to 1)
      [2] brake (0 to 1)
    """

    metadata: Dict[str, Any] = {"render_modes": []}

    def __init__(
        self, port: int = DEFAULT_PORT, render_mode: Optional[str] = None,
    ) -> None:
        if HAS_GYM:
            super().__init__()
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf,
                shape=(OBS_DIM,), dtype=np.float32,
            )
            self.action_space = spaces.Box(
                low=np.array([-1.0, 0.0, 0.0]),
                high=np.array([1.0, 1.0, 1.0]),
                dtype=np.float32,
            )

        self._port = port
        self._physics_shm = None
        self._graphics_shm = None
        self._gamepad = None
        self._connected = False
        self._prev_lap_dist = 0.0

    # -- Connection --------------------------------------------------------

    def connect(self) -> bool:
        """Open shared memory for reading and virtual gamepad for control.

        Returns True if at least SHM or gamepad is connected.
        """
        shm_ok = False
        gamepad_ok = False

        # SHM for reading telemetry
        if HAS_MMAP:
            try:
                self._physics_shm = mmap.mmap(
                    -1, 4096, SHM_PHYSICS, access=mmap.ACCESS_READ,
                )
                self._graphics_shm = mmap.mmap(
                    -1, 4096, SHM_GRAPHICS, access=mmap.ACCESS_READ,
                )
                shm_ok = True
                logger.info("AC shared memory connected")
            except (OSError, ValueError) as exc:
                logger.warning("Cannot open AC SHM: %s", exc)
                self._physics_shm = None
                self._graphics_shm = None

        # Virtual gamepad for control injection
        try:
            from telemetry_tool.lap_oracle.rl.gamepad_controller import GamepadController
            self._gamepad = GamepadController()
            gamepad_ok = self._gamepad.connect()
            if gamepad_ok:
                logger.info("Virtual gamepad connected")
            else:
                logger.warning("Virtual gamepad failed to connect")
        except ImportError:
            logger.warning("GamepadController not available")

        self._connected = gamepad_ok
        return shm_ok or gamepad_ok

    def close(self) -> None:
        """Disconnect from AC."""
        if self._gamepad is not None:
            self._gamepad.release()
            self._gamepad = None
        if self._physics_shm is not None:
            self._physics_shm.close()
            self._physics_shm = None
        if self._graphics_shm is not None:
            self._graphics_shm.close()
            self._graphics_shm = None
        self._connected = False

    # -- Gym interface -----------------------------------------------------

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> Tuple[np.ndarray, dict]:
        """Reset the environment.  Returns (obs, info)."""
        if HAS_GYM:
            super().reset(seed=seed)
        self._prev_lap_dist = 0.0
        obs = self._read_state()
        return obs, {}

    def step(
        self, action: np.ndarray,
    ) -> Tuple[np.ndarray, float, bool, bool, dict]:
        """Execute one step.  Returns (obs, reward, terminated, truncated, info)."""
        action = np.asarray(action, dtype=np.float32)
        self._send_control(
            steer=float(action[0]),
            throttle=float(action[1]),
            brake=float(action[2]),
        )

        # Small delay for physics to step
        time.sleep(0.01)

        obs = self._read_state()

        from telemetry_tool.lap_oracle.rl.reward import compute_reward

        reward = compute_reward(obs, action, self._prev_lap_dist)
        self._prev_lap_dist = float(obs[4]) if len(obs) > 4 else 0.0

        terminated = False
        truncated = False
        info: dict = {}

        return obs, reward, terminated, truncated, info

    # -- I/O ---------------------------------------------------------------

    def _send_control(
        self, steer: float, throttle: float, brake: float,
    ) -> None:
        """Send control inputs via virtual gamepad."""
        if self._gamepad is not None and self._gamepad.connected:
            self._gamepad.send(steer, throttle, brake)

    def _read_state(self) -> np.ndarray:
        """Read observation from shared memory.

        Returns a zeros array if SHM is not available.
        """
        obs = np.zeros(OBS_DIM, dtype=np.float32)

        if self._physics_shm is None:
            return obs

        try:
            self._physics_shm.seek(0)
            raw = self._physics_shm.read(256)
            if len(raw) >= 92:  # Enough for basic fields
                # AC SHM layout (simplified, first floats):
                # speed_kmh, ...
                vals = struct.unpack_from("<23f", raw[:92])
                obs[:] = np.array(vals, dtype=np.float32)
                # Convert speed from km/h to m/s
                obs[0] = obs[0] / 3.6
        except (struct.error, ValueError, OSError):
            pass

        return obs
