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
from track_surface.gt_loader import load_gt, resolve_track_id
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
    # 1. Normalise positions
    xy_list, z_list, enriched_laps, lap_times_s = _extract_lap_xy(laps, adapter_format)
    n_laps = len(xy_list)

    if n_laps == 0:
        raise ValueError("No valid laps with position data for track surface")

    logger.info("Building track surface: track=%s, laps=%d, format=%s",
                track_id, n_laps, adapter_format)

    # 2. Extract centerline. Plumb per-lap times through so the Day-7
    #    out-lap rejection can fire on time outliers (out-lap / in-lap)
    #    in addition to arclength outliers. Pass None when no parseable
    #    time column exists (graceful fallback to arclength-only).
    times_arg = lap_times_s if any(np.isfinite(t) for t in lap_times_s) else None
    cl_xy, total_length = extract_centerline(
        xy_list, ds_m=0.5, lap_times_s=times_arg,
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
    coord_sys = detect_coordinate_system(adapter_format)
    lat_ref_rad, lon_ref_rad = _compute_global_gps_ref(laps, coord_sys)

    gt_left_xy = gt_right_xy = None
    if coord_sys == "gps" and lat_ref_rad is not None and lon_ref_rad is not None:
        canonical_id = resolve_track_id(track_id)
        if canonical_id is not None:
            gt = load_gt(canonical_id)
            if gt is not None:
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

    # 5. Boundaries (>= 3 laps): prefer hand_traced gt when available, fall
    #    back to data_derived percentile×1.3 path otherwise. Track identity
    #    is threaded via the alias registry; GPS reference comes from union
    #    of all lap GPS samples (None for sim Cartesian formats — those
    #    skip the gt path).
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
        elev_surface = build_elevation_surface(frenet, laps_snz)
        if elev_surface is not None:
            curbs = detect_curbs(elev_surface)

    # 9. 2D grip (>= 10 laps) — uses vertical curvature for terrain-corrected mu
    grip_2d = None
    if n_laps >= 5:
        grip_2d = build_grip_surface(
            frenet, enriched_laps,
            s_bin_m=2.0, n_bin_m=0.5, n_range_m=8.0,
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
