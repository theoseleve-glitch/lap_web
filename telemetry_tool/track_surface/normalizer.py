"""
track_surface/normalizer.py
---------------------------
Coordinate normalization for multi-sim telemetry.

Converts position data from any source (GPS lat/lon, sim Cartesian Y-up,
or Cartesian Z-up) to a consistent local (x_m, y_m, z_m) frame in metres,
where x/y are horizontal and z is vertical (elevation).

The equirectangular projection matches the existing formula used in
reference_line.py, fusion_ekf.py, and harvest.py.
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M: Final[float] = 6_371_000.0

# Adapter FORMAT_NAME -> coordinate system type
_FORMAT_TO_COORD: Final[dict[str, str]] = {
    # GPS sources (WGS-84 lat/lon)
    "iracing":      "gps",
    "iracing_ibt":  "gps",
    "racechrono":   "gps",
    "racechrono_rcz": "gps",
    "racebox":      "gps",
    "qstarz":       "gps",
    "qstarz_bin":   "gps",
    "vbox":         "gps",
    # Cartesian Y-up (X/Z horizontal, Y vertical)
    "ac":           "cartesian_y_up",
    "acc":          "cartesian_y_up",
    "lmu":          "cartesian_y_up",
    "motec":        "cartesian_y_up",
    "motec_bin":    "cartesian_y_up",
    # Cartesian Z-up (X/Y horizontal, Z vertical)
    "f1_game":      "cartesian_z_up",
}

# Canonical column names used to look up position data in DataFrames
_GPS_LAT_COLS = ("lat_deg", "Latitude (deg)")
_GPS_LON_COLS = ("lon_deg", "Longitude (deg)")
_GPS_ALT_COLS = ("altitude_m", "Altitude (m)", "GPS Altitude (m)")
_SIM_X_COLS = ("pos_x_m", "pos_x")
_SIM_Y_COLS = ("pos_y_m", "pos_y")  # horizontal in Y-up sims = Z axis
_SIM_Z_COLS = ("pos_z_m", "pos_z")  # vertical in Y-up sims = Y axis


def detect_coordinate_system(adapter_format: str) -> str:
    """Determine coordinate system from the adapter's FORMAT_NAME.

    Returns
    -------
    ``"gps"`` | ``"cartesian_y_up"`` | ``"cartesian_z_up"``

    Falls back to ``"gps"`` for unknown formats (safe default since GPS
    is the most common real-world telemetry source).
    """
    return _FORMAT_TO_COORD.get(adapter_format, "gps")


def _find_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """Return the first column name from candidates that exists in df."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


# -- GPS projection ----------------------------------------------------------


def _gps_to_local_enu(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    alt_m: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Equirectangular projection: lat/lon degrees -> local ENU metres.

    Returns (x_m, y_m, z_m, metadata) where metadata contains the
    reference point for the inverse projection.
    """
    lat_r = np.radians(lat_deg.astype(np.float64))
    lon_r = np.radians(lon_deg.astype(np.float64))

    lat_ref = float(np.nanmean(lat_r))
    lon_ref = float(np.nanmean(lon_r))

    x_m = _EARTH_RADIUS_M * (lon_r - lon_ref) * np.cos(lat_ref)
    y_m = _EARTH_RADIUS_M * (lat_r - lat_ref)
    z_m = alt_m if alt_m is not None else np.zeros_like(x_m)

    meta = {"lat_ref_rad": lat_ref, "lon_ref_rad": lon_ref, "projection": "equirectangular"}
    return x_m, y_m, z_m, meta


def _local_enu_to_gps(
    x_m: np.ndarray,
    y_m: np.ndarray,
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse projection: local ENU metres -> lat/lon degrees."""
    lat_r = y_m / _EARTH_RADIUS_M + lat_ref_rad
    lon_r = x_m / (_EARTH_RADIUS_M * np.cos(lat_ref_rad)) + lon_ref_rad
    return np.degrees(lat_r), np.degrees(lon_r)


# -- Main entry point --------------------------------------------------------


def normalize_positions(
    df: pd.DataFrame,
    coord_system: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Convert any sim/logger position data to consistent (x_m, y_m, z_m).

    Parameters
    ----------
    df : DataFrame with canonical channel columns from an adapter.
    coord_system : one of ``"gps"``, ``"cartesian_y_up"``, ``"cartesian_z_up"``
        (use ``detect_coordinate_system()`` to determine this).

    Returns
    -------
    (x_m, y_m, z_m, metadata) where x/y are horizontal metres and z is
    elevation.  metadata contains projection reference for inverse mapping.
    """
    n = len(df)

    if coord_system == "gps":
        lat_col = _find_col(df, _GPS_LAT_COLS)
        lon_col = _find_col(df, _GPS_LON_COLS)
        if lat_col is None or lon_col is None:
            logger.warning("GPS coordinate system but no lat/lon columns found")
            return np.zeros(n), np.zeros(n), np.zeros(n), {}

        lat = pd.to_numeric(df[lat_col], errors="coerce").to_numpy()
        lon = pd.to_numeric(df[lon_col], errors="coerce").to_numpy()

        alt_col = _find_col(df, _GPS_ALT_COLS)
        alt = pd.to_numeric(df[alt_col], errors="coerce").to_numpy() if alt_col else None

        return _gps_to_local_enu(lat, lon, alt)

    elif coord_system == "cartesian_y_up":
        # Sims: X/Z are horizontal, Y is vertical
        x_col = _find_col(df, _SIM_X_COLS)
        z_col = _find_col(df, _SIM_Y_COLS)  # sim Z -> our horizontal y
        y_col = _find_col(df, _SIM_Z_COLS)  # sim Y -> our vertical z

        x_m = pd.to_numeric(df[x_col], errors="coerce").to_numpy() if x_col else np.zeros(n)
        y_m = pd.to_numeric(df[z_col], errors="coerce").to_numpy() if z_col else np.zeros(n)
        z_m = pd.to_numeric(df[y_col], errors="coerce").to_numpy() if y_col else np.zeros(n)

        meta = {"projection": "cartesian_y_up_remapped"}
        return x_m, y_m, z_m, meta

    elif coord_system == "cartesian_z_up":
        # F1 games: X/Y horizontal, Z vertical
        x_col = _find_col(df, _SIM_X_COLS)
        y_col = _find_col(df, _SIM_Y_COLS)
        z_col = _find_col(df, _SIM_Z_COLS)

        x_m = pd.to_numeric(df[x_col], errors="coerce").to_numpy() if x_col else np.zeros(n)
        y_m = pd.to_numeric(df[y_col], errors="coerce").to_numpy() if y_col else np.zeros(n)
        z_m = pd.to_numeric(df[z_col], errors="coerce").to_numpy() if z_col else np.zeros(n)

        meta = {"projection": "cartesian_z_up"}
        return x_m, y_m, z_m, meta

    else:
        logger.warning("Unknown coordinate system '%s', returning zeros", coord_system)
        return np.zeros(n), np.zeros(n), np.zeros(n), {}
