"""
track_surface/elevation.py
--------------------------
Elevation profile and camber estimation from Frenet-projected telemetry.

Averages z-values across laps at each s-bin to produce a smooth elevation
profile, then estimates lateral camber (banking angle) from the slope
of z vs n at each longitudinal position.
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_SMOOTH_SIGMA_BINS: Final[int] = 5


def _smooth_1d(arr: np.ndarray, sigma: int) -> np.ndarray:
    """Gaussian smooth with reflect padding."""
    if sigma <= 0 or len(arr) < 3:
        return arr.copy()
    hw = 3 * sigma
    kernel = np.exp(-0.5 * (np.arange(-hw, hw + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(arr, hw, mode="reflect")
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


def build_elevation_profile(
    frenet: FrenetFrame,
    laps_sz: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Average z(s) across laps for a smooth elevation profile.

    Parameters
    ----------
    frenet : FrenetFrame with the centerline s-grid.
    laps_sz : list of (s, z) arrays from each lap.

    Returns
    -------
    (elevation_m, slope_pct) arrays on the centerline s-grid.
    slope_pct is longitudinal slope in percent (+ = uphill).
    """
    n_bins = frenet.n_points
    z_sum = np.zeros(n_bins)
    z_count = np.zeros(n_bins, dtype=int)

    for s_arr, z_arr in laps_sz:
        indices = np.clip(
            np.searchsorted(frenet.s_grid, s_arr) - 1,
            0, n_bins - 1,
        ).astype(int)
        np.add.at(z_sum, indices, z_arr)
        np.add.at(z_count, indices, 1)

    # Average, fill gaps with interpolation
    valid = z_count > 0
    if not np.any(valid):
        return np.zeros(n_bins), np.zeros(n_bins)

    elevation = np.zeros(n_bins)
    elevation[valid] = z_sum[valid] / z_count[valid]

    # Interpolate over gaps
    if not np.all(valid):
        valid_idx = np.where(valid)[0]
        elevation = np.interp(
            np.arange(n_bins), valid_idx, elevation[valid_idx],
        )

    elevation = _smooth_1d(elevation, _SMOOTH_SIGMA_BINS)

    # Compute slope: dz/ds as percentage
    ds = np.diff(frenet.s_grid)
    ds_safe = np.where(ds > 1e-6, ds, 1e-6)
    dz = np.diff(elevation)
    slope_mid = (dz / ds_safe) * 100.0  # percentage

    slope = np.zeros(n_bins)
    slope[1:-1] = 0.5 * (slope_mid[:-1] + slope_mid[1:])
    slope[0] = slope_mid[0] if len(slope_mid) > 0 else 0.0
    slope[-1] = slope_mid[-1] if len(slope_mid) > 0 else 0.0
    slope = _smooth_1d(slope, _SMOOTH_SIGMA_BINS)

    return elevation, slope


def compute_vertical_curvature(
    elevation_m: np.ndarray,
    s_grid: np.ndarray,
) -> np.ndarray:
    """Vertical curvature kappa_v = d²z/ds² along the centerline.

    Positive = compression (car pushed into ground, MORE grip).
    Negative = crest (car lifts, LESS grip).

    At speed v, the effective normal acceleration is:
        g_eff = g + v² * kappa_v

    So grip at a compression at 200 kph with kappa_v=0.01:
        g_eff = 9.81 + 55.6² * 0.01 = 9.81 + 30.9 = 40.7 m/s²
        → grip multiplier = 40.7 / 9.81 = 4.15× (!)

    Parameters
    ----------
    elevation_m : smoothed elevation profile on the s-grid.
    s_grid : cumulative arc-length grid.

    Returns
    -------
    kappa_v array (same length as inputs). Units: 1/m.
    """
    n = len(elevation_m)
    if n < 3:
        return np.zeros(n)

    ds = np.diff(s_grid)
    ds_safe = np.where(ds > 1e-6, ds, 1e-6)

    # First derivative: dz/ds
    dz = np.diff(elevation_m)
    dz_ds = dz / ds_safe

    # Second derivative: d²z/ds²
    d2z = np.diff(dz_ds)
    ds_mid = 0.5 * (ds_safe[:-1] + ds_safe[1:])
    d2z_ds2 = d2z / ds_mid

    # Assign to full grid (central values, edge extrapolation)
    kappa_v = np.zeros(n)
    kappa_v[1:-1] = d2z_ds2 if len(d2z_ds2) == n - 2 else d2z_ds2[: n - 2]
    kappa_v[0] = kappa_v[1]
    kappa_v[-1] = kappa_v[-2]

    # Smooth to suppress noise (vertical curvature is a second derivative,
    # very sensitive to noise in the elevation data)
    kappa_v = _smooth_1d(kappa_v, _SMOOTH_SIGMA_BINS * 2)

    return kappa_v


def estimate_camber(
    frenet: FrenetFrame,
    laps_snz: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    min_samples_per_bin: int = 10,
    min_lateral_spread_m: float = 1.0,
) -> np.ndarray:
    """Estimate banking/camber angle from z vs n at each s position.

    Per s-bin, performs linear regression z = a*n + b.  The slope a is
    the camber (dz/dn), converted to radians via arctan.

    Parameters
    ----------
    frenet : FrenetFrame with the centerline s-grid.
    laps_snz : list of (s, n, z) arrays from each lap.
    min_samples_per_bin : need this many samples per bin for regression.
    min_lateral_spread_m : n must span at least this range for a meaningful fit.

    Returns
    -------
    camber_rad array on the centerline s-grid.  Positive = banked to the left.
    Returns zeros if insufficient lateral coverage.
    """
    n_bins = frenet.n_points

    # Collect all data
    all_s = np.concatenate([s for s, _, _ in laps_snz]) if laps_snz else np.array([])
    all_n = np.concatenate([n for _, n, _ in laps_snz]) if laps_snz else np.array([])
    all_z = np.concatenate([z for _, _, z in laps_snz]) if laps_snz else np.array([])

    if len(all_s) == 0:
        return np.zeros(n_bins)

    all_idx = np.clip(
        np.searchsorted(frenet.s_grid, all_s) - 1,
        0, n_bins - 1,
    ).astype(int)

    camber = np.zeros(n_bins)

    for i in range(n_bins):
        mask = all_idx == i
        if mask.sum() < min_samples_per_bin:
            continue

        n_vals = all_n[mask]
        z_vals = all_z[mask]

        # Check lateral spread
        n_range = np.ptp(n_vals)
        if n_range < min_lateral_spread_m:
            continue

        # Simple linear regression: z = a*n + b
        n_mean = np.mean(n_vals)
        z_mean = np.mean(z_vals)
        denom = np.sum((n_vals - n_mean) ** 2)
        if denom < 1e-12:
            continue
        slope = np.sum((n_vals - n_mean) * (z_vals - z_mean)) / denom
        camber[i] = float(np.arctan(slope))

    camber = _smooth_1d(camber, _SMOOTH_SIGMA_BINS)
    return camber
