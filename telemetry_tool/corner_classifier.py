"""Corner classification using geometry + speed context.

Classifies corners into types: kink, fast_sweeper, simple, hairpin,
double_apex, compound, chicane, decreasing_radius, increasing_radius.

Uses curvature profile shape, arc length, speed ratio (min corner speed
vs straight speed), direction changes, and heading change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class CornerClassification:
    """Result of corner type classification."""
    corner_type: str
    min_radius_m: float
    arc_length_m: float
    speed_ratio: float
    confidence: float


_KINK_MAX_LENGTH_M = 40.0
_KINK_MAX_SPEED_DROP = 0.10
_SWEEPER_MIN_LENGTH_M = 80.0
_SWEEPER_MIN_SPEED_RATIO = 0.70
_HAIRPIN_MAX_RADIUS_M = 25.0
_HAIRPIN_MIN_HEADING_DEG = 120.0
_DECREASING_RADIUS_SLOPE_THRESHOLD = 0.3


def classify_corner(
    distances: np.ndarray,
    curvatures: np.ndarray,
    speeds: np.ndarray,
    *,
    direction_changes: int = 0,
    directions: Optional[list[str]] = None,
    n_peaks: int = 1,
    total_heading_change: float = 0.0,
    straight_speed_mps: Optional[float] = None,
) -> CornerClassification:
    """Classify a corner segment by geometry and speed profile.

    Parameters
    ----------
    distances : array of cumulative distance values (metres).
    curvatures : array of curvature values (1/m) aligned with *distances*.
    speeds : array of speed values (m/s) aligned with *distances*.
    direction_changes : number of direction reversals within the corner.
    directions : list of turn directions for each sub-apex (e.g. ["L", "R"]).
    n_peaks : number of curvature peaks detected in the segment.
    total_heading_change : absolute heading change across the corner (degrees).
    straight_speed_mps : reference straight-line speed (m/s) for ratio calc.

    Returns
    -------
    CornerClassification with corner_type, min_radius_m, arc_length_m,
    speed_ratio, and confidence.
    """
    arc_length = float(distances[-1] - distances[0])
    max_curv = float(np.max(np.abs(curvatures)))
    min_radius = 1.0 / max_curv if max_curv > 1e-6 else 9999.0
    min_speed = float(np.min(speeds))
    max_speed = float(np.max(speeds))

    if straight_speed_mps is not None and straight_speed_mps > 0:
        speed_ratio = min_speed / straight_speed_mps
    else:
        speed_ratio = min_speed / max_speed if max_speed > 0 else 1.0

    directions = directions or []
    confidence = 0.8

    # --- Multi-peak logic (chicane / double-apex / compound) ---
    if n_peaks >= 2:
        if (direction_changes >= 1 and len(set(directions)) > 1
                and n_peaks == 2):
            corner_type = "chicane"
            confidence = 0.85
        elif direction_changes == 0 and len(set(directions)) == 1:
            corner_type = "double_apex"
            confidence = 0.80
        else:
            corner_type = "compound"
            confidence = 0.75

    # --- Single-peak logic ---
    elif arc_length < _KINK_MAX_LENGTH_M and (1.0 - speed_ratio) < _KINK_MAX_SPEED_DROP:
        corner_type = "kink"
        confidence = 0.85

    elif (total_heading_change >= _HAIRPIN_MIN_HEADING_DEG
          and min_radius < _HAIRPIN_MAX_RADIUS_M):
        corner_type = "hairpin"
        confidence = 0.90

    elif (arc_length >= _SWEEPER_MIN_LENGTH_M
          and speed_ratio >= _SWEEPER_MIN_SPEED_RATIO):
        corner_type = "fast_sweeper"
        confidence = 0.80

    else:
        # Check for radius variation (decreasing / increasing)
        n = len(curvatures)
        if n >= 10:
            first_half_mean = float(np.mean(np.abs(curvatures[:n // 2])))
            second_half_mean = float(np.mean(np.abs(curvatures[n // 2:])))
            total_mean = (first_half_mean + second_half_mean) / 2
            if total_mean > 1e-6:
                ratio = (second_half_mean - first_half_mean) / total_mean
                if ratio > _DECREASING_RADIUS_SLOPE_THRESHOLD:
                    corner_type = "decreasing_radius"
                    confidence = 0.70
                elif ratio < -_DECREASING_RADIUS_SLOPE_THRESHOLD:
                    corner_type = "increasing_radius"
                    confidence = 0.70
                else:
                    corner_type = "simple"
                    confidence = 0.85
            else:
                corner_type = "simple"
                confidence = 0.85
        else:
            corner_type = "simple"
            confidence = 0.85

    return CornerClassification(
        corner_type=corner_type,
        min_radius_m=min_radius,
        arc_length_m=arc_length,
        speed_ratio=speed_ratio,
        confidence=confidence,
    )
