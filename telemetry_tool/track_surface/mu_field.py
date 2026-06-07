"""
track_surface/mu_field.py
-------------------------
Builders that turn GripSurface data into solver-ready MuField grids.

Confidence shrinkage guards the 2D optimizer's classic failure mode:
exploiting sparse high-mu noise cells or undriven asphalt.  House rule
(matches robust_ocp.py): never let the solver see MORE grip than the
trusted estimate.

  measured cell:    mu_eff = conf*mu_raw + (1-conf)*row_prior
  unmeasured cell:  mu_eff = row_prior * UNMEASURED_DISCOUNT

where row_prior is the count-weighted mean of measured cells at that
arclength (falls back to the global measured mean).
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from track_surface.grip_2d import GripSurface
from telemetry_tool.lap_oracle.solver.ocp_2d import MuField

logger = logging.getLogger(__name__)

# Domain-judgment constants — flagged in the plan as a tuning point.
UNMEASURED_DISCOUNT: Final[float] = 0.95   # 5% pessimism on undriven asphalt
_GLOBAL_PRIOR_FALLBACK: Final[float] = 1.0  # nothing measured at all


def shrink_mu_grid(
    mu_grid: np.ndarray,
    count_grid: np.ndarray,
    confidence: np.ndarray,
) -> np.ndarray:
    """Confidence-shrunk friction grid (same shape as mu_grid)."""
    measured = count_grid > 0

    # Global prior: count-weighted mean over all measured cells
    if measured.any():
        global_prior = float(
            np.average(mu_grid[measured], weights=count_grid[measured])
        )
    else:
        global_prior = _GLOBAL_PRIOR_FALLBACK

    # Per-row (per-s) prior: count-weighted mean of measured cells in the row
    M = mu_grid.shape[0]
    row_prior = np.full(M, global_prior)
    for i in range(M):
        row_measured = measured[i]
        if row_measured.any():
            row_prior[i] = float(
                np.average(mu_grid[i, row_measured], weights=count_grid[i, row_measured])
            )

    prior_2d = row_prior[:, None]                       # broadcast (M, 1)
    w = np.clip(confidence, 0.0, 1.0)
    out = w * mu_grid + (1.0 - w) * prior_2d            # measured blend
    out = np.where(measured, out, prior_2d * UNMEASURED_DISCOUNT)
    return out
