"""Quasi-Steady-State (QSS) lap-time solver -- fallback when CasADi is
unavailable or the full OCP fails to converge.

Algorithm:
    1.  Compute cornering speed limit from curvature + vehicle.
    2.  Forward integration: limit acceleration by tyre + power.
    3.  Backward integration: limit braking by tyre + aero.
    4.  Final speed = element-wise minimum of three profiles.
    5.  Lap time = sum(ds / v_avg).
"""
from __future__ import annotations

import time
from typing import List

import numpy as np

from telemetry_tool.lap_oracle.config import (
    OCPSolution,
    TrackModel,
    VehicleParams,
    WeatherConditions,
)
from telemetry_tool.lap_oracle.physics.bicycle_model import (
    corner_speed,
    max_longitudinal_accel,
)
from telemetry_tool.lap_oracle.track.model import resample_track


def solve_qss(
    track: TrackModel,
    vehicle: VehicleParams,
    weather: WeatherConditions | None = None,
) -> OCPSolution:
    """Solve for the quasi-steady-state speed profile.

    Parameters
    ----------
    track:
        Discretized track model.
    vehicle:
        Vehicle parameters.
    weather:
        Optional weather conditions (grip multiplier applied).

    Returns
    -------
    OCPSolution
        Solution with ``solver_status="qss_fallback"``.
    """
    t0 = time.perf_counter()

    if weather is None:
        weather = WeatherConditions()

    # Resample to roughly 1 m spacing if needed
    if track.n_points < 10:
        raise ValueError("Track needs at least 10 points for QSS solve")
    ds_target = max(track.total_length_m / 500.0, 1.0)
    tk = resample_track(track, ds_target=ds_target)

    n = tk.n_points
    ds = tk.ds  # length N-1
    kappa = np.abs(tk.curvature)

    # -- Step 1: cornering speed limit ------------------------------------
    v_max = corner_speed(kappa, vehicle) * weather.grip_multiplier

    # -- Step 2: forward pass (acceleration-limited) ----------------------
    v_fwd = v_max.copy()
    for i in range(n - 1):
        a_accel = max_longitudinal_accel(v_fwd[i], vehicle, braking=False)
        v_next = np.sqrt(max(v_fwd[i] ** 2 + 2.0 * a_accel * ds[i], 0.0))
        v_fwd[i + 1] = min(v_fwd[i + 1], v_next)

    # -- Step 3: backward pass (braking-limited) --------------------------
    v_bwd = v_max.copy()
    for i in range(n - 2, -1, -1):
        a_brake = max_longitudinal_accel(v_bwd[i + 1], vehicle, braking=True)
        v_prev = np.sqrt(max(v_bwd[i + 1] ** 2 + 2.0 * a_brake * ds[i], 0.0))
        v_bwd[i] = min(v_bwd[i], v_prev)

    # -- Step 4: combine --------------------------------------------------
    v_opt = np.minimum(v_max, np.minimum(v_fwd, v_bwd))
    v_opt = np.clip(v_opt, 5.0, 400.0)

    # -- Step 5: lap time -------------------------------------------------
    v_avg = (v_opt[:-1] + v_opt[1:]) / 2.0
    v_avg = np.maximum(v_avg, 1.0)  # guard against zero
    dt_seg = ds / v_avg
    lap_time = float(np.sum(dt_seg))

    # -- Post-process channels --------------------------------------------
    ax = np.diff(v_opt ** 2) / (2.0 * ds)
    throttle = np.where(ax >= 0, np.clip(ax / 10.0, 0.0, 1.0), 0.0)
    brake = np.where(ax < 0, np.clip(-ax / 15.0, 0.0, 1.0), 0.0)
    # Pad to length N
    throttle = np.concatenate([throttle, [throttle[-1]]])
    brake = np.concatenate([brake, [brake[-1]]])

    distance_m = np.concatenate(([0.0], np.cumsum(ds)))

    # -- Sector times -----------------------------------------------------
    sector_times = _compute_sector_times(
        tk.sector_boundaries, distance_m, v_opt, ds,
    )

    elapsed = time.perf_counter() - t0

    return OCPSolution(
        sim=track.sim,
        track_name=track.name,
        car_name=vehicle.car_name,
        weather=weather,
        optimal_lap_time_s=lap_time,
        sector_times_s=sector_times,
        distance_m=distance_m,
        speed_mps=v_opt,
        throttle=throttle,
        brake=brake,
        steering_rad=np.zeros(n, dtype=np.float64),
        lateral_offset_m=np.zeros(n, dtype=np.float64),
        solver_status="qss_fallback",
        solver_time_s=elapsed,
        vehicle_params=vehicle,
    )


def _compute_sector_times(
    sector_boundaries: List[int],
    distance_m: np.ndarray,
    v_opt: np.ndarray,
    ds: np.ndarray,
) -> List[float]:
    """Compute sector times from boundary indices."""
    if not sector_boundaries:
        return []

    v_avg = (v_opt[:-1] + v_opt[1:]) / 2.0
    v_avg = np.maximum(v_avg, 1.0)
    dt_seg = ds / v_avg

    boundaries = [0] + list(sector_boundaries) + [len(dt_seg)]
    sector_times: List[float] = []
    for j in range(len(boundaries) - 1):
        s_start = boundaries[j]
        s_end = min(boundaries[j + 1], len(dt_seg))
        if s_start < s_end:
            sector_times.append(float(np.sum(dt_seg[s_start:s_end])))
    return sector_times
