"""Day-13 Phase D — per-tile mesh geometry helpers.

Computes per-tile surface normals + slope% from the ``ElevationSurface``
``z(s, n)`` grid via finite differences. Used by the spatial producer to
build 2D drainage / sun / wind fields when elevation data is available.

Why elevation_surface, not camber_rad? camber_rad on launch tracks
(OK_R4 / KCT_R1) is physically implausible — ±48° spikes on flat kart
circuits. Routed around for Day 13; logged as a deferred investigation
in ``CLEANUP_LOG.md`` Day 13 section. ``elevation_surface`` is the
smoothed 2D height field built by ``track_surface.elevation``; finite
differences on it bypass the noisy 1D camber estimate.

Coordinate convention follows ``spatial_factors``: ENU local frame
(+X=east, +Y=north, +Z=up). Per-tile normals returned in world ENU,
ready for ``sun_factor`` / future ``wind_factor_2d``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# Lateral Gaussian smoothing applied before computing ∂z/∂n. The
# elevation pipeline smooths z_grid longitudinally at build time but
# leaves the lateral axis untouched — without this pass, finite-
# differences across n surface the per-cell measurement noise as
# spurious banking. Sigma=2 bins (≈ 2 m at default n_bin=1 m).
_LATERAL_SMOOTH_SIGMA: int = 2

# Clip extreme cross-track gradients (in % units after × 100). 20%
# corresponds to ~11° tilt — above this on a kart track is almost
# certainly residual noise leaking past the smoother, not real banking.
_GRADIENT_CLIP_PCT: float = 20.0


@dataclass(frozen=True)
class TileGeometry:
    """Per-tile geometry derived from ElevationSurface.

    Indexed ``[i_s, j_n]`` where ``s_bins[i_s]`` is the longitudinal
    bin centre and ``n_bins[j_n]`` is the lateral offset bin centre.
    """

    normals: np.ndarray         # (M, K, 3) unit ENU vectors
    slope_pct: np.ndarray       # (M, K) full 2D gradient magnitude × 100
    s_bins: np.ndarray          # (M,) — copied from elevation_surface
    n_bins: np.ndarray          # (K,) — copied from elevation_surface


def _smooth_2d_lateral(z: np.ndarray, sigma_n: int) -> np.ndarray:
    """Gaussian-smooth along axis=1 (lateral). Reflect-pad at the
    cross-section edges (n is not periodic)."""
    if sigma_n <= 0 or z.shape[1] < 3:
        return z.copy()
    hw = 3 * sigma_n
    kernel = np.exp(-0.5 * (np.arange(-hw, hw + 1) / sigma_n) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(z, ((0, 0), (hw, hw)), mode="reflect")
    out = np.empty_like(z, dtype=np.float64)
    for i in range(z.shape[0]):
        out[i] = np.convolve(padded[i], kernel, mode="valid")[: z.shape[1]]
    return out


def compute_tile_geometry(
    elevation_surface: Any,
    frenet: Any,
    *,
    lateral_smooth_sigma: int = _LATERAL_SMOOTH_SIGMA,
    gradient_clip_pct: float = _GRADIENT_CLIP_PCT,
) -> TileGeometry:
    """Per-tile normals + slope% from z(s, n).

    Args:
        elevation_surface: ``ElevationSurface`` (from
            ``track_surface.elevation``) with ``s_bins (M,)``,
            ``n_bins (K,)``, ``z_grid (M, K)``.
        frenet: ``FrenetFrame`` with ``s_grid`` + ``heading_rad`` for
            the world-frame rotation. May be sampled at finer or
            coarser resolution than ``elevation_surface.s_bins`` —
            heading is interpolated to the elevation grid.
        lateral_smooth_sigma: Gaussian sigma (in n-bins) applied to
            z_grid before differentiating across n. Defaults to 2.
        gradient_clip_pct: clip ``||∇z||·100`` at this value to suppress
            residual noise leaking past the smoother. Defaults to 20%
            (~11° tilt — above this on a kart track is residual noise).

    Returns:
        :class:`TileGeometry` with per-tile normals, slope%, and the
        grid axes (copied for convenience).

    Raises:
        ValueError: if the z_grid is degenerate (M < 2 or K < 2).
    """
    z = np.asarray(elevation_surface.z_grid, dtype=np.float64)
    M, K = z.shape
    if M < 2 or K < 2:
        raise ValueError(
            f"elevation_surface.z_grid shape {z.shape} too small for "
            "finite-difference normals (need M >= 2 and K >= 2)"
        )

    s_bins = np.asarray(elevation_surface.s_bins, dtype=np.float64)
    n_bins = np.asarray(elevation_surface.n_bins, dtype=np.float64)
    ds = float(s_bins[1] - s_bins[0])
    dn = float(n_bins[1] - n_bins[0])

    # Smooth laterally before differentiating across n.
    z_smooth = _smooth_2d_lateral(z, lateral_smooth_sigma)

    # Finite-difference gradients in local s-n frame.
    dz_ds = np.gradient(z_smooth, ds, axis=0)  # (M, K)
    dz_dn = np.gradient(z_smooth, dn, axis=1)  # (M, K)

    # Heading at each s_bin — interpolated from frenet's s_grid.
    h_at_s = np.interp(s_bins, frenet.s_grid, frenet.heading_rad)
    cos_h = np.cos(h_at_s)[:, None]
    sin_h = np.sin(h_at_s)[:, None]

    # Local-frame normal (-∂z/∂s, -∂z/∂n, 1) rotated to ENU. Derivation:
    #   world_x = s · cos(h) - n · sin(h)
    #   world_y = s · sin(h) + n · cos(h)
    #   world_z = z
    # so a local vector (V_s, V_n, V_z) maps to world by:
    #   (V_s·cos h - V_n·sin h,  V_s·sin h + V_n·cos h,  V_z)
    nx = -dz_ds * cos_h - (-dz_dn) * sin_h     # = -dz_ds·cos_h + dz_dn·sin_h
    ny = -dz_ds * sin_h + (-dz_dn) * cos_h     # = -dz_ds·sin_h - dz_dn·cos_h
    nz = np.ones_like(z)

    normals = np.stack([nx, ny, nz], axis=-1)  # (M, K, 3)
    mag = np.linalg.norm(normals, axis=-1, keepdims=True)
    mag = np.where(mag > 1e-9, mag, 1.0)
    normals = normals / mag

    # Slope magnitude as % from full 2D gradient. Clipped to suppress
    # residual noise above the kart-track plausibility ceiling.
    slope_raw = np.sqrt(dz_ds**2 + dz_dn**2) * 100.0
    slope_pct = np.minimum(slope_raw, gradient_clip_pct)

    return TileGeometry(
        normals=normals,
        slope_pct=slope_pct,
        s_bins=s_bins,
        n_bins=n_bins,
    )


def wind_bank_modulator(
    tile_normals: np.ndarray,
    wind_direction_deg: float,
    *,
    alpha: float = 0.10,
) -> np.ndarray:
    """Per-tile wind exposure modulator for banked sections.

    The 1D ``wind_factor`` uses the angle between tangent (direction of
    travel) and wind-FROM direction; that angle is constant per s (no
    per-n variation). On banked sections, an additional effect matters:
    the surface NORMAL has a horizontal component pointing somewhere,
    and wind hitting that surface from the windward side dries it
    while the lee side stays sheltered. This helper returns that
    secondary per-tile multiplier so:

        wind_field_2d[i, j] = wind_components_1d[i] · modulator[i, j]

    The modulator is centred on 1.0 and rolls off to (1 ± ``alpha``)
    based on the alignment between the surface normal's horizontal
    component and the wind direction. Flat tiles (vertical normal)
    get modulator = 1.0 (no banking → no bank-exposure effect →
    falls back to the 1D wind_components value).

    Args:
        tile_normals: (M, K, 3) unit normals in ENU.
        wind_direction_deg: compass-FROM degrees per Open-Meteo
            (0°=N wind FROM north, 90°=E, etc.).
        alpha: max modulation magnitude. Default 0.10 (10% — subtle but
            visible). Stacked on top of the 1D wind_factor's own
            [0.85, 1.15] range, so combined max swing is roughly ±25%.

    Returns:
        (M, K) modulator values centred on 1.0. Apply by multiplying
        with the per-row 1D wind_components (broadcast over n).
    """
    n_h = tile_normals[..., :2]  # (M, K, 2) horizontal projection
    n_h_mag = np.linalg.norm(n_h, axis=-1, keepdims=True)
    # Safe-divide: where the horizontal component is ~zero (flat tile),
    # dividing by 1.0 leaves n_h_unit ≈ zero — the strength multiplier
    # downstream then zeros out the modulation. Avoids a RuntimeWarning
    # from np.where evaluating both branches.
    safe_mag = np.where(n_h_mag > 1e-9, n_h_mag, 1.0)
    n_h_unit = n_h / safe_mag
    n_h_strength = n_h_mag.squeeze(-1)  # (M, K) — 0 on flat tiles

    wind_rad = np.deg2rad(wind_direction_deg)
    wind_from_xy = np.array([np.sin(wind_rad), np.cos(wind_rad)])

    # Alignment ∈ [-1, +1]. Positive → tile normal points TOWARD the
    # wind source (windward face exposed). Negative → lee side.
    alignment = (n_h_unit @ wind_from_xy)  # (M, K)

    # Weight by horizontal-strength so flat tiles get zero modulation
    # contribution. modulator = 1 - alpha * alignment · strength
    # (negative on windward → wind_components ↓ → drier; consistent
    # with the existing wind_factor convention where windward < 1.0).
    return 1.0 - alpha * alignment * n_h_strength
