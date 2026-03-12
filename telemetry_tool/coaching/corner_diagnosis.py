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


# ---------------------------------------------------------------------------
# Segment extraction and metrics
# ---------------------------------------------------------------------------
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_HEADING = "Heading (rad)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_ACCEL_LAT = "accel_lat_mps2"
_COL_BRAKE = "Brake (%)"
_COL_THROTTLE = "Throttle (%)"


def _extract_corner_metrics(
    lap_df: pd.DataFrame,
    corner: dict,
    curvature_profile: "pd.DataFrame | None",
    mrp_event: "dict | None",
) -> "dict | None":
    """Slice a lap DataFrame for one corner and compute all metrics.

    Returns None if the segment has fewer than 5 data points.
    """
    s_entry = corner["s_entry"]
    s_apex = corner["s_apex"]
    s_exit = corner["s_exit"]

    if _COL_DIST not in lap_df.columns or _COL_SPEED not in lap_df.columns:
        return None

    dist = lap_df[_COL_DIST].values
    # Include 50m pre-corner buffer for early_braking detection
    mask = (dist >= s_entry - 50.0) & (dist <= s_exit)
    core_mask = (dist >= s_entry) & (dist <= s_exit)
    if core_mask.sum() < 5:
        return None

    seg = lap_df[mask]  # boolean indexing (not .loc) — safe regardless of index type
    d = seg[_COL_DIST].values
    v = seg[_COL_SPEED].values

    # Basic speed metrics
    v_entry_mps = float(np.interp(s_entry, d, v))
    v_exit_mps = float(np.interp(s_exit, d, v))
    vmin_idx = int(np.argmin(v))
    v_min_mps = float(v[vmin_idx])
    s_vmin = float(d[vmin_idx])

    # Kappa sign (corner direction)
    kappa_sign = _compute_kappa_sign(seg, s_apex, curvature_profile)

    # Yaw residual (direction-normalised)
    yaw_residual = _compute_yaw_residual(seg, curvature_profile, kappa_sign)

    # Accel channels (may be None)
    lon_g = seg[_COL_ACCEL_LONG].values if _COL_ACCEL_LONG in seg.columns else None
    lat_g = seg[_COL_ACCEL_LAT].values if _COL_ACCEL_LAT in seg.columns else None

    # Pedal channels (may be None)
    brake = seg[_COL_BRAKE].values if _COL_BRAKE in seg.columns else None
    throttle = seg[_COL_THROTTLE].values if _COL_THROTTLE in seg.columns else None

    metrics = {
        "s_entry": s_entry,
        "s_apex": s_apex,
        "s_exit": s_exit,
        "d": d,
        "v": v,
        "v_entry_mps": v_entry_mps,
        "v_exit_mps": v_exit_mps,
        "v_min_mps": v_min_mps,
        "s_vmin": s_vmin,
        "kappa_sign": kappa_sign,
        "yaw_residual": yaw_residual,
        "lon_g": lon_g,
        "lat_g": lat_g,
        "brake": brake,
        "throttle": throttle,
        # MRP fields (may be None)
        "mrp_m": mrp_event["mrp_m"] if mrp_event else None,
        "mrp_apex_delta_m": mrp_event["mrp_apex_delta_m"] if mrp_event else None,
    }
    return metrics


def _compute_kappa_sign(
    seg: pd.DataFrame, s_apex: float, curvature_profile: "pd.DataFrame | None",
) -> float:
    """Determine corner direction: +1 = left turn, -1 = right turn."""
    if curvature_profile is not None and len(curvature_profile) > 1:
        cp_dist = curvature_profile["distance_m"].values
        cp_curv = curvature_profile["curvature_1pm"].values
        kappa_at_apex = float(np.interp(s_apex, cp_dist, cp_curv))
        if abs(kappa_at_apex) > 1e-6:
            return float(np.sign(kappa_at_apex))

    # Fallback: heading change across segment
    if _COL_HEADING in seg.columns:
        h = seg[_COL_HEADING].values
        if len(h) >= 2:
            delta_rad = h[-1] - h[0]
            delta_rad = (delta_rad + np.pi) % (2 * np.pi) - np.pi
            if abs(delta_rad) > 1e-6:
                return float(np.sign(delta_rad))

    return 1.0  # default left turn if unknown


def _compute_yaw_residual(
    seg: pd.DataFrame, curvature_profile: "pd.DataFrame | None", kappa_sign: float,
) -> "np.ndarray | None":
    """Compute direction-normalised yaw residual for the segment.

    yaw_residual_norm = (yaw_measured - yaw_expected) * sign(kappa)
    Positive = oversteer, Negative = understeer.
    Returns None if heading data is unavailable.
    """
    if _COL_HEADING not in seg.columns or _COL_SPEED not in seg.columns:
        return None
    if _COL_DIST not in seg.columns:
        return None

    d = seg[_COL_DIST].values
    v = seg[_COL_SPEED].values
    h = seg[_COL_HEADING].values

    if len(d) < 3:
        return None

    # Measured yaw rate: dh/dd (rad/m) * v (m/s) = rad/s, then * (180/pi) = deg/s
    dd = np.diff(d)
    dd = np.where(np.abs(dd) > 1e-9, dd, 1e-9)
    dh = np.diff(h)
    dh = (dh + np.pi) % (2 * np.pi) - np.pi  # wrap
    yaw_rate_radpm = dh / dd
    yaw_rate_radpm = np.append(yaw_rate_radpm, yaw_rate_radpm[-1])
    # Convert to deg/s: yaw_rate_radpm * speed * (180/pi)
    yaw_measured_dps = yaw_rate_radpm * v * (180.0 / np.pi)

    # Expected yaw rate from curvature
    if curvature_profile is not None and len(curvature_profile) > 1:
        cp_dist = curvature_profile["distance_m"].values
        cp_curv = curvature_profile["curvature_1pm"].values
        kappa = np.interp(d, cp_dist, cp_curv)
    else:
        # No curvature profile: assume uniform curvature from heading change
        total_heading_change = h[-1] - h[0]
        total_heading_change = (total_heading_change + np.pi) % (2 * np.pi) - np.pi
        total_dist = d[-1] - d[0]
        if abs(total_dist) > 1e-6:
            kappa = np.full(len(d), total_heading_change / total_dist)
        else:
            return None

    yaw_expected_dps = v * kappa * (180.0 / np.pi)

    # Direction-normalised residual
    residual = (yaw_measured_dps - yaw_expected_dps) * kappa_sign
    return residual


@dataclass
class Candidate:
    """A candidate label with priority for resolution."""
    label: str
    priority: int  # lower = higher priority (safety=1, time-loss=2, misc=3)
    phase: str     # "entry", "apex", "exit", "overall"


def _check_entry_phase(
    metrics: dict, theo: dict | None, thresholds: dict, tier: str,
) -> list[Candidate]:
    """Check entry phase labels. Returns list of candidates."""
    candidates: list[Candidate] = []
    v_entry = metrics["v_entry_mps"]
    d = metrics["d"]
    s_entry = metrics["s_entry"]
    s_apex = metrics["s_apex"]

    # Entry half indices
    entry_mask = d <= s_apex

    # Speed-based checks (all tiers)
    if theo and "v_entry_mps" in theo:
        v_theo = theo["v_entry_mps"]
        delta_kmh = (v_entry - v_theo) * 3.6
        if delta_kmh > thresholds["v_entry_delta_kmh"]:
            candidates.append(Candidate(ENTRY_OVERSPEED, 2, "entry"))
        elif -delta_kmh > thresholds.get("v_underspeed_delta_kmh", 5.0):
            candidates.append(Candidate(ENTRY_UNDERSPEED, 3, "entry"))

    # Yaw residual checks (all tiers)
    yaw_res = metrics.get("yaw_residual")
    if yaw_res is not None and entry_mask.sum() >= 5:
        entry_yaw = yaw_res[entry_mask]
        yaw_thresh = thresholds["yaw_residual_dps"]
        # Oversteer: sustained positive residual
        if np.sum(entry_yaw > yaw_thresh) >= 5:
            candidates.append(Candidate(ENTRY_OVERSTEER, 1, "entry"))
        # Understeer: sustained negative residual
        elif np.sum(entry_yaw < -yaw_thresh) >= 5:
            candidates.append(Candidate(ENTRY_UNDERSTEER, 2, "entry"))

    # Accel-tier checks
    lon_g = metrics.get("lon_g")
    if tier in ("accel", "full") and lon_g is not None:
        # Late braking: lon_g < -0.3g past s_apex
        past_apex = d > s_apex
        if past_apex.any() and np.any(lon_g[past_apex] < -0.3 * 9.81):
            candidates.append(Candidate(LATE_BRAKING, 2, "entry"))
        # Early braking: lon_g < -0.3g starts >15m before s_entry
        pre_entry = d < (s_entry - 15.0)
        if pre_entry.any() and np.any(lon_g[pre_entry] < -0.3 * 9.81):
            candidates.append(Candidate(EARLY_BRAKING, 3, "entry"))
        # Excessive trail brake: lon_g < -0.2g at s_apex
        apex_idx = np.argmin(np.abs(d - s_apex))
        if lon_g[apex_idx] < -0.2 * 9.81:
            candidates.append(Candidate(EXCESSIVE_TRAIL_BRAKE, 2, "entry"))

    # Pedal-tier checks
    brake = metrics.get("brake")
    if tier == "full" and brake is not None:
        # Late braking: brake > 20% past s_apex
        past_apex = d > s_apex
        if past_apex.any() and np.any(brake[past_apex] > 20):
            if not any(c.label == LATE_BRAKING for c in candidates):
                candidates.append(Candidate(LATE_BRAKING, 2, "entry"))
        # Early braking: brake > 10% starts >15m before s_entry
        pre_entry = d < (s_entry - 15.0)
        if pre_entry.any() and np.any(brake[pre_entry] > 10):
            if not any(c.label == EARLY_BRAKING for c in candidates):
                candidates.append(Candidate(EARLY_BRAKING, 3, "entry"))
        # Excessive trail brake: brake > 30% at s_apex
        apex_idx = np.argmin(np.abs(d - s_apex))
        if brake[apex_idx] > 30:
            if not any(c.label == EXCESSIVE_TRAIL_BRAKE for c in candidates):
                candidates.append(Candidate(EXCESSIVE_TRAIL_BRAKE, 2, "entry"))
        # Insufficient trail brake: brake to 0 before first 10% of corner
        corner_len = s_apex - s_entry
        first_10pct = s_entry + corner_len * 0.1
        early_mask = d <= first_10pct
        if early_mask.any() and np.all(brake[early_mask] < 1):
            candidates.append(Candidate(INSUFFICIENT_TRAIL_BRAKE, 3, "entry"))

    return candidates


def _check_apex_phase(
    metrics: dict, theo: dict | None, thresholds: dict, tier: str,
) -> list[Candidate]:
    """Check apex/mid-corner phase labels."""
    candidates: list[Candidate] = []
    s_apex = metrics["s_apex"]
    s_entry = metrics["s_entry"]
    s_exit = metrics["s_exit"]
    v_min = metrics["v_min_mps"]
    s_vmin = metrics["s_vmin"]
    d = metrics["d"]
    v = metrics["v"]
    apex_offset = thresholds["apex_offset_m"]

    # Low min speed (all tiers)
    if theo and "v_min_mps" in theo:
        delta_kmh = (theo["v_min_mps"] - v_min) * 3.6
        if delta_kmh > thresholds["v_min_delta_kmh"]:
            candidates.append(Candidate(LOW_MIN_SPEED, 2, "apex"))

    # Apex position (all tiers)
    if s_vmin < s_apex - apex_offset:
        candidates.append(Candidate(EARLY_APEX, 2, "apex"))
    elif s_vmin > s_apex + apex_offset:
        candidates.append(Candidate(LATE_APEX, 3, "apex"))

    # Yaw residual in apex zone (all tiers)
    apex_zone_start = s_apex - 0.15 * (s_exit - s_entry)
    apex_zone_end = s_apex + 0.15 * (s_exit - s_entry)
    apex_mask = (d >= apex_zone_start) & (d <= apex_zone_end)

    yaw_res = metrics.get("yaw_residual")
    if yaw_res is not None and apex_mask.sum() >= 3:
        apex_yaw = yaw_res[apex_mask]
        yaw_thresh = thresholds["yaw_residual_dps"]
        if np.sum(apex_yaw > yaw_thresh) >= 3:
            candidates.append(Candidate(MID_CORNER_OVERSTEER, 1, "apex"))
        elif np.sum(apex_yaw < -yaw_thresh) >= 3:
            candidates.append(Candidate(MID_CORNER_UNDERSTEER, 2, "apex"))

    # Coast hesitation
    coast_gap_s = thresholds["coast_gap_s"]
    _check_coast_hesitation(metrics, tier, coast_gap_s, candidates)

    return candidates


def _check_coast_hesitation(
    metrics: dict, tier: str, coast_gap_s: float, candidates: list[Candidate],
) -> None:
    """Detect coast hesitation across all three tiers."""
    d = metrics["d"]
    v = metrics["v"]

    if tier == "full":
        brake = metrics.get("brake")
        throttle = metrics.get("throttle")
        if brake is not None and throttle is not None:
            coast_mask = (brake < 5) & (throttle < 10)
            if _sustained_run(coast_mask, d, coast_gap_s):
                candidates.append(Candidate(COAST_HESITATION, 3, "apex"))
                return

    if tier in ("accel", "full"):
        lon_g = metrics.get("lon_g")
        if lon_g is not None:
            coast_mask = np.abs(lon_g) < 0.05 * 9.81
            if _sustained_run(coast_mask, d, coast_gap_s):
                candidates.append(Candidate(COAST_HESITATION, 3, "apex"))
                return

    # GPS tier only: smoothed speed derivative
    if tier == "gps" and len(v) >= 3 and len(d) >= 3:
        v_smooth = np.convolve(v, [0.25, 0.5, 0.25], mode="same")
        dd = np.diff(d)
        dd = np.where(np.abs(dd) > 1e-9, dd, 1e-9)
        dv_ds = np.diff(v_smooth) / dd
        v_avg = (v_smooth[:-1] + v_smooth[1:]) / 2
        accel_approx = dv_ds * v_avg
        coast_mask_gps = np.abs(accel_approx) < 0.5
        coast_mask_full = np.zeros(len(d), dtype=bool)
        coast_mask_full[:-1] = coast_mask_gps
        if _sustained_run(coast_mask_full, d, coast_gap_s):
            candidates.append(Candidate(COAST_HESITATION, 3, "apex"))


def _sustained_run(mask: np.ndarray, distances: np.ndarray, min_duration_s: float) -> bool:
    """Check if a boolean mask has a contiguous True run spanning >= min_duration_s.

    Uses distance span as proxy for time (assumes ~constant speed in the zone).
    """
    if not mask.any():
        return False
    min_dist = min_duration_s * 20.0  # conservative ~20 m/s

    runs = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    starts = np.where(runs == 1)[0]
    ends = np.where(runs == -1)[0]
    for s, e in zip(starts, ends):
        if e <= len(distances) and s < len(distances):
            span = distances[min(e, len(distances) - 1)] - distances[s]
            if span >= min_dist:
                return True
    return False


def _check_exit_phase(
    metrics: dict, theo: dict | None, thresholds: dict, tier: str,
) -> list[Candidate]:
    """Check exit phase labels."""
    candidates: list[Candidate] = []
    s_apex = metrics["s_apex"]
    s_exit = metrics["s_exit"]
    d = metrics["d"]
    v = metrics["v"]

    exit_mask = d >= s_apex

    # Late rotation (all tiers, requires MRP data)
    mrp_delta = metrics.get("mrp_apex_delta_m")
    if mrp_delta is not None and mrp_delta > thresholds["late_rotation_m"]:
        candidates.append(Candidate(LATE_ROTATION, 2, "exit"))

    # Yaw residual in exit zone (accel + full tiers only)
    yaw_res = metrics.get("yaw_residual")
    if tier in ("accel", "full") and yaw_res is not None and exit_mask.sum() >= 3:
        exit_yaw = yaw_res[exit_mask]
        if np.sum(exit_yaw > thresholds["yaw_residual_dps"]) >= 3:
            candidates.append(Candidate(EXIT_OVERSTEER, 1, "exit"))
        elif np.sum(exit_yaw < -thresholds["exit_yaw_understeer_dps"]) >= 3:
            candidates.append(Candidate(EXIT_UNDERSTEER, 2, "exit"))

    # Pedal-tier checks
    throttle = metrics.get("throttle")
    if tier == "full" and throttle is not None:
        mrp_m = metrics.get("mrp_m")

        # Early throttle: throttle > 50% before MRP + 2m (or v_min fallback)
        reference_m = (mrp_m + 2.0) if mrp_m is not None else metrics["s_vmin"]
        before_ref = (d >= s_apex) & (d < reference_m)
        if before_ref.any() and np.any(throttle[before_ref] > 50):
            candidates.append(Candidate(EARLY_THROTTLE, 2, "exit"))

        # Late throttle: first throttle application > 40% of exit zone past apex
        exit_zone_len = s_exit - s_apex
        late_threshold_m = s_apex + 0.4 * exit_zone_len
        first_throttle_idx = None
        for i in range(len(d)):
            if d[i] >= s_apex and throttle[i] > 10:
                first_throttle_idx = i
                break
        if first_throttle_idx is not None and d[first_throttle_idx] > late_threshold_m:
            candidates.append(Candidate(LATE_THROTTLE, 3, "exit"))

        # Throttle lift: drop > 20% before s_exit after initial application
        exit_throttle = throttle[exit_mask]
        if len(exit_throttle) > 5:
            peak_throttle = 0.0
            for val in exit_throttle:
                if val > peak_throttle:
                    peak_throttle = val
                elif peak_throttle > 20 and (peak_throttle - val) > 20:
                    candidates.append(Candidate(THROTTLE_LIFT, 2, "exit"))
                    break

    return candidates


def _check_overall(
    metrics: dict, theo: dict | None, thresholds: dict,
    existing_candidates: list[Candidate],
) -> list[Candidate]:
    """Check overall labels: slow_exit, scrappy."""
    candidates: list[Candidate] = []

    # Slow exit: exit speed deficit with no entry/apex cause
    if theo and "v_exit_mps" in theo:
        delta_kmh = (theo["v_exit_mps"] - metrics["v_exit_mps"]) * 3.6
        has_upstream_cause = any(
            c.phase in ("entry", "apex") for c in existing_candidates
        )
        if delta_kmh > thresholds["v_exit_delta_kmh"] and not has_upstream_cause:
            candidates.append(Candidate(SLOW_EXIT, 3, "overall"))

    # Scrappy: many yaw sign reversals (spec: >2 sign-reversals in residual)
    yaw_res = metrics.get("yaw_residual")
    if yaw_res is not None and len(yaw_res) > 2:
        signs = np.sign(yaw_res)
        reversals = int(np.sum(np.abs(np.diff(signs)) > 0))
        if reversals > 2:
            candidates.append(Candidate(SCRAPPY, 3, "overall"))

    # Throttle modulations (scrappy via pedals)
    throttle = metrics.get("throttle")
    if throttle is not None and not any(c.label == SCRAPPY for c in candidates):
        above = throttle > 20
        transitions = np.sum(np.abs(np.diff(above.astype(int))))
        if transitions > 4:
            candidates.append(Candidate(SCRAPPY, 3, "overall"))

    return candidates


def _resolve_and_pick(candidates: list[Candidate]) -> str:
    """Resolve causal chains and return the single dominant label.

    1. Remove labels that are downstream of a present root cause.
    2. Pick the highest-priority remaining label.
    3. Return "good" if nothing remains.
    """
    if not candidates:
        return GOOD

    # Build set of present labels
    present = {c.label for c in candidates}

    # Remove downstream labels when their upstream cause is present
    to_remove: set[str] = set()
    for child, parent in _CAUSAL_PARENT.items():
        if child in present and parent in present:
            to_remove.add(child)

    # Also check "always" chains (e.g. slow_exit removed when early_apex or late_rotation present)
    for child, parents in _CAUSAL_ALWAYS.items():
        if child in present and any(p in present for p in parents):
            to_remove.add(child)

    filtered = [c for c in candidates if c.label not in to_remove]
    if not filtered:
        return GOOD

    # Sort by priority (lower = higher priority), then prefer safety labels
    filtered.sort(key=lambda c: (c.priority, c.label not in _SAFETY_LABELS))
    return filtered[0].label


# ---------------------------------------------------------------------------
# MRP key mapping
# ---------------------------------------------------------------------------
def _map_mrp_to_corners(
    user_corners: list[dict], mrp_events: dict[int, dict] | None,
) -> dict[int, dict | None]:
    """Map user corner_index to MRP event dict.

    Strategy: positional match first (sorted corner_index vs sorted section_id),
    then spatial fallback (overlapping distance ranges).
    Returns {corner_index: mrp_event_dict_or_None}.
    """
    result: dict[int, dict | None] = {c["corner_index"]: None for c in user_corners}
    if not mrp_events:
        return result

    sorted_corners = sorted(user_corners, key=lambda c: c["corner_index"])
    sorted_mrp_keys = sorted(mrp_events.keys())

    # Positional match
    if len(sorted_corners) == len(sorted_mrp_keys):
        for corner, mrp_key in zip(sorted_corners, sorted_mrp_keys):
            result[corner["corner_index"]] = mrp_events[mrp_key]
        return result

    # Spatial fallback: overlap between corner [s_entry, s_exit] and MRP [s_start, s_end]
    for corner in sorted_corners:
        s_entry = corner["s_entry"]
        s_exit = corner["s_exit"]
        for mrp_key, mrp_ev in mrp_events.items():
            mrp_m = mrp_ev.get("mrp_m", 0)
            if s_entry <= mrp_m <= s_exit:
                result[corner["corner_index"]] = mrp_ev
                break

    return result


# ---------------------------------------------------------------------------
# Theoretical metrics extraction
# ---------------------------------------------------------------------------
def _extract_theo_metrics(
    theoretical_lap: pd.DataFrame | None, corner: dict,
) -> dict | None:
    """Extract theoretical speed metrics for a corner from the theoretical lap."""
    if theoretical_lap is None:
        return None
    if _COL_DIST not in theoretical_lap.columns or _COL_SPEED not in theoretical_lap.columns:
        return None

    d = theoretical_lap[_COL_DIST].values
    v = theoretical_lap[_COL_SPEED].values
    s_entry = corner["s_entry"]
    s_apex = corner["s_apex"]
    s_exit = corner["s_exit"]

    mask = (d >= s_entry) & (d <= s_exit)
    if mask.sum() < 3:
        return None

    seg_d = d[mask]
    seg_v = v[mask]

    return {
        "v_entry_mps": float(np.interp(s_entry, seg_d, seg_v)),
        "v_min_mps": float(np.min(seg_v)),
        "v_exit_mps": float(np.interp(s_exit, seg_d, seg_v)),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def classify_all_corners(
    resampled_laps: dict[int, pd.DataFrame],
    theoretical_lap: pd.DataFrame | None,
    user_corners: list[dict],
    vehicle_class: str,
    valid_lap_numbers: list[int],
    curvature_profile: pd.DataFrame | None = None,
    mrp_events: dict[int, dict] | None = None,
) -> dict[str, dict[str, str | None]]:
    """Classify driving symptoms for each user corner on every valid lap.

    Returns {lap_num_str: {corner_index_str: label}}.
    """
    if not user_corners or not valid_lap_numbers:
        return {}

    thresholds = _get_thresholds(vehicle_class)
    mrp_map = _map_mrp_to_corners(user_corners, mrp_events)

    # Pre-compute theoretical metrics per corner
    theo_per_corner: dict[int, dict | None] = {}
    for corner in user_corners:
        cid = corner["corner_index"]
        theo_per_corner[cid] = _extract_theo_metrics(theoretical_lap, corner)

    result: dict[str, dict[str, str]] = {}

    for lap_num in valid_lap_numbers:
        lap_df = resampled_laps.get(lap_num)
        if lap_df is None or lap_df.empty:
            continue

        tier = _detect_tier(set(lap_df.columns))
        lap_labels: dict[str, str] = {}

        for corner in user_corners:
            cid = corner["corner_index"]
            mrp_event = mrp_map.get(cid)
            theo = theo_per_corner.get(cid)

            metrics = _extract_corner_metrics(lap_df, corner, curvature_profile, mrp_event)
            if metrics is None:
                lap_labels[str(cid)] = None
                continue

            # Run all phase checkers
            entry = _check_entry_phase(metrics, theo, thresholds, tier)
            apex = _check_apex_phase(metrics, theo, thresholds, tier)
            exit_ = _check_exit_phase(metrics, theo, thresholds, tier)
            all_phase = entry + apex + exit_
            overall = _check_overall(metrics, theo, thresholds, all_phase)
            all_candidates = all_phase + overall

            lap_labels[str(cid)] = _resolve_and_pick(all_candidates)

        result[str(lap_num)] = lap_labels

    return result
