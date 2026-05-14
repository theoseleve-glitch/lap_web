"""
track_surface/corridor_filter.py
--------------------------------
RC2: reject off-track / off-corridor samples before boundary estimation
and downstream grip statistics.

Two precedence-ordered paths:

  gt-polygon mask
    When a hand-traced gt is available for the track, build a polygon
    from (gt LEFT polyline forward) ∪ (gt RIGHT polyline reverse),
    inflate by ``gt_inflation_m`` (default 1 m), and accept any sample
    that lies inside. Inflation handles the joint of gt polyline
    spacing + driver-line jitter near gt edges. The D3 lock (S1
    OK tail is real geometry) is honoured by construction: the gt
    polygon includes the tail, so the inflated polygon does too.

  per-s-bin MAD fallback
    When gt is absent, treat the lap samples themselves as the
    corridor. Project samples to Frenet (s, n), bin by s, compute
    median + MAD of n per bin, and reject samples with
    |n_i - median(bin)| > mad_threshold * MAD(bin). Robust to
    individual GPS-multipath spikes; tolerates moderate driver-line
    spread. Default threshold 5 * MAD ≈ 4.4 sigma of normal data.

Public API
~~~~~~~~~~

``filter_samples_in_corridor(sample_xy, frenet, gt_left_xy=None,
                              gt_right_xy=None, mad_threshold=5.0,
                              gt_inflation_m=1.0)``
    → ``(kept_mask, metadata)``

``kept_mask`` is a boolean numpy array of length ``len(sample_xy)``;
``metadata`` is a dict with method used, rejection counts, and a brief
reason string for downstream logging.
"""
from __future__ import annotations

import logging

import numpy as np

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

# Per-s-bin width for the MAD fallback; matches the ds=0.5 m grid used
# by build_track_surface so each bin holds ~N_laps samples on average.
_MAD_BIN_M = 2.0
# Minimum samples per bin before MAD is computed (else keep all samples
# in that bin).
_MAD_MIN_SAMPLES_PER_BIN = 5


def _gt_polygon_mask(
    sample_xy: np.ndarray,
    gt_left_xy: np.ndarray,
    gt_right_xy: np.ndarray,
    inflation_m: float,
) -> tuple[np.ndarray, str]:
    """Build the gt corridor polygon (left ∪ right reversed), inflate by
    ``inflation_m``, return per-sample inside-or-not mask.
    """
    try:
        from shapely.geometry import Point, Polygon
        from shapely.prepared import prep
    except ImportError as exc:
        raise RuntimeError(
            "filter_samples_in_corridor gt_mask path requires shapely"
        ) from exc

    if gt_left_xy.shape[0] < 2 or gt_right_xy.shape[0] < 2:
        return np.zeros(len(sample_xy), dtype=bool), "gt_polylines_too_short"

    # Polygon = gt LEFT forward + gt RIGHT reversed, closed.
    # The reversal makes the polygon trace continuously around the
    # corridor; if gt LEFT and gt RIGHT happen to be in opposite
    # orientations relative to each other, this still produces a valid
    # ring (shapely will normalise winding).
    ring = np.vstack([gt_left_xy, gt_right_xy[::-1]])
    polygon = Polygon(ring)

    if not polygon.is_valid:
        # Self-intersection or other validity issue → buffer(0) trick
        # commonly cleans these up
        polygon = polygon.buffer(0)
    if polygon.is_empty:
        return np.zeros(len(sample_xy), dtype=bool), "gt_polygon_empty"

    if inflation_m > 0:
        polygon = polygon.buffer(inflation_m, resolution=4)

    prepared = prep(polygon)
    mask = np.array([prepared.contains(Point(x, y)) for x, y in sample_xy])
    return mask, ""


def _mad_mask(
    sample_xy: np.ndarray,
    frenet: FrenetFrame,
    threshold: float,
) -> tuple[np.ndarray, str]:
    """Two-pass MAD rejection. Pass 1 filters samples whose |n| is far
    from the global |n| MAD floor (catches dense outlier clusters that
    would otherwise dominate their own s-bin). Pass 2 does per-s-bin
    MAD on the survivors.

    Per-bin MAD alone is robust to *sparse* outliers but breaks when a
    cluster of off-track samples fully dominates an s-bin (their median
    becomes the off-track centroid and MAD collapses). The global
    pre-filter catches those.
    """
    s_arr, n_arr = frenet.xy_to_sn(sample_xy[:, 0], sample_xy[:, 1])
    L = float(frenet.total_length_m)

    # Pass 1 — global |n| pre-filter. Use the global median + MAD of |n|
    # as a coarse corridor estimate; reject samples with |n - median| >
    # a generous multiple. The multiplier is intentionally loose (10×)
    # because real driver-line spread can be 3-4 sigma on its own, and
    # Pass 2's per-bin MAD does the precise work. Pass 1 only needs to
    # catch dense off-track clusters (typically ≥15m off centerline),
    # so a ±10m floor around the median |n| is plenty.
    abs_n = np.abs(n_arr)
    global_median = float(np.median(abs_n))
    global_mad = float(np.median(np.abs(abs_n - global_median)))
    global_threshold = 10.0 * max(global_mad, 1.0)  # at least ±10 m around median
    global_mask = abs_n <= (global_median + global_threshold)

    # Pass 2 — per-s-bin MAD on the survivors.
    n_bins = max(int(np.ceil(L / _MAD_BIN_M)), 1)
    s_wrap = np.mod(s_arr, L) if L > 0 else s_arr
    bin_idx = np.clip(
        (s_wrap / max(L, 1e-9) * n_bins).astype(int), 0, n_bins - 1,
    )

    mask = global_mask.copy()
    # MAD floor: on bins where the racing line is highly consistent
    # (tight apex, fast corners), MAD can collapse to ~0.1m, making
    # threshold*MAD < 1m and over-rejecting legitimate driver variation.
    # Floor at 0.5m → minimum per-bin half-width of threshold*0.5 m
    # (2.5m for the default threshold=5.0). Below this scale, the
    # racing-line variation is just noise we shouldn't be filtering.
    _MAD_FLOOR_M = 0.5
    for b in range(n_bins):
        sel = (bin_idx == b) & global_mask  # only use Pass-1 survivors
        if int(sel.sum()) < _MAD_MIN_SAMPLES_PER_BIN:
            continue
        n_in_bin = n_arr[sel]
        median_n = float(np.median(n_in_bin))
        mad = max(float(np.median(np.abs(n_in_bin - median_n))), _MAD_FLOOR_M)
        bin_mask = np.abs(n_in_bin - median_n) <= threshold * mad
        global_idx = np.flatnonzero(sel)
        mask[global_idx] = mask[global_idx] & bin_mask
    return mask, ""


def filter_samples_in_corridor(
    sample_xy: np.ndarray,
    frenet: FrenetFrame,
    gt_left_xy: np.ndarray | None = None,
    gt_right_xy: np.ndarray | None = None,
    mad_threshold: float = 5.0,
    gt_inflation_m: float = 1.0,
) -> tuple[np.ndarray, dict]:
    """Reject off-corridor samples.

    Precedence:
      1. If gt polylines supplied → gt-polygon-mask path (inflate by 1 m)
      2. Else → per-s-bin MAD rejection (threshold * MAD)

    Parameters
    ----------
    sample_xy : (N, 2) float array of sample positions in the local XY
        frame matching ``frenet``'s centerline.
    frenet : FrenetFrame for the current centerline (used by both paths;
        MAD requires it for s-binning, gt path uses it indirectly through
        the polygon ring).
    gt_left_xy, gt_right_xy : optional gt LEFT / RIGHT polylines in the
        same XY frame. Both must be provided to enable the gt-mask path.
    mad_threshold : multiplier on the per-bin MAD for the fallback path
        (default 5.0; with normal data, |z| ≤ 5 * MAD captures > 99.97 %).
    gt_inflation_m : metres to inflate the gt polygon outward before
        testing (default 1 m).

    Returns
    -------
    (kept_mask, metadata) where:
        kept_mask : boolean array of len(sample_xy); True = kept
        metadata  : {
            "method": "gt_mask" | "mad" | "empty" | "gt_failed_fallback_mad",
            "n_total": int,
            "n_kept": int,
            "n_rejected": int,
            "reject_pct": float,
            "reason": str,
        }
    """
    n_total = len(sample_xy)
    if n_total == 0:
        return np.zeros(0, dtype=bool), {
            "method": "empty", "n_total": 0, "n_kept": 0,
            "n_rejected": 0, "reject_pct": 0.0, "reason": "empty input",
        }

    method: str
    reason = ""
    if gt_left_xy is not None and gt_right_xy is not None:
        mask, reason = _gt_polygon_mask(
            sample_xy, gt_left_xy, gt_right_xy, gt_inflation_m,
        )
        if reason and not mask.any():
            # gt construction failed and rejected everything — fall back
            # to MAD so we don't return an empty corridor.
            mask, _ = _mad_mask(sample_xy, frenet, mad_threshold)
            method = "gt_failed_fallback_mad"
        else:
            method = "gt_mask"
    else:
        mask, reason = _mad_mask(sample_xy, frenet, mad_threshold)
        method = "mad"

    n_kept = int(mask.sum())
    n_rejected = n_total - n_kept
    reject_pct = 100.0 * n_rejected / max(n_total, 1)

    logger.info(
        "corridor_filter (%s): kept %d / %d samples (rejected %.1f%%)%s",
        method, n_kept, n_total, reject_pct,
        f" — {reason}" if reason else "",
    )

    return mask, {
        "method": method,
        "n_total": n_total,
        "n_kept": n_kept,
        "n_rejected": n_rejected,
        "reject_pct": reject_pct,
        "reason": reason,
    }
