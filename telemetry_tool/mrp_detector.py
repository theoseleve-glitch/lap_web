"""MRP (Maximum Rotation Point) detector with corner event timeline.

Finds the point of peak direction change in each corner and builds an
event timeline: brake, turn-in, MRP, throttle, track-out.

Public API
~~~~~~~~~~
- ``detect_mrp(section, distances, speeds, ...)`` -> CornerEvents
- ``detect_all_mrp(sections, df)`` -> dict[int, CornerEvents]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from track_decomposition import TrackSection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds — aligned with corner_analysis.py
# ---------------------------------------------------------------------------

_BRAKING_THRESHOLD_MPS2: float = -1.0   # a_long below this = braking
_THROTTLE_THRESHOLD_MPS2: float = 0.5   # a_long above this = accelerating
_LATERAL_THRESHOLD_MPS2: float = 2.94   # ~0.3g for turn-in detection
_MRP_PROXIMITY_M: float = 5.0           # yaw vs speed candidates within this → average

# Column names (pipeline conventions)
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_HEADING = "Heading (rad)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_ACCEL_LAT = "accel_lat_mps2"
_COL_STEERING = "Steering (deg)"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CornerEvents:
    """Event timeline for a single corner."""
    corner_id: int
    brake_point_m: float | None
    turn_in_m: float
    trail_brake_end_m: float | None
    mrp_m: float
    mrp_speed_mps: float
    mrp_yaw_rate: float
    throttle_application_m: float | None
    track_out_m: float
    geometric_apex_m: float
    mrp_apex_delta_m: float  # positive = late rotation


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_yaw_rate(headings: np.ndarray, distances: np.ndarray) -> np.ndarray:
    """Compute yaw rate as heading change per metre (rad/m)."""
    dh = np.diff(headings)
    # Wrap to [-pi, pi]
    dh = (dh + np.pi) % (2 * np.pi) - np.pi
    dd = np.diff(distances)
    dd = np.where(np.abs(dd) > 1e-9, dd, 1e-9)
    yaw_rate = dh / dd
    # Pad to same length
    return np.concatenate([yaw_rate, [yaw_rate[-1]]])


def _slice_indices(distances: np.ndarray, s_start: float, s_end: float):
    """Return boolean mask for distances within [s_start, s_end]."""
    return (distances >= s_start) & (distances <= s_end)


def _find_brake_point(
    distances: np.ndarray,
    accel_long: np.ndarray,
    s_start: float,
    s_end: float,
    threshold: float = _BRAKING_THRESHOLD_MPS2,
) -> float | None:
    """Find first point where accel_long drops below threshold in corner region.

    Searches from 50m before s_start up to midpoint of corner.
    """
    search_start = s_start - 50.0
    search_end = s_start + (s_end - s_start) * 0.5
    for i in range(len(distances)):
        if distances[i] < search_start:
            continue
        if distances[i] > search_end:
            break
        if np.isfinite(accel_long[i]) and accel_long[i] < threshold:
            return float(distances[i])
    return None


def _find_throttle_application(
    distances: np.ndarray,
    accel_long: np.ndarray,
    after_m: float,
    threshold: float = _THROTTLE_THRESHOLD_MPS2,
) -> float | None:
    """Find first point after after_m where accel_long exceeds threshold."""
    for i in range(len(distances)):
        if distances[i] < after_m:
            continue
        if np.isfinite(accel_long[i]) and accel_long[i] > threshold:
            return float(distances[i])
    return None


def _find_turn_in(
    distances: np.ndarray,
    accel_lat: np.ndarray | None,
    speeds: np.ndarray,
    s_start: float,
    s_end: float,
    threshold: float = _LATERAL_THRESHOLD_MPS2,
) -> float:
    """Find turn-in point from lateral acceleration or speed drop."""
    mask = _slice_indices(distances, s_start, s_end)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return s_start

    if accel_lat is not None:
        for i in idx:
            if np.isfinite(accel_lat[i]) and abs(accel_lat[i]) > threshold:
                return float(distances[i])

    # Fallback: first point where speed starts decreasing noticeably
    d_seg = distances[idx]
    s_seg = speeds[idx]
    if len(s_seg) > 1:
        speed_diff = np.diff(s_seg)
        for j in range(len(speed_diff)):
            if speed_diff[j] < -0.5:
                return float(d_seg[j])

    return float(distances[idx[0]])


def _find_trail_brake_end(
    distances: np.ndarray,
    accel_long: np.ndarray | None,
    accel_lat: np.ndarray | None,
    after_m: float,
    s_end: float,
) -> float | None:
    """Find where braking tapers off while lateral g is still high."""
    if accel_long is None:
        return None

    for i in range(len(distances)):
        if distances[i] < after_m or distances[i] > s_end:
            continue
        if (np.isfinite(accel_long[i])
                and accel_long[i] > _BRAKING_THRESHOLD_MPS2
                and accel_long[i] < _THROTTLE_THRESHOLD_MPS2):
            # Check lateral g is still meaningful
            if accel_lat is not None and abs(accel_lat[i]) > _LATERAL_THRESHOLD_MPS2 * 0.5:
                return float(distances[i])
            elif accel_lat is None:
                return float(distances[i])
    return None


def _find_track_out(
    distances: np.ndarray,
    accel_lat: np.ndarray | None,
    speeds: np.ndarray,
    s_start: float,
    s_end: float,
    threshold: float = _LATERAL_THRESHOLD_MPS2,
) -> float:
    """Find track-out point (lateral g drops below threshold from the end)."""
    mask = _slice_indices(distances, s_start, s_end)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return s_end

    if accel_lat is not None:
        # Search backwards from end
        for i in reversed(idx):
            if np.isfinite(accel_lat[i]) and abs(accel_lat[i]) > threshold:
                return float(distances[min(i + 1, len(distances) - 1)])

    # Fallback: where speed is increasing near end
    d_seg = distances[idx]
    s_seg = speeds[idx]
    if len(s_seg) > 2:
        speed_diff = np.diff(s_seg)
        for j in range(len(speed_diff) - 1, -1, -1):
            if speed_diff[j] < 0.5:
                return float(d_seg[min(j + 1, len(d_seg) - 1)])

    return float(distances[idx[-1]])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_mrp(
    section: TrackSection,
    distances: np.ndarray,
    speeds: np.ndarray,
    headings: np.ndarray | None = None,
    accel_long: np.ndarray | None = None,
    accel_lat: np.ndarray | None = None,
    steering: np.ndarray | None = None,
) -> CornerEvents:
    """Detect MRP and build event timeline for a single corner section.

    Parameters
    ----------
    section : TrackSection with s_start, s_end, geometric_apex.
    distances : monotonic distance array (m).
    speeds : speed array (m/s).
    headings : heading array (radians), optional.
    accel_long : longitudinal acceleration (m/s^2), optional.
    accel_lat : lateral acceleration (m/s^2), optional.
    steering : steering angle (degrees), optional.
    """
    s_start = section.s_start
    s_end = section.s_end
    geometric_apex = section.geometric_apex if section.geometric_apex is not None else (s_start + s_end) / 2.0

    mask = _slice_indices(distances, s_start, s_end)
    idx = np.where(mask)[0]

    if len(idx) == 0:
        # No data in corner — return defaults at geometric apex
        return CornerEvents(
            corner_id=section.section_id,
            brake_point_m=None,
            turn_in_m=s_start,
            trail_brake_end_m=None,
            mrp_m=geometric_apex,
            mrp_speed_mps=0.0,
            mrp_yaw_rate=0.0,
            throttle_application_m=None,
            track_out_m=s_end,
            geometric_apex_m=geometric_apex,
            mrp_apex_delta_m=0.0,
        )

    d_seg = distances[idx]
    s_seg = speeds[idx]

    # --- MRP detection ---
    yaw_mrp = None
    yaw_rate_at_mrp = 0.0

    if headings is not None:
        yaw_rate = _compute_yaw_rate(headings, distances)
        yaw_seg = np.abs(yaw_rate[idx])
        peak_idx = int(np.argmax(yaw_seg))
        yaw_mrp = float(d_seg[peak_idx])
        yaw_rate_at_mrp = float(yaw_rate[idx[peak_idx]])

    # Speed-based MRP candidate: minimum speed in corner
    speed_min_idx = int(np.argmin(s_seg))
    speed_mrp = float(d_seg[speed_min_idx])

    # Combine candidates
    if yaw_mrp is not None:
        if abs(yaw_mrp - speed_mrp) <= _MRP_PROXIMITY_M:
            mrp_m = (yaw_mrp + speed_mrp) / 2.0
        else:
            mrp_m = yaw_mrp  # yaw rate takes priority
    else:
        mrp_m = speed_mrp

    # Steering confirmation (nudge towards steering peak if available)
    if steering is not None:
        steer_seg = np.abs(steering[idx])
        steer_peak_idx = int(np.argmax(steer_seg))
        steer_mrp = float(d_seg[steer_peak_idx])
        # If steering peak is within 5m, average with current MRP
        if abs(steer_mrp - mrp_m) <= _MRP_PROXIMITY_M:
            mrp_m = (mrp_m + steer_mrp) / 2.0

    # Clamp MRP to corner bounds
    mrp_m = max(s_start, min(s_end, mrp_m))

    # MRP speed: interpolate
    mrp_speed = float(np.interp(mrp_m, d_seg, s_seg))

    # --- Event detection ---
    brake_point = None
    trail_brake_end = None
    throttle_app = None

    if accel_long is not None:
        brake_point = _find_brake_point(distances, accel_long, s_start, s_end)
        throttle_app = _find_throttle_application(distances, accel_long, mrp_m)
        if brake_point is not None:
            trail_brake_end = _find_trail_brake_end(
                distances, accel_long, accel_lat,
                after_m=brake_point, s_end=s_end,
            )

    turn_in_m = _find_turn_in(distances, accel_lat, speeds, s_start, s_end)
    track_out_m = _find_track_out(distances, accel_lat, speeds, s_start, s_end)

    # Ensure ordering: turn_in <= mrp <= track_out
    turn_in_m = min(turn_in_m, mrp_m)
    track_out_m = max(track_out_m, mrp_m)

    # Ensure brake < turn_in if both exist
    if brake_point is not None and brake_point > turn_in_m:
        brake_point = turn_in_m

    # Ensure throttle > mrp if exists
    if throttle_app is not None and throttle_app < mrp_m:
        throttle_app = mrp_m

    # Ensure throttle <= track_out if both exist
    if throttle_app is not None and throttle_app > track_out_m:
        track_out_m = throttle_app

    mrp_apex_delta = mrp_m - geometric_apex

    return CornerEvents(
        corner_id=section.section_id,
        brake_point_m=brake_point,
        turn_in_m=turn_in_m,
        trail_brake_end_m=trail_brake_end,
        mrp_m=mrp_m,
        mrp_speed_mps=mrp_speed,
        mrp_yaw_rate=yaw_rate_at_mrp,
        throttle_application_m=throttle_app,
        track_out_m=track_out_m,
        geometric_apex_m=geometric_apex,
        mrp_apex_delta_m=mrp_apex_delta,
    )


def detect_all_mrp(
    sections: list[TrackSection],
    df: pd.DataFrame,
) -> dict[int, CornerEvents]:
    """Detect MRP for all corner sections in a DataFrame.

    Parameters
    ----------
    sections : list of TrackSection from track decomposition.
    df : DataFrame with at least Distance (m) and Speed (m/s).

    Returns
    -------
    dict mapping section_id to CornerEvents (corners only).
    """
    if _COL_DIST not in df.columns or _COL_SPEED not in df.columns:
        logger.warning("Missing required columns for MRP detection")
        return {}

    distances = df[_COL_DIST].to_numpy(dtype=float)
    speeds = df[_COL_SPEED].to_numpy(dtype=float)

    headings = df[_COL_HEADING].to_numpy(dtype=float) if _COL_HEADING in df.columns else None
    accel_long = df[_COL_ACCEL_LONG].to_numpy(dtype=float) if _COL_ACCEL_LONG in df.columns else None
    accel_lat = df[_COL_ACCEL_LAT].to_numpy(dtype=float) if _COL_ACCEL_LAT in df.columns else None
    steering = df[_COL_STEERING].to_numpy(dtype=float) if _COL_STEERING in df.columns else None

    results: dict[int, CornerEvents] = {}
    for sec in sections:
        if sec.section_type != "corner":
            continue
        try:
            events = detect_mrp(
                sec, distances, speeds,
                headings=headings, accel_long=accel_long,
                accel_lat=accel_lat, steering=steering,
            )
            results[sec.section_id] = events
        except Exception:
            logger.exception("MRP detection failed for section %d", sec.section_id)

    return results
