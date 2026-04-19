"""Detector B5: Lateral G plateau shape — G curve shape around peak.

Measures plateau width and entry/exit slope asymmetry to detect
whether the car is snapping (oversteer) or washing out (understeer).
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext


class LatGPlateauDetector(HandlingDetector):
    """Lateral G plateau flatness and slope asymmetry.

    Fast exit G decay (slope_ratio > 1.0) = OVERSTEER (snap off).
    Fast entry G decay (slope_ratio < 1.0) = UNDERSTEER at exit.
    """

    name = "lat_g_plateau"
    default_weight = 0.6

    _PLATEAU_THRESH = 0.90   # fraction of peak to count as plateau
    _MIN_PLATEAU_FRAC = 0.05  # must have a real peak to be meaningful
    _DEAD_LO = 0.8
    _DEAD_HI = 1.2
    _SCALE = 0.50  # normalise slope_ratio deviation

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        if corner.n_samples < 8 or corner.peak_g < 0.10:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        # Calibration look-ups (hardcoded values kept as defaults)
        dead_lo = self.get_cal(ctx, 'dead_zone_lo', self._DEAD_LO)  # 0.8
        dead_hi = self.get_cal(ctx, 'dead_zone_hi', self._DEAD_HI)  # 1.2
        scale = self.get_cal(ctx, 'scale', self._SCALE)              # 0.50

        g_mag = np.abs(corner.a_lat_g)
        peak_idx = int(np.argmax(g_mag))
        peak_val = g_mag[peak_idx]

        # --- plateau width ---
        thresh = self._PLATEAU_THRESH * peak_val
        above = g_mag >= thresh
        # contiguous run around peak
        lo = peak_idx
        while lo > 0 and above[lo - 1]:
            lo -= 1
        hi = peak_idx
        while hi < len(above) - 1 and above[hi + 1]:
            hi += 1
        plateau_width = hi - lo + 1
        plateau_frac = plateau_width / corner.n_samples

        if plateau_frac < self._MIN_PLATEAU_FRAC:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=plateau_frac)

        # --- slope asymmetry ---
        if peak_idx < 2 or peak_idx > corner.n_samples - 3:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=plateau_frac)

        x_entry = np.arange(peak_idx + 1, dtype=np.float64)
        entry_slope = abs(np.polyfit(x_entry, g_mag[:peak_idx + 1], 1)[0]) if len(x_entry) > 1 else 0.0

        n_exit = corner.n_samples - peak_idx
        x_exit = np.arange(n_exit, dtype=np.float64)
        exit_slope = abs(np.polyfit(x_exit, g_mag[peak_idx:], 1)[0]) if n_exit > 1 else 0.0

        slope_ratio = exit_slope / (entry_slope + 1e-6)

        # dead zone
        if dead_lo <= slope_ratio <= dead_hi:
            return DetectorVote(self.name, 0.0, 0.0, "mid", raw_value=slope_ratio)

        # slope_ratio > 1 = fast exit decay = oversteer (negative direction)
        direction = float(np.clip(-(slope_ratio - 1.0) / scale, -1.0, 1.0))

        g_boost = min(corner.peak_g / ctx.friction_estimate_g, 1.5)
        confidence = float(np.clip(0.6 * g_boost, 0.0, 1.0))

        return DetectorVote(
            self.name, direction, confidence, "mid", raw_value=slope_ratio,
        )
