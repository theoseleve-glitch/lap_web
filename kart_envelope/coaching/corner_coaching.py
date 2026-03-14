"""
corner_coaching.py
------------------
Corner-level performance attribution: for each corner, compute entry /
apex / exit speed deltas versus theoretical and identify the primary
cause of time loss.

Supports **corner complexes**: adjacent corners are classified into
types (chicane, esses, decreasing/increasing radius) and grouped so
coaching advice considers compound strategy — e.g., "sacrifice entry
of corner 3 to maximize exit of corner 4."
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.ingest.columns import COL_ACCEL_LONG, COL_DIST, COL_SPEED
from kart_envelope.solver.min_time import TheoreticalResult

logger = logging.getLogger(__name__)


# ── Corner type classification ──────────────────────────────────────────

class CornerType:
    """Constants for corner types."""
    SINGLE = "single"
    CHICANE = "chicane"            # alternating direction (L-R or R-L)
    ESSES = "esses"               # 3+ alternating corners
    DECREASING_RADIUS = "decreasing_radius"  # tightening mid-corner
    INCREASING_RADIUS = "increasing_radius"  # opening mid-corner
    COMPOUND = "compound"          # same-direction linked corners


@dataclass
class CornerComplex:
    """A group of related corners that should be coached as a unit.

    Attributes
    ----------
    complex_id : int
        1-based identifier.
    corner_type : str
        One of ``CornerType`` constants.
    corner_ids : list[int]
        IDs of corners in this complex (in track order).
    priority_corner_id : int
        The corner within the complex whose exit matters most (typically
        the last corner before a straight).
    compound_hint : str
        Coaching advice for the complex as a whole.
    """
    complex_id: int
    corner_type: str
    corner_ids: list[int] = field(default_factory=list)
    priority_corner_id: int = 0
    compound_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "complex_id": self.complex_id,
            "corner_type": self.corner_type,
            "corner_ids": self.corner_ids,
            "priority_corner_id": self.priority_corner_id,
            "compound_hint": self.compound_hint,
        }


@dataclass
class CornerPerformance:
    """Performance breakdown for a single corner."""

    corner_id: int
    s_start: float
    s_end: float
    s_apex: float
    direction: str  # "L" or "R"

    # Speeds [m/s]
    entry_speed_actual: float = 0.0
    entry_speed_theory: float = 0.0
    apex_speed_actual: float = 0.0
    apex_speed_theory: float = 0.0
    exit_speed_actual: float = 0.0
    exit_speed_theory: float = 0.0

    # Braking
    brake_point_actual_m: float = 0.0
    brake_point_theory_m: float = 0.0
    brake_delta_m: float = 0.0  # positive = too early

    # Time loss decomposition [s]
    time_loss_total_s: float = 0.0
    time_loss_entry_s: float = 0.0
    time_loss_apex_s: float = 0.0
    time_loss_exit_s: float = 0.0

    # Primary cause
    primary_cause: str = ""
    coaching_hint: str = ""

    # Complex membership (filled by classify_corner_complexes)
    complex_id: int = 0          # 0 = standalone
    corner_type: str = "single"

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


def detect_corners_from_curvature(
    kappa: np.ndarray,
    distance: np.ndarray,
    threshold: float = 0.01,
    min_length_m: float = 10.0,
    merge_gap_m: float = 15.0,
    signed_kappa: np.ndarray | None = None,
) -> list[dict]:
    """Detect corners from the curvature profile.

    Parameters
    ----------
    kappa : np.ndarray
        Unsigned curvature [1/m].
    distance : np.ndarray
        Distance along track [m].
    threshold : float
        Minimum curvature to be considered a corner.
    min_length_m : float
        Minimum corner length [m].
    merge_gap_m : float
        Merge corners closer than this [m].
    signed_kappa : np.ndarray | None
        Signed curvature for direction detection. Positive = left, negative = right.
        If None, direction is unknown ("?").

    Returns list of ``{corner_id, s_start, s_end, s_apex, direction, peak_kappa}``.
    """
    n = len(kappa)
    in_corner = kappa > threshold
    corners: list[dict] = []
    corner_id = 0
    i = 0

    while i < n:
        if in_corner[i]:
            start = i
            while i < n and in_corner[i]:
                i += 1
            end = i - 1
            s_start = float(distance[start])
            s_end = float(distance[end])
            if (s_end - s_start) >= min_length_m:
                apex_idx = start + int(np.argmax(kappa[start:end + 1]))
                corner_id += 1

                # Determine direction from signed curvature
                direction = "?"
                if signed_kappa is not None:
                    mean_signed = float(np.mean(signed_kappa[start:end + 1]))
                    direction = "L" if mean_signed > 0 else "R"

                corners.append({
                    "corner_id": corner_id,
                    "s_start": s_start,
                    "s_end": s_end,
                    "s_apex": float(distance[apex_idx]),
                    "idx_start": start,
                    "idx_end": end,
                    "idx_apex": apex_idx,
                    "direction": direction,
                    "peak_kappa": float(kappa[apex_idx]),
                })
        else:
            i += 1

    # Merge close corners (same direction only — don't merge chicane halves)
    merged: list[dict] = []
    for c in corners:
        if (merged
                and (c["s_start"] - merged[-1]["s_end"]) < merge_gap_m
                and c["direction"] == merged[-1]["direction"]):
            prev = merged[-1]
            prev["s_end"] = c["s_end"]
            prev["idx_end"] = c["idx_end"]
            combined_kappa = kappa[prev["idx_start"]:c["idx_end"] + 1]
            rel_apex = int(np.argmax(combined_kappa))
            prev["idx_apex"] = prev["idx_start"] + rel_apex
            prev["s_apex"] = float(distance[prev["idx_apex"]])
            prev["peak_kappa"] = float(kappa[prev["idx_apex"]])
        else:
            merged.append(c)

    # Re-number
    for i, c in enumerate(merged):
        c["corner_id"] = i + 1

    return merged


def classify_corner_complexes(
    corners: list[dict],
    kappa: np.ndarray,
    distance: np.ndarray,
    complex_gap_m: float = 80.0,
) -> list[CornerComplex]:
    """Classify groups of adjacent corners into complexes.

    Adjacent corners within ``complex_gap_m`` are grouped and classified
    based on their directional pattern and curvature progression:

    - **chicane**: 2 corners with alternating direction (L-R or R-L).
    - **esses**: 3+ corners with alternating direction.
    - **decreasing_radius**: same-direction corners where curvature increases.
    - **increasing_radius**: same-direction corners where curvature decreases.
    - **compound**: same-direction linked corners without clear radius trend.
    - **single**: isolated corner (no adjacent neighbour within gap).

    The **priority corner** is the last corner in the complex — its exit
    leads onto a straight, so maximising that exit speed matters most.

    Parameters
    ----------
    corners : list[dict]
        From ``detect_corners_from_curvature``.
    kappa : np.ndarray
        Full unsigned curvature profile.
    distance : np.ndarray
        Full distance profile.
    complex_gap_m : float
        Maximum gap between corners to consider them part of a complex.

    Returns
    -------
    list[CornerComplex]
    """
    if not corners:
        return []

    # Group adjacent corners by gap
    groups: list[list[dict]] = [[corners[0]]]
    for c in corners[1:]:
        prev = groups[-1][-1]
        gap = c["s_start"] - prev["s_end"]
        if gap <= complex_gap_m:
            groups[-1].append(c)
        else:
            groups.append([c])

    complexes: list[CornerComplex] = []
    complex_id = 0

    for group in groups:
        complex_id += 1
        ids = [c["corner_id"] for c in group]
        directions = [c.get("direction", "?") for c in group]
        peak_kappas = [c.get("peak_kappa", 0.0) for c in group]

        if len(group) == 1:
            # Single corner — classify radius pattern within it
            c = group[0]
            c_type = _classify_single_corner_shape(
                kappa, distance, c["idx_start"], c["idx_end"], c["idx_apex"],
            )
            complexes.append(CornerComplex(
                complex_id=complex_id,
                corner_type=c_type,
                corner_ids=ids,
                priority_corner_id=ids[0],
                compound_hint=_single_hint(c_type),
            ))
            continue

        # Multi-corner group: classify by directional pattern
        alternating = _is_alternating(directions)

        if alternating and len(group) >= 3:
            c_type = CornerType.ESSES
            hint = _esses_hint(ids)
        elif alternating and len(group) == 2:
            c_type = CornerType.CHICANE
            hint = _chicane_hint(ids)
        else:
            # Same-direction or mixed — check curvature progression
            c_type = _classify_curvature_trend(peak_kappas)
            hint = _compound_hint(c_type, ids)

        # Priority = last corner in complex (exit onto straight)
        priority = ids[-1]

        complexes.append(CornerComplex(
            complex_id=complex_id,
            corner_type=c_type,
            corner_ids=ids,
            priority_corner_id=priority,
            compound_hint=hint,
        ))

    return complexes


def _is_alternating(directions: list[str]) -> bool:
    """Check if directions alternate (L-R-L or R-L-R)."""
    if any(d == "?" for d in directions):
        return False
    for i in range(1, len(directions)):
        if directions[i] == directions[i - 1]:
            return False
    return True


def _classify_single_corner_shape(
    kappa: np.ndarray,
    distance: np.ndarray,
    idx_start: int,
    idx_end: int,
    idx_apex: int,
) -> str:
    """Classify a single corner's curvature shape."""
    if idx_end <= idx_start + 4:
        return CornerType.SINGLE

    # Compare curvature in first and second halves
    mid = (idx_start + idx_end) // 2
    k_first = float(np.mean(kappa[idx_start:mid]))
    k_second = float(np.mean(kappa[mid:idx_end + 1]))

    if k_first > 0 and k_second > 0:
        ratio = k_second / k_first
        if ratio > 1.3:
            return CornerType.DECREASING_RADIUS
        if ratio < 0.7:
            return CornerType.INCREASING_RADIUS

    return CornerType.SINGLE


def _classify_curvature_trend(peak_kappas: list[float]) -> str:
    """Classify curvature trend across a same-direction multi-corner group."""
    if len(peak_kappas) < 2:
        return CornerType.COMPOUND
    increasing = all(peak_kappas[i] <= peak_kappas[i + 1] * 1.1
                     for i in range(len(peak_kappas) - 1))
    decreasing = all(peak_kappas[i] >= peak_kappas[i + 1] * 0.9
                     for i in range(len(peak_kappas) - 1))
    if increasing and not decreasing:
        return CornerType.DECREASING_RADIUS
    if decreasing and not increasing:
        return CornerType.INCREASING_RADIUS
    return CornerType.COMPOUND


# ── Compound coaching hints ─────────────────────────────────────────────

def _single_hint(c_type: str) -> str:
    if c_type == CornerType.DECREASING_RADIUS:
        return "Corner tightens — brake progressively and trail-brake deeper."
    if c_type == CornerType.INCREASING_RADIUS:
        return "Corner opens — get on throttle early; the radius is increasing."
    return ""


def _chicane_hint(ids: list[int]) -> str:
    return (
        f"Chicane (corners {ids[0]}-{ids[1]}): sacrifice corner {ids[0]} "
        f"entry to set up a fast exit from corner {ids[1]}. "
        f"The exit speed of corner {ids[1]} matters most — it leads onto the straight."
    )


def _esses_hint(ids: list[int]) -> str:
    return (
        f"Esses (corners {ids[0]}-{ids[-1]}): maintain rhythm and "
        f"smooth transitions. Prioritise exit of corner {ids[-1]} "
        f"for the following straight. Avoid over-slowing mid-sequence."
    )


def _compound_hint(c_type: str, ids: list[int]) -> str:
    if c_type == CornerType.DECREASING_RADIUS:
        return (
            f"Tightening complex (corners {ids[0]}-{ids[-1]}): "
            f"enter wide and slow progressively. Save braking for the "
            f"tightest section (corner {ids[-1]})."
        )
    if c_type == CornerType.INCREASING_RADIUS:
        return (
            f"Opening complex (corners {ids[0]}-{ids[-1]}): "
            f"the hardest part is the first corner. Once past corner "
            f"{ids[0]}, unwind and accelerate progressively."
        )
    return (
        f"Linked corners {ids[0]}-{ids[-1]}: "
        f"prioritise exit of corner {ids[-1]} — sacrifice entry speed "
        f"if needed to carry maximum exit speed onto the straight."
    )


def analyze_corner_performance(
    driver_lap: pd.DataFrame,
    theoretical: TheoreticalResult,
    corners: list[dict],
    complexes: list[CornerComplex] | None = None,
) -> list[CornerPerformance]:
    """Compute per-corner performance breakdown.

    Parameters
    ----------
    driver_lap : pd.DataFrame
        Resampled driver lap with canonical columns.
    theoretical : TheoreticalResult
    corners : list[dict]
        Output of ``detect_corners_from_curvature``.
    complexes : list[CornerComplex] | None
        Output of ``classify_corner_complexes``. If provided, each
        ``CornerPerformance`` is tagged with its complex membership.

    Returns
    -------
    list[CornerPerformance]
    """
    if COL_DIST not in driver_lap.columns or COL_SPEED not in driver_lap.columns:
        return []

    s_dr = driver_lap[COL_DIST].values
    v_dr = driver_lap[COL_SPEED].values
    s_th = theoretical.distance_m
    v_th = theoretical.speed_profile_mps

    has_ax = COL_ACCEL_LONG in driver_lap.columns
    ax_dr = driver_lap[COL_ACCEL_LONG].values if has_ax else np.zeros_like(v_dr)

    results: list[CornerPerformance] = []

    for corner in corners:
        s_start = corner["s_start"]
        s_end = corner["s_end"]
        s_apex = corner["s_apex"]
        c_len = s_end - s_start
        if c_len <= 0:
            continue

        # Define entry / apex / exit zones
        entry_lo, entry_hi = s_start, s_start + 0.2 * c_len
        apex_lo, apex_hi = s_apex - 0.1 * c_len, s_apex + 0.1 * c_len
        exit_lo, exit_hi = s_end - 0.2 * c_len, s_end

        # Interpolate driver speeds at zone midpoints
        def _mean_speed(s_arr, v_arr, lo, hi):
            mask = (s_arr >= lo) & (s_arr <= hi) & np.isfinite(v_arr)
            return float(np.mean(v_arr[mask])) if mask.any() else 0.0

        cp = CornerPerformance(
            corner_id=corner["corner_id"],
            s_start=s_start,
            s_end=s_end,
            s_apex=s_apex,
            direction=corner.get("direction", "?"),
            entry_speed_actual=_mean_speed(s_dr, v_dr, entry_lo, entry_hi),
            entry_speed_theory=_mean_speed(s_th, v_th, entry_lo, entry_hi),
            apex_speed_actual=_mean_speed(s_dr, v_dr, apex_lo, apex_hi),
            apex_speed_theory=_mean_speed(s_th, v_th, apex_lo, apex_hi),
            exit_speed_actual=_mean_speed(s_dr, v_dr, exit_lo, exit_hi),
            exit_speed_theory=_mean_speed(s_th, v_th, exit_lo, exit_hi),
        )

        # Braking point detection
        if has_ax:
            bp_actual = _find_brake_point(s_dr, ax_dr, s_start, threshold=-1.0)
            bp_theory = _find_brake_point(
                s_th, theoretical.accel_profile_mps2, s_start, threshold=-1.0)
            cp.brake_point_actual_m = bp_actual
            cp.brake_point_theory_m = bp_theory
            cp.brake_delta_m = bp_actual - bp_theory  # positive = early

        # Time loss per zone (simplified: dt = ds / v)
        for zone, attr in [
            ((entry_lo, entry_hi), "time_loss_entry_s"),
            ((apex_lo, apex_hi), "time_loss_apex_s"),
            ((exit_lo, exit_hi), "time_loss_exit_s"),
        ]:
            lo_z, hi_z = zone
            dr_t = _integrate_zone(s_dr, v_dr, lo_z, hi_z)
            th_t = _integrate_zone(s_th, v_th, lo_z, hi_z)
            setattr(cp, attr, max(0.0, dr_t - th_t))

        cp.time_loss_total_s = cp.time_loss_entry_s + cp.time_loss_apex_s + cp.time_loss_exit_s

        # Attribute primary cause
        losses = {
            "late_braking": cp.time_loss_entry_s if cp.brake_delta_m > 2 else 0.0,
            "early_braking": cp.time_loss_entry_s if cp.brake_delta_m < -2 else 0.0,
            "low_apex_speed": cp.time_loss_apex_s,
            "slow_exit": cp.time_loss_exit_s,
        }
        if losses:
            cp.primary_cause = max(losses, key=losses.get)
        cp.coaching_hint = _coaching_hint(cp)

        results.append(cp)

    # Tag corners with complex membership
    if complexes:
        cid_to_complex: dict[int, CornerComplex] = {}
        for cx in complexes:
            for cid in cx.corner_ids:
                cid_to_complex[cid] = cx
        for cp in results:
            cx = cid_to_complex.get(cp.corner_id)
            if cx:
                cp.complex_id = cx.complex_id
                cp.corner_type = cx.corner_type

    results.sort(key=lambda c: c.time_loss_total_s, reverse=True)
    return results


def _find_brake_point(
    s: np.ndarray, ax: np.ndarray, corner_entry: float,
    threshold: float = -1.0, search_back_m: float = 50.0,
) -> float:
    """Find the distance at which braking begins before a corner."""
    search_lo = corner_entry - search_back_m
    mask = (s >= search_lo) & (s <= corner_entry) & np.isfinite(ax)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return corner_entry

    # Walk backward from corner entry until ax > threshold
    for i in reversed(idx):
        if ax[i] > threshold:
            return float(s[i])
    return float(s[idx[0]])


def _integrate_zone(s: np.ndarray, v: np.ndarray, lo: float, hi: float) -> float:
    """Integrate time over a zone using trapezoidal rule."""
    mask = (s >= lo) & (s <= hi) & np.isfinite(v) & (v > 0.5)
    s_zone = s[mask]
    v_zone = v[mask]
    if len(s_zone) < 2:
        return 0.0
    ds = np.diff(s_zone)
    v_avg = 0.5 * (v_zone[:-1] + v_zone[1:])
    return float(np.sum(ds / np.maximum(v_avg, 0.5)))


_HINTS = {
    "early_braking": "Brake later — you're losing time before the corner entry.",
    "late_braking": "You're braking too late and arriving too fast, costing corner speed.",
    "low_apex_speed": "Carry more minimum speed through the apex. Try a wider entry or smoother steering.",
    "slow_exit": "Get on the throttle earlier at corner exit. Straighten the wheel before full power.",
}


def _coaching_hint(cp: CornerPerformance) -> str:
    return _HINTS.get(cp.primary_cause, "Review this corner for general improvement.")
