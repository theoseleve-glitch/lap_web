"""Per-lap corner diagnosis classifier.

Classifies driving symptoms for each user-selected corner on every valid lap.
Produces a flat grid {lap_number: {corner_id: label}} with one dominant label
per cell from a 23-label taxonomy across 4 corner phases.

Spec: docs/superpowers/specs/2026-03-12-corner-diagnosis-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label constants
# ---------------------------------------------------------------------------
# Entry phase
ENTRY_OVERSPEED = "entry_overspeed"
ENTRY_UNDERSPEED = "entry_underspeed"
LATE_BRAKING = "late_braking"
EARLY_BRAKING = "early_braking"
ENTRY_UNDERSTEER = "entry_understeer"
ENTRY_OVERSTEER = "entry_oversteer"
INSUFFICIENT_TRAIL_BRAKE = "insufficient_trail_brake"
EXCESSIVE_TRAIL_BRAKE = "excessive_trail_brake"
# Apex / mid-corner phase
LOW_MIN_SPEED = "low_min_speed"
EARLY_APEX = "early_apex"
LATE_APEX = "late_apex"
MID_CORNER_UNDERSTEER = "mid_corner_understeer"
MID_CORNER_OVERSTEER = "mid_corner_oversteer"
COAST_HESITATION = "coast_hesitation"
# Exit phase
EXIT_UNDERSTEER = "exit_understeer"
EXIT_OVERSTEER = "exit_oversteer"
EARLY_THROTTLE = "early_throttle"
LATE_ROTATION = "late_rotation"
LATE_THROTTLE = "late_throttle"
THROTTLE_LIFT = "throttle_lift"
# Overall
GOOD = "good"
SLOW_EXIT = "slow_exit"
SCRAPPY = "scrappy"

# Safety labels get highest priority
_SAFETY_LABELS = {EXIT_OVERSTEER, ENTRY_OVERSTEER}

# ---------------------------------------------------------------------------
# Causal chains: child -> parent (root cause)
# ---------------------------------------------------------------------------
_CAUSAL_PARENT: dict[str, str] = {
    ENTRY_UNDERSTEER: ENTRY_OVERSPEED,
    EARLY_APEX: ENTRY_UNDERSTEER,
    MID_CORNER_UNDERSTEER: ENTRY_OVERSPEED,
    EXCESSIVE_TRAIL_BRAKE: LATE_BRAKING,
    ENTRY_OVERSTEER: LATE_BRAKING,  # via excessive trail brake
    LATE_THROTTLE: COAST_HESITATION,
    THROTTLE_LIFT: SLOW_EXIT,
    EXIT_UNDERSTEER: EARLY_THROTTLE,  # power understeer caused by early throttle
}
# Chains where child (key) is suppressed when ANY of its parents (values) are present:
_CAUSAL_ALWAYS: dict[str, list[str]] = {
    SLOW_EXIT: [EARLY_APEX, LATE_ROTATION],
}
# Note: can't use dict[str, str] — SLOW_EXIT has two parents, duplicate key would silently drop one.


# ---------------------------------------------------------------------------
# Vehicle class thresholds
# ---------------------------------------------------------------------------
_CAR_THRESHOLDS = {
    "v_entry_delta_kmh": 3.0,
    "v_underspeed_delta_kmh": 5.0,
    "v_min_delta_kmh": 3.0,  # spec Vehicle Class Thresholds table: car=3, kart=2
    "v_exit_delta_kmh": 5.0,
    "coast_gap_s": 0.3,
    "yaw_residual_dps": 10.0,
    "good_time_tol_s": 0.15,
    "late_rotation_m": 8.0,
    "apex_offset_m": 5.0,
    "exit_yaw_understeer_dps": 8.0,  # slightly lower threshold for exit understeer
}

_KART_THRESHOLDS = {
    "v_entry_delta_kmh": 2.0,
    "v_underspeed_delta_kmh": 5.0,  # spec: no kart/car split for underspeed, 5 km/h uniform
    "v_min_delta_kmh": 2.0,
    "v_exit_delta_kmh": 3.0,
    "coast_gap_s": 0.2,
    "yaw_residual_dps": 8.0,
    "good_time_tol_s": 0.10,
    "late_rotation_m": 4.0,
    "apex_offset_m": 3.0,
    "exit_yaw_understeer_dps": 6.0,
}


def _get_thresholds(vehicle_class: str) -> dict:
    """Return threshold dict for the given vehicle class."""
    if vehicle_class == "kart":
        return _KART_THRESHOLDS.copy()
    return _CAR_THRESHOLDS.copy()


# ---------------------------------------------------------------------------
# Tier detection
# ---------------------------------------------------------------------------
_BRAKE_THROTTLE_COLS = {
    "Brake (%)", "Throttle (%)", "brake_pct", "throttle_pct",
    "Brake", "Throttle",
}
_ACCEL_COLS = {"accel_lat_mps2", "accel_long_mps2", "Lat G", "Long G"}


def _detect_tier(columns: set[str]) -> str:
    """Determine detection tier from available DataFrame columns."""
    if columns & _BRAKE_THROTTLE_COLS:
        return "full"
    if columns & _ACCEL_COLS:
        return "accel"
    return "gps"
