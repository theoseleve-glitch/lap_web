"""GPS/channel repository — GPS traces and rich telemetry channel data."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

import numpy as np

from db import queries as Q
from web.repos._helpers import _np_to_json, _parse_json_or_list

import logging

logger = logging.getLogger(__name__)


def insert_gps_traces(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """
    Extract GPS coordinates from resampled_laps and persist.

    Looks for columns like 'Latitude (deg)', 'Longitude (deg)',
    'distance_m', and speed columns in the resampled DataFrames.
    """
    resampled = summary.get("resampled_laps") or {}
    count = 0

    for lap_num, df in resampled.items():
        if df is None or len(df) == 0:
            continue

        # Find GPS columns (RaceChrono naming).
        lat_col = None
        lon_col = None
        dist_col = None
        spd_col = None

        for c in df.columns:
            cl = c.lower()
            if "latitude" in cl and "deg" in cl:
                lat_col = c
            elif "longitude" in cl and "deg" in cl:
                lon_col = c
            elif cl in ("distance_m", "distance", "distance (m)"):
                dist_col = c
            elif cl in ("speed_mps", "speed (m/s)", "speed"):
                spd_col = c

        # Must have at least lat + lon.
        if lat_col is None or lon_col is None:
            continue

        lats = df[lat_col].values
        lons = df[lon_col].values

        # Distance: use column or synthesize from index/row number.
        if dist_col and dist_col in df.columns:
            dists = df[dist_col].values
        elif hasattr(df.index, "name") and df.index.name == "distance_m":
            dists = df.index.values
        else:
            dists = np.arange(len(df), dtype=float)

        # Speed.
        if spd_col and spd_col in df.columns:
            speeds = df[spd_col].values
        else:
            # Try to find any speed column.
            for c in df.columns:
                if "speed" in c.lower():
                    speeds = df[c].values
                    break
            else:
                speeds = np.zeros(len(df))

        # Acceleration columns for G-G diagram.
        accel_lat_col = None
        accel_long_col = None
        for c in df.columns:
            cl = c.lower()
            if accel_lat_col is None and (
                "accel_lat" in cl
                or ("lateral" in cl and "accel" in cl)
                or cl == "lateral acceleration (g) *calc"
            ):
                accel_lat_col = c
            if accel_long_col is None and (
                "accel_long" in cl
                or ("longitudinal" in cl and "accel" in cl)
                or cl == "acceleration (m/s²)"
            ):
                accel_long_col = c

        accel_lat_json = _np_to_json(df[accel_lat_col].values) if accel_lat_col else None
        accel_long_json = _np_to_json(df[accel_long_col].values) if accel_long_col else None

        # ── Rich telemetry channels ──────────────────────────────
        cols_lower = {c.lower(): c for c in df.columns}

        def _col_json(canonical: str):
            """Return JSON array for a canonical column name, or None."""
            real = cols_lower.get(canonical)
            return _np_to_json(df[real].values) if real else None

        throttle_json = _col_json("throttle_pct")
        brake_json = _col_json("brake_pct")
        steering_json = _col_json("steering_angle_deg")
        rpm_json = _col_json("rpm")
        gear_json = _col_json("gear")
        fuel_json = _col_json("fuel_kg")

        # Tire temps: 4 corners x 3 zones (inner/middle/outer) + single-value
        tire_temp_data = {}
        for corner in ("fl", "fr", "rl", "rr"):
            zones = {}
            for zone in ("i", "m", "o"):
                key = f"tire_temp_{corner}_{zone}"
                real = cols_lower.get(key)
                if real:
                    zones[zone] = json.loads(_np_to_json(df[real].values))
            if not zones:
                # Try single-value tire temp per corner.
                key = f"tire_temp_{corner}"
                real = cols_lower.get(key)
                if real:
                    zones["avg"] = json.loads(_np_to_json(df[real].values))
            if zones:
                tire_temp_data[corner] = zones
        tire_temp_json_str = json.dumps(tire_temp_data) if tire_temp_data else None

        # Tire pressures: 4 corners
        tire_pressure_data = {}
        for corner in ("fl", "fr", "rl", "rr"):
            real = cols_lower.get(f"tire_pressure_{corner}")
            if real:
                tire_pressure_data[corner] = json.loads(_np_to_json(df[real].values))
        tire_pressure_json_str = json.dumps(tire_pressure_data) if tire_pressure_data else None

        # Brake temps: 4 corners
        brake_temp_data = {}
        for corner in ("fl", "fr", "rl", "rr"):
            real = cols_lower.get(f"brake_temp_{corner}")
            if real:
                brake_temp_data[corner] = json.loads(_np_to_json(df[real].values))
        brake_temp_json_str = json.dumps(brake_temp_data) if brake_temp_data else None

        # Wheel slip ratios: 4 corners
        wheel_slip_data = {}
        for corner in ("fl", "fr", "rl", "rr"):
            real = cols_lower.get(f"slip_ratio_{corner}")
            if real:
                wheel_slip_data[corner] = json.loads(_np_to_json(df[real].values))
        wheel_slip_json_str = json.dumps(wheel_slip_data) if wheel_slip_data else None

        conn.execute(Q.INSERT_GPS_TRACE, {
            "session_id":      session_id,
            "lap_number":      int(lap_num),
            "latitudes_json":  _np_to_json(lats),
            "longitudes_json": _np_to_json(lons),
            "distances_json":  _np_to_json(dists),
            "speeds_json":     _np_to_json(speeds),
            "accel_lat_json":  accel_lat_json,
            "accel_long_json": accel_long_json,
            "throttle_json":      throttle_json,
            "brake_json":         brake_json,
            "steering_json":      steering_json,
            "rpm_json":           rpm_json,
            "gear_json":          gear_json,
            "tire_temp_json":     tire_temp_json_str,
            "tire_pressure_json": tire_pressure_json_str,
            "brake_temp_json":    brake_temp_json_str,
            "wheel_slip_json":    wheel_slip_json_str,
            "fuel_json":          fuel_json,
        })
        count += 1

    return count


def get_gps_trace(
    conn: sqlite3.Connection,
    session_id: str,
    lap_number: int,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_GPS_TRACE,
        {"session_id": session_id, "lap_number": lap_number},
    ).fetchone()
    if row is None:
        return None
    result = {
        "latitudes":  _parse_json_or_list(row["latitudes_json"]),
        "longitudes": _parse_json_or_list(row["longitudes_json"]),
        "distances":  _parse_json_or_list(row["distances_json"]),
        "speeds":     _parse_json_or_list(row["speeds_json"]),
    }
    if row["accel_lat_json"]:
        result["accel_lat"] = _parse_json_or_list(row["accel_lat_json"])
    if row["accel_long_json"]:
        result["accel_long"] = _parse_json_or_list(row["accel_long_json"])
    return result


def get_channel_data(
    conn: sqlite3.Connection,
    session_id: str,
    lap_number: int,
) -> Optional[dict]:
    """Return all rich telemetry channel data for a specific lap.

    Returns a dict with keys for each channel group, or None if no row exists.
    Each value is either a list (single-channel) or a dict (multi-corner).
    """
    row = conn.execute(
        Q.SELECT_GPS_TRACE_CHANNELS,
        {"session_id": session_id, "lap_number": lap_number},
    ).fetchone()
    if row is None:
        return None

    result: dict[str, Any] = {
        "distances": _parse_json_or_list(row["distances_json"]),
        "speeds": _parse_json_or_list(row["speeds_json"]),
    }

    _SIMPLE_CHANNELS = [
        ("throttle_json", "throttle"),
        ("brake_json", "brake"),
        ("steering_json", "steering"),
        ("rpm_json", "rpm"),
        ("gear_json", "gear"),
        ("fuel_json", "fuel"),
    ]
    for col, key in _SIMPLE_CHANNELS:
        val = row[col]
        if val:
            result[key] = _parse_json_or_list(val)

    _DICT_CHANNELS = [
        ("tire_temp_json", "tire_temps"),
        ("tire_pressure_json", "tire_pressures"),
        ("brake_temp_json", "brake_temps"),
        ("wheel_slip_json", "wheel_slip"),
    ]
    for col, key in _DICT_CHANNELS:
        val = row[col]
        if val:
            result[key] = _parse_json_or_list(val)

    return result


def get_channel_availability(
    conn: sqlite3.Connection,
    session_id: str,
) -> dict[str, bool]:
    """Check which rich channels are stored for a session (any lap).

    Returns a dict mapping channel name to True/False.
    """
    row = conn.execute(
        "SELECT throttle_json, brake_json, steering_json, "
        "       rpm_json, gear_json, tire_temp_json, "
        "       tire_pressure_json, brake_temp_json, "
        "       wheel_slip_json, fuel_json "
        "FROM gps_traces "
        "WHERE session_id = :session_id LIMIT 1;",
        {"session_id": session_id},
    ).fetchone()
    if row is None:
        return {}
    return {
        "throttle": row["throttle_json"] is not None,
        "brake": row["brake_json"] is not None,
        "steering": row["steering_json"] is not None,
        "rpm": row["rpm_json"] is not None,
        "gear": row["gear_json"] is not None,
        "tire_temps": row["tire_temp_json"] is not None,
        "tire_pressures": row["tire_pressure_json"] is not None,
        "brake_temps": row["brake_temp_json"] is not None,
        "wheel_slip": row["wheel_slip_json"] is not None,
        "fuel": row["fuel_json"] is not None,
    }
