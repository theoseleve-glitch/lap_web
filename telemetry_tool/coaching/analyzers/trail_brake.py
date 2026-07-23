"""Trail brake 4-block analyzer — detects braking phases and trail-braking overlap."""
from __future__ import annotations

import numpy as np
import pandas as pd

from coaching.models import BrakingBlock, TrailBrakeAssessment

# Thresholds
_BRAKE_THRESHOLD = 5.0       # % to consider brake applied
_STEER_THRESHOLD = 5.0       # degrees to consider turning
_THROTTLE_THRESHOLD = 5.0    # % to consider throttle applied
_DECEL_THRESHOLD = -1.0      # m/s2 to consider braking (accel fallback)
_LAT_THRESHOLD = 2.0         # m/s2 to consider cornering (accel fallback)


def analyze_trail_braking(corner: dict, lap: pd.DataFrame) -> TrailBrakeAssessment:
    """Analyze braking phases for a single corner.

    Tier 1: Uses Throttle/Brake/Steering channels if available.
    Tier 2/3: Falls back to longitudinal/lateral acceleration.
    """
    corner_id = corner["corner_id"]
    s_start = corner["s_start"]
    s_end = corner["s_end"]

    dist = lap["Distance (m)"].values
    speed = lap["Speed (m/s)"].values
    time_s = lap["Time (s)"].values if "Time (s)" in lap.columns else np.arange(len(dist)) * 0.01

    mask = (dist >= s_start) & (dist <= s_end)
    seg_dist = dist[mask]
    seg_speed = speed[mask]
    seg_time = time_s[mask]

    if len(seg_dist) < 4:
        return _empty_assessment(corner_id)

    has_pedals = all(c in lap.columns for c in ("Throttle (%)", "Brake (%)", "Steering angle (deg)"))

    if has_pedals:
        throttle = lap["Throttle (%)"].values[mask]
        brake = lap["Brake (%)"].values[mask]
        steer = np.abs(lap["Steering angle (deg)"].values[mask])
        braking = brake > _BRAKE_THRESHOLD
        turning = steer > _STEER_THRESHOLD
        throttling = throttle > _THROTTLE_THRESHOLD
    else:
        # Accel fallback
        lon = lap.get("Longitudinal acceleration (m/s2)")
        lat = lap.get("Lateral acceleration (m/s2)")
        if lon is None or lat is None:
            return _empty_assessment(corner_id)
        lon_seg = lon.values[mask]
        lat_seg = np.abs(lat.values[mask])
        braking = lon_seg < _DECEL_THRESHOLD
        turning = lat_seg > _LAT_THRESHOLD
        throttling = lon_seg > 1.0
        brake = np.abs(np.minimum(lon_seg, 0)) * 10  # synthetic brake %
        steer = lat_seg * 5  # synthetic steer deg

    # Classify each point into one of 4 blocks
    overlap = braking & turning
    has_trail = bool(np.any(overlap))

    blocks = _classify_blocks(seg_dist, seg_time, seg_speed, braking, turning, throttling, brake)

    # Compute overlap distance
    overlap_indices = np.where(overlap)[0]
    actual_overlap_m = 0.0
    if len(overlap_indices) >= 2:
        actual_overlap_m = float(seg_dist[overlap_indices[-1]] - seg_dist[overlap_indices[0]])

    # Theoretical overlap: ~30% of corner length is a good target
    corner_length = s_end - s_start
    theoretical_overlap_m = corner_length * 0.30

    # Time loss from no trail: estimated as overlap_deficit / avg_speed * 0.5
    if has_trail:
        overlap_deficit = max(theoretical_overlap_m - actual_overlap_m, 0)
    else:
        overlap_deficit = theoretical_overlap_m
    avg_speed = float(np.mean(seg_speed)) if len(seg_speed) > 0 else 15.0
    time_loss = overlap_deficit / max(avg_speed, 1.0) * 0.5

    # Release linearity: how smoothly brake is released in the trail zone
    release_linearity = _compute_release_linearity(brake[overlap] if has_pedals else brake[braking])

    # Overall score
    overlap_ratio = min(actual_overlap_m / max(theoretical_overlap_m, 1.0), 1.0)
    score = 100.0 * overlap_ratio * release_linearity

    primary_issue = None if has_trail else "no_trail_braking"

    return TrailBrakeAssessment(
        corner_id=corner_id,
        blocks=blocks,
        overall_score=min(max(score, 0.0), 100.0),
        has_trail_braking=has_trail,
        theoretical_overlap_m=theoretical_overlap_m,
        actual_overlap_m=actual_overlap_m,
        time_loss_from_no_trail_s=time_loss,
        primary_issue=primary_issue,
    )


def _classify_blocks(
    dist: np.ndarray, time: np.ndarray, speed: np.ndarray,
    braking: np.ndarray, turning: np.ndarray, throttling: np.ndarray,
    brake_pct: np.ndarray,
) -> list[BrakingBlock]:
    """Classify corner segment into 4 braking blocks."""
    n = len(dist)
    blocks: list[BrakingBlock] = []

    # Block 1: throttle→brake transition (start until braking begins)
    brake_start = np.argmax(braking) if np.any(braking) else n
    if brake_start > 0:
        blocks.append(BrakingBlock(
            block_id=1, name="throttle_to_brake",
            s_start=float(dist[0]), s_end=float(dist[min(brake_start, n - 1)]),
            duration_s=float(time[min(brake_start, n - 1)] - time[0]),
            transition_duration_s=float(time[min(brake_start, n - 1)] - time[0]),
        ))

    # Block 2: straight-line braking (braking but not turning)
    straight_brake = braking & ~turning
    sb_indices = np.where(straight_brake)[0]
    if len(sb_indices) > 0:
        peak_decel = float(np.min(np.diff(speed[:len(sb_indices) + 1]))) if len(sb_indices) > 1 else None
        blocks.append(BrakingBlock(
            block_id=2, name="straight_line_braking",
            s_start=float(dist[sb_indices[0]]),
            s_end=float(dist[sb_indices[-1]]),
            duration_s=float(time[sb_indices[-1]] - time[sb_indices[0]]),
            peak_decel_mps2=peak_decel,
        ))

    # Block 3: trail-brake (braking + turning overlap)
    overlap = braking & turning
    ov_indices = np.where(overlap)[0]
    if len(ov_indices) > 0:
        trail_brake_pct = brake_pct[ov_indices]
        release_rate = float(np.mean(np.diff(trail_brake_pct))) if len(trail_brake_pct) > 1 else 0.0
        linearity = _compute_release_linearity(trail_brake_pct)
        blocks.append(BrakingBlock(
            block_id=3, name="trail_brake",
            s_start=float(dist[ov_indices[0]]),
            s_end=float(dist[ov_indices[-1]]),
            duration_s=float(time[ov_indices[-1]] - time[ov_indices[0]]),
            overlap_m=float(dist[ov_indices[-1]] - dist[ov_indices[0]]),
            trail_pct_at_turnin=float(trail_brake_pct[0]) if len(trail_brake_pct) > 0 else None,
            release_rate_mps3=release_rate,
            release_linearity=linearity,
        ))

    # Block 4: brake→throttle transition
    if np.any(throttling):
        throttle_start = np.argmax(throttling)
        brake_end_after_turn = n - 1
        for idx in range(n - 1, -1, -1):
            if braking[idx]:
                brake_end_after_turn = idx
                break
        trans_start = min(brake_end_after_turn, throttle_start)
        blocks.append(BrakingBlock(
            block_id=4, name="brake_to_throttle",
            s_start=float(dist[trans_start]),
            s_end=float(dist[min(throttle_start + 1, n - 1)]),
            duration_s=float(time[min(throttle_start + 1, n - 1)] - time[trans_start]),
            transition_duration_s=float(time[min(throttle_start + 1, n - 1)] - time[trans_start]),
        ))

    # Ensure exactly 4 blocks (pad if needed)
    while len(blocks) < 4:
        blocks.append(BrakingBlock(
            block_id=len(blocks) + 1, name="not_detected",
            s_start=float(dist[0]), s_end=float(dist[0]),
            duration_s=0.0,
        ))

    return blocks[:4]


def _compute_release_linearity(brake_values: np.ndarray) -> float:
    """Compute how linear the brake release is (1.0 = perfectly linear, 0.0 = step)."""
    if len(brake_values) < 3:
        return 0.5
    # Compare actual release profile to linear regression
    x = np.arange(len(brake_values), dtype=float)
    coeffs = np.polyfit(x, brake_values, 1)
    predicted = np.polyval(coeffs, x)
    residuals = brake_values - predicted
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((brake_values - np.mean(brake_values)) ** 2))
    if ss_tot < 1e-6:
        return 1.0
    r_squared = max(1.0 - ss_res / ss_tot, 0.0)
    return r_squared


def _empty_assessment(corner_id: int) -> TrailBrakeAssessment:
    """Return an assessment when data is insufficient."""
    return TrailBrakeAssessment(
        corner_id=corner_id,
        blocks=[
            BrakingBlock(i, "insufficient_data", 0, 0, 0)
            for i in range(1, 5)
        ],
        overall_score=0.0,
        has_trail_braking=False,
        theoretical_overlap_m=0.0,
        actual_overlap_m=0.0,
        time_loss_from_no_trail_s=0.0,
        primary_issue="insufficient_data",
    )
