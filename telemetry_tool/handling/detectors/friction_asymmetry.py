"""Detector B1: Friction circle utilization asymmetry.

Compares traction budget usage in entry vs exit zones.
Exit grip-limited = oversteer; entry grip-limited = understeer.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_DEAD_LO = 0.85
_DEAD_HI = 1.15
_DIRECTION_SCALE = 0.30  # ratio deviation per unit direction


class FrictionAsymmetryDetector(HandlingDetector):
    """Entry vs exit friction circle utilization asymmetry."""

    name = "friction_asymmetry"
    default_weight = 0.7

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        dead_lo = self.get_cal(ctx, 'dead_zone_lo', _DEAD_LO)      # 0.85
        dead_hi = self.get_cal(ctx, 'dead_zone_hi', _DEAD_HI)      # 1.15
        scale = self.get_cal(ctx, 'scale', _DIRECTION_SCALE)        # 0.30

        n = corner.n_samples
        if n < 10:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        # Split into entry (first 30%) and exit (last 30%)
        entry_end = max(int(n * 0.30), 1)
        exit_start = min(int(n * 0.70), n - 1)

        a_lat = corner.a_lat_g
        a_lon = corner.a_lon_g

        entry_combined = np.sqrt(a_lat[:entry_end] ** 2 + a_lon[:entry_end] ** 2)
        exit_combined = np.sqrt(a_lat[exit_start:] ** 2 + a_lon[exit_start:] ** 2)

        friction = max(ctx.friction_estimate_g, 0.1)
        entry_util = float(np.mean(entry_combined)) / friction
        exit_util = float(np.mean(exit_combined)) / friction

        ratio = exit_util / (entry_util + 1e-6)

        # Dead zone
        if dead_lo <= ratio <= dead_hi:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=ratio)

        # Exit << entry = oversteer (negative); entry << exit = understeer (positive)
        direction = float(np.clip((ratio - 1.0) / scale, -1.0, 1.0))

        # Confidence: higher utilization = closer to limit = more meaningful
        max_util = max(entry_util, exit_util)
        confidence = float(np.clip(max_util * 0.7, 0.0, 1.0))

        return DetectorVote(
            self.name, direction, confidence, "mid", raw_value=ratio,
        )
