"""Detector B7: Line width variation — GPS path spread across laps.

Confidence modifier: high spread = inconsistent data = reduce other votes.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext

_DEG_LAT_M = 110540.0
_DEG_LON_M = 111320.0
_MATCH_R_M = 15.0
_MIN_LAPS = 3
_SPREAD_CAP = 3.0  # metres — 3m spread = 80% confidence reduction
_MAX_RED = 0.80


def _gps_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Euclidean GPS distance approximation in metres."""
    cos_lat = np.cos(np.radians((lat1 + lat2) / 2.0))
    dx = (lon2 - lon1) * _DEG_LON_M * cos_lat
    dy = (lat2 - lat1) * _DEG_LAT_M
    return float(np.sqrt(dx * dx + dy * dy))


class LineVariationDetector(HandlingDetector):
    """GPS path spread across laps — confidence modifier."""

    name = "line_variation"
    default_weight = 1.0

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        # Calibration look-ups (hardcoded values kept as defaults)
        spread_cap = self.get_cal(ctx, 'spread_cap', _SPREAD_CAP)    # 3.0 metres
        max_red = self.get_cal(ctx, 'max_reduction', _MAX_RED)        # 0.80

        _no_mod = DetectorVote(
            self.name, 0.0, 1.0, "mid", raw_value=0.0, is_confidence_modifier=True,
        )
        if not ctx.all_lap_corners or corner.n_samples < 3:
            return _no_mod

        matched: list[CornerWindow] = []
        for corners in ctx.all_lap_corners.values():
            for c in corners:
                if c.corner_id != corner.corner_id and \
                        _gps_dist(corner.apex_lat, corner.apex_lon, c.apex_lat, c.apex_lon) < _MATCH_R_M:
                    matched.append(c)
        if len(matched) < _MIN_LAPS:
            return _no_mod

        n_pts = min(corner.n_samples, *(c.n_samples for c in matched))
        if n_pts < 3:
            return _no_mod

        idx_ref = np.linspace(0, corner.n_samples - 1, n_pts).astype(int)
        lats = [corner.lat_deg[idx_ref]]
        lons = [corner.lon_deg[idx_ref]]
        for c in matched:
            idx_c = np.linspace(0, c.n_samples - 1, n_pts).astype(int)
            lats.append(c.lat_deg[idx_c])
            lons.append(c.lon_deg[idx_c])

        lat_arr = np.array(lats)
        lon_arr = np.array(lons)
        m_lat = lat_arr.mean(axis=0)
        m_lon = lon_arr.mean(axis=0)

        dx = (lon_arr - m_lon) * _DEG_LON_M * np.cos(np.radians(m_lat))
        dy = (lat_arr - m_lat) * _DEG_LAT_M
        spread = float(np.mean(np.sqrt(dx * dx + dy * dy)))
        conf = 1.0 - min(spread / spread_cap, max_red)

        return DetectorVote(
            self.name, 0.0, conf, "mid", raw_value=spread, is_confidence_modifier=True,
        )
