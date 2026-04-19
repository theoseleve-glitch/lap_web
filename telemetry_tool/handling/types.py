"""Core data types for the handling detection system."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class CornerWindow:
    """Sliced data for a single corner, ready for detectors."""

    corner_id: int
    start_i: int                    # global index into session arrays
    end_i: int
    apex_g_i: int                   # index of peak |lateral G| (geometric apex)
    apex_speed_i: int               # index of minimum speed

    # Pre-sliced arrays (corner length)
    time_s: np.ndarray
    dist_m: np.ndarray
    speed_mps: np.ndarray
    a_lat_g: np.ndarray             # signed lateral G (positive = right turn)
    a_lon_g: np.ndarray             # longitudinal G (negative = braking)
    bearing_deg: np.ndarray
    lat_deg: np.ndarray
    lon_deg: np.ndarray
    yaw_rate_dps: np.ndarray        # GPS-derived yaw rate (deg/s)
    curvature: np.ndarray           # 1/m from GPS position

    # Derived scalars
    peak_g: float                   # max |a_lat_g| in the corner
    corner_len_m: float             # distance from start to end
    corner_dur_s: float             # time from start to end
    direction: int                  # +1 = right turn, -1 = left turn

    # Phase boundaries (from G-derivative segmentation)
    phase_entry: tuple[int, int] = (0, 0)    # (local_start, local_end)
    phase_mid: tuple[int, int] = (0, 0)
    phase_exit: tuple[int, int] = (0, 0)

    # Cross-lap matching
    apex_lat: float = 0.0
    apex_lon: float = 0.0

    @property
    def n_samples(self) -> int:
        return len(self.time_s)

    @property
    def fs(self) -> float:
        """Effective sampling rate."""
        if self.n_samples < 2:
            return 25.0
        return (self.n_samples - 1) / (self.corner_dur_s + 1e-9)


@dataclass
class SessionContext:
    """Session-level calibration and metadata available to all detectors."""

    # Calibration (from calibration.py)
    yaw_ratio_offset: float = 1.0       # session median yaw ratio (for normalizing)
    trail_braking_slope: float = 0.60    # per-session regression: overlap = slope*peak_g + intercept
    trail_braking_intercept: float = 0.05
    corner_g_threshold: float = 0.25     # adaptive corner detection G threshold
    friction_estimate_g: float = 1.0     # estimated max lateral G for the session
    native_gps_hz: float = 25.0          # GPS native update rate

    # Session-level arrays (full session, for cross-corner analysis)
    all_corners: list = field(default_factory=list)  # list[CornerWindow]
    all_lap_corners: dict = field(default_factory=dict)  # {lap_num: list[CornerWindow]}

    # Vehicle config
    wheelbase_m: float = 1.0
    vehicle_class: str = "kart"          # "kart" or "car"

    # Calibration profile for this vehicle class (loaded from JSON)
    calibration_profile: dict = field(default_factory=dict)

    # Pipeline coaching results (for ensemble detector #17)
    coaching_results: dict = field(default_factory=dict)


@dataclass
class DetectorVote:
    """Output of a single detector for a single corner."""

    detector_name: str
    direction: float            # -1 (oversteer) to +1 (understeer)
    confidence: float           # 0 to 1
    zone: str                   # "entry", "mid", "exit"
    raw_value: float = 0.0      # the detector's raw metric (for diagnostics)
    is_confidence_modifier: bool = False  # True for B7 line variation (modifies others, not a vote)


@dataclass
class FusedEvent:
    """Result of fusing multiple detector votes for one corner-zone."""

    corner_id: int
    zone: str                   # "entry", "mid", "exit"
    direction: float            # -1 (oversteer) to +1 (understeer)
    confidence: float           # 0 to 1
    start_dist_m: float
    end_dist_m: float
    duration_s: float
    n_voters: int
    conflict: bool = False      # True if detectors strongly disagree
    detector_votes: dict = field(default_factory=dict)  # {name: (direction, confidence)}

    @property
    def label(self) -> str:
        if self.direction > 0.15:
            return "understeer"
        elif self.direction < -0.15:
            return "oversteer"
        return "neutral"

    @property
    def severity(self) -> str:
        mag = abs(self.direction) * self.confidence
        if mag > 0.5:
            return "severe"
        elif mag > 0.25:
            return "moderate"
        elif mag > 0.1:
            return "mild"
        return "none"

    def to_dict(self) -> dict:
        """Serialize for JSON/DB persistence (matches HandlingEvent contract)."""
        return {
            "corner_id": self.corner_id,
            "event_type": self.label,
            "severity": self.severity,
            "corner_phase": self.zone,
            "direction": round(self.direction, 3),
            "confidence": round(self.confidence, 3),
            "s_start": round(self.start_dist_m, 2),
            "s_end": round(self.end_dist_m, 2),
            "duration_s": round(self.duration_s, 3),
            "magnitude": round(abs(self.direction), 3),
            "n_voters": self.n_voters,
            "conflict": self.conflict,
            "detector_votes": {
                k: {"direction": round(d, 3), "confidence": round(c, 3)}
                for k, (d, c) in self.detector_votes.items()
            },
        }
