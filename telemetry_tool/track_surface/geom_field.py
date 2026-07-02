"""(s, n) geometry grids for the quasi-3D solver (spec §4 B1).

Derives, from the accumulated ElevationSurface z(s,n):
  kv_grid      vertical curvature d2z/ds2 per cell (passthrough)
  camber_grid  SIGNED lateral slope arctan(dz/dn), radians
  grade_grid   longitudinal slope arctan(dz/ds), radians
Unmeasured cells are filled with their row's measured mean BEFORE
differentiation so off-line lookups degrade to the row average — the solver
must never see NaN or an artificial cliff at the measured/unmeasured seam.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class GeomField:
    s_bins: np.ndarray
    n_bins: np.ndarray
    kv_grid: np.ndarray
    camber_grid: np.ndarray
    grade_grid: np.ndarray


def build_geom_field(elev, *, min_count: int = 1) -> GeomField | None:
    if elev is None:
        return None
    s = np.asarray(elev.s_bins, dtype=float)
    n = np.asarray(elev.n_bins, dtype=float)
    z = np.asarray(elev.z_grid, dtype=float).copy()
    kv = np.asarray(elev.kv_grid, dtype=float).copy()
    counts = np.asarray(elev.count_grid)
    if len(s) < 2 or len(n) < 2 or z.shape != (len(s), len(n)):
        return None

    measured = counts >= min_count
    for i in range(z.shape[0]):
        row_meas = measured[i]
        if row_meas.any():
            fill = float(z[i, row_meas].mean())
            kv_fill = float(kv[i, row_meas].mean())
        else:
            fill, kv_fill = 0.0, 0.0
        z[i, ~row_meas] = fill
        kv[i, ~row_meas] = kv_fill

    dz_dn = np.gradient(z, n, axis=1)
    dz_ds = np.gradient(z, s, axis=0)
    return GeomField(
        s_bins=s, n_bins=n, kv_grid=kv,
        camber_grid=np.arctan(dz_dn),
        grade_grid=np.arctan(dz_ds),
    )
