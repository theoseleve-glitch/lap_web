"""
track_surface/boundary.py
-------------------------
Track boundary estimation from lateral scatter in Frenet coordinates.

Given multiple laps projected to (s, n), estimates track width by computing
percentile bounds of lateral offset at each distance bin.
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_DEFAULT_PERCENTILE: Final[float] = 99.0
_SMOOTH_SIGMA_BINS: Final[int] = 5


def _smooth_1d(arr: np.ndarray, sigma: int) -> np.ndarray:
    """Gaussian smooth a 1D array with reflect padding."""
    if sigma <= 0:
        return arr.copy()
    hw = 3 * sigma
    kernel = np.exp(-0.5 * (np.arange(-hw, hw + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(arr, hw, mode="reflect")
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


def estimate_boundaries(
    frenet: FrenetFrame,
    laps_sn: list[tuple[np.ndarray, np.ndarray]],
    percentile: float = _DEFAULT_PERCENTILE,
    min_laps: int = 3,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Estimate track width from lateral scatter across laps.

    Parameters
    ----------
    frenet : FrenetFrame with the centerline s-grid.
    laps_sn : list of (s, n) arrays from Frenet projection of each lap.
    percentile : percentile of lateral spread to use as boundary (e.g. 99).
    min_laps : minimum laps required for a meaningful estimate.

    Returns
    -------
    (width_left, width_right) arrays on the centerline s-grid, in metres.
    width_left is positive (distance from center to left edge).
    width_right is positive (distance from center to right edge).
    Returns None if fewer than min_laps provided.
    """
    if len(laps_sn) < min_laps:
        return None

    n_bins = frenet.n_points
    ds = frenet.s_grid[1] - frenet.s_grid[0] if n_bins > 1 else 1.0

    # Collect all n-values per s-bin
    left_max = np.full(n_bins, 3.0)   # default 3m
    right_max = np.full(n_bins, 3.0)  # default 3m
    counts = np.zeros(n_bins, dtype=int)

    for s_arr, n_arr in laps_sn:
        # Bin each sample into the nearest s-grid index
        indices = np.clip(
            np.searchsorted(frenet.s_grid, s_arr) - 1,
            0, n_bins - 1,
        ).astype(int)

        for i, n_val in zip(indices, n_arr):
            counts[i] += 1
            if n_val > 0:
                left_max[i] = max(left_max[i], n_val)
            else:
                right_max[i] = max(right_max[i], abs(n_val))

    # For bins with enough data, use percentile-based widths
    # Collect all n-values in vectorised form for percentile computation
    all_s = np.concatenate([s for s, _ in laps_sn])
    all_n = np.concatenate([n for _, n in laps_sn])
    all_idx = np.clip(
        np.searchsorted(frenet.s_grid, all_s) - 1,
        0, n_bins - 1,
    ).astype(int)

    width_left = np.full(n_bins, 3.0)
    width_right = np.full(n_bins, 3.0)

    for i in range(n_bins):
        mask = all_idx == i
        if mask.sum() < 5:
            continue
        n_vals = all_n[mask]
        pos = n_vals[n_vals > 0]
        neg = n_vals[n_vals < 0]
        if len(pos) >= 3:
            width_left[i] = float(np.percentile(pos, percentile))
        if len(neg) >= 3:
            width_right[i] = float(np.percentile(np.abs(neg), percentile))

    # Add margin: assume track extends beyond observed positions
    margin_factor = 1.3
    width_left *= margin_factor
    width_right *= margin_factor

    # Smooth to suppress noise
    width_left = _smooth_1d(width_left, _SMOOTH_SIGMA_BINS)
    width_right = _smooth_1d(width_right, _SMOOTH_SIGMA_BINS)

    return width_left, width_right
