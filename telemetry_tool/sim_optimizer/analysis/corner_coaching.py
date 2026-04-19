"""Per-corner root cause analysis and coaching text generation."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.analysis.delta import LapDelta

log = logging.getLogger(__name__)


@dataclass
class CornerDelta:
    corner_id: int
    entry_dist_m: float
    apex_dist_m: float
    exit_dist_m: float
    time_loss_s: float
    root_cause: str  # "braked_late"|"braked_early"|"apex_speed_low"|"throttle_late"|"oversteer"|"understeer"|"clean"
    coaching_text: str
    brake_point_delta_m: float  # positive = driver braked later than theoretical
    apex_speed_delta_kph: float  # positive = driver was slower at apex
    exit_throttle_delta_pct: float  # positive = theoretical uses more throttle at exit

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "entry_dist_m": round(self.entry_dist_m, 1),
            "apex_dist_m": round(self.apex_dist_m, 1),
            "exit_dist_m": round(self.exit_dist_m, 1),
            "time_loss_s": round(self.time_loss_s, 3),
            "root_cause": self.root_cause,
            "coaching_text": self.coaching_text,
            "brake_point_delta_m": round(self.brake_point_delta_m, 1),
            "apex_speed_delta_kph": round(self.apex_speed_delta_kph, 1),
            "exit_throttle_delta_pct": round(self.exit_throttle_delta_pct, 1),
        }


def _detect_corners(
    distance_m: np.ndarray,
    curvature: np.ndarray,
    min_curvature: float = 0.005,
) -> list[tuple[int, int, int]]:
    """Detect corners as contiguous regions where |curvature| > threshold.

    Returns list of (entry_idx, apex_idx, exit_idx) tuples.
    apex = index of max |curvature| within the region.
    """
    above = np.abs(curvature) > min_curvature
    corners: list[tuple[int, int, int]] = []

    i = 0
    n = len(above)
    while i < n:
        if above[i]:
            entry = i
            # Walk forward to find end of corner region
            while i < n and above[i]:
                i += 1
            exit_idx = i - 1
            # Apex is the point of max |curvature| within region
            region_abs = np.abs(curvature[entry : exit_idx + 1])
            apex = entry + int(np.argmax(region_abs))
            corners.append((entry, apex, exit_idx))
        else:
            i += 1

    return corners


def _find_brake_point(
    brake: np.ndarray,
    region_start: int,
    threshold: float = 0.1,
) -> int | None:
    """Search backward from region_start for first sample where brake > threshold.

    Returns the index of the first brake application found searching backwards,
    or None if no braking detected within a reasonable lookback window.
    """
    lookback = min(region_start, 200)  # max 200 samples back
    for idx in range(region_start, region_start - lookback - 1, -1):
        if idx < 0:
            break
        if brake[idx] > threshold:
            # Found braking; now walk further back to find where it started
            while idx > 0 and brake[idx - 1] > threshold:
                idx -= 1
            return idx
    return None


def _classify_root_cause(
    brake_point_delta_m: float,
    apex_speed_delta_kph: float,
    exit_throttle_delta_pct: float,
) -> tuple[str, str]:
    """Determine root cause and coaching text from deltas.

    Priority order (biggest contributor first):
    1. If |brake_point_delta_m| > 10: "braked_late"/"braked_early"
    2. If apex_speed_delta_kph > 3: "apex_speed_low"
    3. If exit_throttle_delta_pct > 0.1: "throttle_late"
    4. Else: "clean" (small differences)
    """
    if abs(brake_point_delta_m) > 10:
        if brake_point_delta_m > 0:
            return (
                "braked_late",
                f"Brake {abs(brake_point_delta_m):.0f}m earlier "
                "— you're carrying too much speed into the corner",
            )
        else:
            return (
                "braked_early",
                f"Brake {abs(brake_point_delta_m):.0f}m later "
                "— you're scrubbing speed too early",
            )

    if apex_speed_delta_kph > 3:
        return (
            "apex_speed_low",
            f"Apex speed {apex_speed_delta_kph:.0f} km/h too slow "
            "— more confidence on entry",
        )

    if exit_throttle_delta_pct > 0.1:
        return (
            "throttle_late",
            f"Get on throttle earlier at exit "
            f"— {exit_throttle_delta_pct * 100:.0f}% more throttle available",
        )

    return ("clean", "Corner looks good — small differences only")


def analyze_corners(
    delta: LapDelta,
    curvature: np.ndarray,
    distance_m: np.ndarray,
    actual_brake: np.ndarray,
    theoretical_brake: np.ndarray,
    actual_speed_mps: np.ndarray,
    theoretical_speed_mps: np.ndarray,
    actual_throttle: np.ndarray,
    theoretical_throttle: np.ndarray,
    *,
    min_curvature: float = 0.005,
) -> list[CornerDelta]:
    """Analyze each corner for time loss and root cause.

    Returns a list of CornerDelta sorted by |time_loss_s| descending.
    """
    corners = _detect_corners(distance_m, curvature, min_curvature)

    if not corners:
        log.info("No corners detected (min_curvature=%.4f)", min_curvature)
        return []

    results: list[CornerDelta] = []

    for cid, (entry_idx, apex_idx, exit_idx) in enumerate(corners, start=1):
        entry_dist = float(distance_m[entry_idx])
        apex_dist = float(distance_m[apex_idx])
        exit_dist = float(distance_m[exit_idx])

        # --- Time loss for this corner ---
        # Find the indices in delta.distance_m that overlap with this corner
        d_mask = (delta.distance_m >= entry_dist) & (delta.distance_m <= exit_dist)
        d_indices = np.where(d_mask)[0]

        if len(d_indices) >= 2:
            time_loss = float(
                delta.time_delta_s[d_indices[-1]] - delta.time_delta_s[d_indices[0]]
            )
        else:
            time_loss = 0.0

        # --- Brake point delta ---
        actual_bp = _find_brake_point(actual_brake, entry_idx)
        theoretical_bp = _find_brake_point(theoretical_brake, entry_idx)

        if actual_bp is not None and theoretical_bp is not None:
            bp_delta_m = float(distance_m[actual_bp] - distance_m[theoretical_bp])
        else:
            bp_delta_m = 0.0

        # --- Apex speed delta ---
        actual_apex_speed = float(actual_speed_mps[apex_idx])
        theoretical_apex_speed = float(theoretical_speed_mps[apex_idx])
        # positive = driver was slower (theoretical faster)
        apex_speed_delta_kph = (theoretical_apex_speed - actual_apex_speed) * 3.6

        # --- Exit throttle delta ---
        # Use the last quarter of the corner as "exit zone"
        exit_zone_start = apex_idx + (exit_idx - apex_idx) // 2
        exit_zone_start = max(exit_zone_start, apex_idx + 1)
        exit_zone_end = exit_idx + 1

        if exit_zone_end > exit_zone_start:
            theo_exit_thr = float(
                np.mean(theoretical_throttle[exit_zone_start:exit_zone_end])
            )
            act_exit_thr = float(
                np.mean(actual_throttle[exit_zone_start:exit_zone_end])
            )
            exit_throttle_delta = theo_exit_thr - act_exit_thr
        else:
            exit_throttle_delta = 0.0

        # --- Classification ---
        root_cause, coaching_text = _classify_root_cause(
            bp_delta_m, apex_speed_delta_kph, exit_throttle_delta
        )

        results.append(
            CornerDelta(
                corner_id=cid,
                entry_dist_m=entry_dist,
                apex_dist_m=apex_dist,
                exit_dist_m=exit_dist,
                time_loss_s=time_loss,
                root_cause=root_cause,
                coaching_text=coaching_text,
                brake_point_delta_m=bp_delta_m,
                apex_speed_delta_kph=apex_speed_delta_kph,
                exit_throttle_delta_pct=exit_throttle_delta,
            )
        )

    # Sort by |time_loss| descending
    results.sort(key=lambda c: abs(c.time_loss_s), reverse=True)
    return results
