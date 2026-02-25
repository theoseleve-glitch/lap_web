"""
min_time.py
-----------
Forward/backward quasi-steady-state (QSS) minimum-time solver.

Given a ``TrackGeometry`` (curvature profile) and a ``CapabilityEnvelope``
(optionally scaled by session scalars), computes the fastest possible
speed profile v*(s) and the corresponding theoretical lap time.

The algorithm is the industry-standard apex-seeded forward-backward
method used in OptimumLap, ChassisSim, and by F1 teams.
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
from kart_envelope.track.geometry import TrackGeometry

logger = logging.getLogger(__name__)


class SolverError(ValueError):
    """Raised when the solver produces an invalid result."""


@dataclass
class TheoreticalResult:
    """Output of the minimum-time solver."""

    speed_profile_mps: np.ndarray     # v*(s) [m/s]
    distance_m: np.ndarray            # s grid [m]
    accel_profile_mps2: np.ndarray    # a(s) [m/s²]
    lap_time_s: float
    cornering_limited: np.ndarray     # bool mask
    accel_limited: np.ndarray         # bool mask
    braking_limited: np.ndarray       # bool mask
    method: str = "envelope_qss"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_time_s": round(self.lap_time_s, 4),
            "method": self.method,
            "n_points": len(self.distance_m),
            "v_max_mps": round(float(np.max(self.speed_profile_mps)), 2),
            "v_min_mps": round(float(np.min(self.speed_profile_mps)), 2),
            "pct_cornering_limited": round(
                100 * float(np.mean(self.cornering_limited)), 1),
            "pct_accel_limited": round(
                100 * float(np.mean(self.accel_limited)), 1),
            "pct_braking_limited": round(
                100 * float(np.mean(self.braking_limited)), 1),
        }


def compute_theoretical_lap(
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars | None = None,
    config: KartEnvelopeConfig | None = None,
) -> TheoreticalResult:
    """Compute the minimum-time speed profile using QSS forward/backward.

    Parameters
    ----------
    geometry : TrackGeometry
        Track curvature profile κ(s).
    envelope : CapabilityEnvelope
        Performance limits (optionally pre-scaled).
    scalars : SessionScalars | None
        If provided, the envelope is scaled by (mu, p, b).
    config : KartEnvelopeConfig | None

    Returns
    -------
    TheoreticalResult

    Raises
    ------
    SolverError
        If the solver fails to produce a valid result.
    """
    if config is None:
        config = default_config()

    # Scale envelope by session scalars
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

    # --- Step 1: Cornering speed limit ---
    v_corner = np.empty(n)
    for i in range(n):
        v_corner[i] = min(env.max_cornering_speed(kappa[i]), v_max)
    v_corner = np.maximum(v_corner, v_min)

    # --- Step 2: Find apex points ---
    apices = _find_apices(v_corner, kappa, config.solver_apex_curvature_threshold)

    if not apices:
        # Fallback: use global minimum
        apices = [int(np.argmin(v_corner))]

    # --- Step 3: Apex-seeded forward/backward ---
    v_fwd = np.full(n, v_max)
    v_bwd = np.full(n, v_max)

    for apex in apices:
        # Forward from apex
        v_fwd[apex] = min(v_fwd[apex], v_corner[apex])
        for i in range(apex, n - 1):
            v_cur = min(v_fwd[i], v_corner[i])
            a_lat = v_cur ** 2 * kappa[i] if kappa[i] > 0 else 0.0
            a_drive = env.max_longitudinal_accel(v_cur, a_lat, braking=False)
            v_sq_next = v_cur ** 2 + 2.0 * a_drive * ds[i]
            v_next = math.sqrt(max(v_sq_next, 0.0))
            v_next = min(v_next, v_max, v_corner[i + 1])
            v_next = max(v_next, v_min)
            v_fwd[i + 1] = min(v_fwd[i + 1], v_next)

        # Backward into apex
        v_bwd[apex] = min(v_bwd[apex], v_corner[apex])
        for i in range(apex, 0, -1):
            v_cur = min(v_bwd[i], v_corner[i])
            a_lat = v_cur ** 2 * kappa[i] if kappa[i] > 0 else 0.0
            a_brake = env.max_longitudinal_accel(v_cur, a_lat, braking=True)
            # Going backward: the car was faster before, so we add braking capacity
            v_sq_prev = v_cur ** 2 + 2.0 * a_brake * ds[i - 1]
            v_prev = math.sqrt(max(v_sq_prev, 0.0))
            v_prev = min(v_prev, v_max, v_corner[i - 1])
            v_prev = max(v_prev, v_min)
            v_bwd[i - 1] = min(v_bwd[i - 1], v_prev)

    # --- Step 4: Combine ---
    v_final = np.minimum(np.minimum(v_corner, v_fwd), v_bwd)
    v_final = np.clip(v_final, v_min, v_max)

    # --- Step 5: Closed-loop convergence (wrap-around) ---
    for iteration in range(config.solver_wrap_iterations):
        v_start_old = v_final[0]

        # Global forward pass
        for i in range(n - 1):
            v_cur = v_final[i]
            a_lat = v_cur ** 2 * kappa[i] if kappa[i] > 0 else 0.0
            a_drive = env.max_longitudinal_accel(v_cur, a_lat, braking=False)
            v_sq_next = v_cur ** 2 + 2.0 * a_drive * ds[i]
            v_next = math.sqrt(max(v_sq_next, 0.0))
            v_final[i + 1] = min(v_final[i + 1], v_next, v_max)
            v_final[i + 1] = max(v_final[i + 1], v_min)

        # Global backward pass
        for i in range(n - 1, 0, -1):
            v_cur = v_final[i]
            a_lat = v_cur ** 2 * kappa[i] if kappa[i] > 0 else 0.0
            a_brake = env.max_longitudinal_accel(v_cur, a_lat, braking=True)
            v_sq_prev = v_cur ** 2 + 2.0 * a_brake * ds[i - 1]
            v_prev = math.sqrt(max(v_sq_prev, 0.0))
            v_final[i - 1] = min(v_final[i - 1], v_prev, v_max)
            v_final[i - 1] = max(v_final[i - 1], v_min)

        # Wrap: enforce last→first continuity
        v_wrap = min(v_final[0], v_final[-1])
        v_final[0] = 0.6 * v_wrap + 0.4 * v_final[0]
        v_final[-1] = 0.6 * v_wrap + 0.4 * v_final[-1]

        if abs(v_final[0] - v_start_old) < config.solver_wrap_tol_mps:
            logger.debug("Wrap converged at iteration %d.", iteration + 1)
            break

    # --- Step 6: Integrate time ---
    v_avg = 0.5 * (v_final[:-1] + v_final[1:])
    v_avg = np.maximum(v_avg, v_min)
    dt = ds / v_avg
    lap_time = float(np.sum(dt))

    if not math.isfinite(lap_time) or lap_time <= 0:
        raise SolverError(f"Invalid lap time: {lap_time:.3f} s")

    # --- Step 7: Acceleration profile ---
    accel = np.zeros(n)
    accel[:-1] = np.diff(v_final ** 2) / (2.0 * ds)

    # --- Step 8: Classify limiting factor ---
    # Tolerance for "close to limit"
    tol = 0.1  # m/s
    cornering_limited = (v_final <= v_corner + tol)
    accel_limited = np.zeros(n, dtype=bool)
    braking_limited = np.zeros(n, dtype=bool)
    accel_limited[:-1] = (v_final[1:] >= v_fwd[1:] - tol) & (accel[:-1] > 0.1)
    braking_limited[:-1] = (v_final[1:] >= v_bwd[1:] - tol) & (accel[:-1] < -0.1)

    result = TheoreticalResult(
        speed_profile_mps=v_final,
        distance_m=dist,
        accel_profile_mps2=accel,
        lap_time_s=lap_time,
        cornering_limited=cornering_limited,
        accel_limited=accel_limited,
        braking_limited=braking_limited,
    )

    logger.info(
        "Theoretical lap: %.3f s  (v_max=%.1f, v_min=%.1f m/s, "
        "corner=%.0f%%, accel=%.0f%%, brake=%.0f%%).",
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
