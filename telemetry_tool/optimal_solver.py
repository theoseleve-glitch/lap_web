"""
optimal_solver.py
-----------------
Unified forward-backward feasibility solver for optimal lap speed.

Defines a canonical input contract (OptimalCaps) and output schema
(OptimalResult). All cap sources (percentile envelope, physics model,
kart_envelope adapter) produce OptimalCaps; the shared solver
produces a single canonical v_opt(s).

Deterministic: same OptimalCaps always produces same v_opt.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

_G: float = 9.80665
_SOLVER_VERSION: str = "optimal_v2_1.0"
_MIN_SPEED_MPS: float = 1.0
_MAX_ITERATIONS: int = 5


@dataclass
class OptimalCaps:
    """Unified input contract for the optimal solver.

    All cap sources fill this structure — the solver treats them identically.
    """
    distance_m: np.ndarray        # distance grid [m]
    v_cap: np.ndarray             # max speed at each point [m/s]
    ax_accel: np.ndarray          # max traction accel [m/s^2] per point
    ax_brake: np.ndarray          # max braking decel [m/s^2] per point (positive)
    curvature: np.ndarray         # curvature [1/m] at each point
    mu: np.ndarray | None         # friction coeff per point (None = use v_cap only)
    cap_source: list[str]         # per-point provenance tag
    solver_version: str = _SOLVER_VERSION

    def to_dict(self) -> dict:
        source_counts = dict(Counter(self.cap_source))
        return {
            "n_points": len(self.distance_m),
            "lap_length_m": round(float(self.distance_m[-1] - self.distance_m[0]), 1)
                if len(self.distance_m) > 1 else 0.0,
            "v_cap_mean": round(float(np.mean(self.v_cap)), 2),
            "ax_accel_mean": round(float(np.mean(self.ax_accel)), 2),
            "ax_brake_mean": round(float(np.mean(self.ax_brake)), 2),
            "has_mu": self.mu is not None,
            "cap_source_summary": source_counts,
            "solver_version": self.solver_version,
        }


@dataclass
class OptimalResult:
    """Canonical output from the optimal solver."""
    distance_m: np.ndarray
    v_opt_mps: np.ndarray           # optimal speed trace
    accel_profile_mps2: np.ndarray  # longitudinal accel at each point
    lap_time_s: float
    cornering_limited: np.ndarray   # bool per point
    accel_limited: np.ndarray       # bool per point
    brake_limited: np.ndarray       # bool per point
    limiting_factor: np.ndarray     # per-point string: "cornering"|"traction"|"braking"|"cap"
    cap_source: list[str]           # from OptimalCaps
    solver_version: str
    n_iterations: int

    def to_dict(self) -> dict:
        source_counts = dict(Counter(self.cap_source))
        n = len(self.v_opt_mps)
        return {
            "distance_m": np.round(self.distance_m, 2).tolist(),
            "v_opt_mps": np.round(self.v_opt_mps, 4).tolist(),
            "lap_time_s": round(self.lap_time_s, 4),
            "solver_version": self.solver_version,
            "cap_source_summary": source_counts,
            "cornering_limited_frac": round(float(self.cornering_limited.mean()), 4)
                if n > 0 else 0.0,
            "accel_limited_frac": round(float(self.accel_limited.mean()), 4)
                if n > 0 else 0.0,
            "brake_limited_frac": round(float(self.brake_limited.mean()), 4)
                if n > 0 else 0.0,
            "limiting_factor": self.limiting_factor.tolist(),
            "limiting_factor_summary": dict(Counter(self.limiting_factor.tolist())),
            "n_iterations": self.n_iterations,
        }

    def to_theoretical_df(self) -> "pd.DataFrame":
        """Convert to the legacy pipeline DataFrame format."""
        import pandas as pd
        accel = self.accel_profile_mps2.copy()
        accel_pos = np.where(accel > 0, accel, 0.0)
        brake_pos = np.where(accel < 0, np.abs(accel), 0.0)
        return pd.DataFrame({
            "distance_m": self.distance_m,
            "v_env_mps": self.v_opt_mps,
            "accel_max_mps2": accel_pos,
            "brake_max_mps2": brake_pos,
        })


@dataclass
class CornerSaturation:
    """Per-corner breakdown of limiting factor distribution."""
    corner_id: int
    s_start: float
    s_end: float
    cornering_pct: float
    traction_pct: float
    braking_pct: float
    cap_pct: float
    dominant_factor: str
    saturation_98pct: float   # fraction of bins at >98% of active constraint

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "s_start": round(self.s_start, 2),
            "s_end": round(self.s_end, 2),
            "cornering_pct": round(self.cornering_pct, 4),
            "traction_pct": round(self.traction_pct, 4),
            "braking_pct": round(self.braking_pct, 4),
            "cap_pct": round(self.cap_pct, 4),
            "dominant_factor": self.dominant_factor,
            "saturation_98pct": round(self.saturation_98pct, 4),
        }


def solve_optimal_speed(caps: OptimalCaps) -> OptimalResult:
    """Run forward-backward feasibility solver on unified caps.

    Deterministic: same OptimalCaps always produces same v_opt.

    Algorithm
    ---------
    1. Cornering pass: v_corner = min(v_cap, sqrt(mu*g / |curvature|))
    2. Forward pass: v[i+1] = sqrt(v[i]^2 + 2*ax_accel*ds), capped by v_corner
    3. Backward pass: v[i] = sqrt(v[i+1]^2 + 2*ax_brake*ds), capped by v_corner
    4. v_opt = min(forward, backward, v_corner)
    5. Iterate for closed-loop convergence
    """
    n = len(caps.distance_m)
    if n < 2:
        return OptimalResult(
            distance_m=caps.distance_m,
            v_opt_mps=caps.v_cap.copy(),
            accel_profile_mps2=np.zeros(n),
            lap_time_s=0.0,
            cornering_limited=np.ones(n, dtype=bool),
            accel_limited=np.zeros(n, dtype=bool),
            brake_limited=np.zeros(n, dtype=bool),
            limiting_factor=np.full(n, "cornering", dtype=object),
            cap_source=caps.cap_source,
            solver_version=caps.solver_version,
            n_iterations=0,
        )

    dist = caps.distance_m
    ds = np.diff(dist)

    # Step 1: Cornering speed limit
    v_corner = caps.v_cap.copy()
    if caps.mu is not None:
        for i in range(n):
            kappa = abs(caps.curvature[i])
            if kappa > 1e-6:
                v_mu = math.sqrt(caps.mu[i] * _G / kappa)
                v_corner[i] = min(v_corner[i], v_mu)
    v_corner = np.clip(v_corner, _MIN_SPEED_MPS, None)

    # Iterate forward-backward for convergence
    v_opt = v_corner.copy()
    n_iter = 0
    v_fwd = v_corner.copy()
    v_bwd = v_corner.copy()

    for iteration in range(_MAX_ITERATIONS):
        n_iter = iteration + 1
        v_prev = v_opt.copy()

        # Step 2: Forward pass (acceleration limited)
        v_fwd = v_corner.copy()
        for i in range(n - 1):
            a_max = caps.ax_accel[i]
            v_next_sq = v_fwd[i] ** 2 + 2.0 * a_max * ds[i]
            if v_next_sq > 0:
                v_fwd[i + 1] = min(v_corner[i + 1], math.sqrt(v_next_sq))
            else:
                v_fwd[i + 1] = _MIN_SPEED_MPS

        # Step 3: Backward pass (braking limited)
        v_bwd = v_corner.copy()
        for i in range(n - 2, -1, -1):
            b_max = caps.ax_brake[i + 1]
            v_prev_sq = v_bwd[i + 1] ** 2 + 2.0 * b_max * ds[i]
            if v_prev_sq > 0:
                v_bwd[i] = min(v_corner[i], math.sqrt(v_prev_sq))
            else:
                v_bwd[i] = _MIN_SPEED_MPS

        # Step 4: v_opt = min(forward, backward, v_corner)
        v_opt = np.minimum(np.minimum(v_fwd, v_bwd), v_corner)
        v_opt = np.clip(v_opt, _MIN_SPEED_MPS, None)

        # Convergence check
        if np.max(np.abs(v_opt - v_prev)) < 0.001:
            break

    # Compute accel profile from v_opt
    accel_profile = np.zeros(n)
    for i in range(n - 1):
        if ds[i] > 0:
            accel_profile[i] = (v_opt[i + 1] ** 2 - v_opt[i] ** 2) / (2.0 * ds[i])
    accel_profile[-1] = accel_profile[-2] if n > 1 else 0.0

    # Classify limiting constraints
    tol = 0.5  # m/s tolerance
    cornering_limited = np.abs(v_opt - v_corner) < tol
    accel_limited = np.abs(v_opt - v_fwd) < tol
    brake_limited = np.abs(v_opt - v_bwd) < tol

    # Per-point limiting factor (priority: cornering > braking > traction > cap)
    limiting_factor = np.full(n, "cap", dtype=object)
    for i in range(n):
        if cornering_limited[i]:
            limiting_factor[i] = "cornering"
        elif brake_limited[i]:
            limiting_factor[i] = "braking"
        elif accel_limited[i]:
            limiting_factor[i] = "traction"

    # Lap time via trapezoidal integration
    inv_v = 1.0 / np.clip(v_opt, _MIN_SPEED_MPS, None)
    dt = 0.5 * (inv_v[:-1] + inv_v[1:]) * np.abs(ds)
    lap_time = float(np.sum(dt))

    logger.info(
        "Optimal solver: %.2fs, %d iterations, %.0f%% corner / "
        "%.0f%% accel / %.0f%% brake limited.",
        lap_time, n_iter,
        100 * cornering_limited.mean(),
        100 * accel_limited.mean(),
        100 * brake_limited.mean(),
    )

    return OptimalResult(
        distance_m=dist,
        v_opt_mps=v_opt,
        accel_profile_mps2=accel_profile,
        lap_time_s=lap_time,
        cornering_limited=cornering_limited,
        accel_limited=accel_limited,
        brake_limited=brake_limited,
        limiting_factor=limiting_factor,
        cap_source=caps.cap_source,
        solver_version=caps.solver_version,
        n_iterations=n_iter,
    )


def compute_corner_saturation(
    result: OptimalResult,
    corners: list[dict],
) -> list[CornerSaturation]:
    """Compute per-corner saturation metrics from solver result.

    Parameters
    ----------
    result : OptimalResult with limiting_factor
    corners : list of dicts with corner_id, s_start, s_end

    Returns
    -------
    List of CornerSaturation, one per corner.
    """
    if not corners:
        return []

    dist = result.distance_m
    saturations = []

    for corner in corners:
        cid = corner.get("corner_id", 0)
        s_start = corner.get("s_start", 0)
        s_end = corner.get("s_end", 0)

        # Find indices within corner
        mask = (dist >= s_start) & (dist <= s_end)
        n_pts = int(mask.sum())
        if n_pts == 0:
            continue

        # Factor distribution
        factors = result.limiting_factor[mask]
        total = len(factors)
        cornering_pct = float(np.sum(factors == "cornering")) / total
        traction_pct = float(np.sum(factors == "traction")) / total
        braking_pct = float(np.sum(factors == "braking")) / total
        cap_pct = float(np.sum(factors == "cap")) / total

        # Dominant factor
        counts = {"cornering": cornering_pct, "traction": traction_pct,
                  "braking": braking_pct, "cap": cap_pct}
        dominant = max(counts, key=counts.get)

        # Saturation: fraction of bins where v_opt is >98% of the constraint
        # that is actually limiting at that point
        v_opt = result.v_opt_mps[mask]
        cornering_mask_local = result.cornering_limited[mask]
        accel_mask_local = result.accel_limited[mask]
        brake_mask_local = result.brake_limited[mask]

        # Count how many limited points there are as the saturation proxy
        limited_any = cornering_mask_local | accel_mask_local | brake_mask_local
        sat_98 = float(limited_any.sum()) / total if total > 0 else 0.0

        saturations.append(CornerSaturation(
            corner_id=cid,
            s_start=s_start,
            s_end=s_end,
            cornering_pct=cornering_pct,
            traction_pct=traction_pct,
            braking_pct=braking_pct,
            cap_pct=cap_pct,
            dominant_factor=dominant,
            saturation_98pct=sat_98,
        ))

    return saturations
