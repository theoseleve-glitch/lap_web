"""Detector #8: Yaw rate TREND within the corner (self-normalizing)."""
from __future__ import annotations

import logging

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

log = logging.getLogger(__name__)


class YawResidualDetector(HandlingDetector):
    """Compares yaw ratio in entry half vs exit half of the same corner.

    Self-normalizing: avoids the systematic GPS yaw offset (~1.6x) by
    looking at the relative change within a single corner, not absolutes.
    """

    name = "yaw_residual"
    default_weight = 1.0

    DEAD_ZONE = 0.10            # |relative_change| below this -> abstain
    DIRECTION_SCALE = 0.30      # relative_change per unit direction
    MIN_SPEED_MPS = 3.0         # ignore very low speed samples
    MIN_EXPECTED = 1e-4         # minimum expected yaw to avoid div-by-zero

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        dead = self.get_cal(ctx, 'dead_zone', self.DEAD_ZONE)      # 0.10
        scale = self.get_cal(ctx, 'scale', self.DIRECTION_SCALE)    # 0.30

        speed = corner.speed_mps
        curv = corner.curvature
        yaw_dps = corner.yaw_rate_dps

        # Expected yaw rate (rad/s) = curvature * speed
        expected = curv * speed
        # Actual yaw rate in rad/s
        actual = np.abs(yaw_dps) * (np.pi / 180.0)

        # Filter: meaningful speed and non-trivial expected yaw
        valid = (speed > self.MIN_SPEED_MPS) & (expected > self.MIN_EXPECTED)
        if np.sum(valid) < 6:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        ratio = actual[valid] / expected[valid]
        n = len(ratio)
        mid = n // 2

        entry_half = ratio[:mid]
        exit_half = ratio[mid:]

        if len(entry_half) < 2 or len(exit_half) < 2:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        entry_med = float(np.median(entry_half))
        exit_med = float(np.median(exit_half))
        mean_ratio = (entry_med + exit_med) / 2.0

        if mean_ratio < 1e-6:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        relative_change = (exit_med - entry_med) / mean_ratio

        if abs(relative_change) < dead:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=relative_change)

        # Positive change (yaw increases through corner) = OVERSTEER -> negative direction
        direction = float(np.clip(-relative_change / scale, -1.0, 1.0))

        # Confidence: consistency within each half + peak G boost
        entry_cv = float(np.std(entry_half) / (np.mean(entry_half) + 1e-9))
        exit_cv = float(np.std(exit_half) / (np.mean(exit_half) + 1e-9))
        consistency = max(1.0 - (entry_cv + exit_cv) / 2.0, 0.1)
        g_boost = min(corner.peak_g / 0.8, 1.0)
        confidence = float(np.clip(consistency * g_boost, 0.0, 1.0))

        # Zone assignment
        if relative_change < -0.05:
            zone = "entry"
        elif relative_change > 0.05:
            zone = "exit"
        else:
            zone = "mid"

        return DetectorVote(self.name, direction, confidence, zone,
                            raw_value=float(relative_change))
