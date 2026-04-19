"""
track_surface/drainage.py
-------------------------
Water drainage model for 3D elevation surfaces.

Computes gradient-based water flow to predict puddle accumulation zones
where standing water collects in depressions on the track surface.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from track_surface.elevation import ElevationSurface

logger = logging.getLogger(__name__)


@dataclass
class PuddleZone:
    """A zone where water accumulates on the track surface."""

    s_center: float       # distance along track (m)
    n_center: float       # lateral offset (m)
    depth_score: float    # relative depth (0-1, 1 = deepest)
    area_cells: int       # number of grid cells in the puddle

    def to_dict(self) -> dict:
        return {
            "s_center": round(self.s_center, 1),
            "n_center": round(self.n_center, 2),
            "depth_score": round(self.depth_score, 3),
            "area_cells": self.area_cells,
        }


def _follow_gradient(
    dz_ds: np.ndarray,
    dz_dn: np.ndarray,
    start_i: int,
    start_j: int,
    max_steps: int = 500,
) -> tuple[int, int]:
    """Follow the steepest-descent gradient from (start_i, start_j)
    until reaching a local minimum (no downhill neighbour).

    Returns the (i, j) index of the basin minimum.
    """
    M, K = dz_ds.shape
    ci, cj = start_i, start_j
    for _ in range(max_steps):
        # Evaluate downhill direction from gradient components
        grad_s = dz_ds[ci, cj]
        grad_n = dz_dn[ci, cj]

        # Choose step: move in the direction of steepest descent
        ni, nj = ci, cj
        if abs(grad_s) >= abs(grad_n):
            ni = ci - 1 if grad_s > 0 else ci + 1
        else:
            nj = cj - 1 if grad_n > 0 else cj + 1

        # Clamp to grid bounds
        ni = max(0, min(M - 1, ni))
        nj = max(0, min(K - 1, nj))

        # If we didn't move, we're at a local minimum
        if ni == ci and nj == cj:
            break
        ci, cj = ni, nj
    return ci, cj


def compute_drainage(elev_surface: ElevationSurface) -> list[PuddleZone]:
    """Find where water accumulates on the 3D elevation surface.

    Algorithm:
    1. Compute gradient of z_grid: (dz/ds, dz/dn) per cell.
    2. For each cell, follow the gradient downhill until reaching a
       local minimum.
    3. Cells that drain to the same minimum form a basin.
    4. Basins below a depth threshold are puddle zones.
    5. Rank by depth_score = (surrounding_z - basin_z) / max_range.

    Parameters
    ----------
    elev_surface : ElevationSurface with .z_grid (M,K),
                   .s_bins (M,), .n_bins (K,).

    Returns
    -------
    List of PuddleZone sorted by depth_score descending.
    """
    z = elev_surface.z_grid
    M, K = z.shape
    if M < 3 or K < 3:
        return []

    z_range = float(np.ptp(z))
    if z_range < 1e-9:
        return []

    # 1. Compute gradients via central finite differences
    dz_ds = np.zeros_like(z)
    dz_dn = np.zeros_like(z)
    dz_ds[1:-1, :] = (z[2:, :] - z[:-2, :]) / 2.0
    dz_ds[0, :] = z[1, :] - z[0, :]
    dz_ds[-1, :] = z[-1, :] - z[-2, :]
    dz_dn[:, 1:-1] = (z[:, 2:] - z[:, :-2]) / 2.0
    dz_dn[:, 0] = z[:, 1] - z[:, 0]
    dz_dn[:, -1] = z[:, -1] - z[:, -2]

    # 2. For each cell, follow gradient to its basin minimum
    drain_target = np.full((M, K, 2), -1, dtype=int)
    for i in range(M):
        for j in range(K):
            ti, tj = _follow_gradient(dz_ds, dz_dn, i, j)
            drain_target[i, j, 0] = ti
            drain_target[i, j, 1] = tj

    # 3. Group cells by their drain target
    basins: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i in range(M):
        for j in range(K):
            key = (int(drain_target[i, j, 0]), int(drain_target[i, j, 1]))
            basins.setdefault(key, []).append((i, j))

    # 4. Score each basin
    puddles: list[PuddleZone] = []
    min_area = 2  # need at least 2 cells for a meaningful puddle

    for (bi, bj), cells in basins.items():
        if len(cells) < min_area:
            continue

        basin_z = z[bi, bj]

        # Compute mean surrounding z of basin member cells
        cell_zs = np.array([z[ci, cj] for ci, cj in cells])
        surrounding_z = float(np.mean(cell_zs))

        depth = surrounding_z - basin_z
        if depth <= 0:
            continue

        depth_score = min(depth / z_range, 1.0)

        s_center = float(elev_surface.s_bins[bi])
        n_center = float(elev_surface.n_bins[bj])

        puddles.append(PuddleZone(
            s_center=s_center,
            n_center=n_center,
            depth_score=depth_score,
            area_cells=len(cells),
        ))

    # 5. Sort by depth_score descending
    puddles.sort(key=lambda p: p.depth_score, reverse=True)
    return puddles
