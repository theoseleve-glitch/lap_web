"""
phone_mount_estimator.py
------------------------
Estimate the rotation between phone IMU frame and vehicle (kart) frame
from accelerometer, gyro, and GPS data.

Outputs a stable mapping phone_frame -> kart_frame and the gravity vector
in phone frame, enabling downstream separation:

    measured_accel = gravity + vehicle_accel

Design principles:
  - Deterministic (no ML)
  - Robust to noisy phone IMU
  - No assumption of perfect mounting
  - Does not modify bronze/silver outputs (additive layer only)

Method:
  1. Gravity from low-pass accelerometer (gravity is the DC component)
  2. Refinement using low-dynamic segments (low gyro, near-constant speed)
  3. Vertical axis from normalized gravity (down direction)
  4. Forward axis from correlation between GPS speed derivative and the
     horizontal projection of residual accelerometer signal
  5. Lateral axis from cross product (vertical x forward)
  6. Quality from gravity stability + forward-axis confidence
  7. Instability detection from sudden orientation changes

Invariant: this module estimates phone-to-kart geometry. It does NOT
estimate friction, surface grip, or anything physical about the road.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter1d

logger = logging.getLogger(__name__)

_G = 9.80665  # gravity magnitude m/s^2


@dataclass
class PhoneMountEstimate:
    """Result of phone mount orientation estimation."""

    R_phone_to_kart: np.ndarray         # (3, 3) rotation matrix
    gravity_vector: np.ndarray          # (3,) gravity in phone frame, units of g
    orientation_quality: float          # 0-1 composite quality score
    mount_unstable: bool                # sudden orientation change detected
    confidence_flags: dict = field(default_factory=dict)


# ───────────────────────────────────────────────────────────────────
# Gravity estimation
# ───────────────────────────────────────────────────────────────────


def estimate_gravity(
    accel: np.ndarray,
    gyro: np.ndarray,
    timestamps: np.ndarray,
    *,
    lowpass_window_s: float = 1.5,
) -> tuple[np.ndarray, float]:
    """Estimate gravity vector in phone frame, units of g.

    Strategy: low-pass the accelerometer over ~1.5s to extract the DC
    component (gravity), then refine using low-dynamic segments where
    the vehicle accel contribution is minimal.

    Returns
    -------
    (gravity_vector_g, stability_score)
        gravity_vector_g : (3,) array, magnitude should be near 1.0
        stability_score  : 0-1, higher = more stable estimate
    """
    n = len(accel)
    if n < 50:
        return np.array([0.0, 0.0, -1.0]), 0.0

    # Median dt for window size in samples
    dt = float(np.median(np.diff(timestamps)))
    if dt <= 0 or not np.isfinite(dt):
        dt = 0.04  # 25Hz default
    window_samples = max(11, int(lowpass_window_s / dt))
    if window_samples % 2 == 0:
        window_samples += 1

    # Low-pass each axis
    g_lp = np.zeros((n, 3))
    for axis in range(3):
        g_lp[:, axis] = uniform_filter1d(accel[:, axis], window_samples, mode='nearest')

    # Find low-dynamic segments: low gyro magnitude AND low |accel - g_lp|
    gyro_mag = np.sqrt(np.sum(gyro ** 2, axis=1))
    accel_dynamic = np.sqrt(np.sum((accel - g_lp) ** 2, axis=1))
    low_dynamic = (gyro_mag < 30.0) & (accel_dynamic < 0.3)

    if low_dynamic.sum() > 50:
        # Use median of low-dynamic samples as refined estimate
        g_refined = np.median(accel[low_dynamic], axis=0)
    else:
        # Fall back to overall mean of low-pass
        g_refined = np.mean(g_lp, axis=0)

    # Stability score: how consistent is the low-pass estimate?
    g_std = np.std(g_lp, axis=0)
    stability = float(np.clip(1.0 - np.mean(g_std) / 0.1, 0.0, 1.0))

    # Sanity check: magnitude should be ~1g
    g_mag = float(np.linalg.norm(g_refined))
    if not (0.7 < g_mag < 1.3):
        logger.warning("Gravity magnitude %.3fg is implausible — IMU may not be in g units", g_mag)
        # Try assuming m/s^2 input instead
        g_refined_mps = g_refined / _G
        g_mag_mps = float(np.linalg.norm(g_refined_mps))
        if 0.7 < g_mag_mps < 1.3:
            return g_refined_mps, stability * 0.7  # confidence reduced, units guessed
        # Otherwise return what we have
        return g_refined, stability * 0.5

    return g_refined, stability


# ───────────────────────────────────────────────────────────────────
# Horizontal projection
# ───────────────────────────────────────────────────────────────────


def project_to_horizontal(
    vec: np.ndarray,
    gravity_unit: np.ndarray,
) -> np.ndarray:
    """Remove the component of vec along gravity_unit (project to horizontal)."""
    if vec.ndim == 1:
        return vec - np.dot(vec, gravity_unit) * gravity_unit
    # Batched: vec shape (N, 3)
    proj = np.dot(vec, gravity_unit)  # (N,)
    return vec - proj[:, None] * gravity_unit[None, :]


# ───────────────────────────────────────────────────────────────────
# Forward axis estimation
# ───────────────────────────────────────────────────────────────────


def estimate_forward_axis(
    accel: np.ndarray,
    gravity_vec: np.ndarray,
    gps_speed: np.ndarray,
    timestamps: np.ndarray,
    *,
    min_speed: float = 5.0,
    min_accel_threshold: float = 1.0,
) -> tuple[np.ndarray | None, float]:
    """Estimate forward direction in phone horizontal frame.

    Method: during longitudinal accel/braking events, the phone's
    horizontal acceleration projection should align with the vehicle's
    forward axis. Find that direction by maximum correlation with
    GPS-derived longitudinal accel.

    Returns
    -------
    (forward_unit_3d, confidence)
        forward_unit_3d : (3,) unit vector in phone frame, or None if low confidence
        confidence      : 0-1
    """
    n = len(accel)
    if n < 50 or len(gps_speed) != n:
        return None, 0.0

    # Gravity unit vector
    g_mag = np.linalg.norm(gravity_vec)
    if g_mag < 0.1:
        return None, 0.0
    g_unit = gravity_vec / g_mag

    # Vehicle accel = total accel - gravity (in g units)
    vehicle_accel = accel - gravity_vec[None, :]

    # Project to horizontal plane
    vehicle_accel_h = project_to_horizontal(vehicle_accel, g_unit)

    # GPS-derived longitudinal accel (in g)
    dt = np.gradient(timestamps)
    dt[dt < 1e-6] = 1e-6
    dv_dt = np.gradient(gps_speed) / dt  # m/s^2
    dv_dt_g = dv_dt / _G

    # Significant samples: high speed AND large longitudinal accel magnitude
    significant = (gps_speed > min_speed) & (np.abs(dv_dt_g) > min_accel_threshold / _G)
    n_sig = int(significant.sum())
    if n_sig < 30:
        return None, 0.0

    # Find horizontal direction with max correlation to dv_dt_g
    # Build orthonormal basis in horizontal plane
    # Pick any vector not parallel to g_unit, project, normalize
    helper = np.array([1.0, 0.0, 0.0]) if abs(g_unit[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = project_to_horizontal(helper, g_unit)
    e1 /= np.linalg.norm(e1) + 1e-12
    e2 = np.cross(g_unit, e1)
    e2 /= np.linalg.norm(e2) + 1e-12

    # Project horizontal accel onto basis (N, 2)
    a_e1 = np.dot(vehicle_accel_h[significant], e1)
    a_e2 = np.dot(vehicle_accel_h[significant], e2)
    target = dv_dt_g[significant]

    # Correlation as function of angle theta
    # forward = cos(theta) * e1 + sin(theta) * e2
    # projection = a_e1 * cos(theta) + a_e2 * sin(theta)
    # Maximize Pearson correlation with target
    thetas = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    correlations = np.zeros(len(thetas))
    target_centered = target - target.mean()
    target_norm = np.linalg.norm(target_centered)
    if target_norm < 1e-9:
        return None, 0.0

    for ti, th in enumerate(thetas):
        proj = a_e1 * np.cos(th) + a_e2 * np.sin(th)
        proj_centered = proj - proj.mean()
        proj_norm = np.linalg.norm(proj_centered)
        if proj_norm < 1e-9:
            continue
        correlations[ti] = np.dot(proj_centered, target_centered) / (proj_norm * target_norm)

    best_ti = int(np.argmax(correlations))
    best_corr = float(correlations[best_ti])
    best_theta = thetas[best_ti]

    forward_unit = np.cos(best_theta) * e1 + np.sin(best_theta) * e2

    # Confidence: correlation strength + sample count + speed coverage
    corr_score = max(0.0, best_corr)
    count_score = min(1.0, n_sig / 200.0)
    speed_score = min(1.0, float(gps_speed.max()) / 30.0)
    confidence = 0.5 * corr_score + 0.3 * count_score + 0.2 * speed_score

    return forward_unit, float(np.clip(confidence, 0.0, 1.0))


# ───────────────────────────────────────────────────────────────────
# Build rotation matrix
# ───────────────────────────────────────────────────────────────────


def build_rotation_matrix(
    forward_phone: np.ndarray,
    gravity_phone: np.ndarray,
) -> np.ndarray:
    """Build R such that v_kart = R @ v_phone.

    Kart frame convention:
      x = forward (direction of travel)
      y = lateral (left, right-hand rule with z up)
      z = vertical up (opposite to gravity)
    """
    g_mag = np.linalg.norm(gravity_phone)
    if g_mag < 1e-6:
        return np.eye(3)
    z_kart_in_phone = -gravity_phone / g_mag   # up = -gravity direction

    # Re-orthogonalize forward against vertical
    fwd = forward_phone - np.dot(forward_phone, z_kart_in_phone) * z_kart_in_phone
    fwd_norm = np.linalg.norm(fwd)
    if fwd_norm < 1e-6:
        return np.eye(3)
    x_kart_in_phone = fwd / fwd_norm

    # Lateral = z x forward (right-handed system, lateral points LEFT)
    y_kart_in_phone = np.cross(z_kart_in_phone, x_kart_in_phone)
    y_kart_in_phone /= np.linalg.norm(y_kart_in_phone) + 1e-12

    # R rows are kart axes expressed in phone frame
    # v_kart = R @ v_phone where R[i,:] = kart_axis_i (in phone frame)
    R = np.vstack([x_kart_in_phone, y_kart_in_phone, z_kart_in_phone])
    return R


# ───────────────────────────────────────────────────────────────────
# Drift / instability detection
# ───────────────────────────────────────────────────────────────────


def detect_mount_instability(
    accel: np.ndarray,
    gyro: np.ndarray,
    timestamps: np.ndarray,
    *,
    window_s: float = 10.0,
    long_smooth_s: float = 30.0,
    short_smooth_s: float = 0.5,
    slip_threshold_g: float = 0.15,
    drift_threshold_g: float = 0.05,
    min_low_dynamic_samples_per_window: int | None = None,
    low_dynamic_residual_g: float = 0.20,
    low_dynamic_gyro_dps: float = 30.0,
) -> dict:
    """Detect mount slip (genuine reorientation) vs normal kart vibration.

    Three timescales are separated:
      • Vibration (short, ~10-30 Hz): rejected by a short low-pass smoother.
      • Corner dynamics (medium, 1-10 s of sustained centripetal accel):
        rejected by per-sample "low-dynamic" gating — only samples where the
        accel residual from a long smoother is small AND gyro magnitude is
        small contribute to a window's gravity estimate.
      • Mount slip (step change in orientation): detected as the maximum
        **pairwise** distance between any two windows' gravity estimates
        across the entire session — not adjacent-window comparison.

    Why the redesign: the previous detector compared raw-accel medians of
    adjacent windows, which conflates sustained corner accel with mount
    slip and reliably triggered ``mount_unstable=True`` on every kart
    session. This logic preserves slip detection while ignoring vibration
    and the per-corner accel signature.

    Parameters
    ----------
    accel : (N, 3) accelerometer in g
    gyro : (N, 3) gyroscope in deg/s
    timestamps : (N,) seconds
    window_s : analysis window length (default 10 s)
    long_smooth_s : long low-pass for "what gravity should be in this region"
        — long enough to average across multiple corners
    short_smooth_s : short low-pass to estimate vibration metric
    slip_threshold_g : max pairwise gravity drift above which mount_unstable=True
    drift_threshold_g : softer threshold above which low_confidence=True
    min_low_dynamic_samples_per_window : minimum samples per window that must
        pass low-dynamic gating to compute a window gravity. None → adaptive
        (5% of window_samples, floor 5).
    low_dynamic_residual_g : per-sample max |accel - long_smoothed| (in g)
        to qualify as low-dynamic
    low_dynamic_gyro_dps : per-sample max gyro magnitude (deg/s) to qualify
        as low-dynamic

    Returns
    -------
    dict with both legacy keys (preserved for backward compatibility) and
    new diagnostic fields. See keys below.
    """
    n = len(accel)
    base = {
        'mount_unstable': False,
        'low_confidence': True,
        'max_gravity_drift_g': 0.0,
        'max_slip_drift_g': 0.0,
        'total_drift_g': 0.0,
        'vibration_metric_g': 0.0,
        'low_dynamic_frac': 0.0,
        'n_windows_total': 0,
        'n_windows_assessed': 0,
        'mean_low_dynamic_samples_per_window': 0.0,
        'instability_mask': [],
        'reason': 'insufficient_samples',
        'thresholds': {
            'slip_threshold_g': slip_threshold_g,
            'drift_threshold_g': drift_threshold_g,
            'window_s': window_s,
            'long_smooth_s': long_smooth_s,
            'short_smooth_s': short_smooth_s,
            'low_dynamic_residual_g': low_dynamic_residual_g,
            'low_dynamic_gyro_dps': low_dynamic_gyro_dps,
        },
    }
    if n < 100:
        return base

    accel = np.asarray(accel, dtype=float)
    gyro = np.asarray(gyro, dtype=float)

    dt = float(np.median(np.diff(timestamps)))
    if dt <= 0 or not np.isfinite(dt):
        dt = 0.04

    window_samples = max(50, int(window_s / dt))
    n_windows = n // window_samples
    if n_windows < 2:
        return {**base, 'reason': 'too_few_windows'}

    # ── 1. Long-smoothed accel — proxy for "session-local gravity baseline" ──
    # Long enough to average out individual corners. Capped at half the
    # session so we don't degenerate to a constant on short sessions.
    long_smooth_samples = min(max(int(long_smooth_s / dt), 11), max(11, n // 2))
    if long_smooth_samples % 2 == 0:
        long_smooth_samples += 1
    accel_long_smooth = uniform_filter1d(
        accel, long_smooth_samples, axis=0, mode='nearest',
    )

    # ── 2. Vibration metric — RMS of residual from a SHORT smoother ──
    # Pure observability metric. Not used for the gating decision but
    # exposed in diagnostics so downstream can see *why* a session was hard.
    short_smooth_samples = max(int(short_smooth_s / dt), 5)
    if short_smooth_samples % 2 == 0:
        short_smooth_samples += 1
    accel_short_smooth = uniform_filter1d(
        accel, short_smooth_samples, axis=0, mode='nearest',
    )
    vibration_metric = float(
        np.sqrt(np.mean(np.sum((accel - accel_short_smooth) ** 2, axis=1)))
    )

    # ── 3. Per-sample "low-dynamic" mask ──
    # Reject samples where the kart is meaningfully accelerating (residual from
    # the long smoother is large) or rotating fast (gyro magnitude is large).
    # Critical: compare the SHORT-SMOOTHED accel (vibration already rejected)
    # to the long smoother. Otherwise vibration spikes alone disqualify
    # samples on noisy kart data — which was the v1 detector failure mode.
    # What survives: straights at steady speed.
    accel_residual = np.linalg.norm(accel_short_smooth - accel_long_smooth, axis=1)
    gyro_mag = np.linalg.norm(gyro, axis=1)
    low_dynamic = (accel_residual < low_dynamic_residual_g) & (gyro_mag < low_dynamic_gyro_dps)

    if min_low_dynamic_samples_per_window is None:
        min_ld = max(5, window_samples // 20)
    else:
        min_ld = int(min_low_dynamic_samples_per_window)

    # ── 4. Per-window gravity — from low-dynamic samples only ──
    g_per_window = np.full((n_windows, 3), np.nan)
    n_ld_per_window = np.zeros(n_windows, dtype=int)
    for w in range(n_windows):
        start = w * window_samples
        end = min(n, start + window_samples)
        ld_mask = low_dynamic[start:end]
        n_ld = int(ld_mask.sum())
        n_ld_per_window[w] = n_ld
        if n_ld >= min_ld:
            # Median over low-dynamic samples in this window. Use the
            # short-smoothed signal — vibration is already rejected, but the
            # local orientation signature (which is what slip detection
            # cares about) is preserved. Using the long-smoothed signal
            # would bake in edge bias on short sessions.
            g_per_window[w] = np.median(accel_short_smooth[start:end][ld_mask], axis=0)

    valid = ~np.isnan(g_per_window).any(axis=1)
    n_assessed = int(valid.sum())

    if n_assessed < 2:
        # Cannot assess slip — entire session is too dynamic. Default to
        # NOT-unstable + low_confidence rather than blocking all correction.
        return {
            **base,
            'low_dynamic_frac': float(low_dynamic.mean()),
            'mean_low_dynamic_samples_per_window': float(np.mean(n_ld_per_window)),
            'n_windows_total': int(n_windows),
            'n_windows_assessed': n_assessed,
            'vibration_metric_g': vibration_metric,
            'reason': 'insufficient_low_dynamic_samples',
        }

    g_valid = g_per_window[valid]

    # ── 5. Slip detection — max pairwise gravity distance across the session ──
    # If the phone slipped at any point, two windows on either side will have
    # noticeably different gravity. A per-corner accel pattern won't show up
    # because corners have already been gated out at step 3.
    # Use vector ops to avoid an N×N inner loop.
    max_slip = float(
        np.linalg.norm(g_valid[:, None, :] - g_valid[None, :, :], axis=2).max()
    )

    # ── 6. Drift detection — linear trend across windows ──
    if n_assessed >= 3:
        w_indices = np.where(valid)[0].astype(float)
        slopes = np.array([
            np.polyfit(w_indices, g_valid[:, ax], 1)[0] for ax in range(3)
        ])
        total_drift = float(np.linalg.norm(slopes * n_windows))
    else:
        total_drift = 0.0

    # ── 7. Per-window instability mask (windows that diverge from session median) ──
    g_session_median = np.median(g_valid, axis=0)
    per_window_drift = np.linalg.norm(g_per_window - g_session_median[None, :], axis=1)
    instability_mask = np.zeros(n_windows, dtype=bool)
    # Only mark windows we could actually assess.
    instability_mask[valid] = per_window_drift[valid] > slip_threshold_g

    # ── 8. Top-level decision ──
    mount_unstable = max_slip > slip_threshold_g
    # low_confidence is intentionally looser than mount_unstable: it warns
    # downstream consumers that the gravity baseline may be drifting even
    # when no hard slip is detected.
    low_confidence = (
        (max_slip > drift_threshold_g)
        or (total_drift > drift_threshold_g)
        or (n_assessed < 0.5 * n_windows)
    )

    return {
        # Legacy keys (preserved for backward compatibility):
        'mount_unstable': bool(mount_unstable),
        'low_confidence': bool(low_confidence),
        'max_gravity_drift_g': max_slip,
        # New diagnostic keys:
        'max_slip_drift_g': max_slip,
        'total_drift_g': total_drift,
        'vibration_metric_g': vibration_metric,
        'low_dynamic_frac': float(low_dynamic.mean()),
        'n_windows_total': int(n_windows),
        'n_windows_assessed': n_assessed,
        'mean_low_dynamic_samples_per_window': float(np.mean(n_ld_per_window)),
        'instability_mask': instability_mask.tolist(),
        'reason': 'ok',
        'thresholds': {
            'slip_threshold_g': slip_threshold_g,
            'drift_threshold_g': drift_threshold_g,
            'window_s': window_s,
            'long_smooth_s': long_smooth_s,
            'short_smooth_s': short_smooth_s,
            'low_dynamic_residual_g': low_dynamic_residual_g,
            'low_dynamic_gyro_dps': low_dynamic_gyro_dps,
            'min_low_dynamic_samples_per_window': min_ld,
        },
    }


# ───────────────────────────────────────────────────────────────────
# Diagnostic surfacing helper
# ───────────────────────────────────────────────────────────────────


_INSTABILITY_FLAGS_SURFACE = (
    'mount_unstable',
    'max_gravity_drift_g',
    'max_slip_drift_g',
    'total_drift_g',
    'vibration_metric_g',
    'low_dynamic_frac',
    'n_windows_total',
    'n_windows_assessed',
    'mean_low_dynamic_samples_per_window',
    'instability_mask',
    'reason',
    'thresholds',
)


def _pick_instability_flags(instability: dict) -> dict:
    """Surface instability-detector diagnostics into ``confidence_flags``.

    Keeps the detector's internal dict format authoritative — this just
    forwards the keys we want callers to see, which preserves backward
    compatibility (the legacy ``mount_unstable`` and ``max_gravity_drift_g``
    keys are still present) while exposing the new diagnostic fields.
    """
    return {k: instability[k] for k in _INSTABILITY_FLAGS_SURFACE if k in instability}


# ───────────────────────────────────────────────────────────────────
# Top-level estimator
# ───────────────────────────────────────────────────────────────────


def estimate_phone_mount(
    accel: np.ndarray,
    gyro: np.ndarray,
    gps_speed: np.ndarray,
    timestamps: np.ndarray,
    *,
    gps_heading: np.ndarray | None = None,
) -> PhoneMountEstimate:
    """Estimate phone-to-kart frame rotation from IMU + GPS.

    Parameters
    ----------
    accel : (N, 3) accelerometer samples in PHONE FRAME, units of g
            (if input is m/s^2, function will detect and convert)
    gyro  : (N, 3) gyroscope samples in PHONE FRAME, deg/s
    gps_speed : (N,) GPS speed, m/s
    timestamps : (N,) sample timestamps, seconds
    gps_heading : optional (N,) GPS bearing in radians

    Returns
    -------
    PhoneMountEstimate
    """
    accel = np.asarray(accel, dtype=float)
    gyro = np.asarray(gyro, dtype=float)
    gps_speed = np.asarray(gps_speed, dtype=float)
    timestamps = np.asarray(timestamps, dtype=float)

    if accel.ndim != 2 or accel.shape[1] != 3:
        raise ValueError(f"accel must be (N, 3), got {accel.shape}")
    if len(accel) != len(gps_speed) or len(accel) != len(timestamps):
        raise ValueError("accel, gps_speed, timestamps must all have same length")

    # Step 1: Gravity
    gravity_vec, gravity_stability = estimate_gravity(accel, gyro, timestamps)

    # Step 2-3: Forward axis from GPS speed correlation
    forward_unit, fwd_confidence = estimate_forward_axis(
        accel, gravity_vec, gps_speed, timestamps,
    )

    if forward_unit is None:
        # Insufficient data for forward axis — still run instability detection
        # so mount-slip events are detected even with poor speed coverage
        instability_only = detect_mount_instability(accel, gyro, timestamps)
        return PhoneMountEstimate(
            R_phone_to_kart=np.eye(3),
            gravity_vector=gravity_vec,
            orientation_quality=0.0,
            mount_unstable=instability_only['mount_unstable'],
            confidence_flags={
                'forward_axis_known': False,
                'low_speed_or_no_dynamics': True,
                'gravity_stability': gravity_stability,
                'low_confidence': True,
                **_pick_instability_flags(instability_only),
            },
        )

    # Step 4: Build rotation
    R = build_rotation_matrix(forward_unit, gravity_vec)

    # Step 5: Quality score
    instability = detect_mount_instability(accel, gyro, timestamps)
    drift_score = max(0.0, 1.0 - instability['max_gravity_drift_g'] / 0.15)
    speed_coverage = min(1.0, float(np.percentile(gps_speed, 95)) / 25.0)

    quality = (
        0.35 * gravity_stability
        + 0.35 * fwd_confidence
        + 0.20 * drift_score
        + 0.10 * speed_coverage
    )
    quality = float(np.clip(quality, 0.0, 1.0))

    flags = {
        'forward_axis_known': True,
        'gravity_stability': float(gravity_stability),
        'forward_confidence': float(fwd_confidence),
        'speed_coverage': float(speed_coverage),
        'drift_score': float(drift_score),
        'low_confidence': instability['low_confidence'] or quality < 0.4,
        **_pick_instability_flags(instability),
    }

    return PhoneMountEstimate(
        R_phone_to_kart=R,
        gravity_vector=gravity_vec,
        orientation_quality=quality,
        mount_unstable=instability['mount_unstable'],
        confidence_flags=flags,
    )
