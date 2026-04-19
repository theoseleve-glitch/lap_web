"""Detector A6: Speed recovery — linear regression on exit speed curve.

FIX A6: Uses np.polyfit on the entire exit phase instead of a single
point at 30% of exit.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_MIN_EXIT_SAMPLES = 4


class SpeedRecoveryDetector(HandlingDetector):
    """How fast speed recovers after apex via linear regression.

    Low recovery = OVERSTEER (rear-limited).
    High recovery = UNDERSTEER (front-limited, car straightens easily).
    """

    name = "speed_recovery"
    default_weight = 0.8

    # Calibration constants (from 400-corner dataset)
    _MEDIAN_SLOPE = 0.091  # normalized recovery slope
    _STD_SLOPE = 0.138
    _NEUTRAL_LO = 0.05
    _NEUTRAL_HI = 0.15

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        neutral = self.get_cal(ctx, 'neutral', self._MEDIAN_SLOPE)  # 0.091
        std = self.get_cal(ctx, 'std', self._STD_SLOPE)              # 0.138
        dead = self.get_cal(ctx, 'dead_zone', 0.04)                  # half-width

        exit_start, exit_end = corner.phase_exit
        n_exit = exit_end - exit_start

        if n_exit < _MIN_EXIT_SAMPLES:
            return DetectorVote(self.name, 0.0, 0.0, "exit")

        # Extract exit phase arrays (local indices)
        t_exit = corner.time_s[exit_start:exit_end]
        s_exit = corner.speed_mps[exit_start:exit_end]

        # Relative time from exit start
        t_rel = t_exit - t_exit[0]
        if t_rel[-1] < 0.05:  # exit too short in time
            return DetectorVote(self.name, 0.0, 0.0, "exit")

        # Linear regression: speed = slope * time + intercept
        slope, _ = np.polyfit(t_rel, s_exit, 1)

        # Normalize by peak lateral force (m/s^2)
        peak_force = corner.peak_g * 9.81
        if peak_force < 0.5:
            return DetectorVote(self.name, 0.0, 0.0, "exit")

        norm_slope = slope / peak_force

        # Neutral zone (symmetric around neutral using dead_zone half-width)
        if (neutral - dead) <= norm_slope <= (neutral + dead):
            return DetectorVote(self.name, 0.0, 0.0, "exit", raw_value=norm_slope)

        # Direction: high recovery = understeer, low = oversteer
        centered = norm_slope - neutral
        direction = float(np.clip(centered / std, -1.0, 1.0))

        confidence = float(min(abs(centered) / (1.5 * std), 1.0))

        return DetectorVote(
            self.name, direction, confidence, "exit", raw_value=norm_slope,
        )
