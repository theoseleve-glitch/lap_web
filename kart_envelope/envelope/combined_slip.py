"""
combined_slip.py
----------------
Fit the p-norm exponent for the combined-grip friction ellipse:

    (|ax| / Ax_lim(v))^p  +  (|ay| / Ay_lim(v))^p  <=  1

Supports **asymmetric** fitting: tires lose lateral grip faster under
braking than under traction, so the optimal p-norm exponent differs:
  - p_traction: typically higher (rounder boundary — more combined grip)
  - p_braking:  typically lower (tighter boundary — less combined grip)

The fitting uses boundary data (high utilisation of both axes
simultaneously) and a grid search over *p*.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_P: float = 1.6
_DEFAULT_P_TRACTION: float = 1.7
_DEFAULT_P_BRAKING: float = 1.5


@dataclass
class AsymmetricPNorm:
    """Result of asymmetric p-norm fitting.

    Attributes
    ----------
    p_combined : float
        Single symmetric fit (backward-compatible).
    p_traction : float
        Fit from traction-phase boundary data (ax > 0 + |ay| high).
    p_braking : float
        Fit from braking-phase boundary data (ax < 0 + |ay| high).
    n_boundary_traction : int
        Number of boundary points used for traction fit.
    n_boundary_braking : int
        Number of boundary points used for braking fit.
    cost_traction : float
        Residual cost of traction fit.
    cost_braking : float
        Residual cost of braking fit.
    """
    p_combined: float
    p_traction: float
    p_braking: float
    n_boundary_traction: int = 0
    n_boundary_braking: int = 0
    cost_traction: float = float("inf")
    cost_braking: float = float("inf")


def _grid_search_p(
    rx: np.ndarray,
    ry: np.ndarray,
    p_lo: float,
    p_hi: float,
    p_step: float,
    default: float,
) -> tuple[float, float]:
    """Grid-search for best p-norm exponent. Returns (p, cost)."""
    best_p = default
    best_cost = float("inf")
    for p_candidate in np.arange(p_lo, p_hi + 0.5 * p_step, p_step):
        residual = rx ** p_candidate + ry ** p_candidate - 1.0
        cost = float(np.mean(residual ** 2))
        if cost < best_cost:
            best_cost = cost
            best_p = float(p_candidate)
    return best_p, best_cost


def _prepare_normalised(
    speeds: np.ndarray,
    a_long: np.ndarray,
    a_lat: np.ndarray,
    ax_max_fn,
    ay_max_fn,
    braking_max_fn,
):
    """Normalise accelerations by their speed-dependent limits."""
    mask = np.isfinite(speeds) & np.isfinite(a_long) & np.isfinite(a_lat)
    v = speeds[mask]
    ax = a_long[mask]
    ay = a_lat[mask]

    ay_max = np.maximum(np.asarray(ay_max_fn(v), dtype=float), 0.1)
    ax_pos = ax > 0
    ax_max = np.where(
        ax_pos,
        np.asarray(ax_max_fn(v), dtype=float),
        np.asarray(braking_max_fn(v), dtype=float),
    )
    ax_max = np.maximum(ax_max, 0.1)

    rx = np.abs(ax) / ax_max
    ry = np.abs(ay) / ay_max

    return v, ax, ay, rx, ry


def _select_boundary(
    rx: np.ndarray,
    ry: np.ndarray,
    utilisation_threshold: float,
    single_axis_threshold: float,
) -> np.ndarray:
    """Boolean mask selecting boundary (high combined-utilisation) samples."""
    total_util = np.sqrt(rx ** 2 + ry ** 2)
    return (
        (total_util > utilisation_threshold)
        & (rx > single_axis_threshold)
        & (ry > single_axis_threshold)
    )


def fit_p_norm(
    speeds: np.ndarray,
    a_long: np.ndarray,
    a_lat: np.ndarray,
    ax_max_fn,   # callable(v) -> ndarray
    ay_max_fn,   # callable(v) -> ndarray
    braking_max_fn,  # callable(v) -> ndarray
    *,
    p_lo: float = 1.2,
    p_hi: float = 2.4,
    p_step: float = 0.1,
    min_boundary_points: int = 15,
    utilisation_threshold: float = 0.70,
    single_axis_threshold: float = 0.10,
) -> float:
    """Fit a single (symmetric) combined-slip p-norm exponent.

    For asymmetric fitting (separate braking/traction), use
    ``fit_asymmetric_p_norm`` instead.

    Returns
    -------
    float
        Fitted p-norm exponent.
    """
    result = fit_asymmetric_p_norm(
        speeds, a_long, a_lat,
        ax_max_fn, ay_max_fn, braking_max_fn,
        p_lo=p_lo, p_hi=p_hi, p_step=p_step,
        min_boundary_points=min_boundary_points,
        utilisation_threshold=utilisation_threshold,
        single_axis_threshold=single_axis_threshold,
    )
    return result.p_combined


def fit_asymmetric_p_norm(
    speeds: np.ndarray,
    a_long: np.ndarray,
    a_lat: np.ndarray,
    ax_max_fn,
    ay_max_fn,
    braking_max_fn,
    *,
    p_lo: float = 1.2,
    p_hi: float = 2.4,
    p_step: float = 0.1,
    min_boundary_points: int = 15,
    utilisation_threshold: float = 0.70,
    single_axis_threshold: float = 0.10,
) -> AsymmetricPNorm:
    """Fit separate p-norm exponents for traction and braking phases.

    Real tires lose lateral grip faster under braking (longitudinal slip
    competes with lateral slip more aggressively) than under traction.
    This produces an asymmetric friction boundary:
      - p_traction is typically higher (1.6–2.0): rounder, more combined grip
      - p_braking is typically lower (1.3–1.6): tighter, less combined grip

    Algorithm
    ---------
    1. Normalise all samples by speed-dependent limits.
    2. Select boundary samples (high combined utilisation).
    3. Split boundary into traction (ax > 0) and braking (ax < 0).
    4. Fit p separately for each phase via grid search.
    5. Fit a single symmetric p from all boundary data as fallback.

    Parameters
    ----------
    speeds, a_long, a_lat : np.ndarray
        Observed telemetry triplets (same length).
    ax_max_fn, ay_max_fn, braking_max_fn
        Callables returning max accel/decel at given speed(s).
    p_lo, p_hi, p_step
        Grid search range for p.
    min_boundary_points
        Minimum boundary samples per phase for a valid fit.

    Returns
    -------
    AsymmetricPNorm
        Contains p_combined, p_traction, p_braking plus diagnostics.
    """
    v, ax, ay, rx, ry = _prepare_normalised(
        speeds, a_long, a_lat, ax_max_fn, ay_max_fn, braking_max_fn,
    )

    if len(v) < min_boundary_points:
        logger.info(
            "Too few samples (%d) for p-norm fit; using defaults "
            "(p=%.1f, p_trac=%.1f, p_brake=%.1f).",
            len(v), _DEFAULT_P, _DEFAULT_P_TRACTION, _DEFAULT_P_BRAKING,
        )
        return AsymmetricPNorm(
            p_combined=_DEFAULT_P,
            p_traction=_DEFAULT_P_TRACTION,
            p_braking=_DEFAULT_P_BRAKING,
        )

    boundary = _select_boundary(rx, ry, utilisation_threshold, single_axis_threshold)
    n_boundary = int(boundary.sum())

    if n_boundary < min_boundary_points:
        logger.info(
            "Only %d boundary points (need %d); using defaults.",
            n_boundary, min_boundary_points,
        )
        return AsymmetricPNorm(
            p_combined=_DEFAULT_P,
            p_traction=_DEFAULT_P_TRACTION,
            p_braking=_DEFAULT_P_BRAKING,
        )

    # ── Symmetric fit (all boundary data) ──
    rx_b = rx[boundary]
    ry_b = ry[boundary]
    p_combined, cost_combined = _grid_search_p(
        rx_b, ry_b, p_lo, p_hi, p_step, _DEFAULT_P,
    )

    # ── Split into traction and braking phases ──
    ax_boundary = ax[boundary]
    trac_mask = ax_boundary > 0.0
    brake_mask = ax_boundary < 0.0

    n_trac = int(trac_mask.sum())
    n_brake = int(brake_mask.sum())

    # Fit traction phase
    if n_trac >= min_boundary_points:
        p_traction, cost_trac = _grid_search_p(
            rx_b[trac_mask], ry_b[trac_mask],
            p_lo, p_hi, p_step, _DEFAULT_P_TRACTION,
        )
    else:
        # Fall back: traction p slightly above combined p
        p_traction = min(p_combined + 0.1, p_hi)
        cost_trac = float("inf")
        logger.debug(
            "Only %d traction boundary points; using p_traction=%.2f (combined+0.1).",
            n_trac, p_traction,
        )

    # Fit braking phase
    if n_brake >= min_boundary_points:
        p_braking, cost_brake = _grid_search_p(
            rx_b[brake_mask], ry_b[brake_mask],
            p_lo, p_hi, p_step, _DEFAULT_P_BRAKING,
        )
    else:
        # Fall back: braking p slightly below combined p
        p_braking = max(p_combined - 0.1, p_lo)
        cost_brake = float("inf")
        logger.debug(
            "Only %d braking boundary points; using p_braking=%.2f (combined-0.1).",
            n_brake, p_braking,
        )

    logger.info(
        "Asymmetric p-norm fit: p_combined=%.2f, p_traction=%.2f (%d pts, cost=%.4f), "
        "p_braking=%.2f (%d pts, cost=%.4f).",
        p_combined, p_traction, n_trac, cost_trac,
        p_braking, n_brake, cost_brake,
    )

    return AsymmetricPNorm(
        p_combined=p_combined,
        p_traction=p_traction,
        p_braking=p_braking,
        n_boundary_traction=n_trac,
        n_boundary_braking=n_brake,
        cost_traction=cost_trac,
        cost_braking=cost_brake,
    )
