"""
road_attitude_estimator.py
--------------------------
Estimate road attitude (bank, grade) from phone IMU + GPS, given a known
phone-to-kart frame rotation.

What this estimates
-------------------
- Bank angle (lateral road tilt, deg)
- Grade angle (longitudinal road slope, deg)
- Per-sample attitude quality (0-1)
- Instability/low-observability flags

What this does NOT estimate
---------------------------
- Tire-road friction coefficient
- Surface grip potential
- Tire force capacity
- Anything physical about the road's friction

Observability limitations
-------------------------
1. Bank and lateral vehicle dynamics are confounded. With curvature
   available, we can subtract the expected centripetal load and attribute
   the residual to bank. Without curvature, bank is poorly observable
   except in low-lateral-G segments.
2. Grade and longitudinal vehicle dynamics (braking, throttle) are
   confounded. With GPS speed available, we can subtract the expected
   longitudinal accel and attribute the residual to grade. Under hard
   braking or full throttle, grade observability degrades.
3. Speed must be sufficient (~5 m/s+) for centripetal cancellation to
   work. Low-speed segments produce low-confidence estimates.
4. Phone mount must be stable. If `mount_estimate.mount_unstable` is True,
   all attitude estimates inherit that instability.

How downstream modules should use this
--------------------------------------
- For demand correction: use `bank_deg` and `grade_deg` to remove gravity
  contamination from kart-frame lateral/longitudinal accel.
- ALWAYS check `attitude_quality[i]` before trusting `bank_deg[i]` or
  `grade_deg[i]`. Quality < 0.4 means the estimate is essentially noise.
- ALWAYS check `unstable_segments[i]` before propagating estimates into
  downstream physical interpretations.

Invariant: this module separates road attitude from vehicle motion to
improve demand interpretation. It does not estimate friction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter

logger = logging.getLogger(__name__)

_G = 9.80665

# Default bounds (configurable via function args)
_DEFAULT_BANK_MAX_DEG = 12.0
_DEFAULT_GRADE_MAX_DEG = 10.0


@dataclass
class RoadAttitudeEstimate:
    """Per-sample road attitude estimate with confidence + flags."""

    bank_deg: np.ndarray            # (N,) bank angle (positive = left side high)
    grade_deg: np.ndarray           # (N,) grade angle (positive = uphill)
    attitude_quality: np.ndarray    # (N,) 0-1 per-sample confidence
    mean_bank_deg: float            # session-level mean (high-confidence samples only)
    mean_grade_deg: float           # session-level mean (high-confidence samples only)
    unstable_segments: np.ndarray   # (N,) bool — true where estimate is unreliable
    confidence_flags: dict = field(default_factory=dict)


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────


def _savgol(arr: np.ndarray, window: int, polyorder: int = 2) -> np.ndarray:
    """Savitzky-Golay with safe boundary handling."""
    n = len(arr)
    if n < window:
        return arr.copy()
    if window % 2 == 0:
        window += 1
    return savgol_filter(arr, window, polyorder, mode='nearest')


def _to_kart_frame(
    accel_phone: np.ndarray,
    gyro_phone: np.ndarray,
    R_phone_to_kart: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Transform phone-frame measurements to kart frame.

    Returns (accel_kart, gyro_kart) each shape (N, 3).
    Kart frame: x=forward, y=lateral (left), z=up.
    """
    # v_kart = R @ v_phone — apply to each row
    accel_kart = accel_phone @ R_phone_to_kart.T
    gyro_kart = gyro_phone @ R_phone_to_kart.T
    return accel_kart, gyro_kart


# ───────────────────────────────────────────────────────────────────
# Main estimator
# ───────────────────────────────────────────────────────────────────


def estimate_road_attitude(
    accel: np.ndarray,
    gyro: np.ndarray,
    gps_speed: np.ndarray,
    timestamps: np.ndarray,
    mount_estimate,
    *,
    gps_heading: np.ndarray | None = None,
    curvature: np.ndarray | None = None,
    bank_max_deg: float = _DEFAULT_BANK_MAX_DEG,
    grade_max_deg: float = _DEFAULT_GRADE_MAX_DEG,
    smooth_window_s: float = 1.0,
    min_speed_mps: float = 5.0,
) -> RoadAttitudeEstimate:
    """Estimate road bank and grade per sample.

    Parameters
    ----------
    accel : (N, 3) phone-frame accelerometer in g
    gyro : (N, 3) phone-frame gyroscope in deg/s
    gps_speed : (N,) m/s
    timestamps : (N,) seconds
    mount_estimate : PhoneMountEstimate from phone_mount_estimator
    gps_heading : optional (N,) bearing in radians
    curvature : optional (N,) signed curvature 1/m at each sample
    bank_max_deg : conservative clamp for bank estimate
    grade_max_deg : conservative clamp for grade estimate
    smooth_window_s : smoothing window in seconds
    min_speed_mps : below this speed, mark low confidence

    Returns
    -------
    RoadAttitudeEstimate
    """
    accel = np.asarray(accel, dtype=float)
    gyro = np.asarray(gyro, dtype=float)
    gps_speed = np.asarray(gps_speed, dtype=float)
    timestamps = np.asarray(timestamps, dtype=float)
    n = len(accel)

    if n < 50:
        return _empty_estimate(n)

    # ── Step 1: transform to kart frame ──
    R = mount_estimate.R_phone_to_kart
    accel_kart, gyro_kart = _to_kart_frame(accel, gyro, R)

    # Gravity vector in kart frame: should be (0, 0, -1) ideally.
    # Any deviation from that is the road tilt.
    g_phone = mount_estimate.gravity_vector
    g_kart = R @ g_phone
    # Expected: g_kart = (0, 0, -1) for level road.
    # For tilted road: g_kart = (-sin(grade), sin(bank)*cos(grade), -cos(bank)*cos(grade))
    # We compare instantaneous (low-pass) accel to this expected gravity.

    # ── Step 2: low-pass to extract gravity component per sample ──
    dt = float(np.median(np.diff(timestamps)))
    if dt <= 0 or not np.isfinite(dt):
        dt = 0.04
    win_samples = max(11, int(smooth_window_s / dt))
    if win_samples % 2 == 0:
        win_samples += 1
    win_samples = min(win_samples, n - 1 if n % 2 == 0 else n - 2)
    if win_samples < 5:
        win_samples = 5

    # Low-pass each kart-frame axis to separate gravity-like component
    g_lp = np.zeros((n, 3))
    for axis in range(3):
        g_lp[:, axis] = _savgol(accel_kart[:, axis], win_samples, polyorder=2)

    # ── Step 3: estimate grade ──
    # On level road: a_x_lp = -longitudinal_accel_demand (roughly 0 at steady state)
    # Plus gravity component: g * sin(grade) projected onto kart x
    # On uphill: gravity pulls back, so a_x_phone reads negative on x (kart forward)
    # → expected a_x_kart_lp ≈ -sin(grade) * |g| - vehicle_long_accel
    # Grade contribution: a_x from gravity = -|g| * sin(grade)
    #   (on uphill, kart frame x is along forward; gravity has a -x component)

    # Vehicle longitudinal accel from GPS speed
    speed_safe = np.maximum(gps_speed, 0.1)
    dv_dt = np.gradient(gps_speed) / np.maximum(np.gradient(timestamps), 1e-6)  # m/s²
    dv_dt_g = dv_dt / _G
    dv_dt_g_smooth = _savgol(dv_dt_g, win_samples, polyorder=2)

    # Expected a_x_kart from vehicle motion alone: +dv_dt_g (forward accel)
    # Residual (after subtracting vehicle long accel) attributed to gravity → grade
    a_x_residual = g_lp[:, 0] - dv_dt_g_smooth
    # a_x_residual = -sin(grade), so grade = -arcsin(a_x_residual)
    sin_grade = -np.clip(a_x_residual, -0.9, 0.9)
    grade_rad_raw = np.arcsin(sin_grade)
    grade_deg_raw = np.degrees(grade_rad_raw)

    # ── Step 4: estimate bank ──
    # On level road: a_y_lp ≈ centripetal accel = v²κ/g (in g)
    # On banked road: a_y_kart_lp = -v²κ/g (centripetal demand) + sin(bank)
    # Wait — sign convention:
    #   Kart y = LEFT. Right turn means car needs centripetal toward right = -y direction.
    #   Centripetal accel measured by IMU: in a right turn (curvature negative), the
    #   IMU reads positive on +y (it's pulled toward outside = left, while kart turns right).
    # Simpler: net lateral accel measured = centripetal + gravity_lat
    #   gravity_lat (kart frame) = +sin(bank) (on a left-banked road, gravity pulls toward +y)

    if curvature is not None:
        curv_arr = np.asarray(curvature, dtype=float)
        if len(curv_arr) != n:
            curv_arr = np.interp(
                np.linspace(0, 1, n),
                np.linspace(0, 1, len(curv_arr)),
                curv_arr,
            )
        # Centripetal (signed): positive curvature = left turn = centripetal toward +y
        # → IMU lateral reading from centripetal = -v²κ/g (reaction to the +y centripetal)
        # Actually: IMU measures the force on the phone, which points toward center of turn.
        # In a left turn, phone is pulled right (-y) → IMU reads -v²κ/g on y? Confusing.
        # Convention: a_lat_imu = +v²κ/g for positive κ (left turn).
        a_lat_centripetal = (gps_speed ** 2) * curv_arr / _G
        a_lat_centripetal_smooth = _savgol(a_lat_centripetal, win_samples, polyorder=2)
    else:
        # No curvature → assume level cornering doesn't bias bank, use raw
        a_lat_centripetal_smooth = np.zeros(n)

    a_y_residual = g_lp[:, 1] - a_lat_centripetal_smooth
    sin_bank = np.clip(a_y_residual, -0.9, 0.9)
    bank_rad_raw = np.arcsin(sin_bank)
    bank_deg_raw = np.degrees(bank_rad_raw)

    # ── Step 5: smooth and clamp ──
    bank_deg = _savgol(bank_deg_raw, win_samples, polyorder=2)
    grade_deg = _savgol(grade_deg_raw, win_samples, polyorder=2)
    bank_deg = np.clip(bank_deg, -bank_max_deg, bank_max_deg)
    grade_deg = np.clip(grade_deg, -grade_max_deg, grade_max_deg)

    # ── Step 6: per-sample quality ──
    # Components:
    #   speed_score: 0 below min_speed, 1 above 2*min_speed
    speed_score = np.clip((gps_speed - min_speed_mps) / min_speed_mps, 0.0, 1.0)

    #   dynamic_score: high when vehicle accel is small (bank/grade observable)
    #   penalize when |dv/dt| > 3 m/s² (hard accel/brake) or |a_centripetal| > 0.5g
    long_dynamic = np.clip(np.abs(dv_dt_g_smooth) / 0.3, 0.0, 1.0)
    if curvature is not None:
        lat_dynamic = np.clip(np.abs(a_lat_centripetal_smooth) / 0.5, 0.0, 1.0)
    else:
        lat_dynamic = np.zeros(n)
    dynamic_score = 1.0 - 0.5 * long_dynamic - 0.5 * lat_dynamic
    dynamic_score = np.clip(dynamic_score, 0.0, 1.0)

    #   stability_score: how much does the raw estimate jump?
    bank_jump = np.abs(np.gradient(bank_deg_raw))
    grade_jump = np.abs(np.gradient(grade_deg_raw))
    jump_penalty = (bank_jump + grade_jump) / 5.0  # 5 deg/sample = saturation
    stability_score = np.clip(1.0 - jump_penalty, 0.0, 1.0)

    #   mount_score: from phone mount estimator
    mount_score = float(getattr(mount_estimate, 'orientation_quality', 0.5))

    # Composite quality per sample
    attitude_quality = (
        0.30 * speed_score
        + 0.30 * dynamic_score
        + 0.20 * stability_score
        + 0.20 * mount_score
    )
    attitude_quality = np.clip(attitude_quality, 0.0, 1.0)
    attitude_quality = _savgol(attitude_quality, win_samples, polyorder=2)
    attitude_quality = np.clip(attitude_quality, 0.0, 1.0)

    # ── Step 7: instability flags ──
    unstable = np.zeros(n, dtype=bool)
    # Mount slip propagates
    if getattr(mount_estimate, 'mount_unstable', False):
        unstable[:] = True
    # Big jumps in raw estimate
    unstable |= (bank_jump > 3.0) | (grade_jump > 3.0)
    # Very low speed
    unstable |= gps_speed < min_speed_mps / 2

    # ── Step 8: high-confidence aggregates ──
    high_conf = attitude_quality > 0.5
    if high_conf.any():
        mean_bank = float(np.mean(bank_deg[high_conf]))
        mean_grade = float(np.mean(grade_deg[high_conf]))
    else:
        mean_bank = float(np.mean(bank_deg))
        mean_grade = float(np.mean(grade_deg))

    flags = {
        'mount_orientation_quality': mount_score,
        'mount_unstable': bool(getattr(mount_estimate, 'mount_unstable', False)),
        'curvature_available': curvature is not None,
        'mean_speed_score': float(np.mean(speed_score)),
        'mean_dynamic_score': float(np.mean(dynamic_score)),
        'mean_stability_score': float(np.mean(stability_score)),
        'high_confidence_fraction': float(high_conf.sum() / n),
        'unstable_fraction': float(unstable.sum() / n),
        'bank_clamp_hits': int(np.sum(np.abs(bank_deg) >= bank_max_deg * 0.999)),
        'grade_clamp_hits': int(np.sum(np.abs(grade_deg) >= grade_max_deg * 0.999)),
    }

    return RoadAttitudeEstimate(
        bank_deg=bank_deg,
        grade_deg=grade_deg,
        attitude_quality=attitude_quality,
        mean_bank_deg=mean_bank,
        mean_grade_deg=mean_grade,
        unstable_segments=unstable,
        confidence_flags=flags,
    )


def _empty_estimate(n: int) -> RoadAttitudeEstimate:
    """Return a zero estimate with low confidence for insufficient data."""
    return RoadAttitudeEstimate(
        bank_deg=np.zeros(max(n, 1)),
        grade_deg=np.zeros(max(n, 1)),
        attitude_quality=np.zeros(max(n, 1)),
        mean_bank_deg=0.0,
        mean_grade_deg=0.0,
        unstable_segments=np.ones(max(n, 1), dtype=bool),
        confidence_flags={
            'insufficient_data': True,
            'high_confidence_fraction': 0.0,
        },
    )
