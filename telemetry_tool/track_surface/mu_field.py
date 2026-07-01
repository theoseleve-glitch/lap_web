"""
track_surface/mu_field.py
-------------------------
Builders that turn GripSurface data into solver-ready MuField grids.

The dry field sources the per-cell cornering-LIMIT grid (`mu_limit_grid`,
per-session p90) when present — see `_base_grip_grid` — falling back to the
per-cell mean for old/pre-limit sidecars. Confidence shrinkage then guards
the 2D optimizer's classic failure mode: exploiting sparse high-mu noise
cells or undriven asphalt. House rule (matches robust_ocp.py): never let the
solver see MORE grip than the trusted estimate.

  measured cell:    mu_eff = conf*mu_raw + (1-conf)*row_prior
  unmeasured cell:  mu_eff = row_prior * UNMEASURED_DISCOUNT   (also NaN cells)

where row_prior is the count-weighted mean of measured cells at that
arclength (falls back to the global measured mean).
"""
from __future__ import annotations

from typing import Final

import numpy as np

from track_surface.dense_grip import build_dense_grip_grid
from track_surface.drainage import PuddleZone, puddle_footprint_radius
from track_surface.grip_2d import GripSurface
from track_surface.wet_model import invert_grip_for_wet
from lap_oracle.solver.ocp_2d import MuField

# Domain-judgment constants — flagged in the plan as a tuning point.
UNMEASURED_DISCOUNT: Final[float] = 0.95   # 5% pessimism on undriven asphalt
_GLOBAL_PRIOR_FALLBACK: Final[float] = 1.0  # nothing measured at all


def shrink_mu_grid(
    mu_grid: np.ndarray,
    count_grid: np.ndarray,
    confidence: np.ndarray,
) -> np.ndarray:
    """Confidence-shrunk friction grid (same shape as mu_grid)."""
    # A cell is "measured" only if it has samples AND a finite value. The limit
    # grid carries NaN below its sample floor; those cells take the prior path.
    measured = (count_grid > 0) & np.isfinite(mu_grid)

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
PUDDLE_MU: Final[float] = 0.2  # standing water — domain-judgment constant
_WET_MU_FLOOR: Final[float] = 0.2
_WET_MU_CEIL: Final[float] = 1.0


def _base_grip_grid(grip_2d: GripSurface) -> np.ndarray:
    """The grip the SOLVER should see.

    With a limit grid: each well-sampled cell uses its cornering-limit (p90);
    cells that HAD samples but fell below the limit's sample floor (NaN in the
    limit grid, but real in the mean grid) degrade to their measured MEAN — a
    conservative local estimate, never the global limit prior (which would
    OVER-state grip in sparse sections, violating "never show the solver more
    grip than the trusted estimate"). Truly-unmeasured cells (count==0) stay
    NaN and take shrink_mu_grid's unmeasured-prior path.

    Without a limit grid (old sidecars / pre-limit builds): the per-cell mean.
    """
    if grip_2d.mu_limit_grid is None:
        return grip_2d.mu_grid
    base = grip_2d.mu_limit_grid.copy()
    gap = ~np.isfinite(base) & (grip_2d.count_grid > 0)
    base[gap] = grip_2d.mu_grid[gap]
    return base


def build_dry_mu_field(
    grip_2d: GripSurface,
    spatial: np.ndarray | None = None,
    condition_factor: float = 1.0,
) -> MuField:
    """Solver-ready DRY field: the dense, full-width grip (build_dense_grip_grid)
    — measured where driven, row-p90 level × spatial meteo-extended where
    undriven. ``spatial`` is the meteo factor field resampled to this grip
    lattice (None -> uniform 1.0); ``condition_factor`` scales the undriven
    level (1.0 = measured condition).

    The dense builder already (a) fills every cell finite, (b) caps grip to
    [0.1, 2.5], and (c) confidence-blends low-count cells toward the robust
    row level — it supersedes shrink_mu_grid for the dry path.
    shrink_mu_grid's count-gated undriven branch (count==0 → row_mean×0.95)
    would OVERWRITE the dense off-line fill and discard the spatial, defeating
    Part A's purpose. So the dense grid is returned directly.
    shrink_mu_grid remains the correct path for the sparse wet grid."""
    # The dense builder already fills the full width (measured on the line,
    # row-p90 level extended + spatial off-line), caps grip, and confidence-
    # blends low-count cells toward the robust row level. It supersedes
    # shrink_mu_grid, whose count-gated undriven branch would OVERWRITE the
    # dense off-line fill (and discard the spatial) — the exact cells Part A
    # exists to populate. So return the dense grid directly.
    dense = build_dense_grip_grid(grip_2d, spatial=spatial, condition_factor=condition_factor)
    return MuField(
        s_bins=grip_2d.s_bins.copy(),
        n_bins=grip_2d.n_bins.copy(),
        mu_grid=dense,
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

    Note: s-windows/footprints do NOT wrap across start/finish; a puddle
    straddling s=0 is handled one-sided (consistent with
    puddles_to_n_windows); revisit if real data shows start/finish puddles.
    """
    wet_grid = invert_grip_for_wet(grip_2d)
    wet_grid = shrink_mu_grid(wet_grid, grip_2d.count_grid, grip_2d.confidence)
    # Re-clip: shrinkage's unmeasured-cell path (row_prior * 0.95) can emit
    # values below 0.2 when the wet row prior already sits at the floor.
    wet_grid = np.clip(wet_grid, _WET_MU_FLOOR, _WET_MU_CEIL)

    if puddles:
        ss, nn = np.meshgrid(grip_2d.s_bins, grip_2d.n_bins, indexing="ij")
        for p in puddles:
            radius_m = puddle_footprint_radius(p, grip_2d.s_bins, grip_2d.n_bins)
            inside = (ss - p.s_center) ** 2 + (nn - p.n_center) ** 2 <= radius_m ** 2
            wet_grid = np.where(inside, np.minimum(wet_grid, PUDDLE_MU), wet_grid)

    return MuField(
        s_bins=grip_2d.s_bins.copy(),
        n_bins=grip_2d.n_bins.copy(),
        mu_grid=wet_grid,
    )
