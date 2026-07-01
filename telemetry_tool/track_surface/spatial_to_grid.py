"""
track_surface/spatial_to_grid.py
--------------------------------
Resample the conditions-engine meteo spatial field (SpatialMuModifier.
factor_field_2d, on the ElevationSurface lattice ~5m x 1m) onto a target
grip lattice (GripSurface s_bins/n_bins ~2m x 0.5m). The single
co-registration point between the weather mesh and the grip mesh.

Returns None whenever no 2D field exists, so callers fall back to a uniform
1.0 modifier (no spatial variation) — works for every track.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def _bilinear(src_s, src_n, grid, out_s, out_n):
    """Bilinear sample of grid(len(src_s), len(src_n)) at the outer product
    out_s x out_n, clamped to the source domain (no extrapolation)."""
    s_c = np.clip(out_s, src_s[0], src_s[-1])
    n_c = np.clip(out_n, src_n[0], src_n[-1])
    si = np.clip(np.searchsorted(src_s, s_c) - 1, 0, len(src_s) - 2)
    ni = np.clip(np.searchsorted(src_n, n_c) - 1, 0, len(src_n) - 2)
    out = np.empty((len(out_s), len(out_n)), dtype=float)
    for a, (s_val, i) in enumerate(zip(s_c, si)):
        s0, s1 = src_s[i], src_s[i + 1]
        ws = 0.0 if s1 == s0 else (s_val - s0) / (s1 - s0)
        for b, (n_val, j) in enumerate(zip(n_c, ni)):
            n0, n1 = src_n[j], src_n[j + 1]
            wn = 0.0 if n1 == n0 else (n_val - n0) / (n1 - n0)
            v00, v10 = grid[i, j], grid[i + 1, j]
            v01, v11 = grid[i, j + 1], grid[i + 1, j + 1]
            out[a, b] = (v00 * (1 - ws) * (1 - wn) + v10 * ws * (1 - wn)
                         + v01 * (1 - ws) * wn + v11 * ws * wn)
    return out


def resample_spatial_to_grid(modifier, s_bins: np.ndarray, n_bins: np.ndarray) -> np.ndarray | None:
    """SpatialMuModifier (or any object with factor_field_2d / tile_* fields)
    -> (len(s_bins), len(n_bins)) factor array on the grip lattice. None when
    the 2D field is absent or malformed."""
    if modifier is None:
        return None
    fg = getattr(modifier, "factor_field_2d", None)
    ts = getattr(modifier, "tile_arclength_samples", None)
    tn = getattr(modifier, "tile_lateral_offsets", None)
    shape = getattr(modifier, "tile_grid_shape", None)
    if fg is None or ts is None or tn is None or shape is None:
        return None
    M_s, M_n = int(shape[0]), int(shape[1])
    arr = np.asarray(fg, dtype=float)
    if arr.size != M_s * M_n or len(ts) != M_s or len(tn) != M_n or M_s < 2 or M_n < 2:
        logger.warning("spatial_to_grid: malformed 2D field (shape %s, size %d) — skipping",
                       shape, arr.size)
        return None
    grid = arr.reshape(M_s, M_n)
    src_s = np.asarray(ts, dtype=float)
    src_n = np.asarray(tn, dtype=float)
    return _bilinear(src_s, src_n, grid, np.asarray(s_bins, float), np.asarray(n_bins, float))
