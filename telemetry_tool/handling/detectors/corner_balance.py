"""Detector A5: Corner balance — entry vs exit time split at geometric apex."""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext


class CornerBalanceDetector(HandlingDetector):
    """Entry vs exit time split at geometric apex (lateral G peak).

    ratio = t_entry / t_exit.  >1 = entry-heavy = UNDERSTEER.
    """

    name = "corner_balance"
    default_weight = 0.9

    # Calibration constants (from 400-corner dataset)
    _MEDIAN_RATIO = 1.0
    _STD_RATIO = 0.85
    _DEAD_LO = 0.8
    _DEAD_HI = 1.2

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        if corner.n_samples < 5:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        # Calibration look-ups (hardcoded values kept as defaults)
        neutral = self.get_cal(ctx, 'neutral', self._MEDIAN_RATIO)      # 1.0
        std = self.get_cal(ctx, 'std', self._STD_RATIO)                 # 0.85
        dead_lo = self.get_cal(ctx, 'dead_zone_lo', self._DEAD_LO)      # 0.8
        dead_hi = self.get_cal(ctx, 'dead_zone_hi', self._DEAD_HI)      # 1.2

        time = corner.time_s
        apex_local = corner.apex_g_i - corner.start_i

        # Need at least 2 samples on each side of apex
        if apex_local < 2 or apex_local >= corner.n_samples - 2:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        t_entry = time[apex_local] - time[0]
        t_exit = time[-1] - time[apex_local]

        if t_exit < 0.01:  # avoid division by zero
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        ratio = t_entry / t_exit

        # Dead zone
        if dead_lo <= ratio <= dead_hi:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=ratio)

        # Direction: ratio > 1 = entry-heavy = understeer
        centered = ratio - neutral
        direction = float(np.clip(centered / std, -1.0, 1.0))

        confidence = float(min(abs(centered) / (1.5 * std), 1.0))

        zone = "entry" if direction > 0 else "exit"

        return DetectorVote(
            self.name, direction, confidence, zone, raw_value=ratio,
        )
