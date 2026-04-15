"""
track_surface/line_delta.py
---------------------------
2D line delta: compare a driver's actual trajectory against the optimal
racing line, decomposing time loss into line and speed components.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)


@dataclass
class LineDelta:
    """Per-point comparison of actual vs optimal racing line."""
    distance_m: np.ndarray           # (N,) s-grid
    actual_n: np.ndarray             # (N,) actual lateral offset [m]
    optimal_n: np.ndarray            # (N,) optimal lateral offset [m]
    delta_n: np.ndarray              # (N,) actual - optimal [m]
    actual_speed: np.ndarray         # (N,) [m/s]
    optimal_speed: np.ndarray        # (N,) [m/s]
    delta_speed: np.ndarray          # (N,) [m/s]
    cumulative_time_delta: np.ndarray  # (N,) cumulative time difference [s]

    @property
    def total_time_loss_s(self) -> float:
        return float(self.cumulative_time_delta[-1]) if len(self.cumulative_time_delta) > 0 else 0.0

    def to_dict(self) -> dict:
        def _r(arr):
            return [round(float(v), 3) for v in arr]
        return {
            "distance_m": _r(self.distance_m),
            "actual_n": _r(self.actual_n),
            "optimal_n": _r(self.optimal_n),
            "delta_n": _r(self.delta_n),
            "actual_speed_mps": _r(self.actual_speed),
            "optimal_speed_mps": _r(self.optimal_speed),
            "delta_speed_mps": _r(self.delta_speed),
            "cumulative_time_delta_s": _r(self.cumulative_time_delta),
            "total_time_loss_s": round(self.total_time_loss_s, 3),
        }


@dataclass
class CornerLineLoss:
    """Time loss decomposition for a single corner."""
    corner_id: int
    s_start: float
    s_end: float
    total_loss_s: float
    line_loss_s: float           # time lost from wrong position
    speed_loss_s: float          # time lost from wrong speed
    apex_error_m: float          # actual apex n - optimal apex n
    entry_error_m: float
    exit_error_m: float
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "s_start": round(self.s_start, 1),
            "s_end": round(self.s_end, 1),
            "total_loss_s": round(self.total_loss_s, 3),
            "line_loss_s": round(self.line_loss_s, 3),
            "speed_loss_s": round(self.speed_loss_s, 3),
            "apex_error_m": round(self.apex_error_m, 2),
            "entry_error_m": round(self.entry_error_m, 2),
            "exit_error_m": round(self.exit_error_m, 2),
            "suggestion": self.suggestion,
        }


def compute_line_delta(
    frenet: FrenetFrame,
    actual_df: pd.DataFrame,
    optimal_distance_m: np.ndarray,
    optimal_speed_mps: np.ndarray,
    optimal_lateral_m: np.ndarray,
) -> LineDelta:
    """Project actual lap to Frenet and compare against optimal.

    Parameters
    ----------
    frenet : FrenetFrame for coordinate projection.
    actual_df : DataFrame with x_m, y_m, speed_mps columns.
    optimal_distance_m : distance grid from OCP solution.
    optimal_speed_mps : optimal speed profile.
    optimal_lateral_m : optimal lateral offset (N_lat from OCP).

    Returns
    -------
    LineDelta with per-metre comparison.
    """
    # Project actual positions to Frenet frame along the optimal line.
    x = actual_df["x_m"].to_numpy()
    y = actual_df["y_m"].to_numpy()
    actual_s, actual_n = frenet.xy_to_sn(x, y)
    actual_speed = actual_df["speed_mps"].to_numpy()

    # Resample the actual trajectory onto the optimal s-grid.
    actual_n_resampled = np.interp(optimal_distance_m, actual_s, actual_n)
    actual_speed_resampled = np.interp(optimal_distance_m, actual_s, actual_speed)

    delta_n = actual_n_resampled - optimal_lateral_m
    delta_speed = actual_speed_resampled - optimal_speed_mps

    # Canonical cumulative-delta engine: trapezoidal, NaN-safe, no forward-
    # fill. Sign convention: positive delta ⇒ B (actual) slower than A
    # (optimal) — which matches "time lost" for this comparison.
    from telemetry_tool.deltas import cumulative_delta
    result = cumulative_delta(
        progress_a=optimal_distance_m,
        speed_a=optimal_speed_mps,
        progress_b=optimal_distance_m,          # resampled onto same grid
        speed_b=actual_speed_resampled,
        n_grid=len(optimal_distance_m),
        anchor_to_official=False,
    )
    # The canonical function returns its own 0-based grid (same length as
    # optimal_distance_m since we passed the same grid spacing). Use the
    # optimal grid for the LineDelta fields.
    cumulative = result.delta_s

    return LineDelta(
        distance_m=optimal_distance_m,
        actual_n=actual_n_resampled,
        optimal_n=optimal_lateral_m,
        delta_n=delta_n,
        actual_speed=actual_speed_resampled,
        optimal_speed=optimal_speed_mps,
        delta_speed=delta_speed,
        cumulative_time_delta=cumulative,
    )


def decompose_corner_losses(
    line_delta: LineDelta,
    corners: list[dict],
    frenet: FrenetFrame,
) -> list[CornerLineLoss]:
    """Decompose time loss per corner into line and speed components.

    For each corner (s_start, s_end):
    - Total loss = cumulative time delta over the corner segment
    - Speed component = time lost assuming actual line but wrong speed
    - Line component = total - speed

    Parameters
    ----------
    line_delta : LineDelta from compute_line_delta().
    corners : list of corner dicts with s_start, s_end, s_apex, corner_id.
    frenet : FrenetFrame for curvature lookup.

    Returns
    -------
    List of CornerLineLoss, one per corner.
    """
    losses = []

    for corner in corners:
        cid = corner.get("corner_id", 0)
        s_start = corner.get("s_start", 0.0)
        s_end = corner.get("s_end", 0.0)
        s_apex = corner.get("s_apex", (s_start + s_end) / 2.0)

        # Segment mask
        mask = (line_delta.distance_m >= s_start) & (line_delta.distance_m <= s_end)
        if mask.sum() < 2:
            continue

        seg_dist = line_delta.distance_m[mask]
        seg_actual_speed = line_delta.actual_speed[mask]
        seg_optimal_speed = line_delta.optimal_speed[mask]
        seg_delta_n = line_delta.delta_n[mask]

        ds = np.diff(seg_dist, prepend=seg_dist[0])
        ds[0] = ds[1] if len(ds) > 1 else 1.0

        # Total time loss in this corner
        v_a = np.maximum(seg_actual_speed, 1.0)
        v_o = np.maximum(seg_optimal_speed, 1.0)
        total_loss = float(np.sum(ds / v_a - ds / v_o))

        # Speed component: difference due to speed alone
        # (approximate: how much time is lost from speed deficit)
        speed_loss = max(0.0, total_loss * 0.5)  # heuristic split initially

        # Better decomposition: use effective curvature difference
        # to estimate how much speed the wrong line costs
        kappa_actual = frenet.effective_curvature(
            seg_dist, line_delta.actual_n[mask])
        kappa_optimal = frenet.effective_curvature(
            seg_dist, line_delta.optimal_n[mask])

        # Curvature ratio: tighter line = lower max speed
        kappa_ratio = np.abs(kappa_actual) / np.maximum(np.abs(kappa_optimal), 0.001)
        # Approximate speed reduction from curvature: v_max ~ sqrt(1/kappa)
        # so speed ratio ≈ sqrt(kappa_opt / kappa_actual)
        speed_from_line = np.mean(np.sqrt(1.0 / np.maximum(kappa_ratio, 0.1))) - 1.0
        line_fraction = np.clip(abs(speed_from_line) * 5.0, 0.0, 0.9)
        line_loss = total_loss * line_fraction
        speed_loss = total_loss - line_loss

        # Lateral errors at key points
        apex_idx = np.argmin(np.abs(seg_dist - s_apex))
        entry_idx = 0
        exit_idx = -1

        apex_error = float(seg_delta_n[apex_idx])
        entry_error = float(seg_delta_n[entry_idx])
        exit_error = float(seg_delta_n[exit_idx])

        losses.append(CornerLineLoss(
            corner_id=cid,
            s_start=s_start,
            s_end=s_end,
            total_loss_s=total_loss,
            line_loss_s=line_loss,
            speed_loss_s=speed_loss,
            apex_error_m=apex_error,
            entry_error_m=entry_error,
            exit_error_m=exit_error,
        ))

    return losses
