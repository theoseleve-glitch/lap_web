"""triangulated_surface.py — constrained Delaunay render mesh.

Replaces the structured M×K render with a constrained Delaunay
triangulation of the real asphalt polygon (outer kerb minus inner-
infield hole). The M×K grid is kept as the LOGICAL coordinate system
for the optimiser + grip lookup; only the rendered geometry changes
to a triangulation.

Why: the M×K grid's K=0 = spine + hw·N boundary back-tracks at apex
stations where R_medial < hw (multiple consecutive medial points
project to the same kerb segment), which neither Laplacian nor
Winslow smoothers can fix. A Delaunay triangulation of the real
polygon is clean by construction: vertices touch both kerbs, no
inversions (after CW→CCW orientation pass), no fans, no gaps.

Construction:
  1. Auto-detect outer/inner by polygon area.
  2. Densify both kerbs to ~1 m spacing (boundary vertices).
  3. Sample hex-grid interior points; keep those inside outer AND
     outside inner. Spacing chosen to target ``target_area_m2``.
  4. scipy.spatial.Delaunay on the combined point set
     (deterministic via QHull for fixed input).
  5. Filter triangles whose centroid lies outside the asphalt (i.e.
     inside the hole or outside outer — should be few; the convex
     hull of an annulus has extra triangles to remove).
  6. Compact unused vertices; orient all triangles CCW (positive
     signed area) so the FE renderer's back-face culling shows the
     front face.

Determinism: scipy.spatial.Delaunay (QHull) + shapely.vectorized
.contains + np.unique are all deterministic for byte-identical
input. 3-run sha256 check.
"""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Defaults — overridable per call.
TARGET_AREA_M2_DEFAULT = 1.5
BOUNDARY_SPACING_M_DEFAULT = 1.861  # sqrt(1.5 * 4 / sqrt(3)) — matches interior hex pitch
MIN_AREA_M2_DEFAULT = 1e-4


def _densify_closed_polyline(poly: np.ndarray, spacing_m: float) -> np.ndarray:
    """Resample a closed polyline to uniform arclength spacing."""
    closed = np.vstack([poly, poly[0:1]])
    diffs = np.diff(closed, axis=0)
    seg = np.sqrt((diffs ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    n = max(int(round(total / spacing_m)), 12)
    targets = np.linspace(0.0, total, n, endpoint=False)
    sx = np.interp(targets, cum, closed[:, 0])
    sy = np.interp(targets, cum, closed[:, 1])
    return np.column_stack([sx, sy])


# Per-triangle barycentric sample weights for the area-fraction filter
# against the raster asphalt mask. 13 FIXED points per triangle (3 verts
# + 3 edge midpoints + 1 centroid + 6 interior weighted barycentric).
# Fixed = NOT random → deterministic for a given input. Threshold ≥ 0.6
# of these landing in mask keeps the triangle (tunable 0.5-0.7).
_TRI_SAMPLE_BARYCENTRIC = np.asarray([
    [1.0,    0.0,    0.0   ],  # vertex A
    [0.0,    1.0,    0.0   ],  # vertex B
    [0.0,    0.0,    1.0   ],  # vertex C
    [0.5,    0.5,    0.0   ],  # midpoint AB
    [0.0,    0.5,    0.5   ],  # midpoint BC
    [0.5,    0.0,    0.5   ],  # midpoint CA
    [1/3,    1/3,    1/3   ],  # centroid
    [0.5,    0.25,   0.25  ],  # interior, weighted to A
    [0.25,   0.5,    0.25  ],  # interior, weighted to B
    [0.25,   0.25,   0.5   ],  # interior, weighted to C
    [2/3,    1/6,    1/6   ],  # near A
    [1/6,    2/3,    1/6   ],  # near B
    [1/6,    1/6,    2/3   ],  # near C
], dtype=float)


def _triangle_fraction_in_mask(
    verts: np.ndarray,
    tris: np.ndarray,
    raster: dict,
) -> np.ndarray:
    """Vectorised: per-tri fraction of 13 fixed barycentric samples
    that fall inside the raster mask. Returns (T,) array of fractions."""
    mask = raster["mask"]
    minx_r = float(raster["minx"])
    miny_r = float(raster["miny"])
    res_r = float(raster["res_m"])
    W_r = int(raster["W"])
    H_r = int(raster["H"])

    A = verts[tris[:, 0]]  # (T, 2)
    B = verts[tris[:, 1]]
    C = verts[tris[:, 2]]

    # (T, 13, 2) — sample[t, i] = wa·A[t] + wb·B[t] + wc·C[t]
    w = _TRI_SAMPLE_BARYCENTRIC  # (13, 3)
    samples = (
        w[None, :, 0:1] * A[:, None, :]
        + w[None, :, 1:2] * B[:, None, :]
        + w[None, :, 2:3] * C[:, None, :]
    )
    flat = samples.reshape(-1, 2)
    cols = np.round((flat[:, 0] - minx_r) / res_r).astype(int)
    rows = np.round((flat[:, 1] - miny_r) / res_r).astype(int)
    in_range = (cols >= 0) & (cols < W_r) & (rows >= 0) & (rows < H_r)
    in_mask_flat = np.zeros(len(flat), dtype=bool)
    in_mask_flat[in_range] = mask[rows[in_range], cols[in_range]]
    return in_mask_flat.reshape(-1, 13).mean(axis=1)


def build_triangulated_surface(
    left_xy: np.ndarray,
    right_xy: np.ndarray,
    spine_xy: Optional[np.ndarray] = None,
    s_grid: Optional[np.ndarray] = None,
    target_area_m2: float = TARGET_AREA_M2_DEFAULT,
    boundary_spacing_m: float = BOUNDARY_SPACING_M_DEFAULT,
    min_area_m2: float = MIN_AREA_M2_DEFAULT,
    band_mask_raster: Optional[dict] = None,
    kerb_buffer_iters: int = 0,
    mask_fraction_threshold: float = 0.6,
) -> dict:
    """QHull Delaunay + area-fraction filter against the raster
    asphalt mask. Spirals / inter-arm gaps / outer notches are
    handled correctly because the mask itself encodes them (built by
    medial_axis.py with morphological closing). PSLG / Polygon-with-
    hole approaches break on spirals because shapely's nested-hole
    semantics fill solid for non-simply-connected infields. The raster
    mask is the source of truth — every other geometric simplification
    on top of it leaked.

    For each triangle, 13 FIXED barycentric sample points (3 verts +
    3 edge midpoints + 1 centroid + 6 interior weighted points) — see
    ``_TRI_SAMPLE_BARYCENTRIC``. Keep iff fraction-in-mask ≥
    ``mask_fraction_threshold`` (default 0.6). Tarmac tris ~100% in
    mask → kept; gap/infield tris mostly out → dropped; kerb-straddling
    tris kept when mostly in → no fringe, no hairline gap.

    Args:
        left_xy/right_xy: closed kerb polylines (gt-internal frame),
            outer/inner auto-detected by polygon area.
        spine_xy, s_grid: optional medial spine + arclength for per-
            vertex (s, n) projection.
        target_area_m2: hex interior point spacing target.
        boundary_spacing_m: kerb densification spacing.
        min_area_m2: drop sub-threshold slivers (numerical noise).
        band_mask_raster: REQUIRED for spiral-correct filtering.
            Falls back to polygon-contains (LEAKS for spirals) when None.
        kerb_buffer_iters: IGNORED (no dilation — kerb is sharp).
        mask_fraction_threshold: tunable 0.5-0.7. Lower = keep more
            boundary-edge tris (risk fringe); higher = stricter
            (risk hairline gap). 0.6 default.
    """
    from scipy.spatial import Delaunay
    from shapely.geometry import Polygon
    from shapely.vectorized import contains as shp_contains

    del kerb_buffer_iters  # dilation always backfires — kerb is sharp

    p_left = Polygon(left_xy)
    if not p_left.is_valid:
        p_left = p_left.buffer(0)
    p_right = Polygon(right_xy)
    if not p_right.is_valid:
        p_right = p_right.buffer(0)
    if p_left.area >= p_right.area:
        outer_xy, inner_xy = left_xy, right_xy
        p_outer, p_inner = p_left, p_right
    else:
        outer_xy, inner_xy = right_xy, left_xy
        p_outer, p_inner = p_right, p_left

    if np.allclose(outer_xy[0], outer_xy[-1]):
        outer_xy = outer_xy[:-1]
    if np.allclose(inner_xy[0], inner_xy[-1]):
        inner_xy = inner_xy[:-1]

    outer_dense = _densify_closed_polyline(outer_xy, boundary_spacing_m)
    inner_dense = _densify_closed_polyline(inner_xy, boundary_spacing_m)
    N_outer = len(outer_dense)
    N_inner = len(inner_dense)

    # Hex interior — same equilateral packing as before. Filter to
    # asphalt via the RASTER MASK (truth) so spiral-arm gaps don't get
    # interior pts; polygon-contains fallback only for callers that
    # don't supply a raster.
    spacing = float(np.sqrt(target_area_m2 * 4.0 / np.sqrt(3.0)))
    minx, miny = float(outer_dense[:, 0].min()), float(outer_dense[:, 1].min())
    maxx, maxy = float(outer_dense[:, 0].max()), float(outer_dense[:, 1].max())
    row_step = spacing * float(np.sqrt(3.0)) * 0.5
    xs = np.arange(minx, maxx + spacing, spacing)
    ys = np.arange(miny, maxy + row_step, row_step)
    pts: list[tuple[float, float]] = []
    for j, y in enumerate(ys):
        offset = (spacing * 0.5) if (j % 2) else 0.0
        for x in xs:
            pts.append((float(x + offset), float(y)))
    if not pts:
        raise ValueError("hex grid produced no interior points")
    interior_grid = np.asarray(pts, dtype=float)

    if band_mask_raster is not None:
        mask = band_mask_raster["mask"]
        mxr = float(band_mask_raster["minx"])
        myr = float(band_mask_raster["miny"])
        rr = float(band_mask_raster["res_m"])
        Wr = int(band_mask_raster["W"])
        Hr = int(band_mask_raster["H"])
        cols = np.round((interior_grid[:, 0] - mxr) / rr).astype(int)
        rows = np.round((interior_grid[:, 1] - myr) / rr).astype(int)
        in_range = (cols >= 0) & (cols < Wr) & (rows >= 0) & (rows < Hr)
        in_mask = np.zeros(len(interior_grid), dtype=bool)
        in_mask[in_range] = mask[rows[in_range], cols[in_range]]
        interior_pts = interior_grid[in_mask]
    else:
        in_outer_mask = shp_contains(p_outer, interior_grid[:, 0], interior_grid[:, 1])
        in_inner_mask = shp_contains(p_inner, interior_grid[:, 0], interior_grid[:, 1])
        interior_pts = interior_grid[in_outer_mask & ~in_inner_mask]

    vertices_all = np.vstack([outer_dense, inner_dense, interior_pts])

    tri = Delaunay(vertices_all)
    simplices = np.asarray(tri.simplices, dtype=int)

    # AREA-FRACTION filter — 13 fixed sample pts per triangle.
    if band_mask_raster is not None:
        fraction = _triangle_fraction_in_mask(
            vertices_all, simplices, band_mask_raster,
        )
        keep_mask = fraction >= mask_fraction_threshold
    else:
        # Last-resort fallback: polygon-contains (leaks on spirals).
        A_pts = vertices_all[simplices[:, 0]]
        B_pts = vertices_all[simplices[:, 1]]
        C_pts = vertices_all[simplices[:, 2]]
        centroids = (A_pts + B_pts + C_pts) / 3.0
        in_outer_c = shp_contains(p_outer, centroids[:, 0], centroids[:, 1])
        in_inner_c = shp_contains(p_inner, centroids[:, 0], centroids[:, 1])
        keep_mask = in_outer_c & ~in_inner_c
        fraction = keep_mask.astype(float)  # for diag below

    # ─── INTERIOR-TEAR SEAL ──────────────────────────────────────────
    # The 0.6 area-fraction filter correctly carves the outer boundary
    # (Théo-approved corridor) but nicks thin triangles at narrow necks
    # and kerb-sliver spots, producing pinholes / 1-wide cracks in
    # the membrane interior. Pure triangle-adjacency morphological
    # close: re-add any DROPPED triangle whose 3 edge-neighbours are
    # ALL KEPT (= enclosed by membrane). Iterate to stable.
    #
    # Exterior-boundary triangles never have all-3 neighbours kept (at
    # least one edge faces the dropped exterior or the convex-hull
    # outside), so the carved concavities Théo approved stay carved.
    # Deterministic: sorted iteration + Jacobi-style per-pass update.

    # Build edge → triangle adjacency map over ALL simplices.
    n_simplices = len(simplices)
    edge_to_tris: dict[tuple[int, int], list[int]] = {}
    for t_idx in range(n_simplices):
        a, b, c = int(simplices[t_idx, 0]), int(simplices[t_idx, 1]), int(simplices[t_idx, 2])
        for u, v in ((a, b), (b, c), (a, c)):
            key = (u, v) if u < v else (v, u)
            edge_to_tris.setdefault(key, []).append(t_idx)

    def _neighbours_kept_count(t_idx: int, mask: np.ndarray) -> int:
        a, b, c = int(simplices[t_idx, 0]), int(simplices[t_idx, 1]), int(simplices[t_idx, 2])
        n = 0
        for u, v in ((a, b), (b, c), (a, c)):
            key = (u, v) if u < v else (v, u)
            for nb in edge_to_tris[key]:
                if nb != t_idx and mask[nb]:
                    n += 1
                    break
        return n

    # Diagnose dropped tris BEFORE seal: classify INTERIOR (≥2/3 kept
    # neighbours = on the inside of the membrane, surrounded) vs
    # EXTERIOR (≤1/3 kept = on the carved boundary).
    dropped_initial = np.where(~keep_mask)[0]
    nb_kept_initial = np.array(
        [_neighbours_kept_count(int(t), keep_mask) for t in dropped_initial],
        dtype=int,
    )
    fr_dropped = fraction[dropped_initial]
    diag_dropped_total = int(len(dropped_initial))
    diag_interior_tears = int(np.sum(nb_kept_initial >= 2))
    diag_exterior_drops = int(np.sum(nb_kept_initial <= 1))
    diag_all_three = int(np.sum(nb_kept_initial == 3))
    diag_frac_histogram = {
        "<0.1": int(np.sum(fr_dropped < 0.1)),
        "0.1-0.3": int(np.sum((fr_dropped >= 0.1) & (fr_dropped < 0.3))),
        "0.3-0.5": int(np.sum((fr_dropped >= 0.3) & (fr_dropped < 0.5))),
        "0.5-0.6": int(np.sum((fr_dropped >= 0.5) & (fr_dropped < 0.6))),
    }

    # FROZEN-CLASSIFICATION SEAL: re-add every triangle initially
    # classified as INTERIOR (≥2/3 neighbours kept). The classification
    # is computed ONCE against the initial keep_mask, then frozen — no
    # iteration, no re-classification. This guarantees:
    #   - every dropped tri surrounded by ≥2 kept neighbours fills the
    #     adjacent pinhole/crack (no matter how wide the dropped band
    #     gets, as long as the dropped tri itself has 2 kept neighbours)
    #   - every dropped tri originally classified EXTERIOR (≤1 kept
    #     neighbour) STAYS dropped — outer carved boundary preserved
    #     exactly because the classification predates the seal
    #
    # The all-3-neighbours-kept-with-iteration variant from spec only
    # filled 6/57 KCT tears (most are multi-tri cracks where no single
    # dropped tri has all 3 kept), so we fall back to the spec's branch
    # "if diagnosis shows wider tears, switch approach" — frozen ≥2 is
    # adjacency's analogue of binary_closing constrained to the initial
    # interior set.
    interior_mask_initial = np.zeros(n_simplices, dtype=bool)
    for k, t_idx in enumerate(dropped_initial):
        if nb_kept_initial[k] >= 2:
            interior_mask_initial[t_idx] = True
    seal_added_total_count = int(interior_mask_initial.sum())
    keep_mask = keep_mask | interior_mask_initial

    # Post-seal interior-tear count: any dropped tri with ≥2 kept
    # neighbours after the seal. Should be 0 (every initial INTERIOR
    # tri got added). A non-zero result here would mean an EXTERIOR
    # tri got promoted to INTERIOR by the seal — shouldn't happen
    # given the frozen-classification guarantee.
    nb_kept_after = np.array(
        [_neighbours_kept_count(i, keep_mask) for i in range(n_simplices)],
        dtype=int,
    )
    diag_interior_tears_after = int(np.sum((~keep_mask) & (nb_kept_after >= 2)))
    seal_added_per_pass = [seal_added_total_count]  # one-shot, single "pass"
    diag_seal_added_total = seal_added_total_count

    # Stash diag values on the simplices for the caller's report.
    # (Module logger; caller can inspect via get_triangulated_surface_cached
    # diag fields below.)
    _seal_diag = {
        "dropped_total_pre_seal": diag_dropped_total,
        "interior_tears_pre_seal": diag_interior_tears,
        "interior_tears_post_seal": diag_interior_tears_after,
        "exterior_drops_pre_seal": diag_exterior_drops,
        "dropped_with_all_3_neighbours_kept_pre_seal": diag_all_three,
        "dropped_area_fraction_histogram": diag_frac_histogram,
        "seal_added_per_pass": seal_added_per_pass,
        "seal_added_total": diag_seal_added_total,
        "seal_passes_used": len(seal_added_per_pass),
    }
    logger.info(
        "triangulated_surface seal: dropped_pre=%d interior_tears_pre=%d "
        "exterior_pre=%d added_per_pass=%s tears_post=%d",
        diag_dropped_total, diag_interior_tears, diag_exterior_drops,
        seal_added_per_pass, diag_interior_tears_after,
    )

    kept = simplices[keep_mask]
    if len(kept) == 0:
        raise ValueError("no triangles passed area-fraction filter")

    A_k = vertices_all[kept[:, 0]]
    B_k = vertices_all[kept[:, 1]]
    C_k = vertices_all[kept[:, 2]]
    cross = (B_k[:, 0] - A_k[:, 0]) * (C_k[:, 1] - A_k[:, 1]) - (
        B_k[:, 1] - A_k[:, 1]
    ) * (C_k[:, 0] - A_k[:, 0])
    signed_areas_raw = 0.5 * cross

    cw_mask = signed_areas_raw < 0
    kept_oriented = kept.copy()
    kept_oriented[cw_mask] = kept[cw_mask][:, [0, 2, 1]]
    signed_areas = np.where(cw_mask, -signed_areas_raw, signed_areas_raw)

    keep_area = signed_areas >= min_area_m2
    sliver_count = int(np.sum(~keep_area))
    kept_oriented = kept_oriented[keep_area]
    signed_areas = signed_areas[keep_area]

    used = np.unique(kept_oriented)
    remap = np.full(len(vertices_all), -1, dtype=int)
    remap[used] = np.arange(len(used))
    verts_compact = vertices_all[used]
    tris_compact = remap[kept_oriented]

    # Per-vertex (s, n) on the spine.
    sn_per_vertex: Optional[np.ndarray] = None
    if spine_xy is not None and s_grid is not None:
        # Cyclic central-diff tangents / normals (same convention as
        # api_edge_payload + medial_axis).
        ahead = np.roll(spine_xy, -1, axis=0)
        behind = np.roll(spine_xy, +1, axis=0)
        tangents = ahead - behind
        tn = np.linalg.norm(tangents, axis=1, keepdims=True)
        tangents = tangents / np.where(tn > 1e-12, tn, 1e-12)
        normals = np.column_stack([-tangents[:, 1], tangents[:, 0]])

        # Brute-force closest-station per vertex: V × M floats (~few MB).
        d2 = (
            (verts_compact[:, None, 0] - spine_xy[None, :, 0]) ** 2
            + (verts_compact[:, None, 1] - spine_xy[None, :, 1]) ** 2
        )
        i_min = np.argmin(d2, axis=1)
        delta = verts_compact - spine_xy[i_min]
        # Tangential refinement: s_v = s_grid[i_min] + δ · T[i_min]
        # (where T[i_min] is the unit tangent; gives sub-station s).
        s_v = s_grid[i_min] + (
            delta[:, 0] * tangents[i_min, 0] + delta[:, 1] * tangents[i_min, 1]
        )
        n_v = delta[:, 0] * normals[i_min, 0] + delta[:, 1] * normals[i_min, 1]
        sn_per_vertex = np.column_stack([s_v, n_v])

    sha_input = verts_compact.tobytes() + tris_compact.tobytes()
    sha = hashlib.sha256(sha_input).hexdigest()

    return {
        "vertices_xy": verts_compact,
        "indices": tris_compact,
        "sn_per_vertex": sn_per_vertex,
        "triangle_count": int(len(tris_compact)),
        "vertex_count": int(len(verts_compact)),
        "min_signed_area_m2": float(np.min(signed_areas)),
        "max_signed_area_m2": float(np.max(signed_areas)),
        "median_signed_area_m2": float(np.median(signed_areas)),
        "inverted_count_post_orient": int(np.sum(signed_areas <= 0)),
        "sliver_count_dropped": sliver_count,
        "min_area_m2_threshold": float(min_area_m2),
        "outer_dense_pts": int(N_outer),
        "inner_dense_pts": int(N_inner),
        "interior_pts": int(len(interior_pts)),
        "sha256": sha,
        "target_area_m2": float(target_area_m2),
        "boundary_spacing_m": float(boundary_spacing_m),
        "mask_fraction_threshold": float(mask_fraction_threshold),
        "method": "qhull_plus_raster_area_fraction_plus_seal",
        "seal_diag": _seal_diag,
    }


@lru_cache(maxsize=16)
def get_triangulated_surface_cached(canonical_id: str) -> Optional[dict]:
    """Cached per-canonical-id Delaunay topology (xy in gt-internal frame).

    Builds the triangulation ONCE per process per canonical_id; gt files
    are static so the topology never changes. The cached payload omits
    per-session data (grip values, session-frame xy) — those are
    computed in ``build_edge_payload`` per API call.

    Returns dict with vertices_xy_internal (V, 2), indices (T, 3),
    sn_per_vertex (V, 2) + topology stats. Returns None when gt is
    missing, when medial-axis fell back (no spine available for the
    (s, n) lookup), or when triangulation raises.
    """
    from track_surface.gt_loader import _local_equirect, load_gt
    from track_surface.medial_axis import get_medial_spine_cached

    gt = load_gt(canonical_id)
    if gt is None or not gt.left_polyline or not gt.right_polyline:
        return None
    if gt.gt_centerline_lonlat is None:
        return None

    diag = gt.gt_midline_diagnostics or {}
    if diag.get("midline_source") != "medial_axis":
        # Triangulation needs a clean spine for the (s, n) projection.
        # On figure-8 / fallback cases the spine self-intersects → (s, n)
        # lookup at apex is ambiguous. Caller falls back to M×K or
        # literal-edge dispatcher.
        logger.info(
            "triangulation skipped for %s: midline_source=%s (not medial)",
            canonical_id, diag.get("midline_source"),
        )
        return None

    lat_r = float(diag["internal_lat_ref_rad"])
    lon_r = float(diag["internal_lon_ref_rad"])
    left_xy = _local_equirect(gt.left_polyline, lat_r, lon_r)
    right_xy = _local_equirect(gt.right_polyline, lat_r, lon_r)
    spine_xy = _local_equirect(gt.gt_centerline_lonlat, lat_r, lon_r)

    # Per-station spine arclength (closed loop, last segment wraps).
    closed = np.vstack([spine_xy, spine_xy[0:1]])
    seg = np.sqrt((np.diff(closed, axis=0) ** 2).sum(axis=1))
    s_grid = np.concatenate([[0.0], np.cumsum(seg)[:-1]])
    spine_perim = float(seg.sum())

    # Pull the band raster medial_axis built (in gt-internal frame).
    # When present, drives the centroid-in-band filter so triangles in
    # outer notches / spiral-arm gaps get dropped. When missing (old
    # cached diag from before this fix), build_triangulated_surface
    # falls back to the polygon-contains filter.
    band_raster = None
    if "asphalt_mask" in diag and "raster_minx" in diag:
        band_raster = {
            "mask": diag["asphalt_mask"],
            "minx": diag["raster_minx"],
            "miny": diag["raster_miny"],
            "res_m": diag["raster_res_m"],
            "W": diag["raster_W"],
            "H": diag["raster_H"],
        }

    try:
        result = build_triangulated_surface(
            left_xy, right_xy, spine_xy=spine_xy, s_grid=s_grid,
            band_mask_raster=band_raster,
        )
    except Exception as exc:
        logger.warning(
            "triangulation FAILED for canonical_id=%s: %s", canonical_id, exc,
        )
        return None

    logger.info(
        "triangulation cached for canonical_id=%s: V=%d T=%d min_area=%.4fm² "
        "max_area=%.4fm² slivers_dropped=%d sha=%s",
        canonical_id, result["vertex_count"], result["triangle_count"],
        result["min_signed_area_m2"], result["max_signed_area_m2"],
        result["sliver_count_dropped"], result["sha256"][:12],
    )
    return {
        "canonical_id": canonical_id,
        "vertices_xy_internal": result["vertices_xy"],
        "indices": result["indices"],
        "sn_per_vertex": result["sn_per_vertex"],
        "spine_perimeter_m": spine_perim,
        "spine_lat_ref_rad": lat_r,
        "spine_lon_ref_rad": lon_r,
        "triangle_count": result["triangle_count"],
        "vertex_count": result["vertex_count"],
        "min_signed_area_m2": result["min_signed_area_m2"],
        "max_signed_area_m2": result["max_signed_area_m2"],
        "median_signed_area_m2": result["median_signed_area_m2"],
        "inverted_count_post_orient": result["inverted_count_post_orient"],
        "sliver_count_dropped": result["sliver_count_dropped"],
        "sha256": result["sha256"],
        "seal_diag": result.get("seal_diag"),
    }


def lookup_per_vertex_grip(
    sn_per_vertex: np.ndarray,
    surface_bins: Optional[list[dict[str, Any]]],
    spatial_modifier: Optional[dict[str, Any]],
    spine_perimeter_m: float,
) -> tuple[np.ndarray, list[str]]:
    """Per-vertex grip from 2D field (where available), else 1D fallback.

    Sources, in priority order per spec:
      1. ``2d_combined``  — 1D mu_lat_p95(s) × 2D factor_field_2d(s, n)
         (bilinear-interpolated). Used when surface_bins has data AND
         spatial_modifier.factor_field_2d is populated.
      2. ``meteo_default``— factor_field_2d(s, n) × 1.0 default mu
         (no measured grip for this s; meteo modifier still varies
         laterally per tile so we preserve the n-direction signal).
      3. ``1d_fallback``  — mu_lat_p95(s) only, n ignored
         (2D modifier absent — flagged so caller can surface that the
         2D meteo layer isn't producing per-tile values).
      4. ``default``      — fixed 1.0, no measured or modelled data.

    Lookup is clamped to the (s, n) field range so the apex boundary-
    vertex n-overshoot (-8.4/+7.91 vs hw_max 7.77) never misses.

    Returns (grip_per_vertex, source_per_vertex) — same length V.
    """
    V = len(sn_per_vertex)
    grip = np.full(V, 1.0, dtype=float)
    source = ["default"] * V

    # 1D mu_lat_p95(s) — interp on a sorted bins array.
    mu_1d_avail = False
    if surface_bins:
        dist_arr = np.array([b.get("distance_m", 0.0) for b in surface_bins], dtype=float)
        mu_arr = np.array([b.get("mu_lat_p95", 0.0) for b in surface_bins], dtype=float)
        order = np.argsort(dist_arr)
        dist_arr = dist_arr[order]
        mu_arr = mu_arr[order]
        if len(dist_arr) >= 2:
            mu_1d_avail = True
        # Clamp s to [0, max_dist] so vertices with s slightly negative
        # (-0.47 m at the seam) or s > perim still get a value.
        s_max = float(dist_arr[-1]) if len(dist_arr) else spine_perimeter_m
        s_v_clamped = np.clip(sn_per_vertex[:, 0] % spine_perimeter_m, 0.0, s_max)
        mu_1d_per_v = np.interp(s_v_clamped, dist_arr, mu_arr)
    else:
        mu_1d_per_v = np.zeros(V)

    # 2D factor_field_2d(s, n) — bilinear from M×K grid.
    f2d_avail = False
    f2d_per_v = np.ones(V)
    if spatial_modifier:
        field_flat = spatial_modifier.get("factor_field_2d")
        s_bins = spatial_modifier.get("tile_arclength_samples")
        n_bins = spatial_modifier.get("tile_lateral_offsets")
        shape = spatial_modifier.get("tile_grid_shape")
        if field_flat and s_bins and n_bins and shape:
            try:
                M_s, M_n = int(shape[0]), int(shape[1])
                field = np.asarray(field_flat, dtype=float).reshape(M_s, M_n)
                s_arr = np.asarray(s_bins, dtype=float)
                n_arr = np.asarray(n_bins, dtype=float)
                # Clamp the per-vertex (s, n) into the field bounds.
                s_v = np.clip(sn_per_vertex[:, 0] % spine_perimeter_m,
                              s_arr.min(), s_arr.max())
                n_v = np.clip(sn_per_vertex[:, 1], n_arr.min(), n_arr.max())
                # Bilinear: find surrounding indices in s and n.
                si = np.clip(np.searchsorted(s_arr, s_v) - 1, 0, M_s - 2)
                ni = np.clip(np.searchsorted(n_arr, n_v) - 1, 0, M_n - 2)
                s0 = s_arr[si]; s1 = s_arr[si + 1]
                n0 = n_arr[ni]; n1 = n_arr[ni + 1]
                ws = (s_v - s0) / np.where(s1 - s0 > 1e-9, s1 - s0, 1e-9)
                wn = (n_v - n0) / np.where(n1 - n0 > 1e-9, n1 - n0, 1e-9)
                v00 = field[si, ni]
                v10 = field[si + 1, ni]
                v01 = field[si, ni + 1]
                v11 = field[si + 1, ni + 1]
                f2d_per_v = (
                    v00 * (1 - ws) * (1 - wn)
                    + v10 * ws * (1 - wn)
                    + v01 * (1 - ws) * wn
                    + v11 * ws * wn
                )
                f2d_avail = True
            except Exception as exc:
                logger.warning("factor_field_2d lookup failed: %s", exc)

    # Combine per spec.
    if f2d_avail and mu_1d_avail:
        grip = mu_1d_per_v * f2d_per_v
        source = ["2d_combined"] * V
    elif f2d_avail:
        grip = f2d_per_v  # default mu = 1.0 implicit
        source = ["meteo_default"] * V
    elif mu_1d_avail:
        grip = mu_1d_per_v
        source = ["1d_fallback"] * V
    else:
        grip = np.full(V, 1.0)
        source = ["default"] * V

    return grip, source
