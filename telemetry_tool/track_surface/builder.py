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

from track_surface.boundary import estimate_boundaries
from track_surface.centerline import extract_centerline
from track_surface.elevation import build_elevation_profile, compute_vertical_curvature, estimate_camber
from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import build_grip_surface
from track_surface.model import TrackSurface
from track_surface.normalizer import detect_coordinate_system, normalize_positions

logger = logging.getLogger(__name__)


def _extract_lap_xy(
    laps: dict[int, pd.DataFrame],
    adapter_format: str,
) -> tuple[list[np.ndarray], list[np.ndarray], list[pd.DataFrame]]:
    """Normalise positions for each lap.

    Returns
    -------
    (xy_list, z_list, enriched_laps) where:
    - xy_list: list of (N_i, 2) horizontal position arrays
    - z_list: list of (N_i,) elevation arrays
    - enriched_laps: DataFrames with x_m, y_m, z_m columns added
    """
    coord_sys = detect_coordinate_system(adapter_format)
    xy_list = []
    z_list = []
    enriched = []

    for lap_num, df in sorted(laps.items()):
        x, y, z, meta = normalize_positions(df, coord_sys)

        # Skip laps with no valid position data
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() < 20:
            continue

        xy = np.column_stack([x[valid], y[valid]])
        xy_list.append(xy)
        z_list.append(z[valid])

        # Enrich DataFrame with normalised coords for downstream
        enriched_df = df.copy()
        enriched_df["x_m"] = x
        enriched_df["y_m"] = y
        enriched_df["z_m"] = z
        enriched.append(enriched_df)

    return xy_list, z_list, enriched


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
    xy_list, z_list, enriched_laps = _extract_lap_xy(laps, adapter_format)
    n_laps = len(xy_list)

    if n_laps == 0:
        raise ValueError("No valid laps with position data for track surface")

    logger.info("Building track surface: track=%s, laps=%d, format=%s",
                track_id, n_laps, adapter_format)

    # 2. Extract centerline
    cl_xy, total_length = extract_centerline(xy_list, ds_m=1.0)

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

    # 5. Boundaries (>= 3 laps)
    boundaries = estimate_boundaries(frenet, laps_sn)
    width_left = boundaries[0] if boundaries else None
    width_right = boundaries[1] if boundaries else None

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

    # 8. 2D grip (>= 10 laps) — uses vertical curvature for terrain-corrected mu
    grip_2d = None
    if n_laps >= 10:
        grip_2d = build_grip_surface(frenet, enriched_laps, vert_curvature=vert_curvature)

    # 9. Assemble
    surface = TrackSurface(
        track_id=track_id,
        frenet=frenet,
        width_left=width_left,
        width_right=width_right,
        elevation_m=elevation_m,
        slope_pct=slope_pct,
        vert_curvature_1pm=vert_curvature,
        camber_rad=camber_rad,
        grip_2d=grip_2d,
        n_laps=n_laps,
        sim_sources=[adapter_format],
    )

    logger.info("Track surface built: tier=%s, length=%.0fm, laps=%d",
                surface.quality_tier, frenet.total_length_m, n_laps)
    return surface
