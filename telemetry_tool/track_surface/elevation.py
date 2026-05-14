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
from dataclasses import dataclass
from typing import Final

import numpy as np

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_SMOOTH_SIGMA_BINS: Final[int] = 5


def _smooth_1d(arr: np.ndarray, sigma: int, *, closed: bool = True) -> np.ndarray:
    """Gaussian smooth a 1D array.

    closed=True (default) uses wrap padding — the centerline / elevation
    profile always represents a closed-loop kart track in build_track_surface,
    and reflect padding produces a small step at the seam (z[0] != z[-1]
    even though they're at the same physical location). Day-9.5 hot-patch.
    closed=False uses reflect padding (open profile).
    """
    if sigma <= 0 or len(arr) < 3:
        return arr.copy()
    hw = 3 * sigma
    kernel = np.exp(-0.5 * (np.arange(-hw, hw + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(arr, hw, mode="wrap" if closed else "reflect")
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


@dataclass
class ElevationSurface:
    """Full 3D elevation grid z(s, n) with vertical curvature at each cell."""
    s_bins: np.ndarray          # (M,) distance bin centres
    n_bins: np.ndarray          # (K,) lateral offset bin centres
    z_grid: np.ndarray          # (M, K) elevation in metres
    kv_grid: np.ndarray         # (M, K) vertical curvature d²z/ds² per cell
    count_grid: np.ndarray      # (M, K) samples per cell
    confidence: np.ndarray      # (M, K) 0-1

    def z_at(self, s: float, n: float) -> float:
        """Bilinear interpolation of elevation at (s, n)."""
        if self.z_grid.size == 0:
            return 0.0
        si = np.clip(np.searchsorted(self.s_bins, s) - 1, 0, len(self.s_bins) - 2)
        ni = np.clip(np.searchsorted(self.n_bins, n) - 1, 0, len(self.n_bins) - 2)
        s0, s1 = self.s_bins[si], self.s_bins[si + 1]
        n0, n1 = self.n_bins[ni], self.n_bins[ni + 1]
        ws = (s - s0) / max(s1 - s0, 1e-9)
        wn = (n - n0) / max(n1 - n0, 1e-9)
        return float(
            self.z_grid[si, ni] * (1 - ws) * (1 - wn)
            + self.z_grid[si + 1, ni] * ws * (1 - wn)
            + self.z_grid[si, ni + 1] * (1 - ws) * wn
            + self.z_grid[si + 1, ni + 1] * ws * wn
        )

    def kv_at(self, s: float, n: float) -> float:
        """Bilinear interpolation of vertical curvature at (s, n)."""
        if self.kv_grid.size == 0:
            return 0.0
        si = np.clip(np.searchsorted(self.s_bins, s) - 1, 0, len(self.s_bins) - 2)
        ni = np.clip(np.searchsorted(self.n_bins, n) - 1, 0, len(self.n_bins) - 2)
        s0, s1 = self.s_bins[si], self.s_bins[si + 1]
        n0, n1 = self.n_bins[ni], self.n_bins[ni + 1]
        ws = (s - s0) / max(s1 - s0, 1e-9)
        wn = (n - n0) / max(n1 - n0, 1e-9)
        return float(
            self.kv_grid[si, ni] * (1 - ws) * (1 - wn)
            + self.kv_grid[si + 1, ni] * ws * (1 - wn)
            + self.kv_grid[si, ni + 1] * (1 - ws) * wn
            + self.kv_grid[si + 1, ni + 1] * ws * wn
        )

    def to_mesh(self, frenet: FrenetFrame) -> np.ndarray:
        """Convert to a 3D point cloud: (M*K, 3) array of (x, y, z).

        Each grid cell becomes a world-space vertex, suitable for
        triangulation into a WebGL mesh.
        """
        M, K = self.z_grid.shape
        ss, nn = np.meshgrid(self.s_bins[:M], self.n_bins[:K], indexing="ij")
        x, y = frenet.sn_to_xy(ss.ravel(), nn.ravel())
        z = self.z_grid.ravel()
        return np.column_stack([x, y, z])


def build_elevation_surface(
    frenet: FrenetFrame,
    laps_snz: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    s_bin_m: float = 5.0,
    n_bin_m: float = 1.0,
    n_range_m: float = 8.0,
    min_samples: int = 3,
) -> ElevationSurface | None:
    """Build a full 3D elevation grid z(s, n) from multi-lap data.

    Each (s, n) cell gets the average z from all telemetry samples
    that fall within it.  Then d²z/ds² is computed per n-column to give
    laterally-varying vertical curvature.

    Parameters
    ----------
    frenet : FrenetFrame for the centerline.
    laps_snz : list of (s, n, z) arrays from each lap.
    s_bin_m : longitudinal bin size.
    n_bin_m : lateral bin size.
    n_range_m : lateral range ± from centerline.
    min_samples : minimum total samples to produce a surface.

    Returns
    -------
    ElevationSurface or None if insufficient z-data.
    """
    if not laps_snz:
        return None

    all_s = np.concatenate([s for s, _, _ in laps_snz])
    all_n = np.concatenate([n for _, n, _ in laps_snz])
    all_z = np.concatenate([z for _, _, z in laps_snz])

    # Filter invalid
    valid = np.isfinite(all_s) & np.isfinite(all_n) & np.isfinite(all_z)
    if valid.sum() < min_samples:
        return None
    all_s, all_n, all_z = all_s[valid], all_n[valid], all_z[valid]

    s_bins = np.arange(0, frenet.total_length_m, s_bin_m)
    n_bins = np.arange(-n_range_m, n_range_m + n_bin_m, n_bin_m)
    M, K = len(s_bins), len(n_bins)

    z_sum = np.zeros((M, K))
    z_count = np.zeros((M, K), dtype=int)

    s_idx = np.clip(np.searchsorted(s_bins, all_s) - 1, 0, M - 1).astype(int)
    n_idx = np.clip(np.searchsorted(n_bins, all_n) - 1, 0, K - 1).astype(int)

    np.add.at(z_sum, (s_idx, n_idx), all_z)
    np.add.at(z_count, (s_idx, n_idx), 1)

    # Average where data exists
    has_data = z_count > 0
    z_grid = np.zeros((M, K))
    z_grid[has_data] = z_sum[has_data] / z_count[has_data]

    # Fill gaps: first longitudinally per column, then laterally per row
    for k in range(K):
        col = z_grid[:, k]
        col_mask = z_count[:, k] > 0
        if col_mask.sum() >= 2:
            filled_idx = np.where(col_mask)[0]
            z_grid[:, k] = np.interp(np.arange(M), filled_idx, col[filled_idx])
        elif col_mask.sum() == 1:
            z_grid[:, k] = col[col_mask][0]

    # Fill laterally: for rows where some columns have data, interpolate across n
    for i in range(M):
        row = z_grid[i, :]
        row_mask = z_count[i, :] > 0
        if row_mask.sum() == 0:
            # No data at this s — will be filled by longitudinal pass above
            # or remains zero. Try to copy from nearest filled s-row.
            continue
        if row_mask.sum() < K:
            filled_idx = np.where(row_mask)[0]
            z_grid[i, :] = np.interp(np.arange(K), filled_idx, row[filled_idx])

    # Smooth each column longitudinally
    for k in range(K):
        z_grid[:, k] = _smooth_1d(z_grid[:, k], _SMOOTH_SIGMA_BINS)

    # Compute vertical curvature per column: d²z/ds² at each (s, n)
    kv_grid = np.zeros((M, K))
    for k in range(K):
        kv_grid[:, k] = _compute_column_kv(z_grid[:, k], s_bins)

    confidence = np.clip(z_count / 20.0, 0.0, 1.0)

    return ElevationSurface(
        s_bins=s_bins,
        n_bins=n_bins,
        z_grid=z_grid,
        kv_grid=kv_grid,
        count_grid=z_count,
        confidence=confidence,
    )


def _compute_column_kv(z_col: np.ndarray, s_bins: np.ndarray) -> np.ndarray:
    """Compute d²z/ds² for a single lateral column."""
    n = len(z_col)
    if n < 3:
        return np.zeros(n)
    ds = np.diff(s_bins[:n])
    ds_safe = np.where(ds > 1e-6, ds, 1e-6)
    dz = np.diff(z_col)
    dz_ds = dz / ds_safe
    d2z = np.diff(dz_ds)
    ds_mid = 0.5 * (ds_safe[:-1] + ds_safe[1:])
    d2z_ds2 = d2z / ds_mid
    kv = np.zeros(n)
    kv[1:1 + len(d2z_ds2)] = d2z_ds2
    kv[0] = kv[1]
    kv[-1] = kv[-2] if n > 2 else 0.0
    return _smooth_1d(kv, _SMOOTH_SIGMA_BINS * 2)


@dataclass
class CurbDetection:
    """A detected curb at the track edge."""
    s_center: float          # distance along track
    n_position: float        # lateral offset (positive = left edge, negative = right)
    side: str                # "left" | "right"
    height_m: float          # z-deviation from surrounding surface
    length_m: float          # longitudinal extent
    is_raised: bool          # True = raised curb, False = dropped/negative curb

    def to_dict(self) -> dict:
        return {
            "s_center": round(self.s_center, 1),
            "n_position": round(self.n_position, 2),
            "side": self.side,
            "height_m": round(self.height_m, 3),
            "length_m": round(self.length_m, 1),
            "is_raised": self.is_raised,
        }


def detect_curbs(
    elev_surface: ElevationSurface,
    z_threshold_m: float = 0.03,
    edge_n_fraction: float = 0.7,
) -> list[CurbDetection]:
    """Detect curbs as z-discontinuities at track edges.

    Looks at the outermost lateral bins for sudden z-deviations relative
    to the adjacent inward bin.  A curb shows as a sharp z-step at the
    track boundary.

    Parameters
    ----------
    elev_surface : ElevationSurface with the full z(s,n) grid.
    z_threshold_m : minimum z-deviation to count as a curb (metres).
    edge_n_fraction : fraction of n-range to consider as "edge" (0.7 = outer 30%).

    Returns
    -------
    List of CurbDetection objects.
    """
    M, K = elev_surface.z_grid.shape
    if M < 3 or K < 4:
        return []

    curbs = []
    n_bins = elev_surface.n_bins
    n_edge_idx = max(1, int(K * (1 - edge_n_fraction) / 2))

    # Check left edge (high n)
    for side, edge_col, ref_col in [
        ("left", K - 1, K - 1 - n_edge_idx),
        ("right", 0, n_edge_idx),
    ]:
        z_edge = elev_surface.z_grid[:, edge_col]
        z_ref = elev_surface.z_grid[:, ref_col]
        count_edge = elev_surface.count_grid[:, edge_col]

        delta_z = z_edge - z_ref

        # Find runs of significant z-deviation
        in_curb = False
        curb_start = 0
        for i in range(M):
            is_significant = abs(delta_z[i]) > z_threshold_m and count_edge[i] > 0
            if is_significant and not in_curb:
                in_curb = True
                curb_start = i
            elif not is_significant and in_curb:
                in_curb = False
                # Record curb
                seg = delta_z[curb_start:i]
                s_center = float(elev_surface.s_bins[curb_start + len(seg) // 2])
                height = float(np.mean(seg))
                length = float(elev_surface.s_bins[min(i, M - 1)] - elev_surface.s_bins[curb_start])
                curbs.append(CurbDetection(
                    s_center=s_center,
                    n_position=float(n_bins[edge_col]),
                    side=side,
                    height_m=abs(height),
                    length_m=max(length, 1.0),
                    is_raised=height > 0,
                ))

        # Handle curb that extends to end
        if in_curb:
            seg = delta_z[curb_start:]
            s_center = float(elev_surface.s_bins[curb_start + len(seg) // 2])
            height = float(np.mean(seg))
            length = float(elev_surface.s_bins[-1] - elev_surface.s_bins[curb_start])
            curbs.append(CurbDetection(
                s_center=s_center,
                n_position=float(n_bins[edge_col]),
                side=side,
                height_m=abs(height),
                length_m=max(length, 1.0),
                is_raised=height > 0,
            ))

    return curbs


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
