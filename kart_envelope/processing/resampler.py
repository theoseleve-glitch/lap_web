"""
resampler.py
------------
Wrapper around ``telemetry_tool.resampling`` that converts a
``ds`` (metres) spacing into the ``n_points`` parameter expected by the
existing resampler, and enforces monotonic cumulative distance.
"""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.config import KartEnvelopeConfig  # noqa: E402
from kart_envelope.ingest.columns import CANONICAL_TO_RAW, COL_DIST  # noqa: E402
from telemetry_tool.resampling import resample_lap_by_distance  # noqa: E402

logger = logging.getLogger(__name__)


class ResamplingError(ValueError):
    """Raised when resampling fails for all laps."""


def _ensure_monotonic_distance(df: pd.DataFrame) -> pd.DataFrame:
    """Fix small distance reversals by sorting and de-duplicating."""
    # The column might be canonical (distance_m) or raw (Distance (m))
    dist_col = COL_DIST if COL_DIST in df.columns else "Distance (m)"
    if dist_col not in df.columns:
        return df

    out = df.copy()
    d = out[dist_col].values.copy()

    # Replace NaN with interpolated values
    nans = np.isnan(d)
    if nans.all():
        return out
    if nans.any():
        idx = np.arange(len(d))
        d[nans] = np.interp(idx[nans], idx[~nans], d[~nans])

    # Sort by distance (fixes small reversals)
    order = np.argsort(d, kind="stable")
    if not np.array_equal(order, np.arange(len(d))):
        logger.debug("Fixing non-monotonic distance (%d swaps).",
                      int(np.sum(order != np.arange(len(d)))))
        out = out.iloc[order].reset_index(drop=True)

    return out


def _subtract_lap_start_distance(df: pd.DataFrame) -> pd.DataFrame:
    """Make distance lap-relative by subtracting the first sample."""
    dist_col = COL_DIST if COL_DIST in df.columns else "Distance (m)"
    if dist_col not in df.columns:
        return df
    out = df.copy()
    d = out[dist_col].dropna()
    if len(d) > 0:
        out[dist_col] = out[dist_col] - float(d.iloc[0])
    return out


def resample_laps_by_ds(
    lap_dict: dict[int, pd.DataFrame],
    config: KartEnvelopeConfig,
) -> dict[int, pd.DataFrame]:
    """Resample all laps onto a uniform distance grid with spacing ``ds``.

    Parameters
    ----------
    lap_dict : dict[int, pd.DataFrame]
        ``{lap_number: lap_df}`` with a distance column.
    config : KartEnvelopeConfig

    Returns
    -------
    dict[int, pd.DataFrame]
        Resampled laps.  Laps that fail resampling are silently dropped.

    Raises
    ------
    ResamplingError
        If all laps fail.
    """
    ds = config.resample_ds_m
    result: dict[int, pd.DataFrame] = {}

    for lap_num, lap_df in lap_dict.items():
        try:
            prepped = _subtract_lap_start_distance(lap_df)
            prepped = _ensure_monotonic_distance(prepped)

            # Determine lap length → compute n_points
            dist_col = COL_DIST if COL_DIST in prepped.columns else "Distance (m)"
            if dist_col not in prepped.columns:
                logger.warning("Lap %d: no distance column, skipping.", lap_num)
                continue

            d = prepped[dist_col].dropna()
            if len(d) < 2:
                continue
            lap_len = float(d.iloc[-1] - d.iloc[0])
            if lap_len < config.min_lap_distance_m:
                logger.debug("Lap %d: %.1f m too short for resampling.", lap_num, lap_len)
                continue

            n_points = max(config.resample_min_points, int(math.ceil(lap_len / ds)))

            # Bridge canonical → raw names for telemetry_tool, then back
            raw_prepped = _to_raw_names(prepped)
            resampled_raw = resample_lap_by_distance(raw_prepped, n_points=n_points)
            resampled = _to_canonical_names(resampled_raw)
            result[lap_num] = resampled
        except Exception as exc:
            logger.warning("Lap %d resampling failed: %s", lap_num, exc)

    if not result:
        raise ResamplingError("All laps failed resampling.")

    logger.info("Resampled %d / %d laps (ds=%.2f m).", len(result), len(lap_dict), ds)
    return result


def _to_raw_names(df: pd.DataFrame) -> pd.DataFrame:
    """Rename canonical columns back to RaceChrono raw names for telemetry_tool."""
    rename = {canon: raw for canon, raw in CANONICAL_TO_RAW.items()
              if canon in df.columns}
    return df.rename(columns=rename) if rename else df


def _to_canonical_names(df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw RaceChrono columns back to canonical names after telemetry_tool.

    Uses a simple rename (no G-conversion) because values are already in SI
    units from the prior normalize_columns call.
    """
    from kart_envelope.ingest.columns import RAW_TO_CANONICAL
    rename = {raw: canon for raw, canon in RAW_TO_CANONICAL.items()
              if raw in df.columns}
    return df.rename(columns=rename) if rename else df
