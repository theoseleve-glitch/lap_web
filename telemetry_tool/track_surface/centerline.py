"""
track_surface/centerline.py
----------------------------
Multi-lap centerline extraction with B-spline fitting.

Given position data from multiple laps, produces a smooth track centerline
at uniform arc-length spacing.  For a single lap, applies Gaussian smoothing
directly.  For multiple laps, computes per-distance-bin medians then fits
a parametric B-spline.
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

logger = logging.getLogger(__name__)

_MIN_POINTS: Final[int] = 20


def _arc_lengths(xy: np.ndarray) -> np.ndarray:
    """Cumulative arc length along an (N, 2) path.  Returns (N,) array."""
    diffs = np.diff(xy, axis=0)
    seg_lens = np.sqrt(diffs[:, 0] ** 2 + diffs[:, 1] ** 2)
    return np.concatenate([[0.0], np.cumsum(seg_lens)])


def _resample_uniform(xy: np.ndarray, s: np.ndarray, ds: float) -> np.ndarray:
    """Resample (N, 2) path to uniform arc-length spacing ds.

    Returns (M, 2) array where M = floor(total_length / ds) + 1.
    """
    total = s[-1]
    if total < ds:
        return xy.copy()
    s_uniform = np.arange(0, total, ds)
    x_interp = np.interp(s_uniform, s, xy[:, 0])
    y_interp = np.interp(s_uniform, s, xy[:, 1])
    return np.column_stack([x_interp, y_interp])


def _gaussian_smooth_xy(xy: np.ndarray, sigma_m: float, ds: float) -> np.ndarray:
    """Apply Gaussian smoothing to an (N, 2) path.

    sigma_m is in metres; ds is the spacing between points.
    Uses reflect-mode padding to avoid edge artefacts.
    """
    if sigma_m <= 0 or ds <= 0:
        return xy.copy()
    hw = max(1, int(3 * sigma_m / ds))
    kernel = np.exp(-0.5 * (np.arange(-hw, hw + 1) * ds / sigma_m) ** 2)
    kernel /= kernel.sum()

    pad_x = np.pad(xy[:, 0], hw, mode="reflect")
    pad_y = np.pad(xy[:, 1], hw, mode="reflect")
    sx = np.convolve(pad_x, kernel, mode="valid")[: len(xy)]
    sy = np.convolve(pad_y, kernel, mode="valid")[: len(xy)]
    return np.column_stack([sx, sy])


def _align_lap_starts(
    laps: list[np.ndarray],
    ref_start: np.ndarray,
) -> list[np.ndarray]:
    """Circularly shift each lap so its closest point to ref_start is at index 0."""
    aligned = []
    for lap in laps:
        dists = np.sqrt(np.sum((lap - ref_start) ** 2, axis=1))
        shift = int(np.argmin(dists))
        aligned.append(np.roll(lap, -shift, axis=0))
    return aligned


def _fit_bspline(xy: np.ndarray, ds: float) -> tuple[np.ndarray, float]:
    """Fit a parametric B-spline and resample at ds spacing.

    Falls back to raw input if scipy is unavailable.
    Returns (centerline_xy, total_length_m).
    """
    try:
        from scipy.interpolate import splev, splprep
    except ImportError:
        logger.debug("scipy unavailable, skipping B-spline fit")
        s = _arc_lengths(xy)
        return xy.copy(), float(s[-1])

    s_param = _arc_lengths(xy)
    total = float(s_param[-1])
    if total < ds * 3:
        return xy.copy(), total

    # Normalise parameter to [0, 1]
    u = s_param / total

    # splprep needs non-duplicate u values
    mask = np.diff(u, prepend=-1) > 1e-12
    u_clean = u[mask]
    xy_clean = xy[mask]
    if len(u_clean) < 4:
        return xy.copy(), total

    try:
        tck, _ = splprep([xy_clean[:, 0], xy_clean[:, 1]], u=u_clean, s=0, k=3)
    except Exception:
        logger.debug("B-spline fit failed, using raw points")
        return xy.copy(), total

    n_out = max(int(total / ds), _MIN_POINTS)
    u_eval = np.linspace(0, 1, n_out)
    xs, ys = splev(u_eval, tck)
    result = np.column_stack([xs, ys])
    new_total = float(_arc_lengths(result)[-1])
    return result, new_total


def extract_centerline(
    laps: list[np.ndarray],
    ds_m: float = 1.0,
    smooth_sigma_m: float = 3.0,
) -> tuple[np.ndarray, float]:
    """Extract a track centerline from one or more lap trajectories.

    Parameters
    ----------
    laps : list of (N_i, 2) arrays, each a lap trajectory in (x, y) metres.
    ds_m : output uniform spacing in metres.
    smooth_sigma_m : Gaussian smoothing sigma in metres (for single-lap case).

    Returns
    -------
    (centerline_xy, total_length_m) where centerline_xy is (M, 2) at
    uniform ds_m spacing.
    """
    # Filter out degenerate laps
    valid = [lap for lap in laps if len(lap) >= _MIN_POINTS]
    if not valid:
        raise ValueError("No valid laps provided (all have < %d points)" % _MIN_POINTS)

    if len(valid) == 1:
        # Single lap: smooth and resample
        lap = valid[0]
        s = _arc_lengths(lap)
        resampled = _resample_uniform(lap, s, ds_m)
        smoothed = _gaussian_smooth_xy(resampled, smooth_sigma_m, ds_m)
        return _fit_bspline(smoothed, ds_m)

    # Multiple laps: resample each to uniform grid, align, median, fit spline
    resampled_laps = []
    for lap in valid:
        s = _arc_lengths(lap)
        resampled_laps.append(_resample_uniform(lap, s, ds_m))

    # Align starts: use first lap's start as reference
    ref_start = resampled_laps[0][0]
    aligned = _align_lap_starts(resampled_laps, ref_start)

    # Find common length (shortest after alignment)
    min_len = min(len(lap) for lap in aligned)
    if min_len < _MIN_POINTS:
        # Fall back to first lap
        return _fit_bspline(aligned[0], ds_m)

    # Truncate to common length and compute per-bin median
    stacked_x = np.array([lap[:min_len, 0] for lap in aligned])
    stacked_y = np.array([lap[:min_len, 1] for lap in aligned])
    median_x = np.median(stacked_x, axis=0)
    median_y = np.median(stacked_y, axis=0)
    median_xy = np.column_stack([median_x, median_y])

    return _fit_bspline(median_xy, ds_m)
