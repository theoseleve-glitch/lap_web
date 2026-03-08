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
