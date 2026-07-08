"""
min_time.py
-----------
Minimum-time lap solver backends.

Default backend:
- qss: apex-seeded forward/backward quasi-steady-state solver.

Optional backend:
- casadi_ocp: nonlinear OCP solver (falls back to qss when unavailable or failing,
  depending on config).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kart_envelope.config import KartEnvelopeConfig, default_config
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.solver.aero import AeroRuntime, build_aero_runtime
from kart_envelope.solver.powertrain import PowertrainRuntime, build_powertrain_runtime
from kart_envelope.track.geometry import TrackGeometry

logger = logging.getLogger(__name__)


class SolverError(ValueError):
    """Raised when the solver produces an invalid result."""


@dataclass
class TheoreticalResult:
    """Output of a minimum-time solver."""

    speed_profile_mps: np.ndarray  # v*(s) [m/s]
    distance_m: np.ndarray         # s grid [m]
    accel_profile_mps2: np.ndarray  # a(s) [m/s^2]
    lap_time_s: float
    cornering_limited: np.ndarray
    accel_limited: np.ndarray
    braking_limited: np.ndarray
    method: str = "envelope_qss"
    solver_backend: str = "qss"
    solver_diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_time_s": round(self.lap_time_s, 4),
            "method": self.method,
            "solver_backend": self.solver_backend,
            "n_points": len(self.distance_m),
            "v_max_mps": round(float(np.max(self.speed_profile_mps)), 2),
            "v_min_mps": round(float(np.min(self.speed_profile_mps)), 2),
            "pct_cornering_limited": round(
                100 * float(np.mean(self.cornering_limited)), 1
            ),
            "pct_accel_limited": round(
                100 * float(np.mean(self.accel_limited)), 1
            ),
            "pct_braking_limited": round(
                100 * float(np.mean(self.braking_limited)), 1
            ),
            "solver_diagnostics": self.solver_diagnostics,
        }


def compute_theoretical_lap(
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars | None = None,
    config: KartEnvelopeConfig | None = None,
    metadata: SessionMetadata | None = None,
    acd_engine: dict[str, Any] | None = None,
    *,
    powertrain_runtime: PowertrainRuntime | None = None,
    aero_runtime: AeroRuntime | None = None,
    lateral_scale_profile: np.ndarray | None = None,
    drive_scale_profile: np.ndarray | None = None,
    brake_scale_profile: np.ndarray | None = None,
) -> TheoreticalResult:
    """Compute minimum-time speed profile with backend + retry/fallback policy."""
    cfg = config or default_config()
    backend = _normalise_solver_backend(getattr(cfg, "solver_backend", "qss"))
    condition_label = str(getattr(scalars, "condition_label", "") or "")
    powertrain = powertrain_runtime or build_powertrain_runtime(metadata, cfg, acd_engine=acd_engine)
    aero = aero_runtime or build_aero_runtime(metadata, cfg, condition_label=condition_label)

    if backend == "qss":
        return _compute_theoretical_lap_qss(
            geometry=geometry,
            envelope=envelope,
            scalars=scalars,
            config=cfg,
            powertrain=powertrain,
            aero_runtime=aero,
            condition_label=condition_label,
            lateral_scale_profile=lateral_scale_profile,
            drive_scale_profile=drive_scale_profile,
            brake_scale_profile=brake_scale_profile,
            method_name="envelope_qss",
        )

    if backend == "casadi_ocp":
        qss_warm: TheoreticalResult | None = None
        if bool(getattr(cfg, "solver_casadi_warm_start", True)):
            qss_warm = _compute_theoretical_lap_qss(
                geometry=geometry,
                envelope=envelope,
                scalars=scalars,
                config=cfg,
                powertrain=powertrain,
                aero_runtime=aero,
                condition_label=condition_label,
                lateral_scale_profile=lateral_scale_profile,
                drive_scale_profile=drive_scale_profile,
                brake_scale_profile=brake_scale_profile,
                method_name="envelope_qss_warm_start",
            )
        attempts = _build_casadi_attempts(cfg)
        errors: list[str] = []
        for i, attempt in enumerate(attempts, start=1):
            try:
                from kart_envelope.solver.ocp_casadi import compute_theoretical_lap_casadi

                result = compute_theoretical_lap_casadi(
                    geometry=geometry,
                    envelope=envelope,
                    scalars=scalars,
                    config=cfg,
                    warm_start_mps=(
                        qss_warm.speed_profile_mps if qss_warm is not None else None
                    ),
                    mesh_mode=str(attempt["mesh_mode"]),
                    solver_tol=float(attempt["tol"]),
                    solver_max_iter=int(attempt["max_iter"]),
                    powertrain=powertrain,
                    aero_runtime=aero,
                    condition_label=condition_label,
                    lateral_scale_profile=lateral_scale_profile,
                    drive_scale_profile=drive_scale_profile,
                    brake_scale_profile=brake_scale_profile,
                )
                diag = dict(result.solver_diagnostics or {})
                diag.setdefault("attempt_index", i)
                diag.setdefault("attempt_total", len(attempts))
                diag["attempts"] = [{"index": j + 1, **a} for j, a in enumerate(attempts)]
                result.solver_diagnostics = diag
                result.solver_backend = "casadi_ocp"
                return result
            except Exception as exc:
                msg = f"attempt {i}/{len(attempts)} failed: {exc}"
                errors.append(msg)
                logger.warning("CASADI backend %s", msg)

        if bool(getattr(cfg, "solver_backend_fallback_to_qss", True)):
            if qss_warm is None:
                qss_warm = _compute_theoretical_lap_qss(
                    geometry=geometry,
                    envelope=envelope,
                    scalars=scalars,
                    config=cfg,
                    powertrain=powertrain,
                    aero_runtime=aero,
                    condition_label=condition_label,
                    lateral_scale_profile=lateral_scale_profile,
                    drive_scale_profile=drive_scale_profile,
                    brake_scale_profile=brake_scale_profile,
                    method_name="envelope_qss_fallback",
                )
            else:
                qss_warm.method = "envelope_qss_fallback"
                qss_warm.solver_backend = "qss"
            qdiag = dict(qss_warm.solver_diagnostics or {})
            qdiag["fallback_from"] = "casadi_ocp"
            qdiag["casadi_errors"] = errors
            qss_warm.solver_diagnostics = qdiag
            return qss_warm
        raise SolverError(
            f"Solver backend '{backend}' failed: {' | '.join(errors)}"
        )

    raise SolverError(
        f"Unsupported solver backend '{backend}'. Use 'qss' or 'casadi_ocp'."
    )


def _normalise_solver_backend(value: str) -> str:
    raw = str(value or "qss").strip().lower()
    if raw in {"qss", "envelope_qss"}:
        return "qss"
    if raw in {"casadi", "casadi_ocp", "ocp", "nlp"}:
        return "casadi_ocp"
    return raw


def _compute_theoretical_lap_qss(
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars | None,
    config: KartEnvelopeConfig,
    powertrain: PowertrainRuntime,
    aero_runtime: AeroRuntime,
    condition_label: str,
    lateral_scale_profile: np.ndarray | None,
    drive_scale_profile: np.ndarray | None,
    brake_scale_profile: np.ndarray | None,
    *,
    method_name: str,
) -> TheoreticalResult:
    """Compute the minimum-time speed profile using QSS forward/backward."""
    env = envelope
    if scalars is not None:
        env = envelope.scaled(
            mu=scalars.mu_session,
            p_drive=scalars.p_session,
            b_brake=scalars.b_session,
        )

    dist = geometry.distance_m
    kappa = geometry.curvature_1pm
    n = len(dist)
    if n < 3:
        raise SolverError(f"Track has only {n} points; need >= 3.")

    ds = np.diff(dist)
    if np.any(ds <= 0):
        raise SolverError("Distance grid is not strictly increasing.")

    v_max = config.solver_max_speed_mps
    v_min = config.solver_min_speed_mps
    lat_prof = _profile_or_default(lateral_scale_profile, n, default=1.0, lo=0.70, hi=1.20)
    drv_prof = _profile_or_default(drive_scale_profile, n, default=1.0, lo=0.70, hi=1.20)
    brk_prof = _profile_or_default(brake_scale_profile, n, default=1.0, lo=0.70, hi=1.25)

    v_corner = np.empty(n, dtype=float)
    for i in range(n):
        v_probe = min(max(v_min, env.max_cornering_speed(float(kappa[i]))), v_max)
        aero_lf = aero_runtime.downforce_load_factor(v_probe, powertrain.mass_kg)
        corner_scale = float(max(lat_prof[i], 0.05)) * float(aero_lf)
        v_corner[i] = min(v_probe * math.sqrt(max(corner_scale, 0.05)), v_max)
    v_corner = np.maximum(v_corner, v_min)

    apices = _find_apices(v_corner, kappa, config.solver_apex_curvature_threshold)
    if not apices:
        apices = [int(np.argmin(v_corner))]

    v_fwd = np.full(n, v_max, dtype=float)
    v_bwd = np.full(n, v_max, dtype=float)

    for apex in apices:
        v_fwd[apex] = min(v_fwd[apex], v_corner[apex])
        for i in range(apex, n - 1):
            v_cur = min(v_fwd[i], v_corner[i])
            a_lat = v_cur * v_cur * kappa[i] if kappa[i] > 0 else 0.0
            aero_lf = aero_runtime.downforce_load_factor(v_cur, powertrain.mass_kg)
            a_drive_env = env.max_longitudinal_accel(float(v_cur), float(a_lat), braking=False)
            a_drive_env *= float(drv_prof[i]) * float(aero_lf)
            a_rr = powertrain.resistance_accel(
                float(v_cur),
                condition_label=condition_label,
                load_factor=float(aero_lf) * (1.0 + 0.08 * min(abs(a_lat) / 9.80665, 2.0)),
            )
            a_drag = aero_runtime.drag_accel(float(v_cur), powertrain.mass_kg)
            a_res = a_rr + a_drag
            # The capability envelope is trained from NET accel (drag + rolling
            # resistance already removed); add resistance back so the power-map
            # cap compares gross-with-gross and resistance is subtracted exactly
            # once. See docs/theoretical-lap-grip-underestimation-diagnosis.md.
            a_drive = powertrain.max_drive_accel(float(v_cur), float(a_drive_env) + float(a_res))
            a_net = max(0.0, float(a_drive) - float(a_res))
            v_sq_next = v_cur * v_cur + 2.0 * a_net * ds[i]
            v_next = math.sqrt(max(v_sq_next, 0.0))
            v_next = min(v_next, v_max, v_corner[i + 1])
            v_next = max(v_next, v_min)
            v_fwd[i + 1] = min(v_fwd[i + 1], v_next)

        v_bwd[apex] = min(v_bwd[apex], v_corner[apex])
        for i in range(apex, 0, -1):
            v_cur = min(v_bwd[i], v_corner[i])
            a_lat = v_cur * v_cur * kappa[i] if kappa[i] > 0 else 0.0
            aero_lf = aero_runtime.downforce_load_factor(v_cur, powertrain.mass_kg)
            a_brake_env = env.max_longitudinal_accel(float(v_cur), float(a_lat), braking=True)
            a_brake_env *= float(brk_prof[i]) * (0.60 + 0.40 * float(aero_lf))
            a_rr = powertrain.resistance_accel(
                float(v_cur),
                condition_label=condition_label,
                load_factor=float(aero_lf) * (1.0 + 0.08 * min(abs(a_lat) / 9.80665, 2.0)),
            )
            a_drag = aero_runtime.drag_accel(float(v_cur), powertrain.mass_kg)
            a_res = a_rr + a_drag
            a_brake = max(0.0, float(a_brake_env) + 0.25 * float(a_res))
            v_sq_prev = v_cur * v_cur + 2.0 * a_brake * ds[i - 1]
            v_prev = math.sqrt(max(v_sq_prev, 0.0))
            v_prev = min(v_prev, v_max, v_corner[i - 1])
            v_prev = max(v_prev, v_min)
            v_bwd[i - 1] = min(v_bwd[i - 1], v_prev)

    v_final = np.minimum(np.minimum(v_corner, v_fwd), v_bwd)
    v_final = np.clip(v_final, v_min, v_max)

    for iteration in range(config.solver_wrap_iterations):
        v_start_old = v_final[0]

        for i in range(n - 1):
            v_cur = v_final[i]
            a_lat = v_cur * v_cur * kappa[i] if kappa[i] > 0 else 0.0
            aero_lf = aero_runtime.downforce_load_factor(v_cur, powertrain.mass_kg)
            a_drive_env = env.max_longitudinal_accel(float(v_cur), float(a_lat), braking=False)
            a_drive_env *= float(drv_prof[i]) * float(aero_lf)
            a_rr = powertrain.resistance_accel(
                float(v_cur),
                condition_label=condition_label,
                load_factor=float(aero_lf) * (1.0 + 0.08 * min(abs(a_lat) / 9.80665, 2.0)),
            )
            a_drag = aero_runtime.drag_accel(float(v_cur), powertrain.mass_kg)
            a_res = a_rr + a_drag
            # The capability envelope is trained from NET accel (drag + rolling
            # resistance already removed); add resistance back so the power-map
            # cap compares gross-with-gross and resistance is subtracted exactly
            # once. See docs/theoretical-lap-grip-underestimation-diagnosis.md.
            a_drive = powertrain.max_drive_accel(float(v_cur), float(a_drive_env) + float(a_res))
            a_net = max(0.0, float(a_drive) - float(a_res))
            v_sq_next = v_cur * v_cur + 2.0 * a_net * ds[i]
            v_next = math.sqrt(max(v_sq_next, 0.0))
            v_final[i + 1] = min(v_final[i + 1], v_next, v_max)
            v_final[i + 1] = max(v_final[i + 1], v_min)

        for i in range(n - 1, 0, -1):
            v_cur = v_final[i]
            a_lat = v_cur * v_cur * kappa[i] if kappa[i] > 0 else 0.0
            aero_lf = aero_runtime.downforce_load_factor(v_cur, powertrain.mass_kg)
            a_brake_env = env.max_longitudinal_accel(float(v_cur), float(a_lat), braking=True)
            a_brake_env *= float(brk_prof[i]) * (0.60 + 0.40 * float(aero_lf))
            a_rr = powertrain.resistance_accel(
                float(v_cur),
                condition_label=condition_label,
                load_factor=float(aero_lf) * (1.0 + 0.08 * min(abs(a_lat) / 9.80665, 2.0)),
            )
            a_drag = aero_runtime.drag_accel(float(v_cur), powertrain.mass_kg)
            a_res = a_rr + a_drag
            a_brake = max(0.0, float(a_brake_env) + 0.25 * float(a_res))
            v_sq_prev = v_cur * v_cur + 2.0 * a_brake * ds[i - 1]
            v_prev = math.sqrt(max(v_sq_prev, 0.0))
            v_final[i - 1] = min(v_final[i - 1], v_prev, v_max)
            v_final[i - 1] = max(v_final[i - 1], v_min)

        v_wrap = min(v_final[0], v_final[-1])
        v_final[0] = 0.6 * v_wrap + 0.4 * v_final[0]
        v_final[-1] = 0.6 * v_wrap + 0.4 * v_final[-1]

        if abs(v_final[0] - v_start_old) < config.solver_wrap_tol_mps:
            logger.debug("Wrap converged at iteration %d.", iteration + 1)
            break

    v_avg = 0.5 * (v_final[:-1] + v_final[1:])
    v_avg = np.maximum(v_avg, v_min)
    dt = ds / v_avg
    lap_time = float(np.sum(dt))
    if not math.isfinite(lap_time) or lap_time <= 0:
        raise SolverError(f"Invalid lap time: {lap_time:.3f} s")

    accel = np.zeros(n, dtype=float)
    accel[:-1] = np.diff(v_final * v_final) / (2.0 * ds)

    tol = 0.1
    cornering_limited = v_final <= v_corner + tol
    accel_limited = np.zeros(n, dtype=bool)
    braking_limited = np.zeros(n, dtype=bool)
    accel_limited[:-1] = (v_final[1:] >= v_fwd[1:] - tol) & (accel[:-1] > 0.1)
    braking_limited[:-1] = (v_final[1:] >= v_bwd[1:] - tol) & (accel[:-1] < -0.1)

    solver_diag = {
        "backend": "qss",
        "status": "ok",
        "wrap_iterations_configured": int(config.solver_wrap_iterations),
        "wrap_tol_mps": float(config.solver_wrap_tol_mps),
        "n_apices": int(len(apices)),
        "powertrain": powertrain.to_dict(),
        "aero": aero_runtime.to_dict(),
        "profiles": {
            "lateral_scale_min": float(np.nanmin(lat_prof)),
            "lateral_scale_max": float(np.nanmax(lat_prof)),
            "drive_scale_min": float(np.nanmin(drv_prof)),
            "drive_scale_max": float(np.nanmax(drv_prof)),
            "brake_scale_min": float(np.nanmin(brk_prof)),
            "brake_scale_max": float(np.nanmax(brk_prof)),
        },
    }

    result = TheoreticalResult(
        speed_profile_mps=v_final,
        distance_m=dist,
        accel_profile_mps2=accel,
        lap_time_s=lap_time,
        cornering_limited=cornering_limited,
        accel_limited=accel_limited,
        braking_limited=braking_limited,
        method=method_name,
        solver_backend="qss",
        solver_diagnostics=solver_diag,
    )
    logger.info(
        "Theoretical lap (%s): %.3f s (v_max=%.1f, v_min=%.1f m/s, corner=%.0f%%, accel=%.0f%%, brake=%.0f%%).",
        method_name,
        lap_time,
        float(np.max(v_final)),
        float(np.min(v_final)),
        100 * float(np.mean(cornering_limited)),
        100 * float(np.mean(accel_limited)),
        100 * float(np.mean(braking_limited)),
    )
    return result


def _find_apices(
    v_corner: np.ndarray,
    kappa: np.ndarray,
    curvature_threshold: float,
) -> list[int]:
    """Find local minima of v_corner where curvature is above threshold."""
    n = len(v_corner)
    apices: list[int] = []
    for i in range(1, n - 1):
        if kappa[i] < curvature_threshold:
            continue
        if v_corner[i] <= v_corner[i - 1] and v_corner[i] <= v_corner[i + 1]:
            apices.append(i)
    return apices


def _build_casadi_attempts(config: KartEnvelopeConfig) -> list[dict[str, Any]]:
    """
    Build ordered CasADi solve attempts:
    - attempt 1: configured mesh/tolerance/iterations
    - optional retries: relaxed tolerances and/or coarser mesh
    """
    base_mode = str(getattr(config, "solver_ocp_mesh_mode", "standard")).strip().lower()
    base_tol = float(max(getattr(config, "solver_casadi_tol", 1e-6), 1e-10))
    base_iter = int(max(getattr(config, "solver_casadi_max_iter", 600), 50))
    relax = bool(getattr(config, "solver_ocp_retry_relax", True))
    relax_factor = float(max(getattr(config, "solver_ocp_retry_relax_factor", 10.0), 1.0))
    max_attempts = int(max(getattr(config, "solver_ocp_retry_max_attempts", 2), 1))

    attempts: list[dict[str, Any]] = [{
        "mesh_mode": _normalise_mesh_mode(base_mode),
        "tol": base_tol,
        "max_iter": base_iter,
    }]
    if max_attempts <= 1:
        return attempts

    mesh_fallback = {
        "fine": "standard",
        "standard": "coarse",
        "coarse": "coarse",
    }
    last_mode = attempts[0]["mesh_mode"]
    last_tol = attempts[0]["tol"]
    last_iter = attempts[0]["max_iter"]
    for _ in range(1, max_attempts):
        next_mode = mesh_fallback.get(str(last_mode), "coarse")
        next_tol = last_tol * relax_factor if relax else last_tol
        next_iter = int(last_iter * (1.25 if relax else 1.0))
        attempts.append({
            "mesh_mode": next_mode,
            "tol": float(np.clip(next_tol, 1e-10, 1e-2)),
            "max_iter": int(max(next_iter, 50)),
        })
        last_mode = next_mode
        last_tol = next_tol
        last_iter = next_iter
    return attempts


def _normalise_mesh_mode(value: str) -> str:
    raw = str(value or "standard").strip().lower()
    if raw in {"coarse", "standard", "fine"}:
        return raw
    if raw in {"fast", "quick"}:
        return "coarse"
    if raw in {"accurate", "dense"}:
        return "fine"
    return "standard"


def _profile_or_default(
    values: np.ndarray | None,
    n: int,
    *,
    default: float,
    lo: float,
    hi: float,
) -> np.ndarray:
    if values is None:
        return np.full(n, float(default), dtype=float)
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        return np.full(n, float(default), dtype=float)
    if arr.size != n:
        x_old = np.linspace(0.0, 1.0, arr.size)
        x_new = np.linspace(0.0, 1.0, n)
        arr = np.interp(x_new, x_old, arr)
    arr = np.nan_to_num(arr, nan=float(default), posinf=float(hi), neginf=float(lo))
    return np.clip(arr, float(lo), float(hi))
