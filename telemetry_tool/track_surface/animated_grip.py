"""
Rolling-window animation frames for the physics grip ceiling.

One frame per lap, each frame computed from a rolling window of laps with
exponential decay weights. Shows grip evolution (rubber buildup, tire
warming, degradation) across a session.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

import numpy as np

from track_surface.physics_grip import propagate_physics_grip

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW: Final[int] = 5
_DEFAULT_DECAY: Final[float] = 0.5


@dataclass
class LapSliceIndex:
    """Contiguous index range for one lap within the global sample arrays."""
    lap_number: int
    start: int
    end: int
    lap_time_s: float


def build_lap_slices(
    lap_arr: np.ndarray,
    valid_mask: np.ndarray,
    time_arr: np.ndarray,
) -> dict[int, LapSliceIndex]:
    """Identify contiguous per-lap slices in the global sample arrays.

    Only valid samples (on_track + no GPS sentinels) count. Assumes
    samples are time-ordered, which iRacing telemetry is.
    """
    slices: dict[int, LapSliceIndex] = {}
    valid_idx = np.where(valid_mask)[0]
    if len(valid_idx) == 0:
        return slices

    lap_at_valid = lap_arr[valid_idx]
    time_at_valid = time_arr[valid_idx]

    # Find runs of identical lap numbers
    change_points = np.concatenate(
        [[0], np.where(np.diff(lap_at_valid) != 0)[0] + 1, [len(lap_at_valid)]]
    )

    for i in range(len(change_points) - 1):
        run_start = change_points[i]
        run_end = change_points[i + 1]
        lap_num = int(lap_at_valid[run_start])
        if lap_num <= 0:
            continue
        t0 = float(time_at_valid[run_start])
        t1 = float(time_at_valid[run_end - 1])
        lap_time = t1 - t0
        if lap_time < 10.0 or run_end - run_start < 500:
            continue
        # If this lap already has a slice, keep the longest
        if lap_num in slices and (slices[lap_num].end - slices[lap_num].start) >= (
            run_end - run_start
        ):
            continue
        slices[lap_num] = LapSliceIndex(
            lap_number=lap_num,
            start=int(valid_idx[run_start]),
            end=int(valid_idx[run_end - 1] + 1),
            lap_time_s=lap_time,
        )
    return slices


def _weighted_percentile_per_cell(
    cell_idx: np.ndarray,
    values: np.ndarray,
    weights: np.ndarray,
    n_cells: int,
    percentile: float,
) -> np.ndarray:
    """Weighted percentile per cell via sort + cumulative-weight crossing.

    Parameters
    ----------
    cell_idx : (N,) int32 — flat cell index for each sample
    values : (N,) float32 — sample value (mu)
    weights : (N,) float32 — sample weight
    n_cells : total number of cells
    percentile : 0..100

    Returns
    -------
    (n_cells,) array with NaN where no samples exist.
    """
    if len(values) == 0:
        return np.full(n_cells, np.nan, dtype=np.float32)

    # Sort by (cell, value) so each cell's samples are in ascending value order
    order = np.lexsort((values, cell_idx))
    sorted_cell = cell_idx[order]
    sorted_val = values[order]
    sorted_w = weights[order]

    # Find run boundaries
    starts = np.searchsorted(sorted_cell, np.arange(n_cells), side="left")
    ends = np.searchsorted(sorted_cell, np.arange(n_cells), side="right")

    out = np.full(n_cells, np.nan, dtype=np.float32)
    p_frac = percentile / 100.0

    for c in range(n_cells):
        a, b = starts[c], ends[c]
        if b - a < 2:
            continue
        w = sorted_w[a:b]
        v = sorted_val[a:b]
        csum = np.cumsum(w)
        target = float(csum[-1]) * p_frac
        k = int(np.searchsorted(csum, target))
        if k >= len(v):
            k = len(v) - 1
        out[c] = v[k]

    return out


def build_animation_frames(
    *,
    lap_slices: dict[int, LapSliceIndex],
    s_proj: np.ndarray,
    n_proj: np.ndarray,
    mu_per_wheel: np.ndarray,
    a_body_mag: np.ndarray,
    g_eff: np.ndarray,
    s_bins: np.ndarray,
    n_bins: np.ndarray,
    window_laps: int = _DEFAULT_WINDOW,
    decay: float = _DEFAULT_DECAY,
    util_threshold: float = 0.55,
    percentile: float = 95.0,
    downsample_s: int = 1,
    downsample_n: int = 1,
) -> tuple[np.ndarray, list[int], list[float]]:
    """Build one frame per lap using a rolling window of prior laps.

    Frame for lap L uses all samples from laps in [L-window+1, L], each
    sample weighted by its lap's position in the window:

        w[i] = decay + (1 - decay) × i / (W - 1)

    For W=5, decay=0.5  →  [0.5, 0.625, 0.75, 0.875, 1.0]
    The most recent lap gets weight 1.0, oldest gets 0.5.

    Returns
    -------
    (frames, lap_numbers, lap_times)
        frames: (F, M, K) float32
        lap_numbers: list of lap numbers in frame order
        lap_times: list of lap times in frame order
    """
    M_full = len(s_bins) - 1
    K_full = len(n_bins) - 1

    # Downsample the grid (take every Nth bin) for animation-size fit
    if downsample_s > 1:
        s_bins_anim = s_bins[::downsample_s]
    else:
        s_bins_anim = s_bins
    if downsample_n > 1:
        n_bins_anim = n_bins[::downsample_n]
    else:
        n_bins_anim = n_bins
    M = len(s_bins_anim) - 1
    K = len(n_bins_anim) - 1

    sorted_laps = sorted(lap_slices.keys())
    F = len(sorted_laps)
    frames = np.full((F, M, K), np.nan, dtype=np.float32)
    lap_numbers: list[int] = []
    lap_times: list[float] = []

    # Precompute per-sample max-wheel μ and util
    mu_max_all = np.nanmax(mu_per_wheel, axis=1)  # (N,)
    util_all = a_body_mag / np.maximum(g_eff, 1.0)
    keep_all = (util_all > util_threshold) & np.isfinite(mu_max_all)

    # Precompute cell indices on the (possibly downsampled) grid
    s_idx_all = np.clip(
        np.searchsorted(s_bins_anim, s_proj) - 1, 0, M - 1
    ).astype(np.int32)
    n_idx_all = np.clip(
        np.searchsorted(n_bins_anim, n_proj) - 1, 0, K - 1
    ).astype(np.int32)
    flat_idx_all = s_idx_all * K + n_idx_all

    for f_idx, target_lap in enumerate(sorted_laps):
        # Determine laps in the window
        window = [
            l for l in sorted_laps
            if target_lap - (window_laps - 1) <= l <= target_lap
        ]
        w_count = len(window)
        if w_count == 0:
            continue

        weights_by_lap = [
            decay + (1 - decay) * (i / max(w_count - 1, 1))
            for i in range(w_count)
        ]

        # Collect samples from the window
        sample_indices = []
        sample_weights = []
        for wi, lnum in enumerate(window):
            sl = lap_slices[lnum]
            # Apply the global keep mask within this lap's slice
            lap_slice_keep = keep_all[sl.start : sl.end]
            abs_idx = np.arange(sl.start, sl.end)[lap_slice_keep]
            sample_indices.append(abs_idx)
            sample_weights.append(np.full(len(abs_idx), weights_by_lap[wi]))

        if not sample_indices:
            continue
        sample_idx = np.concatenate(sample_indices)
        sample_w = np.concatenate(sample_weights).astype(np.float32)

        if len(sample_idx) < 10:
            continue

        cell_ids = flat_idx_all[sample_idx]
        mu_vals = mu_max_all[sample_idx].astype(np.float32)

        grid_flat = _weighted_percentile_per_cell(
            cell_ids, mu_vals, sample_w, M * K, percentile
        )
        frame = grid_flat.reshape(M, K)

        # Propagate empty cells
        frame_filled = propagate_physics_grip(frame, iterations=2)
        frames[f_idx] = frame_filled

        lap_numbers.append(target_lap)
        lap_times.append(lap_slices[target_lap].lap_time_s)

    return frames, lap_numbers, lap_times
