"""Traction budget analyzer — friction circle utilization at entry/apex/exit."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from telemetry_tool.coaching.models import TractionBudget


def analyze_traction_budget(
    corner: dict,
    lap: pd.DataFrame,
    friction_max: float,
) -> TractionBudget:
    """Compute friction circle utilization at entry, apex, and exit zones.

    Zones are defined as:
    - Entry: first 25% of corner
    - Apex: middle 25% centered on s_apex
    - Exit: last 25% of corner
    """
    corner_id = corner["corner_id"]
    s_start = corner["s_start"]
    s_end = corner["s_end"]
    s_apex = corner.get("s_apex", (s_start + s_end) / 2)
    corner_len = s_end - s_start

    dist = lap["Distance (m)"].values
    lat = lap["Lateral acceleration (m/s2)"].values
    lon = lap["Longitudinal acceleration (m/s2)"].values

    # Define zone boundaries
    entry_end = s_start + corner_len * 0.25
    apex_start = s_apex - corner_len * 0.125
    apex_end = s_apex + corner_len * 0.125
    exit_start = s_end - corner_len * 0.25

    entry_data = _zone_data(dist, lat, lon, s_start, entry_end)
    apex_data = _zone_data(dist, lat, lon, apex_start, apex_end)
    exit_data = _zone_data(dist, lat, lon, exit_start, s_end)

    entry_lat_pct, entry_lon_pct, entry_total_pct = _compute_pcts(entry_data, friction_max)
    apex_lat_pct, apex_lon_pct, apex_total_pct = _compute_pcts(apex_data, friction_max)
    exit_lat_pct, exit_lon_pct, exit_total_pct = _compute_pcts(exit_data, friction_max)

    # Theoretical apex: assume friction_max fully utilized laterally
    theoretical_apex_total = min(100.0, (friction_max / max(friction_max, 0.01)) * 100)

    return TractionBudget(
        corner_id=corner_id,
        entry_lateral_pct=entry_lat_pct,
        entry_longitudinal_pct=entry_lon_pct,
        entry_total_pct=entry_total_pct,
        entry_remaining_pct=100.0 - entry_total_pct,
        apex_lateral_pct=apex_lat_pct,
        apex_longitudinal_pct=apex_lon_pct,
        apex_total_pct=apex_total_pct,
        apex_remaining_pct=100.0 - apex_total_pct,
        exit_lateral_pct=exit_lat_pct,
        exit_longitudinal_pct=exit_lon_pct,
        exit_total_pct=exit_total_pct,
        exit_remaining_pct=100.0 - exit_total_pct,
        theoretical_apex_total_pct=theoretical_apex_total,
        grip_headroom_pct=theoretical_apex_total - apex_total_pct,
    )


def _zone_data(
    dist: np.ndarray, lat: np.ndarray, lon: np.ndarray,
    s_start: float, s_end: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract lateral and longitudinal accel for a distance zone."""
    mask = (dist >= s_start) & (dist <= s_end)
    return np.abs(lat[mask]), np.abs(lon[mask])


def _compute_pcts(
    data: tuple[np.ndarray, np.ndarray],
    friction_max: float,
) -> tuple[float, float, float]:
    """Compute percentage utilization from zone accel data."""
    lat_arr, lon_arr = data
    if len(lat_arr) == 0:
        return 0.0, 0.0, 0.0

    avg_lat = float(np.mean(lat_arr))
    avg_lon = float(np.mean(lon_arr))

    # Combined via friction circle: sqrt(lat^2 + lon^2) / friction_max
    combined = math.sqrt(avg_lat ** 2 + avg_lon ** 2)
    total_pct = min((combined / max(friction_max, 0.01)) * 100.0, 100.0)
    lat_pct = min((avg_lat / max(friction_max, 0.01)) * 100.0, 100.0)
    lon_pct = min((avg_lon / max(friction_max, 0.01)) * 100.0, 100.0)

    return lat_pct, lon_pct, total_pct
