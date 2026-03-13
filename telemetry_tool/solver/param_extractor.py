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

    # Safety clamps: degenerate values cause solver division-by-zero or infeasibility
    # Upper clamp: no production tire exceeds mu ≈ 2.2 (even F1 slicks).
    # Higher values indicate measured lateral-g is inflated by aerodynamic
    # downforce; the solver already models downforce separately via Cl,
    # so leaving mu_ref uncapped would double-count the grip contribution.
    _MU_CEILING = 2.2
    if params.mu_ref > _MU_CEILING:
        logger.warning("mu_ref=%.3f exceeds physical tire limit (%.1f), "
                        "likely inflated by aero downforce — clamping",
                        params.mu_ref, _MU_CEILING)
        params.mu_ref = _MU_CEILING
    if params.mu_ref < 0.3:
        logger.warning("mu_ref=%.3f too low (sensor failure?), clamping to base %.3f",
                        params.mu_ref, base_params.mu_ref)
        params.mu_ref = max(params.mu_ref, base_params.mu_ref * 0.5)
        params.mu_ref = max(params.mu_ref, 0.3)  # absolute floor
    if params.P_max < 1000.0:
        logger.warning("P_max=%.0fW too low, clamping to base %.0fW",
                        params.P_max, base_params.P_max)
        params.P_max = max(params.P_max, base_params.P_max * 0.5)
    if params.F_brake_max < 500.0:
        logger.warning("F_brake_max=%.0fN too low, clamping to base %.0fN",
                        params.F_brake_max, base_params.F_brake_max)
        params.F_brake_max = max(params.F_brake_max, base_params.F_brake_max * 0.5)
    if params.F_drive_max < 200.0:
        params.F_drive_max = max(params.F_drive_max, base_params.F_drive_max * 0.5)

    logger.info("OCP params extracted: mu_ref=%.3f, P_max=%.0fW, F_brake=%.0fN, F_drive=%.0fN",
                params.mu_ref, params.P_max, params.F_brake_max, params.F_drive_max)
    return params
