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
    is_operator_run: bool = False,
    job_id: str | None = None,
    fingerprint: dict | None = None,
    track_label: str | None = None,
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
    is_operator_run : whether this pipeline run was triggered by an
        operator/admin (``PipelineContext.is_operator_run``, threaded down
        via ``meta["is_operator_run"]``) -- gates the track-onboarding
        GT-miss detection hook below. End-user uploads must NEVER trigger
        onboarding, so this defaults to ``False``.
    job_id : the pipeline job id (``meta["job_id"]``/``meta["session_id"]``),
        forwarded as the onboarding request's ``session_ref`` -- it MUST
        equal ``ingestion_jobs.job_id`` so the later reprocess-after-bless
        flow can look the session back up.
    fingerprint : this session's track fingerprint dict (from step 05's
        ``track_match["fingerprint"]``), forwarded to the onboarding request
        for operator triage.
    track_label : human-readable track name (from step 05's
        ``track_match["track_name"]``), forwarded to the onboarding request.

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

    # Track-onboarding GT-miss detection hook (best-effort, never raises --
    # see _maybe_trigger_onboarding's docstring). Must run BEFORE the merge
    # below: merge_track_model can only improve on session_surface, it can't
    # change whether GT existed for this build.
    _maybe_trigger_onboarding(
        session_surface,
        track_id,
        is_operator_run=is_operator_run,
        job_id=job_id,
        fingerprint=fingerprint,
        track_label=track_label,
        resampled_laps=resampled_laps,
    )

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


def _maybe_trigger_onboarding(
    session_surface: Any,
    track_id: str,
    *,
    is_operator_run: bool,
    job_id: str | None,
    fingerprint: dict | None,
    track_label: str | None,
    resampled_laps: dict[int, pd.DataFrame],
) -> None:
    """Detection trigger for the Track Onboarding Loop.

    Fires ``onboarding.service.record_missing_geometry`` exactly when this
    build produced a real GT gap: ``session_surface.boundary_source is
    None`` (a GT hit sets it to ``"gt_anchored_native"`` --
    ``track_surface/builder.py`` around lines 342/361). Every other
    condition below is a refusal-to-onboard gate, cheapest first so we
    never do the canonical-id resolution or bbox/centerline work for a
    case ``record_missing_geometry`` would refuse anyway:

    1. No surface, or GT already present (``boundary_source`` set) --
       nothing missing.
    2. Not an operator run -- end-user uploads must NEVER onboard. This is
       the single most important invariant here; ``is_operator_run``
       defaults to ``False`` everywhere upstream (``PipelineContext``,
       this function's own parameter) and is only set ``True`` by
       verified operator/admin entrypoints (see ``pipeline_context.py``
       and ``web/routes/admin/jobs.py``).
    3. ``track_id`` missing/sentinel -- can't onboard an unrecognised
       track.
    4. No ``job_id`` -- nothing usable as ``session_ref``.

    Entirely best-effort: the ``try`` below wraps canonical-id resolution,
    bbox/centerline derivation, and the ``record_missing_geometry`` call
    itself. Any exception is logged and swallowed -- this hook must never
    break the analysis pipeline.
    """
    if session_surface is None or session_surface.boundary_source is not None:
        return  # no surface, or GT already anchored -- nothing missing

    if not is_operator_run:
        logger.debug(
            "onboarding trigger: skip (not an operator run) track_id=%s", track_id,
        )
        return

    if not track_id or track_id == "unknown_track":
        logger.debug(
            "onboarding trigger: skip (no/unknown track_id=%r)", track_id,
        )
        return

    if not job_id:
        logger.debug(
            "onboarding trigger: skip (no job_id/session_ref) track_id=%s", track_id,
        )
        return

    try:
        from track_surface.gt_loader import resolve_canonical_via_pg, resolve_track_id
        from onboarding.service import record_missing_geometry

        # Same dual-path resolution build_track_surface uses to load gt
        # (track_surface/builder.py ~line 192) -- the track_key we hand to
        # record_missing_geometry MUST be that same canonical id, since a
        # later bless writes GT under whatever key load_gt will query.
        canonical_id = resolve_track_id(track_id) or resolve_canonical_via_pg(track_id)
        if not canonical_id:
            logger.info(
                "onboarding trigger: skip (no canonical id resolved) track_id=%s",
                track_id,
            )
            return

        bbox = _compute_gps_bbox(resampled_laps)
        if bbox is None:
            logger.info(
                "onboarding trigger: skip (no GPS bbox derivable) track_id=%s, "
                "canonical_id=%s", track_id, canonical_id,
            )
            return

        centerline = _downsample_centerline(resampled_laps)

        record_missing_geometry(
            track_key=canonical_id,
            track_label=track_label or track_id,
            fingerprint=fingerprint,
            bbox=bbox,
            session_ref=job_id,
            draft_centerline=centerline,
            is_operator_run=True,
        )
    except Exception:
        logger.exception(
            "onboarding trigger failed for track_id=%s, job_id=%s",
            track_id, job_id,
        )


def _compute_gps_bbox(
    resampled_laps: dict[int, pd.DataFrame],
) -> dict[str, float] | None:
    """WGS84 bounding box over every lap's GPS samples, or ``None``.

    Uses the same column-detection convention as
    ``track_surface/normalizer.py`` (``lat_deg``/``lon_deg`` or the raw
    RaceChrono ``"Latitude (deg)"``/``"Longitude (deg)"`` header names) so
    this works for both canonical and pre-canonical DataFrames.
    """
    from track_surface.normalizer import _GPS_LAT_COLS, _GPS_LON_COLS, _find_col

    lats: list[np.ndarray] = []
    lons: list[np.ndarray] = []
    for df in (resampled_laps or {}).values():
        if df is None or df.empty:
            continue
        lat_col = _find_col(df, _GPS_LAT_COLS)
        lon_col = _find_col(df, _GPS_LON_COLS)
        if lat_col is None or lon_col is None:
            continue
        lats.append(pd.to_numeric(df[lat_col], errors="coerce").to_numpy())
        lons.append(pd.to_numeric(df[lon_col], errors="coerce").to_numpy())

    if not lats:
        return None

    all_lat = np.concatenate(lats)
    all_lon = np.concatenate(lons)
    finite = np.isfinite(all_lat) & np.isfinite(all_lon)
    if not finite.any():
        return None

    return {
        "min_lon": float(np.min(all_lon[finite])),
        "min_lat": float(np.min(all_lat[finite])),
        "max_lon": float(np.max(all_lon[finite])),
        "max_lat": float(np.max(all_lat[finite])),
    }


def _downsample_centerline(
    resampled_laps: dict[int, pd.DataFrame],
    n_points: int = 100,
) -> list[list[float]] | None:
    """Downsample one representative lap's GPS trace to ~``n_points``.

    Picks the lowest-numbered lap (deterministic) as "representative" --
    this is only a draft seed for the annotator review UI, not a final
    geometry, so any single clean lap is good enough. Returns a list of
    ``[lon, lat]`` pairs, or ``None`` if no lap has usable GPS.
    """
    from track_surface.normalizer import _GPS_LAT_COLS, _GPS_LON_COLS, _find_col

    if not resampled_laps:
        return None

    for lap_key in sorted(resampled_laps.keys()):
        df = resampled_laps[lap_key]
        if df is None or df.empty:
            continue
        lat_col = _find_col(df, _GPS_LAT_COLS)
        lon_col = _find_col(df, _GPS_LON_COLS)
        if lat_col is None or lon_col is None:
            continue

        lat = pd.to_numeric(df[lat_col], errors="coerce").to_numpy()
        lon = pd.to_numeric(df[lon_col], errors="coerce").to_numpy()
        finite = np.isfinite(lat) & np.isfinite(lon)
        lat, lon = lat[finite], lon[finite]
        if len(lat) == 0:
            continue

        idx = np.unique(np.linspace(0, len(lat) - 1, min(n_points, len(lat))).round().astype(int))
        return [[float(lon[i]), float(lat[i])] for i in idx]

    return None


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
                    (track_id, v_class, t_condition, failure["gate"], json.dumps(failure, default=str)),
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
