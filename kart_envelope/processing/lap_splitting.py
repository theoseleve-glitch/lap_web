"""
lap_splitting.py
----------------
Split a session DataFrame into per-lap DataFrames, validate each lap,
and select the subset of "clean" laps suitable for envelope training.

Filtering uses both **time** and **distance** windows relative to the
session median to reject outlaps, incomplete laps and corner-cut laps.
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.ingest.columns import COL_DIST, COL_LAP, COL_SPEED, COL_TIME

logger = logging.getLogger(__name__)

_MIN_ROWS_PER_LAP: Final[int] = 20


class LapSplittingError(ValueError):
    """Raised when lap splitting cannot produce usable laps."""


def split_and_select_laps(
    df: pd.DataFrame,
    config: KartEnvelopeConfig,
) -> dict[int, pd.DataFrame]:
    """Split by lap number, validate, and select clean laps.

    Validation gates (applied in order):
    1. Minimum row count (hard-coded 20).
    2. Minimum lap distance (``min_lap_distance_m`` from config).
    3. Missing speed data ratio (``max_missing_ratio``).
    4. Time-window filter: reject laps outside ``[median / outlap_ratio,
       median × outlap_ratio]``.
    5. Distance-window filter: reject laps whose distance deviates from
       the median by more than ``outlap_ratio`` (catches corner cuts and
       incomplete laps that happen to have normal-ish times).

    Parameters
    ----------
    df : pd.DataFrame
        Session DataFrame with canonical column names.
    config : KartEnvelopeConfig

    Returns
    -------
    dict[int, pd.DataFrame]
        ``{lap_number: lap_df}`` for clean laps.

    Raises
    ------
    LapSplittingError
        If no valid laps remain.
    """
    if COL_LAP not in df.columns:
        raise LapSplittingError(f"Column '{COL_LAP}' not found.")

    grouped = dict(list(df.groupby(COL_LAP)))
    logger.info("Raw lap groups: %d", len(grouped))

    valid: dict[int, pd.DataFrame] = {}

    for lap_num_raw, lap_df in grouped.items():
        try:
            lap_num = int(float(lap_num_raw))
        except (ValueError, TypeError):
            continue
        if lap_num <= 0:
            logger.debug("Skipping lap 0 (outlap).")
            continue

        lap_df = lap_df.copy().reset_index(drop=True)

        # --- Gate 1: minimum rows ---
        if len(lap_df) < _MIN_ROWS_PER_LAP:
            logger.debug("Lap %d: too few rows (%d).", lap_num, len(lap_df))
            continue

        # --- Gate 2: absolute minimum lap distance ---
        if COL_DIST in lap_df.columns:
            d = lap_df[COL_DIST].dropna()
            if len(d) > 1:
                lap_dist = float(d.iloc[-1] - d.iloc[0])
                if lap_dist < config.min_lap_distance_m:
                    logger.debug("Lap %d: too short (%.1f m).", lap_num, lap_dist)
                    continue

        # --- Gate 3: missing-data ratio ---
        if COL_SPEED in lap_df.columns:
            n_total = len(lap_df)
            n_nan = int(lap_df[COL_SPEED].isna().sum())
            if n_total > 0 and (n_nan / n_total) > config.max_missing_ratio:
                logger.debug("Lap %d: %.0f%% speed NaN.", lap_num, 100 * n_nan / n_total)
                continue

        valid[lap_num] = lap_df

    if not valid:
        raise LapSplittingError("No valid laps after filtering.")

    # --- Gate 4: time-window filter (relative to median) ---
    lap_times = compute_lap_times(valid)
    reject: set[int] = set()

    if lap_times:
        med_t = float(np.median(list(lap_times.values())))
        slow_t = med_t * config.outlap_ratio
        fast_t = med_t / config.outlap_ratio
        time_reject = {n for n, t in lap_times.items()
                       if t > slow_t or t < fast_t}
        if time_reject:
            logger.info("Time-window filter: removing %d laps outside "
                         "%.1f–%.1f s: %s", len(time_reject), fast_t, slow_t,
                         sorted(time_reject))
            reject |= time_reject

    # --- Gate 5: distance-window filter (relative to median) ---
    lap_dists = compute_lap_distances(valid)
    if lap_dists:
        med_d = float(np.median(list(lap_dists.values())))
        short_d = med_d / config.outlap_ratio
        long_d = med_d * config.outlap_ratio
        dist_reject = {n for n, d in lap_dists.items()
                       if d < short_d or d > long_d}
        if dist_reject:
            logger.info("Distance-window filter: removing %d laps outside "
                         "%.0f–%.0f m: %s", len(dist_reject), short_d, long_d,
                         sorted(dist_reject))
            reject |= dist_reject

    for n in reject:
        valid.pop(n, None)

    if not valid:
        raise LapSplittingError("No laps remain after time/distance filtering.")

    logger.info("Selected %d clean laps: %s", len(valid), sorted(valid.keys()))
    return valid


def compute_lap_times(lap_dict: dict[int, pd.DataFrame]) -> dict[int, float]:
    """Return ``{lap_number: lap_time_s}`` from the time column."""
    result: dict[int, float] = {}
    for lap_num, lap_df in lap_dict.items():
        if COL_TIME not in lap_df.columns:
            continue
        t = lap_df[COL_TIME].dropna()
        if len(t) < 2:
            continue
        result[lap_num] = float(t.iloc[-1] - t.iloc[0])
    return result


def compute_lap_distances(lap_dict: dict[int, pd.DataFrame]) -> dict[int, float]:
    """Return ``{lap_number: lap_distance_m}`` from the distance column."""
    result: dict[int, float] = {}
    for lap_num, lap_df in lap_dict.items():
        if COL_DIST not in lap_df.columns:
            continue
        d = lap_df[COL_DIST].dropna()
        if len(d) < 2:
            continue
        result[lap_num] = float(d.iloc[-1] - d.iloc[0])
    return result
