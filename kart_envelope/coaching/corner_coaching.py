"""
corner_coaching.py
------------------
Corner-level performance attribution: for each corner, compute entry /
apex / exit speed deltas versus theoretical and identify the primary
cause of time loss.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.ingest.columns import COL_ACCEL_LONG, COL_DIST, COL_SPEED
from kart_envelope.solver.min_time import TheoreticalResult

logger = logging.getLogger(__name__)


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

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


def detect_corners_from_curvature(
    kappa: np.ndarray,
    distance: np.ndarray,
    threshold: float = 0.01,
    min_length_m: float = 10.0,
    merge_gap_m: float = 15.0,
) -> list[dict]:
    """Detect corners from the curvature profile.

    Returns list of ``{corner_id, s_start, s_end, s_apex, direction}``.
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
                corners.append({
                    "corner_id": corner_id,
                    "s_start": s_start,
                    "s_end": s_end,
                    "s_apex": float(distance[apex_idx]),
                    "idx_start": start,
                    "idx_end": end,
                    "idx_apex": apex_idx,
                    "direction": "L",  # placeholder; needs signed curvature
                })
        else:
            i += 1

    # Merge close corners
    merged: list[dict] = []
    for c in corners:
        if merged and (c["s_start"] - merged[-1]["s_end"]) < merge_gap_m:
            prev = merged[-1]
            prev["s_end"] = c["s_end"]
            prev["idx_end"] = c["idx_end"]
            # New apex = highest curvature in merged range
            combined_kappa = kappa[prev["idx_start"]:c["idx_end"] + 1]
            rel_apex = int(np.argmax(combined_kappa))
            prev["idx_apex"] = prev["idx_start"] + rel_apex
            prev["s_apex"] = float(distance[prev["idx_apex"]])
        else:
            merged.append(c)

    # Re-number
    for i, c in enumerate(merged):
        c["corner_id"] = i + 1

    return merged


def analyze_corner_performance(
    driver_lap: pd.DataFrame,
    theoretical: TheoreticalResult,
    corners: list[dict],
) -> list[CornerPerformance]:
    """Compute per-corner performance breakdown.

    Parameters
    ----------
    driver_lap : pd.DataFrame
        Resampled driver lap with canonical columns.
    theoretical : TheoreticalResult
    corners : list[dict]
        Output of ``detect_corners_from_curvature``.

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
