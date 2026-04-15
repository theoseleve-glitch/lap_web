"""Detector B3: Corner exit throttle response.

Measures time from apex (peak |lateral G|) to first sustained positive
longitudinal acceleration. Long delay = managing oversteer; short delay =
confident exit (neutral or understeer-limited elsewhere).
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_ACCEL_THRESHOLD = 0.05  # G threshold for "throttle on"
_SUSTAINED_SAMPLES = 3   # consecutive samples above threshold
_NEUTRAL_LO = 0.15
_NEUTRAL_HI = 0.35
_DIRECTION_SCALE = 0.20


class ThrottleResponseDetector(HandlingDetector):
    """Time from apex to first sustained positive longitudinal G."""

    name = "throttle_response"
    default_weight = 0.7

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        neutral_lo = self.get_cal(ctx, 'dead_zone_lo', _NEUTRAL_LO)  # 0.15
        neutral_hi = self.get_cal(ctx, 'dead_zone_hi', _NEUTRAL_HI)  # 0.35
        scale = self.get_cal(ctx, 'scale', _DIRECTION_SCALE)          # 0.20

        n = corner.n_samples
        if n < 8 or corner.corner_dur_s < 0.2:
            return DetectorVote(self.name, 0.0, 0.0, "exit")

        # Convert global apex index to local
        apex_local = corner.apex_g_i - corner.start_i
        apex_local = max(0, min(apex_local, n - 1))

        if apex_local >= n - _SUSTAINED_SAMPLES:
            return DetectorVote(self.name, 0.0, 0.0, "exit")

        # Search for sustained positive a_lon from apex onward
        a_lon = corner.a_lon_g[apex_local:]
        above = a_lon > _ACCEL_THRESHOLD
        throttle_idx = None

        for i in range(len(above) - _SUSTAINED_SAMPLES + 1):
            if np.all(above[i : i + _SUSTAINED_SAMPLES]):
                throttle_idx = i
                break

        if throttle_idx is None:
            # Never accelerates in exit: strong oversteer signal
            return DetectorVote(
                self.name, -0.8, 0.7, "exit",
                raw_value=float(corner.corner_dur_s),
            )

        time_from_apex = corner.time_s[apex_local + throttle_idx] - corner.time_s[apex_local]
        delay_frac = time_from_apex / corner.corner_dur_s

        # Dead zone
        if neutral_lo <= delay_frac <= neutral_hi:
            return DetectorVote(self.name, 0.0, 0.0, "exit", raw_value=delay_frac)

        # Long delay = managing oversteer (negative); short = understeer or neutral
        direction = float(np.clip(-(delay_frac - 0.25) / scale, -1.0, 1.0))

        # Confidence: higher when peak G is significant
        conf = float(np.clip(corner.peak_g / ctx.friction_estimate_g * 0.6, 0.0, 1.0))

        return DetectorVote(
            self.name, direction, conf, "exit", raw_value=delay_frac,
        )
