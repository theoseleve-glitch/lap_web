"""
traffic_detection.py
--------------------
Detect traffic-induced speed lifts on straights.

Uses curvature-based straight detection and cross-lap speed envelope
comparison to flag segments where the driver lifted due to slower
traffic ahead. Produces per-lap traffic_score and per-segment flags.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Column name constants ──────────────────────────────────────────
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_BEARING = "Bearing (deg)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_YAW = "yaw_rate_dps"

# ── Detection thresholds ──────────────────────────────────────────
_CURVATURE_STRAIGHT_THRESHOLD = 0.005  # 1/m — below this is "straight"
_MIN_STRAIGHT_LENGTH_M = 30.0          # metres — minimum straight segment
_SPEED_DEFICIT_FACTOR = 0.95           # flag when v < envelope * this
_MIN_DEFICIT_LENGTH_M = 10.0           # metres — minimum continuous deficit
_DECEL_THRESHOLD_MPS2 = -0.5           # m/s² — unexplained braking
_CORNER_PROXIMITY_M = 20.0             # metres — don't flag near corners
_ENVELOPE_PERCENTILE = 90.0            # cross-lap speed envelope percentile


@dataclass
class TrafficEvent:
    """A single traffic-induced speed lift on a straight."""
    lap_number: int
    s_start: float              # metres
    s_end: float                # metres
    speed_deficit_pct: float    # how much below envelope (%)
    max_decel_mps2: float       # worst a_long in event (m/s²)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrafficResult:
    """Result of traffic detection across all laps."""
    straights: list[dict]           # detected straight segments
    events: list[TrafficEvent]      # all traffic events
    per_lap_score: dict[int, float] # lap_number → traffic_score [0-1]
    n_laps_affected: int

    def to_dict(self) -> dict:
        return {
            "straights": list(self.straights),
            "events": [e.to_dict() for e in self.events],
            "per_lap_score": dict(self.per_lap_score),
            "n_laps_affected": self.n_laps_affected,
        }


def _compute_curvature(df: "pd.DataFrame") -> np.ndarray:
    """Compute curvature from heading derivative w.r.t. distance.

    curvature = dheading/ds (rad/m).
    Uses Bearing (deg) and Distance (m) columns.
    """
    import pandas as pd

    bearing = pd.to_numeric(df[_COL_BEARING], errors="coerce").values.astype(float)
    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)

    # Convert bearing to radians, unwrap to remove 0/360 jumps
    hdg_rad = np.unwrap(np.radians(bearing))

    # dheading / ds
    ds = np.diff(dist)
    dh = np.diff(hdg_rad)
    ds = np.where(ds > 0, ds, np.nan)

    curvature = np.concatenate([[0.0], dh / ds])
    curvature = np.where(np.isfinite(curvature), curvature, 0.0)

    # Smooth with a small window to reduce noise
    if len(curvature) > 7:
        kernel = np.ones(7) / 7
        curvature = np.convolve(curvature, kernel, mode="same")

    return curvature


def detect_straights(
    df: "pd.DataFrame",
    *,
    curvature_threshold: float = _CURVATURE_STRAIGHT_THRESHOLD,
    min_length_m: float = _MIN_STRAIGHT_LENGTH_M,
) -> list[dict]:
    """Detect straight segments from curvature.

    Returns list of dicts with keys: s_start, s_end, length_m.
    """
    import pandas as pd

    if _COL_BEARING not in df.columns or _COL_DIST not in df.columns:
        logger.warning("detect_straights: missing Bearing or Distance column.")
        return []

    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)
    curvature = _compute_curvature(df)

    # Identify low-curvature regions
    is_straight = np.abs(curvature) < curvature_threshold

    # Find contiguous runs of True
    straights = []
    in_straight = False
    start_idx = 0

    for i in range(len(is_straight)):
        if is_straight[i] and not in_straight:
            start_idx = i
            in_straight = True
        elif not is_straight[i] and in_straight:
            s_start = float(dist[start_idx])
            s_end = float(dist[i - 1])
            length = s_end - s_start
            if length >= min_length_m:
                straights.append({
                    "s_start": round(s_start, 1),
                    "s_end": round(s_end, 1),
                    "length_m": round(length, 1),
                })
            in_straight = False

    # Handle straight that extends to end
    if in_straight:
        s_start = float(dist[start_idx])
        s_end = float(dist[-1])
        length = s_end - s_start
        if length >= min_length_m:
            straights.append({
                "s_start": round(s_start, 1),
                "s_end": round(s_end, 1),
                "length_m": round(length, 1),
            })

    logger.info("detect_straights: found %d straight segments.", len(straights))
    return straights
