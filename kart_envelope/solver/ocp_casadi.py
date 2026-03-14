"""
ocp_casadi.py
-------------
CasADi-based minimum-time OCP backend.

This backend is optional. If CasADi is not installed, callers should catch
the raised error and use a fallback backend.
"""
from __future__ import annotations

import logging
import math

import numpy as np

from kart_envelope.config import KartEnvelopeConfig, default_config
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.solver.aero import AeroRuntime
from kart_envelope.solver.min_time import SolverError, TheoreticalResult
from kart_envelope.solver.powertrain import PowertrainRuntime
from kart_envelope.track.geometry import TrackGeometry

logger = logging.getLogger(__name__)

try:
    import casadi as ca  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    ca = None  # type: ignore[assignment]


def compute_theoretical_lap_casadi(
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars | None = None,
    config: KartEnvelopeConfig | None = None,
    *,
    warm_start_mps: np.ndarray | None = None,
    mesh_mode: str = "standard",
    solver_tol: float | None = None,
    solver_max_iter: int | None = None,
    powertrain: PowertrainRuntime | None = None,
    aero_runtime: AeroRuntime | None = None,
    condition_label: str = "",
    lateral_scale_profile: np.ndarray | None = None,
    drive_scale_profile: np.ndarray | None = None,
    brake_scale_profile: np.ndarray | None = None,
) -> TheoreticalResult:
    """Compute minimum-time lap using a direct OCP solved by IPOPT."""
    if ca is None:
        raise RuntimeError("casadi is not installed")

    cfg = config or default_config()
    pw = powertrain or PowertrainRuntime()
    aero = aero_runtime or AeroRuntime()
    env = envelope
    if scalars is not None:
        env = envelope.scaled(
            mu=scalars.mu_session,
            p_drive=scalars.p_session,
            b_brake=scalars.b_session,
        )

    dist_full = np.asarray(geometry.distance_m, dtype=float)
    kappa_full = np.asarray(geometry.curvature_1pm, dtype=float)
    dist, kappa, warm = _build_mesh_view(
        dist_full=dist_full,
        kappa_full=kappa_full,
        mesh_mode=mesh_mode,
        warm_start_mps=warm_start_mps,
    )
    lat_prof = _mesh_profile(
        values=lateral_scale_profile,
        dist_full=dist_full,
        dist_mesh=dist,
        default=1.0,
        lo=0.70,
        hi=1.20,
    )
    drv_prof = _mesh_profile(
        values=drive_scale_profile,
        dist_full=dist_full,
        dist_mesh=dist,
        default=1.0,
        lo=0.70,
        hi=1.20,
    )
    brk_prof = _mesh_profile(
        values=brake_scale_profile,
        dist_full=dist_full,
        dist_mesh=dist,
        default=1.0,
        lo=0.70,
        hi=1.25,
    )
    if len(dist) < 3:
        raise SolverError(f"Track has only {len(dist)} points; need >= 3.")
    ds = np.diff(dist)
    if np.any(ds <= 0):
        raise SolverError("Distance grid is not strictly increasing.")

    n = len(dist)
    v_grid = np.asarray(env.v_grid, dtype=float)
    ay_grid = np.asarray(env.ay_max, dtype=float)
    axd_grid = np.asarray(env.ax_drive_max, dtype=float)
    axb_grid = np.asarray(env.ax_brake_max, dtype=float)
    if len(v_grid) < 2:
        raise SolverError("Envelope v_grid has insufficient points.")

    v_min_cfg = float(cfg.solver_min_speed_mps)
    v_max_cfg = float(cfg.solver_max_speed_mps)
    v_min = max(v_min_cfg, float(np.nanmin(v_grid)))
    v_max = min(v_max_cfg, float(np.nanmax(v_grid)))
    if v_max <= v_min:
        raise SolverError("Invalid speed bounds for CasADi backend.")

    p = float(max(env.p_combined, 1.05))
    p_trac = float(max(env._effective_p(braking=False), 1.05))
    p_brake = float(max(env._effective_p(braking=True), 1.05))
    asymmetric = abs(p_trac - p_brake) >= 0.01
    p_trac_ca = ca.DM(p_trac)
    p_brake_ca = ca.DM(p_brake)
    p_ca = ca.DM(p)

    ay_fun = ca.interpolant("ay_lim", "linear", [v_grid], ay_grid)
    axd_fun = ca.interpolant("axd_lim", "linear", [v_grid], axd_grid)
    axb_fun = ca.interpolant("axb_lim", "linear", [v_grid], axb_grid)

    v = ca.MX.sym("v", n)
    a = ca.MX.sym("a", n - 1)
    x = ca.vertcat(v, a)

    g_terms: list[ca.MX] = []
    lbg: list[float] = []
    ubg: list[float] = []

    # Minimize integrated lap time + small regularization on jerk and speed ripple.
    obj = 0.0
    for i in range(n - 1):
        v_avg = 0.5 * (v[i] + v[i + 1])
        obj += ds[i] / ca.fmax(v_avg, v_min)
    if n > 2:
        dv = v[1:] - v[:-1]
        obj += float(cfg.solver_casadi_speed_smooth_weight) * ca.sumsqr(dv)
    if n > 3:
        da = a[1:] - a[:-1]
        obj += float(cfg.solver_casadi_accel_smooth_weight) * ca.sumsqr(da)

    # Dynamics, tire constraints, and drivetrain resistance constraints.
    kappa_abs = np.abs(kappa)
    rr_cond = _condition_rr_factor(condition_label)
    rr_c0 = float(pw.rr_c0) * 9.80665 * rr_cond if pw.enabled_rolling_resistance else 0.0
    rr_c1 = float(pw.rr_c1) * 9.80665 * rr_cond if pw.enabled_rolling_resistance else 0.0
    mass_kg = float(max(getattr(pw, "mass_kg", 180.0), 60.0))
    rho = float(getattr(aero, "air_density_kg_m3", 1.2))
    cda = float(getattr(aero, "cda", 0.0)) if getattr(aero, "enabled_drag", False) else 0.0
    cl = float(max(getattr(aero, "cl", 0.0), 0.0)) if getattr(aero, "enabled_downforce", False) else 0.0
    for i in range(n - 1):
        vi = v[i]
        vi1 = v[i + 1]
        ai = a[i]
        ds_i = float(ds[i])

        # v^2 integration dynamics.
        g_terms.append(vi1 * vi1 - vi * vi - 2.0 * ai * ds_i)
        lbg.append(0.0)
        ubg.append(0.0)

        v_clip = ca.fmin(ca.fmax(vi, v_grid[0]), v_grid[-1])
        lf = 1.0 + (0.5 * rho * cl * vi * vi) / max(mass_kg * 9.80665, 1e-6)
        lf = ca.fmin(ca.fmax(lf, 1.0), 1.2)
        ay_lim = ca.fmax(ay_fun(v_clip), 0.1) * float(lat_prof[i]) * lf
        axd_lim = ca.fmax(axd_fun(v_clip), 0.1) * float(drv_prof[i]) * lf
        axb_lim = ca.fmax(axb_fun(v_clip), 0.1) * float(brk_prof[i]) * (0.60 + 0.40 * lf)
        a_res = rr_c0 + rr_c1 * vi + (0.5 * rho * cda * vi * vi) / max(mass_kg, 1e-6)
        # Net drive capability after resistive loads.
        if pw.enabled_map and pw.peak_power_w_per_kg is not None:
            a_power = float(np.clip(pw.peak_power_w_per_kg * pw.transmission_efficiency, 1.0, 1e5)) / ca.fmax(vi, 1.0)
            axd_eff = ca.fmax(ca.fmin(axd_lim, a_power) - a_res, 0.1)
        else:
            axd_eff = ca.fmax(axd_lim - a_res, 0.1)
        axb_eff = ca.fmax(axb_lim + 0.25 * a_res, 0.1)
        ax_lim = ca.if_else(ai >= 0, axd_eff, axb_eff)

        lat_req = vi * vi * float(kappa_abs[i])
        lat_ratio = lat_req / ay_lim
        long_ratio = ca.fabs(ai) / ax_lim

        # Combined-slip ellipse/p-norm (asymmetric when braking vs traction).
        if asymmetric:
            p_eff = ca.if_else(ai >= 0, p_trac_ca, p_brake_ca)
            g_terms.append(ca.power(long_ratio, p_eff) + ca.power(lat_ratio, p_eff))
        else:
            g_terms.append(ca.power(long_ratio, p_ca) + ca.power(lat_ratio, p_ca))
        lbg.append(-ca.inf)
        ubg.append(1.0)

        # Separate lateral cap for numerical stability.
        g_terms.append(lat_req - ay_lim)
        lbg.append(-ca.inf)
        ubg.append(0.0)

    if bool(cfg.solver_casadi_closed_loop):
        g_terms.append(v[0] - v[-1])
        lbg.append(0.0)
        ubg.append(0.0)

    nlp = {"x": x, "f": obj, "g": ca.vertcat(*g_terms)}
    opts = {
        "ipopt.print_level": int(cfg.solver_casadi_print_level),
        "print_time": False,
        "ipopt.max_iter": int(max(solver_max_iter or cfg.solver_casadi_max_iter, 50)),
        "ipopt.tol": float(max(solver_tol or cfg.solver_casadi_tol, 1e-10)),
        "ipopt.linear_solver": "mumps",
    }
    solver = ca.nlpsol("lap_ocp", "ipopt", nlp, opts)

    lbx = np.concatenate(
        [
            np.full(n, v_min, dtype=float),
            -np.full(n - 1, float(np.nanmax(axb_grid)), dtype=float),
        ]
    )
    ubx = np.concatenate(
        [
            np.full(n, v_max, dtype=float),
            np.full(n - 1, float(np.nanmax(axd_grid)), dtype=float),
        ]
    )

    x0 = _build_initial_guess(
        dist=dist,
        ds=ds,
        kappa=kappa_abs,
        env=env,
        v_min=v_min,
        v_max=v_max,
        warm_start_mps=warm,
    )

    try:
        sol = solver(
            x0=x0,
            lbx=lbx,
            ubx=ubx,
            lbg=np.asarray(lbg, dtype=float),
            ubg=np.asarray(ubg, dtype=float),
        )
    except Exception as exc:
        raise SolverError(f"CasADi NLP solve failed: {exc}") from exc

    x_opt = np.asarray(sol["x"]).reshape(-1)
    if len(x_opt) != n + (n - 1):
        raise SolverError("Unexpected CasADi solution vector size.")

    v_opt_mesh = np.clip(x_opt[:n], v_min_cfg, v_max_cfg)
    a_opt = x_opt[n:]
    v_opt = np.interp(dist_full, dist, v_opt_mesh, left=float(v_opt_mesh[0]), right=float(v_opt_mesh[-1]))
    lap_time = _integrate_lap_time(dist_full, v_opt, v_min_cfg)
    if not math.isfinite(lap_time) or lap_time <= 0:
        raise SolverError(f"Invalid CasADi lap time: {lap_time}")

    accel = np.zeros(len(dist_full), dtype=float)
    accel[:-1] = np.diff(v_opt * v_opt) / (2.0 * np.maximum(np.diff(dist_full), 1e-6))
    accel[-1] = accel[-2] if len(accel) > 1 else 0.0
    ay_lim_np = np.asarray(env.lateral_max(v_opt), dtype=float)
    axd_lim_np = np.asarray(env.traction_max(v_opt), dtype=float)
    axb_lim_np = np.asarray(env.braking_max(v_opt), dtype=float)
    lf_np = 1.0 + (0.5 * rho * cl * np.square(v_opt)) / max(mass_kg * 9.80665, 1e-6)
    lf_np = np.clip(lf_np, 1.0, 1.2)
    lat_prof_full = _profile_full(lat_prof, dist, dist_full)
    drv_prof_full = _profile_full(drv_prof, dist, dist_full)
    brk_prof_full = _profile_full(brk_prof, dist, dist_full)
    axd_lim_np = axd_lim_np * drv_prof_full * lf_np
    axb_lim_np = axb_lim_np * brk_prof_full * (0.60 + 0.40 * lf_np)
    ay_lim_np = ay_lim_np * lat_prof_full * lf_np
    a_rr_np = np.asarray(
        [pw.resistance_accel(float(vv), condition_label=condition_label) for vv in v_opt],
        dtype=float,
    )
    a_drag_np = (0.5 * rho * cda * np.square(v_opt)) / max(mass_kg, 1e-6)
    a_res_np = a_rr_np + a_drag_np
    if pw.enabled_map and pw.peak_power_w_per_kg is not None:
        a_pow_np = (float(pw.peak_power_w_per_kg) * float(np.clip(pw.transmission_efficiency, 0.6, 1.0))) / np.maximum(v_opt, 1.0)
        axd_lim_np = np.minimum(axd_lim_np, a_pow_np)
    axd_lim_np = np.maximum(axd_lim_np - a_res_np, 0.1)
    axb_lim_np = np.maximum(axb_lim_np + 0.25 * a_res_np, 0.1)
    lat_req_np = (v_opt * v_opt) * np.abs(kappa_full)

    cornering_limited = lat_req_np >= (0.985 * np.maximum(ay_lim_np, 1e-3))
    accel_limited = np.zeros(len(dist_full), dtype=bool)
    braking_limited = np.zeros(len(dist_full), dtype=bool)
    accel_limited[:-1] = accel[:-1] >= 0.97 * np.maximum(axd_lim_np[:-1], 1e-3)
    braking_limited[:-1] = -accel[:-1] >= 0.97 * np.maximum(axb_lim_np[:-1], 1e-3)

    stats = {}
    try:
        raw_stats = solver.stats()
        if isinstance(raw_stats, dict):
            stats = {
                "return_status": str(raw_stats.get("return_status", "")),
                "iter_count": int(raw_stats.get("iter_count", 0) or 0),
                "success": bool(raw_stats.get("success", False)),
                "t_wall_total_s": float(raw_stats.get("t_wall_total", 0.0) or 0.0),
            }
    except Exception:
        stats = {}

    result = TheoreticalResult(
        speed_profile_mps=v_opt,
        distance_m=dist_full,
        accel_profile_mps2=accel,
        lap_time_s=float(lap_time),
        cornering_limited=cornering_limited,
        accel_limited=accel_limited,
        braking_limited=braking_limited,
        method="envelope_casadi_ocp",
        solver_backend="casadi_ocp",
        solver_diagnostics={
            "backend": "casadi_ocp",
            "status": "ok",
            "mesh_mode": str(mesh_mode),
            "mesh_points": int(len(dist)),
            "full_points": int(len(dist_full)),
            "solver_tol": float(solver_tol or cfg.solver_casadi_tol),
            "solver_max_iter": int(solver_max_iter or cfg.solver_casadi_max_iter),
            "powertrain": pw.to_dict(),
            "aero": aero.to_dict(),
            "profiles": {
                "lateral_scale_min": float(np.nanmin(lat_prof)),
                "lateral_scale_max": float(np.nanmax(lat_prof)),
                "drive_scale_min": float(np.nanmin(drv_prof)),
                "drive_scale_max": float(np.nanmax(drv_prof)),
                "brake_scale_min": float(np.nanmin(brk_prof)),
                "brake_scale_max": float(np.nanmax(brk_prof)),
            },
            "ipopt": stats,
            "p_combined": round(p, 3),
            "p_traction": round(p_trac, 3),
            "p_braking": round(p_brake, 3),
            "asymmetric_ellipse": asymmetric,
        },
    )
    logger.info(
        "Theoretical lap (envelope_casadi_ocp): %.3f s (v_max=%.1f, v_min=%.1f m/s, "
        "mesh=%s, p_trac=%.2f, p_brake=%.2f).",
        result.lap_time_s,
        float(np.max(v_opt)),
        float(np.min(v_opt)),
        str(mesh_mode),
        p_trac,
        p_brake,
    )
    return result


def _build_initial_guess(
    dist: np.ndarray,
    ds: np.ndarray,
    kappa: np.ndarray,
    env: CapabilityEnvelope,
    v_min: float,
    v_max: float,
    warm_start_mps: np.ndarray | None,
) -> np.ndarray:
    n = len(dist)
    if warm_start_mps is not None and len(warm_start_mps) == n:
        v0 = np.asarray(warm_start_mps, dtype=float)
    else:
        ay = np.asarray(env.ay_max, dtype=float)
        ay_ref = float(np.nanmedian(ay)) if len(ay) else 8.0
        v0 = np.sqrt(np.maximum(ay_ref / np.maximum(kappa, 1e-6), v_min * v_min))
        v0 = np.clip(v0, v_min, v_max)

    a0 = np.diff(v0 * v0) / (2.0 * np.maximum(ds, 1e-6))
    return np.concatenate([v0, a0], dtype=float)


def _integrate_lap_time(dist: np.ndarray, speed: np.ndarray, v_floor: float) -> float:
    ds = np.diff(dist)
    v_avg = 0.5 * (speed[:-1] + speed[1:])
    v_avg = np.maximum(v_avg, max(v_floor, 1e-6))
    return float(np.sum(ds / v_avg))


def _build_mesh_view(
    *,
    dist_full: np.ndarray,
    kappa_full: np.ndarray,
    mesh_mode: str,
    warm_start_mps: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    stride = _mesh_stride(mesh_mode, len(dist_full))
    if stride <= 1:
        return dist_full, kappa_full, warm_start_mps

    idx = np.arange(0, len(dist_full), stride, dtype=int)
    if idx[-1] != len(dist_full) - 1:
        idx = np.append(idx, len(dist_full) - 1)
    dist = dist_full[idx]
    kappa = kappa_full[idx]
    warm = None
    if warm_start_mps is not None and len(warm_start_mps) == len(dist_full):
        warm = np.asarray(warm_start_mps, dtype=float)[idx]
    return dist, kappa, warm


def _mesh_stride(mesh_mode: str, n: int) -> int:
    mode = str(mesh_mode or "standard").strip().lower()
    if mode == "fine":
        return 1
    if mode == "coarse":
        return 4 if n >= 240 else 2
    # standard
    return 2 if n >= 120 else 1


def _condition_rr_factor(condition_label: str) -> float:
    cond = str(condition_label or "").strip().lower()
    if "wet" in cond:
        return 1.18
    if "damp" in cond:
        return 1.10
    if "greasy" in cond:
        return 1.12
    if "green" in cond:
        return 1.05
    return 1.0


def _mesh_profile(
    *,
    values: np.ndarray | None,
    dist_full: np.ndarray,
    dist_mesh: np.ndarray,
    default: float,
    lo: float,
    hi: float,
) -> np.ndarray:
    if values is None:
        return np.full(len(dist_mesh), float(default), dtype=float)
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        return np.full(len(dist_mesh), float(default), dtype=float)
    if arr.size != len(dist_full):
        x_old = np.linspace(0.0, 1.0, arr.size)
        x_new = np.linspace(0.0, 1.0, len(dist_full))
        arr = np.interp(x_new, x_old, arr)
    arr = np.nan_to_num(arr, nan=float(default), posinf=float(hi), neginf=float(lo))
    mesh = np.interp(dist_mesh, dist_full, arr, left=float(arr[0]), right=float(arr[-1]))
    return np.clip(mesh, float(lo), float(hi))


def _profile_full(values_mesh: np.ndarray, dist_mesh: np.ndarray, dist_full: np.ndarray) -> np.ndarray:
    arr = np.asarray(values_mesh, dtype=float)
    if arr.size == 0:
        return np.ones(len(dist_full), dtype=float)
    return np.interp(dist_full, dist_mesh, arr, left=float(arr[0]), right=float(arr[-1]))
