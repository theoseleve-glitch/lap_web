"""Lap extraction and distance-based resampling."""
from __future__ import annotations

import numpy as np
import pandas as pd


_MIN_POINTS = 20


def align_lap(
    df: pd.DataFrame,
    lap_number: int,
    ds_m: float = 0.5,
    dist_col: str = "irsdk__LapDist",
    lap_col: str = "irsdk__Lap",
) -> pd.DataFrame | None:
    """Extract one lap and resample to uniform distance grid.

    Parameters
    ----------
    df : pd.DataFrame
        Full session dataframe with at least *dist_col* and *lap_col*.
    lap_number : int
        Which lap to extract.
    ds_m : float
        Distance spacing in metres for the output grid.
    dist_col : str
        Column holding cumulative lap distance.
    lap_col : str
        Column holding lap number.

    Returns
    -------
    pd.DataFrame | None
        Resampled dataframe with uniform distance grid, or ``None`` if the
        lap has fewer than ``_MIN_POINTS`` rows.
    """
    lap_df = df.loc[df[lap_col] == lap_number].copy()
    if len(lap_df) < _MIN_POINTS:
        return None

    lap_df = lap_df.sort_values(dist_col)
    lap_df = lap_df.drop_duplicates(subset=dist_col, keep="first")

    if len(lap_df) < _MIN_POINTS:
        return None

    dist = lap_df[dist_col].values
    d_min, d_max = float(dist[0]), float(dist[-1])
    grid = np.arange(d_min, d_max, ds_m)

    numeric_cols = lap_df.select_dtypes(include="number").columns.tolist()

    result: dict[str, np.ndarray] = {dist_col: grid}
    for col in numeric_cols:
        if col == dist_col:
            continue
        result[col] = np.interp(grid, dist, lap_df[col].values)

    return pd.DataFrame(result)
