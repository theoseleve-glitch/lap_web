"""Detector B4: Steering correction count from GPS steering angle.

Counts sign changes in the GPS-derived steering angle derivative during
the mid-corner phase. High correction rate = fighting oversteer.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_MIN_SPEED_MPS = 3.0     # clamp speed to avoid div-by-zero
_DEAD_CORRECTIONS = 2.0  # corrections/s below this is normal
_DIRECTION_SCALE = 4.0   # corrections/s per unit direction


class SteeringCorrectionsDetector(HandlingDetector):
    """Mid-corner steering corrections from GPS yaw rate."""

    name = "steering_corrections"
    default_weight = 0.5

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        dead_corrections = self.get_cal(ctx, 'dead_zone', _DEAD_CORRECTIONS)  # 2.0
        scale = self.get_cal(ctx, 'scale', _DIRECTION_SCALE)                  # 4.0

        n = corner.n_samples
        if n < 10:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        # Determine mid-corner region
        mid_start, mid_end = corner.phase_mid
        if mid_end - mid_start < 4:
            # Fall back to middle 50%
            mid_start = n // 4
            mid_end = n - n // 4

        mid_slice = slice(mid_start, mid_end)
        mid_n = mid_end - mid_start
        if mid_n < 4:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        # GPS steering angle: steer = arctan(wheelbase * yaw_rate_rad / speed)
        speed = np.maximum(corner.speed_mps[mid_slice], _MIN_SPEED_MPS)
        yaw_rad_s = np.deg2rad(corner.yaw_rate_dps[mid_slice])
        steer_deg = np.degrees(np.arctan(ctx.wheelbase_m * yaw_rad_s / speed))

        # Derivative of steering angle
        dt = np.diff(corner.time_s[mid_slice])
        dt = np.maximum(dt, 1e-6)
        d_steer = np.diff(steer_deg) / dt

        # Count sign changes in the derivative
        signs = np.sign(d_steer)
        sign_changes = np.count_nonzero(np.diff(signs[signs != 0]))

        mid_duration = corner.time_s[mid_end - 1] - corner.time_s[mid_start]
        if mid_duration < 0.1:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        corrections_per_s = sign_changes / mid_duration

        # Dead zone
        if corrections_per_s < dead_corrections:
            return DetectorVote(
                self.name, 0.0, 0.0, "mid", raw_value=corrections_per_s,
            )

        # More corrections = oversteer (negative direction)
        direction = float(np.clip(
            -(corrections_per_s - dead_corrections) / scale, -1.0, 0.0,
        ))

        # Confidence: longer corners + higher G = more reliable
        dur_factor = min(corner.corner_dur_s / 2.0, 1.0)
        g_factor = min(corner.peak_g / ctx.friction_estimate_g, 1.5)
        confidence = float(np.clip(dur_factor * g_factor * 0.5, 0.0, 1.0))

        return DetectorVote(
            self.name, direction, confidence, "mid",
            raw_value=corrections_per_s,
        )
