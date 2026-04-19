"""Detector #7: Cross-lap speed-curvature regression per corner."""
from __future__ import annotations

import logging
import math

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

log = logging.getLogger(__name__)

_EARTH_R = 6_371_000.0  # metres


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(math.sqrt(a), 1.0))


class PathDivergenceDetector(HandlingDetector):
    """Speed-curvature regression across laps for the same physical corner."""

    name = "path_divergence"
    default_weight = 0.5

    MATCH_RADIUS_M = 15.0       # GPS proximity for corner matching
    MIN_MATCHED = 4             # minimum laps to fit regression
    DIRECTION_SCALE = 500.0     # slope scaling factor
    MIN_LAPS_FULL_CONF = 6      # laps for confidence = 1.0

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        scale = self.get_cal(ctx, 'scale', self.DIRECTION_SCALE)  # 500.0

        if not ctx.all_lap_corners or corner.apex_lat == 0.0:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        # Collect (mean_speed, mean_curvature) for matching corners across laps
        pairs: list[tuple[float, float]] = []
        pairs.append(self._corner_pair(corner))

        for lap_num, lap_corners in ctx.all_lap_corners.items():
            for other in lap_corners:
                if other.corner_id == corner.corner_id:
                    continue
                if other.apex_lat == 0.0:
                    continue
                dist = _haversine_m(corner.apex_lat, corner.apex_lon,
                                    other.apex_lat, other.apex_lon)
                if dist < self.MATCH_RADIUS_M:
                    pairs.append(self._corner_pair(other))

        if len(pairs) < self.MIN_MATCHED:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        speeds = np.array([p[0] for p in pairs])
        curvatures = np.array([p[1] for p in pairs])

        # Guard against constant arrays
        if np.std(speeds) < 1e-6:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=0.0)

        # Linear regression: curvature = slope * speed + intercept
        coeffs = np.polyfit(speeds, curvatures, 1)
        slope = coeffs[0]

        # R-squared
        predicted = np.polyval(coeffs, speeds)
        ss_res = np.sum((curvatures - predicted) ** 2)
        ss_tot = np.sum((curvatures - np.mean(curvatures)) ** 2)
        r_sq = 1.0 - ss_res / (ss_tot + 1e-12)
        r_sq = max(r_sq, 0.0)

        # Negative slope: faster -> wider path -> UNDERSTEER (positive direction)
        direction = float(np.clip(-slope * scale, -1.0, 1.0))
        confidence = float(r_sq * min(len(pairs) / self.MIN_LAPS_FULL_CONF, 1.0))

        return DetectorVote(self.name, direction, confidence, "mid",
                            raw_value=float(slope))

    @staticmethod
    def _corner_pair(c: CornerWindow) -> tuple[float, float]:
        """Extract (mean_speed, mean_curvature) for a corner window."""
        valid = c.curvature > 1e-6
        mean_speed = float(np.mean(c.speed_mps))
        mean_curv = float(np.mean(c.curvature[valid])) if np.any(valid) else 0.0
        return mean_speed, mean_curv
