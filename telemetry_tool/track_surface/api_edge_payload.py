"""Stage 1 Step A — API edge payload builder.

Attaches the literal hand-traced edge polylines (left + right) to the
``/sessions/<id>/track-surface`` response when the track has a gt file,
projected into the SAME local xy frame the FE uses (= mean of the
session's best-lap GPS lat/lon, equirectangular). Also pre-computes the
per-vertex ``(s, n)`` Frenet coordinates so the FE can look up colors on
the spine's 2D fields without porting FrenetFrame to JavaScript.

Output schema (merged into the TrackSurfaceResponse when present):
    left_edge_xy_local:  list[[x, y], ...]   # N_e × 2, metres in session frame
    right_edge_xy_local: list[[x, y], ...]
    left_edge_sn:        list[[s, n], ...]   # N_e × 2, metres on spine
    right_edge_sn:       list[[s, n], ...]
    midline_total_length_m: float

Returns None (caller omits fields) on any prerequisite miss:
    - canonical_id unresolvable
    - no gt file on disk
    - gt midline compute failed
    - session has no GPS data
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Mirrors track_surface.boundary._EARTH_RADIUS_M and
# track_surface.gt_loader._EARTH_RADIUS_M (kept local to avoid a circular
# dep on the boundary module; the value is fixed by GeoJSON convention).
_EARTH_RADIUS_M = 6_371_000.0


def _session_gps_ref(
    conn: Any,
    session_id: str,
) -> Optional[tuple[float, float]]:
    """Return (lat_ref_rad, lon_ref_rad) = mean(lat), mean(lon) over a lap.

    Matches the FE's ``projectGPS`` convention in
    ``lap-website/.../TrackSurface3D.tsx`` so projected gt edges land in
    the exact same xy frame the FE uses for the centerline + optimal
    line + line-delta overlays. Reads the best lap (or first lap) via
    ``web.repos.gps_repo``; returns None when GPS is unavailable.
    """
    try:
        from web.repos import gps_repo
        from web.repos.lap_repo import get_laps_for_session
    except Exception as exc:
        logger.warning("session_gps_ref: repo import failed: %s", exc)
        return None

    # Resolve lap number: prefer the best lap recorded for this session.
    # Falls back to lap 1 if no best-lap row.
    try:
        laps = get_laps_for_session(conn, session_id) or []
    except Exception as exc:
        logger.warning("session_gps_ref: get_laps_for_session failed: %s", exc)
        laps = []
    lap_num: Optional[int] = None
    for lap in laps:
        if isinstance(lap, dict) and lap.get("is_best"):
            lap_num = int(lap["lap_number"])
            break
    if lap_num is None and laps:
        first = laps[0]
        if isinstance(first, dict) and "lap_number" in first:
            lap_num = int(first["lap_number"])
    if lap_num is None:
        lap_num = 1

    try:
        trace = gps_repo.get_gps_trace(conn, session_id, lap_num)
    except Exception as exc:
        logger.warning("session_gps_ref: get_gps_trace failed: %s", exc)
        return None
    if not trace:
        return None
    lats = trace.get("latitudes") or []
    lons = trace.get("longitudes") or []
    if not lats or not lons or len(lats) != len(lons):
        return None
    lat_arr = np.asarray(lats, dtype=float)
    lon_arr = np.asarray(lons, dtype=float)
    finite = np.isfinite(lat_arr) & np.isfinite(lon_arr)
    if not finite.any():
        return None
    lat_ref = float(np.deg2rad(np.mean(lat_arr[finite])))
    lon_ref = float(np.deg2rad(np.mean(lon_arr[finite])))
    return lat_ref, lon_ref


def _project_lonlat_to_xy(
    polyline_lonlat: list[tuple[float, float]],
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> np.ndarray:
    """Equirectangular WGS84 → local XY metres. Matches FE's projectGPS."""
    if not polyline_lonlat:
        return np.empty((0, 2), dtype=float)
    arr = np.asarray(polyline_lonlat, dtype=float)
    lon_r = np.deg2rad(arr[:, 0])
    lat_r = np.deg2rad(arr[:, 1])
    x = _EARTH_RADIUS_M * (lon_r - lon_ref_rad) * np.cos(lat_ref_rad)
    y = _EARTH_RADIUS_M * (lat_r - lat_ref_rad)
    return np.column_stack([x, y])


def build_edge_payload(
    conn: Any,
    session_id: str,
    track_id: str,
    surface: Optional[dict] = None,
) -> Optional[dict]:
    """Build the literal-edge payload for the surface API response.

    Returns the dict to merge into ``surface`` (with the four new fields
    + ``midline_total_length_m``), or None when prerequisites are missing
    (caller then omits the fields entirely — FE falls back to legacy
    spine±width ribbon rendering via dispatcher null-check).
    """
    # 1. Canonical id (try alias registry, fall back to PG bridge for UUID).
    try:
        from track_surface.gt_loader import (
            load_gt, resolve_canonical_via_pg, resolve_track_id,
        )
    except Exception as exc:
        logger.warning("edge_payload: gt_loader import failed: %s", exc)
        return None

    canonical_id = resolve_track_id(track_id) or resolve_canonical_via_pg(track_id)
    if canonical_id is None:
        return None

    # 2. Load gt for this canonical id. Skip if gt missing or midline failed.
    gt = load_gt(canonical_id)
    if gt is None or gt.gt_centerline_lonlat is None:
        return None
    if not gt.left_polyline or not gt.right_polyline:
        return None

    # 3. Session GPS-mean projection ref (matches the FE's frame).
    ref = _session_gps_ref(conn, session_id)
    if ref is None:
        return None
    lat_ref_rad, lon_ref_rad = ref

    # 4. Project edges + midline to the session frame.
    left_xy = _project_lonlat_to_xy(gt.left_polyline, lat_ref_rad, lon_ref_rad)
    right_xy = _project_lonlat_to_xy(gt.right_polyline, lat_ref_rad, lon_ref_rad)
    midline_xy = _project_lonlat_to_xy(gt.gt_centerline_lonlat, lat_ref_rad, lon_ref_rad)
    if len(midline_xy) < 2 or len(left_xy) < 2 or len(right_xy) < 2:
        return None

    # 5. Build a FrenetFrame from the session-frame midline; compute per-
    #    vertex (s, n) for each edge polyline point.
    try:
        from track_surface.frenet import FrenetFrame
        frenet = FrenetFrame.from_centerline(midline_xy)
    except Exception as exc:
        logger.warning("edge_payload: FrenetFrame build failed: %s", exc)
        return None

    try:
        s_l, n_l = frenet.xy_to_sn(left_xy[:, 0], left_xy[:, 1])
        s_r, n_r = frenet.xy_to_sn(right_xy[:, 0], right_xy[:, 1])
    except Exception as exc:
        logger.warning("edge_payload: xy_to_sn failed: %s", exc)
        return None

    midline_length_m = float(frenet.total_length_m)

    payload = {
        "left_edge_xy_local":  [[float(x), float(y)] for x, y in left_xy.tolist()],
        "right_edge_xy_local": [[float(x), float(y)] for x, y in right_xy.tolist()],
        "left_edge_sn":        [[float(s), float(n)] for s, n in zip(s_l, n_l)],
        "right_edge_sn":       [[float(s), float(n)] for s, n in zip(s_r, n_r)],
        "midline_total_length_m": midline_length_m,
        "edge_source": "hand_traced_gt",
    }

    # Stage 1 medial-axis M×K grid fields. The midline_xy IS the spine
    # (sourced from gt.gt_centerline_lonlat which gt_loader populates
    # from medial_axis on success, falling back to Path E). For each
    # spine station, find the perpendicular-projected nearest L and R
    # via the spine's FrenetFrame: at station i, L_i is the spine point
    # offset by +half_width_left along +normal; R_i is offset by
    # -half_width_right. FE then K-lerps these and triangulates.
    try:
        # Half-widths from gt diagnostics (medial_axis stores per-station,
        # Path E stores all-equal). The spine-frame Frenet build above
        # gives us s_grid per spine station.
        if gt.gt_width_left_m is not None and gt.gt_width_right_m is not None:
            import numpy as np
            hw_L = np.asarray(gt.gt_width_left_m, dtype=float)
            hw_R = np.asarray(gt.gt_width_right_m, dtype=float)
            # Spine has len(midline_xy) stations; widths may have a
            # different length (medial uses M=300 stations); resample
            # widths onto the FrenetFrame's M.
            M_spine = len(midline_xy)
            if len(hw_L) != M_spine:
                src_s = np.linspace(0.0, midline_length_m, len(hw_L))
                tgt_s = np.linspace(0.0, midline_length_m, M_spine)
                hw_L = np.interp(tgt_s, src_s, hw_L)
                hw_R = np.interp(tgt_s, src_s, hw_R)

            # Pull the LAPLACIAN-SMOOTHED M×K grid built once per canonical_id
            # inside ``medial_axis.build_medial_axis_spine`` (cached via
            # ``get_medial_spine_cached``) and AFFINE-transform each xy from
            # gt-internal frame to the session frame. Replaces the prior
            # curvature clamp on hw — clamp traded inversion for collapse-
            # fan at apex inside; elliptic smoothing bends grid lines
            # smoothly around tight corners → 0 inverted tiles, no fans,
            # no gaps, boundary rows still on the real hand-traced kerbs.
            mid_diag = gt.gt_midline_diagnostics or {}
            grid_internal_list = mid_diag.get("mesh_grid_xy_internal")
            K_LATERAL = int(mid_diag.get("mesh_K") or 24)
            if grid_internal_list:
                grid_internal = np.asarray(grid_internal_list, dtype=float)
                M_grid, K_grid, _ = grid_internal.shape
                gt_lat = float(mid_diag["internal_lat_ref_rad"])
                gt_lon = float(mid_diag["internal_lon_ref_rad"])
                # gt-internal xy → WGS84 (inverse equirect with gt refs)
                # → session xy (forward equirect with session refs). The
                # composite is affine-ish; Laplacian smoothing is
                # affine-equivariant so the smoothed grid stays smooth.
                flat = grid_internal.reshape(-1, 2)
                cos_gt = float(np.cos(gt_lat))
                if abs(cos_gt) < 1e-12:
                    cos_gt = 1e-12
                lon_r_flat = gt_lon + flat[:, 0] / (_EARTH_RADIUS_M * cos_gt)
                lat_r_flat = gt_lat + flat[:, 1] / _EARTH_RADIUS_M
                x_session = (
                    _EARTH_RADIUS_M * (lon_r_flat - lon_ref_rad)
                    * float(np.cos(lat_ref_rad))
                )
                y_session = _EARTH_RADIUS_M * (lat_r_flat - lat_ref_rad)
                mesh_grid_xy = np.column_stack(
                    [x_session, y_session]
                ).reshape(M_grid, K_grid, 2)
                # Boundary rows ARE the kerbs at full DT width (Laplacian
                # holds k=0 and k=K-1 fixed). Pull from the smoothed grid.
                mesh_L_xy = mesh_grid_xy[:, 0, :]
                mesh_R_xy = mesh_grid_xy[:, K_grid - 1, :]
                K_LATERAL = K_grid
                M_grid_effective = M_grid
            else:
                # Producer didn't cache a grid (shouldn't happen post-deploy
                # for medial_axis tracks). Fall back to the simple lerp.
                ks = np.linspace(0.0, 1.0, K_LATERAL)
                ahead = np.roll(midline_xy, -1, axis=0)
                behind = np.roll(midline_xy, +1, axis=0)
                tangents = ahead - behind
                tn = np.linalg.norm(tangents, axis=1, keepdims=True)
                tangents = tangents / np.where(tn > 1e-12, tn, 1e-12)
                normals = np.column_stack([-tangents[:, 1], tangents[:, 0]])
                mesh_L_xy = midline_xy + normals * hw_L[:, None]
                mesh_R_xy = midline_xy - normals * hw_R[:, None]
                mesh_grid_xy = np.zeros((M_spine, K_LATERAL, 2), dtype=float)
                for k_idx in range(K_LATERAL):
                    t = float(ks[k_idx])
                    mesh_grid_xy[:, k_idx, :] = (
                        mesh_L_xy + t * (mesh_R_xy - mesh_L_xy)
                    )
                M_grid_effective = M_spine

            # Per-vertex (s, n) for grip-field colour lookup on the FE.
            # n stays LOGICAL (linear lerp from +hw_L to -hw_R across k);
            # the rendered physical xy is the smoothed grid. This keeps
            # the optimiser + grip cache stable (key by logical n) while
            # the rendered tube bends around apexes.
            s_grid = np.asarray(frenet.s_grid, dtype=float)
            ks = np.linspace(0.0, 1.0, K_LATERAL)
            mesh_grid_sn = np.zeros((M_grid_effective, K_LATERAL, 2), dtype=float)
            for k_idx in range(K_LATERAL):
                t = float(ks[k_idx])
                mesh_grid_sn[:, k_idx, 0] = s_grid
                mesh_grid_sn[:, k_idx, 1] = hw_L - t * (hw_L + hw_R)

            payload["mesh_spine_xy"] = [
                [float(x), float(y)] for x, y in midline_xy.tolist()
            ]
            payload["mesh_L_xy"] = [
                [float(x), float(y)] for x, y in mesh_L_xy.tolist()
            ]
            payload["mesh_R_xy"] = [
                [float(x), float(y)] for x, y in mesh_R_xy.tolist()
            ]
            payload["mesh_spine_s"] = [float(s) for s in s_grid.tolist()]
            payload["mesh_hw_L"] = [float(w) for w in hw_L.tolist()]
            payload["mesh_hw_R"] = [float(w) for w in hw_R.tolist()]
            payload["mesh_M"] = int(M_grid_effective)
            payload["mesh_K"] = K_LATERAL
            payload["mesh_spine_source"] = mid_diag.get("midline_source", "unknown")
            payload["mesh_grid_xy"] = [
                [[float(x), float(y)] for x, y in row] for row in mesh_grid_xy.tolist()
            ]
            payload["mesh_grid_sn"] = [
                [[float(s), float(n)] for s, n in row] for row in mesh_grid_sn.tolist()
            ]
            # Periodic-loop contract: mesh_spine_s is cyclic. The renderer
            # AND any downstream consumer (lap-time optimiser, line-delta
            # binner) must treat s = mesh_lap_length_m as identical to
            # s = 0. The producer emits M=300 DISTINCT stations spaced
            # ~Δs apart with NO duplicated seam; the wrap ring between
            # station M-1 and station 0 is what makes the tube watertight.
            payload["mesh_s_periodic"] = True
            payload["mesh_lap_length_m"] = float(midline_length_m)
    except Exception as exc:
        logger.warning(
            "edge_payload: M×K mesh assembly failed (%s) — FE will fall "
            "back to literal-edge or spine±width renderer", exc,
        )

    # ─── PRIMARY render path: constrained Delaunay triangulation ──────
    # Replaces the structured M×K render (which inverts at apex where
    # R_medial < hw). The triangulation touches both kerbs directly,
    # is non-inverting by construction (CCW orient + sliver filter),
    # and uses per-vertex grip from the 2D (s, n) field where the
    # producer has it. M×K fields above are kept for the LOGICAL grid
    # (optimiser + grip cache key) + as a dispatcher fallback.
    try:
        import numpy as np
        from track_surface.triangulated_surface import (
            get_triangulated_surface_cached, lookup_per_vertex_grip,
        )
        tri = get_triangulated_surface_cached(canonical_id)
        if tri is not None:
            verts_internal = np.asarray(tri["vertices_xy_internal"], dtype=float)
            indices = np.asarray(tri["indices"], dtype=int)
            sn = np.asarray(tri["sn_per_vertex"], dtype=float)
            # gt-internal → WGS84 (inverse equirect) → session-frame xy.
            gt_lat = float(tri["spine_lat_ref_rad"])
            gt_lon = float(tri["spine_lon_ref_rad"])
            cos_gt = float(np.cos(gt_lat))
            if abs(cos_gt) < 1e-12:
                cos_gt = 1e-12
            lon_r_flat = gt_lon + verts_internal[:, 0] / (_EARTH_RADIUS_M * cos_gt)
            lat_r_flat = gt_lat + verts_internal[:, 1] / _EARTH_RADIUS_M
            x_session = (
                _EARTH_RADIUS_M * (lon_r_flat - lon_ref_rad)
                * float(np.cos(lat_ref_rad))
            )
            y_session = _EARTH_RADIUS_M * (lat_r_flat - lat_ref_rad)
            verts_session = np.column_stack([x_session, y_session])

            # Per-vertex grip from 2D field where available; flagged otherwise.
            spine_perim_m = float(tri["spine_perimeter_m"])
            surface_bins = (surface or {}).get("bins") if surface else None
            cond = (surface or {}).get("conditions") if surface else None
            spatial_mod = (cond or {}).get("spatial_modifier") if cond else None
            grip_per_v, source_per_v = lookup_per_vertex_grip(
                sn, surface_bins, spatial_mod, spine_perim_m,
            )

            payload["mesh_tri_xy"] = [
                [float(x), float(y)] for x, y in verts_session.tolist()
            ]
            payload["mesh_tri_indices"] = [
                [int(a), int(b), int(c)] for a, b, c in indices.tolist()
            ]
            payload["mesh_tri_sn"] = [
                [float(s), float(n)] for s, n in sn.tolist()
            ]
            payload["mesh_tri_grip"] = [float(g) for g in grip_per_v.tolist()]
            payload["mesh_tri_grip_source"] = source_per_v
            payload["mesh_tri_vertex_count"] = int(tri["vertex_count"])
            payload["mesh_tri_triangle_count"] = int(tri["triangle_count"])
            payload["mesh_tri_min_signed_area_m2"] = float(tri["min_signed_area_m2"])
            payload["mesh_tri_sha256"] = str(tri["sha256"])
            # Grip-source distribution for the API consumer's at-a-glance check.
            from collections import Counter
            payload["mesh_tri_grip_source_counts"] = dict(Counter(source_per_v))
    except Exception as exc:
        logger.warning(
            "edge_payload: Delaunay triangulation assembly failed (%s) — "
            "FE dispatcher will fall back to M×K → literal-edge", exc,
        )

    return payload
