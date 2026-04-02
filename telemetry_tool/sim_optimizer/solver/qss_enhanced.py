"""Enhanced QSS forward/backward lap-time solver using VehicleModel.

Mirrors the kart_envelope ``_compute_theoretical_lap_qss()`` algorithm
but delegates all grip/power queries to the sim-optimizer VehicleModel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kart_envelope.track.geometry import TrackGeometry
from telemetry_tool.sim_optimizer.config import SimOptimizerConfig, default_config
from telemetry_tool.sim_optimizer.param_id.vehicle_model import VehicleModel

_G = 9.80665


class SimSolverError(ValueError):
    """Raised when the QSS solver cannot produce a valid result."""


@dataclass
class SimTheoreticalResult:
    """Output of the enhanced QSS solver."""

    speed_profile_mps: np.ndarray
    distance_m: np.ndarray
    accel_profile_mps2: np.ndarray
    lap_time_s: float
    cornering_limited: np.ndarray
    accel_limited: np.ndarray
    braking_limited: np.ndarray
    gear_profile: np.ndarray
    method: str = "sim_qss"

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed_profile_mps": self.speed_profile_mps.tolist(),
            "distance_m": self.distance_m.tolist(),
            "accel_profile_mps2": self.accel_profile_mps2.tolist(),
            "lap_time_s": self.lap_time_s,
            "cornering_limited": self.cornering_limited.tolist(),
            "accel_limited": self.accel_limited.tolist(),
            "braking_limited": self.braking_limited.tolist(),
            "gear_profile": self.gear_profile.tolist(),
            "method": self.method,
        }


# ------------------------------------------------------------------
# Core solver
# ------------------------------------------------------------------


def compute_sim_theoretical_lap(
    geometry: TrackGeometry,
    vehicle: VehicleModel,
    *,
    fuel_level_l: float = 30.0,
    config: SimOptimizerConfig | None = None,
) -> SimTheoreticalResult:
    """Compute a minimum-time speed profile over *geometry* using *vehicle*.

    Algorithm
    ---------
    1. Corner-speed ceiling from curvature + grip.
    2. Apex detection (local minima of corner speed).
    3. Forward integration (traction-limited) from each apex.
    4. Backward integration (braking-limited) from each apex.
    5. Merge: v = min(v_corner, v_fwd, v_bwd).
    6. Wrap iterations for lap closure.
    7. Compute lap time, classify limits, assign gears.

    Raises
    ------
    SimSolverError
        If geometry has fewer than 3 points or produces invalid results.
    """
    if config is None:
        config = default_config()

    dist = geometry.distance_m
    kappa = geometry.curvature_1pm
    n = len(dist)

    if n < 3:
        raise SimSolverError(f"Track geometry too short: {n} points (need >= 3).")

    v_min = config.solver_min_speed_mps
    v_max = config.solver_max_speed_mps
    kappa_thresh = config.solver_apex_curvature_threshold
    wrap_iters = config.solver_wrap_iterations

    # Step sizes between consecutive points
    ds = np.diff(dist)
    ds = np.append(ds, ds[-1])  # pad last element

    # ------------------------------------------------------------------
    # 1. Corner-speed ceiling
    # ------------------------------------------------------------------
    v_corner = np.empty(n)
    for i in range(n):
        if kappa[i] > 1e-9:
            v_corner[i] = vehicle.max_cornering_speed(kappa[i])
        else:
            v_corner[i] = v_max
    v_corner = np.clip(v_corner, v_min, v_max)

    # ------------------------------------------------------------------
    # 2. Find apices (local minima of v_corner where kappa > threshold)
    # ------------------------------------------------------------------
    apices = _find_apices(v_corner, kappa, kappa_thresh, n)
    if len(apices) == 0:
        # No corners: treat start as only apex
        apices = [0]

    # ------------------------------------------------------------------
    # 3-6. Forward/backward passes with wrap iterations
    # ------------------------------------------------------------------
    v_fwd = np.full(n, v_max)
    v_bwd = np.full(n, v_max)

    mass = vehicle.total_mass_kg(fuel_level_l)

    for _wrap in range(wrap_iters):
        # Forward pass from each apex
        v_fwd[:] = v_max
        for apex in apices:
            v = min(v_corner[apex], v_fwd[apex])
            v_fwd[apex] = min(v_fwd[apex], v)
            for i in range(apex + 1, n + apex):
                idx = i % n
                prev_idx = (i - 1) % n
                v_prev = v_fwd[prev_idx]
                a_lat = _lateral_accel(v_prev, kappa[prev_idx])
                a_max = vehicle.max_longitudinal_accel(v_prev, a_lat, braking=False)
                step = ds[prev_idx]
                if a_max <= 0 or step <= 0:
                    v_next = v_prev
                else:
                    v_sq = v_prev * v_prev + 2.0 * a_max * step
                    v_next = math.sqrt(max(v_sq, v_min * v_min))
                v_next = min(v_next, v_corner[idx], v_max)
                v_next = max(v_next, v_min)
                if v_next < v_fwd[idx]:
                    v_fwd[idx] = v_next
                else:
                    break  # this apex's influence is exhausted

        # Backward pass from each apex
        v_bwd[:] = v_max
        for apex in apices:
            v = min(v_corner[apex], v_bwd[apex])
            v_bwd[apex] = min(v_bwd[apex], v)
            for i in range(apex - 1, apex - n, -1):
                idx = i % n
                next_idx = (i + 1) % n
                v_next = v_bwd[next_idx]
                a_lat = _lateral_accel(v_next, kappa[next_idx])
                a_max = vehicle.max_longitudinal_accel(v_next, a_lat, braking=True)
                step = ds[idx]
                if a_max <= 0 or step <= 0:
                    v_prev = v_next
                else:
                    v_sq = v_next * v_next + 2.0 * a_max * step
                    v_prev = math.sqrt(max(v_sq, v_min * v_min))
                v_prev = min(v_prev, v_corner[idx], v_max)
                v_prev = max(v_prev, v_min)
                if v_prev < v_bwd[idx]:
                    v_bwd[idx] = v_prev
                else:
                    break

        # Update v_corner with merged result for next wrap iteration
        v_merged = np.minimum(v_corner, np.minimum(v_fwd, v_bwd))
        v_corner_for_wrap = np.clip(v_merged, v_min, v_max)
        # Feed merged into next wrap's corner ceiling
        v_corner = np.maximum(v_corner, v_min)  # keep original ceiling

    # ------------------------------------------------------------------
    # 5. Final merge
    # ------------------------------------------------------------------
    v_final = np.minimum(v_corner, np.minimum(v_fwd, v_bwd))
    v_final = np.clip(v_final, v_min, v_max)

    # ------------------------------------------------------------------
    # 7. Lap time
    # ------------------------------------------------------------------
    lap_time = float(np.sum(ds / v_final))

    # ------------------------------------------------------------------
    # 8. Acceleration profile
    # ------------------------------------------------------------------
    accel = np.zeros(n)
    for i in range(n - 1):
        if ds[i] > 0:
            accel[i] = (v_final[i + 1] ** 2 - v_final[i] ** 2) / (2.0 * ds[i])
    accel[-1] = accel[-2] if n > 1 else 0.0

    # ------------------------------------------------------------------
    # 9. Classification
    # ------------------------------------------------------------------
    tol = 0.5  # m/s tolerance for classification
    cornering_lim = np.abs(v_final - np.clip(v_corner, v_min, v_max)) < tol
    accel_lim = np.abs(v_final - v_fwd) < tol
    braking_lim = np.abs(v_final - v_bwd) < tol

    # ------------------------------------------------------------------
    # 10. Gear profile
    # ------------------------------------------------------------------
    gear_profile = np.ones(n, dtype=int)
    for i in range(n):
        gear_profile[i] = vehicle.powertrain.optimal_gear(v_final[i], mass)

    return SimTheoreticalResult(
        speed_profile_mps=v_final,
        distance_m=dist.copy(),
        accel_profile_mps2=accel,
        lap_time_s=lap_time,
        cornering_limited=cornering_lim,
        accel_limited=accel_lim,
        braking_limited=braking_lim,
        gear_profile=gear_profile,
        method="sim_qss",
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _lateral_accel(speed: float, curvature: float) -> float:
    """Return centripetal acceleration v^2 * kappa."""
    return speed * speed * curvature


def _find_apices(
    v_corner: np.ndarray,
    kappa: np.ndarray,
    kappa_thresh: float,
    n: int,
) -> list[int]:
    """Find apex indices: local minima of v_corner where kappa > threshold."""
    apices: list[int] = []
    for i in range(n):
        if kappa[i] < kappa_thresh:
            continue
        prev_v = v_corner[(i - 1) % n]
        next_v = v_corner[(i + 1) % n]
        if v_corner[i] <= prev_v and v_corner[i] <= next_v:
            apices.append(i)
    return apices
