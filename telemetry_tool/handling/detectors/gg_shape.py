"""Detector #6: GG diagram asymmetry between entry and exit quadrants."""
from __future__ import annotations

import logging

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

log = logging.getLogger(__name__)


class GGShapeDetector(HandlingDetector):
    """Compares convex hull area in braking-turn vs accel-turn GG quadrants."""

    name = "gg_shape"
    default_weight = 0.8

    # Calibrated from 109-corner dataset
    MEDIAN_RATIO = 1.074
    STD_RATIO = 0.175
    DEAD_ZONE = 0.15            # wider dead zone for hull area ratios
    DIRECTION_SCALE = 0.50      # hull ratios vary more than mean G ratios
    MIN_HULL_POINTS = 4         # ConvexHull needs >= 3; we require 4 for stability
    CONFIDENCE_DENOM = 20.0     # min(points) / this = confidence

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        dead = self.get_cal(ctx, 'dead_zone', self.DEAD_ZONE)      # 0.15
        scale = self.get_cal(ctx, 'scale', self.DIRECTION_SCALE)    # 0.50

        a_lon = corner.a_lon_g
        a_lat_abs = np.abs(corner.a_lat_g)

        # Entry quadrant: braking (a_lon < -0.05) with meaningful lateral G
        entry_mask = (a_lon < -0.05) & (a_lat_abs > 0.15)
        # Exit quadrant: accelerating (a_lon > 0.05) with meaningful lateral G
        exit_mask = (a_lon > 0.05) & (a_lat_abs > 0.15)

        n_entry = int(np.sum(entry_mask))
        n_exit = int(np.sum(exit_mask))

        if n_entry < self.MIN_HULL_POINTS or n_exit < self.MIN_HULL_POINTS:
            # Fallback: mean combined G comparison
            return self._fallback(corner, a_lon, a_lat_abs, entry_mask, exit_mask,
                                  dead, scale)

        entry_area = self._hull_area(a_lon[entry_mask], a_lat_abs[entry_mask])
        exit_area = self._hull_area(a_lon[exit_mask], a_lat_abs[exit_mask])

        # Guard: if either hull is degenerate or ratio is extreme, fall back
        if entry_area < 1e-4 or exit_area < 1e-4 or max(entry_area, exit_area) / (min(entry_area, exit_area) + 1e-12) > 100:
            return self._fallback(corner, a_lon, a_lat_abs, entry_mask, exit_mask,
                                  dead, scale)

        # Use log-ratio instead of raw ratio — symmetric and bounded
        log_ratio = np.log(exit_area / entry_area)
        # Typical log_ratio range: -1.5 to +1.5 (i.e., one side 0.2x to 5x the other)

        if abs(log_ratio) < dead:  # dead zone in log-space
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=float(log_ratio))

        direction = np.clip(log_ratio / 1.0, -1.0, 1.0)  # ±1.0 in log-space = full signal
        confidence = min(min(n_entry, n_exit) / self.CONFIDENCE_DENOM, 1.0) * 0.8

        return DetectorVote(self.name, float(direction), float(confidence),
                            "mid", raw_value=float(log_ratio))

    def _fallback(self, corner, a_lon, a_lat_abs, entry_mask, exit_mask,
                  dead=None, scale=None):
        """Mean combined G when not enough points for hull."""
        if dead is None:
            dead = self.DEAD_ZONE
        if scale is None:
            scale = self.DIRECTION_SCALE
        entry_g = np.mean(np.sqrt(a_lon[entry_mask] ** 2 + a_lat_abs[entry_mask] ** 2)) \
            if np.any(entry_mask) else 0.0
        exit_g = np.mean(np.sqrt(a_lon[exit_mask] ** 2 + a_lat_abs[exit_mask] ** 2)) \
            if np.any(exit_mask) else 0.0
        if entry_g < 1e-6 and exit_g < 1e-6:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)
        ratio = exit_g / (entry_g + 1e-9)
        deviation = abs(ratio - self.MEDIAN_RATIO)
        if deviation < dead:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=ratio)
        direction = np.clip((ratio - self.MEDIAN_RATIO) / scale, -1.0, 1.0)
        return DetectorVote(self.name, float(direction), 0.15, "mid", raw_value=float(ratio))

    @staticmethod
    def _hull_area(x: np.ndarray, y: np.ndarray) -> float:
        """Convex hull area of 2D point set. Returns 0 on degenerate input."""
        from scipy.spatial import ConvexHull

        pts = np.column_stack([x, y])
        try:
            return float(ConvexHull(pts).volume)  # 2D: volume == area
        except Exception:
            return 0.0
