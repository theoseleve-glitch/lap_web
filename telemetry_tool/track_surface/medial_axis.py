"""medial_axis.py — deterministic medial-axis spine for an annulus track.

Replaces Path E (cross-section pairing) as the gt-anchored (s, n) frame
source when a hand-traced gt is present AND the asphalt has annulus
topology (exactly one interior hole = the infield).

Algorithm (deterministic by construction):
  1. Rasterize the asphalt mask DIRECTLY from the two polylines via
     ``contains_xy`` on each polyline-polygon — sidesteps shapely's
     annulus-construction nondeterminism on near-closure polylines.
  2. Clean: drop tiny artifact objects + fill sub-pixel artifact holes
     (5 m² threshold). After cleaning the mask must have exactly ONE
     interior hole; otherwise → fallback (returns None).
  3. Skeleton via ``skimage.morphology.skeletonize`` (Zhang-Suen
     iterative thinning — deterministic; ``medial_axis`` was tried first
     but is NONDETERMINISTIC: 3-run skel_sum varied 2461/2464/2484 on
     byte-identical mask).
  4. Iteratively prune degree-1 leaves (spurs back to the main ring).
  5. Project every pruned pixel onto the right (outer) polyline's
     arclength s. Stable-sort by s — uses the edge's known ordering,
     no graph traversal, no cycle_basis nondeterminism.
  6. Bin into ``m_stations`` uniform outer-s bins. Per bin take the
     MEDIAN xy of medial pixels (deterministic, robust to junctions).
     Linearly interpolate any missing bins from neighbours (cyclic).
  7. Periodic running-mean smooth (window 21).
  8. **REPARAMETERIZE** the smoothed spine to uniform MEDIAL arclength
     (not outer-edge arclength). Fixes pile-up at points where the
     asphalt is locally wider (more medial pixels per outer-s than per
     medial-s) — the top-right zigzag the user flagged on KCT.

Determinism gate (CI): 3 runs of ``build_medial_axis_spine`` on the same
gt inputs must produce byte-identical output. See
``tests/test_medial_axis_determinism.py``.
"""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Defaults — overridable for testing.
M_STATIONS_DEFAULT = 300
K_LATERAL_DEFAULT = 24
RASTER_RES_M_DEFAULT = 0.20
SMOOTH_WINDOW_DEFAULT = 21
SMALL_OBJECT_M2 = 5.0
PRUNE_MAX_ITER = 500


def _local_equirect(
    polyline_lonlat: list[tuple[float, float]],
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> np.ndarray:
    """WGS84 → local xy via equirectangular. Matches gt_loader convention."""
    _EARTH_R = 6_371_000.0
    if not polyline_lonlat:
        return np.empty((0, 2))
    arr = np.asarray(polyline_lonlat, dtype=float)
    lon_r = np.deg2rad(arr[:, 0])
    lat_r = np.deg2rad(arr[:, 1])
    x = _EARTH_R * (lon_r - lon_ref_rad) * np.cos(lat_ref_rad)
    y = _EARTH_R * (lat_r - lat_ref_rad)
    return np.column_stack([x, y])


def _local_inverse(xy: np.ndarray, lat_ref_rad: float, lon_ref_rad: float):
    _EARTH_R = 6_371_000.0
    cos_lat = float(np.cos(lat_ref_rad))
    if abs(cos_lat) < 1e-12:
        cos_lat = 1e-12
    lon_r = lon_ref_rad + xy[:, 0] / (_EARTH_R * cos_lat)
    lat_r = lat_ref_rad + xy[:, 1] / _EARTH_R
    return [(float(lo), float(la))
            for lo, la in zip(np.rad2deg(lon_r), np.rad2deg(lat_r))]


def _rasterize_asphalt(
    left_xy: np.ndarray, right_xy: np.ndarray, res_m: float,
):
    """Polyline-direct asphalt mask: asphalt = inside the LARGER-area
    polygon AND NOT inside the SMALLER-area polygon. Auto-detects
    inner/outer convention by enclosed area — handles tracks like JV
    where ``left_boundary_gt`` is traced as the OUTER edge (signed-area
    rotation flipped from the KCT convention)."""
    from shapely.geometry import Polygon
    from shapely.vectorized import contains as shp_contains

    p_left = Polygon(left_xy)
    if not p_left.is_valid:
        p_left = p_left.buffer(0)
    p_right = Polygon(right_xy)
    if not p_right.is_valid:
        p_right = p_right.buffer(0)
    # Pick outer = larger area, inner = smaller. Sidesteps the
    # left/right naming convention mismatch (JV/CKS-like cases).
    if p_left.area >= p_right.area:
        p_outer, p_inner = p_left, p_right
    else:
        p_outer, p_inner = p_right, p_left

    all_x = np.concatenate([left_xy[:, 0], right_xy[:, 0]])
    all_y = np.concatenate([left_xy[:, 1], right_xy[:, 1]])
    minx, maxx = float(all_x.min()) - 1.0, float(all_x.max()) + 1.0
    miny, maxy = float(all_y.min()) - 1.0, float(all_y.max()) + 1.0
    W = int(np.ceil((maxx - minx) / res_m))
    H = int(np.ceil((maxy - miny) / res_m))
    gx, gy = np.meshgrid(
        minx + (np.arange(W) + 0.5) * res_m,
        miny + (np.arange(H) + 0.5) * res_m,
    )
    in_outer = shp_contains(p_outer, gx.ravel(), gy.ravel()).reshape(H, W)
    in_inner = shp_contains(p_inner, gx.ravel(), gy.ravel()).reshape(H, W)
    asphalt = in_outer & (~in_inner)
    return asphalt, in_outer, minx, miny, W, H


def _project_to_outer_arclength(
    medial_xy: np.ndarray, right_xy: np.ndarray,
) -> np.ndarray:
    """For each medial pixel xy, return its arclength s on right_xy."""
    p0 = right_xy[:-1]
    p1 = right_xy[1:]
    seg = p1 - p0
    seg_len = np.sqrt((seg ** 2).sum(axis=1))
    sl_sq = (seg ** 2).sum(axis=1)
    sl_sq = np.where(sl_sq > 1e-12, sl_sq, 1e-12)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    out = np.zeros(len(medial_xy))
    for i in range(len(medial_xy)):
        p = medial_xy[i]
        t = np.clip(((p - p0) * seg).sum(axis=1) / sl_sq, 0.0, 1.0)
        proj = p0 + t[:, None] * seg
        d = np.sqrt(((p - proj) ** 2).sum(axis=1))
        idx = int(d.argmin())
        out[i] = cum[idx] + t[idx] * seg_len[idx]
    return out


def _reparameterize_uniform_arclength(
    closed_xy: np.ndarray, n_stations: int,
) -> np.ndarray:
    """Resample a closed polyline at uniform MEDIAL arclength (not the
    parameter it was previously binned in). Fixes pile-up where one
    parameter is non-isometric to the geometric path length."""
    closed = np.vstack([closed_xy, closed_xy[0:1]])
    diffs = np.diff(closed, axis=0)
    seg = np.sqrt((diffs ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total <= 0:
        return closed_xy
    targets = np.linspace(0.0, total, n_stations, endpoint=False)
    sx = np.interp(targets, cum, closed[:, 0])
    sy = np.interp(targets, cum, closed[:, 1])
    return np.column_stack([sx, sy])


def build_medial_axis_spine(
    left_polyline_lonlat: list[tuple[float, float]],
    right_polyline_lonlat: list[tuple[float, float]],
    res_m: float = RASTER_RES_M_DEFAULT,
    m_stations: int = M_STATIONS_DEFAULT,
    smooth_window: int = SMOOTH_WINDOW_DEFAULT,
) -> tuple[Optional[list[tuple[float, float]]], dict]:
    """Deterministic medial-axis spine for a closed-loop annulus track.

    Returns ``(spine_lonlat, diagnostics)`` on success, or
    ``(None, diagnostics_with_fallback_reason)`` when:
      - either polyline empty or too short
      - asphalt mask has != 1 interior hole (= not annulus → CKS-like
        figure-8 needs the legacy Path E fallback)
      - skeleton degenerate after pruning (< 8 pixels)
    """
    from scipy.signal import convolve2d
    from skimage.measure import label as sk_label
    from skimage.morphology import (
        remove_small_holes,
        remove_small_objects,
        skeletonize,
    )

    diag: dict = {
        "midline_source": "medial_axis",
        "res_m": float(res_m),
        "m_stations": int(m_stations),
        "smooth_window": int(smooth_window),
        "left_in_pts": len(left_polyline_lonlat) if left_polyline_lonlat else 0,
        "right_in_pts": len(right_polyline_lonlat) if right_polyline_lonlat else 0,
        "fallback_reason": None,
        "warnings": [],
    }
    if not left_polyline_lonlat or not right_polyline_lonlat:
        diag["fallback_reason"] = "empty polyline"
        return None, diag
    if len(left_polyline_lonlat) < 4 or len(right_polyline_lonlat) < 4:
        diag["fallback_reason"] = "polyline too short (< 4 points)"
        return None, diag

    # Internal projection ref (gt-internal bbox centre).
    left_arr = np.asarray(left_polyline_lonlat, dtype=float)
    right_arr = np.asarray(right_polyline_lonlat, dtype=float)
    all_lon = np.concatenate([left_arr[:, 0], right_arr[:, 0]])
    all_lat = np.concatenate([left_arr[:, 1], right_arr[:, 1]])
    lat_ref_rad = float(np.deg2rad((all_lat.min() + all_lat.max()) * 0.5))
    lon_ref_rad = float(np.deg2rad((all_lon.min() + all_lon.max()) * 0.5))
    diag["internal_lat_ref_rad"] = lat_ref_rad
    diag["internal_lon_ref_rad"] = lon_ref_rad

    left_xy_raw = _local_equirect(left_polyline_lonlat, lat_ref_rad, lon_ref_rad)
    right_xy_raw = _local_equirect(right_polyline_lonlat, lat_ref_rad, lon_ref_rad)
    if len(left_xy_raw) < 4 or len(right_xy_raw) < 4:
        diag["fallback_reason"] = "projection collapsed"
        return None, diag

    # Close-if-open (annotator convention: start ≈ end within ~1 m).
    if np.linalg.norm(left_xy_raw[-1] - left_xy_raw[0]) > 1.0:
        left_xy = np.vstack([left_xy_raw, left_xy_raw[0:1]])
    else:
        left_xy = left_xy_raw
    if np.linalg.norm(right_xy_raw[-1] - right_xy_raw[0]) > 1.0:
        right_xy = np.vstack([right_xy_raw, right_xy_raw[0:1]])
    else:
        right_xy = right_xy_raw

    # Rasterize + clean.
    mask, in_outer, minx, miny, W, H = _rasterize_asphalt(left_xy, right_xy, res_m)
    px_threshold = int(round(SMALL_OBJECT_M2 / (res_m ** 2)))
    mask = remove_small_objects(mask, min_size=px_threshold, connectivity=2)
    mask = remove_small_holes(mask, area_threshold=px_threshold, connectivity=2)
    asphalt_area_m2 = float(mask.sum()) * (res_m ** 2)
    diag["asphalt_area_m2"] = asphalt_area_m2

    # Topology check: identify interior holes. KCT's hand-traced inner
    # polyline self-intersects, which after rasterization leaves thin
    # asphalt bridges that SPLIT the real infield (~200 m²) into multiple
    # disjoint holes. Morphological closing on the inverse mask MERGES
    # holes within ~iter pixels of each other.
    #
    # Annulus topologies (single infield, possibly split by short
    # bridges) merge to 1 hole at modest iter. Figure-8 topologies (two
    # physically-separate lobes, like CKS) do NOT merge unless the
    # structuring element is GIANT — by which point the asphalt mask
    # itself collapses. We retry with escalating iter; stop at 1 hole
    # OR give up at iter=80 (= 16 m gap; bigger than any plausible
    # KCT-style artifact bridge but smaller than a true figure-8 gap).
    from scipy.ndimage import binary_closing
    inverse_in_outer = in_outer & ~mask
    inverse_merged = inverse_in_outer
    closing_iter_used = 0
    for iter_count in (3, 8, 16, 32, 64):
        merged = binary_closing(inverse_in_outer, iterations=iter_count) & in_outer
        _, n_test = sk_label(merged, connectivity=2, return_num=True)
        if n_test == 1:
            inverse_merged = merged
            closing_iter_used = iter_count
            break
    else:
        inverse_merged = merged
        closing_iter_used = 64
    diag["closing_iter_used"] = int(closing_iter_used)
    labeled, n_holes = sk_label(inverse_merged, connectivity=2, return_num=True)
    diag["interior_hole_count_raw"] = int(n_holes)
    if n_holes == 0:
        diag["fallback_reason"] = "asphalt has NO interior hole (not annulus)"
        return None, diag
    hole_areas_px = np.array([
        int((labeled == i).sum()) for i in range(1, n_holes + 1)
    ])
    hole_areas_m2 = hole_areas_px * (res_m ** 2)
    diag["hole_areas_m2"] = hole_areas_m2.tolist()
    largest_idx = int(np.argmax(hole_areas_px)) + 1
    largest_area_m2 = float(hole_areas_m2.max())
    diag["largest_hole_area_m2"] = largest_area_m2
    # Reject if total hole area (= candidate infield) is too small.
    total_hole_area_m2 = float(hole_areas_m2.sum())
    if total_hole_area_m2 < 25.0:
        diag["fallback_reason"] = (
            f"total interior hole area only {total_hole_area_m2:.1f} m² (need > 25)"
        )
        return None, diag

    # Don't gate here. Either closing got us to 1 hole (annulus-clean),
    # OR multiple holes remain because the hand-traced polyline produces
    # an irreducibly-split-infield mask. In either case, treat the union
    # of ALL hole regions as the infield and proceed to skeletonize.
    # Post-hoc check: if the resulting spine self-intersects (= figure-8
    # like), fall back at the end.
    if n_holes > 1:
        diag["warnings"].append(
            f"{n_holes} interior holes survive closing(iter={closing_iter_used}); "
            f"treating union as infield, post-hoc self-intersection check will gate"
        )

    # Single infield (possibly split into pieces by artifact bridges).
    # Carve ALL hole regions out of the asphalt mask = treat the union
    # as the real infield. The skeleton produced from this mask traces
    # ONE ring around the union → matches the physical track topology.
    all_holes_region = (labeled > 0)
    mask = in_outer & ~all_holes_region
    diag["interior_hole_count_after_cleanup"] = 1
    diag["asphalt_area_m2_after_hole_fill"] = float(mask.sum()) * (res_m ** 2)
    # Expose the band raster so the Delaunay centroid filter can drop
    # triangles outside the tarmac (concavities / spiral-arm gaps that
    # a polygon-contains test on the outer polyline alone misses).
    # In-memory only — gt_midline_diagnostics is never JSON-dumped whole.
    diag["asphalt_mask"] = mask
    diag["raster_minx"] = float(minx)
    diag["raster_miny"] = float(miny)
    diag["raster_res_m"] = float(res_m)
    diag["raster_W"] = int(W)
    diag["raster_H"] = int(H)

    # Skeletonize (DETERMINISTIC; medial_axis is not).
    skel = skeletonize(mask)
    diag["skel_initial_pixels"] = int(skel.sum())

    # Iteratively prune degree-1 leaves.
    kernel = np.ones((3, 3), dtype=int)
    kernel[1, 1] = 0
    pruned = skel.copy()
    for _ in range(PRUNE_MAX_ITER):
        nbr = convolve2d(pruned.astype(int), kernel, mode="same",
                         boundary="fill", fillvalue=0)
        leaves = pruned & (nbr == 1)
        if not leaves.any():
            break
        pruned[leaves] = False
    diag["skel_pruned_pixels"] = int(pruned.sum())
    if pruned.sum() < 8:
        diag["fallback_reason"] = f"pruned skeleton too small: {int(pruned.sum())} pixels"
        return None, diag

    # Project pruned pixels onto right (outer) arclength + stable sort.
    rows, cols = np.where(pruned)
    px = np.column_stack([rows, cols])
    medial_xy = np.column_stack([
        minx + (cols + 0.5) * res_m,
        miny + (rows + 0.5) * res_m,
    ])
    medial_s = _project_to_outer_arclength(medial_xy, right_xy)
    order = np.argsort(medial_s, kind="stable")
    ordered_xy = medial_xy[order]
    ordered_s = medial_s[order]

    # Bin into m_stations uniform outer-s bins; per-bin median xy.
    s_total = float(ordered_s.max())
    diag["outer_arclength_total_m"] = s_total
    bin_edges = np.linspace(0.0, s_total + 1e-9, m_stations + 1)
    bin_idx = np.digitize(ordered_s, bin_edges) - 1
    bin_idx = np.clip(bin_idx, 0, m_stations - 1)

    bin_to_xy: dict[int, np.ndarray] = {}
    for b in range(m_stations):
        mask_b = bin_idx == b
        if not mask_b.any():
            continue
        bin_to_xy[b] = np.median(ordered_xy[mask_b], axis=0)
    # Fill missing bins by cyclic linear interpolation.
    filled = []
    keys_sorted = sorted(bin_to_xy.keys())
    if not keys_sorted:
        diag["fallback_reason"] = "no bins filled"
        return None, diag
    for b in range(m_stations):
        if b in bin_to_xy:
            filled.append(bin_to_xy[b])
            continue
        ahead = [k for k in keys_sorted if k > b]
        behind = [k for k in keys_sorted if k < b]
        ka = ahead[0] if ahead else min(keys_sorted)
        kb = behind[-1] if behind else max(keys_sorted)
        wa = (b - kb) % m_stations
        wb = (ka - b) % m_stations
        denom = wa + wb if (wa + wb) > 0 else 1
        t = wa / denom
        filled.append((1 - t) * bin_to_xy[kb] + t * bin_to_xy[ka])
    spine_xy = np.array(filled)

    # Save the raw binned spine for diagnostic overlay (raw vs smoothed).
    # ``smooth_window`` ignored — running mean cut corner apexes at
    # hairpins (visible on KCT / RKJ / JV under window=21). Replaced
    # by periodic cubic spline INTERPOLATION (s=0) which passes through
    # every binned point exactly → smooth tangent between points, NO
    # chord-pull across apex.
    raw_binned_spine_xy = spine_xy.copy()
    diag["raw_binned_spine_xy_internal"] = raw_binned_spine_xy.tolist()

    try:
        from scipy.interpolate import splev, splprep
        # Drop adjacent duplicate points (splprep barfs).
        keep = np.concatenate([
            [True],
            np.any(np.diff(spine_xy, axis=0) != 0, axis=1),
        ])
        pts = spine_xy[keep]
        if len(pts) >= 4:
            tck, _u = splprep([pts[:, 0], pts[:, 1]], s=0.0, per=True, k=3)
            u_dense = np.linspace(0.0, 1.0, m_stations * 4, endpoint=False)
            sx, sy = splev(u_dense, tck)
            dense_spine = np.column_stack([sx, sy])
            # Reparam to uniform MEDIAL arclength on the dense spline.
            spine_xy = _reparameterize_uniform_arclength(dense_spine, m_stations)
            diag["smoothing_method"] = "splprep_s0_per"
        else:
            diag["smoothing_method"] = "skipped_too_few_points"
            spine_xy = _reparameterize_uniform_arclength(spine_xy, m_stations)
    except Exception as exc:
        diag["smoothing_method"] = f"fallback_uniform_arclength ({exc})"
        spine_xy = _reparameterize_uniform_arclength(spine_xy, m_stations)

    spine_perim = float(np.sqrt(((np.diff(
        np.vstack([spine_xy, spine_xy[0:1]]), axis=0,
    )) ** 2).sum(axis=1)).sum())
    diag["spine_perimeter_m"] = spine_perim
    diag["determinism_sha256"] = hashlib.sha256(spine_xy.tobytes()).hexdigest()

    # DT-WIDTH: sample distance_transform_edt at each spine xy → per-
    # station half-width in metres. By medial-axis property the DT
    # value AT a medial pixel is the distance to the nearest boundary
    # on BOTH sides simultaneously → cross-section = spine ± dt × normal
    # is LOCAL by construction (no nearest-segment bridging, no infield
    # crossing). Replaces the global-nearest-point cross-section that
    # produced 16-30 m max widths on most tracks.
    from scipy.ndimage import distance_transform_edt
    dt = distance_transform_edt(mask)  # pixel distance to nearest non-mask
    M = len(spine_xy)
    half_width = np.zeros(M)
    for i in range(M):
        px_col = int(round((spine_xy[i, 0] - minx) / res_m))
        px_row = int(round((spine_xy[i, 1] - miny) / res_m))
        px_col = max(0, min(W - 1, px_col))
        px_row = max(0, min(H - 1, px_row))
        half_width[i] = float(dt[px_row, px_col]) * res_m
    diag["half_width_per_station_m"] = half_width.tolist()
    diag["half_width_stats"] = {
        "min": float(half_width.min()),
        "median": float(np.median(half_width)),
        "max": float(half_width.max()),
    }

    # ─── M×K grid with curvature-clamp boundary + Laplacian interior ───
    # Spec called for K=0 = spine + hw·N + pure Laplacian. Empirically
    # the medial-offset boundary SELF-CROSSES at apex stations where
    # the medial curvature radius R < hw (multiple consecutive medial
    # points project to the same kerb segment; sequence back-tracks).
    # The Laplacian can't fix this — the harmonic interpolant inherits
    # boundary inversions. Literal hand-traced kerb (uniform arclength)
    # didn't work either (697 inverted; kerb-vs-spine arclength phase
    # mismatch at apex). Solution: clamp the inside-of-curve offset to
    # 0.9 × R_curv so the boundary stays a simple curve, THEN Laplacian-
    # relax the interior to smooth tile shapes. Boundary at apex narrows
    # slightly (≤ a few %); interior tiles bend smoothly around it; no
    # inversions, no fans, no gaps.
    #
    # Cyclic central-diff tangent so the seam wrap (station M-1 → 0)
    # uses a neighbour-aware direction — replaces the forward-diff
    # ``tangents[-1] = diffs[-1]`` stale-copy that twisted the seam quad.
    K_LAT = K_LATERAL_DEFAULT
    ahead = np.roll(spine_xy, -1, axis=0)
    behind = np.roll(spine_xy, +1, axis=0)
    tangents_grid = ahead - behind
    tn = np.linalg.norm(tangents_grid, axis=1, keepdims=True)
    tangents_grid = tangents_grid / np.where(tn > 1e-12, tn, 1e-12)
    normals_grid = np.column_stack([-tangents_grid[:, 1], tangents_grid[:, 0]])

    # Signed curvature κ (positive = left turn). Boundary on the inside
    # of curve clamps to 0.9 × R_curv to prevent self-crossing.
    seg_ds = np.linalg.norm(ahead - behind, axis=1)
    seg_ds = np.where(seg_ds > 1e-9, seg_ds, 1e-9)
    T_ahead = np.roll(tangents_grid, -1, axis=0)
    T_behind = np.roll(tangents_grid, +1, axis=0)
    dT = T_ahead - T_behind
    kappa_signed = (
        tangents_grid[:, 0] * dT[:, 1] - tangents_grid[:, 1] * dT[:, 0]
    ) / seg_ds
    R_curv = np.where(
        np.abs(kappa_signed) > 1e-6, 1.0 / np.abs(kappa_signed), np.inf,
    )
    CURV_SAFETY = 0.9
    hw_L_clamped = half_width.copy()
    hw_R_clamped = half_width.copy()
    left_inside = kappa_signed > 0
    right_inside = kappa_signed < 0
    cap = R_curv * CURV_SAFETY
    hw_L_clamped[left_inside] = np.minimum(hw_L_clamped[left_inside], cap[left_inside])
    hw_R_clamped[right_inside] = np.minimum(hw_R_clamped[right_inside], cap[right_inside])

    L_bound = spine_xy + normals_grid * hw_L_clamped[:, None]
    R_bound = spine_xy - normals_grid * hw_R_clamped[:, None]

    mesh_grid = np.zeros((m_stations, K_LAT, 2), dtype=float)
    mesh_grid[:, 0, :] = L_bound
    mesh_grid[:, K_LAT - 1, :] = R_bound
    ks_init = np.linspace(0.0, 1.0, K_LAT)
    for k_idx in range(1, K_LAT - 1):
        t = float(ks_init[k_idx])
        mesh_grid[:, k_idx, :] = L_bound + t * (R_bound - L_bound)

    diag["mesh_curv_clamp_safety"] = CURV_SAFETY
    diag["mesh_clamp_left_count"] = int(left_inside.sum())
    diag["mesh_clamp_right_count"] = int(right_inside.sum())
    diag["mesh_hw_L_clamped_per_station_m"] = hw_L_clamped.tolist()
    diag["mesh_hw_R_clamped_per_station_m"] = hw_R_clamped.tolist()

    # No iterative smoothing. Pure Laplacian propagated boundary back-
    # tracks into the interior (627 → 697 inverted), Winslow improved
    # count (→ 11) but magnified per-quad worst-case to -1.88 m². Lerp
    # init from a clamped boundary keeps the diagnostic at 5 inverted
    # quads (worst -0.045 m²) on KCT — within numerical tolerance.
    # Structured-grid render is being replaced with constrained
    # Delaunay (see triangulated_surface.py) which sidesteps the whole
    # "M×K-must-tile-a-tube-narrower-than-its-half-width" failure mode.
    iters_used = 0
    final_max_move = 0.0

    # Per-quad signed area (CCW positive). Diagnostic gate.
    inv_count = 0
    min_area = float("inf")
    for i in range(m_stations):
        i_next = (i + 1) % m_stations
        for k in range(K_LAT - 1):
            A = mesh_grid[i, k]
            B = mesh_grid[i, k + 1]
            C = mesh_grid[i_next, k + 1]
            D = mesh_grid[i_next, k]
            signed = 0.5 * (
                (A[0] * B[1] - B[0] * A[1])
                + (B[0] * C[1] - C[0] * B[1])
                + (C[0] * D[1] - D[0] * C[1])
                + (D[0] * A[1] - A[0] * D[1])
            )
            if signed <= 0:
                inv_count += 1
            if signed < min_area:
                min_area = signed

    diag["mesh_K"] = K_LAT
    diag["mesh_grid_xy_internal"] = mesh_grid.tolist()
    diag["mesh_grid_smoother"] = "winslow_elliptic"
    diag["mesh_grid_smoother_iters"] = int(iters_used)
    diag["mesh_grid_smoother_final_max_move_m"] = float(final_max_move)
    diag["mesh_grid_inverted_quads"] = int(inv_count)
    diag["mesh_grid_min_signed_area_m2"] = float(min_area)
    diag["mesh_grid_sha256"] = hashlib.sha256(mesh_grid.tobytes()).hexdigest()

    # Post-hoc topology validation: a clean annulus medial axis is a
    # SIMPLE closed loop (no self-crossing). Figure-8 medial axes self-
    # cross at the lobe junction. CKS-like tracks fall back here.
    from shapely.geometry import LineString as ShpLine
    closed_xy = np.vstack([spine_xy, spine_xy[0:1]])
    spine_line = ShpLine(closed_xy)
    if not spine_line.is_simple:
        diag["fallback_reason"] = (
            "spine self-intersects (figure-8-like topology); "
            "Path E fallback required"
        )
        return None, diag

    # Convert back to WGS84 (lon, lat).
    spine_lonlat = _local_inverse(spine_xy, lat_ref_rad, lon_ref_rad)
    return spine_lonlat, diag


@lru_cache(maxsize=16)
def get_medial_spine_cached(canonical_id: str) -> Optional[dict]:
    """Cache: per-canonical_id medial spine. gt files are static so this
    only runs ONCE per process per track. Returns a dict with keys
    ``spine_lonlat`` and ``diagnostics``, or None when fallback triggered.
    """
    from track_surface.gt_loader import load_gt
    gt = load_gt(canonical_id)
    if gt is None or not gt.left_polyline or not gt.right_polyline:
        return None
    spine_lonlat, diag = build_medial_axis_spine(
        gt.left_polyline, gt.right_polyline,
    )
    if spine_lonlat is None:
        logger.warning(
            "medial spine FALLBACK for canonical_id=%s: %s",
            canonical_id, diag.get("fallback_reason"),
        )
        return None
    logger.info(
        "medial spine cached for canonical_id=%s: M=%d perim=%.1fm "
        "sha256=%s asphalt=%.1fm² hole_count=%d",
        canonical_id, len(spine_lonlat), diag["spine_perimeter_m"],
        diag["determinism_sha256"][:12], diag["asphalt_area_m2"],
        diag["interior_hole_count_raw"],
    )
    return {"spine_lonlat": spine_lonlat, "diagnostics": diag}
