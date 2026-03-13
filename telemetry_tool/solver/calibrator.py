# telemetry_tool/solver/calibrator.py
"""Multi-parameter calibration loop for the OCP solver.

Adjusts mu_ref, P_max, F_brake_max by comparing OCP predictions
to the driver's actual session data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Result of the calibration loop."""
    mu_ref_initial: float
    mu_ref_final: float
    P_max_initial: float
    P_max_final: float
    F_brake_initial: float
    F_brake_final: float
    passes: int
    residual_pct: float

    def to_dict(self) -> dict:
        import dataclasses
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in dataclasses.asdict(self).items()}


def calibrate_params(
    mu_ref: float,
    P_max: float,
    F_brake_max: float,
    actual_apex_speeds: list[float],
    theoretical_apex_speeds: list[float],
    actual_straight_end_speeds: list[float],
    theoretical_straight_end_speeds: list[float],
    actual_braking_dists: list[float],
    theoretical_braking_dists: list[float],
) -> CalibrationResult:
    """Single-pass parameter adjustment: compare actual vs. theoretical.

    Adjusts mu_ref (from apex speeds), P_max (from straight-end speeds),
    F_brake_max (from braking distances) using ratio-based scaling.
    The caller (Celery task) handles the re-solve + convergence loop.

    Returns CalibrationResult with initial and final values + residual.
    """
    mu_initial = mu_ref
    P_initial = P_max
    F_initial = F_brake_max
    adjustments = []

    # Grip calibration from apex speeds (truncate to equal length)
    n_apex = min(len(actual_apex_speeds), len(theoretical_apex_speeds))
    if n_apex > 0:
        actual_arr = np.array(actual_apex_speeds[:n_apex])
        theo_arr = np.array(theoretical_apex_speeds[:n_apex])
        valid = (theo_arr > 1.0) & (actual_arr > 1.0)
        if valid.sum() > 0:
            # v_apex ~ sqrt(mu), so mu_ratio = (v_actual / v_theo)^2
            speed_ratio = float(np.mean(actual_arr[valid] / theo_arr[valid]))
            mu_ratio = speed_ratio ** 2
            mu_ref *= mu_ratio
            adjustments.append(f"mu_ref *= {mu_ratio:.3f}")

    # Power calibration from straight-end speeds (truncate to equal length)
    n_straight = min(len(actual_straight_end_speeds), len(theoretical_straight_end_speeds))
    if n_straight > 0:
        actual_arr = np.array(actual_straight_end_speeds[:n_straight])
        theo_arr = np.array(theoretical_straight_end_speeds[:n_straight])
        valid = (theo_arr > 1.0) & (actual_arr > 1.0)
        if valid.sum() > 0:
            ratio = float(np.mean(actual_arr[valid] / theo_arr[valid]))
            # P ~ v^3 for drag-limited top speed
            P_ratio = ratio ** 3
            P_max *= P_ratio
            adjustments.append(f"P_max *= {P_ratio:.3f}")

    # Braking calibration from braking distances (truncate to equal length)
    n_brake = min(len(actual_braking_dists), len(theoretical_braking_dists))
    if n_brake > 0:
        actual_arr = np.array(actual_braking_dists[:n_brake])
        theo_arr = np.array(theoretical_braking_dists[:n_brake])
        valid = (theo_arr > 1.0) & (actual_arr > 1.0)
        if valid.sum() > 0:
            # Shorter actual braking = stronger brakes
            ratio = float(np.mean(theo_arr[valid] / actual_arr[valid]))
            F_brake_max *= ratio
            adjustments.append(f"F_brake *= {ratio:.3f}")

    # Compute residual (how far theoretical was from actual)
    residuals = []
    if n_apex > 0:
        residuals.extend([
            abs(a - t) / max(a, 1.0) * 100
            for a, t in zip(actual_apex_speeds[:n_apex], theoretical_apex_speeds[:n_apex])
        ])
    residual_pct = float(np.mean(residuals)) if residuals else 0.0

    logger.info("Calibration: residual=%.1f%%, adjustments=%s", residual_pct, adjustments)

    return CalibrationResult(
        mu_ref_initial=mu_initial,
        mu_ref_final=mu_ref,
        P_max_initial=P_initial,
        P_max_final=P_max,
        F_brake_initial=F_initial,
        F_brake_final=F_brake_max,
        passes=1 if adjustments else 0,
        residual_pct=residual_pct,
    )
