"""Detector B2: Trail braking overlap corrected for corner severity."""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_BRAKING_G_THRESHOLD = -0.15  # a_lon must be below this to count as braking
_TURNING_G_THRESHOLD = 0.1    # |a_lat| must exceed this to count as turning
_MIN_BRAKE_SAMPLES = 5


class TrailBrakingDetector(HandlingDetector):
    """Brake-turn overlap corrected for corner severity.

    Uses per-session regression from ctx to compute expected overlap.
    Positive residual (more overlap than expected) = good front grip = OVERSTEER.
    """

    name = "trail_braking"
    default_weight = 0.4

    # Calibration constants
    _DEAD_ZONE = 0.15   # |residual| must exceed this to fire
    _SCALE = 0.25       # direction = -residual / scale

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        dead = self.get_cal(ctx, 'dead_zone', self._DEAD_ZONE)  # 0.15
        scale = self.get_cal(ctx, 'scale', self._SCALE)          # 0.25

        entry_start, entry_end = corner.phase_entry
        n_entry = entry_end - entry_start

        if n_entry < 3:
            return DetectorVote(self.name, 0.0, 0.0, "entry")

        a_lon_entry = corner.a_lon_g[entry_start:entry_end]
        a_lat_entry = corner.a_lat_g[entry_start:entry_end]

        # Check driver actually brakes in entry
        braking_mask = a_lon_entry < _BRAKING_G_THRESHOLD
        if np.sum(braking_mask) < _MIN_BRAKE_SAMPLES:
            return DetectorVote(self.name, 0.0, 0.0, "entry")

        # Overlap: samples with simultaneous braking AND turning
        turning_mask = np.abs(a_lat_entry) > _TURNING_G_THRESHOLD
        overlap_mask = braking_mask & turning_mask
        overlap_frac = float(np.sum(overlap_mask)) / n_entry

        # Expected overlap from per-session regression
        expected = (
            ctx.trail_braking_slope * corner.peak_g
            + ctx.trail_braking_intercept
        )

        residual = overlap_frac - expected

        # Dead zone
        if abs(residual) < dead:
            return DetectorVote(self.name, 0.0, 0.0, "entry", raw_value=residual)

        # Positive residual = more overlap than expected = good front grip = oversteer
        direction = float(np.clip(-residual / scale, -1.0, 1.0))

        confidence = float(min(abs(residual) / (2.0 * dead), 1.0))

        return DetectorVote(
            self.name, direction, confidence, "entry", raw_value=residual,
        )
