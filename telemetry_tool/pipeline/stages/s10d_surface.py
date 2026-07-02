"""
pipeline/stages/s10d_surface.py
-------------------------------
Track surface reconstruction pipeline stage.

Builds a TrackSurface from the resampled laps, optionally solves for the
optimal racing line, and computes the line delta for the best actual lap.

Sits between the corner analysis stages (s10b/s10c) and the features
stage (s11).  All steps are optional and fail gracefully via _safe_step.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def run_surface_build(
    resampled_laps: dict[int, pd.DataFrame] | None,
    track_id: str,
    adapter_format: str,
    vehicle_name: str | None = None,
    track_wetness: float | None = None,
    grip_multiplier: float | None = None,
    **kwargs: Any,
) -> dict | None:
    """Build a TrackSurface from resampled laps.

    Loads the accumulated track model (if one exists) and uses it as context.
    After building, merges this session's surface into the accumulated model.
    Grip data is keyed by (vehicle_class, track_condition) to prevent
    mixing different car classes or weather conditions.

    Parameters
    ----------
    resampled_laps : dict mapping lap_number -> canonical DataFrame.
    track_id : the detected track ID.
    adapter_format : adapter FORMAT_NAME for coordinate system detection.
    vehicle_name : car name from session metadata (for class detection).
    track_wetness : 0-1 track wetness from telemetry (for condition detection).
    grip_multiplier : grip multiplier from sim (for condition detection).

    Returns
    -------
    Dict with 'surface_summary', 'track_surface', keying info, and
    'accumulated' flag, or None on failure.
    """
    if not resampled_laps or len(resampled_laps) == 0:
        return None

    try:
        from track_surface.builder import build_track_surface
        from track_surface.store import (
            detect_track_condition,
            detect_vehicle_class,
            load_track_model,
            merge_track_model,
        )
    except ImportError:
        logger.debug("track_surface modules not importable, skipping surface build")
        return None

    # Detect vehicle class and track condition
    v_class = detect_vehicle_class(vehicle_name)
    t_condition = detect_track_condition(track_wetness, grip_multiplier)

    # Load accumulated model for this track+class+condition
    accumulated = load_track_model(track_id, vehicle_class=v_class, condition=t_condition)

    # Build this session's surface
    session_surface = build_track_surface(resampled_laps, track_id, adapter_format)

    # Merge into accumulated model (keyed by class+condition)
    merged = merge_track_model(
        track_id, session_surface, vehicle_class=v_class, condition=t_condition,
        on_geometry_rejected=lambda report: _record_geometry_rejection(
            track_id, v_class, t_condition, report),
    )
    if merged:
        logger.info("Track model accumulated: track=%s, class=%s, cond=%s",
                     track_id, v_class, t_condition)

    # Use accumulated model for solver if it has better data, else session's
    surface_for_solver = accumulated if (accumulated and accumulated.has_boundaries) else session_surface

    return {
        "track_surface": surface_for_solver,
        "session_surface": session_surface,
        "surface_summary": surface_for_solver.to_summary_dict(),
        "accumulated": accumulated is not None,
        "vehicle_class": v_class,
        "track_condition": t_condition,
    }


def _record_geometry_rejection(track_id: str, v_class: str, t_condition: str, report: Any) -> None:
    """Insert one ``track_geometry_audit`` row per failed gate (spec A3).

    Connection pattern mirrors ``tasks/racing_line_tasks.py`` — the other
    Celery-adjacent writer of a global, RLS-free ``track_*`` table (migration
    078) — using the maintenance DSN (``get_maint_connection`` /
    ``return_pg_connection``), not the per-request/workspace-scoped
    connection ``pipeline.orchestrator._open_ws_conn`` opens for
    ``upsert_global_surface`` (that one pins an RLS GUC via SQLAlchemy
    ``:name`` params, which doesn't apply to this RLS-free table).

    Audit recording must never break the pipeline: every failure mode here
    (import, connect, insert, commit) is caught and logged, never raised.
    """
    import json

    try:
        from web.db_pg import get_maint_connection, return_pg_connection
    except Exception as exc:
        logger.warning("geometry-audit: db module unavailable, skipping audit for %s: %s",
                        track_id, exc)
        return

    try:
        conn = get_maint_connection()
    except Exception as exc:
        logger.warning("geometry-audit: could not open maint connection for %s: %s",
                        track_id, exc)
        return

    try:
        for failure in report.to_details()["failures"]:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO track_geometry_audit "
                    "(track_id, vehicle_class, condition, gate, details) "
                    "VALUES (%s,%s,%s,%s,%s::jsonb)",
                    (track_id, v_class, t_condition, failure["gate"], json.dumps(failure)),
                )
            finally:
                cur.close()
        conn.commit()
    except Exception as exc:
        logger.warning("geometry-audit: failed to record rejection for %s: %s", track_id, exc)
    finally:
        return_pg_connection(conn)


def run_optimal_line(
    surface_result: dict | None,
    vehicle_params: Any = None,
    **kwargs: Any,
) -> dict | None:
    """Solve for the optimal racing line using the CasADi OCP solver.

    Only runs if a TrackSurface with boundaries is available and the
    solver dependencies (casadi) are importable.

    Returns
    -------
    Dict with 'optimal_line' (OCPSolution) or None.
    """
    if surface_result is None:
        return None

    surface = surface_result.get("track_surface")
    if surface is None or not surface.has_boundaries:
        return None

    if vehicle_params is None:
        return None

    try:
        from track_surface.solver_bridge import solve_optimal_line
        solution = solve_optimal_line(surface, vehicle_params)
        return {"optimal_line": solution}
    except ImportError:
        logger.debug("CasADi not available, skipping optimal line solve")
        return None
    except Exception as exc:
        logger.warning("Optimal line solve failed: %s", exc)
        return None


def run_line_delta(
    surface_result: dict | None,
    optimal_result: dict | None,
    best_lap_df: pd.DataFrame | None,
    corners: list[dict] | None = None,
    **kwargs: Any,
) -> dict | None:
    """Compute line delta between best actual lap and optimal line.

    Returns
    -------
    Dict with 'line_delta' and 'corner_line_losses', or None.
    """
    if surface_result is None or optimal_result is None or best_lap_df is None:
        return None

    surface = surface_result.get("track_surface")
    solution = optimal_result.get("optimal_line")
    if surface is None or solution is None:
        return None

    # Best lap needs normalised positions
    if "x_m" not in best_lap_df.columns:
        try:
            from track_surface.normalizer import (
                detect_coordinate_system,
                normalize_positions,
            )
            coord_sys = detect_coordinate_system(
                surface.sim_sources[0] if surface.sim_sources else "gps"
            )
            x, y, z, _ = normalize_positions(best_lap_df, coord_sys)
            best_lap_df = best_lap_df.copy()
            best_lap_df["x_m"] = x
            best_lap_df["y_m"] = y
        except Exception:
            return None

    try:
        from track_surface.line_delta import compute_line_delta, decompose_corner_losses
        from track_surface.coaching import generate_spatial_coaching

        delta = compute_line_delta(
            surface.frenet,
            best_lap_df,
            solution.distance_m,
            solution.speed_mps,
            solution.lateral_offset_m,
        )

        corner_losses = []
        coaching = []
        if corners:
            corner_losses = decompose_corner_losses(delta, corners, surface.frenet)
            coaching = generate_spatial_coaching(corner_losses, surface)

        return {
            "line_delta": delta,
            "corner_line_losses": [cl.to_dict() for cl in corner_losses],
            "spatial_coaching": coaching,
        }
    except Exception as exc:
        logger.warning("Line delta computation failed: %s", exc)
        return None
