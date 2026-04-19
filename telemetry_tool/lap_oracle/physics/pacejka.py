"""Pacejka Magic Formula tyre model (TUM MVDC simplified form).

Provides vectorized lateral and longitudinal force computation plus a
combined-slip friction-ellipse model.  All functions accept and return
numpy arrays for direct use by the OCP solver.

Reference:
    Fy = D * Fz * sin(C * arctan(B*alpha - E*(B*alpha - arctan(B*alpha))))
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.lap_oracle.config import PacejkaParams


# -- Single-axis forces ---------------------------------------------------

def lateral_force(
    slip_angle_rad: np.ndarray,
    fz: np.ndarray,
    params: PacejkaParams,
) -> np.ndarray:
    """Lateral tyre force via Pacejka Magic Formula.

    Parameters
    ----------
    slip_angle_rad : array
        Tyre slip angle in radians.
    fz : array
        Normal load on the tyre (N).  Must broadcast with *slip_angle_rad*.
    params : PacejkaParams
        Magic Formula coefficients (B, C, D, E).

    Returns
    -------
    array
        Lateral force in Newtons (same shape as inputs).
    """
    B, C, D, E = params.B, params.C, params.D, params.E
    Bx = B * slip_angle_rad
    return D * fz * np.sin(C * np.arctan(Bx - E * (Bx - np.arctan(Bx))))


def longitudinal_force(
    slip_ratio: np.ndarray,
    fz: np.ndarray,
    params: PacejkaParams,
) -> np.ndarray:
    """Longitudinal tyre force via Pacejka Magic Formula.

    Parameters
    ----------
    slip_ratio : array
        Tyre slip ratio (dimensionless, typically -0.15 .. +0.15).
    fz : array
        Normal load on the tyre (N).
    params : PacejkaParams
        Magic Formula coefficients (B, C, D, E).

    Returns
    -------
    array
        Longitudinal force in Newtons.
    """
    B, C, D, E = params.B, params.C, params.D, params.E
    Bx = B * slip_ratio
    return D * fz * np.sin(C * np.arctan(Bx - E * (Bx - np.arctan(Bx))))


# -- Combined slip (friction ellipse) -------------------------------------

def combined_slip(
    fx0: np.ndarray,
    fy0: np.ndarray,
    slip_ratio: np.ndarray,
    slip_angle_rad: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce pure-slip forces via the friction-ellipse combined-slip model.

    sigma = sqrt(kappa^2 + tan(alpha)^2)
    fx = fx0 * kappa / sigma
    fy = fy0 * tan(alpha) / sigma

    When sigma is near zero both outputs are zero (no slip => no force).

    Parameters
    ----------
    fx0, fy0 : array
        Pure longitudinal / lateral forces (from single-axis formulae).
    slip_ratio : array
        Longitudinal slip ratio (kappa).
    slip_angle_rad : array
        Lateral slip angle in radians (alpha).

    Returns
    -------
    (fx, fy) : tuple of arrays
        Combined-slip corrected forces.
    """
    kappa = np.asarray(slip_ratio, dtype=np.float64)
    tan_alpha = np.tan(np.asarray(slip_angle_rad, dtype=np.float64))

    sigma = np.sqrt(kappa ** 2 + tan_alpha ** 2)
    # Avoid division by zero -- when sigma ~ 0 both forces are ~ 0
    safe_sigma = np.where(sigma > 1e-12, sigma, 1.0)

    fx = fx0 * kappa / safe_sigma
    fy = fy0 * tan_alpha / safe_sigma

    # Zero out where sigma was negligible
    zero_mask = sigma <= 1e-12
    fx = np.where(zero_mask, 0.0, fx)
    fy = np.where(zero_mask, 0.0, fy)

    return fx, fy


# -- Utility ---------------------------------------------------------------

def peak_mu(params: PacejkaParams) -> float:
    """Return the peak friction coefficient from the Pacejka parameters.

    In the simplified form used here, D is the peak normalised force.
    """
    return params.D
