"""
track_surface/boundary.py
-------------------------
Track boundary estimation. Two paths:

  - hand_traced: project gt_*.geojson polylines (WGS84) to centerline Frenet
    (s, n) and return per-s-bin signed offsets. Preferred when available.
    Day 4b empirical baseline: mean 3.36m gap vs hand-traced on KCT when
    using only the data_derived path; hand_traced closes this gap.

  - data_derived: percentile-99 × 1.3 margin of lateral scatter across laps.
    Falls back when no gt exists for the track. Defaults 3m left + 3m right
    when < min_laps or < 5 samples/bin.

estimate_boundaries() is the 2-tuple back-compat entry point; new code should
prefer estimate_boundaries_with_source() which also reports which path was
taken via a 'hand_traced' | 'data_derived' source string for the
TrackSurface.boundary_source field.
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from track_surface.frenet import FrenetFrame
from track_surface.gt_loader import GroundTruth, load_gt, resolve_track_id

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M: Final[float] = 6_371_000.0
_DEFAULT_PERCENTILE: Final[float] = 99.0
_SMOOTH_SIGMA_BINS: Final[int] = 5
_GT_SMOOTH_SIGMA_BINS: Final[int] = 2  # ~1m at ds=0.5m — gentler than data_derived

# Hand-traced width sanity thresholds — logged, not enforced (gt is trusted).
_GT_WIDTH_MIN_M: Final[float] = 2.0
_GT_WIDTH_MAX_M: Final[float] = 20.0


def _smooth_1d(arr: np.ndarray, sigma: int, *, closed: bool = True) -> np.ndarray:
    """Gaussian smooth a 1D array.

    closed=True (default) uses wrap padding — width arrays are indexed by
    the closed-loop centerline s_grid, and reflect padding produces a step
    at the seam (width[0] != width[-1] even though they're at the same
    physical location). Day-9.5 hot-patch — same pattern as
    centerline._gaussian_smooth_xy and elevation._smooth_1d.
    """
    if sigma <= 0:
        return arr.copy()
    hw = 3 * sigma
    kernel = np.exp(-0.5 * (np.arange(-hw, hw + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(arr, hw, mode="wrap" if closed else "reflect")
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


# ---------------------------------------------------------------------------
# Hand-traced (gt) path
# ---------------------------------------------------------------------------


def _gt_project_to_xy(
    polyline: list[tuple[float, float]],
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> np.ndarray:
    """Equirectangular: WGS84 (lon, lat) → local XY in metres.

    Matches the convention used in
    telemetry_tool.track_surface.normalizer._gps_to_local_enu so that
    projected gt points share a reference frame with the centerline_xy
    that build_track_surface produces (modulo the O(1m) residual from
    per-lap-mean centering in normalize_positions; documented in
    build_track_surface).
    """
    if not polyline:
        return np.empty((0, 2), dtype=float)
    arr = np.asarray(polyline, dtype=float)  # shape (N, 2): [lon, lat]
    lon_r = np.deg2rad(arr[:, 0])
    lat_r = np.deg2rad(arr[:, 1])
    x = _EARTH_RADIUS_M * (lon_r - lon_ref_rad) * np.cos(lat_ref_rad)
    y = _EARTH_RADIUS_M * (lat_r - lat_ref_rad)
    return np.column_stack([x, y])


_GT_COVERAGE_GAP_THRESHOLD_M: Final[float] = 10.0
"""If the polyline's projected-s coverage has a contiguous gap larger
than this (cyclic), centerline bins in the gap are flagged and their
signed_n is replaced by a smooth bridge from the boundary's INTERIOR
signed_n values on either side of the gap (avoiding the polyline
endpoint artifacts where signed_n collapses toward zero)."""

_GT_GAP_EDGE_GUARD_M: Final[float] = 5.0
"""When bridging a coverage gap, take the boundary value from this many
metres INSIDE the non-gap region. Avoids using the polyline-endpoint
signed_n values (which are typically anomalously small because hand-
traced polylines often end right next to the centerline at the seam)."""

_GT_DOMINANT_SIDE_FLOOR_M: Final[float] = 0.3
"""Day-10.5 F1 — dominant-side minimum-offset floor.

A polyline projection bin is flagged as "broken-down" (and bridged like
a coverage-gap bin) when its dominant-side signed offset is less than
this threshold. That is, the bin satisfies::

    signed_offsets[i] * dominant_sign < _GT_DOMINANT_SIDE_FLOOR_M

which catches BOTH wrong-sign bins (their dominant-side projection is
negative) AND near-zero bins on the correct side (their dominant-side
projection is small).

Empirical motivation (OK_R1 apex at s=228m): a centerline that runs
slightly off-track at a tight apex (the lap-set's racing lines vary
widely there) causes the gt polyline projection's signed_n to flip
sign through zero. ``np.interp`` then linearly bridges across the
crossings, leaving signed_n collapsed near zero across a 25 m run.
The downstream polygon assembly self-intersects because the boundary
curve folds back on itself at the high-curvature apex.

Threshold 0.3 m: below this on the dominant side, the bin is considered
projection-broken and gets bridged. This is well clear of any
legitimate narrow-track-edge value (real kart hairpins observed at
≥ 4 m total width = ≥ 2 m per side; KCT and OK never legitimately have
gt-polyline-to-centerline distance below 1 m on the dominant side of
either polyline)."""

_GT_OFFSET_CURVE_SAFETY_ALPHA: Final[float] = 0.5
"""Day-10.5 F1 — offset-curve safety factor.

The offset curve of a centerline at distance d on the INSIDE of a bend
(where ``signed_n * kappa > 0``) self-intersects when ``d > 1 / |kappa|``
— the boundary crosses past the curvature centre and folds back.
On OK_R1 at bin 450 the centerline has |kappa| = 0.163 /m (radius 6 m)
while the gt LEFT polyline projects to signed_n = -9.97 m on the
inside; that's |kappa * signed_n| = 1.63 — the polygon's LEFT
linestring loops around (52.3, -22.8) and shapely.is_simple() fails.

We clip signed_offsets on the inside side to keep ``|signed_n * kappa|
≤ alpha`` per bin. Choosing alpha < 1 guarantees the offset curve
stays simple in isolation, but the *transition* between clipped and
un-clipped bins also matters: a sharp step at the clip boundary can
itself produce a self-intersection a few bins downstream.

Empirical tuning on OK_R1: alpha = 0.85 fixed the kappa-peak fold but
left a step at the clip boundary that produced a new self-intersection
elsewhere. alpha = 0.5 widens the clip region enough that the transition
to un-clipped neighbours is gradual, and the polygon stays simple.
KCT_R1 and OK_R4 are unaffected: their inside-side gt offsets are well
below ``alpha / |kappa|`` everywhere, so the clip never fires."""


def _detect_coverage_gap(
    s_projected: np.ndarray, L: float, threshold_m: float,
) -> tuple[float, float] | None:
    """Find the largest contiguous gap in cyclic-s coverage.
    Returns (gap_start_s, gap_end_s) — bins in the gap satisfy
    s_grid ∈ (gap_start_s, gap_end_s) modulo L. gap_end_s may exceed L
    when the gap spans the seam. Returns None if the largest gap is
    smaller than threshold_m.
    """
    if len(s_projected) < 2 or L <= 0:
        return None
    s_sorted = np.sort(s_projected % L)
    diffs = np.diff(s_sorted)
    seam_gap = L - (s_sorted[-1] - s_sorted[0])
    all_gaps = np.concatenate([diffs, [seam_gap]])
    if float(all_gaps.max()) < threshold_m:
        return None
    biggest = int(np.argmax(all_gaps))
    if biggest < len(diffs):
        return float(s_sorted[biggest]), float(s_sorted[biggest + 1])
    # Seam gap
    return float(s_sorted[-1]), float(s_sorted[0] + L)


def _gt_boundary_signed_offsets(
    frenet: FrenetFrame,
    gt_xy: np.ndarray,
    side: str,
) -> np.ndarray:
    """Per-centerline-s signed Frenet offset of a gt boundary polyline.

    Algorithm (Day-8.5 replacement for the Day-5 sort-by-s + np.interp +
    tile-3-wrap path):

      1. Project each polyline point to centerline (s, n). Sort by s
         and tile [s-L, s, s+L] for cyclic interpolation.
      2. Use np.interp to map onto the centerline s-grid. For bins where
         the polyline has data nearby, this gives the correct signed_n.
      3. Detect the largest cyclic gap in projected-s coverage. If > 10
         m, the polyline didn't fully close around the track — most
         common cause: the human tracing tool's start/end points are
         physically close but landed on the same side of the centerline
         seam, leaving a section uncovered.
      4. In the gap region, OVERRIDE the np.interp output (which would
         have linearly bridged from one polyline endpoint's signed_n to
         the other — both typically anomalously small, since polyline
         endpoints tend to land right next to the centerline at the
         seam). Replace with a smooth bridge from the boundary's
         INTERIOR signed_n values _GT_GAP_EDGE_GUARD_M inside each
         non-gap edge. This uses the boundary's representative signed_n
         (5 m back from the gap edge) rather than the endpoint artifact.
      5. Gaussian smooth with the standard kernel.

    Empirical findings that motivated this design (gt_circuit-d-essay
    + Day-7 centerline):

      - gt RIGHT polyline projects to s ∈ [62.7, 1201.7] of a 1203m
        centerline — 64m coverage gap at the seam, where the human
        tracer drew up to xy=(+47, +101) and resumed at xy=(-17.8,
        +98.9) without tracing the 65m straight between them.
      - The naive linear bridge gives signed_n collapsing to ≈ 0 across
        the gap (polyline endpoints have n ≈ +0.003m and n ≈ +2.23m,
        and the bridge interpolates between them across 64m).
      - At s = gap_start + 5m, signed_n is +5m (a typical track-edge
        value); same at s = gap_end - 5m. Using THESE values as the
        bridge endpoints gives a sensible width across the gap.
    """
    if gt_xy.shape[0] < 2:
        raise ValueError(f"gt {side} polyline has < 2 points after projection")

    s_arr, n_arr = frenet.xy_to_sn(gt_xy[:, 0], gt_xy[:, 1])
    L = float(frenet.total_length_m)

    # 1+2. Sort by s, tile-3-wrap, np.interp onto centerline s_grid.
    order = np.argsort(s_arr)
    s_sorted = s_arr[order]
    n_sorted = n_arr[order]
    if L > 0:
        s_sorted_tiled = np.concatenate([s_sorted - L, s_sorted, s_sorted + L])
        n_sorted_tiled = np.concatenate([n_sorted, n_sorted, n_sorted])
    else:
        s_sorted_tiled = s_sorted
        n_sorted_tiled = n_sorted
    signed_offsets = np.interp(frenet.s_grid, s_sorted_tiled, n_sorted_tiled)

    # 3+4. Detect coverage gap; if present, replace gap-bin values with
    # the MEDIAN of the polyline's interior signed_n, plus heavier
    # smoothing to absorb the resulting step at the gap boundary. The
    # median is robust to polyline-endpoint artifacts (where signed_n
    # collapses toward zero) and represents the boundary's typical
    # offset across the bulk of the track.
    gap = _detect_coverage_gap(s_arr, L, _GT_COVERAGE_GAP_THRESHOLD_M)
    s_grid = frenet.s_grid
    smooth_sigma = _GT_SMOOTH_SIGMA_BINS
    in_gap = np.zeros_like(s_grid, dtype=bool)
    if gap is not None:
        gap_start, gap_end = gap  # gap_end may be > L for seam gap
        if gap_end <= L:
            in_gap = (s_grid > gap_start) & (s_grid < gap_end)
        else:
            in_gap = (s_grid > gap_start) | (s_grid < (gap_end - L))

    # 4b. Day-10.5 F1 — detect projection-broken bins where the np.interp
    # output collapses toward (or past) zero on the dominant side of the
    # polyline. These arise when the centerline runs slightly off-track
    # at a tight apex (lap-set's racing lines vary widely → centerline
    # median lands on top of the polyline). np.interp linearly bridges
    # across the zero-crossings, leaving signed_n collapsed near zero
    # across a long run; the polygon assembly then self-intersects at
    # high curvature. Same bridge-fill treatment as a coverage gap.
    dominant_sign_pool = signed_offsets[np.abs(signed_offsets) > 0.5]
    if dominant_sign_pool.size > 0:
        dominant_sign = float(np.sign(np.median(dominant_sign_pool)))
    else:
        dominant_sign = float(np.sign(np.median(signed_offsets))) if signed_offsets.size else 1.0
    if dominant_sign == 0:
        dominant_sign = 1.0
    # Flag any bin whose dominant-side projection is below the floor —
    # this captures both wrong-sign bins AND near-zero bins on the
    # correct side, in one expression.
    broken_side = (signed_offsets * dominant_sign) < _GT_DOMINANT_SIDE_FLOOR_M

    # Combine coverage-gap bins + projection-broken bins under one fill.
    bad_bins = in_gap | broken_side
    if bad_bins.any() and not bad_bins.all():
        # Use the polyline's interior median signed_n (computed from
        # s-bin values OUTSIDE the bad region, away from endpoint and
        # zero-crossing artifacts). An additional inner guard band of
        # _GT_GAP_EDGE_GUARD_M is excluded from the median calculation
        # to avoid bias from bins immediately adjacent to bad regions
        # (which may be pulled toward zero by np.interp's linear bridge
        # into the bad region).
        guard_bins = int(round(_GT_GAP_EDGE_GUARD_M / max(s_grid[1] - s_grid[0], 1e-6)))
        interior_mask = ~bad_bins
        if guard_bins > 0:
            bad_dil = bad_bins.copy()
            for _ in range(guard_bins):
                bad_dil = bad_dil | np.roll(bad_dil, 1) | np.roll(bad_dil, -1)
            interior_mask = ~bad_dil

        interior_vals = signed_offsets[interior_mask]
        bridge_value = float(np.median(interior_vals)) if interior_vals.size else 0.0
        # Apply dominant sign defensively (the median should already match it).
        if dominant_sign != 0 and np.sign(bridge_value) != dominant_sign:
            bridge_value = dominant_sign * abs(bridge_value or 0.5)
        signed_offsets[bad_bins] = bridge_value
        # Bump smoothing in the presence of a bridged region to absorb
        # the step at the boundary. 10 bins ≈ 5m on a 0.5m grid.
        smooth_sigma = max(smooth_sigma, 10)

    # Final Gaussian smooth FIRST — this handles the bridge step (where
    # smoothing absorbs the discontinuity at the gap boundary) and any
    # natural noise in the polyline projection.
    signed_offsets = _smooth_1d(signed_offsets, smooth_sigma)

    # 5. Day-10.5 F1 — offset-curve safety clip, applied AFTER the smooth
    # so the smoothing can't pull clipped values back toward their original
    # un-clipped neighbours. On the INSIDE of a bend (signed_n * kappa > 0),
    # the polygon's boundary linestring folds back through the curvature
    # centre when |signed_n| > 1/|kappa|. Clip inside-side offsets so
    # |signed_n * kappa| stays under _GT_OFFSET_CURVE_SAFETY_ALPHA,
    # guaranteeing the offset curve is simple. The resulting step at the
    # clip boundary is acceptable: the boundary curve takes a slightly
    # sharper turn there, but it stays simple, which is what G1 requires.
    # OUTSIDE-side offsets are not affected (they only stretch the boundary,
    # never fold it).
    kappa = frenet.curvature_1pm
    if kappa is not None and kappa.shape == signed_offsets.shape:
        inside_metric = signed_offsets * kappa  # > 0 on the inside side
        is_inside = inside_metric > 0
        if is_inside.any():
            kappa_safe = np.maximum(np.abs(kappa), 1e-3)
            max_inside_abs = _GT_OFFSET_CURVE_SAFETY_ALPHA / kappa_safe
            current_abs = np.abs(signed_offsets)
            needs_clip = is_inside & (current_abs > max_inside_abs)
            if needs_clip.any():
                signed_offsets = np.where(
                    needs_clip,
                    np.sign(signed_offsets) * max_inside_abs,
                    signed_offsets,
                )
                # Narrow second smooth (σ ≈ 2 bins) softens the step between
                # clipped and un-clipped neighbours. Wider σ would defeat
                # the clip; narrower would leave a sharp boundary-curve
                # jump that itself can cause a self-intersection. σ=2 is
                # tuned empirically: OK_R1 polygon becomes simple, OK_R4
                # and KCT_R1 unaffected (their inside_metric never reaches
                # alpha so the clip doesn't fire).
                signed_offsets = _smooth_1d(signed_offsets, 2)
                # Re-apply the clip after smoothing — smoothing may have
                # nudged a few clipped values upward toward the
                # un-clipped neighbours. One iteration of (clip → smooth)
                # → clip is the minimal fixpoint that preserves the
                # geometric constraint AND has no step discontinuity.
                inside_metric = signed_offsets * kappa
                is_inside = inside_metric > 0
                current_abs = np.abs(signed_offsets)
                needs_clip = is_inside & (current_abs > max_inside_abs)
                if needs_clip.any():
                    signed_offsets = np.where(
                        needs_clip,
                        np.sign(signed_offsets) * max_inside_abs,
                        signed_offsets,
                    )

    return signed_offsets


def _gt_boundaries(
    frenet: FrenetFrame,
    gt: GroundTruth,
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> tuple[np.ndarray, np.ndarray, bool] | None:
    """Compute (width_left, width_right, side_swap) from hand-traced gt.

    width_left  is the distance from centerline to the boundary on the
                **+n̂_left side** of the centerline (rendered LEFT in the
                mesh output).
    width_right is the distance to the boundary on the **-n̂_left side**
                (rendered RIGHT).

    These are GEOMETRIC sides defined by the centerline's left-normal
    direction at each s — NOT the gt polylines' "left_boundary_gt" /
    "right_boundary_gt" labels. Day-8 fix: the previous |n|-based
    implementation sent both gt polylines to the +n̂_left side when
    the centerline was traversed opposite to gt's labeling convention
    (observed on OK_R4: gt LEFT had median signed n ≈ -4.8 m, gt RIGHT
    had ≈ +3.7 m; both abs values applied via +n̂_left placed both
    rendered polylines on the wrong sides — per-side gaps 9-11 m).

    ``side_swap`` tells callers whether gt's labeled "left_boundary_gt"
    landed on the geometric +n̂_left side (``False``, standard) or on
    the -n̂_left side (``True``, swapped). Downstream viz can use this
    flag to preserve the driver-perspective labeling from gt.

    Returns None if projected polylines are degenerate (too few points
    after projection) or sanity-violating (gt polylines on the same side
    of centerline, or non-positive widths). Width-out-of-range bins are
    logged but not rejected; gt is the trusted source.
    """
    left_xy = _gt_project_to_xy(gt.left_polyline, lat_ref_rad, lon_ref_rad)
    right_xy = _gt_project_to_xy(gt.right_polyline, lat_ref_rad, lon_ref_rad)

    if left_xy.shape[0] < 2 or right_xy.shape[0] < 2:
        logger.warning(
            "gt for %s has degenerate polylines after projection "
            "(left=%d pts, right=%d pts); refusing hand_traced path",
            gt.canonical_track_id, left_xy.shape[0], right_xy.shape[0],
        )
        return None

    try:
        signed_left = _gt_boundary_signed_offsets(frenet, left_xy, side="left")
        signed_right = _gt_boundary_signed_offsets(frenet, right_xy, side="right")
    except ValueError as exc:
        logger.warning(
            "gt projection failed for %s: %s; refusing hand_traced path",
            gt.canonical_track_id, exc,
        )
        return None

    # Determine geometric side of each gt polyline. The centerline
    # traversal direction (CW vs CCW from the Day-7 closed-loop algorithm)
    # is data-driven and not guaranteed to align with gt's labeling. We
    # pair gt polylines to width_left / width_right based on the signed
    # median n: the polyline with positive median ⇒ +n̂_left side ⇒
    # width_left; the polyline with negative median ⇒ -n̂_left side ⇒
    # width_right.
    median_left_n = float(np.median(signed_left))
    median_right_n = float(np.median(signed_right))

    if median_left_n > 0 and median_right_n < 0:
        # Standard convention: gt "left_boundary_gt" sits on +n̂_left side
        # of centerline. width_left = +signed_left is positive (gt LEFT
        # distance); width_right = -signed_right is positive (gt RIGHT
        # distance). Rendered LEFT = centerline + width_left * (+n̂_left),
        # rendered RIGHT = centerline - width_right * (+n̂_left).
        side_swap = False
        width_left = signed_left            # gt LEFT distance, positive
        width_right = -signed_right         # gt RIGHT distance, positive
    elif median_left_n < 0 and median_right_n > 0:
        # Swapped convention: gt "left_boundary_gt" sits on -n̂_left side
        # of centerline (the Day-7 centerline traversal direction is
        # opposite to gt's labeling convention). To keep the convention
        # width_left = gt LEFT distance, render with the opposite normal
        # sign downstream — handled via the side_swap=True flag.
        # Rendered LEFT = centerline - width_left * (+n̂_left),
        # rendered RIGHT = centerline + width_right * (+n̂_left).
        side_swap = True
        width_left = -signed_left           # gt LEFT distance, positive
        width_right = signed_right          # gt RIGHT distance, positive
    else:
        # Both polylines on the same side, or one is at n ≈ 0 → degenerate
        logger.warning(
            "gt for %s has both polylines on the same Frenet side "
            "(median_left_n=%+0.2f m, median_right_n=%+0.2f m); refusing "
            "hand_traced path — gt may cross the centerline.",
            gt.canonical_track_id, median_left_n, median_right_n,
        )
        return None

    # Sanity: widths should be positive. A modest fraction of non-positive
    # bins is tolerated (the racing-line centerline can legitimately cross
    # gt edges at tight hairpin apexes — observed on KCT at ~8 % bins).
    # Those bins are clipped to a tiny min rather than rejecting the whole
    # hand_traced path. The median-sign check above already guarantees
    # each gt polyline is on its expected side as a whole; only a very
    # large fraction would indicate a deeper polyline-crossing failure.
    _MIN_GT_WIDTH_FRAC_OK = 0.20      # tolerate up to 20 % bins bad
    _GT_BIN_FLOOR_M = 0.1             # clip floor on tolerated bad bins
    n_bins_total = len(width_left)
    n_left_bad = int(np.sum(width_left <= 0))
    n_right_bad = int(np.sum(width_right <= 0))
    if (
        n_left_bad / max(n_bins_total, 1) > _MIN_GT_WIDTH_FRAC_OK
        or n_right_bad / max(n_bins_total, 1) > _MIN_GT_WIDTH_FRAC_OK
    ):
        logger.warning(
            "gt for %s has too many non-positive width bins "
            "(width_left bad=%d/%d, width_right bad=%d/%d, threshold>%.0f%%); "
            "polyline likely crosses centerline. Refusing hand_traced path.",
            gt.canonical_track_id,
            n_left_bad, n_bins_total, n_right_bad, n_bins_total,
            100 * _MIN_GT_WIDTH_FRAC_OK,
        )
        return None
    if n_left_bad > 0:
        width_left = np.where(width_left <= 0, _GT_BIN_FLOOR_M, width_left)
    if n_right_bad > 0:
        width_right = np.where(width_right <= 0, _GT_BIN_FLOOR_M, width_right)
    if n_left_bad or n_right_bad:
        logger.info(
            "gt for %s clipped %d left + %d right tracing-outlier bins to %.2fm floor "
            "(within %.0f%% tolerance)",
            gt.canonical_track_id, n_left_bad, n_right_bad, _GT_BIN_FLOOR_M,
            100 * _MIN_GT_WIDTH_FRAC_OK,
        )

    total_w = width_left + width_right
    if np.any(total_w < _GT_WIDTH_MIN_M) or np.any(total_w > _GT_WIDTH_MAX_M):
        below = int(np.sum(total_w < _GT_WIDTH_MIN_M))
        above = int(np.sum(total_w > _GT_WIDTH_MAX_M))
        logger.warning(
            "gt for %s has %d bins below %.1fm and %d bins above %.1fm — "
            "outside sanity range [%.1f, %.1f]m. Keeping (gt trusted).",
            gt.canonical_track_id, below, _GT_WIDTH_MIN_M, above,
            _GT_WIDTH_MAX_M, _GT_WIDTH_MIN_M, _GT_WIDTH_MAX_M,
        )

    logger.info(
        "Hand-traced boundaries for %s: left mean=%.2fm, right mean=%.2fm, "
        "total width mean=%.2fm (n_bins=%d, source=%s, side_swap=%s)",
        gt.canonical_track_id, float(width_left.mean()), float(width_right.mean()),
        float(total_w.mean()), len(width_left), gt.source_filename, side_swap,
    )
    return width_left, width_right, side_swap


# ---------------------------------------------------------------------------
# Data-derived (RC3 robust MAD) path
# ---------------------------------------------------------------------------

# RC3 robust-MAD width estimator (Day-8 Phase D). Replaces the Day-3
# percentile-99 × 1.3 path with a per-s-bin median + K*MAD estimator that
# is robust to small-sample volatility (5-9 samples per bin) and to single-
# lap outliers. Constants below were chosen against the OK_R4 racing-line
# envelope (mean racing-line span ~1m past centerline; this estimator gives
# ~2-3m widths matching the racing-line corridor envelope + 1m headroom).
_RC3_MAD_K: Final[float] = 3.0          # ~3σ capture of racing-line variation
_RC3_MAD_FLOOR_M: Final[float] = 0.5    # min MAD; prevents collapse on tight apex bins
_RC3_MARGIN_M: Final[float] = 1.0       # additive corridor headroom beyond robust-max
_RC3_MIN_PER_SIDE: Final[int] = 3       # min samples per side to attempt MAD estimation
_RC3_DEFAULT_WIDTH_M: Final[float] = 3.0  # fallback width on under-sampled bins


def _data_derived_boundaries(
    frenet: FrenetFrame,
    laps_sn: list[tuple[np.ndarray, np.ndarray]],
    percentile: float,
    min_laps: int,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Robust MAD-based racing-line corridor estimator (Day-8 RC3).

    For each s-bin and each side (positive n = +n̂_left, |negative n| =
    -n̂_left), the width is::

        width = median(n_side) + K * max(MAD(n_side), MAD_FLOOR) + margin

    with K=3.0, MAD_FLOOR=0.5m, margin=1.0m. This is robust to the small-
    sample (5-9 per bin) volatility that made the Day-3 percentile-99 path
    erratic, and to dense single-lap outliers via the MAD floor.

    PRODUCES A RACING-LINE CORRIDOR ENVELOPE, NOT TRACK-EDGE WIDTHS.
    On tracks where drivers stay near a tight racing line (OK_R4 samples
    span ~1m past centerline on average), the resulting widths will sit
    around 2-3m — close to the racing-line corridor + 1m headroom, NOT
    the actual gt track edge (5m+ on OK_R4). For true track-edge
    boundaries use the hand_traced path with gt_*.geojson.

    The ``percentile`` parameter is retained for API back-compat with
    callers from the Day-3 era; it is no longer used internally.
    """
    if len(laps_sn) < min_laps:
        return None

    n_bins = frenet.n_points

    all_s = np.concatenate([s for s, _ in laps_sn])
    all_n = np.concatenate([n for _, n in laps_sn])
    all_idx = np.clip(
        np.searchsorted(frenet.s_grid, all_s) - 1,
        0, n_bins - 1,
    ).astype(int)

    width_left = np.full(n_bins, _RC3_DEFAULT_WIDTH_M)
    width_right = np.full(n_bins, _RC3_DEFAULT_WIDTH_M)

    for i in range(n_bins):
        mask = all_idx == i
        if mask.sum() < 5:
            continue
        n_vals = all_n[mask]
        pos = n_vals[n_vals > 0]
        neg_abs = np.abs(n_vals[n_vals < 0])
        if len(pos) >= _RC3_MIN_PER_SIDE:
            med = float(np.median(pos))
            mad = max(float(np.median(np.abs(pos - med))), _RC3_MAD_FLOOR_M)
            width_left[i] = med + _RC3_MAD_K * mad + _RC3_MARGIN_M
        if len(neg_abs) >= _RC3_MIN_PER_SIDE:
            med = float(np.median(neg_abs))
            mad = max(float(np.median(np.abs(neg_abs - med))), _RC3_MAD_FLOOR_M)
            width_right[i] = med + _RC3_MAD_K * mad + _RC3_MARGIN_M

    width_left = _smooth_1d(width_left, _SMOOTH_SIGMA_BINS)
    width_right = _smooth_1d(width_right, _SMOOTH_SIGMA_BINS)

    return width_left, width_right


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def estimate_boundaries_with_source(
    frenet: FrenetFrame,
    laps_sn: list[tuple[np.ndarray, np.ndarray]],
    track_id: str | None = None,
    lat_ref_rad: float | None = None,
    lon_ref_rad: float | None = None,
    percentile: float = _DEFAULT_PERCENTILE,
    min_laps: int = 3,
) -> tuple[np.ndarray, np.ndarray, str, bool] | None:
    """Estimate track width — prefer hand_traced gt when available.

    Resolution order:
      1. If track_id resolves to a canonical_id AND gt_*.geojson exists AND
         lat_ref_rad/lon_ref_rad are provided AND gt projection passes sanity
         → return hand_traced widths.
      2. Otherwise → data_derived (percentile-99 × 1.3 margin).
      3. If data_derived has < min_laps → return None.

    Returns
    -------
    (width_left, width_right, boundary_source, side_swap) where:
      - boundary_source is "hand_traced" or "data_derived"
      - side_swap is True when gt's "left_boundary_gt" sits on the
        -n̂_left side of the Day-7 centerline (i.e., the centerline was
        traversed in the opposite orientation to gt's labeling
        convention; the renderer must flip the normal direction for
        the LEFT polyline to land at the gt LEFT position).
      - For the data_derived path side_swap is always False.

    Returns None if neither path produced widths.
    """
    if track_id and lat_ref_rad is not None and lon_ref_rad is not None:
        canonical = resolve_track_id(track_id)
        if canonical is not None:
            gt = load_gt(canonical)
            if gt is not None:
                gt_result = _gt_boundaries(frenet, gt, lat_ref_rad, lon_ref_rad)
                if gt_result is not None:
                    return gt_result[0], gt_result[1], "hand_traced", gt_result[2]
                logger.info(
                    "Falling back to data_derived for track_id=%s "
                    "(gt loaded but projection failed sanity)",
                    track_id,
                )

    result = _data_derived_boundaries(frenet, laps_sn, percentile, min_laps)
    if result is None:
        return None
    return result[0], result[1], "data_derived", False


def estimate_boundaries(
    frenet: FrenetFrame,
    laps_sn: list[tuple[np.ndarray, np.ndarray]],
    percentile: float = _DEFAULT_PERCENTILE,
    min_laps: int = 3,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Backward-compatible 2-tuple wrapper.

    Stays on the data_derived path — callers that want hand_traced should
    use ``estimate_boundaries_with_source`` directly with track_id +
    lat_ref_rad + lon_ref_rad.
    """
    result = estimate_boundaries_with_source(
        frenet, laps_sn,
        track_id=None,
        lat_ref_rad=None, lon_ref_rad=None,
        percentile=percentile, min_laps=min_laps,
    )
    if result is None:
        return None
    return result[0], result[1]  # side_swap dropped — back-compat wrapper
