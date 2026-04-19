"""Detector B2: Speed scrub profile.

Identifies WHERE in the corner speed is lost. Entry-heavy speed loss
indicates understeer (front scrubbing); exit-heavy indicates oversteer
(rear breaking loose, driver lifting).
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_N_SEGMENTS = 5
_MIN_SPEED_LOSS_MPS = 2.0  # ignore flat-out bends
_BALANCED_LO = 2.0
_BALANCED_HI = 3.0
_DIRECTION_SCALE = 1.5
_ZONE_MAP = {0: "entry", 1: "entry", 2: "mid", 3: "exit", 4: "exit"}


class SpeedScrubDetector(HandlingDetector):
    """Speed loss distribution across 5 equal corner segments."""

    name = "speed_scrub"
    default_weight = 0.6

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        balanced_lo = self.get_cal(ctx, 'dead_zone_lo', _BALANCED_LO)  # 2.0
        balanced_hi = self.get_cal(ctx, 'dead_zone_hi', _BALANCED_HI)  # 3.0
        scale = self.get_cal(ctx, 'scale', _DIRECTION_SCALE)           # 1.5

        n = corner.n_samples
        if n < _N_SEGMENTS * 2:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        speed = corner.speed_mps
        total_loss = float(speed[0] - speed[-1])

        if total_loss < _MIN_SPEED_LOSS_MPS:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        # Split into 5 equal segments by sample count
        seg_indices = np.array_split(np.arange(n), _N_SEGMENTS)
        losses = np.zeros(_N_SEGMENTS)
        for i, idx in enumerate(seg_indices):
            if len(idx) < 2:
                continue
            losses[i] = max(speed[idx[0]] - speed[idx[-1]], 0.0)

        loss_sum = float(np.sum(losses))
        if loss_sum < 1e-6:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        # Weighted position of speed loss (1-indexed: 1..5)
        weights = losses / loss_sum
        segment_ids = np.arange(1, _N_SEGMENTS + 1, dtype=float)
        position = float(np.dot(segment_ids, weights))

        # Dead zone
        if balanced_lo <= position <= balanced_hi:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=position)

        # Entry-heavy (position < 2.5) = understeer (positive direction)
        # Exit-heavy (position > 2.5) = oversteer (negative direction)
        direction = float(np.clip(-(position - 2.5) / scale, -1.0, 1.0))

        # Confidence: stronger signal when total loss is significant
        loss_kmh = total_loss * 3.6
        conf_base = min(loss_kmh / 20.0, 1.0)  # saturates at 20 km/h loss
        g_boost = min(corner.peak_g / ctx.friction_estimate_g, 1.5)
        confidence = float(np.clip(conf_base * g_boost * 0.7, 0.0, 1.0))

        # Zone from dominant segment
        dominant_seg = int(np.argmax(losses))
        zone = _ZONE_MAP.get(dominant_seg, "mid")

        return DetectorVote(
            self.name, direction, confidence, zone, raw_value=position,
        )
