"""Adapter for TUM FTM autonomous racing simulation CSVs.

TUMFTM CSVs contain vehicle dynamics at 100 Hz from simulated autonomous
race cars.  Headers start with '#' (e.g. ``#vx_mps,vy_mps,...``).

Source: ``data/external/tumftm/*.csv``

Returns the dict format expected by ``run_handling_analysis()``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

G = 9.80665
DT = 0.01  # 100 Hz simulation
WHEELBASE_M = 2.6  # approx. race car wheelbase


def load(filepath: str | Path) -> dict:
    """Load a TUMFTM CSV and return arrays for handling analysis.

    Parameters
    ----------
    filepath : path to a ``data/external/tumftm/*.csv`` file.

    Returns
    -------
    dict with keys: time_s, dist_m, speed_mps, a_lat_g, a_lon_g,
        bearing_deg, lat_deg, lon_deg, lap_col, plus ground-truth
        channels steering_angle_deg, sideslip_angle_deg,
        understeer_angle_deg.
    """
    raw = pd.read_csv(filepath, comment=None)
    # Strip leading '#' from the first column name
    cols = raw.columns.tolist()
    cols[0] = cols[0].lstrip("#").strip()
    raw.columns = cols

    n = len(raw)

    vx = raw["vx_mps"].to_numpy(dtype=np.float64)
    vy = raw["vy_mps"].to_numpy(dtype=np.float64)
    dpsi = raw["dpsi_radps"].to_numpy(dtype=np.float64)
    ax = raw["ax_mps2"].to_numpy(dtype=np.float64)
    ay = raw["ay_mps2"].to_numpy(dtype=np.float64)
    delta = raw["deltawheel_rad"].to_numpy(dtype=np.float64)

    speed_mps = np.sqrt(vx ** 2 + vy ** 2)
    a_lat_g = ay / G
    a_lon_g = ax / G
    time_s = np.arange(n, dtype=np.float64) * DT
    dist_m = np.cumsum(speed_mps * DT)
    bearing_deg = np.cumsum(np.degrees(dpsi) * DT) % 360.0

    # Synthesise lat/lon from bearing + distance increments
    lat_deg = np.empty(n, dtype=np.float64)
    lon_deg = np.empty(n, dtype=np.float64)
    lat_deg[0] = 48.0  # arbitrary start latitude
    lon_deg[0] = 11.0  # arbitrary start longitude
    bearing_rad = np.radians(bearing_deg)
    ds = speed_mps * DT
    for i in range(1, n):
        dy = ds[i] * np.cos(bearing_rad[i])
        dx = ds[i] * np.sin(bearing_rad[i])
        lat_deg[i] = lat_deg[i - 1] + dy / 110540.0
        lon_deg[i] = lon_deg[i - 1] + dx / (111320.0 * np.cos(np.radians(lat_deg[i - 1])))

    lap_col = np.ones(n, dtype=np.int32)

    # Ground-truth channels
    steering_angle_deg = np.degrees(delta)
    sideslip_angle_deg = np.degrees(np.arctan2(vy, vx))
    understeer_angle_deg = steering_angle_deg - np.degrees(
        np.arctan(WHEELBASE_M * dpsi / (vx + 1e-6))
    )

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
        "steering_angle_deg": steering_angle_deg,
        "sideslip_angle_deg": sideslip_angle_deg,
        "understeer_angle_deg": understeer_angle_deg,
    }


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/external/tumftm/data_to_run.csv"
    d = load(path)
    print(f"Loaded {path}")
    for k, v in d.items():
        print(f"  {k:26s}  shape={v.shape}  min={v.min():.4f}  max={v.max():.4f}")
