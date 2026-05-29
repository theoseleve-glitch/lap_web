"""gt_loader.py — Hand-traced ground-truth polyline loader.

Loads ``gt_*.geojson`` files (schema ``trackreco_ground_truth_v1``) from
``Analysis/trackreco-main/data/ground_truth/`` and resolves any input name
to a canonical track id via the alias registry at
``telemetry_tool/track_surface/track_aliases.json``.

Public API
~~~~~~~~~~

``resolve_track_id(input_name)``
    Resolve any alias (case-insensitive, whitespace-tolerant) to canonical_id.
    Returns ``None`` for unknown inputs.

``load_gt(track_input)``
    Return a frozen :class:`GroundTruth` with left + right polylines in
    WGS84 ``(lon, lat)``. Returns ``None`` when the track is unknown OR when
    no ``gt_*.geojson`` exists for any of its aliases on disk. Raises
    :class:`GTLoaderError` only on structurally-invalid gt files (e.g.,
    not a FeatureCollection, missing a boundary feature).

The alias-aware lookup means slk-fp1 → slk → tries gt_slk.geojson then
gt_slk-fp1.geojson — finds the variant filename automatically. Same for
ouest-karting → ok → tries gt_ok.geojson (currently absent, returns None).

Design constraints
~~~~~~~~~~~~~~~~~~

- Pure read; no side effects on disk
- Polyline order preserved (do NOT resort or reproject in this module —
  Frenet projection is the consumer's responsibility in boundary.py)
- WGS84 (lon, lat) preserved per GeoJSON spec
- Registry + alias index cached for the process lifetime via ``lru_cache``
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M = 6_371_000.0
"""Mirrors track_surface.boundary._EARTH_RADIUS_M. Kept local so the midline
helpers don't import from boundary.py (boundary imports from this module —
would be a circular dep). Identical equirectangular convention."""

_REPO_ROOT = Path(__file__).resolve().parents[2]  # Analysis/V2_claude_ai/ OR lap_web/
_ALIAS_REGISTRY_PATH = _REPO_ROOT / "telemetry_tool" / "track_surface" / "track_aliases.json"


def _resolve_gt_dir() -> Path:
    """Pick the first gt directory that exists.

    Layouts supported:
      1. ``$LAP_GT_DIR`` (explicit override; absolute path).
      2. ``<repo_root>/data/ground_truth/`` — self-contained
         (lap_web carries its own copy under ``lap_web/data/``).
      3. ``<repo_root>/../trackreco-main/data/ground_truth/`` — sibling
         layout that V2 uses (``Analysis/V2_claude_ai/`` next to
         ``Analysis/trackreco-main/``).

    Falls back to layout 3 if none match (callers see ``load_gt`` return
    None for any track).
    """
    env = os.environ.get("LAP_GT_DIR")
    if env:
        return Path(env)
    candidates = [
        _REPO_ROOT / "data" / "ground_truth",
        _REPO_ROOT.parent / "trackreco-main" / "data" / "ground_truth",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


_GT_DIR = _resolve_gt_dir()

_SCHEMA_VERSION_EXPECTED = "trackreco_ground_truth_v1"


class GTLoaderError(ValueError):
    """Raised when a gt file is structurally invalid."""


@dataclass(frozen=True)
class GroundTruth:
    """Hand-traced ground truth for a single track.

    Attributes
    ----------
    canonical_track_id : str
        The registry's canonical id (e.g., "kct", "slk", "ok").
    source_filename : str
        Basename of the gt file actually loaded (e.g., "gt_slk-fp1.geojson").
    left_polyline : list[tuple[float, float]]
        WGS84 (lon, lat) per GeoJSON spec, in order of annotation.
    right_polyline : list[tuple[float, float]]
        WGS84 (lon, lat).
    annotated_at : str
        ISO-8601 timestamp from the file's properties (empty string if absent).
    schema_version : str
        Schema string from the file's properties (e.g., "trackreco_ground_truth_v1").
    centerline_pred_polyline : list[tuple[float, float]] | None
        Pipeline-predicted centerline LineString in WGS84 (lon, lat). Loaded
        from the ``centerline_pred`` feature when present in the gt file.
        Used by the builder as a sanity cross-check against the
        midline computed from left_boundary_gt + right_boundary_gt. ``None``
        when the gt file has no ``centerline_pred`` feature.
    gt_centerline_lonlat : list[tuple[float, float]] | None
        Stage 1 (Day-15+) computed midline in WGS84 (lon, lat) from
        midpoint-walk on arclength-paired resamples of the
        ``left_boundary_gt`` and ``right_boundary_gt`` polylines. ``None``
        when the midline could not be computed (degenerate input).
    gt_width_left_m : np.ndarray | None
        Stage 1 per-station perpendicular distance from
        ``gt_centerline_lonlat`` to ``left_polyline`` in metres. Always
        non-negative. Shape ``(n_stations,)``. ``None`` when not computed.
    gt_width_right_m : np.ndarray | None
        Stage 1 per-station perpendicular distance from
        ``gt_centerline_lonlat`` to ``right_polyline`` in metres.
    gt_midline_diagnostics : dict | None
        Stage 1 metadata about the midline construction (n_stations,
        internal projection reference, width statistics). For debugging
        and dry-run reporting; not required by any downstream consumer.
    """

    canonical_track_id: str
    source_filename: str
    left_polyline: list[tuple[float, float]]
    right_polyline: list[tuple[float, float]]
    annotated_at: str
    schema_version: str
    centerline_pred_polyline: Optional[list[tuple[float, float]]] = None
    gt_centerline_lonlat: Optional[list[tuple[float, float]]] = None
    gt_width_left_m: Optional[np.ndarray] = field(default=None, repr=False)
    gt_width_right_m: Optional[np.ndarray] = field(default=None, repr=False)
    gt_midline_diagnostics: Optional[dict] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Midline + per-station width derivation (Stage 1 of the gt-anchored
# re-architecture). The midline becomes the Frenet frame's centerline in
# builder.py — replacing the driven-median path when gt is present.
# ---------------------------------------------------------------------------


def _local_equirect(
    polyline_lonlat: list[tuple[float, float]],
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> np.ndarray:
    """WGS84 (lon, lat) → local XY in metres via equirectangular projection.

    Same convention as track_surface.boundary._gt_project_to_xy. Kept local
    to avoid a circular dependency on boundary.py.
    """
    if not polyline_lonlat:
        return np.empty((0, 2), dtype=float)
    arr = np.asarray(polyline_lonlat, dtype=float)
    lon_r = np.deg2rad(arr[:, 0])
    lat_r = np.deg2rad(arr[:, 1])
    x = _EARTH_RADIUS_M * (lon_r - lon_ref_rad) * np.cos(lat_ref_rad)
    y = _EARTH_RADIUS_M * (lat_r - lat_ref_rad)
    return np.column_stack([x, y])


def _local_inverse(
    xy: np.ndarray,
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> list[tuple[float, float]]:
    """Inverse of _local_equirect — local XY (m) → WGS84 (lon, lat) degrees.

    Returns a list of (lon, lat) tuples matching the polyline conventions
    used by the rest of this module.
    """
    if xy.size == 0:
        return []
    cos_lat = float(np.cos(lat_ref_rad))
    if abs(cos_lat) < 1e-12:
        cos_lat = 1e-12
    lon_r = lon_ref_rad + xy[:, 0] / (_EARTH_RADIUS_M * cos_lat)
    lat_r = lat_ref_rad + xy[:, 1] / _EARTH_RADIUS_M
    lon_deg = np.rad2deg(lon_r)
    lat_deg = np.rad2deg(lat_r)
    return [(float(lo), float(la)) for lo, la in zip(lon_deg, lat_deg)]


def _resample_polyline_arclength(xy: np.ndarray, n: int) -> np.ndarray:
    """Resample (N,2) polyline to ``n`` points at uniform arclength.

    Used for the arclength-paired resample step of the midline midpoint
    walk: independent Δs resampling of left and right tolerates the
    natural point-count asymmetry (KCT: left=60 pts, right=93 pts).
    """
    if len(xy) < 2:
        return np.tile(xy[0], (n, 1)) if len(xy) == 1 else np.empty((0, 2))
    diffs = np.diff(xy, axis=0)
    seg = np.sqrt((diffs ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total <= 0:
        return np.tile(xy[0], (n, 1))
    targets = np.linspace(0.0, total, n)
    rx = np.interp(targets, cum, xy[:, 0])
    ry = np.interp(targets, cum, xy[:, 1])
    return np.column_stack([rx, ry])


def _bspline_smooth_closed(
    xy: np.ndarray,
    n_samples: int,
) -> np.ndarray:
    """Periodic cubic B-spline INTERPOLATION + resample at uniform u.

    Used to give continuous tangent direction along sparse hand-traced
    edge polylines (KCT: 60 pts / 428 m → ~7 m spacing → piecewise-linear
    segments produce step-discontinuous tangents at every original point
    → ray-cast normals jitter → 11.8% miss rate under Path E).

    Convention:
      * Pure INTERPOLATION (``s=0``) — spline passes through every input
        point. Geometry is preserved exactly; only the tangent direction
        between points becomes continuous (cubic C² across segments
        instead of piecewise constant). A first pass with a fitted
        smoothing spline ``s = N × σ²`` over-smoothed corners on
        compact tracks (AUX 0% → 30% ray miss). Pure interpolation
        avoids that.
      * ``xy`` must be a closed-loop polyline (start ≈ end within 1 m);
        caller must run ``_close_polyline`` first if needed.
      * Spline is fit through the un-closed sequence ``xy[:-1]`` with
        ``per=True`` so scipy enforces periodicity at the seam.

    Returns ``(n_samples, 2)`` points sampled at uniform ``u ∈ [0, 1)``.
    The output is a closed loop (start ≠ end; consumer can append start
    if a literal closure point is required).

    Falls back to the unsmoothed arclength resample when scipy isn't
    available, when there are < 4 points (cubic spline needs at least
    that), or when splprep raises — never crashes the producer.
    """
    if len(xy) < 4:
        return _resample_polyline_arclength(xy, n_samples)

    try:
        from scipy.interpolate import splev, splprep
    except ImportError:
        logger.warning(
            "scipy not available — B-spline smooth skipped, using linear resample"
        )
        return _resample_polyline_arclength(xy, n_samples)

    pts = xy[:-1] if np.allclose(xy[0], xy[-1], atol=1e-3) else xy
    if len(pts) < 4:
        return _resample_polyline_arclength(xy, n_samples)

    # Drop adjacent-duplicate points — splprep raises "Invalid inputs"
    # when consecutive points are identical (observed on slk-fp1).
    keep = np.concatenate([
        [True],
        np.any(np.diff(pts, axis=0) != 0, axis=1),
    ])
    pts = pts[keep]
    if len(pts) < 4:
        return _resample_polyline_arclength(xy, n_samples)

    try:
        tck, _u = splprep([pts[:, 0], pts[:, 1]], s=0.0, per=True, k=3)
    except Exception as exc:
        logger.warning(
            "B-spline fit failed (%s) — falling back to linear resample", exc
        )
        return _resample_polyline_arclength(xy, n_samples)

    u_fine = np.linspace(0.0, 1.0, n_samples, endpoint=False)
    try:
        sx, sy = splev(u_fine, tck)
    except Exception as exc:
        logger.warning(
            "B-spline eval failed (%s) — falling back to linear resample", exc
        )
        return _resample_polyline_arclength(xy, n_samples)

    return np.column_stack([sx, sy])


def _local_tangents_normals(
    xy: np.ndarray, window: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Unit tangent + left-hand unit normal at each polyline station.

    Tangents via forward differences (last station carries the last
    segment's direction). When ``window > 1``, tangents are smoothed via
    a moving average over ``window`` adjacent segments before
    normalization — useful for noisy hand-traced polylines where
    point-to-point tangent direction is dominated by digitizer jitter.

    Normals = tangents rotated 90° CCW: ``(-ty, tx)``. The +normal
    direction is "left of forward travel" — matches the +n half-plane of
    a FrenetFrame built from the same polyline.
    """
    n = len(xy)
    diffs = np.diff(xy, axis=0)
    if len(diffs) == 0:
        return np.zeros((n, 2)), np.zeros((n, 2))

    if window > 1:
        pad = window // 2
        diffs_padded = np.concatenate([
            np.tile(diffs[0:1], (pad, 1)),
            diffs,
            np.tile(diffs[-1:], (pad, 1)),
        ])
        kernel = np.ones(window) / window
        # convolve each axis
        smooth_x = np.convolve(diffs_padded[:, 0], kernel, mode="valid")
        smooth_y = np.convolve(diffs_padded[:, 1], kernel, mode="valid")
        # The "valid" convolution returns len(diffs_padded) - window + 1 = len(diffs)
        diffs_smooth = np.column_stack([smooth_x, smooth_y])
    else:
        diffs_smooth = diffs

    tangents = np.zeros_like(xy)
    tangents[:-1] = diffs_smooth
    tangents[-1] = diffs_smooth[-1]
    norms = np.linalg.norm(tangents, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1e-12)
    tangents = tangents / norms
    normals = np.column_stack([-tangents[:, 1], tangents[:, 0]])
    return tangents, normals


def _close_polyline(xy: np.ndarray, tol_m: float = 1.0) -> np.ndarray:
    """Append start to end if polyline is open within ``tol_m``.

    KCT and most gt boundaries are traced as open polylines whose
    endpoints are within ~1 m of each other (closed loops where the
    annotator didn't snap-close). Used to make ray-segment intersection
    treat the polyline as a true closed loop.
    """
    if len(xy) < 2:
        return xy
    if np.linalg.norm(xy[-1] - xy[0]) > tol_m:
        return np.vstack([xy, xy[0:1]])
    return xy


def _ray_segment_intersect(
    origin: np.ndarray,
    direction: np.ndarray,
    p0: np.ndarray,
    p1: np.ndarray,
) -> tuple[Optional[float], Optional[float]]:
    """Ray-segment intersection in 2D.

    Returns ``(t_along_ray, s_along_segment)`` or ``(None, None)`` when
    the ray either is parallel to the segment, hits behind the origin
    (``t < 0``), or lands outside the segment bounds (``s ∉ [0, 1]``).
    """
    seg = p1 - p0
    d = direction
    # Solve origin + t*d = p0 + s*seg
    # → [[d_x, -seg_x], [d_y, -seg_y]] @ [t, s] = (p0 - origin)
    det = d[1] * seg[0] - d[0] * seg[1]
    if abs(det) < 1e-12:
        return None, None
    rhs = p0 - origin
    t = (seg[0] * rhs[1] - seg[1] * rhs[0]) / det
    s = (d[0] * rhs[1] - d[1] * rhs[0]) / det
    if t < 0.0 or s < 0.0 or s > 1.0:
        return None, None
    return float(t), float(s)


def _cast_ray_to_polyline(
    origin: np.ndarray,
    direction: np.ndarray,
    polyline: np.ndarray,
    max_dist_m: float,
    t_min_m: float = 1e-3,
) -> tuple[Optional[float], Optional[np.ndarray]]:
    """Find the NEAREST forward intersection of a ray with a polyline.

    ``t_min_m`` skips intersections that fall within ``t_min_m`` of the
    origin — prevents the ray from immediately re-hitting its own
    starting segment when the origin lies ON the polyline (numerical
    degenerate case, not relevant for cross-section pairing from left to
    right but cheap to guard against).
    """
    best_t = None
    best_pt = None
    for i in range(len(polyline) - 1):
        p0 = polyline[i]
        p1 = polyline[i + 1]
        t, s = _ray_segment_intersect(origin, direction, p0, p1)
        if t is None:
            continue
        if t < t_min_m or t > max_dist_m:
            continue
        if best_t is None or t < best_t:
            best_t = t
            best_pt = p0 + s * (p1 - p0)
    return best_t, best_pt


def _signed_perp_distance_to_polyline(
    point: np.ndarray,
    normal: np.ndarray,
    polyline: np.ndarray,
) -> tuple[float, float]:
    """Closest-point distance from ``point`` to ``polyline``, signed via
    ``normal`` dot product.

    Returns ``(signed_distance, abs_distance)``. ``signed > 0`` means the
    nearest point on ``polyline`` is in the +``normal`` half-plane from
    ``point``; ``signed < 0`` means the -``normal`` half-plane.

    The match algorithm is the same clamped-segment projection used by
    the legacy ``_perp_distance_to_polyline`` — naive global-min, which
    can hit the wrong side of a tight horseshoe. Acceptable here because
    the midline is the GEOMETRIC centerline of the track (``centerline_pred``),
    not a driven racing line, so the local boundary is always closer
    than the opposite-side boundary.
    """
    if len(polyline) < 2:
        return float("nan"), float("nan")
    p0 = polyline[:-1]
    p1 = polyline[1:]
    seg = p1 - p0
    seg_len_sq = (seg ** 2).sum(axis=1)
    seg_len_sq = np.where(seg_len_sq > 1e-12, seg_len_sq, 1e-12)
    t = ((point - p0) * seg).sum(axis=1) / seg_len_sq
    t = np.clip(t, 0.0, 1.0)
    proj = p0 + t[:, None] * seg
    delta = proj - point  # polyline-point minus midline-point
    dists = np.sqrt((delta ** 2).sum(axis=1))
    idx_min = int(dists.argmin())
    abs_d = float(dists[idx_min])
    signed_d = float(delta[idx_min] @ normal)
    return signed_d, abs_d


def _compute_cross_section_midline_and_widths(
    left_polyline_lonlat: list[tuple[float, float]],
    right_polyline_lonlat: list[tuple[float, float]],
    ds_m: float = 0.5,
    tangent_window: int = 21,
    max_cast_dist_m: float = 20.0,
    width_max_warn_m: float = 8.0,
    side_consistency_threshold: float = 0.95,
) -> tuple[
    Optional[list[tuple[float, float]]],
    Optional[np.ndarray],
    Optional[np.ndarray],
    dict,
]:
    """Path E — true geometric midline by cross-section pairing.

    Algorithm:
      1. Project both WGS84 polylines to a local equirectangular frame.
      2. Close polylines if they're open within 1 m (handles annotator
         start≈end conventions).
      3. Resample ``left_boundary_gt`` to uniform ``ds_m`` arclength.
      4. Compute smoothed unit tangents on the resampled left (moving
         average over ``tangent_window`` segments — robust to hand-tracing
         point-spacing noise).
      5. At each left station, cast a ray perpendicular to the smoothed
         tangent onto ``right_boundary_gt``. Try BOTH ±normal directions
         and take whichever direction hits closer — this self-corrects
         the "+n vs -n is inward" question per-station (signed-area-of-
         polyline inference fails on inner-edge polylines with tiny
         enclosed area).
      6. Midline station = midpoint(left_pt, ray_intersection).
         half_width_left[i] = half_width_right[i] = (cast_dist) / 2.
      7. Ray-miss → interpolate from neighbors AND record in WARN list.

    Provenance: midline_source="cross_section_hand_traced",
    width_source="hand_traced_edges".

    WARN gates (appended to ``diagnostics["warnings"]``, never raise):
      - any ray miss
      - width_left / width_right max > ``width_max_warn_m`` (default 8.0 m;
        karting expectation)
      - side flip frequency > ``(1 - side_consistency_threshold)``

    Returns
    -------
    (midline_lonlat, width_left_m, width_right_m, diagnostics)

    Failure modes (return ``(None, None, None, diagnostics_with_error)``):
      - boundary polyline missing / too short
      - bbox projection collapses
      - all stations ray-miss (every cross-section ray fails)
    """
    diagnostics: dict = {
        "midline_source": "cross_section_hand_traced",
        "width_source": "hand_traced_edges",
        "ds_m": float(ds_m),
        "tangent_window": int(tangent_window),
        "max_cast_dist_m": float(max_cast_dist_m),
        "left_in_pts": len(left_polyline_lonlat) if left_polyline_lonlat else 0,
        "right_in_pts": len(right_polyline_lonlat) if right_polyline_lonlat else 0,
        "error": None,
        "warnings": [],
    }

    if not left_polyline_lonlat or not right_polyline_lonlat:
        diagnostics["error"] = "boundary polyline missing"
        return None, None, None, diagnostics
    if len(left_polyline_lonlat) < 2 or len(right_polyline_lonlat) < 2:
        diagnostics["error"] = "boundary polyline too short (< 2 points)"
        return None, None, None, diagnostics

    left_arr = np.asarray(left_polyline_lonlat, dtype=float)
    right_arr = np.asarray(right_polyline_lonlat, dtype=float)
    all_lon = np.concatenate([left_arr[:, 0], right_arr[:, 0]])
    all_lat = np.concatenate([left_arr[:, 1], right_arr[:, 1]])
    lat_ref_rad = float(np.deg2rad((all_lat.min() + all_lat.max()) * 0.5))
    lon_ref_rad = float(np.deg2rad((all_lon.min() + all_lon.max()) * 0.5))
    diagnostics["internal_lat_ref_rad"] = lat_ref_rad
    diagnostics["internal_lon_ref_rad"] = lon_ref_rad

    left_xy_raw = _local_equirect(left_polyline_lonlat, lat_ref_rad, lon_ref_rad)
    right_xy_raw = _local_equirect(right_polyline_lonlat, lat_ref_rad, lon_ref_rad)
    if len(left_xy_raw) < 2 or len(right_xy_raw) < 2:
        diagnostics["error"] = "projection collapsed (degenerate input)"
        return None, None, None, diagnostics

    left_xy = _close_polyline(left_xy_raw)
    right_xy = _close_polyline(right_xy_raw)

    left_total = float(np.sqrt(((np.diff(left_xy, axis=0)) ** 2).sum(axis=1)).sum())
    if left_total <= 0:
        diagnostics["error"] = "left polyline projects to zero length"
        return None, None, None, diagnostics

    n_stations = max(int(round(left_total / max(ds_m, 1e-6))), 50)
    diagnostics["n_left_stations"] = n_stations
    diagnostics["left_total_length_m"] = left_total

    # Stage 1 Step C: B-spline INTERPOLATE the left polyline (pass through
    # every hand-traced point exactly, cubic C² continuous tangent between
    # them) before the fine-ds resample. Fixes the step-discontinuous
    # tangents that linear interpolation produces at every original point
    # — which drove the 11.8% ray-cast miss rate on KCT (60 pts / 428 m
    # → ~7 m piecewise-linear segments). Geometry preserved exactly;
    # only tangent smoothness changes. Falls back to linear arclength
    # resample on scipy unavailable / spline fit failure.
    left_rs = _bspline_smooth_closed(left_xy, n_stations)
    _tangents, normals = _local_tangents_normals(left_rs, window=tangent_window)

    # Pre-pass: pick a CONSISTENT cross-section direction (+nrm or -nrm)
    # across the whole loop. For CCW-left + CCW-right (one inner, one outer
    # boundary of a closed track), the perpendicular direction from left
    # toward right is the same sign at every station. Letting each station
    # pick independently zig-zags the midline (KCT first attempt: midline
    # ended up 1.58x the expected length). Sample-vote up front, then
    # enforce the majority sign as the primary cast direction; only fall
    # back to the opposite sign at stations where the primary misses.
    sample_ix = np.linspace(0, n_stations - 1, num=min(30, n_stations), dtype=int)
    plus_hits = 0
    minus_hits = 0
    for i in sample_ix:
        origin = left_rs[i]
        nrm = normals[i]
        t_plus, _ = _cast_ray_to_polyline(origin, +nrm, right_xy, max_cast_dist_m)
        t_minus, _ = _cast_ray_to_polyline(origin, -nrm, right_xy, max_cast_dist_m)
        if t_plus is not None and (t_minus is None or t_plus <= t_minus):
            plus_hits += 1
        elif t_minus is not None:
            minus_hits += 1
    preferred_sign = +1 if plus_hits >= minus_hits else -1
    diagnostics["preferred_cast_sign"] = int(preferred_sign)
    diagnostics["preferred_cast_vote"] = {"plus": int(plus_hits), "minus": int(minus_hits)}

    midline_xy = np.zeros_like(left_rs)
    half_width = np.zeros(n_stations)
    miss_mask = np.ones(n_stations, dtype=bool)

    for i in range(n_stations):
        origin = left_rs[i]
        nrm = normals[i]
        primary_dir = preferred_sign * nrm
        t, hit = _cast_ray_to_polyline(origin, primary_dir, right_xy, max_cast_dist_m)
        if t is None:
            # Don't fall back to the opposite direction — at corners with
            # bad-tangent hand-tracing, the opposite hit lands the midline
            # on the wrong side of left and produces zig-zags. Let the
            # neighbor-interpolation pass below handle these stations.
            continue
        midline_xy[i] = 0.5 * (origin + hit)
        half_width[i] = float(t) * 0.5
        miss_mask[i] = False

    n_miss = int(miss_mask.sum())
    diagnostics["ray_miss_count"] = n_miss
    diagnostics["ray_miss_ratio"] = float(n_miss / n_stations)

    if n_miss == n_stations:
        diagnostics["error"] = "all stations ray-miss (no cross-section reachable)"
        return None, None, None, diagnostics

    if n_miss > 0:
        diagnostics["warnings"].append(
            f"ray miss at {n_miss}/{n_stations} stations "
            f"({n_miss / n_stations:.1%}) — interpolated from nearest neighbors"
        )
        good_idx = np.where(~miss_mask)[0]
        for i in np.where(miss_mask)[0]:
            ahead = good_idx[good_idx > i]
            behind = good_idx[good_idx < i]
            if len(ahead) == 0 and len(behind) == 0:
                continue
            ia = int(ahead[0]) if len(ahead) else int(behind[0])
            ib = int(behind[-1]) if len(behind) else int(ahead[-1])
            wa = (i - ib) % n_stations
            wb = (ia - i) % n_stations
            denom = wa + wb if (wa + wb) > 0 else 1
            t_blend = wa / denom
            midline_xy[i] = (1 - t_blend) * midline_xy[ib] + t_blend * midline_xy[ia]
            half_width[i] = (1 - t_blend) * half_width[ib] + t_blend * half_width[ia]

    width_left_m = half_width.copy()
    width_right_m = half_width.copy()

    _mid_tangents, mid_normals = _local_tangents_normals(midline_xy, window=tangent_window)
    sgn_left = np.zeros(n_stations)
    sgn_right = np.zeros(n_stations)
    for i in range(n_stations):
        s_l, _ = _signed_perp_distance_to_polyline(midline_xy[i], mid_normals[i], left_xy)
        s_r, _ = _signed_perp_distance_to_polyline(midline_xy[i], mid_normals[i], right_xy)
        sgn_left[i] = s_l
        sgn_right[i] = s_r
    left_on_plus = int((sgn_left > 0).sum())
    right_on_minus = int((sgn_right < 0).sum())
    left_plus_frac = left_on_plus / n_stations
    right_minus_frac = right_on_minus / n_stations
    diagnostics["left_on_plus_frac"] = float(left_plus_frac)
    diagnostics["right_on_minus_frac"] = float(right_minus_frac)
    if left_plus_frac < side_consistency_threshold:
        diagnostics["warnings"].append(
            f"left edge: only {left_on_plus}/{n_stations} stations "
            f"({left_plus_frac:.1%}) on +n side (expected >= "
            f"{side_consistency_threshold:.0%}); side convention flip suspected"
        )
    if right_minus_frac < side_consistency_threshold:
        diagnostics["warnings"].append(
            f"right edge: only {right_on_minus}/{n_stations} stations "
            f"({right_minus_frac:.1%}) on -n side (expected >= "
            f"{side_consistency_threshold:.0%}); side convention flip suspected"
        )

    mid_seg = np.sqrt(((np.diff(midline_xy, axis=0)) ** 2).sum(axis=1))
    midline_total_length = float(mid_seg.sum())
    diagnostics["midline_total_length_m"] = midline_total_length

    wl_max = float(width_left_m.max())
    wr_max = float(width_right_m.max())
    if wl_max > width_max_warn_m:
        diagnostics["warnings"].append(
            f"width_left max = {wl_max:.2f} m exceeds {width_max_warn_m} m sanity bound"
        )
    if wr_max > width_max_warn_m:
        diagnostics["warnings"].append(
            f"width_right max = {wr_max:.2f} m exceeds {width_max_warn_m} m sanity bound"
        )

    diagnostics["width_left_stats"] = {
        "min": float(width_left_m.min()),
        "median": float(np.median(width_left_m)),
        "max": wl_max,
    }
    diagnostics["width_right_stats"] = {
        "min": float(width_right_m.min()),
        "median": float(np.median(width_right_m)),
        "max": wr_max,
    }

    midline_lonlat = _local_inverse(midline_xy, lat_ref_rad, lon_ref_rad)
    return midline_lonlat, width_left_m, width_right_m, diagnostics


# ---------------------------------------------------------------------------
# Registry + alias index
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, dict]:
    """Return the ``tracks`` block from track_aliases.json."""
    with open(_ALIAS_REGISTRY_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    tracks = data.get("tracks", {})
    if not isinstance(tracks, dict):
        raise GTLoaderError(
            f"{_ALIAS_REGISTRY_PATH.name}: 'tracks' is not a dict"
        )
    return tracks


@lru_cache(maxsize=1)
def _build_alias_index() -> dict[str, str]:
    """Return ``{lowercased_alias: canonical_id}``.

    Raises :class:`GTLoaderError` if an alias collision is detected
    (same lowercased alias mapping to two different canonical_ids).
    """
    registry = _load_registry()
    index: dict[str, str] = {}
    for canonical_id, entry in registry.items():
        target = entry.get("canonical_id", canonical_id)
        for alias in entry.get("aliases", []) or []:
            key = str(alias).strip().lower()
            if not key:
                continue
            existing = index.get(key)
            if existing is not None and existing != target:
                raise GTLoaderError(
                    f"Alias collision: '{key}' resolves to both "
                    f"'{existing}' and '{target}'"
                )
            index[key] = target
    return index


@lru_cache(maxsize=1)
def load_all_canonical_polygons() -> list[tuple[str, "object", tuple[float, float, float, float]]]:
    """Day-15 Stage B: load every gt_*.geojson in the corpus, combine
    left_boundary_gt + reversed(right_boundary_gt) into a closed
    Shapely Polygon, repair self-intersection at the seam via buffer(0)
    when needed.

    Returns ``[(canonical_id, Polygon, bbox), ...]``. Bbox is
    ``(minx, miny, maxx, maxy)`` matching Shapely's ``Polygon.bounds``.

    Cached at module level (lru_cache size 1) — gt files don't change at
    runtime; the build cost (Shapely Polygon construction + buffer(0)
    repair for ~6 of 8 tracks) is paid once per worker process.
    """
    from shapely.geometry import Polygon
    from shapely import make_valid

    results: list[tuple[str, "object", tuple[float, float, float, float]]] = []
    if not _GT_DIR.exists():
        logger.warning("gt corpus dir does not exist: %s — matcher will fall through", _GT_DIR)
        return results

    for gt_path in sorted(_GT_DIR.glob("gt_*.geojson")):
        try:
            with open(gt_path, encoding="utf-8") as fh:
                gt = json.load(fh)
        except Exception as exc:
            logger.warning("failed to load %s: %s — skipping", gt_path.name, exc)
            continue
        raw_name = (gt.get("properties", {}) or {}).get("track_name")
        if not raw_name:
            continue
        # Resolve raw track_name (annotator-issued slug) through the alias
        # registry to its canonical_id. Without this, a gt file with
        # ``properties.track_name = "karting-club-de-tours-kct-"`` returns
        # that raw slug and the matcher's PG lookup
        # ``WHERE canonical_id = ?`` misses (PG has canonical_id='kct').
        # Fall back to the filename stem (gt_<alias>.geojson → <alias>)
        # if alias-registry resolve also misses — last-ditch.
        canon = (
            resolve_track_id(str(raw_name))
            or resolve_track_id(gt_path.stem[3:] if gt_path.stem.startswith("gt_") else gt_path.stem)
            or str(raw_name).strip().lower()
        )
        features = {
            f.get("properties", {}).get("role"): f.get("geometry", {}).get("coordinates")
            for f in gt.get("features", []) or []
        }
        left = features.get("left_boundary_gt")
        right = features.get("right_boundary_gt")
        if not left or not right:
            logger.warning("gt %s missing left/right_boundary_gt — skipping", gt_path.name)
            continue
        ring = list(left) + list(reversed(right))
        if ring[0] != ring[-1]:
            ring = ring + [ring[0]]
        try:
            poly = Polygon(ring)
        except Exception as exc:
            logger.warning("Polygon construction failed for %s: %s", gt_path.name, exc)
            continue
        if not poly.is_valid:
            fixed = poly.buffer(0)
            if not (fixed.is_valid and not fixed.is_empty):
                fixed = make_valid(poly)
            if not (fixed.is_valid and not fixed.is_empty):
                logger.warning("gt %s polygon invalid + unrepairable", gt_path.name)
                continue
            poly = fixed
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        results.append((str(canon).strip().lower(), poly, poly.bounds))
    return results


def match_session_to_canonical(
    lats: list[float] | None,
    lons: list[float] | None,
    *,
    sample_n_min: int = 500,
    threshold_abs: float = 0.30,
    threshold_gap: float = 0.30,
) -> dict:
    """Day-15 Stage B: match a session's GPS to a canonical_id by
    point-in-polygon against the hand-traced gt corpus.

    Algorithm (Phase 1 dry-run validated, 2026-05-21):
      1. Build session bbox from lats/lons.
      2. Adaptive sampling: max(sample_n_min, len(points)//50) target.
      3. For each gt polygon: bbox-prefilter (O(1) reject), then
         point-in-polygon on sampled points → confidence = in_poly / n.
      4. Pick best canonical_id; require confidence >= threshold_abs
         AND (best - runner_up) >= threshold_gap to declare a match.

    Returns dict with keys:
      canonical_id, confidence, in_bbox_frac, runner_up,
      runner_up_confidence, status ("matched" | "pending"), reason.

    Pure read-only; safe to call from anywhere.
    """
    if not lats or not lons or len(lats) < 10:
        return {
            "canonical_id": None, "confidence": 0.0, "in_bbox_frac": 0.0,
            "runner_up": None, "runner_up_confidence": 0.0,
            "status": "pending", "reason": "no_gps_data",
        }

    from shapely.geometry import Point

    polys = load_all_canonical_polygons()
    if not polys:
        return {
            "canonical_id": None, "confidence": 0.0, "in_bbox_frac": 0.0,
            "runner_up": None, "runner_up_confidence": 0.0,
            "status": "pending", "reason": "gt_corpus_empty",
        }

    s_min_lon, s_max_lon = min(lons), max(lons)
    s_min_lat, s_max_lat = min(lats), max(lats)
    target = max(sample_n_min, len(lats) // 50)
    step = max(1, len(lats) // target)
    sampled = [(lons[i], lats[i]) for i in range(0, len(lats), step)]
    n = len(sampled)

    scores: list[tuple[str, float, float]] = []  # (canon, in_poly_frac, in_bbox_frac)
    for canon, poly, (minx, miny, maxx, maxy) in polys:
        if s_max_lon < minx or s_min_lon > maxx or s_max_lat < miny or s_min_lat > maxy:
            scores.append((canon, 0.0, 0.0))
            continue
        in_bbox = sum(1 for lon, lat in sampled if minx <= lon <= maxx and miny <= lat <= maxy)
        in_poly = sum(1 for p in sampled if poly.contains(Point(p)))
        scores.append((canon, in_poly / n, in_bbox / n))

    scores.sort(key=lambda x: -x[1])
    best = scores[0]
    runner = scores[1] if len(scores) > 1 else ("", 0.0, 0.0)

    if best[1] >= threshold_abs and (best[1] - runner[1]) >= threshold_gap:
        return {
            "canonical_id": best[0], "confidence": round(best[1], 4),
            "in_bbox_frac": round(best[2], 4),
            "runner_up": runner[0] or None,
            "runner_up_confidence": round(runner[1], 4),
            "status": "matched", "reason": None,
        }
    return {
        "canonical_id": None, "confidence": round(best[1], 4),
        "in_bbox_frac": round(best[2], 4),
        "runner_up": (best[0] or None) if best[1] > 0 else None,
        "runner_up_confidence": round(runner[1], 4),
        "status": "pending",
        "reason": "low_polygon_coverage" if best[1] < threshold_abs else "ambiguous_match",
    }


def resolve_canonical_via_pg(track_id: str | None) -> str | None:
    """Bridge PG `tracks.track_id` → `tracks.canonical_id` for sessions
    keyed by UUID rather than a registry alias.

    Day-15 Phase 2 Stage B: the pipeline passes the PG `track_id` (UUID
    or sentinel) down to the surface build, but `resolve_track_id`
    only matches strings present in `track_aliases.json`. This helper
    closes that gap by doing a single read-only lookup against the
    `tracks.canonical_id` column (added in migration 060).

    Connection sourcing: uses its OWN raw psycopg2 connection with
    `autocommit=True` so this query cannot poison and cannot be poisoned
    by any surrounding transaction state (the surface-build context has
    a history of txn-abort cascades — this lookup must stay isolated).

    Error handling:
      - track_id falsy → return None (no log).
      - Row found, `canonical_id` IS NULL → return None (no log; this
        is the expected case for placeholder tracks like the
        `unknown_track` sentinel and pipeline-auto-registered UUIDs).
      - Row not found → return None (no log; unknown track is expected).
      - Connection / query exception → log WARNING and return None
        (never silently swallow). The surface build falls back to the
        data_derived envelope, which is the safe default.
    """
    if not track_id:
        return None
    raw = None
    try:
        # Lazy import — web.db_pg is in a sibling package; keeping it out of
        # module-load avoids any circular-dep risk in the track_surface tree.
        from web.db_pg import _new_connection
        # _new_connection() returns a fresh psycopg2 conn (RealDictCursor).
        # We force autocommit ON for this single SELECT so we never share
        # txn state with anything upstream/downstream.
        raw = _new_connection()
        raw.autocommit = True
        with raw.cursor() as cur:
            cur.execute(
                "SELECT canonical_id FROM tracks WHERE track_id = %(t)s",
                {"t": track_id},
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning(
            "canonical_id bridge query failed for track_id=%r: %s",
            track_id, exc,
        )
        return None
    finally:
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass
    if row is None:
        return None
    val = row.get("canonical_id") if hasattr(row, "get") else row[0]
    if val is None or not str(val).strip():
        return None
    return str(val).strip().lower()


def resolve_track_id(input_name: str | None) -> str | None:
    """Resolve any alias to canonical_id.

    Case-insensitive, whitespace-tolerant. Returns ``None`` for unknown
    inputs (empty string, whitespace-only, not in the registry).
    """
    if not input_name or not str(input_name).strip():
        return None
    key = str(input_name).strip().lower()
    return _build_alias_index().get(key)


# ---------------------------------------------------------------------------
# gt file parsing
# ---------------------------------------------------------------------------


def _parse_gt_geojson(
    path: Path,
) -> tuple[
    list[tuple[float, float]],
    list[tuple[float, float]],
    Optional[list[tuple[float, float]]],
    str,
    str,
]:
    """Parse a gt_*.geojson and return its boundary polylines + metadata.

    Returns
    -------
    (left_polyline, right_polyline, centerline_pred_polyline,
     annotated_at, schema_version)
        Each polyline is a list of (lon, lat) WGS84 points.
        ``centerline_pred_polyline`` is ``None`` when the gt file has no
        ``centerline_pred`` LineString feature (older / partial gt files).

    Raises
    ------
    GTLoaderError
        - top-level JSON is not an object
        - ``type`` is not ``"FeatureCollection"``
        - missing ``left_boundary_gt`` feature with LineString geometry
        - missing ``right_boundary_gt`` feature with LineString geometry
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise GTLoaderError(f"{path.name}: top-level JSON is not an object")
    if data.get("type") != "FeatureCollection":
        raise GTLoaderError(
            f"{path.name}: type is '{data.get('type')}', expected 'FeatureCollection'"
        )

    props = data.get("properties") or {}
    schema_version = str(props.get("schema", ""))
    annotated_at = str(props.get("annotated_at", ""))

    left: list[tuple[float, float]] | None = None
    right: list[tuple[float, float]] | None = None
    centerline_pred: list[tuple[float, float]] | None = None

    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        role = (feat.get("properties") or {}).get("role", "")
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        polyline = [(float(c[0]), float(c[1])) for c in coords]
        if role == "left_boundary_gt":
            left = polyline
        elif role == "right_boundary_gt":
            right = polyline
        elif role == "centerline_pred":
            centerline_pred = polyline

    if left is None:
        raise GTLoaderError(
            f"{path.name}: missing left_boundary_gt LineString feature"
        )
    if right is None:
        raise GTLoaderError(
            f"{path.name}: missing right_boundary_gt LineString feature"
        )

    return left, right, centerline_pred, annotated_at, schema_version


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_gt(track_input: str | None) -> GroundTruth | None:
    """Load gt for a track identified by any alias.

    Resolves ``track_input`` to canonical_id, then delegates to the
    cached ``_load_gt_canonical`` so the heavy work (file parse + medial
    spine extraction) happens ONCE per canonical_id per process — gt is
    static so re-running per session would waste ~1-2 s each call.
    """
    canonical_id = resolve_track_id(track_input)
    if canonical_id is None:
        logger.debug("Unknown track input: %r", track_input)
        return None
    return _load_gt_canonical(canonical_id)


@lru_cache(maxsize=16)
def _load_gt_canonical(canonical_id: str) -> GroundTruth | None:
    """Cached gt load keyed on canonical_id. See ``load_gt`` for the
    public entry that resolves aliases to canonical_id first.

    Cache is process-local; gt files don't change at runtime so 16 slots
    cover all canonical tracks. Side-effect: parse + medial-axis build
    happen exactly once per (process, canonical_id), then every
    subsequent ``load_gt`` returns the cached ``GroundTruth`` object."""
    registry = _load_registry()
    entry = registry.get(canonical_id, {}) or {}
    # Always probe canonical_id first; then any additional aliases.
    aliases: list[str] = [canonical_id]
    for alias in entry.get("aliases", []) or []:
        if alias not in aliases:
            aliases.append(str(alias))

    for alias in aliases:
        candidate = _GT_DIR / f"gt_{alias}.geojson"
        if not candidate.exists():
            continue
        left, right, centerline_pred, annotated_at, schema_version = (
            _parse_gt_geojson(candidate)
        )
        # Try the medial-axis spine first (Path G — deterministic; replaces
        # Path E cross-section pairing when annulus topology validates).
        # On fallback (figure-8, degenerate, etc.), use the legacy
        # cross-section pairing (Path E + C) as the midline source.
        from track_surface.medial_axis import build_medial_axis_spine
        medial_spine_lonlat, medial_diag = build_medial_axis_spine(left, right)
        if medial_spine_lonlat is not None:
            midline_lonlat = medial_spine_lonlat
            midline_diag = medial_diag
            # DT widths from medial_axis: per-station distance_transform
            # value sampled at the spine pixel. By medial-axis property
            # this IS the distance to the nearest boundary on BOTH sides
            # simultaneously → width_left == width_right == DT half-width.
            # Replaces the global-nearest-pt approach that could bridge
            # at horseshoes.
            hw = np.asarray(
                medial_diag["half_width_per_station_m"], dtype=float,
            )
            width_left = hw.copy()
            width_right = hw.copy()
            midline_diag["width_left_stats"] = dict(
                medial_diag["half_width_stats"]
            )
            midline_diag["width_right_stats"] = dict(
                medial_diag["half_width_stats"]
            )
        else:
            # Medial fallback: use Path E + C (cross-section pairing).
            logger.warning(
                "gt %s: medial-axis spine fell back (%s) — using Path E "
                "cross-section midline",
                candidate.name, medial_diag.get("fallback_reason"),
            )
            midline_lonlat, width_left, width_right, midline_diag = (
                _compute_cross_section_midline_and_widths(left, right)
            )
            # Preserve the medial fallback reason in diagnostics.
            midline_diag["medial_fallback_reason"] = medial_diag.get("fallback_reason")
        err = midline_diag.get("error")
        if err:
            logger.warning(
                "gt %s: midline computation failed (%s) — builder will "
                "fall back to driven-median frame",
                candidate.name, err,
            )
        for w in midline_diag.get("warnings", []):
            logger.warning("gt %s midline WARN: %s", candidate.name, w)
        logger.info(
            "Loaded gt for canonical_id=%s from %s (left=%d pts, right=%d pts, "
            "centerline_pred=%s, midline=%s pts via %s, widths from %s, "
            "schema=%s, annotated=%s)",
            canonical_id, candidate.name, len(left), len(right),
            "absent" if centerline_pred is None else f"{len(centerline_pred)} pts",
            "fail" if midline_lonlat is None else f"{len(midline_lonlat)}",
            midline_diag.get("midline_source", "?"),
            midline_diag.get("width_source", "?"),
            schema_version, annotated_at,
        )
        return GroundTruth(
            canonical_track_id=canonical_id,
            source_filename=candidate.name,
            left_polyline=left,
            right_polyline=right,
            annotated_at=annotated_at,
            schema_version=schema_version,
            centerline_pred_polyline=centerline_pred,
            gt_centerline_lonlat=midline_lonlat,
            gt_width_left_m=width_left,
            gt_width_right_m=width_right,
            gt_midline_diagnostics=midline_diag,
        )

    logger.info(
        "No gt file found for canonical_id=%r (searched %d aliases at %s)",
        canonical_id, len(aliases), _GT_DIR,
    )
    return None
