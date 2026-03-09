"""
delta_analysis.py
-----------------
Compute distance-aligned delta-time maps between a driver's actual lap
and the theoretical optimal speed profile.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from kart_envelope.ingest.columns import (
    COL_ACCEL_LAT,
    COL_ACCEL_LONG,
    COL_DIST,
    COL_SPEED,
    COL_TIME,
)
from kart_envelope.solver.min_time import TheoreticalResult

logger = logging.getLogger(__name__)


def compute_delta_map(
    driver_lap: pd.DataFrame,
    theoretical: TheoreticalResult,
    n_segments: int = 20,
) -> pd.DataFrame:
    """Build a distance-aligned delta-time map.

    Parameters
    ----------
    driver_lap : pd.DataFrame
        Resampled lap with canonical column names.
    theoretical : TheoreticalResult
        Solver output.
    n_segments : int
        Number of equal-distance segments for aggregation.

    Returns
    -------
    pd.DataFrame
        Columns: ``distance_m``, ``v_lap_mps``, ``v_theory_mps``,
        ``dt_lap_s``, ``dt_theory_s``, ``delta_s``, ``cumulative_delta_s``,
        ``kappa_1pm``, ``ax_mps2``, ``ay_mps2``, ``segment``.
    """
    if COL_DIST not in driver_lap.columns or COL_SPEED not in driver_lap.columns:
        logger.warning("Driver lap missing distance/speed; returning empty delta map.")
        return pd.DataFrame()

    # Align onto the theoretical distance grid
    s_theory = theoretical.distance_m
    v_theory = theoretical.speed_profile_mps

    s_driver = driver_lap[COL_DIST].values
    v_driver = driver_lap[COL_SPEED].values

    # Common grid: intersection of distance ranges
    s_lo = max(float(s_theory[0]), float(np.nanmin(s_driver)))
    s_hi = min(float(s_theory[-1]), float(np.nanmax(s_driver)))
    if s_hi <= s_lo:
        logger.warning("No distance overlap between driver lap and theoretical.")
        return pd.DataFrame()

    n_pts = len(s_theory)
    mask = (s_theory >= s_lo) & (s_theory <= s_hi)
    s_grid = s_theory[mask]
    v_th = v_theory[mask]

    # Interpolate driver onto this grid
    v_dr = np.interp(s_grid, s_driver[np.isfinite(s_driver)],
                      v_driver[np.isfinite(v_driver)])

    # Clamp to avoid div-by-zero
    v_dr = np.maximum(v_dr, 0.5)
    v_th = np.maximum(v_th, 0.5)

    # Element-wise dt
    ds = np.diff(s_grid)
    v_avg_dr = 0.5 * (v_dr[:-1] + v_dr[1:])
    v_avg_th = 0.5 * (v_th[:-1] + v_th[1:])
    dt_dr = ds / np.maximum(v_avg_dr, 0.5)
    dt_th = ds / np.maximum(v_avg_th, 0.5)

    delta = dt_dr - dt_th
    cum_delta = np.cumsum(delta)

    # Build output at midpoints
    s_mid = 0.5 * (s_grid[:-1] + s_grid[1:])
    v_dr_mid = 0.5 * (v_dr[:-1] + v_dr[1:])
    v_th_mid = 0.5 * (v_th[:-1] + v_th[1:])

    # Optional columns — use joint mask so xp and fp have same length
    ax_mid = np.full(len(s_mid), np.nan)
    ay_mid = np.full(len(s_mid), np.nan)
    if COL_ACCEL_LONG in driver_lap.columns:
        ax_raw = driver_lap[COL_ACCEL_LONG].values
        valid_ax = np.isfinite(s_driver) & np.isfinite(ax_raw)
        if valid_ax.sum() >= 2:
            ax_mid = np.interp(s_mid, s_driver[valid_ax], ax_raw[valid_ax])
    if COL_ACCEL_LAT in driver_lap.columns:
        ay_raw = driver_lap[COL_ACCEL_LAT].values
        valid_ay = np.isfinite(s_driver) & np.isfinite(ay_raw)
        if valid_ay.sum() >= 2:
            ay_mid = np.interp(s_mid, s_driver[valid_ay], ay_raw[valid_ay])

    # Curvature from theoretical
    kappa = np.zeros(len(s_mid))
    if hasattr(theoretical, "distance_m"):
        from kart_envelope.track.geometry import TrackGeometry  # avoid circular

        # Interpolate if possible from accel profile (a_lat ≈ v²κ)
        # Simpler: just use theoretical accel
        kappa_full = theoretical.accel_profile_mps2  # not quite κ but useful
        kappa = np.interp(s_mid, s_theory[mask], kappa_full[mask]
                           if len(kappa_full) == len(s_theory) else np.zeros(mask.sum()))

    # Segment assignment
    seg_edges = np.linspace(s_mid[0], s_mid[-1], n_segments + 1)
    segments = np.digitize(s_mid, seg_edges) - 1
    segments = np.clip(segments, 0, n_segments - 1)

    result = pd.DataFrame({
        "distance_m": np.round(s_mid, 4),
        "v_lap_mps": np.round(v_dr_mid, 4),
        "v_theory_mps": np.round(v_th_mid, 4),
        "dt_lap_s": np.round(dt_dr, 6),
        "dt_theory_s": np.round(dt_th, 6),
        "delta_s": np.round(delta, 6),
        "cumulative_delta_s": np.round(cum_delta, 6),
        "ax_mps2": np.round(ax_mid, 4),
        "ay_mps2": np.round(ay_mid, 4),
        "segment": segments,
    })

    total_loss = float(cum_delta[-1]) if len(cum_delta) > 0 else 0.0
    logger.info("Delta map: %d points, total loss=%.3f s.", len(result), total_loss)
    return result


def segment_summary(delta_map: pd.DataFrame, n_segments: int = 20) -> pd.DataFrame:
    """Aggregate delta map into per-segment time loss.

    Returns
    -------
    pd.DataFrame
        Columns: ``segment``, ``s_start``, ``s_end``, ``time_loss_ms``,
        ``mean_v_delta_mps``.
    """
    if delta_map.empty or "segment" not in delta_map.columns:
        return pd.DataFrame()

    groups = delta_map.groupby("segment")
    rows = []
    for seg, g in groups:
        rows.append({
            "segment": int(seg),
            "s_start": round(float(g["distance_m"].iloc[0]), 1),
            "s_end": round(float(g["distance_m"].iloc[-1]), 1),
            "time_loss_ms": round(float(g["delta_s"].sum()) * 1000, 1),
            "mean_v_delta_mps": round(
                float(g["v_lap_mps"].mean() - g["v_theory_mps"].mean()), 3),
        })
    return pd.DataFrame(rows)
