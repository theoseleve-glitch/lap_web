"""
raceline_optimizer.py
---------------------
Line variant generation and point-mass lap simulation for per-corner
raceline optimization.

Gated by ``enable_raceline_optimizer`` config flag (default False).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_G = 9.81


@dataclass
class LineVariant:
    variant_id: str
    corner_id: int
    apex_type: str
    offset_profile_m: list
    estimated_time_s: float
    delta_vs_baseline_s: float
    constraints_hit: list

    def to_dict(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "corner_id": self.corner_id,
            "apex_type": self.apex_type,
            "offset_profile_m": self.offset_profile_m,
            "estimated_time_s": self.estimated_time_s,
            "delta_vs_baseline_s": self.delta_vs_baseline_s,
            "constraints_hit": self.constraints_hit,
        }


@dataclass
class RacelineResult:
    corner_results: dict
    total_delta_s: float
    n_variants_evaluated: int

    def to_dict(self) -> dict:
        return {
            "corner_results": {
                k: v.to_dict() if hasattr(v, "to_dict") else v
                for k, v in self.corner_results.items()
            },
            "total_delta_s": self.total_delta_s,
            "n_variants_evaluated": self.n_variants_evaluated,
        }


_APEX_OFFSETS = {"early": -0.6, "neutral": 0.0, "late": 0.6}


def generate_line_variants(
    corner: dict,
    ref_line: dict,
    boundaries: dict,
    n_variants: int = 3,
) -> list[LineVariant]:
    """Generate early/neutral/late apex via curvature shaping within boundaries."""
    entry_s = corner.get("entry_s", 0)
    exit_s = corner.get("exit_s", 0)
    cid = corner.get("corner_id", 0)

    ref_dist = np.asarray(ref_line.get("distance_m", []))
    ref_curv = np.asarray(ref_line.get("curvature", np.zeros_like(ref_dist)))

    mask = (ref_dist >= entry_s) & (ref_dist <= exit_s)
    corner_dist = ref_dist[mask]
    corner_curv = ref_curv[mask]

    if len(corner_dist) < 3:
        return []

    left_bound = (
        np.asarray(boundaries.get("left_offset_m", []))[mask]
        if len(np.asarray(boundaries.get("left_offset_m", []))) == len(ref_dist)
        else np.ones(len(corner_dist)) * 5
    )
    right_bound = (
        np.asarray(boundaries.get("right_offset_m", []))[mask]
        if len(np.asarray(boundaries.get("right_offset_m", []))) == len(ref_dist)
        else np.ones(len(corner_dist)) * -5
    )

    variants = []
    for apex_type, shift_frac in _APEX_OFFSETS.items():
        n_pts = len(corner_dist)
        offset = np.zeros(n_pts)
        apex_idx = int(n_pts * (0.5 + shift_frac * 0.3))
        apex_idx = max(1, min(apex_idx, n_pts - 2))

        for i in range(n_pts):
            t = max(0, 1.0 - abs(i - apex_idx) / max(n_pts, 1))
            offset[i] = t * right_bound[min(apex_idx, len(right_bound) - 1)] * 0.5

        ds = np.diff(corner_dist, prepend=corner_dist[0])
        ds[ds == 0] = 1.0
        dd_offset = np.gradient(np.gradient(offset))
        modified_curv = corner_curv + dd_offset / (ds * ds.mean())

        constraints = []
        for i in range(n_pts):
            if offset[i] > left_bound[i]:
                offset[i] = left_bound[i]
                constraints.append(f"left_at_{i}")
            if offset[i] < right_bound[i]:
                offset[i] = right_bound[i]
                constraints.append(f"right_at_{i}")

        t_est = simulate_variant_time(
            np.abs(modified_curv), entry_speed=25.0, friction_mu=1.2
        )

        variants.append(
            LineVariant(
                variant_id=f"C{cid}_{apex_type}_apex",
                corner_id=cid,
                apex_type=apex_type,
                offset_profile_m=offset.tolist(),
                estimated_time_s=t_est,
                delta_vs_baseline_s=0.0,
                constraints_hit=constraints[:5],
            )
        )

    neutral_time = next(
        (v.estimated_time_s for v in variants if v.apex_type == "neutral"), None
    )
    if neutral_time:
        for v in variants:
            v.delta_vs_baseline_s = v.estimated_time_s - neutral_time

    return variants


def simulate_variant_time(
    curvature_profile: np.ndarray,
    entry_speed: float,
    friction_mu: float,
    ds: float = 1.0,
) -> float:
    """Point-mass sim: v_max = sqrt(mu*g/kappa), forward integration."""
    if len(curvature_profile) == 0:
        return 0.0

    total_time = 0.0
    v = entry_speed

    for kappa in curvature_profile:
        kappa_abs = max(abs(kappa), 1e-6)
        v_max = math.sqrt(friction_mu * _G / kappa_abs)
        v = min(v, v_max)
        v = max(v, 1.0)
        dt = ds / v
        total_time += dt

    return total_time


def optimize_corner_lines(
    corners: list[dict],
    ref_line: dict,
    boundaries: dict,
    friction_model: dict,
    compound_groups: list | None = None,
) -> RacelineResult:
    """Pick min-time variant per corner."""
    corner_results = {}
    total_delta = 0.0
    n_evaluated = 0

    for corner in corners:
        cid = corner.get("corner_id", 0)
        variants = generate_line_variants(corner, ref_line, boundaries)
        n_evaluated += len(variants)
        if not variants:
            continue
        best = min(variants, key=lambda v: v.estimated_time_s)
        corner_results[cid] = best
        total_delta += best.delta_vs_baseline_s

    return RacelineResult(
        corner_results=corner_results,
        total_delta_s=total_delta,
        n_variants_evaluated=n_evaluated,
    )
