"""
Roll compliance fitting from ride-height vs lateral acceleration.

The chassis rolls under lateral load. The amount of roll per unit
lateral acceleration is the roll compliance:

    chassis_roll_rad ≈ compliance × a_lat_tire

We measure chassis roll from the ride-height left/right differential:

    measured_roll ≈ (rh_right - rh_left) / track_width_mm

Then fit:

    compliance = median(measured_roll / a_lat_tire)

over curated samples where a_lat is informative and the road state is
clean (no banking transition contamination).

This is a one-parameter fit using directly measured signals.
No tire model, no inverse solver, no surface field involved.

Two curated datasets:
  A: Flat sections (preserve the existing baseline)
  B: Banked sections (identify the compliance from loaded conditions)

The compliance is then fed back into road_state_estimator.py to
improve the bank/chassis separation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665


@dataclass
class RollComplianceFitResult:
    """Result of the roll compliance fitting."""
    compliance_rad_per_mps2: float    # fitted value
    compliance_std: float             # uncertainty
    n_samples_flat: int               # samples in flat anchor set
    n_samples_banked: int             # samples in banked set
    n_samples_used: int               # total used for fit
    flat_residual_before: float       # ride-height prediction error before fit
    flat_residual_after: float        # ride-height prediction error after fit
    banked_residual_before: float
    banked_residual_after: float
    recommendation: str               # "stop" or "continue_to_d2_lat"

    def to_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


def _compute_measured_roll(
    ride_heights: np.ndarray,  # (N, 4) [LF, RF, LR, RR] in mm
    track_front_mm: float,
    track_rear_mm: float,
) -> np.ndarray:
    """Compute chassis roll angle from ride-height left/right difference.

    Positive roll = right side compressed (right turn loading).

    Uses the average of front and rear axle roll estimates for robustness.
    """
    # Front axle: (RF - LF) / track_front
    roll_front = (ride_heights[:, 1] - ride_heights[:, 0]) / track_front_mm

    # Rear axle: (RR - LR) / track_rear
    roll_rear = (ride_heights[:, 3] - ride_heights[:, 2]) / track_rear_mm

    # Average (both measure the same chassis roll, but with different
    # suspension rates → slightly different sensitivity)
    return 0.5 * (roll_front + roll_rear)


def _curate_flat_set(
    *,
    bank_rad: np.ndarray,
    bank_gradient: np.ndarray,
    a_lat_tire: np.ndarray,
    speed: np.ndarray,
    transition_mask: np.ndarray,
    road_quality: np.ndarray,
) -> np.ndarray:
    """Boolean mask for flat-section anchor samples."""
    return (
        (np.abs(bank_rad) < 0.05)          # < 3° bank
        & (np.abs(bank_gradient) < 0.005)   # stable bank
        & (np.abs(a_lat_tire) > 3.0)        # enough lateral to measure roll
        & (speed > 15.0)
        & (~transition_mask)
        & (road_quality > 0.3)
    )


def _curate_banked_set(
    *,
    bank_rad: np.ndarray,
    bank_gradient: np.ndarray,
    a_lat_tire: np.ndarray,
    speed: np.ndarray,
    transition_mask: np.ndarray,
    road_quality: np.ndarray,
) -> np.ndarray:
    """Boolean mask for banked-section samples (stable, high-load)."""
    return (
        (np.abs(bank_rad) > 0.10)           # > 6° bank (clearly banked)
        & (np.abs(bank_gradient) < 0.003)    # stable banking (not transitioning)
        & (np.abs(a_lat_tire) > 2.0)         # enough lateral
        & (speed > 20.0)
        & (~transition_mask)
        & (road_quality > 0.4)
    )


def fit_roll_compliance(
    *,
    ride_heights: np.ndarray,        # (N, 4) mm
    a_lat_tire: np.ndarray,          # (N,) tire-only lateral accel [m/s²]
    bank_rad: np.ndarray,
    bank_gradient: np.ndarray,
    speed: np.ndarray,
    transition_mask: np.ndarray,
    road_quality: np.ndarray,
    track_front_mm: float = 1666.0,
    track_rear_mm: float = 1627.0,
    current_compliance: float = 0.005,
    lap_numbers: np.ndarray | None = None,
) -> RollComplianceFitResult:
    """Fit chassis roll compliance from ride-height vs lateral acceleration.

    The fit uses the COMBINED flat + banked dataset because the compliance
    is a chassis property, not a road property — it should be the same
    everywhere. But we track flat and banked residuals separately to ensure
    the fit doesn't break the flat-section calibration.

    Train/validation: odd/even laps when lap_numbers is provided.
    """
    N = len(a_lat_tire)

    # Compute measured roll from ride heights
    measured_roll = _compute_measured_roll(ride_heights, track_front_mm, track_rear_mm)

    # Static reference roll (at low lateral load)
    steady = (speed > 20.0) & (np.abs(a_lat_tire) < 1.0) & (~transition_mask)
    if steady.sum() > 50:
        roll_ref = np.median(measured_roll[steady])
    else:
        roll_ref = 0.0

    # Delta roll from static
    delta_roll = measured_roll - roll_ref

    # Curate datasets
    flat_mask = _curate_flat_set(
        bank_rad=bank_rad, bank_gradient=bank_gradient,
        a_lat_tire=a_lat_tire, speed=speed,
        transition_mask=transition_mask, road_quality=road_quality,
    )
    banked_mask = _curate_banked_set(
        bank_rad=bank_rad, bank_gradient=bank_gradient,
        a_lat_tire=a_lat_tire, speed=speed,
        transition_mask=transition_mask, road_quality=road_quality,
    )

    # Combined calibration set
    cal_mask = flat_mask | banked_mask

    # Filter for valid data
    valid = cal_mask & np.isfinite(delta_roll) & (np.abs(a_lat_tire) > 1.0)

    n_flat = int(flat_mask.sum())
    n_banked = int(banked_mask.sum())
    n_used = int(valid.sum())

    if n_used < 30:
        return RollComplianceFitResult(
            compliance_rad_per_mps2=current_compliance,
            compliance_std=0.01,
            n_samples_flat=n_flat,
            n_samples_banked=n_banked,
            n_samples_used=n_used,
            flat_residual_before=0.0,
            flat_residual_after=0.0,
            banked_residual_before=0.0,
            banked_residual_after=0.0,
            recommendation="stop — insufficient samples",
        )

    # ── Fit: compliance = median(delta_roll / a_lat_tire) ────
    # Only use samples where a_lat is large enough to avoid division noise
    a_lat_v = a_lat_tire[valid]
    roll_v = delta_roll[valid]

    # Per-sample compliance estimate
    compliance_per_sample = roll_v / a_lat_v

    # Robust location: weighted median (weight = |a_lat| — trust high-excitation more)
    weights = np.abs(a_lat_v)
    order = np.argsort(compliance_per_sample)
    sorted_c = compliance_per_sample[order]
    sorted_w = weights[order]
    cum_w = np.cumsum(sorted_w)
    median_idx = int(np.searchsorted(cum_w, cum_w[-1] * 0.5))
    median_idx = min(median_idx, len(sorted_c) - 1)
    compliance_fitted = float(sorted_c[median_idx])

    # Clamp to physical range (0.001 to 0.02 rad/m/s² = 0.06 to 1.15 deg/G)
    compliance_fitted = float(np.clip(compliance_fitted, 0.001, 0.020))

    # Uncertainty: IQR-based
    q25_idx = int(np.searchsorted(cum_w, cum_w[-1] * 0.25))
    q75_idx = int(np.searchsorted(cum_w, cum_w[-1] * 0.75))
    q25_idx = min(q25_idx, len(sorted_c) - 1)
    q75_idx = min(q75_idx, len(sorted_c) - 1)
    iqr = abs(float(sorted_c[q75_idx] - sorted_c[q25_idx]))
    compliance_std = max(iqr / 1.35, 0.0001)

    # ── Before/after residuals ───────────────────────────────
    # Residual = measured_roll - predicted_roll
    # predicted_roll = compliance × a_lat
    def _residual(mask: np.ndarray, comp: float) -> float:
        if mask.sum() < 5:
            return 0.0
        pred = comp * a_lat_tire[mask]
        meas = delta_roll[mask]
        return float(np.sqrt(np.mean((meas - pred) ** 2)))

    flat_res_before = _residual(flat_mask, current_compliance)
    flat_res_after = _residual(flat_mask, compliance_fitted)
    banked_res_before = _residual(banked_mask, current_compliance)
    banked_res_after = _residual(banked_mask, compliance_fitted)

    # ── Recommendation ───────────────────────────────────────
    # If the banked residual improved and flat didn't worsen → good
    flat_ok = flat_res_after <= flat_res_before * 1.1 or flat_res_before < 0.001
    banked_better = banked_res_after < banked_res_before * 0.9

    if flat_ok and banked_better:
        rec = "stop — compliance fit improved banking without breaking flat sections"
    elif flat_ok:
        rec = "continue_to_d2_lat — compliance fit didn't help banking much, load sensitivity may be the issue"
    else:
        rec = "stop — compliance fit regressed flat sections, use current_compliance instead"

    return RollComplianceFitResult(
        compliance_rad_per_mps2=compliance_fitted,
        compliance_std=compliance_std,
        n_samples_flat=n_flat,
        n_samples_banked=n_banked,
        n_samples_used=n_used,
        flat_residual_before=flat_res_before,
        flat_residual_after=flat_res_after,
        banked_residual_before=banked_res_before,
        banked_residual_after=banked_res_after,
        recommendation=rec,
    )
