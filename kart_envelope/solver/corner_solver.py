"""
corner_solver.py
----------------
Per-corner QSS (Quasi-Steady-State) min-time solver.

Solves the minimum-time speed profile through a single corner segment
using the same forward/backward sweep as the full-lap solver, but with
fixed entry/exit boundary speeds instead of wrap-around closure.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ── Data classes ─────────────────────────────────────────────────


@dataclass
class CornerActionable:
    """One concrete, immediately-actionable instruction for the driver."""

    rank: int
    action: str
    impact_ms: float
    category: str  # braking | apex_speed | exit_traction | entry_speed | trail_brake
    phase: str  # entry | mid | exit

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "action": self.action,
            "impact_ms": round(self.impact_ms, 1),
            "category": self.category,
            "phase": self.phase,
        }


@dataclass
class CornerOCPResult:
    """Output of a per-corner min-time solve."""

    corner_id: int
    distances: list[float]
    speeds: list[float]  # optimal speed profile (m/s)
    optimal_apex_speed: float
    optimal_entry_speed: float
    optimal_exit_speed: float
    optimal_time_s: float
    actual_apex_speed: float = 0.0
    actual_entry_speed: float = 0.0
    actual_exit_speed: float = 0.0
    actual_time_s: float = 0.0
    time_delta_s: float = 0.0
    speed_delta_apex: float = 0.0
    actionables: list[CornerActionable] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "distances": [round(d, 2) for d in self.distances],
            "optimal_speeds": [round(s, 4) for s in self.speeds],
            "optimal_apex_speed": round(self.optimal_apex_speed, 4),
            "optimal_entry_speed": round(self.optimal_entry_speed, 4),
            "optimal_exit_speed": round(self.optimal_exit_speed, 4),
            "optimal_time_s": round(self.optimal_time_s, 4),
            "actual_apex_speed": round(self.actual_apex_speed, 4),
            "actual_entry_speed": round(self.actual_entry_speed, 4),
            "actual_exit_speed": round(self.actual_exit_speed, 4),
            "actual_time_s": round(self.actual_time_s, 4),
            "time_delta_s": round(self.time_delta_s, 4),
            "speed_delta_apex": round(self.speed_delta_apex, 4),
            "actionables": [a.to_dict() for a in self.actionables],
        }


# ── Standalone QSS solver (no envelope dependency) ──────────────


def _max_cornering_speed(curvature: float, mu: float, g: float = 9.81) -> float:
    """Maximum speed through a corner at given curvature and friction."""
    if abs(curvature) < 1e-6:
        return 200.0  # effectively unlimited on a straight
    return math.sqrt(mu * g / abs(curvature))


def solve_corner_qss(
    curvature: np.ndarray,
    distances: np.ndarray,
    mu: float,
    v_entry: float,
    v_exit: float,
    mass_kg: float = 180.0,
    g: float = 9.81,
    accel_g: float = 0.5,
    brake_g: float = 1.2,
) -> CornerOCPResult:
    """QSS forward/backward sweep on a corner sub-segment.

    Forward pass: start at v_entry, accelerate up to cornering limit.
    Backward pass: start at v_exit, reverse-brake from the exit.
    Take minimum of both passes at each point → optimal speed profile.

    Parameters
    ----------
    curvature : ndarray  — curvature (1/m) at each sample point
    distances : ndarray  — cumulative distance (m) at each sample point
    mu        : float    — friction coefficient
    v_entry   : float    — entry speed boundary condition (m/s)
    v_exit    : float    — exit speed boundary condition (m/s)
    mass_kg   : float    — vehicle mass (for future aero/powertrain hooks)
    g         : float    — gravitational acceleration
    accel_g   : float    — max longitudinal accel as fraction of g
    brake_g   : float    — max longitudinal braking as fraction of g
    """
    n = len(distances)
    if n < 2:
        return CornerOCPResult(
            corner_id=0, distances=distances.tolist(), speeds=[v_entry],
            optimal_apex_speed=v_entry, optimal_entry_speed=v_entry,
            optimal_exit_speed=v_exit, optimal_time_s=0.0,
        )

    ds = np.diff(distances)

    # Cornering speed limit at each point
    v_corner = np.array([_max_cornering_speed(float(curvature[i]), mu, g) for i in range(n)])

    a_max = accel_g * g
    a_brake = brake_g * g

    # Forward pass: accelerate from entry, limited by cornering
    v_fwd = np.full(n, 200.0)
    v_fwd[0] = min(v_entry, v_corner[0])
    for i in range(1, n):
        v_sq = v_fwd[i - 1] ** 2 + 2.0 * a_max * ds[i - 1]
        v_fwd[i] = min(math.sqrt(max(v_sq, 0.0)), v_corner[i])

    # Backward pass: brake from exit, limited by cornering
    v_bwd = np.full(n, 200.0)
    v_bwd[-1] = min(v_exit, v_corner[-1])
    for i in range(n - 2, -1, -1):
        v_sq = v_bwd[i + 1] ** 2 + 2.0 * a_brake * ds[i]
        v_bwd[i] = min(math.sqrt(max(v_sq, 0.0)), v_corner[i])

    # Take minimum of forward, backward, and cornering limit
    v_opt = np.minimum(np.minimum(v_fwd, v_bwd), v_corner)

    # Compute time through corner
    time_s = 0.0
    for i in range(n - 1):
        v_avg = (v_opt[i] + v_opt[i + 1]) / 2.0
        if v_avg > 0.1:
            time_s += ds[i] / v_avg

    apex_idx = int(np.argmin(v_opt))

    return CornerOCPResult(
        corner_id=0,  # set by caller
        distances=distances.tolist(),
        speeds=v_opt.tolist(),
        optimal_apex_speed=float(v_opt[apex_idx]),
        optimal_entry_speed=float(v_opt[0]),
        optimal_exit_speed=float(v_opt[-1]),
        optimal_time_s=float(time_s),
    )


# ── Envelope-aware QSS solver ───────────────────────────────────


def solve_corner_qss_envelope(
    curvature: np.ndarray,
    distances: np.ndarray,
    envelope: Any,  # CapabilityEnvelope
    scalars: Any | None = None,  # SessionScalars
    v_entry: float = 20.0,
    v_exit: float = 20.0,
    v_max: float = 50.0,
    v_min: float = 2.0,
) -> CornerOCPResult:
    """QSS corner solver using the full CapabilityEnvelope.

    Uses the same physics as the full-lap solver (envelope.max_cornering_speed,
    envelope.max_longitudinal_accel) but on a sub-segment with boundary speeds.
    """
    env = envelope
    if scalars is not None and hasattr(envelope, "scaled"):
        env = envelope.scaled(
            mu=getattr(scalars, "mu_session", 1.0),
            p_drive=getattr(scalars, "p_session", 1.0),
            b_brake=getattr(scalars, "b_session", 1.0),
        )

    n = len(distances)
    if n < 2:
        return CornerOCPResult(
            corner_id=0, distances=distances.tolist(), speeds=[v_entry],
            optimal_apex_speed=v_entry, optimal_entry_speed=v_entry,
            optimal_exit_speed=v_exit, optimal_time_s=0.0,
        )

    ds = np.diff(distances)
    kappa = curvature

    # Cornering speed limits from envelope
    v_corner = np.empty(n)
    for i in range(n):
        v_corner[i] = min(max(v_min, env.max_cornering_speed(float(kappa[i]))), v_max)

    # Forward pass (accelerate from entry)
    v_fwd = np.full(n, v_max)
    v_fwd[0] = min(v_entry, v_corner[0])
    for i in range(1, n):
        v_cur = min(v_fwd[i - 1], v_corner[i - 1])
        a_lat = v_cur * v_cur * kappa[i - 1] if kappa[i - 1] > 0 else 0.0
        a_drive = env.max_longitudinal_accel(float(v_cur), float(a_lat), braking=False)
        v_sq = v_cur * v_cur + 2.0 * max(0.0, float(a_drive)) * ds[i - 1]
        v_fwd[i] = min(math.sqrt(max(v_sq, 0.0)), v_corner[i], v_max)

    # Backward pass (brake from exit)
    v_bwd = np.full(n, v_max)
    v_bwd[-1] = min(v_exit, v_corner[-1])
    for i in range(n - 2, -1, -1):
        v_cur = min(v_bwd[i + 1], v_corner[i + 1])
        a_lat = v_cur * v_cur * kappa[i + 1] if kappa[i + 1] > 0 else 0.0
        a_brake = env.max_longitudinal_accel(float(v_cur), float(a_lat), braking=True)
        v_sq = v_cur * v_cur + 2.0 * max(0.0, float(a_brake)) * ds[i]
        v_bwd[i] = min(math.sqrt(max(v_sq, 0.0)), v_corner[i], v_max)

    v_opt = np.minimum(np.minimum(v_fwd, v_bwd), v_corner)
    v_opt = np.clip(v_opt, v_min, v_max)

    # Compute time
    time_s = 0.0
    for i in range(n - 1):
        v_avg = (v_opt[i] + v_opt[i + 1]) / 2.0
        if v_avg > 0.1:
            time_s += ds[i] / v_avg

    apex_idx = int(np.argmin(v_opt))

    return CornerOCPResult(
        corner_id=0,
        distances=distances.tolist(),
        speeds=v_opt.tolist(),
        optimal_apex_speed=float(v_opt[apex_idx]),
        optimal_entry_speed=float(v_opt[0]),
        optimal_exit_speed=float(v_opt[-1]),
        optimal_time_s=float(time_s),
    )


# ── Actionable generation ────────────────────────────────────────


def generate_actionables(
    ocp: CornerOCPResult,
    actual_speeds: np.ndarray | None = None,
    actual_brake_dist: float | None = None,
    optimal_brake_dist: float | None = None,
    actual_throttle_dist: float | None = None,
    optimal_throttle_dist: float | None = None,
    corner_length_m: float = 100.0,
) -> list[CornerActionable]:
    """Generate exactly 3 ranked actionables by comparing driver vs OCP.

    Candidates are generated for 6 categories, ranked by time impact,
    and the top 3 are returned with concrete, number-backed instructions.
    """
    candidates: list[CornerActionable] = []

    # ── Entry speed delta ──
    if ocp.actual_entry_speed > 0 and ocp.optimal_entry_speed > 0:
        delta_mps = ocp.optimal_entry_speed - ocp.actual_entry_speed
        delta_kmh = delta_mps * 3.6
        if abs(delta_kmh) > 0.5:
            impact = abs(delta_mps) / max(ocp.actual_entry_speed, 1) * corner_length_m * 1000 / max(ocp.actual_entry_speed, 1)
            verb = "faster" if delta_kmh > 0 else "slower"
            candidates.append(CornerActionable(
                rank=0, phase="entry", category="entry_speed",
                action=f"Enter {abs(delta_kmh):.1f} km/h {verb}",
                impact_ms=impact,
            ))

    # ── Braking point delta ──
    if actual_brake_dist is not None and optimal_brake_dist is not None:
        delta_m = optimal_brake_dist - actual_brake_dist
        if abs(delta_m) > 1.0:
            impact = abs(delta_m) * 15.0  # ~15ms per meter of brake point shift
            verb = "later" if delta_m > 0 else "earlier"
            candidates.append(CornerActionable(
                rank=0, phase="entry", category="braking",
                action=f"Brake {abs(delta_m):.0f}m {verb}",
                impact_ms=impact,
            ))

    # ── Apex speed delta ──
    if ocp.actual_apex_speed > 0 and ocp.optimal_apex_speed > 0:
        delta_mps = ocp.optimal_apex_speed - ocp.actual_apex_speed
        delta_kmh = delta_mps * 3.6
        if abs(delta_kmh) > 0.3:
            impact = abs(delta_mps) / max(ocp.actual_apex_speed, 1) * corner_length_m * 1000 / max(ocp.actual_apex_speed, 1)
            if delta_kmh > 0:
                candidates.append(CornerActionable(
                    rank=0, phase="mid", category="apex_speed",
                    action=f"Carry {abs(delta_kmh):.1f} km/h more through the apex",
                    impact_ms=impact,
                ))
            else:
                candidates.append(CornerActionable(
                    rank=0, phase="mid", category="apex_speed",
                    action=f"Slow {abs(delta_kmh):.1f} km/h more at the apex",
                    impact_ms=impact,
                ))

    # ── Exit speed delta ──
    if ocp.actual_exit_speed > 0 and ocp.optimal_exit_speed > 0:
        delta_mps = ocp.optimal_exit_speed - ocp.actual_exit_speed
        delta_kmh = delta_mps * 3.6
        if abs(delta_kmh) > 0.5:
            # Exit speed cascades into the next straight
            impact = abs(delta_mps) * 80.0  # high impact due to cascade
            if delta_kmh > 0:
                candidates.append(CornerActionable(
                    rank=0, phase="exit", category="exit_traction",
                    action=f"Exit {abs(delta_kmh):.1f} km/h faster",
                    impact_ms=impact,
                ))
            else:
                candidates.append(CornerActionable(
                    rank=0, phase="exit", category="exit_traction",
                    action=f"Reduce exit speed by {abs(delta_kmh):.1f} km/h",
                    impact_ms=impact,
                ))

    # ── Throttle application point ──
    if actual_throttle_dist is not None and optimal_throttle_dist is not None:
        delta_m = optimal_throttle_dist - actual_throttle_dist
        if abs(delta_m) > 1.0:
            impact = abs(delta_m) * 12.0
            verb = "earlier" if delta_m < 0 else "later"
            candidates.append(CornerActionable(
                rank=0, phase="exit", category="exit_traction",
                action=f"Get on throttle {abs(delta_m):.0f}m {verb}",
                impact_ms=impact,
            ))

    # ── Trail braking (derived from entry speed + apex speed gap) ──
    if ocp.actual_entry_speed > 0 and ocp.actual_apex_speed > 0:
        actual_scrub = ocp.actual_entry_speed - ocp.actual_apex_speed
        optimal_scrub = ocp.optimal_entry_speed - ocp.optimal_apex_speed
        delta_scrub = optimal_scrub - actual_scrub
        if abs(delta_scrub * 3.6) > 1.0:
            impact = abs(delta_scrub) * 50.0
            if delta_scrub > 0:
                candidates.append(CornerActionable(
                    rank=0, phase="entry", category="trail_brake",
                    action=f"Trail brake {abs(delta_scrub * 3.6):.1f} km/h deeper into the corner",
                    impact_ms=impact,
                ))

    # Sort by impact, take top 3
    candidates.sort(key=lambda c: c.impact_ms, reverse=True)
    result = candidates[:3]

    # Pad if fewer than 3
    while len(result) < 3:
        result.append(CornerActionable(
            rank=0, phase="mid", category="apex_speed",
            action="No additional improvement identified",
            impact_ms=0.0,
        ))

    # Assign ranks
    for i, a in enumerate(result):
        a.rank = i + 1

    return result
