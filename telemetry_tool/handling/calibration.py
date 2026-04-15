"""Per-session calibration for handling detection.

Computes session-specific normalization factors so detectors don't rely
on hardcoded thresholds.  Run once at session start, results stored in
SessionContext.

Items implemented:
  D1  Per-session yaw ratio calibration
  D2  Per-session trail braking regression
  D3  Adaptive corner detection threshold
  D4  GPS-position corner matching across laps
  D5  Native GPS rate detection
  D6  Signed lateral G with direction normalization
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from telemetry_tool.handling.types import CornerWindow, SessionContext

logger = logging.getLogger(__name__)

_G = 9.80665


# ---------------------------------------------------------------------------
# D5: Detect native GPS update rate
# ---------------------------------------------------------------------------

def detect_gps_rate(time_s: np.ndarray, bearing: np.ndarray) -> float:
    """Detect native GPS rate by counting unique bearing transitions."""
    changes = np.where(np.diff(bearing) != 0)[0]
    if len(changes) < 10:
        return 25.0  # default
    dt_between = np.diff(time_s[changes])
    dt_between = dt_between[dt_between > 0]
    if len(dt_between) < 5:
        return 25.0
    return 1.0 / np.median(dt_between)


# ---------------------------------------------------------------------------
# D1: Per-session yaw ratio calibration
# ---------------------------------------------------------------------------

def calibrate_yaw_ratio(
    speed: np.ndarray,
    yaw_rate_dps: np.ndarray,
    curvature: np.ndarray,
    a_lat_g: np.ndarray,
    min_speed: float = 8.0,
    max_lat_g: float = 0.05,
) -> float:
    """Compute median yaw ratio on straights to normalize the GPS offset.

    Returns the session median (actual_yaw / expected_yaw) on straight segments.
    Typical value ~1.4-1.7 due to GPS curvature underestimation.
    """
    straight = (np.abs(a_lat_g) < max_lat_g) & (speed > min_speed)
    if straight.sum() < 200:
        logger.warning("Only %d straight samples for yaw calibration, using default", straight.sum())
        return 1.45  # fallback from 109-corner calibration

    expected = np.abs(curvature[straight] * speed[straight])
    actual = np.abs(np.deg2rad(yaw_rate_dps[straight]))
    valid = expected > 1e-5
    if valid.sum() < 50:
        return 1.45

    ratio = actual[valid] / expected[valid]
    med = float(np.nanmedian(ratio))
    logger.info("Yaw ratio calibration: median=%.3f from %d samples", med, valid.sum())
    return med


# ---------------------------------------------------------------------------
# D2: Per-session trail braking regression
# ---------------------------------------------------------------------------

def calibrate_trail_braking(
    corner_windows: list[CornerWindow],
    a_lat: np.ndarray,
    a_lon: np.ndarray,
) -> tuple[float, float]:
    """Fit overlap_fraction = slope * peak_g + intercept across session corners.

    Returns (slope, intercept). Fallback to fixed (0.60, 0.05) if not enough data.
    """
    if len(corner_windows) < 5:
        return 0.60, 0.05

    peak_gs = []
    overlaps = []
    for cw in corner_windows:
        apex_local = cw.apex_g_i - cw.start_i
        if apex_local < 5:
            continue
        entry_alon = cw.a_lon_g[:apex_local]
        entry_alat = np.abs(cw.a_lat_g[:apex_local])
        if len(entry_alon) < 5:
            continue

        braking = entry_alon < -0.1
        turning = entry_alat > 0.15
        overlap = (braking & turning).sum() / len(entry_alon)

        peak_gs.append(cw.peak_g)
        overlaps.append(overlap)

    if len(peak_gs) < 5:
        return 0.60, 0.05

    x = np.array(peak_gs)
    y = np.array(overlaps)
    # Linear fit
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])
    logger.info("Trail braking calibration: slope=%.3f, intercept=%.3f from %d corners",
                slope, intercept, len(peak_gs))
    return slope, intercept


# ---------------------------------------------------------------------------
# D3: Adaptive corner detection threshold
# ---------------------------------------------------------------------------

def calibrate_corner_threshold(a_lat_g: np.ndarray, speed: np.ndarray) -> float:
    """Compute adaptive corner G threshold from session data.

    Uses 25th percentile of peak lateral G in detected regions.
    """
    # Quick scan: find all lateral G peaks above a loose threshold
    abs_alat = np.abs(a_lat_g)
    moving = speed > 3.0
    above = abs_alat > 0.15  # very loose initial threshold
    candidate = moving & above

    if candidate.sum() < 100:
        return 0.25  # fallback

    # Find peak G in each contiguous region
    changes = np.diff(candidate.astype(int))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1
    if candidate[0]:
        starts = np.concatenate([[0], starts])
    if candidate[-1]:
        ends = np.concatenate([ends, [len(candidate) - 1]])

    peak_gs = []
    for s, e in zip(starts, ends):
        if e - s > 10:
            peak_gs.append(np.max(abs_alat[s:e]))

    if len(peak_gs) < 5:
        return 0.25

    threshold = float(np.percentile(peak_gs, 25)) * 0.5
    threshold = max(0.15, min(threshold, 0.40))  # clamp to reasonable range
    logger.info("Adaptive corner threshold: %.3f G (from %d regions)", threshold, len(peak_gs))
    return threshold


# ---------------------------------------------------------------------------
# D4: GPS-position corner matching across laps
# ---------------------------------------------------------------------------

def match_corners_across_laps(
    best_lap_corners: list[CornerWindow],
    all_lap_corners: dict[int, list[CornerWindow]],
    match_radius_m: float = 15.0,
) -> dict[int, list[int]]:
    """Match corners across laps by apex GPS position proximity.

    Returns {best_corner_idx: [matching_corner_indices_from_other_laps]}.
    Uses haversine distance on apex lat/lon.
    """
    matches: dict[int, list[int]] = {i: [] for i in range(len(best_lap_corners))}

    for ci, best_cw in enumerate(best_lap_corners):
        apex_lat = best_cw.apex_lat
        apex_lon = best_cw.apex_lon
        if apex_lat == 0 and apex_lon == 0:
            continue

        for lap_num, lap_corners in all_lap_corners.items():
            for other_cw in lap_corners:
                d = _haversine_m(apex_lat, apex_lon, other_cw.apex_lat, other_cw.apex_lon)
                if d < match_radius_m:
                    matches[ci].append(other_cw.corner_id)

    return matches


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two lat/lon points."""
    R = 6371000.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


# ---------------------------------------------------------------------------
# D6: Corner direction from lateral G sign
# ---------------------------------------------------------------------------

def compute_corner_direction(a_lat_g: np.ndarray) -> int:
    """Determine corner direction: +1 = right turn, -1 = left turn.

    Uses the sign of the median lateral G across the corner.
    """
    med = np.nanmedian(a_lat_g)
    return 1 if med > 0 else -1


# ---------------------------------------------------------------------------
# Phase segmentation: split corner by G-derivative
# ---------------------------------------------------------------------------

def segment_corner_phases(
    a_lat_g: np.ndarray,
    a_lon_g: np.ndarray,
    fs: float,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Split corner into entry/mid/exit by lateral G derivative + longitudinal G.

    Entry: from start until d(|a_lat|)/dt drops below 10% of peak (G still building)
    Mid:   from entry end until longitudinal accel crosses zero (steady-state)
    Exit:  from mid end until corner end (power-on phase)

    Returns ((entry_start, entry_end), (mid_start, mid_end), (exit_start, exit_end))
    as local indices within the corner arrays.
    """
    n = len(a_lat_g)
    if n < 20:
        third = n // 3
        return (0, third), (third, 2 * third), (2 * third, n)

    abs_alat = np.abs(a_lat_g)
    d_alat = np.gradient(abs_alat)

    # Smooth to avoid noise-triggered transitions
    kernel = max(1, int(0.2 * fs))
    d_alat_smooth = pd.Series(d_alat).rolling(kernel, center=True, min_periods=1).mean().values

    # Turn-in ends when G buildup rate drops below 10% of its entry-half peak
    half = n // 2
    peak_rate = np.max(np.abs(d_alat_smooth[:half])) if half > 2 else 1e-6
    threshold = peak_rate * 0.10

    turnin_end = n // 3  # default fallback
    for i in range(n // 6, n * 2 // 3):
        if abs(d_alat_smooth[i]) < threshold and abs_alat[i] > 0.5 * np.max(abs_alat):
            turnin_end = i
            break

    # Exit starts when longitudinal accel crosses zero (net positive = accelerating)
    exit_start = n * 2 // 3  # default fallback
    for i in range(n // 3, n):
        if a_lon_g[i] > 0.02:
            exit_start = i
            break

    turnin_end = min(turnin_end, exit_start)

    return (0, turnin_end), (turnin_end, exit_start), (exit_start, n)


# ---------------------------------------------------------------------------
# Corner window builder
# ---------------------------------------------------------------------------

def build_corner_window(
    corner_id: int,
    start_i: int,
    end_i: int,
    time_s: np.ndarray,
    dist_m: np.ndarray,
    speed_mps: np.ndarray,
    a_lat_g: np.ndarray,
    a_lon_g: np.ndarray,
    bearing_deg: np.ndarray,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    yaw_rate_dps: np.ndarray,
    curvature: np.ndarray,
) -> CornerWindow:
    """Build a CornerWindow from global session arrays and corner boundaries."""
    seg = slice(start_i, end_i)
    seg_alat = a_lat_g[seg]
    seg_speed = speed_mps[seg]
    abs_alat = np.abs(seg_alat)

    apex_g_local = int(np.argmax(abs_alat))
    apex_speed_local = int(np.argmin(seg_speed))
    peak_g = float(np.max(abs_alat))

    # D6: corner direction
    direction = compute_corner_direction(seg_alat)

    # Phase segmentation
    entry, mid, exit_ = segment_corner_phases(seg_alat, a_lon_g[seg], 25.0)

    # Apex GPS position for D4 matching
    apex_global = start_i + apex_g_local
    apex_lat = float(lat_deg[apex_global]) if apex_global < len(lat_deg) else 0.0
    apex_lon = float(lon_deg[apex_global]) if apex_global < len(lon_deg) else 0.0

    return CornerWindow(
        corner_id=corner_id,
        start_i=start_i,
        end_i=end_i,
        apex_g_i=start_i + apex_g_local,
        apex_speed_i=start_i + apex_speed_local,
        time_s=time_s[seg],
        dist_m=dist_m[seg],
        speed_mps=seg_speed,
        a_lat_g=seg_alat,
        a_lon_g=a_lon_g[seg],
        bearing_deg=bearing_deg[seg],
        lat_deg=lat_deg[seg],
        lon_deg=lon_deg[seg],
        yaw_rate_dps=yaw_rate_dps[seg],
        curvature=curvature[seg],
        peak_g=peak_g,
        corner_len_m=float(dist_m[end_i - 1] - dist_m[start_i]) if end_i > start_i else 0.0,
        corner_dur_s=float(time_s[end_i - 1] - time_s[start_i]) if end_i > start_i else 0.0,
        direction=direction,
        phase_entry=entry,
        phase_mid=mid,
        phase_exit=exit_,
        apex_lat=apex_lat,
        apex_lon=apex_lon,
    )


# ---------------------------------------------------------------------------
# Top-level calibration
# ---------------------------------------------------------------------------

def calibrate_session(
    time_s: np.ndarray,
    speed: np.ndarray,
    a_lat_g: np.ndarray,
    a_lon_g: np.ndarray,
    bearing: np.ndarray,
    yaw_rate_dps: np.ndarray,
    curvature: np.ndarray,
    corner_windows: list[CornerWindow],
    wheelbase_m: float = 1.0,
    vehicle_class: str = "kart",
) -> SessionContext:
    """Run all calibration steps and return a populated SessionContext."""

    # D5: detect native GPS rate
    native_hz = detect_gps_rate(time_s, bearing)

    # D1: yaw ratio offset
    yaw_offset = calibrate_yaw_ratio(speed, yaw_rate_dps, curvature, a_lat_g)

    # D2: trail braking regression
    tb_slope, tb_intercept = calibrate_trail_braking(corner_windows, a_lat_g, a_lon_g)

    # D3: adaptive corner threshold
    g_thr = calibrate_corner_threshold(a_lat_g, speed)

    # Friction estimate: 95th percentile of |lateral G| at speed
    moving = speed > 5.0
    if moving.sum() > 100:
        friction_est = float(np.percentile(np.abs(a_lat_g[moving]), 95))
    else:
        friction_est = 1.0

    return SessionContext(
        yaw_ratio_offset=yaw_offset,
        trail_braking_slope=tb_slope,
        trail_braking_intercept=tb_intercept,
        corner_g_threshold=g_thr,
        friction_estimate_g=friction_est,
        native_gps_hz=native_hz,
        all_corners=corner_windows,
        wheelbase_m=wheelbase_m,
        vehicle_class=vehicle_class,
    )
