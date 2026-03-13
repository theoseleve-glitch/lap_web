# telemetry_tool/solver/ocp_solver.py
"""CasADi/IPOPT optimal control solver for minimum-time lap.

Formulates the minimum-time problem as a nonlinear program (NLP):
  - Decision variables: speed v[i] at each collocation node
  - Objective: minimize sum(ds[i] / v[i])  (= total time)
  - Dynamics: v[i+1]^2 = v[i]^2 + 2 * a_net[i] * ds[i]
  - Grip constraint: friction ellipse at each node
  - Complementarity: u_throttle * u_brake <= epsilon (relaxed)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import casadi as ca
import numpy as np

from solver.result import TheoreticalResult
from solver.tire_model import LoadSensitiveTire
from solver.track_model import TrackMesh
from solver.vehicle_params import OCPVehicleParams

logger = logging.getLogger(__name__)

_G = 9.80665
_V_MIN = 2.0       # minimum speed (m/s) to avoid division by zero
_EPSILON = 1e-4     # complementarity relaxation


def solve_ocp(
    mesh: TrackMesh,
    params: OCPVehicleParams,
    tire: LoadSensitiveTire,
    warm_start: Optional[np.ndarray] = None,
    max_iter: int = 500,
    tol: float = 1e-4,
) -> TheoreticalResult:
    """Solve the minimum-time OCP using CasADi + IPOPT.

    Parameters
    ----------
    mesh : Track mesh with distance nodes and curvature.
    params : Vehicle parameters.
    tire : Tire model.
    warm_start : Initial speed guess at each node (m/s). If None, uses
        curvature-based guess.
    max_iter : IPOPT maximum iterations.
    tol : IPOPT convergence tolerance.

    Returns
    -------
    TheoreticalResult with speed profile, lap time, and solver metadata.
    """
    t_start = time.monotonic()
    N = len(mesh.s)
    ds = mesh.ds  # (N-1,)

    # ── Decision variables ──
    opti = ca.Opti()

    v = opti.variable(N)       # speed at each node
    u_thr = opti.variable(N)   # throttle [0, 1]
    u_brk = opti.variable(N)   # brake [0, 1]

    # ── Bounds ──
    opti.subject_to(v >= _V_MIN)
    opti.subject_to(opti.bounded(0, u_thr, 1))
    opti.subject_to(opti.bounded(0, u_brk, 1))

    # ── Objective: minimize lap time ──
    dt_sum = 0
    for i in range(N - 1):
        v_avg = (v[i] + v[i + 1]) / 2.0
        dt_sum += ds[i] / v_avg
    opti.minimize(dt_sum)

    # ── Dynamics constraints ──
    Fz_static = params.Fz_static_per_axle

    for i in range(N - 1):
        kappa_i = float(mesh.kappa[i])

        # Longitudinal acceleration components
        a_drive = ca.fmin(
            u_thr[i] * params.P_max / (params.mass * v[i]),
            params.F_drive_max / params.mass,
        )
        a_brake = u_brk[i] * params.F_brake_max / params.mass
        a_drag = 0.5 * params.rho * params.Cd * params.A * v[i] ** 2 / params.mass
        a_rolling = params.Cr * _G
        F_downforce = 0.5 * params.rho * params.Cl * params.A * v[i] ** 2

        a_long = a_drive - a_brake - a_drag - a_rolling

        # Dynamics: v[i+1]^2 = v[i]^2 + 2 * a_long * ds
        opti.subject_to(v[i + 1] ** 2 == v[i] ** 2 + 2 * a_long * ds[i])

        # Lateral acceleration from curvature
        a_lat = v[i] ** 2 * abs(kappa_i)

        # Load transfer (affects grip via load sensitivity)
        dFz_long = params.mass * ca.fabs(a_long) * params.h_cg / params.wheelbase
        dFz_lat = params.mass * a_lat * params.h_cg / params.track_width

        # Effective vertical load per axle including downforce and transfer
        Fz_base = Fz_static + F_downforce / 2.0
        Fz_loaded = Fz_base + dFz_lat
        Fz_unloaded = ca.fmax(Fz_base - dFz_lat, 1.0)

        # Grip limits with load sensitivity
        if abs(params.load_sensitivity) > 1e-6 and params.h_cg > 0:
            log_r_loaded = ca.log(
                ca.fmax(Fz_loaded, 1.0) / ca.fmax(Fz_static, 1.0)
            )
            mu_loaded = params.mu_ref * ca.exp(
                params.load_sensitivity * log_r_loaded
            )
            log_r_unloaded = ca.log(
                ca.fmax(Fz_unloaded, 1.0) / ca.fmax(Fz_static, 1.0)
            )
            mu_unloaded = params.mu_ref * ca.exp(
                params.load_sensitivity * log_r_unloaded
            )

            F_grip_total = mu_loaded * Fz_loaded + mu_unloaded * Fz_unloaded
            a_grip_max = F_grip_total / params.mass
        else:
            Fz_total = Fz_loaded + Fz_unloaded
            a_grip_max = params.mu_ref * Fz_total / params.mass

        # Friction ellipse: (a_long/a_max)^2 + (a_lat/a_max)^2 <= 1
        opti.subject_to(
            (a_long / a_grip_max) ** 2 + (a_lat / a_grip_max) ** 2 <= 1.0
        )

        # Complementarity: no simultaneous throttle + brake
        opti.subject_to(u_thr[i] * u_brk[i] <= _EPSILON)

    # ── Boundary condition: lap continuity ──
    opti.subject_to(v[0] == v[N - 1])

    # ── Initial guess ──
    if warm_start is not None:
        opti.set_initial(v, warm_start)
    else:
        # Power-limited top speed: P = F*v, at top speed drag = drive
        # 0.5 * rho * Cd * A * v^3 = P_max  =>  v_max = (2*P/(rho*Cd*A))^(1/3)
        drag_coeff = 0.5 * params.rho * params.Cd * params.A
        if drag_coeff > 1e-6:
            v_top = (params.P_max / drag_coeff) ** (1.0 / 3.0)
        else:
            v_top = 50.0  # fallback for zero-drag (karts)
        v_straight = min(v_top, 50.0)  # cap at 180 km/h

        v_guess = np.full(N, v_straight)
        for i in range(N):
            k = abs(float(mesh.kappa[i]))
            if k > 1e-4:
                v_corner = np.sqrt(params.mu_ref * _G / k)
                v_guess[i] = min(v_guess[i], v_corner)
        v_guess = np.maximum(v_guess, _V_MIN)
        opti.set_initial(v, v_guess)

    opti.set_initial(u_thr, 0.5)
    opti.set_initial(u_brk, 0.0)

    # ── Solver options ──
    opts = {
        "ipopt.max_iter": max_iter,
        "ipopt.tol": tol,
        "ipopt.acceptable_tol": 1e-3,
        "ipopt.acceptable_iter": 15,      # accept if in acceptable region for 15 iters
        "ipopt.acceptable_obj_change_tol": 1e-4,  # stop if objective barely moves
        "ipopt.mu_strategy": "adaptive",  # adaptive barrier parameter
        "ipopt.print_level": 0,
        "ipopt.warm_start_init_point": "yes",
        "print_time": False,
    }
    opti.solver("ipopt", opts)

    # ── Solve ──
    converged = True
    iterations = 0
    try:
        sol = opti.solve()
        v_sol = sol.value(v)
        u_thr_sol = sol.value(u_thr)
        u_brk_sol = sol.value(u_brk)
        iterations = int(sol.stats()["iter_count"])
    except RuntimeError as e:
        logger.warning("IPOPT failed to converge: %s -- using last iterate", e)
        converged = False
        v_sol = opti.debug.value(v)
        u_thr_sol = opti.debug.value(u_thr)
        u_brk_sol = opti.debug.value(u_brk)
        iterations = max_iter

    v_arr = np.array(v_sol).flatten()
    # Sanitize NaN from failed solver iterates (IPOPT can produce NaN on hard failure)
    nan_mask = ~np.isfinite(v_arr)
    if nan_mask.any():
        logger.warning("IPOPT produced %d NaN speed values — replacing with V_MIN", int(nan_mask.sum()))
        v_arr[nan_mask] = _V_MIN
    v_arr = np.maximum(v_arr, _V_MIN)

    # Compute derived quantities
    a_lat_arr = v_arr ** 2 * np.abs(mesh.kappa)
    a_long_arr = np.zeros(N)
    for i in range(N - 1):
        a_long_arr[i] = (v_arr[i + 1] ** 2 - v_arr[i] ** 2) / (2.0 * ds[i])
    a_long_arr[-1] = a_long_arr[-2]
    # Sanitize derived arrays
    a_lat_arr = np.nan_to_num(a_lat_arr, nan=0.0, posinf=0.0, neginf=0.0)
    a_long_arr = np.nan_to_num(a_long_arr, nan=0.0, posinf=0.0, neginf=0.0)

    # Lap time
    lap_time = 0.0
    for i in range(N - 1):
        v_avg = (v_arr[i] + v_arr[i + 1]) / 2.0
        lap_time += ds[i] / max(v_avg, _V_MIN)

    wall_time = time.monotonic() - t_start

    return TheoreticalResult(
        lap_time_s=float(lap_time),
        speed_profile=v_arr,
        distance_profile=mesh.s.copy(),
        a_long_profile=a_long_arr,
        a_lat_profile=a_lat_arr,
        corner_times=[],
        vehicle_params_used=params.to_dict(),
        calibration={},
        solver_meta={
            "nodes": N,
            "iterations": iterations,
            "converged": converged,
            "wall_time_s": round(wall_time, 2),
        },
        tier=1,
        converged=converged,
    )
