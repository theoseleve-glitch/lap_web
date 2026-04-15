"""Detector B6: Braking distance ratio — early vs late braking as handling indicator.

Late braking (high brake_frac) signals front-loaded entry = UNDERSTEER risk.
Early braking (low brake_frac) signals driver compensating for OVERSTEER.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext


class BrakingDistanceDetector(HandlingDetector):
    """Braking distance as fraction of corner length.

    Late braking (brake_frac >> 0.25) = UNDERSTEER.
    Early braking (brake_frac << 0.25) = OVERSTEER.
    """

    name = "braking_distance"
    default_weight = 0.5

    _EXPECTED_FRAC = 0.25
    _SCALE = 0.15
    _DEAD_LO = 0.15
    _DEAD_HI = 0.35
    _BRAKE_G_THRESH = -0.15   # minimum decel to count as braking
    _BRAKE_RELEASE = -0.05    # G threshold for brake release
    _MIN_BRAKE_SAMPLES = 5

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        expected_frac = self.get_cal(ctx, 'neutral', self._EXPECTED_FRAC)  # 0.25
        scale = self.get_cal(ctx, 'scale', self._SCALE)                    # 0.15
        dead_lo = self.get_cal(ctx, 'dead_zone_lo', self._DEAD_LO)         # 0.15
        dead_hi = self.get_cal(ctx, 'dead_zone_hi', self._DEAD_HI)         # 0.35

        if corner.n_samples < 10 or corner.corner_len_m < 2.0:
            return DetectorVote(self.name, 0.0, 0.0, "entry")

        a_lon = corner.a_lon_g

        # Check for a real braking zone at corner entry
        braking_mask = a_lon < self._BRAKE_G_THRESH
        # Count contiguous braking samples from the start
        brake_count = 0
        for v in braking_mask:
            if v:
                brake_count += 1
            else:
                break

        if brake_count < self._MIN_BRAKE_SAMPLES:
            return DetectorVote(self.name, 0.0, 0.0, "entry")

        # Find brake release: first index where a_lon > _BRAKE_RELEASE
        release_idx = corner.n_samples  # default: braking through entire corner
        for i in range(brake_count, corner.n_samples):
            if a_lon[i] > self._BRAKE_RELEASE:
                release_idx = i
                break

        dist = corner.dist_m
        brake_dist = dist[min(release_idx, corner.n_samples - 1)] - dist[0]
        brake_frac = brake_dist / (corner.corner_len_m + 1e-6)

        # Dead zone
        if dead_lo <= brake_frac <= dead_hi:
            return DetectorVote(self.name, 0.0, 0.0, "entry", raw_value=brake_frac)

        # Late = positive = understeer
        direction = float(np.clip((brake_frac - expected_frac) / scale, -1.0, 1.0))

        # Confidence: based on clarity of braking zone (peak decel * duration)
        peak_decel = float(np.abs(np.min(a_lon[:release_idx])))
        brake_dur = corner.time_s[min(release_idx, corner.n_samples - 1)] - corner.time_s[0]
        clarity = peak_decel * brake_dur  # G-seconds
        confidence = float(np.clip(clarity / 1.5, 0.0, 1.0))

        return DetectorVote(
            self.name, direction, confidence, "entry", raw_value=brake_frac,
        )
