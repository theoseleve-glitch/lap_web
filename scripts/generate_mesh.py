#!/usr/bin/env python3
"""CLI mesh generator for Day 4b boundary-gap audit.

Generates a JSON mesh artifact with centerline + left/right boundaries from
RaceChrono CSV telemetry, bypassing DB+Celery via a direct call to
telemetry_tool.track_surface.builder.build_track_surface.

Usage:
    python scripts/generate_mesh.py \
        --session data/raw/KCT_R1.csv \
        --track kct \
        --output ../../day4b_outputs/mesh_kct_r1.json

Pipeline chain (mirrors kart_envelope.pipeline.analyze_session steps 1-6):
    parse_session_csv_raw -> clean_and_derive -> normalize_columns
    -> split_and_select_laps -> resample_laps_by_ds -> mad_filter_accel
    -> build_track_surface

The output JSON contains:
    - track_id, session_file, n_laps_used, quality_tier
    - boundary_source ("data_derived (percentile-99 * 1.3 margin)" or "default_3m")
    - projection {method, lat_ref_rad, lon_ref_rad, earth_radius_m}
    - stats (length, width min/max/mean, elevation range)
    - centerline {x_m, y_m, z_m, s_m}
    - left_boundary  {x_m, y_m, z_m, s_m, n_left_m}
    - right_boundary {x_m, y_m, z_m, s_m, n_right_m}

The projection block lets downstream scripts (measure_boundary_gap.py) project
WGS84 gt polylines into the same local XY frame.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from kart_envelope.config import default_config  # noqa: E402
from kart_envelope.ingest.columns import normalize_columns  # noqa: E402
from kart_envelope.ingest.parser import parse_session_csv_raw  # noqa: E402
from kart_envelope.processing.cleaning import clean_and_derive  # noqa: E402
from kart_envelope.processing.lap_splitting import split_and_select_laps  # noqa: E402
from kart_envelope.processing.outlier_filter import mad_filter_accel  # noqa: E402
from kart_envelope.processing.resampler import resample_laps_by_ds  # noqa: E402
from track_surface.builder import build_track_surface  # noqa: E402

logger = logging.getLogger("generate_mesh")

_EARTH_RADIUS_M = 6_371_000.0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--session", required=True, help="Path to RaceChrono CSV")
    p.add_argument("--track", required=True, help="Track slug (e.g. kct, ok, jv)")
    p.add_argument("--output", required=True, help="Output JSON path")
    p.add_argument("--log-level", default="INFO", help="DEBUG / INFO / WARNING / ERROR")
    return p.parse_args()


def _compute_global_gps_reference(
    laps: dict[int, "pd.DataFrame"],
) -> tuple[float, float]:
    """Compute (lat_ref_rad, lon_ref_rad) from union of all lap GPS samples.

    Uses the same equirectangular convention as
    telemetry_tool.track_surface.normalizer._gps_to_local_enu.
    """
    import pandas as pd  # local import (top imports may still be wiring path)

    lats: list[np.ndarray] = []
    lons: list[np.ndarray] = []
    for lap_df in laps.values():
        # Canonical names from normalize_columns
        if "lat_deg" in lap_df.columns and "lon_deg" in lap_df.columns:
            lats.append(pd.to_numeric(lap_df["lat_deg"], errors="coerce").to_numpy())
            lons.append(pd.to_numeric(lap_df["lon_deg"], errors="coerce").to_numpy())
            continue
        # Fallback: RaceChrono raw names (shouldn't happen after normalize_columns,
        # but be defensive)
        if "Latitude (deg)" in lap_df.columns and "Longitude (deg)" in lap_df.columns:
            lats.append(pd.to_numeric(lap_df["Latitude (deg)"], errors="coerce").to_numpy())
            lons.append(pd.to_numeric(lap_df["Longitude (deg)"], errors="coerce").to_numpy())

    if not lats:
        raise RuntimeError(
            "No GPS columns found in any lap DataFrame after normalize_columns; "
            "cannot compute projection reference."
        )

    all_lat = np.concatenate(lats)
    all_lon = np.concatenate(lons)
    finite = np.isfinite(all_lat) & np.isfinite(all_lon)
    if not finite.any():
        raise RuntimeError("All GPS samples were non-finite; cannot compute projection reference.")

    lat_ref_rad = float(np.deg2rad(np.mean(all_lat[finite])))
    lon_ref_rad = float(np.deg2rad(np.mean(all_lon[finite])))
    return lat_ref_rad, lon_ref_rad


def _compute_left_normal(cl_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-point unit normal pointing LEFT of the centerline tangent.

    Uses central differences via np.gradient. Left = +90deg rotation of tangent.
    """
    dx = np.gradient(cl_xy[:, 0])
    dy = np.gradient(cl_xy[:, 1])
    tan_len = np.hypot(dx, dy)
    tan_len = np.where(tan_len < 1e-9, 1.0, tan_len)
    tx = dx / tan_len
    ty = dy / tan_len
    # Left-normal: (-ty, tx) is +90 deg CCW rotation of (tx, ty)
    return -ty, tx


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    session_path = Path(args.session)
    if not session_path.exists():
        logger.error("Session CSV not found: %s", session_path)
        return 2

    config = default_config()

    logger.info("Stage 1: parse_session_csv_raw(%s)", session_path.name)
    raw_df, _normalised = parse_session_csv_raw(str(session_path))
    logger.info("  -> raw_df shape: %s", raw_df.shape)

    logger.info("Stage 2: clean_and_derive (raw RaceChrono column names)")
    cleaned = clean_and_derive(raw_df, config)
    logger.info("  -> cleaned shape: %s", cleaned.shape)

    logger.info("Stage 3: normalize_columns")
    df = normalize_columns(cleaned)
    logger.info("  -> normalised shape: %s, %d columns", df.shape, len(df.columns))

    logger.info("Stage 4: split_and_select_laps")
    laps = split_and_select_laps(df, config)
    logger.info("  -> %d laps selected: %s", len(laps), sorted(laps.keys()))

    logger.info("Stage 5: resample_laps_by_ds (ds=%.2fm)",
                getattr(config, "resampler_ds_m", 0.5))
    resampled = resample_laps_by_ds(laps, config)

    logger.info("Stage 6: mad_filter_accel")
    filtered = mad_filter_accel(resampled, config) or resampled

    logger.info("Stage 7: compute global lat_ref/lon_ref from union of laps")
    lat_ref_rad, lon_ref_rad = _compute_global_gps_reference(filtered)
    logger.info(
        "  -> lat_ref=%.6f rad (%.4f deg), lon_ref=%.6f rad (%.4f deg)",
        lat_ref_rad, np.degrees(lat_ref_rad),
        lon_ref_rad, np.degrees(lon_ref_rad),
    )

    logger.info("Stage 8: build_track_surface(track=%s, format=racechrono)", args.track)
    surface = build_track_surface(filtered, args.track, "racechrono")
    logger.info(
        "  -> quality_tier=%s, n_laps=%d, length=%.1fm, n_points=%d",
        surface.quality_tier, surface.n_laps,
        surface.frenet.total_length_m, surface.frenet.n_points,
    )

    cl_xy = surface.frenet.centerline_xy
    s_grid = surface.frenet.s_grid
    n_pts = surface.frenet.n_points

    nx_left, ny_left = _compute_left_normal(cl_xy)

    if surface.has_boundaries:
        w_left = surface.width_left.astype(float)
        w_right = surface.width_right.astype(float)
        # Use the build_track_surface-supplied boundary_source if present;
        # fall back to a descriptive default. After the Day-5 gt integration,
        # this should be "hand_traced" when a gt file exists for the track
        # and "data_derived" otherwise.
        boundary_source = surface.boundary_source or "data_derived"
    else:
        logger.warning(
            "Surface has no boundaries (n_laps=%d, <3 needed); using 3m defaults",
            surface.n_laps,
        )
        w_left = np.full(n_pts, 3.0)
        w_right = np.full(n_pts, 3.0)
        boundary_source = "default_3m"

    if surface.has_elevation:
        z_cl = surface.elevation_m.astype(float)
    else:
        z_cl = np.zeros(n_pts)

    # If gt's "left_boundary_gt" landed on -n̂_left side of centerline
    # (the centerline was traversed opposite to gt's labeling
    # convention), flip the normal sign so rendered LEFT lands at the
    # gt LEFT physical position. surface.boundary_side_swap reflects
    # this for hand_traced; data_derived path always sets it False.
    side_swap_sign = -1.0 if getattr(surface, "boundary_side_swap", False) else 1.0
    left_x = cl_xy[:, 0] + side_swap_sign * nx_left * w_left
    left_y = cl_xy[:, 1] + side_swap_sign * ny_left * w_left
    right_x = cl_xy[:, 0] - side_swap_sign * nx_left * w_right
    right_y = cl_xy[:, 1] - side_swap_sign * ny_left * w_right

    ds_m = float(s_grid[1] - s_grid[0]) if n_pts > 1 else 0.5

    out: dict = {
        "track_id": args.track,
        "session_file": session_path.name,
        "n_laps_used": int(surface.n_laps),
        "quality_tier": surface.quality_tier,
        "boundary_source": boundary_source,
        "projection": {
            "method": "equirectangular",
            "lat_ref_rad": lat_ref_rad,
            "lon_ref_rad": lon_ref_rad,
            "earth_radius_m": _EARTH_RADIUS_M,
            "note": (
                "x_m = R * (lon_rad - lon_ref) * cos(lat_ref); "
                "y_m = R * (lat_rad - lat_ref). "
                "Note: build_track_surface internally uses per-lap mean GPS as "
                "reference; centerline_xy here is in that internal frame, which "
                "may differ from this global reference by O(1m). Boundary widths "
                "are scalar metres relative to centerline and unaffected."
            ),
        },
        "stats": {
            "total_length_m": float(surface.frenet.total_length_m),
            "n_points": int(n_pts),
            "ds_m": ds_m,
            "width_left_min_m": float(np.min(w_left)),
            "width_left_max_m": float(np.max(w_left)),
            "width_left_mean_m": float(np.mean(w_left)),
            "width_right_min_m": float(np.min(w_right)),
            "width_right_max_m": float(np.max(w_right)),
            "width_right_mean_m": float(np.mean(w_right)),
            "total_width_min_m": float(np.min(w_left + w_right)),
            "total_width_max_m": float(np.max(w_left + w_right)),
            "total_width_mean_m": float(np.mean(w_left + w_right)),
            "elevation_min_m": float(z_cl.min()),
            "elevation_max_m": float(z_cl.max()),
            "elevation_range_m": float(z_cl.max() - z_cl.min()),
        },
        "centerline": {
            "x_m": cl_xy[:, 0].tolist(),
            "y_m": cl_xy[:, 1].tolist(),
            "z_m": z_cl.tolist(),
            "s_m": s_grid.tolist(),
        },
        "left_boundary": {
            "x_m": left_x.tolist(),
            "y_m": left_y.tolist(),
            "z_m": z_cl.tolist(),
            "s_m": s_grid.tolist(),
            "n_left_m": w_left.tolist(),
        },
        "right_boundary": {
            "x_m": right_x.tolist(),
            "y_m": right_y.tolist(),
            "z_m": z_cl.tolist(),
            "s_m": s_grid.tolist(),
            "n_right_m": w_right.tolist(),
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    logger.info(
        "Wrote %s: track=%s, n_points=%d, length=%.1fm, ds=%.2fm, "
        "width=[%.2f, %.2f] m, source=%s",
        output_path, args.track, n_pts, surface.frenet.total_length_m, ds_m,
        out["stats"]["total_width_min_m"], out["stats"]["total_width_max_m"],
        boundary_source,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
