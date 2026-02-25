"""
combined_slip.py
----------------
Fit the p-norm exponent for the combined-grip friction ellipse:

    (|ax| / Ax_lim(v))^p  +  (|ay| / Ay_lim(v))^p  <=  1

The fitting uses boundary data (high utilisation of both axes
simultaneously) and a grid search over *p*.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_P: float = 1.6


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
    """Fit the combined-slip p-norm exponent from observed (v, ax, ay).

    Algorithm
    ---------
    1. Normalise: ``rx = |ax| / ax_max(v)``, ``ry = |ay| / ay_max(v)``.
    2. Select boundary samples where ``rx^2 + ry^2 > utilisation_threshold``
       and both ``rx > single_axis_threshold`` and ``ry > single_axis_threshold``.
    3. Grid search over *p* in ``[p_lo, p_hi]``:
       minimise ``sum( (rx^p + ry^p - 1)^2 )``.
    4. Return best *p*, or ``_DEFAULT_P`` if insufficient boundary data.

    Parameters
    ----------
    speeds, a_long, a_lat : np.ndarray
        Observed data (same length).
    ax_max_fn, ay_max_fn, braking_max_fn
        Callables returning max accel at given speed(s).
    p_lo, p_hi, p_step
        Grid search range.
    min_boundary_points : int
        Minimum boundary samples needed to fit.

    Returns
    -------
    float
        Fitted p-norm exponent.
    """
    mask = np.isfinite(speeds) & np.isfinite(a_long) & np.isfinite(a_lat)
    v = speeds[mask]
    ax = a_long[mask]
    ay = a_lat[mask]

    if len(v) < min_boundary_points:
        logger.info("Too few samples (%d) for p-norm fit; using default p=%.1f.",
                     len(v), _DEFAULT_P)
        return _DEFAULT_P

    # Normalise
    ay_max = np.asarray(ay_max_fn(v), dtype=float)
    ax_pos = ax > 0
    ax_max = np.where(ax_pos,
                       np.asarray(ax_max_fn(v), dtype=float),
                       np.asarray(braking_max_fn(v), dtype=float))

    # Avoid division by zero
    ax_max = np.maximum(ax_max, 0.1)
    ay_max = np.maximum(ay_max, 0.1)

    rx = np.abs(ax) / ax_max
    ry = np.abs(ay) / ay_max

    # Boundary selection
    total_util = np.sqrt(rx ** 2 + ry ** 2)
    boundary = ((total_util > utilisation_threshold)
                & (rx > single_axis_threshold)
                & (ry > single_axis_threshold))

    n_boundary = int(boundary.sum())
    if n_boundary < min_boundary_points:
        logger.info("Only %d boundary points (need %d); using default p=%.1f.",
                     n_boundary, min_boundary_points, _DEFAULT_P)
        return _DEFAULT_P

    rx_b = rx[boundary]
    ry_b = ry[boundary]

    # Grid search
    best_p = _DEFAULT_P
    best_cost = float("inf")

    for p_candidate in np.arange(p_lo, p_hi + 0.5 * p_step, p_step):
        residual = rx_b ** p_candidate + ry_b ** p_candidate - 1.0
        cost = float(np.mean(residual ** 2))
        if cost < best_cost:
            best_cost = cost
            best_p = float(p_candidate)

    logger.info("Fitted p-norm exponent: %.2f (boundary pts=%d, cost=%.4f).",
                 best_p, n_boundary, best_cost)
    return best_p
