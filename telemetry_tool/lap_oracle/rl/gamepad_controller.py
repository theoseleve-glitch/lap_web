"""Virtual Xbox 360 gamepad controller for AC autonomous driving.

Uses ViGEm to create a virtual gamepad that AC reads as a normal
controller. No AC mods or Python apps needed — works with base game.

Mapping:
  Left stick X-axis  → steering (-1 left, +1 right)
  Right trigger      → throttle (0 to 1)
  Left trigger       → brake (0 to 1)
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

try:
    import vgamepad as vg
    HAS_VGAMEPAD = True
except ImportError:
    HAS_VGAMEPAD = False
    log.warning("vgamepad not installed — virtual gamepad unavailable")


class GamepadController:
    """Virtual Xbox 360 controller for sim racing."""

    def __init__(self) -> None:
        self._pad = None
        self._connected = False

    def connect(self) -> bool:
        """Create the virtual gamepad. Returns True on success."""
        if not HAS_VGAMEPAD:
            return False
        try:
            self._pad = vg.VX360Gamepad()
            self._connected = True
            # Center all inputs
            self.send(0.0, 0.0, 0.0)
            log.info("Virtual gamepad created")
            return True
        except Exception as exc:
            log.error("Failed to create virtual gamepad: %s", exc)
            return False

    def send(self, steer: float, throttle: float, brake: float) -> None:
        """Send control inputs to the virtual gamepad.

        Parameters
        ----------
        steer : float
            Steering angle, -1.0 (full left) to +1.0 (full right).
        throttle : float
            Throttle, 0.0 to 1.0.
        brake : float
            Brake, 0.0 to 1.0.
        """
        if not self._connected or self._pad is None:
            return
        # Clamp values
        steer = max(-1.0, min(1.0, steer))
        throttle = max(0.0, min(1.0, throttle))
        brake = max(0.0, min(1.0, brake))

        self._pad.left_joystick_float(x_value_float=steer, y_value_float=0.0)
        self._pad.right_trigger_float(value_float=throttle)
        self._pad.left_trigger_float(value_float=brake)
        self._pad.update()

    def release(self) -> None:
        """Release all inputs and destroy the gamepad."""
        if self._pad is not None:
            try:
                self.send(0.0, 0.0, 0.0)
                time.sleep(0.05)
                del self._pad
            except Exception:
                pass
            self._pad = None
        self._connected = False
        log.info("Virtual gamepad released")

    @property
    def connected(self) -> bool:
        return self._connected

    def __del__(self) -> None:
        self.release()
