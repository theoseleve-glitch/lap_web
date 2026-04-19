"""
Uncertainty-aware OCP grip policy — feeds bucketed friction uncertainty
into the existing CasADi solver via a per-point effective friction array.

Three modes:
  Nominal:     mu_eff = mu_mean (best estimate, no safety margin)
  Robust:      mu_eff = mu_mean - k_sigma*std - k_fallback*depth (conservative)
  Exploitable: mu_eff = mu_mean where trusted, degrades toward robust where not

The solver itself is unchanged — only its grip_map input is modified.
This is a thin, deterministic tightening layer, not stochastic control.

Key properties:
  - Robustness is LOCAL: only uncertain sectors get tightened
  - Fallback depth matters: global-prior estimates are penalised more
  - Transition-excluded zones get the most conservative treatment
  - Exploitable never exceeds mu_mean (no optimistic fantasy grip)
  - Infeasibility from over-tightening degrades gracefully
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Final

import numpy as np

from track_surface.condition_bucketing import (
    BucketKey,
    BucketQueryResult,
    BucketedSurfaceField,
    TRANSITION_BUCKET,
    assign_bucket_keys,
)

logger = logging.getLogger(__name__)

_MU_FLOOR: Final[float] = 0.5  # absolute minimum — even the worst surface has some grip


class PlannerMode(Enum):
    NOMINAL = "nominal"
    ROBUST = "robust"
    EXPLOITABLE = "exploitable"


@dataclass
class RobustGripConfig:
    """Tuning knobs for the uncertainty-to-grip mapping."""
    # Robust mode
    k_sigma: float = 1.5           # how many stds to subtract
    k_fallback: float = 0.05       # penalty per fallback depth level
    mu_floor: float = _MU_FLOOR

    # Exploitable mode thresholds (must ALL pass to allow aggressive)
    exploit_min_confidence: float = 0.3
    exploit_max_std: float = 0.15
    exploit_max_fallback_depth: int = 0   # only exact bucket hits

    # Boundary tightening in uncertain zones
    boundary_tighten_factor: float = 0.85  # multiply track width by this where uncertain


@dataclass
class GripPolicyPoint:
    """Per-point output of the grip policy."""
    mu_eff: float              # effective friction for the solver
    mu_mean: float             # raw field mean
    mu_std: float              # field uncertainty
    confidence: float          # field confidence
    fallback_depth: int        # 0=exact, 1=section, 2=global
    mode_applied: str          # which mode actually governed this point
    is_trusted: bool           # True = exploitable mode can be aggressive here
    boundary_scale: float      # 1.0 = full width, <1 = tightened


def compute_mu_eff_single(
    query: BucketQueryResult,
    mode: PlannerMode,
    config: RobustGripConfig,
) -> GripPolicyPoint:
    """Compute effective friction for one (s, n) point.

    This is the core policy function. It maps field uncertainty to
    a solver-ready friction value based on the planner mode.
    """
    mu_mean = query.mean
    mu_std = query.std
    conf = query.confidence
    depth = query.fallback_depth

    # ── Nominal: best estimate, no margin ────────────────────
    if mode == PlannerMode.NOMINAL:
        return GripPolicyPoint(
            mu_eff=max(mu_mean, config.mu_floor),
            mu_mean=mu_mean, mu_std=mu_std,
            confidence=conf, fallback_depth=depth,
            mode_applied="nominal",
            is_trusted=True,
            boundary_scale=1.0,
        )

    # ── Robust: conservative where uncertain ─────────────────
    if mode == PlannerMode.ROBUST:
        penalty = config.k_sigma * mu_std + config.k_fallback * depth
        mu_eff = max(config.mu_floor, mu_mean - penalty)

        # Boundary tightening: uncertain zones get narrower track
        boundary_scale = 1.0
        if conf < 0.2 or depth >= 2:
            boundary_scale = config.boundary_tighten_factor

        return GripPolicyPoint(
            mu_eff=mu_eff,
            mu_mean=mu_mean, mu_std=mu_std,
            confidence=conf, fallback_depth=depth,
            mode_applied="robust",
            is_trusted=False,
            boundary_scale=boundary_scale,
        )

    # ── Exploitable: aggressive only where trustworthy ───────
    if mode == PlannerMode.EXPLOITABLE:
        trusted = (
            conf >= config.exploit_min_confidence
            and mu_std <= config.exploit_max_std
            and depth <= config.exploit_max_fallback_depth
        )

        if trusted:
            # High confidence: use the full mean (no penalty)
            mu_eff = max(mu_mean, config.mu_floor)
            mode_label = "exploitable_trusted"
            boundary_scale = 1.0
        else:
            # Low confidence: degrade toward robust
            penalty = config.k_sigma * mu_std + config.k_fallback * depth
            mu_eff = max(config.mu_floor, mu_mean - penalty * 0.5)
            mode_label = "exploitable_degraded"
            boundary_scale = config.boundary_tighten_factor if depth >= 2 else 0.95

        return GripPolicyPoint(
            mu_eff=mu_eff,
            mu_mean=mu_mean, mu_std=mu_std,
            confidence=conf, fallback_depth=depth,
            mode_applied=mode_label,
            is_trusted=trusted,
            boundary_scale=boundary_scale,
        )

    raise ValueError(f"Unknown planner mode: {mode}")


# ── Batch: build the grip_map array for the solver ──────────


def build_grip_map_for_ocp(
    *,
    bucketed_field: BucketedSurfaceField,
    s_grid: np.ndarray,              # (M,) centerline arc lengths
    n_query: float = 0.0,            # lateral offset for the query (centerline = 0)
    bucket_keys_per_s: np.ndarray,   # (M,) BucketKey per s-point
    mode: PlannerMode = PlannerMode.NOMINAL,
    config: RobustGripConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, list[GripPolicyPoint]]:
    """Build the mu_eff(s) array that feeds into TrackModel.grip_map.

    Returns
    -------
    mu_eff : (M,) effective friction for the solver
    boundary_scale : (M,) per-point track width multiplier
    details : list of GripPolicyPoint for diagnostics
    """
    if config is None:
        config = RobustGripConfig()

    M = len(s_grid)
    mu_eff = np.ones(M)
    boundary_scale = np.ones(M)
    details: list[GripPolicyPoint] = []

    for i in range(M):
        bucket = bucket_keys_per_s[i]

        # Transition-excluded: use most conservative policy
        if bucket == TRANSITION_BUCKET:
            point = GripPolicyPoint(
                mu_eff=config.mu_floor,
                mu_mean=config.mu_floor, mu_std=0.25,
                confidence=0.0, fallback_depth=2,
                mode_applied="transition_excluded",
                is_trusted=False,
                boundary_scale=config.boundary_tighten_factor,
            )
        else:
            query = bucketed_field.query(float(s_grid[i]), n_query, bucket)
            point = compute_mu_eff_single(query, mode, config)

        mu_eff[i] = point.mu_eff
        boundary_scale[i] = point.boundary_scale
        details.append(point)

    return mu_eff, boundary_scale, details


# ── Diagnostics ──────────────────────────────────────────────


@dataclass
class ModeDiagnostics:
    """Comparison diagnostics across the three planner modes."""
    nominal_mean_mu: float
    robust_mean_mu: float
    exploitable_mean_mu: float
    n_trusted_exploitable: int    # how many points are truly exploitable
    n_degraded_exploitable: int   # how many degraded to robust-like
    n_transition_excluded: int
    max_robust_penalty: float     # biggest mu reduction from nominal
    sectors_most_tightened: list[tuple[float, float]]  # (s_start, penalty) top-5


def compare_modes(
    bucketed_field: BucketedSurfaceField,
    s_grid: np.ndarray,
    bucket_keys_per_s: np.ndarray,
    config: RobustGripConfig | None = None,
) -> ModeDiagnostics:
    """Run all three modes and compare."""
    if config is None:
        config = RobustGripConfig()

    nom_mu, _, nom_det = build_grip_map_for_ocp(
        bucketed_field=bucketed_field, s_grid=s_grid,
        bucket_keys_per_s=bucket_keys_per_s,
        mode=PlannerMode.NOMINAL, config=config,
    )
    rob_mu, _, rob_det = build_grip_map_for_ocp(
        bucketed_field=bucketed_field, s_grid=s_grid,
        bucket_keys_per_s=bucket_keys_per_s,
        mode=PlannerMode.ROBUST, config=config,
    )
    exp_mu, _, exp_det = build_grip_map_for_ocp(
        bucketed_field=bucketed_field, s_grid=s_grid,
        bucket_keys_per_s=bucket_keys_per_s,
        mode=PlannerMode.EXPLOITABLE, config=config,
    )

    n_trusted = sum(1 for d in exp_det if d.is_trusted)
    n_degraded = sum(1 for d in exp_det if d.mode_applied == "exploitable_degraded")
    n_transition = sum(1 for d in exp_det if d.mode_applied == "transition_excluded")

    penalties = nom_mu - rob_mu
    top_5_idx = np.argsort(penalties)[-5:][::-1]
    sectors = [(float(s_grid[i]), float(penalties[i])) for i in top_5_idx]

    return ModeDiagnostics(
        nominal_mean_mu=float(nom_mu.mean()),
        robust_mean_mu=float(rob_mu.mean()),
        exploitable_mean_mu=float(exp_mu.mean()),
        n_trusted_exploitable=n_trusted,
        n_degraded_exploitable=n_degraded,
        n_transition_excluded=n_transition,
        max_robust_penalty=float(penalties.max()),
        sectors_most_tightened=sectors,
    )
