"""Detector A4: Apex timing offset (min-speed vs lateral-G peak).

Uses lateral G peak as apex (not curvature double-derivative).
apex_g_i is already the lateral G peak from calibration.py build_corner_window.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext


class ApexTimingDetector(HandlingDetector):
    """Compare min-speed position vs lateral-G-peak position.

    Positive offset = late speed apex = UNDERSTEER.
    Negative offset = early speed apex = OVERSTEER.
    """

    name = "apex_timing"
    default_weight = 1.0

    # Calibration constants (from 400-corner dataset)
    _MEDIAN_OFFSET = -0.036  # slight natural early-apex tendency
    _STD_OFFSET = 0.262
    _DEAD_LO = -0.05
    _DEAD_HI = 0.05
    _G_CORRELATION = 0.42  # signal strengthens with peak G

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        if corner.corner_len_m < 1.0 or corner.n_samples < 5:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        # Calibration look-ups (hardcoded values kept as defaults)
        neutral = self.get_cal(ctx, 'neutral', self._MEDIAN_OFFSET)   # -0.036
        std = self.get_cal(ctx, 'std', self._STD_OFFSET)              # 0.262
        dead = self.get_cal(ctx, 'dead_zone', 0.05)                   # symmetric
        g_corr = self.get_cal(ctx, 'g_correlation', self._G_CORRELATION)  # 0.42

        dist = corner.dist_m
        # apex_g_i and apex_speed_i are local indices into the corner arrays
        g_apex_dist = dist[corner.apex_g_i - corner.start_i]
        speed_apex_dist = dist[corner.apex_speed_i - corner.start_i]

        offset = (speed_apex_dist - g_apex_dist) / corner.corner_len_m

        # Dead zone
        if -dead <= offset <= dead:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=offset)

        # Direction: positive offset = late speed apex = understeer
        centered = offset - neutral
        direction = np.clip(centered / std, -1.0, 1.0)

        # Confidence: base from deviation, boosted by peak G
        base_conf = min(abs(centered) / (1.5 * std), 1.0)
        g_boost = 1.0 + g_corr * (corner.peak_g - 0.5)
        confidence = float(np.clip(base_conf * g_boost, 0.0, 1.0))

        # Zone assignment
        if offset > dead:
            zone = "entry"  # late apex -> entry problem
        elif offset < -dead:
            zone = "exit"  # early apex -> exit problem
        else:
            zone = "mid"

        return DetectorVote(
            self.name, float(direction), confidence, zone, raw_value=offset,
        )
