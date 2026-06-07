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

from typing import Final

import numpy as np

from track_surface.grip_2d import GripSurface
from telemetry_tool.lap_oracle.solver.ocp_2d import MuField

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


# ---------------------------------------------------------------------------
# Solver-ready field builders
# ---------------------------------------------------------------------------
from track_surface.drainage import PuddleZone
from track_surface.wet_model import invert_grip_for_wet

PUDDLE_MU: Final[float] = 0.2  # standing water — domain-judgment constant
_WET_MU_FLOOR: Final[float] = 0.2
_WET_MU_CEIL: Final[float] = 1.0


def build_dry_mu_field(grip_2d: GripSurface) -> MuField:
    """Solver-ready dry field: raw 2D grip with confidence shrinkage."""
    return MuField(
        s_bins=grip_2d.s_bins.copy(),
        n_bins=grip_2d.n_bins.copy(),
        mu_grid=shrink_mu_grid(
            grip_2d.mu_grid, grip_2d.count_grid, grip_2d.confidence
        ),
    )


def build_wet_mu_field(
    grip_2d: GripSurface,
    puddles: list[PuddleZone],
) -> MuField:
    """Solver-ready wet field.

    1. Invert the dry rubber line (wet_model.invert_grip_for_wet — high
       dry mu means rubber, slick when wet; returns values in [0.2, 1]).
    2. Shrink by the SAME dry confidence grids (wet is derived from dry
       observations, so dry sample density is its provenance).
    3. Re-clip to the wet envelope: shrinkage's unmeasured-cell discount
       (row_prior * 0.95) can dip below the 0.2 floor when a row's wet
       prior sits at the floor.
    4. Clamp puddle zones to PUDDLE_MU within the puddle's footprint
       radius r = sqrt(area_cells * cell_area / pi).
    """
    wet_grid = invert_grip_for_wet(grip_2d)
    wet_grid = shrink_mu_grid(wet_grid, grip_2d.count_grid, grip_2d.confidence)
    # Re-clip: shrinkage's unmeasured-cell path (row_prior * 0.95) can emit
    # values below 0.2 when the wet row prior already sits at the floor.
    wet_grid = np.clip(wet_grid, _WET_MU_FLOOR, _WET_MU_CEIL)

    if puddles:
        s_step = float(np.median(np.diff(grip_2d.s_bins))) if len(grip_2d.s_bins) > 1 else 5.0
        n_step = float(np.median(np.diff(grip_2d.n_bins))) if len(grip_2d.n_bins) > 1 else 1.0
        cell_area = s_step * n_step
        ss, nn = np.meshgrid(grip_2d.s_bins, grip_2d.n_bins, indexing="ij")
        for p in puddles:
            radius_m = max(np.sqrt(p.area_cells * cell_area / np.pi), n_step)
            inside = (ss - p.s_center) ** 2 + (nn - p.n_center) ** 2 <= radius_m ** 2
            wet_grid = np.where(inside, np.minimum(wet_grid, PUDDLE_MU), wet_grid)

    return MuField(
        s_bins=grip_2d.s_bins.copy(),
        n_bins=grip_2d.n_bins.copy(),
        mu_grid=wet_grid,
    )
