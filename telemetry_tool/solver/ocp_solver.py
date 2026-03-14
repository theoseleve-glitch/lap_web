# telemetry_tool/solver/ocp_solver.py
"""CasADi/IPOPT optimal control solver for minimum-time lap and corner segments.

Full-lap solver (solve_ocp):
  - Boundary: v[0] == v[N-1] (lap continuity)
  - Use case: best lap → optimal lap time

Corner segment solver (solve_ocp_segment):
  - Boundary: v[0] == v_entry, v[N-1] == v_exit (from actual data)
  - Use case: per-corner, per-lap optimal time

Common formulation (NLP):
  - Decision variables: speed v[i] at each collocation node
  - Objective: minimize sum(ds[i] / v[i])  (= total time)
  - Dynamics: v[i+1]^2 = v[i]^2 + 2 * a_net[i] * ds[i]
  - Grip constraint: **asymmetric** friction ellipse at each node
      - Braking:  (|ax|/a_max)^p_brake + (|ay|/a_max)^p_brake <= 1
      - Traction: (|ax|/a_max)^p_trac  + (|ay|/a_max)^p_trac  <= 1
    Real tires lose lateral grip faster under braking than traction;
    p_brake < p_trac models this asymmetry.
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
    p_traction: float = 2.0,
    p_braking: float = 2.0,
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
    p_traction : p-norm exponent for friction ellipse under traction.
        Default 2.0 (circle) for backward compatibility.
    p_braking : p-norm exponent for friction ellipse under braking.
        Typically lower than p_traction (tighter constraint: tires lose
        lateral grip faster under braking).

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

        # Tire contact patch longitudinal acceleration (drive/brake only).
        # Drag acts on the vehicle body, NOT through the tire contact patch,
        # so it must NOT appear in the friction ellipse.  Rolling resistance
        # is a tire-road interaction but is small and constant — excluded
        # from the ellipse for simplicity (standard in lap-time simulation).
        a_tire_long = a_drive - a_brake

        # Net longitudinal acceleration (includes all external forces)
        a_long = a_tire_long - a_drag - a_rolling

        # Dynamics: v[i+1]^2 = v[i]^2 + 2 * a_long * ds
        opti.subject_to(v[i + 1] ** 2 == v[i] ** 2 + 2 * a_long * ds[i])

        # Lateral acceleration from curvature
        a_lat = v[i] ** 2 * abs(kappa_i)

        # Load transfer (uses tire forces for longitudinal, not net)
        dFz_long = params.mass * ca.fabs(a_tire_long) * params.h_cg / params.wheelbase
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

        # Asymmetric friction ellipse: tire forces only (no drag).
        # Use p_traction when driving, p_braking when braking.
        # Smooth CasADi switch via if_else on the sign of a_tire_long.
        norm_long = ca.fabs(a_tire_long) / a_grip_max
        norm_lat = a_lat / a_grip_max
        if abs(p_traction - p_braking) < 0.01:
            # Symmetric case: single constraint (cheaper NLP)
            p_eff = p_traction
            opti.subject_to(norm_long ** p_eff + norm_lat ** p_eff <= 1.0)
        else:
            # Asymmetric: smooth switch based on net tire force direction.
            # When braking (a_tire_long < 0) → p_braking (tighter).
            # When driving (a_tire_long > 0) → p_traction (rounder).
            p_eff = ca.if_else(a_tire_long >= 0, p_traction, p_braking)
            opti.subject_to(norm_long ** p_eff + norm_lat ** p_eff <= 1.0)

        # Complementarity: no simultaneous throttle + brake
        opti.subject_to(u_thr[i] * u_brk[i] <= _EPSILON)

    # ── Boundary condition: lap continuity ──
    opti.subject_to(v[0] == v[N - 1])

    # ── Initial guess (downforce-aware) ──
    if warm_start is not None:
        opti.set_initial(v, warm_start)
    else:
        v_guess = _build_warm_start(mesh.kappa, N, params)
        opti.set_initial(v, v_guess)

    # Throttle/brake initial guess based on speed profile shape
    if warm_start is not None:
        _set_control_guess(opti, u_thr, u_brk, warm_start, mesh.ds)
    else:
        _set_control_guess(opti, u_thr, u_brk, v_guess, mesh.ds)

    # ── Solver options (tuned for faster convergence) ──
    opts = {
        "ipopt.max_iter": max_iter,
        "ipopt.tol": tol,
        "ipopt.acceptable_tol": 1e-3,
        "ipopt.acceptable_iter": 10,      # accept if in acceptable region for 10 iters
        "ipopt.acceptable_obj_change_tol": 1e-5,
        "ipopt.mu_strategy": "adaptive",
        "ipopt.mu_init": 0.1,             # higher initial barrier → faster start
        "ipopt.nlp_scaling_method": "gradient-based",
        "ipopt.print_level": 0,
        "ipopt.warm_start_init_point": "yes",
        "ipopt.warm_start_bound_push": 1e-6,
        "ipopt.warm_start_mult_bound_push": 1e-6,
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
            "p_traction": round(p_traction, 3),
            "p_braking": round(p_braking, 3),
            "asymmetric_ellipse": abs(p_traction - p_braking) >= 0.01,
        },
        tier=1,
        converged=converged,
    )


def solve_ocp_segment(
    mesh: TrackMesh,
    params: OCPVehicleParams,
    tire: LoadSensitiveTire,
    v_entry: float,
    v_exit: float,
    max_iter: int = 300,
    tol: float = 1e-4,
    p_traction: float = 2.0,
    p_braking: float = 2.0,
) -> TheoreticalResult:
    """Solve the minimum-time OCP for a track segment (corner).

    Unlike solve_ocp (full lap with v[0]==v[N-1]), this uses fixed boundary
    speeds from actual telemetry data:  v[0] == v_entry,  v[N-1] == v_exit.

    Parameters
    ----------
    mesh : Track mesh for the corner segment (s_start to s_end).
    params : Vehicle parameters.
    tire : Tire model.
    v_entry : Actual entry speed (m/s) at the segment start.
    v_exit : Actual exit speed (m/s) at the segment end.
    max_iter : IPOPT maximum iterations (lower than full-lap — segment is small).
    tol : IPOPT convergence tolerance.
    p_traction : p-norm exponent for friction ellipse under traction.
    p_braking : p-norm exponent for friction ellipse under braking.

    Returns
    -------
    TheoreticalResult with optimal speed profile through the corner.
    """
    t_start = time.monotonic()
    N = len(mesh.s)
    ds = mesh.ds

    v_entry = max(float(v_entry), _V_MIN)
    v_exit = max(float(v_exit), _V_MIN)

    opti = ca.Opti()
    v = opti.variable(N)
    u_thr = opti.variable(N)
    u_brk = opti.variable(N)

    opti.subject_to(v >= _V_MIN)
    opti.subject_to(opti.bounded(0, u_thr, 1))
    opti.subject_to(opti.bounded(0, u_brk, 1))

    # Objective: minimize segment time
    dt_sum = 0
    for i in range(N - 1):
        v_avg = (v[i] + v[i + 1]) / 2.0
        dt_sum += ds[i] / v_avg
    opti.minimize(dt_sum)

    # Dynamics + friction ellipse (identical to full-lap solver)
    Fz_static = params.Fz_static_per_axle
    for i in range(N - 1):
        kappa_i = float(mesh.kappa[i])
        a_drive = ca.fmin(
            u_thr[i] * params.P_max / (params.mass * v[i]),
            params.F_drive_max / params.mass,
        )
        a_brake = u_brk[i] * params.F_brake_max / params.mass
        a_drag = 0.5 * params.rho * params.Cd * params.A * v[i] ** 2 / params.mass
        a_rolling = params.Cr * _G
        F_downforce = 0.5 * params.rho * params.Cl * params.A * v[i] ** 2
        a_tire_long = a_drive - a_brake
        a_long = a_tire_long - a_drag - a_rolling
        opti.subject_to(v[i + 1] ** 2 == v[i] ** 2 + 2 * a_long * ds[i])
        a_lat = v[i] ** 2 * abs(kappa_i)
        dFz_long = params.mass * ca.fabs(a_tire_long) * params.h_cg / params.wheelbase
        dFz_lat = params.mass * a_lat * params.h_cg / params.track_width
        Fz_base = Fz_static + F_downforce / 2.0
        Fz_loaded = Fz_base + dFz_lat
        Fz_unloaded = ca.fmax(Fz_base - dFz_lat, 1.0)
        if abs(params.load_sensitivity) > 1e-6 and params.h_cg > 0:
            log_r_loaded = ca.log(ca.fmax(Fz_loaded, 1.0) / ca.fmax(Fz_static, 1.0))
            mu_loaded = params.mu_ref * ca.exp(params.load_sensitivity * log_r_loaded)
            log_r_unloaded = ca.log(ca.fmax(Fz_unloaded, 1.0) / ca.fmax(Fz_static, 1.0))
            mu_unloaded = params.mu_ref * ca.exp(params.load_sensitivity * log_r_unloaded)
            F_grip_total = mu_loaded * Fz_loaded + mu_unloaded * Fz_unloaded
            a_grip_max = F_grip_total / params.mass
        else:
            Fz_total = Fz_loaded + Fz_unloaded
            a_grip_max = params.mu_ref * Fz_total / params.mass
        # Asymmetric friction ellipse (same logic as solve_ocp)
        norm_long = ca.fabs(a_tire_long) / a_grip_max
        norm_lat = a_lat / a_grip_max
        if abs(p_traction - p_braking) < 0.01:
            p_eff = p_traction
            opti.subject_to(norm_long ** p_eff + norm_lat ** p_eff <= 1.0)
        else:
            p_eff = ca.if_else(a_tire_long >= 0, p_traction, p_braking)
            opti.subject_to(norm_long ** p_eff + norm_lat ** p_eff <= 1.0)

        opti.subject_to(u_thr[i] * u_brk[i] <= _EPSILON)

    # Boundary conditions: fixed entry/exit speeds from actual data
    opti.subject_to(v[0] == v_entry)
    opti.subject_to(v[N - 1] == v_exit)

    # Initial guess: linear interpolation capped by downforce-aware corner speed
    v_guess = np.linspace(v_entry, v_exit, N)
    for i in range(N):
        k = abs(float(mesh.kappa[i]))
        if k > 1e-4:
            v_corner = _corner_speed_with_downforce(k, params)
            v_guess[i] = min(v_guess[i], v_corner)
    v_guess = np.maximum(v_guess, _V_MIN)
    opti.set_initial(v, v_guess)
    _set_control_guess(opti, u_thr, u_brk, v_guess, mesh.ds)

    opts = {
        "ipopt.max_iter": max_iter,
        "ipopt.tol": tol,
        "ipopt.acceptable_tol": 1e-3,
        "ipopt.acceptable_iter": 10,
        "ipopt.acceptable_obj_change_tol": 1e-5,
        "ipopt.mu_strategy": "adaptive",
        "ipopt.mu_init": 0.1,
        "ipopt.nlp_scaling_method": "gradient-based",
        "ipopt.print_level": 0,
        "ipopt.warm_start_init_point": "yes",
        "ipopt.warm_start_bound_push": 1e-6,
        "ipopt.warm_start_mult_bound_push": 1e-6,
        "print_time": False,
    }
    opti.solver("ipopt", opts)

    converged = True
    iterations = 0
    try:
        sol = opti.solve()
        v_sol = sol.value(v)
        iterations = int(sol.stats()["iter_count"])
    except RuntimeError as e:
        logger.warning("Segment OCP failed to converge: %s -- using last iterate", e)
        converged = False
        v_sol = opti.debug.value(v)
        iterations = max_iter

    v_arr = np.array(v_sol).flatten()
    nan_mask = ~np.isfinite(v_arr)
    if nan_mask.any():
        v_arr[nan_mask] = _V_MIN
    v_arr = np.maximum(v_arr, _V_MIN)

    a_lat_arr = v_arr ** 2 * np.abs(mesh.kappa)
    a_long_arr = np.zeros(N)
    for i in range(N - 1):
        a_long_arr[i] = (v_arr[i + 1] ** 2 - v_arr[i] ** 2) / (2.0 * ds[i])
    a_long_arr[-1] = a_long_arr[-2] if N > 1 else 0.0
    a_lat_arr = np.nan_to_num(a_lat_arr, nan=0.0, posinf=0.0, neginf=0.0)
    a_long_arr = np.nan_to_num(a_long_arr, nan=0.0, posinf=0.0, neginf=0.0)

    segment_time = 0.0
    for i in range(N - 1):
        v_avg = (v_arr[i] + v_arr[i + 1]) / 2.0
        segment_time += ds[i] / max(v_avg, _V_MIN)

    wall_time = time.monotonic() - t_start

    return TheoreticalResult(
        lap_time_s=float(segment_time),
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
            "mode": "segment",
            "v_entry": round(v_entry, 3),
            "v_exit": round(v_exit, 3),
            "p_traction": round(p_traction, 3),
            "p_braking": round(p_braking, 3),
            "asymmetric_ellipse": abs(p_traction - p_braking) >= 0.01,
        },
        tier=1,
        converged=converged,
    )


# ── Warm-start helpers ──────────────────────────────────────────────────


def _corner_speed_with_downforce(kappa: float, params: OCPVehicleParams) -> float:
    """Estimate corner speed including aerodynamic downforce.

    Uses iterative solve: v = sqrt(a_lat_total / kappa) where
    a_lat_total = mu * g + mu * downforce(v) / mass.

    Without downforce: v = sqrt(mu*g / kappa).
    With downforce:    v is higher because Fz increases with v^2.
    """
    if kappa <= 0:
        return 100.0

    mu = params.mu_ref
    v = np.sqrt(mu * _G / kappa)

    if params.Cl <= 0.01:
        return float(min(v, 100.0))

    downforce_coeff = 0.5 * params.rho * params.Cl * params.A
    for _ in range(5):
        F_down = downforce_coeff * v * v
        Fz_total = params.mass * _G + F_down
        a_lat = mu * Fz_total / params.mass
        v_new = np.sqrt(a_lat / kappa)
        if abs(v_new - v) < 0.05:
            break
        v = v_new

    return float(min(v, 100.0))


def _build_warm_start(
    kappa: np.ndarray,
    N: int,
    params: OCPVehicleParams,
) -> np.ndarray:
    """Build a downforce-aware initial speed guess for the OCP solver."""
    drag_coeff = 0.5 * params.rho * params.Cd * params.A
    if drag_coeff > 1e-6:
        v_top = (params.P_max / drag_coeff) ** (1.0 / 3.0)
    else:
        v_top = 50.0
    v_straight = min(v_top, 100.0)

    v_guess = np.full(N, v_straight)
    for i in range(N):
        k = abs(float(kappa[i]))
        if k > 1e-4:
            v_corner = _corner_speed_with_downforce(k, params)
            v_guess[i] = min(v_guess[i], v_corner)

    return np.maximum(v_guess, _V_MIN)


def _set_control_guess(opti, u_thr, u_brk, v_guess: np.ndarray, ds: np.ndarray) -> None:
    """Set throttle/brake initial guesses based on speed profile slope."""
    N = len(v_guess)
    thr_guess = np.full(N, 0.3)
    brk_guess = np.full(N, 0.0)

    for i in range(N - 1):
        if ds[i] > 0:
            dv2 = v_guess[i + 1] ** 2 - v_guess[i] ** 2
            if dv2 > 0:
                thr_guess[i] = min(0.8, 0.3 + abs(dv2) / (2 * ds[i] * 20.0))
                brk_guess[i] = 0.0
            elif dv2 < 0:
                thr_guess[i] = 0.0
                brk_guess[i] = min(0.8, abs(dv2) / (2 * ds[i] * 20.0))
    thr_guess[-1] = thr_guess[-2] if N > 1 else 0.3
    brk_guess[-1] = brk_guess[-2] if N > 1 else 0.0

    opti.set_initial(u_thr, thr_guess)
    opti.set_initial(u_brk, brk_guess)
