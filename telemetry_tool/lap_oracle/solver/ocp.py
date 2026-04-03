"""CasADi minimum-time optimal control problem solver.

Spatial (arc-length) formulation: the independent variable is distance
*s* along the centerline, NOT time.  Decision variables are speed V[N],
lateral offset N_lat[N], and longitudinal acceleration Ax[N-1] between
discretization points.

If CasADi is not installed the module automatically falls back to the
QSS solver in :mod:`fallback_qss`.
"""
from __future__ import annotations

import logging
import time
from typing import List

import numpy as np

from telemetry_tool.lap_oracle.config import (
    OCPSolution,
    TrackModel,
    VehicleParams,
    WeatherConditions,
)
from telemetry_tool.lap_oracle.physics.bicycle_model import corner_speed
from telemetry_tool.lap_oracle.track.model import resample_track

logger = logging.getLogger(__name__)

# -- Optional CasADi import ------------------------------------------------
try:
    import casadi as ca

    HAS_CASADI = True
except ImportError:
    HAS_CASADI = False

# -- Physical constants ----------------------------------------------------
G: float = 9.80665
RHO_AIR: float = 1.225


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def solve_minimum_time(
    track: TrackModel,
    vehicle: VehicleParams,
    weather: WeatherConditions | None = None,
    n_points: int = 500,
    max_time_s: float = 120.0,
) -> OCPSolution:
    """Solve the minimum-time OCP for *track* and *vehicle*.

    If CasADi is not available, transparently delegates to the QSS
    fallback solver.

    Parameters
    ----------
    track:
        Discretized track model.
    vehicle:
        Vehicle parameters.
    weather:
        Optional weather conditions.
    n_points:
        Number of discretization points along the centerline.
    max_time_s:
        IPOPT wall-clock time limit in seconds.

    Returns
    -------
    OCPSolution
    """
    if not HAS_CASADI:
        logger.info("CasADi not available -- falling back to QSS solver")
        from telemetry_tool.lap_oracle.solver.fallback_qss import solve_qss

        return solve_qss(track, vehicle, weather)

    if weather is None:
        weather = WeatherConditions()

    return _solve_casadi(track, vehicle, weather, n_points, max_time_s)


# --------------------------------------------------------------------------
# CasADi NLP
# --------------------------------------------------------------------------

def _solve_casadi(
    track: TrackModel,
    vehicle: VehicleParams,
    weather: WeatherConditions,
    n_points: int,
    max_time_s: float,
) -> OCPSolution:
    """Build and solve the IPOPT NLP via CasADi Opti."""
    t0 = time.perf_counter()

    # -- Resample track to the requested grid size -------------------------
    ds_target = track.total_length_m / n_points
    tk = resample_track(track, ds_target=ds_target)
    N = tk.n_points
    ds = tk.ds.astype(np.float64)          # (N-1,)
    kappa = np.abs(tk.curvature).astype(np.float64)   # (N,)

    # -- Vehicle shorthand -------------------------------------------------
    m = vehicle.mass_kg
    cda = vehicle.cda
    cla = vehicle.cla
    p_max = vehicle.max_power_w
    a_brake_max = vehicle.max_brake_decel
    mu_lat = vehicle.tyre_lat.D * weather.grip_multiplier
    mu_long = vehicle.tyre_long.D * weather.grip_multiplier

    # -- Initial guess: cornering speed ------------------------------------
    v_guess = corner_speed(kappa, vehicle) * weather.grip_multiplier
    v_guess = np.clip(v_guess, 10.0, 100.0)

    # -- CasADi Opti -------------------------------------------------------
    opti = ca.Opti()

    V = opti.variable(N)         # speed at each point
    N_lat = opti.variable(N)     # lateral offset
    Ax = opti.variable(N - 1)   # longitudinal accel between points

    # Warm-start
    opti.set_initial(V, v_guess)
    opti.set_initial(N_lat, np.zeros(N))
    opti.set_initial(Ax, np.zeros(N - 1))

    # -- Objective: minimise total lap time --------------------------------
    #    dt_i = ds_i / v_avg_i  with  v_avg_i = (V[i] + V[i+1]) / 2
    total_time = 0
    for i in range(N - 1):
        v_avg = (V[i] + V[i + 1]) / 2.0
        total_time = total_time + ds[i] / v_avg

    opti.minimize(total_time)

    # -- Constraints (per segment) -----------------------------------------
    for i in range(N - 1):
        # 1. Speed dynamics
        opti.subject_to(V[i + 1] ** 2 == V[i] ** 2 + 2 * Ax[i] * ds[i])

        # 2. Lateral accel from curvature
        ay_i = V[i] ** 2 * kappa[i]

        # 3. Downforce
        fz_aero = 0.5 * RHO_AIR * cla * V[i] ** 2
        fz_total = m * G + fz_aero

        # 4. Friction ellipse
        ax_lim = mu_long * fz_total / m
        ay_lim = mu_lat * fz_total / m
        opti.subject_to(
            (Ax[i] / ax_lim) ** 2 + (ay_i / ay_lim) ** 2 <= 1.0
        )

        # 5. Power limit
        drag = 0.5 * RHO_AIR * cda * V[i] ** 2 / m
        rr = 0.01 * G
        v_safe = ca.fmax(V[i], 5.0)
        opti.subject_to(Ax[i] <= p_max / (m * v_safe) - drag - rr)

        # 6. Brake limit
        opti.subject_to(Ax[i] >= -(a_brake_max + drag + rr))

    # 7. Speed bounds
    opti.subject_to(opti.bounded(5.0, V, 120.0))

    # 8. Track boundary limits
    for i in range(N):
        w_left = float(tk.width_left[i]) * 0.9
        w_right = float(tk.width_right[i]) * 0.9
        opti.subject_to(opti.bounded(-w_right, N_lat[i], w_left))

    # 9. Periodic boundary conditions
    opti.subject_to(V[0] == V[N - 1])
    opti.subject_to(N_lat[0] == N_lat[N - 1])

    # -- IPOPT solver options ----------------------------------------------
    opts = {
        "ipopt.max_iter": 3000,
        "ipopt.max_cpu_time": max_time_s,
        "ipopt.print_level": 0,
        "ipopt.sb": "yes",
        "print_time": 0,
    }
    opti.solver("ipopt", opts)

    # -- Solve -------------------------------------------------------------
    status = "optimal"
    try:
        sol = opti.solve()
        v_sol = np.array(sol.value(V)).flatten()
        n_lat_sol = np.array(sol.value(N_lat)).flatten()
        ax_sol = np.array(sol.value(Ax)).flatten()
    except RuntimeError:
        logger.warning("IPOPT did not converge -- extracting debug values")
        status = "suboptimal"
        v_sol = np.array(opti.debug.value(V)).flatten()
        n_lat_sol = np.array(opti.debug.value(N_lat)).flatten()
        ax_sol = np.array(opti.debug.value(Ax)).flatten()
        # Clip speed to feasible range even if solver failed
        v_sol = np.clip(v_sol, 5.0, 120.0)

    elapsed = time.perf_counter() - t0

    # -- Post-process -------------------------------------------------------
    return _build_solution(
        track, vehicle, weather, tk, v_sol, n_lat_sol, ax_sol,
        ds, status, elapsed,
    )


# --------------------------------------------------------------------------
# Post-processing
# --------------------------------------------------------------------------

def _build_solution(
    track: TrackModel,
    vehicle: VehicleParams,
    weather: WeatherConditions,
    tk: TrackModel,
    v_sol: np.ndarray,
    n_lat_sol: np.ndarray,
    ax_sol: np.ndarray,
    ds: np.ndarray,
    status: str,
    elapsed: float,
) -> OCPSolution:
    """Package solver arrays into an :class:`OCPSolution`."""
    N = len(v_sol)

    # Lap time
    v_avg = (v_sol[:-1] + v_sol[1:]) / 2.0
    v_avg = np.maximum(v_avg, 1.0)
    dt_seg = ds / v_avg
    lap_time = float(np.sum(dt_seg))

    # Throttle / brake from ax
    throttle = np.where(ax_sol >= 0, np.clip(ax_sol / 10.0, 0.0, 1.0), 0.0)
    brake = np.where(ax_sol < 0, np.clip(-ax_sol / 15.0, 0.0, 1.0), 0.0)
    # Pad to length N
    throttle = np.concatenate([throttle, [throttle[-1]]])
    brake = np.concatenate([brake, [brake[-1]]])

    # Distance
    distance_m = np.concatenate(([0.0], np.cumsum(ds)))

    # Steering placeholder
    steering = np.zeros(N, dtype=np.float64)

    # Sector times
    sector_times = _compute_sector_times(
        tk.sector_boundaries, distance_m, v_sol, ds,
    )

    return OCPSolution(
        sim=track.sim,
        track_name=track.name,
        car_name=vehicle.car_name,
        weather=weather,
        optimal_lap_time_s=lap_time,
        sector_times_s=sector_times,
        distance_m=distance_m,
        speed_mps=v_sol,
        throttle=throttle,
        brake=brake,
        steering_rad=steering,
        lateral_offset_m=n_lat_sol,
        solver_status=status,
        solver_time_s=elapsed,
        vehicle_params=vehicle,
    )


def _compute_sector_times(
    sector_boundaries: List[int],
    distance_m: np.ndarray,
    v_sol: np.ndarray,
    ds: np.ndarray,
) -> List[float]:
    """Compute sector times from boundary indices."""
    if not sector_boundaries:
        return []

    v_avg = (v_sol[:-1] + v_sol[1:]) / 2.0
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
