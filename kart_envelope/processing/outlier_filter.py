"""
outlier_filter.py
-----------------
Per-speed-bin MAD (Median Absolute Deviation) filtering of acceleration
signals.  Removes GPS/IMU spikes that would pollute envelope learning.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.ingest.columns import COL_ACCEL_LAT, COL_ACCEL_LONG, COL_SPEED

logger = logging.getLogger(__name__)


def mad_filter_accel(
    resampled_laps: dict[int, pd.DataFrame],
    config: KartEnvelopeConfig,
) -> dict[int, pd.DataFrame]:
    """Remove acceleration outliers per speed bin using MAD.

    For each speed bin, computes median and MAD of ``accel_long_mps2`` and
    ``|accel_lat_mps2|``.  Samples beyond
    ``config.outlier_mad_threshold × MAD`` from the median are set to NaN.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
    config : KartEnvelopeConfig

    Returns
    -------
    dict[int, pd.DataFrame]
        Copies with outlier acceleration values set to NaN.
    """
    # Pool all samples for bin statistics
    frames: list[pd.DataFrame] = []
    for lap_df in resampled_laps.values():
        cols = [c for c in (COL_SPEED, COL_ACCEL_LONG, COL_ACCEL_LAT)
                if c in lap_df.columns]
        if COL_SPEED in cols:
            frames.append(lap_df[cols])

    if not frames:
        logger.warning("No acceleration data for MAD filtering.")
        return {k: v.copy() for k, v in resampled_laps.items()}

    pool = pd.concat(frames, ignore_index=True).dropna(subset=[COL_SPEED])
    if len(pool) < 20:
        return {k: v.copy() for k, v in resampled_laps.items()}

    # Adaptive speed bins
    v_min = float(pool[COL_SPEED].quantile(0.01))
    v_max = float(pool[COL_SPEED].quantile(0.99))
    n_bins = max(5, config.envelope_speed_bins)
    edges = np.linspace(v_min, v_max, n_bins + 1)

    # Compute per-bin MAD thresholds
    thresh_long: dict[int, tuple[float, float]] = {}  # bin_idx -> (median, mad_thresh)
    thresh_lat: dict[int, tuple[float, float]] = {}

    speed_arr = pool[COL_SPEED].values
    bin_idx = np.digitize(speed_arr, edges) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    for b in range(n_bins):
        mask = bin_idx == b
        if mask.sum() < config.outlier_min_bin_size:
            continue

        if COL_ACCEL_LONG in pool.columns:
            vals = pool.loc[mask, COL_ACCEL_LONG].dropna().values
            if len(vals) >= config.outlier_min_bin_size:
                med = float(np.median(vals))
                mad = float(np.median(np.abs(vals - med))) * 1.4826  # scale to σ
                if mad > 0:
                    thresh_long[b] = (med, mad * config.outlier_mad_threshold)

        if COL_ACCEL_LAT in pool.columns:
            vals = np.abs(pool.loc[mask, COL_ACCEL_LAT].dropna().values)
            if len(vals) >= config.outlier_min_bin_size:
                med = float(np.median(vals))
                mad = float(np.median(np.abs(vals - med))) * 1.4826
                if mad > 0:
                    thresh_lat[b] = (med, mad * config.outlier_mad_threshold)

    # Apply per-lap
    n_removed = 0
    result: dict[int, pd.DataFrame] = {}

    for lap_num, lap_df in resampled_laps.items():
        out = lap_df.copy()
        if COL_SPEED not in out.columns:
            result[lap_num] = out
            continue

        v = out[COL_SPEED].values
        bi = np.digitize(v, edges) - 1
        bi = np.clip(bi, 0, n_bins - 1)

        for col, thresholds in [(COL_ACCEL_LONG, thresh_long), (COL_ACCEL_LAT, thresh_lat)]:
            if col not in out.columns:
                continue
            vals = out[col].values.copy()
            for i in range(len(vals)):
                b = bi[i]
                if b not in thresholds or np.isnan(vals[i]):
                    continue
                med, thr = thresholds[b]
                ref = abs(vals[i]) if col == COL_ACCEL_LAT else vals[i]
                ref_med = med
                if abs(ref - ref_med) > thr:
                    vals[i] = np.nan
                    n_removed += 1
            out[col] = vals

        result[lap_num] = out

    if n_removed > 0:
        logger.info("MAD filter: set %d acceleration samples to NaN.", n_removed)
    return result
