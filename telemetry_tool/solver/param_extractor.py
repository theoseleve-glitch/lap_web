"""Extract OCP vehicle parameters from session telemetry data."""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd
from solver.vehicle_params import OCPVehicleParams

logger = logging.getLogger(__name__)
_G = 9.80665
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_ACCEL_LAT = "accel_lat_mps2"


def extract_session_params(
    best_lap_df: pd.DataFrame,
    base_params: OCPVehicleParams,
    percentile: float = 98.0,
) -> OCPVehicleParams:
    import dataclasses
    params = dataclasses.replace(base_params)
    has_accel_long = _COL_ACCEL_LONG in best_lap_df.columns
    has_accel_lat = _COL_ACCEL_LAT in best_lap_df.columns
    has_speed = _COL_SPEED in best_lap_df.columns
    speed = best_lap_df[_COL_SPEED].to_numpy(dtype=float) if has_speed else None

    if has_accel_lat:
        a_lat = best_lap_df[_COL_ACCEL_LAT].to_numpy(dtype=float)
        a_lat_valid = a_lat[np.isfinite(a_lat)]
        if len(a_lat_valid) > 10:
            peak_lat = float(np.percentile(np.abs(a_lat_valid), percentile))
            params.mu_ref = peak_lat / _G

    if has_accel_long and speed is not None:
        a_long = best_lap_df[_COL_ACCEL_LONG].to_numpy(dtype=float)
        mask = np.isfinite(a_long) & np.isfinite(speed) & (a_long > 0.5) & (speed > 5.0)
        if mask.sum() > 5:
            power_arr = a_long[mask] * params.mass * speed[mask]
            params.P_max = float(np.percentile(power_arr, percentile))

    if has_accel_long:
        a_long = best_lap_df[_COL_ACCEL_LONG].to_numpy(dtype=float)
        a_long_valid = a_long[np.isfinite(a_long)]
        if len(a_long_valid) > 10:
            braking_vals = np.abs(a_long_valid[a_long_valid < -0.5])
            if len(braking_vals) > 0:
                peak_brake = float(np.percentile(braking_vals, percentile))
                params.F_brake_max = peak_brake * params.mass

    if has_accel_long and speed is not None:
        a_long = best_lap_df[_COL_ACCEL_LONG].to_numpy(dtype=float)
        low_speed_mask = (np.isfinite(a_long) & np.isfinite(speed) & (a_long > 0.5) & (speed < 20.0))
        if low_speed_mask.sum() > 3:
            peak_traction = float(np.percentile(a_long[low_speed_mask], percentile))
            params.F_drive_max = peak_traction * params.mass

    if params.P_max <= 0 and params.F_drive_max > 0:
        params.P_max = params.F_drive_max * 20.0

    logger.info("OCP params extracted: mu_ref=%.3f, P_max=%.0fW, F_brake=%.0fN, F_drive=%.0fN",
                params.mu_ref, params.P_max, params.F_brake_max, params.F_drive_max)
    return params
