"""
track_surface/demand_2d.py
--------------------------
Silver-tier 2D demand field: demand(s, n) with occupancy and confidence.

Wraps the existing grip_2d.py dynamics inversion with the bronze-tier
corrections (excitation gate, centripetal substitution, confidence scoring)
applied per (s, n) cell instead of per s-bin.

This module does NOT modify bronze. It is an additive layer.

Invariant: this is a demand product, not a friction estimator.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class DemandSurface2D:
    """Silver-tier 2D demand field on a (s, n) grid."""

    s_bins: np.ndarray          # (M,) distance bin centers
    n_bins: np.ndarray          # (K,) lateral offset bin centers
    excited_p90: np.ndarray     # (M, K) p90 demand from excited samples
    occupancy: np.ndarray       # (M, K) total sample count per cell
    confidence: np.ndarray      # (M, K) composite quality 0-1
    racing_line_mask: np.ndarray  # (M, K) boolean: on-line?

    def demand_at(self, s: float, n: float) -> float:
        """Bilinear interpolation of excited_p90 at (s, n)."""
        if self.excited_p90.size == 0:
            return 0.0
        s_c = np.clip(s, self.s_bins[0], self.s_bins[-1])
        n_c = np.clip(n, self.n_bins[0], self.n_bins[-1])
        si = int(np.clip(np.searchsorted(self.s_bins, s_c) - 1, 0, len(self.s_bins) - 2))
        ni = int(np.clip(np.searchsorted(self.n_bins, n_c) - 1, 0, len(self.n_bins) - 2))
        ds = self.s_bins[si + 1] - self.s_bins[si]
        dn = self.n_bins[ni + 1] - self.n_bins[ni]
        ts = (s_c - self.s_bins[si]) / ds if ds > 0 else 0.0
        tn = (n_c - self.n_bins[ni]) / dn if dn > 0 else 0.0
        v00 = self.excited_p90[si, ni]
        v10 = self.excited_p90[si + 1, ni]
        v01 = self.excited_p90[si, ni + 1]
        v11 = self.excited_p90[si + 1, ni + 1]
        return float(
            v00 * (1 - ts) * (1 - tn)
            + v10 * ts * (1 - tn)
            + v01 * (1 - ts) * tn
            + v11 * ts * tn
        )

    def on_line_mean(self) -> float:
        """Mean excited_p90 on the racing line."""
        vals = self.excited_p90[self.racing_line_mask]
        return float(np.mean(vals)) if len(vals) > 0 else 0.0

    def off_line_mean(self) -> float:
        """Mean excited_p90 off the racing line (where occupancy > 0)."""
        off_mask = ~self.racing_line_mask & (self.occupancy > 0)
        vals = self.excited_p90[off_mask]
        return float(np.mean(vals)) if len(vals) > 0 else 0.0

    def to_dict(self) -> dict:
        """JSON-safe serialization."""
        M, K = self.excited_p90.shape
        return {
            's_bins': [round(float(v), 1) for v in self.s_bins],
            'n_bins': [round(float(v), 1) for v in self.n_bins],
            'excited_p90': [[round(float(self.excited_p90[i, j]), 3)
                             for j in range(K)] for i in range(M)],
            'occupancy': [[int(self.occupancy[i, j])
                           for j in range(K)] for i in range(M)],
            'confidence': [[round(float(self.confidence[i, j]), 2)
                            for j in range(K)] for i in range(M)],
            'racing_line_mask': [[bool(self.racing_line_mask[i, j])
                                  for j in range(K)] for i in range(M)],
            'on_line_mean_demand': round(self.on_line_mean(), 3),
            'off_line_mean_demand': round(self.off_line_mean(), 3),
            'grid_shape': [M, K],
            'tier': 'silver',
        }


def build_demand_surface_2d(
    frenet: FrenetFrame,
    laps_xy_data: list[dict],
    curvature: np.ndarray,
    excitation_thresholds: dict[str, float],
    s_bin_m: float = 4.0,
    n_bin_m: float = 1.0,
    n_range_m: float = 8.0,
) -> DemandSurface2D | None:
    """Build a 2D demand surface from multi-lap telemetry.

    Parameters
    ----------
    frenet : FrenetFrame with xy_to_sn() method
    laps_xy_data : list of dicts with keys:
        'x', 'y' (np.ndarray, local meters),
        'speed' (np.ndarray, m/s),
        'alat_g' (np.ndarray, lateral accel in G),
        'src' (str, session name)
    curvature : (N,) signed curvature from the centerline
    excitation_thresholds : {session_name: p70_threshold_G}
    s_bin_m : longitudinal bin size (meters)
    n_bin_m : lateral bin size (meters)
    n_range_m : lateral range (meters each side of centerline)

    Returns
    -------
    DemandSurface2D or None if insufficient data.
    """
    total_length = frenet.total_length_m
    s_bins = np.arange(0, total_length, s_bin_m)
    n_bins = np.arange(-n_range_m, n_range_m + n_bin_m, n_bin_m)
    M = len(s_bins)
    K = len(n_bins)

    if M < 5 or K < 3:
        return None

    # Accumulators per cell
    all_samples = [[[] for _ in range(K)] for _ in range(M)]
    excited_samples = [[[] for _ in range(K)] for _ in range(M)]
    occupancy_count = np.zeros((M, K), dtype=int)

    # Curvature lookup (interpolate to s_bins)
    curv_at_s = np.interp(
        s_bins,
        np.linspace(0, total_length, len(curvature)),
        np.abs(curvature),
    )

    for lap in laps_xy_data:
        x = lap['x']
        y = lap['y']
        speed = lap['speed']
        alat_g = np.abs(lap['alat_g'])
        src = lap['src']
        threshold = excitation_thresholds.get(src, 0.3)

        if len(x) < 20:
            continue

        # Project to (s, n) via Frenet frame
        try:
            s_arr, n_arr = frenet.xy_to_sn(x, y)
        except Exception:
            continue

        for idx in range(len(x)):
            if speed[idx] < 3.0 or not np.isfinite(alat_g[idx]):
                continue
            if alat_g[idx] > 2.5:
                continue

            s_val = s_arr[idx]
            n_val = n_arr[idx]

            # Find bin indices
            si = int(np.clip(np.searchsorted(s_bins, s_val) - 1, 0, M - 1))
            ni = int(np.clip(np.searchsorted(n_bins, n_val) - 1, 0, K - 1))

            # Centripetal substitution (same as bronze fix 3)
            a_centripetal = speed[idx] ** 2 * curv_at_s[si] / _G
            if a_centripetal > 0.1:
                a_corrected = a_centripetal
            else:
                a_corrected = float(alat_g[idx])

            occupancy_count[si, ni] += 1
            all_samples[si][ni].append(a_corrected)

            # Excitation gate (same as bronze fix 1)
            if a_corrected > threshold:
                excited_samples[si][ni].append(a_corrected)

    # Build output arrays
    excited_p90 = np.zeros((M, K))
    confidence = np.zeros((M, K))

    for si in range(M):
        for ni in range(K):
            n_all = len(all_samples[si][ni])
            n_exc = len(excited_samples[si][ni])

            if n_exc >= 2:
                excited_p90[si, ni] = float(np.percentile(excited_samples[si][ni], 90))
            elif n_all >= 3:
                excited_p90[si, ni] = float(np.percentile(all_samples[si][ni], 90))

            # Confidence: count + excitation fraction
            count_score = min(1.0, n_all / 20.0)
            exc_score = min(1.0, (n_exc / max(n_all, 1)) / 0.3)
            confidence[si, ni] = 0.5 * count_score + 0.5 * exc_score

    # Racing line mask: cells with occupancy in the top 25%
    occ_nonzero = occupancy_count[occupancy_count > 0]
    if len(occ_nonzero) > 0:
        threshold_occ = float(np.percentile(occ_nonzero, 75))
        racing_line_mask = occupancy_count >= threshold_occ
    else:
        racing_line_mask = np.zeros((M, K), dtype=bool)

    logger.info(
        "DemandSurface2D built: %dx%d grid, %d on-line cells, "
        "on-line mean=%.3f, off-line mean=%.3f",
        M, K, racing_line_mask.sum(),
        float(np.mean(excited_p90[racing_line_mask])) if racing_line_mask.any() else 0,
        float(np.mean(excited_p90[~racing_line_mask & (occupancy_count > 0)]))
        if (~racing_line_mask & (occupancy_count > 0)).any() else 0,
    )

    return DemandSurface2D(
        s_bins=s_bins,
        n_bins=n_bins,
        excited_p90=excited_p90,
        occupancy=occupancy_count,
        confidence=confidence,
        racing_line_mask=racing_line_mask,
    )
