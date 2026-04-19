"""Adapter for the Kaggle motorsport telemetry dataset (92 MB, 286K rows).

CSV at ``data/external/kaggle_motorsport/motorsport_data.csv`` with GPS,
acceleration, driving phase labels, and sector metadata.

Returns the dict format expected by ``run_handling_analysis()``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load(filepath: str | Path, lap_number: int | None = None) -> dict:
    """Load motorsport data, optionally filtering by lap.

    Parameters
    ----------
    filepath   : path to ``motorsport_data.csv``.
    lap_number : if given, return only rows for this lap number.

    Returns
    -------
    dict of numpy arrays for handling analysis plus label channels.
    """
    df = pd.read_csv(filepath)

    if lap_number is not None:
        df = df[df["lap_number"] == lap_number].reset_index(drop=True)
    if df.empty:
        raise ValueError(f"No data found (lap_number={lap_number})")

    df = df.sort_values(["lap_number", "time"]).reset_index(drop=True)

    n = len(df)
    speed_mps = df["speed"].fillna(0).to_numpy(dtype=np.float64) / 3.6
    a_lat_g = df["lateral_acc"].fillna(0).to_numpy(dtype=np.float64)
    a_lon_g = df["inline_acc"].fillna(0).to_numpy(dtype=np.float64)
    time_s = df["time"].ffill().fillna(0).to_numpy(dtype=np.float64)
    dist_m = df["distance"].fillna(0).to_numpy(dtype=np.float64)
    lat_deg = df["gps_latitude"].interpolate(limit_direction="both").fillna(0).to_numpy(dtype=np.float64)
    lon_deg = df["gps_longitude"].interpolate(limit_direction="both").fillna(0).to_numpy(dtype=np.float64)
    lap_col = df["lap_number"].fillna(1).to_numpy(dtype=np.int32)

    # Bearing from GPS coordinates
    d_lat = np.diff(lat_deg, prepend=lat_deg[0])
    d_lon = np.diff(lon_deg, prepend=lon_deg[0])
    cos_lat = np.cos(np.radians(lat_deg))
    bearing_deg = np.degrees(np.arctan2(d_lon * cos_lat, d_lat))
    bearing_deg = np.degrees(np.unwrap(np.radians(bearing_deg))) % 360.0

    # Label channels
    driving_phase = df["driving_phase"].fillna("unknown").to_numpy()
    sector_type = df["gps_sector_type"].fillna("unknown").to_numpy() if "gps_sector_type" in df.columns else np.full(n, "unknown")
    yaw_rate_dps = df["yaw_rate"].fillna(0).to_numpy(dtype=np.float64) if "yaw_rate" in df.columns else np.zeros(n)
    trail_braking = df["trail_braking_intensity"].fillna(0).to_numpy(dtype=np.float64) if "trail_braking_intensity" in df.columns else np.zeros(n)

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
        "driving_phase": driving_phase,
        "sector_type": sector_type,
        "yaw_rate_dps": yaw_rate_dps,
        "trail_braking_intensity": trail_braking,
    }


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/external/kaggle_motorsport/motorsport_data.csv"
    d = load(path)
    print(f"Loaded {path}  ({len(d['time_s'])} rows)")
    for k, v in d.items():
        if v.dtype.kind == "f":
            print(f"  {k:28s}  shape={v.shape}  min={v.min():.4f}  max={v.max():.4f}")
        else:
            print(f"  {k:28s}  shape={v.shape}  unique={len(np.unique(v))}")
