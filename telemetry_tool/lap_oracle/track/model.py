"""Track model construction from raw position data.

Builds a :class:`TrackModel` from an (N, 2) centerline array and provides
resampling to a uniform distance grid.
"""
from __future__ import annotations

import logging

import numpy as np

from telemetry_tool.lap_oracle.config import TrackModel

logger = logging.getLogger(__name__)


def build_from_xy(
    xy: np.ndarray,
    *,
    width: float = 5.0,
    name: str = "",
    sim: str = "",
) -> TrackModel:
    """Construct a :class:`TrackModel` from an (N, 2) centerline array.

    Parameters
    ----------
    xy:
        Shape ``(N, 2)`` array of x/y centerline coordinates.  Must have
        at least 10 points.
    width:
        Uniform half-width applied to both left and right track edges.
    name:
        Human-readable track name.
    sim:
        Simulator identifier (e.g. ``"ac"``, ``"iracing"``).

    Returns
    -------
    TrackModel
        Fully populated track model with curvature, elevation (zeros),
        banking (zeros), and grip_map (ones).

    Raises
    ------
    ValueError
        If *xy* has fewer than 10 points.
    """
    xy = np.asarray(xy, dtype=np.float64)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError(f"Expected (N, 2) array, got shape {xy.shape}")
    n = xy.shape[0]
    if n < 10:
        raise ValueError(
            f"Need at least 10 centerline points, got {n}"
        )

    # -- Curvature via finite differences --------------------------------
    x, y = xy[:, 0], xy[:, 1]
    dx = np.gradient(x)
    dy = np.gradient(y)
    ddx = np.gradient(dx)
    ddy = np.gradient(dy)

    denom = (dx ** 2 + dy ** 2) ** 1.5
    # Guard against zero-length segments
    denom = np.where(denom < 1e-12, 1e-12, denom)
    kappa = (dx * ddy - dy * ddx) / denom

    # -- Cumulative arc length -------------------------------------------
    diffs = np.diff(xy, axis=0)
    seg_lengths = np.sqrt((diffs ** 2).sum(axis=1))
    total_length = float(seg_lengths.sum())

    return TrackModel(
        name=name,
        sim=sim,
        centerline_xy=xy.copy(),
        width_left=np.full(n, width, dtype=np.float64),
        width_right=np.full(n, width, dtype=np.float64),
        curvature=kappa,
        elevation=np.zeros(n, dtype=np.float64),
        banking=np.zeros(n, dtype=np.float64),
        grip_map=np.ones(n, dtype=np.float64),
        total_length_m=total_length,
    )


def resample_track(
    tm: TrackModel,
    ds_target: float = 1.0,
) -> TrackModel:
    """Resample *tm* onto a uniform distance grid.

    Parameters
    ----------
    tm:
        Source track model (any spacing).
    ds_target:
        Target spacing in metres between consecutive points.

    Returns
    -------
    TrackModel
        New track model with approximately uniform spacing.
    """
    if tm.n_points < 2:
        logger.warning("Cannot resample track with fewer than 2 points")
        return tm

    xy = tm.centerline_xy
    diffs = np.diff(xy, axis=0)
    seg_lengths = np.sqrt((diffs ** 2).sum(axis=1))
    cum_dist = np.concatenate(([0.0], np.cumsum(seg_lengths)))
    total = cum_dist[-1]

    if total < ds_target:
        logger.warning(
            "Track total length (%.1f m) shorter than ds_target (%.1f m)",
            total,
            ds_target,
        )
        return tm

    s_new = np.arange(0.0, total, ds_target)
    x_new = np.interp(s_new, cum_dist, xy[:, 0])
    y_new = np.interp(s_new, cum_dist, xy[:, 1])

    xy_new = np.column_stack((x_new, y_new))
    return build_from_xy(
        xy_new,
        width=float(tm.width_left[0]) if tm.width_left.size else 5.0,
        name=tm.name,
        sim=tm.sim,
    )
