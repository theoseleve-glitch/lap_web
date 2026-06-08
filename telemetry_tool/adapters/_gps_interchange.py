"""Shared helpers for GPS-interchange adapters (GPX, NMEA, and later TCX/KML).

These formats all reduce to a sequence of timestamped GPS points. This module
converts such points into a canonical DataFrame (``channel_registry`` names)
and derives ``distance_m`` / ``speed_mps`` / ``heading_deg`` when the source
omits them (most GPS-track exports do).
"""
from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

_EARTH_RADIUS_M: Final[float] = 6_371_000.0


def haversine_m(lat1: ArrayLike, lon1: ArrayLike, lat2: ArrayLike, lon2: ArrayLike) -> np.ndarray:
    """Great-circle distance in metres between arrays of lat/lon in degrees."""
    lat1r = np.radians(lat1)
    lat2r = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2.0) ** 2
         + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2)
    return 2.0 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def initial_bearing_deg(lat1: ArrayLike, lon1: ArrayLike, lat2: ArrayLike, lon2: ArrayLike) -> np.ndarray:
    """Initial bearing (deg, 0-360) from point 1 to point 2 (arrays)."""
    lat1r = np.radians(lat1)
    lat2r = np.radians(lat2)
    dlon = np.radians(lon2 - lon1)
    x = np.sin(dlon) * np.cos(lat2r)
    y = (np.cos(lat1r) * np.sin(lat2r)
         - np.sin(lat1r) * np.cos(lat2r) * np.cos(dlon))
    return np.mod(np.degrees(np.arctan2(x, y)), 360.0)


def finalize_gps_frame(df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """Return a canonical GPS DataFrame.

    *df* may contain any of: ``time_s, lat_deg, lon_deg, altitude_m,
    speed_mps, heading_deg``. Requires at least ``time_s, lat_deg, lon_deg``.
    Drops rows lacking position; derives distance/speed/heading when absent.
    Raises ``ValueError`` if required columns are missing or < 2 valid points.
    """
    required = {"time_s", "lat_deg", "lon_deg"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{source}: GPS frame missing required columns: {sorted(missing)}"
        )

    df = df.dropna(subset=["time_s", "lat_deg", "lon_deg"]).reset_index(drop=True).copy()
    if len(df) < 2:
        raise ValueError(f"{source}: need at least 2 valid GPS points, got {len(df)}")

    lat = df["lat_deg"].to_numpy(dtype=float)
    lon = df["lon_deg"].to_numpy(dtype=float)
    t = df["time_s"].to_numpy(dtype=float)

    # Segment distances: seg[i] = distance from point i-1 to i (seg[0] = 0).
    seg = np.zeros(len(df), dtype=float)
    seg[1:] = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])

    if "distance_m" not in df.columns:
        df["distance_m"] = np.cumsum(seg)

    if "speed_mps" not in df.columns:
        dt = np.diff(t, prepend=t[0])
        with np.errstate(divide="ignore", invalid="ignore"):
            spd = np.where(dt > 0, seg / dt, 0.0)
        if len(spd) > 1:
            # Row 0 has no prior point; copy row 1's speed as the best estimate.
            spd[0] = spd[1]
        df["speed_mps"] = spd

    if "heading_deg" not in df.columns:
        brg = np.zeros(len(df), dtype=float)
        brg[1:] = initial_bearing_deg(lat[:-1], lon[:-1], lat[1:], lon[1:])
        if len(brg) > 1:
            brg[0] = brg[1]
        df["heading_deg"] = brg

    return df
