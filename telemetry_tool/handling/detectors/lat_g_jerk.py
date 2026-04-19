"""Detector B1: Lateral G jerk — turn-in sharpness (G buildup rate)."""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_TURNIN_G_THRESHOLD = 0.1  # |a_lat| must exceed this to count as turn-in


class LatGJerkDetector(HandlingDetector):
    """Turn-in sharpness measured as lateral G buildup rate.

    High jerk = sharp turn-in = OVERSTEER tendency.
    Low jerk  = gradual turn-in = UNDERSTEER tendency.
    """

    name = "lat_g_jerk"
    default_weight = 0.7

    # Calibration constants (from 400-corner dataset)
    _MEDIAN_JERK = 0.35   # normalized jerk (G/s per G)
    _STD_JERK = 0.20
    _DEAD_ZONE = 0.10     # half-width around median

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        if corner.n_samples < 5 or corner.peak_g < 0.15:
            return DetectorVote(self.name, 0.0, 0.0, "entry")

        # Calibration look-ups (hardcoded values kept as defaults)
        neutral = self.get_cal(ctx, 'neutral', self._MEDIAN_JERK)  # 0.35
        std = self.get_cal(ctx, 'std', self._STD_JERK)              # 0.20
        dead = self.get_cal(ctx, 'dead_zone', self._DEAD_ZONE)      # 0.10

        a_lat_abs = np.abs(corner.a_lat_g)
        time = corner.time_s

        # Find turn-in point: first index where |a_lat| exceeds threshold
        above = np.where(a_lat_abs > _TURNIN_G_THRESHOLD)[0]
        if len(above) == 0:
            return DetectorVote(self.name, 0.0, 0.0, "entry")

        turnin_i = above[0]
        if turnin_i < 1:
            turnin_i = 1  # need at least one sample before turn-in

        # G buildup: from corner start to turn-in point
        g_buildup = a_lat_abs[turnin_i] - a_lat_abs[0]
        dt_turnin = time[turnin_i] - time[0]

        if dt_turnin < 0.01:  # too fast to measure
            return DetectorVote(self.name, 0.0, 0.0, "entry")

        # Raw jerk in G/s
        raw_jerk = g_buildup / dt_turnin

        # Normalize by peak G -> G/s per G
        norm_jerk = raw_jerk / corner.peak_g

        # Dead zone
        if abs(norm_jerk - neutral) < dead:
            return DetectorVote(self.name, 0.0, 0.0, "entry", raw_value=norm_jerk)

        # Direction: high jerk = sharp = oversteer tendency (negative direction)
        direction = float(np.clip(
            -(norm_jerk - neutral) / 0.30, -1.0, 1.0,
        ))

        centered = abs(norm_jerk - neutral)
        confidence = float(min(centered / (1.5 * std), 1.0))

        return DetectorVote(
            self.name, direction, confidence, "entry", raw_value=norm_jerk,
        )
