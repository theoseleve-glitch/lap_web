"""Detector #9: Heading acceleration d^2(heading)/ds^2."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

log = logging.getLogger(__name__)


class HeadingAccelDetector(HandlingDetector):
    """Detects rotation stall (understeer) or exit instability (oversteer)
    from the second derivative of heading w.r.t. distance."""

    name = "heading_accel"
    default_weight = 0.9

    # Calibrated from 109 corners
    MID_NORM_MEDIAN = 1.27      # median normalised mid activity
    EXIT_NORM_MEDIAN = 1.05     # median normalised exit activity
    MID_SCALE = 0.40            # tanh scaling for mid understeer
    EXIT_SCALE = 0.40           # tanh scaling for exit oversteer

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        if corner.n_samples < 10:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        # Calibration look-ups (hardcoded values kept as defaults)
        mid_neutral = self.get_cal(ctx, 'mid_neutral', self.MID_NORM_MEDIAN)    # 1.27
        exit_neutral = self.get_cal(ctx, 'exit_neutral', self.EXIT_NORM_MEDIAN)  # 1.05
        scale = self.get_cal(ctx, 'scale', self.MID_SCALE)                       # 0.40
        mid_dead = self.get_cal(ctx, 'mid_dead', 0.25)
        exit_dead = self.get_cal(ctx, 'exit_dead', 0.20)

        bearing = np.unwrap(np.deg2rad(corner.bearing_deg))
        dist = corner.dist_m

        ds = np.diff(dist)
        ds[ds < 1e-4] = 1e-4   # avoid division by zero

        dh_ds = np.diff(bearing) / ds
        d2h_ds2 = np.diff(dh_ds) / ds[:-1]

        if len(d2h_ds2) < 6:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        # Smooth with rolling mean
        win = max(int(0.05 * len(d2h_ds2)), 5)
        smoothed = pd.Series(d2h_ds2).rolling(win, center=True, min_periods=1).mean().values

        n = len(smoothed)
        overall_activity = float(np.mean(np.abs(smoothed)))
        if overall_activity < 1e-9:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        # Mid = central third, exit = last half
        third = n // 3
        mid_region = smoothed[third: 2 * third]
        exit_region = smoothed[n // 2:]

        mid_activity = float(np.mean(np.abs(mid_region))) if len(mid_region) > 0 else 0.0
        exit_activity = float(np.mean(np.abs(exit_region))) if len(exit_region) > 0 else 0.0

        mid_norm = mid_activity / overall_activity
        exit_norm = exit_activity / overall_activity

        g_boost = min(corner.peak_g / 0.6, 1.2)

        # Check mid first: low rotation = understeer
        mid_dev = mid_neutral - mid_norm
        if mid_dev > mid_dead:
            direction = float(np.tanh(mid_dev / scale))
            confidence = float(np.clip(mid_dev / 0.5 * g_boost * 0.7, 0.0, 1.0))
            return DetectorVote(self.name, direction, confidence, "mid",
                                raw_value=float(mid_norm))

        # Then exit: high activity = instability = oversteer
        exit_dev = exit_norm - exit_neutral
        if exit_dev > exit_dead:
            direction = float(-np.tanh(exit_dev / scale))
            confidence = float(np.clip(exit_dev / 0.5 * g_boost * 0.7, 0.0, 1.0))
            return DetectorVote(self.name, direction, confidence, "exit",
                                raw_value=float(exit_norm))

        return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)
