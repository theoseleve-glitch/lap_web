"""Adapter for the Kaggle DTM simulated telemetry dataset (961 MB).

CSV at ``data/external/kaggle_simulated/simulated_dataset.csv`` with 2.6M rows.
Reads in chunks to stay within memory budget.

Returns the dict format expected by ``run_handling_analysis()``.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd

G = 9.80665


def _convert_chunk(df: pd.DataFrame) -> dict:
    """Convert a DataFrame chunk to the standard array dict."""
    df = df.sort_values(["Lap", "lap_time"]).reset_index(drop=True)

    speed_mps = (df["Speed"].fillna(0).to_numpy(dtype=np.float64)) / 3.6
    a_lat_g = df["Lateral_G_Force"].fillna(0).to_numpy(dtype=np.float64)
    a_lon_g = df["Longitudinal_G_Force"].fillna(0).to_numpy(dtype=np.float64)
    time_s = df["lap_time"].ffill().fillna(0).to_numpy(dtype=np.float64)

    dt = np.diff(time_s, prepend=time_s[0])
    dt[dt <= 0] = np.median(dt[dt > 0]) if np.any(dt > 0) else 0.01
    dt[0] = dt[1] if len(dt) > 1 else 0.01
    dist_m = np.cumsum(speed_mps * dt)

    # Derive bearing from lateral acceleration
    yaw_rate = a_lat_g * G / (speed_mps + 1e-6)
    bearing_deg = np.cumsum(np.degrees(yaw_rate) * dt) % 360.0

    n = len(df)
    lat_deg = np.zeros(n, dtype=np.float64)
    lon_deg = np.zeros(n, dtype=np.float64)
    lap_col = df["Lap"].fillna(1).to_numpy(dtype=np.int32)

    # Label columns
    event_labels = df["Event"].fillna("Normal").to_numpy()
    driving_style = df["Driving_Style"].fillna("Normal").to_numpy() if "Driving_Style" in df.columns else np.full(n, "Normal")
    steering_position = df["Steering_Position"].fillna(0).to_numpy(dtype=np.float64) if "Steering_Position" in df.columns else np.zeros(n)

    return {
        "time_s": time_s,
        "dist_m": dist_m,
        "speed_mps": speed_mps,
        "a_lat_g": a_lat_g,
        "a_lon_g": a_lon_g,
        "bearing_deg": bearing_deg,
        "lat_deg": lat_deg,
        "lon_deg": lon_deg,
        "lap_col": lap_col,
        "event_labels": event_labels,
        "driving_style": driving_style,
        "steering_position": steering_position,
    }


def load_chunk(filepath: str | Path, chunk_start: int = 0,
               chunk_size: int = 100_000) -> dict:
    """Load a single chunk of the DTM dataset.

    Parameters
    ----------
    filepath   : path to simulated_dataset.csv
    chunk_start: row offset (0-indexed)
    chunk_size : number of rows to read

    Returns
    -------
    dict of numpy arrays.
    """
    df = pd.read_csv(
        filepath,
        skiprows=range(1, chunk_start + 1) if chunk_start > 0 else None,
        nrows=chunk_size,
    )
    return _convert_chunk(df)


def iter_laps(filepath: str | Path,
              max_laps: int = 10) -> Iterator[dict]:
    """Iterate over laps, yielding one dict per lap.

    Reads the file in chunks and groups by ``Lap`` column.  Yields at
    most *max_laps* laps to cap memory usage.
    """
    laps_seen: dict[int, list[pd.DataFrame]] = {}
    laps_yielded = 0

    for chunk in pd.read_csv(filepath, chunksize=100_000):
        for lap_num, grp in chunk.groupby("Lap"):
            laps_seen.setdefault(int(lap_num), []).append(grp)

        # Yield complete laps (a lap is considered complete when a new
        # chunk no longer contains it)
        finished = [ln for ln in list(laps_seen) if ln not in set(chunk["Lap"].unique())]
        for ln in sorted(finished):
            if laps_yielded >= max_laps:
                return
            frames = laps_seen.pop(ln)
            lap_df = pd.concat(frames, ignore_index=True)
            yield _convert_chunk(lap_df)
            laps_yielded += 1

    # Yield remaining laps
    for ln in sorted(laps_seen):
        if laps_yielded >= max_laps:
            return
        frames = laps_seen.pop(ln)
        lap_df = pd.concat(frames, ignore_index=True)
        yield _convert_chunk(lap_df)
        laps_yielded += 1


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/external/kaggle_simulated/simulated_dataset.csv"
    print(f"Loading first chunk from {path} ...")
    d = load_chunk(path, chunk_start=0, chunk_size=50_000)
    print(f"Chunk rows: {len(d['time_s'])}")
    for k, v in d.items():
        if v.dtype.kind == "f":
            print(f"  {k:22s}  shape={v.shape}  min={v.min():.4f}  max={v.max():.4f}")
        else:
            print(f"  {k:22s}  shape={v.shape}  unique={len(np.unique(v))}")
