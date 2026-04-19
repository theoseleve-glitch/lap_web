"""
track_surface/attitude_correction.py
------------------------------------
Apply road-attitude correction to observed kart-frame demand.

This module wires together the existing ``phone_mount_estimator`` and
``road_attitude_estimator`` and provides a single high-level call that
takes raw 3-axis phone IMU + GPS and returns *both* the original and the
attitude-corrected lateral/longitudinal accelerations, with a per-sample
mask describing where the correction was applied.

Important: this is a **demand-cleaning correction path**, not a new
product semantics layer.

    "This pipeline estimates observed vehicle demand from phone/GPS data.
     It does not estimate tire-road friction coefficient or surface grip
     potential."

The corrected signals subtract the gravity component induced by an
estimated road bank/grade. They are still observed-demand quantities, not
friction coefficients.

Correction rule (per sample i):
    if attitude_quality[i] > MIN_ATTITUDE_QUALITY_FOR_CORRECTION
       and not unstable_segments[i]:
        alat_corrected[i] = alat_raw[i] - sin(bank[i])
        along_corrected[i] = along_raw[i] + sin(grade[i])
    else:
        alat_corrected[i] = alat_raw[i]      # leave raw — no interpolation
        along_corrected[i] = along_raw[i]    # leave raw — no zero-fill
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from phone_mount_estimator import PhoneMountEstimate, estimate_phone_mount
from road_attitude_estimator import RoadAttitudeEstimate, estimate_road_attitude

logger = logging.getLogger(__name__)

# ── Configuration constants (no magic numbers in callers) ──────────────

# Per-sample attitude_quality must exceed this to apply correction.
# Below this threshold the raw demand is preserved unchanged.
MIN_ATTITUDE_QUALITY_FOR_CORRECTION: float = 0.4

# Conservative clamps on the attitude estimates fed into correction. These
# match the defaults inside ``road_attitude_estimator`` and exist here so
# integration callers can reference a single source of truth.
BANK_CORRECTION_CLAMP_DEG: float = 12.0
GRADE_CORRECTION_CLAMP_DEG: float = 10.0

# Master toggle. Off → return raw passthrough with a stub diagnostic block.
# On → run mount + attitude estimation and apply corrections per the rule.
ATTITUDE_CORRECTION_ENABLED: bool = True

# Minimum samples required to even attempt mount/attitude estimation.
# Below this, callers get raw passthrough with a low-data flag.
_MIN_SAMPLES_FOR_ESTIMATION: int = 50


@dataclass
class AttitudeCorrectionResult:
    """Output of :func:`apply_attitude_correction`.

    Both raw and corrected arrays are preserved so downstream code can
    compare or fall back. The ``applied_mask`` describes per-sample
    whether the correction was actually used (True) or skipped (False).
    """

    alat_g_raw: np.ndarray              # (N,) original kart-frame lateral accel (G)
    alat_g_corrected: np.ndarray        # (N,) attitude-corrected lateral accel (G)
    along_g_raw: np.ndarray             # (N,) original kart-frame longitudinal accel (G)
    along_g_corrected: np.ndarray       # (N,) attitude-corrected longitudinal accel (G)
    applied_mask: np.ndarray            # (N,) bool — True where correction was used
    mount_estimate: Optional[PhoneMountEstimate] = None
    attitude_estimate: Optional[RoadAttitudeEstimate] = None
    diagnostics: dict = field(default_factory=dict)


def apply_attitude_correction(
    accel: np.ndarray,
    gyro: np.ndarray,
    gps_speed: np.ndarray,
    timestamps: np.ndarray,
    *,
    alat_g_kart: Optional[np.ndarray] = None,
    along_g_kart: Optional[np.ndarray] = None,
    gps_heading: Optional[np.ndarray] = None,
    curvature: Optional[np.ndarray] = None,
    mount_estimate: Optional[PhoneMountEstimate] = None,
    min_attitude_quality: float = MIN_ATTITUDE_QUALITY_FOR_CORRECTION,
    enabled: bool = ATTITUDE_CORRECTION_ENABLED,
) -> AttitudeCorrectionResult:
    """Estimate road attitude and apply gravity-removal to kart-frame demand.

    Parameters
    ----------
    accel : (N, 3) phone-frame accelerometer (G)
    gyro : (N, 3) phone-frame gyroscope (deg/s)
    gps_speed : (N,) GPS speed (m/s)
    timestamps : (N,) seconds
    alat_g_kart : optional (N,) precomputed kart-frame lateral accel (G).
        If None, derived from accel + estimated mount rotation.
    along_g_kart : optional (N,) precomputed kart-frame longitudinal accel (G).
        If None, derived from accel + estimated mount rotation.
    gps_heading : optional (N,) bearing in radians (or degrees — we accept either)
    curvature : optional (N,) signed curvature (1/m); helps bank observability
    min_attitude_quality : per-sample quality threshold for applying correction
    enabled : master toggle (False → raw passthrough)

    Returns
    -------
    AttitudeCorrectionResult
    """
    accel = np.asarray(accel, dtype=float)
    gyro = np.asarray(gyro, dtype=float)
    gps_speed = np.asarray(gps_speed, dtype=float)
    timestamps = np.asarray(timestamps, dtype=float)
    n = len(accel)

    # ── Resolve raw kart-frame channels ──
    # If caller didn't supply, we fall back to phone-frame (post-mount they'll
    # be in kart frame; for the disabled / low-data paths we still need
    # *something* to return as "raw").
    if alat_g_kart is None:
        # Phone Y is approximately lateral for the typical landscape mount.
        # This is a placeholder; the proper kart-frame value is derived after
        # the mount estimate runs (below).
        alat_g_kart = accel[:, 1] if accel.ndim == 2 and accel.shape[1] >= 2 else np.zeros(n)
    if along_g_kart is None:
        along_g_kart = accel[:, 0] if accel.ndim == 2 and accel.shape[1] >= 1 else np.zeros(n)

    alat_g_raw = np.asarray(alat_g_kart, dtype=float).copy()
    along_g_raw = np.asarray(along_g_kart, dtype=float).copy()

    diagnostics: dict = {
        'enabled': bool(enabled),
        'n_samples': int(n),
        'min_attitude_quality_for_correction': float(min_attitude_quality),
        'mean_estimated_bank_deg': 0.0,
        'mean_estimated_grade_deg': 0.0,
        'attitude_correction_active_frac': 0.0,
        'attitude_low_confidence_frac': 0.0,
        'attitude_unstable_frac': 0.0,
        'mean_abs_delta_alat_g': 0.0,
        'mean_abs_delta_along_g': 0.0,
        'mean_abs_delta_combined_g': 0.0,
    }

    # ── Disabled or insufficient data: raw passthrough ──
    if not enabled or n < _MIN_SAMPLES_FOR_ESTIMATION:
        diagnostics['skipped_reason'] = 'disabled' if not enabled else 'insufficient_samples'
        return AttitudeCorrectionResult(
            alat_g_raw=alat_g_raw,
            alat_g_corrected=alat_g_raw.copy(),
            along_g_raw=along_g_raw,
            along_g_corrected=along_g_raw.copy(),
            applied_mask=np.zeros(n, dtype=bool),
            mount_estimate=None,
            attitude_estimate=None,
            diagnostics=diagnostics,
        )

    # ── Estimate phone mount (or use the one the caller already computed) ──
    # In production the mount estimate is shared across all laps in a session,
    # so callers should compute it once on a calm segment and pass it in here
    # rather than re-estimating per lap.
    try:
        if mount_estimate is None:
            mount_estimate = estimate_phone_mount(accel, gyro, gps_speed, timestamps)
    except Exception as exc:
        logger.warning("Mount estimation failed: %s — returning raw demand", exc)
        diagnostics['skipped_reason'] = f'mount_estimation_failed: {exc}'
        return AttitudeCorrectionResult(
            alat_g_raw=alat_g_raw,
            alat_g_corrected=alat_g_raw.copy(),
            along_g_raw=along_g_raw,
            along_g_corrected=along_g_raw.copy(),
            applied_mask=np.zeros(n, dtype=bool),
            mount_estimate=None,
            attitude_estimate=None,
            diagnostics=diagnostics,
        )

    # If the caller didn't supply kart-frame channels, derive them from the
    # mount rotation now that we have one. (This keeps the "raw" baseline
    # comparable to the corrected output.)
    if alat_g_kart is None or along_g_kart is None:
        accel_kart = accel @ mount_estimate.R_phone_to_kart.T
        if alat_g_kart is None:
            alat_g_raw = accel_kart[:, 1].copy()      # kart y = lateral (left)
        if along_g_kart is None:
            along_g_raw = accel_kart[:, 0].copy()     # kart x = forward

    # Optional GPS heading: convert degrees → radians if it looks like degrees.
    heading_rad: Optional[np.ndarray] = None
    if gps_heading is not None:
        h = np.asarray(gps_heading, dtype=float)
        if np.nanmax(np.abs(h)) > 2 * np.pi + 0.1:    # degrees, not radians
            h = np.deg2rad(h)
        heading_rad = h

    # ── Estimate road attitude ──
    try:
        attitude = estimate_road_attitude(
            accel, gyro, gps_speed, timestamps, mount_estimate,
            gps_heading=heading_rad,
            curvature=curvature,
            bank_max_deg=BANK_CORRECTION_CLAMP_DEG,
            grade_max_deg=GRADE_CORRECTION_CLAMP_DEG,
        )
    except Exception as exc:
        logger.warning("Road attitude estimation failed: %s — returning raw demand", exc)
        diagnostics['skipped_reason'] = f'attitude_estimation_failed: {exc}'
        return AttitudeCorrectionResult(
            alat_g_raw=alat_g_raw,
            alat_g_corrected=alat_g_raw.copy(),
            along_g_raw=along_g_raw,
            along_g_corrected=along_g_raw.copy(),
            applied_mask=np.zeros(n, dtype=bool),
            mount_estimate=mount_estimate,
            attitude_estimate=None,
            diagnostics=diagnostics,
        )

    # ── Per-sample correction with quality + stability gate ──
    quality = np.asarray(attitude.attitude_quality, dtype=float)
    unstable = np.asarray(attitude.unstable_segments, dtype=bool)
    bank_rad = np.deg2rad(np.asarray(attitude.bank_deg, dtype=float))
    grade_rad = np.deg2rad(np.asarray(attitude.grade_deg, dtype=float))

    high_quality = quality > min_attitude_quality
    applied_mask = high_quality & ~unstable

    # Subtract gravity components only on applied samples.
    # Bank: gravity_lat (kart frame) = +sin(bank) in the convention used by
    #       road_attitude_estimator. Subtracting it removes the gravity tilt
    #       contribution from observed lateral accel.
    # Grade: a_x_residual = g_lp[:, 0] - dv_dt; the gravity-x is -sin(grade),
    #        i.e. gravity pulls backward on uphill. Subtracting -sin(grade)
    #        means ADDING sin(grade) to the longitudinal demand.
    sin_bank = np.sin(bank_rad)
    sin_grade = np.sin(grade_rad)

    alat_g_corrected = alat_g_raw.copy()
    along_g_corrected = along_g_raw.copy()
    alat_g_corrected[applied_mask] = alat_g_raw[applied_mask] - sin_bank[applied_mask]
    along_g_corrected[applied_mask] = along_g_raw[applied_mask] + sin_grade[applied_mask]

    # ── Diagnostics ──
    n_applied = int(applied_mask.sum())
    n_low_q = int((~high_quality).sum())
    n_unstable = int(unstable.sum())

    delta_alat = alat_g_corrected - alat_g_raw
    delta_along = along_g_corrected - along_g_raw
    combined_raw = np.sqrt(alat_g_raw ** 2 + along_g_raw ** 2)
    combined_cor = np.sqrt(alat_g_corrected ** 2 + along_g_corrected ** 2)
    delta_combined = combined_cor - combined_raw

    high_conf_attitude = quality > min_attitude_quality
    if high_conf_attitude.any():
        mean_bank = float(np.mean(attitude.bank_deg[high_conf_attitude]))
        mean_grade = float(np.mean(attitude.grade_deg[high_conf_attitude]))
    else:
        mean_bank = float(attitude.mean_bank_deg)
        mean_grade = float(attitude.mean_grade_deg)

    diagnostics.update({
        'mean_estimated_bank_deg': mean_bank,
        'mean_estimated_grade_deg': mean_grade,
        'attitude_correction_active_frac': n_applied / n,
        'attitude_low_confidence_frac': n_low_q / n,
        'attitude_unstable_frac': n_unstable / n,
        'mean_abs_delta_alat_g': float(np.mean(np.abs(delta_alat))),
        'mean_abs_delta_along_g': float(np.mean(np.abs(delta_along))),
        'mean_abs_delta_combined_g': float(np.mean(np.abs(delta_combined))),
        'attitude_high_confidence_fraction': float(
            attitude.confidence_flags.get('high_confidence_fraction', 0.0)),
        'mount_orientation_quality': float(getattr(mount_estimate, 'orientation_quality', 0.0)),
        'mount_unstable': bool(getattr(mount_estimate, 'mount_unstable', False)),
    })

    logger.info(
        "Attitude correction: applied to %d/%d samples (%.1f%%); "
        "mean bank=%+.2f°, mean grade=%+.2f°; "
        "mean |Δalat|=%.4fG, mean |Δalong|=%.4fG",
        n_applied, n, 100.0 * n_applied / n,
        mean_bank, mean_grade,
        diagnostics['mean_abs_delta_alat_g'],
        diagnostics['mean_abs_delta_along_g'],
    )

    return AttitudeCorrectionResult(
        alat_g_raw=alat_g_raw,
        alat_g_corrected=alat_g_corrected,
        along_g_raw=along_g_raw,
        along_g_corrected=along_g_corrected,
        applied_mask=applied_mask,
        mount_estimate=mount_estimate,
        attitude_estimate=attitude,
        diagnostics=diagnostics,
    )


def merge_session_diagnostics(per_lap_diagnostics: list[dict]) -> dict:
    """Aggregate per-lap diagnostics into a single session-level summary.

    Useful for the bronze ``sensor_quality`` block where we want one
    number per session rather than per lap.
    """
    if not per_lap_diagnostics:
        return {
            'mean_estimated_bank_deg': 0.0,
            'mean_estimated_grade_deg': 0.0,
            'attitude_correction_active_frac': 0.0,
            'attitude_low_confidence_frac': 0.0,
            'attitude_unstable_frac': 0.0,
            'n_laps_analyzed': 0,
        }

    def _w_mean(key: str) -> float:
        weights = [d.get('n_samples', 0) for d in per_lap_diagnostics]
        values = [d.get(key, 0.0) for d in per_lap_diagnostics]
        total = sum(weights)
        if total <= 0:
            return float(np.mean(values)) if values else 0.0
        return float(sum(v * w for v, w in zip(values, weights)) / total)

    return {
        'mean_estimated_bank_deg': _w_mean('mean_estimated_bank_deg'),
        'mean_estimated_grade_deg': _w_mean('mean_estimated_grade_deg'),
        'attitude_correction_active_frac': _w_mean('attitude_correction_active_frac'),
        'attitude_low_confidence_frac': _w_mean('attitude_low_confidence_frac'),
        'attitude_unstable_frac': _w_mean('attitude_unstable_frac'),
        'mean_abs_delta_alat_g': _w_mean('mean_abs_delta_alat_g'),
        'mean_abs_delta_along_g': _w_mean('mean_abs_delta_along_g'),
        'mean_abs_delta_combined_g': _w_mean('mean_abs_delta_combined_g'),
        'n_laps_analyzed': len(per_lap_diagnostics),
    }
