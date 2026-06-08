"""
track_surface/grip_2d.py
------------------------
2D grip map mu(s, n) from dynamics inversion.

At each telemetry sample, back-calculates the friction coefficient from
observed lateral acceleration, speed, and curvature.  Bins results into
a 2D grid (s, n) and provides bilinear interpolation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665
_MIN_SPEED_MPS: Final[float] = 3.0  # ignore samples below this speed
_MIN_LAPS: Final[int] = 10


@dataclass
class GripSurface:
    """2D grip map on a (s, n) grid with bilinear interpolation."""
    s_bins: np.ndarray       # (M,) distance bin centres
    n_bins: np.ndarray       # (K,) lateral offset bin centres
    mu_grid: np.ndarray      # (M, K) friction coefficient
    count_grid: np.ndarray   # (M, K) number of samples per cell
    confidence: np.ndarray   # (M, K) confidence 0-1
    # (M, K) per-cell cornering LIMIT (absolute mu, per-session p90, MAX-merged
    # across sessions). NaN where < _MIN_LIMIT_SAMPLES samples or unmeasured.
    # None when no limit data exists (old sidecars). Only the OCP path reads it.
    mu_limit_grid: np.ndarray | None = None

    def mu_at(self, s: float, n: float) -> float:
        """Bilinear interpolation of grip at a single (s, n) point."""
        if self.mu_grid.size == 0:
            return 1.0

        # Clamp to grid bounds
        s_clamped = np.clip(s, self.s_bins[0], self.s_bins[-1])
        n_clamped = np.clip(n, self.n_bins[0], self.n_bins[-1])

        # Find surrounding indices
        si = np.searchsorted(self.s_bins, s_clamped) - 1
        ni = np.searchsorted(self.n_bins, n_clamped) - 1
        si = np.clip(si, 0, len(self.s_bins) - 2)
        ni = np.clip(ni, 0, len(self.n_bins) - 2)

        # Interpolation weights
        s0, s1 = self.s_bins[si], self.s_bins[si + 1]
        n0, n1 = self.n_bins[ni], self.n_bins[ni + 1]
        ws = (s_clamped - s0) / max(s1 - s0, 1e-9)
        wn = (n_clamped - n0) / max(n1 - n0, 1e-9)

        # Bilinear
        v00 = self.mu_grid[si, ni]
        v10 = self.mu_grid[si + 1, ni]
        v01 = self.mu_grid[si, ni + 1]
        v11 = self.mu_grid[si + 1, ni + 1]

        return float(
            v00 * (1 - ws) * (1 - wn)
            + v10 * ws * (1 - wn)
            + v01 * (1 - ws) * wn
            + v11 * ws * wn
        )

    def mu_at_batch(self, s: np.ndarray, n: np.ndarray) -> np.ndarray:
        """Vectorised grip lookup for arrays of (s, n)."""
        return np.array([self.mu_at(si, ni) for si, ni in zip(s, n)])

    def centerline_slice(self) -> np.ndarray:
        """Return grip values along the centerline (n=0)."""
        n0_idx = np.argmin(np.abs(self.n_bins))
        return self.mu_grid[:, n0_idx].copy()


def build_grip_surface(
    frenet: FrenetFrame,
    laps: list[pd.DataFrame],
    s_bin_m: float = 5.0,
    n_bin_m: float = 1.0,
    n_range_m: float = 8.0,
    vert_curvature: np.ndarray | None = None,
) -> GripSurface | None:
    """Build a 2D grip map from multi-lap telemetry.

    Uses dynamics inversion with terrain-corrected normal force:
        mu = |a_lat| / g_effective
        g_effective = g + v² * kappa_v(s)

    where kappa_v is the vertical curvature of the track surface.
    Positive kappa_v = compression (MORE grip), negative = crest (LESS grip).

    Parameters
    ----------
    frenet : FrenetFrame for (x,y) -> (s,n) projection.
    laps : list of DataFrames with canonical channel columns.
    s_bin_m : longitudinal bin size in metres.
    n_bin_m : lateral bin size in metres.
    n_range_m : lateral range ± from centerline.

    Returns
    -------
    GripSurface or None if fewer than MIN_LAPS.
    """
    if len(laps) < _MIN_LAPS:
        logger.debug("Need >= %d laps for 2D grip map, got %d", _MIN_LAPS, len(laps))
        return None

    # Set up grid
    s_bins = np.arange(0, frenet.total_length_m, s_bin_m)
    n_bins = np.arange(-n_range_m, n_range_m + n_bin_m, n_bin_m)
    M, K = len(s_bins), len(n_bins)

    mu_sum = np.zeros((M, K))
    mu_count = np.zeros((M, K), dtype=int)

    for lap_df in laps:
        # Extract required channels.
        # Day-15: dual-name speed lookup. The resampled lap DataFrames carry
        # RaceChrono-style column names ("Speed (m/s)") that never get
        # renamed to the canonical snake_case "speed_mps" this function was
        # written against. Pre-fix, this hit the continue-swallow and
        # build_grip_surface produced an empty grid for every prod session.
        # "Speed (m/s)" is already in m/s — no unit conversion needed.
        speed = lap_df.get("speed_mps")
        if speed is None:
            speed = lap_df.get("Speed (m/s)")
        a_lat = lap_df.get("accel_lat_mps2")
        if speed is None or a_lat is None:
            continue

        speed_arr = pd.to_numeric(speed, errors="coerce").to_numpy()
        a_lat_arr = pd.to_numeric(a_lat, errors="coerce").to_numpy()

        # Need position for Frenet projection
        x_col = None
        for c in ("pos_x_m", "x_m"):
            if c in lap_df.columns:
                x_col = c
                break
        y_col = None
        for c in ("pos_y_m", "y_m"):
            if c in lap_df.columns:
                y_col = c
                break

        if x_col is None or y_col is None:
            continue

        x_arr = pd.to_numeric(lap_df[x_col], errors="coerce").to_numpy()
        y_arr = pd.to_numeric(lap_df[y_col], errors="coerce").to_numpy()

        # Filter: valid speed and acceleration
        valid = (speed_arr > _MIN_SPEED_MPS) & np.isfinite(a_lat_arr) & np.isfinite(x_arr)
        if valid.sum() < 10:
            continue

        x_v, y_v = x_arr[valid], y_arr[valid]
        speed_v = speed_arr[valid]
        a_lat_v = a_lat_arr[valid]

        # Project to Frenet
        s_proj, n_proj = frenet.xy_to_sn(x_v, y_v)

        # Compute effective g: includes terrain vertical load transfer
        # g_eff = g + v² × κ_v(s)  — compression adds grip, crests remove it
        if vert_curvature is not None and len(vert_curvature) > 0:
            kv_at_s = np.interp(
                s_proj % frenet.total_length_m,
                frenet.s_grid,
                np.interp(frenet.s_grid, np.linspace(0, frenet.total_length_m, len(vert_curvature)), vert_curvature),
            )
            g_eff = _G + speed_v ** 2 * kv_at_s
            g_eff = np.maximum(g_eff, 1.0)  # prevent negative/zero at extreme crests
        else:
            g_eff = _G

        mu = np.abs(a_lat_v) / g_eff

        # Tire degradation correction: hot tires = degraded grip
        # If tire temp data is available, penalise mu when temps exceed optimal
        _OPTIMAL_TIRE_TEMP_C = 90.0  # typical optimal operating temp
        _TEMP_PENALTY_PER_10C = 0.02  # 2% grip loss per 10°C over optimal
        for temp_col in ("tire_temp_fl", "tire_temp_fr", "tire_temp_rl", "tire_temp_rr"):
            if temp_col in lap_df.columns:
                t_arr = pd.to_numeric(lap_df[temp_col], errors="coerce").to_numpy()
                t_valid = t_arr[valid]
                if np.any(np.isfinite(t_valid)):
                    over_temp = np.clip(t_valid - _OPTIMAL_TIRE_TEMP_C, 0, 50)
                    penalty = 1.0 - (over_temp / 10.0) * _TEMP_PENALTY_PER_10C
                    mu = mu * np.clip(penalty, 0.8, 1.0)
                break  # use first available tire channel

        # Tire wear correction: worn tires = less grip
        for wear_col in ("tire_wear_fl", "tire_wear_fr", "tire_wear_rl", "tire_wear_rr"):
            if wear_col in lap_df.columns:
                w_arr = pd.to_numeric(lap_df[wear_col], errors="coerce").to_numpy()
                w_valid = w_arr[valid]
                if np.any(np.isfinite(w_valid)):
                    # wear_pct is remaining tread (100% = new, 0% = bald)
                    # Grip penalty below 50% remaining
                    wear_penalty = np.where(w_valid < 50, 0.95 + 0.05 * (w_valid / 50), 1.0)
                    mu = mu * np.clip(wear_penalty, 0.85, 1.0)
                break

        # Bin into grid
        s_idx = np.clip(np.searchsorted(s_bins, s_proj) - 1, 0, M - 1)
        n_idx = np.clip(np.searchsorted(n_bins, n_proj) - 1, 0, K - 1)

        for si, ni, mu_val in zip(s_idx, n_idx, mu):
            if np.isfinite(mu_val) and 0.1 < mu_val < 3.0:
                mu_sum[si, ni] += mu_val
                mu_count[si, ni] += 1

    # Compute mean mu per cell
    mu_grid = np.ones((M, K))  # default 1.0
    has_data = mu_count > 0
    mu_grid[has_data] = mu_sum[has_data] / mu_count[has_data]

    # Confidence: based on sample count (saturates at ~50 samples)
    confidence = np.clip(mu_count / 50.0, 0.0, 1.0)

    # Day-15 silent-empty guard. 5th silent-empty failure surfaced this week
    # (yesterday: reference_line OUT_*, then sidecar perms, then track-detection
    # sentinel, then ON CONFLICT mismatch, today: speed_mps vs "Speed (m/s)").
    # If the gate passed but zero cells got observations, log what was looked
    # for vs what the input actually had so the next mismatch surfaces at
    # ingest time instead of three days downstream.
    if int(mu_count.sum()) == 0:
        sample_cols = list(laps[0].columns) if laps else []
        logger.warning(
            "build_grip_surface: %d lap(s) processed but count_grid is "
            "empty — expected one of {%s} for speed AND %r for a_lat. "
            "First lap actually has %d columns; sample: %s",
            len(laps),
            "'speed_mps', 'Speed (m/s)'",
            "accel_lat_mps2",
            len(sample_cols),
            sample_cols[:12] + (["..."] if len(sample_cols) > 12 else []),
        )

    return GripSurface(
        s_bins=s_bins,
        n_bins=n_bins,
        mu_grid=mu_grid,
        count_grid=mu_count,
        confidence=confidence,
    )
