"""Adapter for TracingInsights / FastF1-style F1 telemetry JSON files.

Each JSON file represents one lap and contains a ``"tel"`` key with
arrays for time, speed, acceleration, x/y/z position, throttle, brake,
etc.  Files may live inside ZIP archives or as standalone ``.json``
files.

Source: ``data/external/f1_tracing/*.json``

Returns the dict format expected by ``run_handling_analysis()``.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np

G = 9.80665
REF_LAT = 48.0  # pseudo-lat reference for position conversion
REF_LON = 2.0   # pseudo-lon reference


def _convert_tel(tel: dict) -> dict:
    """Convert a tel dict to the standard array dict."""
    time_s = np.asarray(tel["time"], dtype=np.float64)
    speed_kmh = np.asarray(tel["speed"], dtype=np.float64)
    acc_x = np.asarray(tel.get("acc_x", [0.0] * len(time_s)), dtype=np.float64)
    acc_y = np.asarray(tel.get("acc_y", [0.0] * len(time_s)), dtype=np.float64)
    dist_raw = np.asarray(tel.get("distance", [0.0] * len(time_s)), dtype=np.float64)
    x = np.asarray(tel.get("x", [0.0] * len(time_s)), dtype=np.float64)
    y = np.asarray(tel.get("y", [0.0] * len(time_s)), dtype=np.float64)

    throttle = np.asarray(tel.get("throttle", [0.0] * len(time_s)), dtype=np.float64)
    brake = np.asarray(tel.get("brake", [0] * len(time_s)), dtype=np.float64)

    n = len(time_s)
    speed_mps = speed_kmh / 3.6
    a_lat_g = acc_y / G
    a_lon_g = acc_x / G

    # Distance: use raw if populated, otherwise integrate speed
    if np.any(dist_raw > 0):
        dist_m = dist_raw
    else:
        dt = np.diff(time_s, prepend=time_s[0])
        dt[0] = dt[1] if n > 1 else 0.04
        dist_m = np.cumsum(speed_mps * dt)

    # Bearing from x,y position differences
    dx = np.diff(x, prepend=x[0])
    dy = np.diff(y, prepend=y[0])
    bearing_deg = np.degrees(np.arctan2(dx, dy))
    # Unwrap to avoid discontinuities
    bearing_deg = np.degrees(np.unwrap(np.radians(bearing_deg))) % 360.0

    # Pseudo lat/lon from x,y positions
    lat_deg = y / 110540.0 + REF_LAT
    lon_deg = x / (111320.0 * np.cos(np.radians(REF_LAT))) + REF_LON

    lap_col = np.ones(n, dtype=np.int32)

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
        "throttle_pct": throttle,
        "brake_on": brake,
    }


def load_from_file(json_path: str | Path) -> dict:
    """Load a single lap from an extracted JSON file."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    tel = data.get("tel", data)
    return _convert_tel(tel)


def load_from_zip(zip_path: str | Path, tel_path: str) -> dict:
    """Load a single lap from a zip archive without extracting.

    Parameters
    ----------
    zip_path : path to the ``.zip`` archive.
    tel_path : internal path within the archive (e.g.
        ``"Australian_Grand_Prix/Qualifying/HAM/lap_5_tel.json"``).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(tel_path) as f:
            data = json.load(f)
    tel = data.get("tel", data)
    return _convert_tel(tel)


def list_laps_in_zip(zip_path: str | Path, gp_name: str | None = None,
                     session: str | None = None,
                     driver: str | None = None) -> list[str]:
    """List available telemetry file paths inside a zip.

    Parameters
    ----------
    zip_path : path to the ``.zip`` archive.
    gp_name  : filter by Grand Prix name substring (case-insensitive).
    session  : filter by session name substring (e.g. "Qualifying").
    driver   : filter by driver abbreviation substring (e.g. "HAM").

    Returns
    -------
    List of internal archive paths matching the filters.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        paths = [n for n in zf.namelist() if n.endswith(".json")]

    if gp_name:
        gp_lower = gp_name.lower()
        paths = [p for p in paths if gp_lower in p.lower()]
    if session:
        sess_lower = session.lower()
        paths = [p for p in paths if sess_lower in p.lower()]
    if driver:
        drv_lower = driver.lower()
        paths = [p for p in paths if drv_lower in p.lower()]

    return sorted(paths)


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/external/f1_tracing/Australian_Grand_Prix_Qualifying_HAM_5_tel.json"
    d = load_from_file(path)
    print(f"Loaded {path}")
    for k, v in d.items():
        if v.dtype.kind == "f":
            print(f"  {k:18s}  shape={v.shape}  min={v.min():.4f}  max={v.max():.4f}")
        else:
            print(f"  {k:18s}  shape={v.shape}  dtype={v.dtype}")
