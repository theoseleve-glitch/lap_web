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


# ── EXEC-7: per-vertex SPEED channel (lap-specific) ──────────────────
# Bin the selected lap's MAX speed into the SAME (s, n) grid scheme as
# grip_2d (searchsorted-1 clipped), but with finer bins and NaN — not
# grip's 1.0 — for empty cells, then attach one value per mesh vertex.
_SPEED_S_BIN_M = 2.0
_SPEED_N_BIN_M = 0.5

# Grip (mu = |a_lat| / g) dynamics-inversion constants — values match
# grip_2d.build_grip_surface so request-time per-tile grip agrees with the
# offline producer (gravity + min-speed gate + plausible-mu band).
_G = 9.80665
_MIN_SPEED_MPS = 3.0
_GRIP_MIN_SAMPLES = 5   # mirror _per_vertex_speed's <5 usable-sample guard
_GRIP_MU_MIN = 0.1
_GRIP_MU_MAX = 3.0


def _resolve_best_lap(conn: Any, session_id: str) -> Optional[int]:
    """Best lap number for the session (is_best flag), else the first lap."""
    try:
        from web.repos.lap_repo import get_laps_for_session
        laps = get_laps_for_session(conn, session_id) or []
    except Exception as exc:
        logger.warning("resolve_best_lap: get_laps_for_session failed: %s", exc)
        return None
    for lap in laps:
        if isinstance(lap, dict) and lap.get("is_best"):
            return int(lap["lap_number"])
    if laps and isinstance(laps[0], dict) and "lap_number" in laps[0]:
        return int(laps[0]["lap_number"])
    return None


def _per_vertex_speed(
    frenet: Any,
    verts_session: np.ndarray,
    gps_x: np.ndarray,
    gps_y: np.ndarray,
    gps_speed: np.ndarray,
) -> Optional[tuple[list, float]]:
    """Bin max GPS speed into a (M_s × K_n) grid (grip_2d scheme) and read one
    value per mesh vertex — its own cell, else the max non-NaN within ±1 cell,
    else NaN. GPS points AND mesh vertices are projected through the SAME
    ``frenet`` so they share the (s, n) frame (sidesteps any gt-internal vs
    session-frame arclength drift). Returns (speed_per_vertex_with_None,
    max_mps), or None when the lap has too little usable GPS.
    """
    total = float(getattr(frenet, "total_length_m", 0.0) or 0.0)
    if total <= 0:
        return None
    s_g, n_g = frenet.xy_to_sn(gps_x, gps_y)
    s_v, n_v = frenet.xy_to_sn(verts_session[:, 0], verts_session[:, 1])
    s_g = np.asarray(s_g, dtype=float)
    n_g = np.asarray(n_g, dtype=float)
    sp = np.asarray(gps_speed, dtype=float)
    ok = np.isfinite(s_g) & np.isfinite(n_g) & np.isfinite(sp)
    if int(ok.sum()) < 5:
        return None
    s_g, n_g, sp = s_g[ok], n_g[ok], sp[ok]
    n_v = np.asarray(n_v, dtype=float)
    n_v_fin = n_v[np.isfinite(n_v)]
    n_extent = float(max(
        float(np.abs(n_g).max()),
        float(np.abs(n_v_fin).max()) if n_v_fin.size else 0.0,
    ))
    n_range = n_extent + _SPEED_N_BIN_M
    s_bins = np.arange(0.0, total, _SPEED_S_BIN_M)
    n_bins = np.arange(-n_range, n_range + _SPEED_N_BIN_M, _SPEED_N_BIN_M)
    M, K = len(s_bins), len(n_bins)
    if M < 1 or K < 1:
        return None
    grid = np.full((M, K), np.nan)
    si = np.clip(np.searchsorted(s_bins, s_g) - 1, 0, M - 1)
    ni = np.clip(np.searchsorted(n_bins, n_g) - 1, 0, K - 1)
    for a, b, v in zip(si.tolist(), ni.tolist(), sp.tolist()):
        cur = grid[a, b]
        if np.isnan(cur) or v > cur:
            grid[a, b] = v  # MAX speed per cell
    vsi = np.clip(np.searchsorted(s_bins, np.asarray(s_v, dtype=float)) - 1, 0, M - 1)
    vni = np.clip(np.searchsorted(n_bins, n_v) - 1, 0, K - 1)
    out: list = []
    for a, b in zip(vsi.tolist(), vni.tolist()):
        val = grid[a, b]
        if np.isnan(val):
            best = np.nan
            for da in (-1, 0, 1):
                for db in (-1, 0, 1):
                    aa, bb = a + da, b + db
                    if 0 <= aa < M and 0 <= bb < K:
                        cell = grid[aa, bb]
                        if not np.isnan(cell) and (np.isnan(best) or cell > best):
                            best = cell
            val = best
        out.append(None if np.isnan(val) else float(val))
    max_mps = float(np.nanmax(sp)) if np.isfinite(sp).any() else 0.0
    return out, max_mps


def _per_vertex_grip_measured(
    frenet: Any,
    verts_session: np.ndarray,
    gps_x: np.ndarray,
    gps_y: np.ndarray,
    accel_lat_mps2: np.ndarray,
    gps_speed: np.ndarray,
) -> Optional[tuple[list, int]]:
    """Per-vertex MEASURED grip (mu = |a_lat| / g), null where undriven.

    Mirrors ``_per_vertex_speed``: bins a per-sample quantity into the SAME
    (s, n) grid scheme (searchsorted-1 clipped) and reads one value per mesh
    vertex — its own cell, else the mean of non-empty cells within ±1, else
    ``None``. The binned quantity is the dynamics-inversion grip
    ``mu = |a_lat| / g`` (same as ``grip_2d.build_grip_surface``), and the
    per-cell reducer is the p95 of all pooled samples (the caller
    concatenates every lap of the session), so a cell reads the peak
    sustained grip the surface delivered — matching ``mu_lat_p95``, not mean
    utilisation. Quality gates match
    grip_2d: ``speed > _MIN_SPEED_MPS`` and ``_GRIP_MU_MIN < mu < _GRIP_MU_MAX``.

    GPS samples AND mesh vertices are projected through the SAME ``frenet`` so
    they share the (s, n) frame; ``n_range`` spans both extents so an
    off-line vertex lands in its own (empty -> None) cell instead of clipping
    onto a driven edge cell. Returns ``(grip_per_vertex_with_None, n_measured)``
    or ``None`` when too few usable samples exist.
    """
    total = float(getattr(frenet, "total_length_m", 0.0) or 0.0)
    if total <= 0:
        return None
    s_g, n_g = frenet.xy_to_sn(gps_x, gps_y)
    s_v, n_v = frenet.xy_to_sn(verts_session[:, 0], verts_session[:, 1])
    s_g = np.asarray(s_g, dtype=float)
    n_g = np.asarray(n_g, dtype=float)
    mu = np.abs(np.asarray(accel_lat_mps2, dtype=float)) / _G
    spd = np.asarray(gps_speed, dtype=float)
    ok = (
        np.isfinite(s_g) & np.isfinite(n_g) & np.isfinite(mu)
        & (spd > _MIN_SPEED_MPS) & (mu > _GRIP_MU_MIN) & (mu < _GRIP_MU_MAX)
    )
    if int(ok.sum()) < _GRIP_MIN_SAMPLES:
        return None
    s_g, n_g, mu = s_g[ok], n_g[ok], mu[ok]

    n_v = np.asarray(n_v, dtype=float)
    n_v_fin = n_v[np.isfinite(n_v)]
    n_extent = float(max(
        float(np.abs(n_g).max()),
        float(np.abs(n_v_fin).max()) if n_v_fin.size else 0.0,
    ))
    n_range = n_extent + _SPEED_N_BIN_M
    s_bins = np.arange(0.0, total, _SPEED_S_BIN_M)
    n_bins = np.arange(-n_range, n_range + _SPEED_N_BIN_M, _SPEED_N_BIN_M)
    M, K = len(s_bins), len(n_bins)
    if M < 1 or K < 1:
        return None

    # Pool every sample into its (s, n) cell, then take the p95 per cell.
    cells: dict = {}
    si = np.clip(np.searchsorted(s_bins, s_g) - 1, 0, M - 1)
    ni = np.clip(np.searchsorted(n_bins, n_g) - 1, 0, K - 1)
    for a, b, v in zip(si.tolist(), ni.tolist(), mu.tolist()):
        cells.setdefault((int(a), int(b)), []).append(v)
    # p95 mu per cell — peak sustained lateral load (matches grip_2d.mu_lat_p95),
    # not mean utilisation.
    cell_p95 = {k: float(np.percentile(vs, 95)) for k, vs in cells.items()}

    vsi = np.clip(np.searchsorted(s_bins, np.asarray(s_v, dtype=float)) - 1, 0, M - 1)
    vni = np.clip(np.searchsorted(n_bins, n_v) - 1, 0, K - 1)
    out: list = []
    n_measured = 0
    for a, b in zip(vsi.tolist(), vni.tolist()):
        a = int(a)
        b = int(b)
        val = cell_p95.get((a, b))
        if val is None:
            # nearest measured within ±1 cell (mean of available neighbours)
            acc = 0.0
            cnt = 0
            for da in (-1, 0, 1):
                for db in (-1, 0, 1):
                    nv = cell_p95.get((a + da, b + db))
                    if nv is not None:
                        acc += nv
                        cnt += 1
            val = acc / cnt if cnt else None
        if val is None:
            out.append(None)
        else:
            out.append(float(val))
            n_measured += 1
    return out, n_measured


def build_edge_payload(
    conn: Any,
    session_id: str,
    track_id: str,
    surface: Optional[dict] = None,
    lap_number: Optional[int] = None,
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

            # s_grid (per spine station) for the mesh_spine_s emission below.
            # EXEC-10: the full M×K mesh_grid_sn was dropped — the FE renders
            # the Delaunay path (mesh_tri_*) and never reads the full grid, so
            # it was dead payload. mesh_spine_s / hw_L / hw_R still feed the
            # FE's M×K fallback (buildMxKMesh) when the Delaunay path is absent.
            s_grid = np.asarray(frenet.s_grid, dtype=float)

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
            # EXEC-10: mesh_grid_xy / mesh_grid_sn no longer emitted — dead
            # payload (FE renders mesh_tri_*; the M×K fallback derives its grid
            # FE-side from mesh_spine/L/R). Trims ~2·M·K floats per response.
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

            # ── EXEC-7: per-vertex SPEED for the selected lap ─────────
            # Lap-specific channel; the geometry + grip above are lap-
            # independent (frame = best-lap projection: verts_session +
            # frenet). Only the speed VALUES vary by lap. Any failure here
            # leaves SPEED grey on the FE — never breaks the surface payload.
            try:
                speed_lap = (
                    lap_number if lap_number is not None
                    else _resolve_best_lap(conn, session_id)
                )
                if speed_lap is not None:
                    from web.repos import gps_repo
                    gps = gps_repo.get_gps_trace(conn, session_id, int(speed_lap))
                    if gps:
                        lats = gps.get("latitudes") or []
                        lons = gps.get("longitudes") or []
                        spd = gps.get("speeds") or []
                        if lats and lons and spd and len(lats) == len(lons) == len(spd):
                            gxy = _project_lonlat_to_xy(
                                list(zip(lons, lats)), lat_ref_rad, lon_ref_rad,
                            )
                            res = _per_vertex_speed(
                                frenet, verts_session,
                                gxy[:, 0], gxy[:, 1],
                                np.asarray(spd, dtype=float),
                            )
                            if res is not None:
                                speed_list, max_mps = res
                                payload["mesh_tri_speed"] = speed_list
                                payload["mesh_tri_speed_lap"] = int(speed_lap)
                                payload["mesh_tri_speed_max_mps"] = max_mps
            except Exception as exc:
                logger.warning(
                    "edge_payload: SPEED channel failed (%s) — FE shows grey speed",
                    exc,
                )

            # ── Per-tile MEASURED grip (lap-aggregate; null where undriven) ──
            # mu = |a_lat|/g binned into the SAME (s, n) grid as SPEED, pooled
            # across ALL of the session's laps, mean per cell, None where the
            # kart never drove. The honest, sparse-where-driven companion to
            # the dense 1D ``mesh_tri_grip`` profile above; the FE prefers this
            # for GRIP and falls back to the 1D profile when it is absent (no
            # accel_lat stored / too few usable samples). Lap-INDEPENDENT
            # (aggregates every lap) so it ignores ?lap. Any failure leaves it
            # absent — never breaks the payload.
            try:
                from web.repos import gps_repo as _gr
                from web.repos.lap_repo import get_laps_for_session as _glfs
                _laps = _glfs(conn, session_id) or []
                _gx, _gy, _al, _sp = [], [], [], []
                for _lap in _laps:
                    _ln = _lap.get("lap_number") if isinstance(_lap, dict) else None
                    if _ln is None:
                        continue
                    _t = _gr.get_gps_trace(conn, session_id, int(_ln))
                    if not _t:
                        continue
                    _la = _t.get("latitudes") or []
                    _lo = _t.get("longitudes") or []
                    _ac = _t.get("accel_lat")
                    _spd = _t.get("speeds") or []
                    if _ac is None:
                        continue  # no lateral-accel for this lap → can't invert grip
                    if len(_la) == 0 or not (len(_la) == len(_lo) == len(_ac) == len(_spd)):
                        continue
                    _xy = _project_lonlat_to_xy(list(zip(_lo, _la)), lat_ref_rad, lon_ref_rad)
                    _gx.append(_xy[:, 0])
                    _gy.append(_xy[:, 1])
                    _al.append(np.asarray(_ac, dtype=float))
                    _sp.append(np.asarray(_spd, dtype=float))
                if _gx:
                    res_g = _per_vertex_grip_measured(
                        frenet, verts_session,
                        np.concatenate(_gx), np.concatenate(_gy),
                        np.concatenate(_al), np.concatenate(_sp),
                    )
                    if res_g is not None:
                        grip_m_list, n_measured = res_g
                        payload["mesh_tri_grip_measured"] = grip_m_list
                        payload["mesh_tri_grip_measured_count"] = int(n_measured)
                        payload["mesh_tri_grip_measured_laps"] = int(len(_laps))
            except Exception as exc:
                logger.warning(
                    "edge_payload: measured-grip channel failed (%s) — "
                    "FE falls back to 1D grip profile", exc,
                )
    except Exception as exc:
        logger.warning(
            "edge_payload: Delaunay triangulation assembly failed (%s) — "
            "FE dispatcher will fall back to M×K → literal-edge", exc,
        )

    return payload
