"""
track_surface/builder.py
------------------------
Top-level orchestrator that builds a TrackSurface from multi-lap telemetry.

Coordinates: normalisation -> centerline extraction -> Frenet frame ->
boundary/elevation/camber/grip estimation, with graceful degradation
based on available data.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from track_surface.boundary import _gt_project_to_xy, estimate_boundaries_with_source
from track_surface.centerline import extract_centerline
from track_surface.corridor_filter import filter_samples_in_corridor
from track_surface.elevation import (
    build_elevation_profile,
    build_elevation_surface,
    compute_vertical_curvature,
    detect_curbs,
    estimate_camber,
)
from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import build_grip_surface
from track_surface.gt_loader import (
    GroundTruth, load_gt, refresh_runtime_gt_if_configured,
    resolve_canonical_via_pg, resolve_track_id,
)
from track_surface.model import TrackSurface
from track_surface.normalizer import detect_coordinate_system, normalize_positions

logger = logging.getLogger(__name__)


def _extract_lap_xy(
    laps: dict[int, pd.DataFrame],
    adapter_format: str,
) -> tuple[list[np.ndarray], list[np.ndarray], list[pd.DataFrame], list[float]]:
    """Normalise positions for each lap.

    Returns
    -------
    (xy_list, z_list, enriched_laps, lap_times_s) where:
    - xy_list: list of (N_i, 2) horizontal position arrays
    - z_list: list of (N_i,) elevation arrays
    - enriched_laps: DataFrames with x_m, y_m, z_m columns added
    - lap_times_s: per-lap duration in seconds (max time minus min time
      within each lap's samples; NaN if the lap has no parseable time
      column). Parallel to xy_list. Day-8 addition for time-based
      out-lap rejection in extract_centerline.
    """
    coord_sys = detect_coordinate_system(adapter_format)
    xy_list = []
    z_list = []
    enriched = []
    lap_times_s: list[float] = []

    for lap_num, df in sorted(laps.items()):
        x, y, z, meta = normalize_positions(df, coord_sys)

        # Skip laps with no valid position data
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() < 20:
            continue

        xy = np.column_stack([x[valid], y[valid]])
        xy_list.append(xy)
        z_list.append(z[valid])

        # Per-lap duration. Use the canonical 'time_s' column when present
        # (post normalize_columns); fall back to raw 'Time (s)' for adapters
        # that haven't been normalised yet.
        t_col = None
        for cand in ("time_s", "Time (s)"):
            if cand in df.columns:
                t_col = cand
                break
        if t_col is not None:
            t = pd.to_numeric(df[t_col], errors="coerce").to_numpy()
            t_finite = t[np.isfinite(t)]
            lap_times_s.append(
                float(t_finite.max() - t_finite.min()) if t_finite.size else float("nan")
            )
        else:
            lap_times_s.append(float("nan"))

        # Enrich DataFrame with normalised coords for downstream
        enriched_df = df.copy()
        enriched_df["x_m"] = x
        enriched_df["y_m"] = y
        enriched_df["z_m"] = z
        enriched.append(enriched_df)

    return xy_list, z_list, enriched, lap_times_s


def _compute_global_gps_ref(
    laps: dict[int, pd.DataFrame],
    coord_sys: str,
) -> tuple[float | None, float | None]:
    """Compute global lat_ref_rad/lon_ref_rad from union of all lap GPS samples.

    Used as the projection reference for hand-traced gt boundaries so the
    projected polylines share a frame with centerline_xy (modulo the O(1m)
    per-lap-mean residual inside _extract_lap_xy).

    Returns (None, None) for non-GPS coord systems (Cartesian sim sources have
    no lat/lon to use — hand_traced path is GPS-only for now).
    """
    if coord_sys != "gps":
        return None, None

    lats: list[np.ndarray] = []
    lons: list[np.ndarray] = []
    for df in laps.values():
        if "lat_deg" in df.columns and "lon_deg" in df.columns:
            lats.append(pd.to_numeric(df["lat_deg"], errors="coerce").to_numpy())
            lons.append(pd.to_numeric(df["lon_deg"], errors="coerce").to_numpy())
        elif "Latitude (deg)" in df.columns and "Longitude (deg)" in df.columns:
            lats.append(pd.to_numeric(df["Latitude (deg)"], errors="coerce").to_numpy())
            lons.append(pd.to_numeric(df["Longitude (deg)"], errors="coerce").to_numpy())

    if not lats:
        return None, None

    all_lat = np.concatenate(lats)
    all_lon = np.concatenate(lons)
    finite = np.isfinite(all_lat) & np.isfinite(all_lon)
    if not finite.any():
        return None, None

    return (
        float(np.deg2rad(np.mean(all_lat[finite]))),
        float(np.deg2rad(np.mean(all_lon[finite]))),
    )


def build_track_surface(
    laps: dict[int, pd.DataFrame],
    track_id: str,
    adapter_format: str,
) -> TrackSurface:
    """Build a TrackSurface from multi-lap canonical telemetry DataFrames.

    Parameters
    ----------
    laps : dict mapping lap_number to DataFrame with canonical channel columns.
    track_id : identifier for this track.
    adapter_format : adapter FORMAT_NAME (e.g. "iracing", "ac", "lmu").

    Returns
    -------
    TrackSurface with quality that scales with the number of laps provided.

    Raises
    ------
    ValueError : if no valid laps with position data are provided.
    """
    # 0. Cross-process GT cache staleness guard (final-review finding I1):
    #    a bless (onboarding/bless_service.py) can happen in the WEB process
    #    while THIS build runs in a separate Celery pipeline worker whose
    #    gt_loader cache may still hold a stale pre-bless miss. Refresh
    #    unconditionally when GT_RUNTIME_DIR is configured, before load_gt
    #    is ever called below -- negligible cost next to the rest of this
    #    build. No-op (and no behavior change) when GT_RUNTIME_DIR is unset.
    refresh_runtime_gt_if_configured()

    # 1. Normalise positions
    xy_list, z_list, enriched_laps, lap_times_s = _extract_lap_xy(laps, adapter_format)
    n_laps = len(xy_list)

    if n_laps == 0:
        raise ValueError("No valid laps with position data for track surface")

    logger.info("Building track surface: track=%s, laps=%d, format=%s",
                track_id, n_laps, adapter_format)

    # 1b. Resolve the global GPS reference (used for both gt midline
    #     projection in step 2 and corridor-filter gt boundaries in step 4b).
    coord_sys = detect_coordinate_system(adapter_format)
    lat_ref_rad, lon_ref_rad = _compute_global_gps_ref(laps, coord_sys)

    # 1c. Stage 1 of the gt-anchor re-architecture: try to load gt for this
    #     track and project its midline into the session-local frame. When
    #     successful, the midline becomes the Frenet centerline below (frame
    #     anchored to the actual track geometry, not the driven median).
    #     When it fails (no gt file, midline failed to compute, non-GPS
    #     adapter), we fall through to the legacy driven-median centerline.
    gt: GroundTruth | None = None
    gt_centerline_xy: np.ndarray | None = None
    if coord_sys == "gps" and lat_ref_rad is not None and lon_ref_rad is not None:
        # track_id may be either a registry alias (e.g., "kct") or a PG UUID
        # like "2063bb27-893". Try the alias lookup first; on miss, fall
        # back to the PG bridge that joins on tracks.canonical_id (added
        # in migration 060). Same dual-path pattern as
        # estimate_boundaries_with_source uses for the legacy hand_traced
        # boundary path.
        canonical_id = resolve_track_id(track_id) or resolve_canonical_via_pg(track_id)
        if canonical_id is not None:
            gt = load_gt(canonical_id)
            if gt is not None and gt.gt_centerline_lonlat is not None:
                gt_centerline_xy = _gt_project_to_xy(
                    gt.gt_centerline_lonlat, lat_ref_rad, lon_ref_rad,
                )
                if gt_centerline_xy is None or len(gt_centerline_xy) < 2:
                    logger.warning(
                        "gt midline projection collapsed for track_id=%r — "
                        "falling back to driven-median frame", track_id,
                    )
                    gt_centerline_xy = None

    # 1d. centerline_pred sanity cross-check (WARN-only, never gates).
    #     Compares the midpoint-walk midline against the gt file's
    #     pipeline-predicted centerline via closest-point distance
    #     (rotation-invariant). > ~2m median divergence likely indicates
    #     a gt tracing issue worth re-checking.
    if (
        gt is not None
        and gt.centerline_pred_polyline
        and gt.gt_centerline_lonlat
        and lat_ref_rad is not None and lon_ref_rad is not None
    ):
        pred_xy = _gt_project_to_xy(gt.centerline_pred_polyline, lat_ref_rad, lon_ref_rad)
        mid_xy = _gt_project_to_xy(gt.gt_centerline_lonlat, lat_ref_rad, lon_ref_rad)
        if len(pred_xy) >= 2 and len(mid_xy) >= 2:
            diff = mid_xy[:, None, :] - pred_xy[None, :, :]
            d = np.sqrt((diff ** 2).sum(axis=2))
            nearest = d.min(axis=1)
            median_div = float(np.median(nearest))
            max_div = float(nearest.max())
            if median_div > 2.0:
                logger.warning(
                    "centerline_pred cross-check: midline diverges from "
                    "prediction by median=%.2fm max=%.2fm — gt tracing may "
                    "need re-check (canonical_id=%s)",
                    median_div, max_div, gt.canonical_track_id,
                )
            else:
                logger.info(
                    "centerline_pred cross-check: median=%.2fm max=%.2fm "
                    "(canonical_id=%s)",
                    median_div, max_div, gt.canonical_track_id,
                )

    surface_frame = "gt_anchored" if gt_centerline_xy is not None else "driven_median"

    # 2. Centerline construction. gt-anchored: midline IS the centerline.
    #    driven-median: legacy extract_centerline RC1 7-stage pipeline.
    if surface_frame == "gt_anchored":
        cl_xy = gt_centerline_xy
        seg = np.sqrt(((np.diff(cl_xy, axis=0)) ** 2).sum(axis=1))
        total_length = float(seg.sum())
        gt_diag = gt.gt_midline_diagnostics or {}
        gt_warns = gt_diag.get("warnings") or []
        logger.info(
            "surface_frame=gt_anchored: midline_source=%s width_source=%s "
            "(canonical_id=%s, midline_pts=%d, total_length_m=%.1f, "
            "gt_warns=%d)",
            gt_diag.get("midline_source", "?"),
            gt_diag.get("width_source", "?"),
            gt.canonical_track_id, len(cl_xy), total_length, len(gt_warns),
        )
    else:
        times_arg = lap_times_s if any(np.isfinite(t) for t in lap_times_s) else None
        cl_xy, total_length = extract_centerline(
            xy_list, ds_m=0.5, lap_times_s=times_arg,
        )
        logger.info(
            "surface_frame=driven_median: extract_centerline produced "
            "%d pts, total_length_m=%.1f",
            len(cl_xy), total_length,
        )

    # 3. Build Frenet frame
    frenet = FrenetFrame.from_centerline(cl_xy)

    # 4. Project all laps to (s, n, z)
    laps_sn = []
    laps_sz = []
    laps_snz = []
    for xy, z in zip(xy_list, z_list):
        s, n = frenet.xy_to_sn(xy[:, 0], xy[:, 1])
        laps_sn.append((s, n))
        laps_sz.append((s, z))
        laps_snz.append((s, n, z))

    # 4b. RC2 corridor filter (Day-8 Phase C). Reject off-corridor samples
    #     before boundary / elevation / camber / curb estimation. Uses the
    #     gt-polygon-mask path when hand-traced gt is available for this
    #     track; falls back to per-s-bin MAD on the lap samples otherwise.
    #     enriched_laps is intentionally NOT filtered — grip_2d's per-bin
    #     statistics are already robust to the small fraction of off-track
    #     samples, and filtering DataFrames would require row-index mapping
    #     back through normalize_positions' valid mask.
    #     gt + lat_ref_rad/lon_ref_rad already resolved in step 1b-1c.
    gt_left_xy = gt_right_xy = None
    if gt is not None and lat_ref_rad is not None and lon_ref_rad is not None:
        gt_left_xy = _gt_project_to_xy(
            gt.left_polyline, lat_ref_rad, lon_ref_rad,
        )
        gt_right_xy = _gt_project_to_xy(
            gt.right_polyline, lat_ref_rad, lon_ref_rad,
        )

    lap_sizes = [xy.shape[0] for xy in xy_list]
    all_xy = np.vstack(xy_list)
    kept_mask, corridor_meta = filter_samples_in_corridor(
        all_xy, frenet,
        gt_left_xy=gt_left_xy, gt_right_xy=gt_right_xy,
    )
    logger.info(
        "Corridor filter: method=%s, kept %d/%d (%.1f%% rejected)",
        corridor_meta["method"], corridor_meta["n_kept"],
        corridor_meta["n_total"], corridor_meta["reject_pct"],
    )

    laps_sn_filt: list[tuple[np.ndarray, np.ndarray]] = []
    laps_sz_filt: list[tuple[np.ndarray, np.ndarray]] = []
    laps_snz_filt: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    cursor = 0
    for i, n_samples in enumerate(lap_sizes):
        lap_mask = kept_mask[cursor: cursor + n_samples]
        s_i, n_i = laps_sn[i]
        laps_sn_filt.append((s_i[lap_mask], n_i[lap_mask]))
        s_i, z_i = laps_sz[i]
        laps_sz_filt.append((s_i[lap_mask], z_i[lap_mask]))
        s_i, n_i, z_i = laps_snz[i]
        laps_snz_filt.append((s_i[lap_mask], n_i[lap_mask], z_i[lap_mask]))
        cursor += n_samples
    laps_sn = laps_sn_filt
    laps_sz = laps_sz_filt
    laps_snz = laps_snz_filt

    # 5. Boundaries. gt-anchored: widths are NATIVE outputs of the midline
    #    midpoint-walk (perpendicular distances midline→left, midline→right),
    #    resampled from the gt's 300-station grid onto frenet.s_grid via
    #    arclength interpolation. No projection of gt polylines onto a
    #    different centerline frame — eliminates the entire class of
    #    coordinate-mismatch bugs that the legacy hand_traced path battled.
    #    driven-median: legacy estimate_boundaries_with_source — picks
    #    hand_traced (gt projected onto driven centerline) when available,
    #    falls back to data_derived percentile envelope otherwise.
    if surface_frame == "gt_anchored":
        gt_n = len(gt.gt_width_left_m)
        gt_s_stations = np.linspace(0.0, frenet.total_length_m, gt_n)
        width_left = np.interp(frenet.s_grid, gt_s_stations, gt.gt_width_left_m)
        width_right = np.interp(frenet.s_grid, gt_s_stations, gt.gt_width_right_m)
        boundary_source = "gt_anchored_native"
        side_swap = False
        logger.info(
            "boundaries: gt_anchored_native (width_left median=%.2fm max=%.2fm; "
            "width_right median=%.2fm max=%.2fm)",
            float(np.median(width_left)), float(np.max(width_left)),
            float(np.median(width_right)), float(np.max(width_right)),
        )
    else:
        boundaries = estimate_boundaries_with_source(
            frenet, laps_sn,
            track_id=track_id,
            lat_ref_rad=lat_ref_rad,
            lon_ref_rad=lon_ref_rad,
        )
        if boundaries is not None:
            width_left, width_right, boundary_source, side_swap = boundaries
        else:
            width_left = width_right = None
            boundary_source = None
            side_swap = False

    # 5b. n_range_m for the 2D field grids (elevation_surface, grip_2d).
    #     gt-anchored: bound by the actual track's max half-width + 1m
    #     margin. Shrinks the grid from the legacy ±8m envelope to the
    #     real track interior. driven-median: legacy ±8m default preserved.
    if surface_frame == "gt_anchored":
        max_half_width_m = max(
            float(np.nanmax(gt.gt_width_left_m)) if gt.gt_width_left_m is not None else 0.0,
            float(np.nanmax(gt.gt_width_right_m)) if gt.gt_width_right_m is not None else 0.0,
        )
        n_range_m_eff = max(max_half_width_m + 1.0, 4.0)  # never below 4m
        logger.info(
            "n_range_m derived from gt widths: max_half_width=%.2fm → "
            "n_range_m_eff=%.2fm (legacy default was 8.0m)",
            max_half_width_m, n_range_m_eff,
        )
    else:
        n_range_m_eff = 8.0

    # 6. Elevation + vertical curvature (if z-data available)
    has_z = any(np.any(np.abs(z) > 0.01) for _, z in laps_sz)
    elevation_m = None
    slope_pct = None
    vert_curvature = None
    if has_z:
        elevation_m, slope_pct = build_elevation_profile(frenet, laps_sz)
        vert_curvature = compute_vertical_curvature(elevation_m, frenet.s_grid)

    # 7. Camber (>= 5 laps with lateral spread)
    camber_rad = None
    if n_laps >= 5:
        camber_est = estimate_camber(frenet, laps_snz)
        if np.any(np.abs(camber_est) > 1e-4):
            camber_rad = camber_est

    # 8. 3D elevation surface z(s,n) + curb detection (>= 3 laps with z)
    elev_surface = None
    curbs = None
    if has_z and n_laps >= 3:
        elev_surface = build_elevation_surface(frenet, laps_snz, n_range_m=n_range_m_eff)
        if elev_surface is not None:
            curbs = detect_curbs(elev_surface)

    # 9. 2D grip (>= 10 laps) — uses vertical curvature for terrain-corrected mu
    grip_2d = None
    if n_laps >= 5:
        grip_2d = build_grip_surface(
            frenet, enriched_laps,
            s_bin_m=2.0, n_bin_m=0.5, n_range_m=n_range_m_eff,
            vert_curvature=vert_curvature,
        )

    # 10. Assemble
    surface = TrackSurface(
        track_id=track_id,
        frenet=frenet,
        width_left=width_left,
        width_right=width_right,
        elevation_m=elevation_m,
        slope_pct=slope_pct,
        vert_curvature_1pm=vert_curvature,
        camber_rad=camber_rad,
        elevation_surface=elev_surface,
        curbs=curbs,
        grip_2d=grip_2d,
        n_laps=n_laps,
        sim_sources=[adapter_format],
        boundary_source=boundary_source,
        boundary_side_swap=side_swap,
    )

    logger.info(
        "Track surface built: tier=%s, length=%.0fm, laps=%d, boundary_source=%s",
        surface.quality_tier, frenet.total_length_m, n_laps,
        surface.boundary_source,
    )
    return surface
