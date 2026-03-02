"""
controls_physics.py
-------------------
Tier 2 controls-physics module for motorsport telemetry analysis.

Provides brake, throttle, steering, and RPM/power analysis when controls
data is available (iRacing, ACC, MoTeC formats).  All functions operate on
distance-based arrays and are designed to degrade gracefully when columns
are missing or data quality is poor.

Public API
~~~~~~~~~~
Brake analysis:
    ``detect_brake_points``
    ``measure_trail_braking``
    ``score_brake_modulation``

Throttle analysis:
    ``measure_throttle_application``
    ``detect_coasting_zones``

Steering analysis:
    ``compute_steering_smoothness``
    ``count_corrections``

RPM / Power curve:
    ``fit_power_curve``
    ``score_shift_quality``

Corner master function:
    ``analyze_corners_with_controls``
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column name constants (canonical + fallback)
# ---------------------------------------------------------------------------

_COL_DIST = "Distance (m)"
_COL_DIST_INT = "distance_m"
_COL_SPEED = "Speed (m/s)"
_COL_SPEED_INT = "speed_mps"
_COL_BRAKE = "brake_pct"
_COL_THROTTLE = "throttle_pct"
_COL_STEERING = "steering_angle_deg"
_COL_RPM = "rpm"
_COL_GEAR = "gear"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_ACCEL_LONG_ALT = "Acceleration X (m/s2)"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_column(df: pd.DataFrame, primary: str, fallback: str | None = None) -> str | None:
    """Return the column name present in *df*, preferring *primary*."""
    if primary in df.columns:
        return primary
    if fallback is not None and fallback in df.columns:
        return fallback
    return None


def _safe_array(arr: np.ndarray) -> np.ndarray:
    """Replace NaN/Inf with 0 and ensure float64."""
    out = np.asarray(arr, dtype=np.float64)
    out = np.where(np.isfinite(out), out, 0.0)
    return out


def _corner_mask(distances: np.ndarray, entry_m: float, exit_m: float) -> np.ndarray:
    """Boolean mask for points inside a corner zone."""
    return (distances >= entry_m) & (distances <= exit_m)


# ========================================================================
# BRAKE ANALYSIS
# ========================================================================


def detect_brake_points(
    distances: np.ndarray,
    brake_pct: np.ndarray,
    threshold: float = 5.0,
) -> list[float]:
    """Return distances where braking begins (crossing *threshold* upward).

    Parameters
    ----------
    distances : np.ndarray
        Monotonically increasing distance array (metres).
    brake_pct : np.ndarray
        Brake percentage (0-100).
    threshold : float
        Minimum brake % to count as "braking".

    Returns
    -------
    list[float]
        Distances at which braking initiates.
    """
    distances = _safe_array(distances)
    brake_pct = _safe_array(brake_pct)
    if len(distances) < 2 or len(brake_pct) < 2:
        return []

    above = brake_pct >= threshold
    # Rising edge: previous sample below threshold, current at or above
    edges = np.diff(above.astype(np.int8))
    indices = np.where(edges == 1)[0] + 1  # index of first "above" sample
    return [float(distances[i]) for i in indices if i < len(distances)]


def measure_trail_braking(
    distances: np.ndarray,
    brake_pct: np.ndarray,
    steering_deg: np.ndarray,
    corners: list[dict],
) -> list[dict]:
    """Compute trail-braking metrics for each corner.

    Trail braking is defined as simultaneous braking (>5 %) and steering
    (absolute steering angle > 10 deg).

    Returns
    -------
    list[dict]
        One dict per corner with keys:
        ``corner_id``, ``trail_brake_pct``, ``trail_brake_duration_m``,
        ``peak_brake_in_turn``.
    """
    distances = _safe_array(distances)
    brake_pct = _safe_array(brake_pct)
    steering_deg = _safe_array(steering_deg)
    results: list[dict] = []

    for corner in corners:
        cid = corner.get("corner_id", 0)
        entry = corner.get("entry_m", 0.0)
        exit_ = corner.get("exit_m", 0.0)
        mask = _corner_mask(distances, entry, exit_)
        n_in = int(np.sum(mask))
        if n_in == 0:
            results.append({
                "corner_id": cid,
                "trail_brake_pct": 0.0,
                "trail_brake_duration_m": 0.0,
                "peak_brake_in_turn": 0.0,
            })
            continue

        brk = brake_pct[mask]
        steer = np.abs(steering_deg[mask])
        dist_in = distances[mask]

        trail_mask = (brk > 5.0) & (steer > 10.0)
        trail_count = int(np.sum(trail_mask))
        trail_pct = 100.0 * trail_count / n_in if n_in > 0 else 0.0

        if trail_count > 0:
            trail_distances = dist_in[trail_mask]
            trail_dur = float(trail_distances[-1] - trail_distances[0])
        else:
            trail_dur = 0.0

        steering_mask = steer > 10.0
        if np.any(steering_mask):
            peak_brk = float(np.max(brk[steering_mask]))
        else:
            peak_brk = 0.0

        results.append({
            "corner_id": cid,
            "trail_brake_pct": round(trail_pct, 2),
            "trail_brake_duration_m": round(trail_dur, 2),
            "peak_brake_in_turn": round(peak_brk, 2),
        })

    return results


def score_brake_modulation(
    laps_brake_profiles: list[dict],
    corners: list[dict],
) -> float:
    """Score brake consistency across laps at each corner (0-1).

    Each element of *laps_brake_profiles* must have keys ``distances``
    and ``brake_pct`` (numpy arrays or lists).  The score is computed as
    1 - mean normalised std of brake % inside each corner zone.
    """
    if not laps_brake_profiles or not corners:
        return 0.0

    corner_scores: list[float] = []
    for corner in corners:
        entry = corner.get("entry_m", 0.0)
        exit_ = corner.get("exit_m", 0.0)
        per_lap_means: list[float] = []

        for profile in laps_brake_profiles:
            d = _safe_array(np.asarray(profile.get("distances", [])))
            b = _safe_array(np.asarray(profile.get("brake_pct", [])))
            if len(d) == 0:
                continue
            mask = _corner_mask(d, entry, exit_)
            if np.any(mask):
                per_lap_means.append(float(np.mean(b[mask])))

        if len(per_lap_means) < 2:
            continue

        arr = np.array(per_lap_means)
        mean_val = np.mean(arr)
        if mean_val < 1e-6:
            corner_scores.append(1.0)
        else:
            cv = float(np.std(arr) / mean_val)
            corner_scores.append(max(0.0, 1.0 - cv))

    if not corner_scores:
        return 0.0
    return float(np.clip(np.mean(corner_scores), 0.0, 1.0))


# ========================================================================
# THROTTLE ANALYSIS
# ========================================================================


def measure_throttle_application(
    distances: np.ndarray,
    throttle_pct: np.ndarray,
    corners: list[dict],
) -> list[dict]:
    """Compute throttle-application metrics for each corner.

    Returns
    -------
    list[dict]
        Per-corner dict with ``corner_id``, ``exit_application_rate``
        (pct/m) and ``hesitation_zones`` (list of {start_m, end_m}).
    """
    distances = _safe_array(distances)
    throttle_pct = _safe_array(throttle_pct)
    results: list[dict] = []

    for corner in corners:
        cid = corner.get("corner_id", 0)
        apex = corner.get("apex_m", 0.0)
        exit_ = corner.get("exit_m", 0.0)

        # Exit zone: apex -> exit
        exit_mask = (distances >= apex) & (distances <= exit_)
        n_exit = int(np.sum(exit_mask))

        if n_exit < 2:
            results.append({
                "corner_id": cid,
                "exit_application_rate": 0.0,
                "hesitation_zones": [],
            })
            continue

        d_exit = distances[exit_mask]
        t_exit = throttle_pct[exit_mask]

        # Linear regression for application rate (pct / m)
        span = float(d_exit[-1] - d_exit[0])
        if span > 0:
            rate = float(t_exit[-1] - t_exit[0]) / span
        else:
            rate = 0.0

        # Hesitation zones: throttle < 20% within the corner zone
        entry = corner.get("entry_m", 0.0)
        full_mask = _corner_mask(distances, entry, exit_)
        d_full = distances[full_mask]
        t_full = throttle_pct[full_mask]
        hesitation: list[dict] = []

        if len(d_full) > 0:
            low_throttle = t_full < 20.0
            # Group contiguous low-throttle samples
            changes = np.diff(low_throttle.astype(np.int8))
            starts = np.where(changes == 1)[0] + 1
            ends = np.where(changes == -1)[0] + 1

            # Handle edge cases: starts at beginning or ends at end
            if low_throttle[0]:
                starts = np.concatenate([[0], starts])
            if low_throttle[-1]:
                ends = np.concatenate([ends, [len(d_full)]])

            for s, e in zip(starts, ends):
                if s < len(d_full) and e <= len(d_full) and e > s:
                    hesitation.append({
                        "start_m": round(float(d_full[s]), 2),
                        "end_m": round(float(d_full[min(e, len(d_full)) - 1]), 2),
                    })

        results.append({
            "corner_id": cid,
            "exit_application_rate": round(rate, 4),
            "hesitation_zones": hesitation,
        })

    return results


def detect_coasting_zones(
    distances: np.ndarray,
    throttle_pct: np.ndarray,
    brake_pct: np.ndarray,
) -> list[dict]:
    """Find zones where throttle == 0 AND brake == 0 (wasted time).

    Returns
    -------
    list[dict]
        Each dict has ``start_m``, ``end_m``, ``duration_m``.
    """
    distances = _safe_array(distances)
    throttle_pct = _safe_array(throttle_pct)
    brake_pct = _safe_array(brake_pct)

    if len(distances) < 2:
        return []

    coasting = (throttle_pct < 1.0) & (brake_pct < 1.0)
    zones: list[dict] = []

    changes = np.diff(coasting.astype(np.int8))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1

    if coasting[0]:
        starts = np.concatenate([[0], starts])
    if coasting[-1]:
        ends = np.concatenate([ends, [len(distances)]])

    for s, e in zip(starts, ends):
        if s < len(distances) and e <= len(distances) and e > s:
            start_m = float(distances[s])
            end_m = float(distances[min(e, len(distances)) - 1])
            dur = end_m - start_m
            if dur > 0.5:  # ignore sub-half-metre micro-zones
                zones.append({
                    "start_m": round(start_m, 2),
                    "end_m": round(end_m, 2),
                    "duration_m": round(dur, 2),
                })

    return zones


# ========================================================================
# STEERING ANALYSIS
# ========================================================================


def compute_steering_smoothness(
    distances: np.ndarray,
    steering_deg: np.ndarray,
) -> float:
    """Score 0-1 for steering smoothness.

    Uses the ratio of high-frequency content (std of 2nd derivative)
    to the overall signal amplitude.  A perfectly smooth sine wave scores
    near 1.0; noisy / jerky input scores lower.
    """
    distances = _safe_array(distances)
    steering_deg = _safe_array(steering_deg)

    if len(steering_deg) < 5:
        return 0.0

    # Compute spacing (use median to be robust to slight irregularity)
    ds = np.diff(distances)
    ds_median = np.median(ds)
    if ds_median < 1e-9:
        return 0.0

    # First and second derivatives via finite differences
    d1 = np.gradient(steering_deg, ds_median)
    d2 = np.gradient(d1, ds_median)

    std_d2 = float(np.std(d2))
    amplitude = float(np.ptp(steering_deg))  # peak-to-peak

    if amplitude < 1e-6:
        # No steering input at all -> considered smooth
        return 1.0

    # Normalise: lower jerk relative to amplitude = smoother
    # Scale factor chosen so a clean sine wave scores ~0.95
    jerk_ratio = std_d2 / (amplitude / (ds_median ** 2))
    # A pure sine of amplitude A, period L:
    #   d2 ~ A*(2pi/L)^2 * sin, std(d2) ~ A*(2pi/L)^2 / sqrt(2)
    #   jerk_ratio ~ 1/sqrt(2) ~ 0.707
    # Map: 0.707 -> 0.95, higher -> lower
    score = max(0.0, 1.0 - 0.07 * jerk_ratio)
    return float(np.clip(score, 0.0, 1.0))


def count_corrections(
    distances: np.ndarray,
    steering_deg: np.ndarray,
    corners: list[dict],
) -> list[dict]:
    """Per corner, count steering reversals (sign changes in steering rate).

    Returns
    -------
    list[dict]
        ``corner_id``, ``correction_count``, ``severity`` (mean absolute
        rate at reversal points, deg/m).
    """
    distances = _safe_array(distances)
    steering_deg = _safe_array(steering_deg)
    results: list[dict] = []

    ds = np.diff(distances)
    ds = np.where(ds > 0, ds, 1e-6)  # avoid division by zero
    steer_rate = np.diff(steering_deg) / ds

    for corner in corners:
        cid = corner.get("corner_id", 0)
        entry = corner.get("entry_m", 0.0)
        exit_ = corner.get("exit_m", 0.0)

        # Rate array has length n-1; use midpoints for distance mapping
        mid_distances = 0.5 * (distances[:-1] + distances[1:])
        mask = _corner_mask(mid_distances, entry, exit_)
        rate_in = steer_rate[mask]

        if len(rate_in) < 3:
            results.append({
                "corner_id": cid,
                "correction_count": 0,
                "severity": 0.0,
            })
            continue

        # Sign changes in steering rate
        signs = np.sign(rate_in)
        sign_changes = np.diff(signs)
        reversals = np.where(sign_changes != 0)[0]
        n_corrections = len(reversals)

        if n_corrections > 0:
            severity = float(np.mean(np.abs(rate_in[reversals])))
        else:
            severity = 0.0

        results.append({
            "corner_id": cid,
            "correction_count": n_corrections,
            "severity": round(severity, 4),
        })

    return results


# ========================================================================
# RPM / POWER CURVE
# ========================================================================


def fit_power_curve(
    rpm: np.ndarray,
    accel_long_mps2: np.ndarray,
    throttle_pct: np.ndarray,
    speed_mps: np.ndarray,
    mass_kg: float = 350.0,
) -> dict:
    """Fit engine torque/power from full-throttle observations.

    Filters to throttle > 90 %, computes wheel torque via
    ``T_wheel = m * a * v / omega``, and bins by RPM.

    Returns
    -------
    dict
        ``rpm_points``, ``torque_nm``, ``power_kw``,
        ``peak_power_rpm``, ``optimal_shift_rpm``.
    """
    rpm = _safe_array(rpm)
    accel = _safe_array(accel_long_mps2)
    throttle = _safe_array(throttle_pct)
    speed = _safe_array(speed_mps)

    empty_result: dict[str, Any] = {
        "rpm_points": [],
        "torque_nm": [],
        "power_kw": [],
        "peak_power_rpm": 0.0,
        "optimal_shift_rpm": 0.0,
    }

    if len(rpm) < 10:
        return empty_result

    # Full-throttle filter
    ft_mask = (throttle > 90.0) & (rpm > 500) & (speed > 1.0) & (accel > 0.1)
    if np.sum(ft_mask) < 5:
        return empty_result

    ft_rpm = rpm[ft_mask]
    ft_accel = accel[ft_mask]
    ft_speed = speed[ft_mask]

    # omega = 2*pi*RPM/60 -- but we want wheel torque, not engine torque
    # T_wheel = m * a * v / omega  would require omega_wheel which we don't have.
    # Simplified: Power_wheel = F * v = m * a * v
    power_w = mass_kg * ft_accel * ft_speed

    # Bin by RPM (500-RPM bins)
    rpm_min = float(np.floor(np.min(ft_rpm) / 500) * 500)
    rpm_max = float(np.ceil(np.max(ft_rpm) / 500) * 500)
    if rpm_max <= rpm_min:
        rpm_max = rpm_min + 500

    bins = np.arange(rpm_min, rpm_max + 500, 500)
    bin_indices = np.digitize(ft_rpm, bins)

    rpm_points: list[float] = []
    torque_nm: list[float] = []
    power_kw: list[float] = []

    for i in range(1, len(bins)):
        mask_bin = bin_indices == i
        if np.sum(mask_bin) < 2:
            continue
        mid_rpm = float(bins[i - 1] + bins[i]) / 2.0
        avg_power = float(np.median(power_w[mask_bin]))
        omega = 2.0 * np.pi * mid_rpm / 60.0
        if omega > 1e-6:
            avg_torque = avg_power / omega
        else:
            avg_torque = 0.0

        rpm_points.append(round(mid_rpm, 0))
        torque_nm.append(round(avg_torque, 2))
        power_kw.append(round(avg_power / 1000.0, 3))

    if not rpm_points:
        return empty_result

    power_arr = np.array(power_kw)
    peak_idx = int(np.argmax(power_arr))
    peak_power_rpm = rpm_points[peak_idx]

    # Optimal shift: RPM where power drops below 95% of peak on the high side
    peak_power = power_arr[peak_idx]
    optimal_shift = rpm_points[-1]  # default: redline
    for j in range(peak_idx, len(power_arr)):
        if power_arr[j] < 0.95 * peak_power:
            optimal_shift = rpm_points[j]
            break

    return {
        "rpm_points": rpm_points,
        "torque_nm": torque_nm,
        "power_kw": power_kw,
        "peak_power_rpm": peak_power_rpm,
        "optimal_shift_rpm": optimal_shift,
    }


def score_shift_quality(
    rpm: np.ndarray,
    gear: np.ndarray,
    optimal_shift_rpm: float,
) -> float:
    """Score 0-1 for how close actual upshift RPMs are to optimal.

    Finds gear transitions (gear increases by 1), captures RPM just
    before the shift, compares to *optimal_shift_rpm*.
    """
    rpm = _safe_array(rpm)
    gear = _safe_array(gear)

    if len(rpm) < 2 or optimal_shift_rpm < 100:
        return 0.0

    gear_diff = np.diff(gear)
    upshift_indices = np.where(gear_diff == 1)[0]

    if len(upshift_indices) == 0:
        return 0.0

    shift_rpms = rpm[upshift_indices]
    # Remove any zero/invalid RPMs
    shift_rpms = shift_rpms[shift_rpms > 100]
    if len(shift_rpms) == 0:
        return 0.0

    # Score: 1 - mean(abs(shift_rpm - optimal) / optimal), clamped 0-1
    deviations = np.abs(shift_rpms - optimal_shift_rpm) / optimal_shift_rpm
    mean_dev = float(np.mean(deviations))
    score = max(0.0, 1.0 - mean_dev)
    return float(np.clip(score, 0.0, 1.0))


# ========================================================================
# CORNER ANALYSIS MASTER FUNCTION
# ========================================================================


def analyze_corners_with_controls(
    resampled_lap: pd.DataFrame,
    corners: list[dict],
) -> list[dict]:
    """Run all brake/throttle/steering analysis for a single lap.

    Parameters
    ----------
    resampled_lap : pd.DataFrame
        Distance-resampled lap data.  Expected columns (all optional
        except distance):
        - ``distance_m`` / ``Distance (m)``
        - ``brake_pct``
        - ``throttle_pct``
        - ``steering_angle_deg``
        - ``rpm``
        - ``gear``
        - ``speed_mps`` / ``Speed (m/s)``
        - ``accel_long_mps2`` / ``Acceleration X (m/s2)``
    corners : list[dict]
        Each dict has at least ``corner_id``, ``entry_m``, ``apex_m``,
        ``exit_m``.

    Returns
    -------
    list[dict]
        Enriched corner analysis list.  Missing-column analyses are
        simply omitted from the output dicts.
    """
    if resampled_lap.empty or not corners:
        return []

    # Resolve distance column (required)
    dist_col = _resolve_column(resampled_lap, _COL_DIST, _COL_DIST_INT)
    if dist_col is None:
        logger.warning("controls_physics: no distance column found — skipping")
        return []

    distances = _safe_array(resampled_lap[dist_col].values)

    # Resolve optional columns
    brake_col = _resolve_column(resampled_lap, _COL_BRAKE)
    throttle_col = _resolve_column(resampled_lap, _COL_THROTTLE)
    steer_col = _resolve_column(resampled_lap, _COL_STEERING)
    rpm_col = _resolve_column(resampled_lap, _COL_RPM)
    gear_col = _resolve_column(resampled_lap, _COL_GEAR)
    speed_col = _resolve_column(resampled_lap, _COL_SPEED, _COL_SPEED_INT)
    accel_col = _resolve_column(resampled_lap, _COL_ACCEL_LONG, _COL_ACCEL_LONG_ALT)

    # Initialize result list from corners
    results: list[dict] = []
    for corner in corners:
        results.append({
            "corner_id": corner.get("corner_id", 0),
            "entry_m": corner.get("entry_m", 0.0),
            "apex_m": corner.get("apex_m", 0.0),
            "exit_m": corner.get("exit_m", 0.0),
        })

    # Brake analysis
    if brake_col is not None:
        brake = _safe_array(resampled_lap[brake_col].values)
        try:
            brake_pts = detect_brake_points(distances, brake)
            # Attach to closest corner
            for res in results:
                entry = res["entry_m"]
                res["brake_points_before"] = [
                    bp for bp in brake_pts
                    if entry - 200 < bp < entry
                ]
        except Exception:
            logger.debug("controls_physics: brake_points failed: %s", traceback.format_exc())

        if steer_col is not None:
            steer = _safe_array(resampled_lap[steer_col].values)
            try:
                trail = measure_trail_braking(distances, brake, steer, corners)
                for i, res in enumerate(results):
                    if i < len(trail):
                        res.update(trail[i])
            except Exception:
                logger.debug("controls_physics: trail_braking failed: %s", traceback.format_exc())

    # Throttle analysis
    if throttle_col is not None:
        throttle = _safe_array(resampled_lap[throttle_col].values)
        try:
            thr_metrics = measure_throttle_application(distances, throttle, corners)
            for i, res in enumerate(results):
                if i < len(thr_metrics):
                    res["exit_application_rate"] = thr_metrics[i].get("exit_application_rate", 0.0)
                    res["hesitation_zones"] = thr_metrics[i].get("hesitation_zones", [])
        except Exception:
            logger.debug("controls_physics: throttle_application failed: %s", traceback.format_exc())

        if brake_col is not None:
            try:
                coasting = detect_coasting_zones(distances, throttle, brake)
                # Attach coasting zones to the nearest preceding corner
                for res in results:
                    exit_ = res["exit_m"]
                    next_entry = float("inf")
                    idx = results.index(res)
                    if idx + 1 < len(results):
                        next_entry = results[idx + 1]["entry_m"]
                    res["coasting_after"] = [
                        z for z in coasting
                        if exit_ <= z["start_m"] < next_entry
                    ]
            except Exception:
                logger.debug("controls_physics: coasting failed: %s", traceback.format_exc())

    # Steering analysis
    if steer_col is not None:
        steer = _safe_array(resampled_lap[steer_col].values)
        try:
            smoothness = compute_steering_smoothness(distances, steer)
            for res in results:
                res["steering_smoothness"] = smoothness
        except Exception:
            logger.debug("controls_physics: smoothness failed: %s", traceback.format_exc())

        try:
            corrections = count_corrections(distances, steer, corners)
            for i, res in enumerate(results):
                if i < len(corrections):
                    res["correction_count"] = corrections[i].get("correction_count", 0)
                    res["correction_severity"] = corrections[i].get("severity", 0.0)
        except Exception:
            logger.debug("controls_physics: corrections failed: %s", traceback.format_exc())

    # RPM / Power (lap-level, attached to all corners)
    if rpm_col is not None and accel_col is not None and speed_col is not None and throttle_col is not None:
        rpm_arr = _safe_array(resampled_lap[rpm_col].values)
        accel_arr = _safe_array(resampled_lap[accel_col].values)
        speed_arr = _safe_array(resampled_lap[speed_col].values)
        throttle_arr = _safe_array(resampled_lap[throttle_col].values)
        try:
            power = fit_power_curve(rpm_arr, accel_arr, throttle_arr, speed_arr)
            for res in results:
                res["peak_power_rpm"] = power.get("peak_power_rpm", 0.0)
                res["optimal_shift_rpm"] = power.get("optimal_shift_rpm", 0.0)
        except Exception:
            logger.debug("controls_physics: power_curve failed: %s", traceback.format_exc())

        if gear_col is not None:
            gear_arr = _safe_array(resampled_lap[gear_col].values)
            optimal = 0.0
            try:
                power = fit_power_curve(rpm_arr, accel_arr, throttle_arr, speed_arr)
                optimal = power.get("optimal_shift_rpm", 0.0)
            except Exception:
                pass
            if optimal > 0:
                try:
                    sq = score_shift_quality(rpm_arr, gear_arr, optimal)
                    for res in results:
                        res["shift_quality_score"] = round(sq, 4)
                except Exception:
                    logger.debug("controls_physics: shift_quality failed: %s", traceback.format_exc())

    return results
