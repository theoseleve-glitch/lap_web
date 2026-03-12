# telemetry_tool/tasks/ocp_tasks.py
"""Celery task for OCP theoretical lap computation.

Runs as a background job after the synchronous pipeline completes.
Reads session data from DB, runs the full OCP pipeline (solve → calibrate → re-solve),
stores result in analysis_json["theoretical_ocp"].
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CALIBRATION_PASSES = 3
_CONVERGENCE_PCT = 1.0  # residual % threshold


def _is_ocp_enabled() -> bool:
    return os.environ.get("THEORETICAL_OCP", "1") not in ("0", "false", "no")


def _get_celery():
    """Import celery app; returns None if unavailable."""
    try:
        from tasks.celery_app import celery
        return celery
    except ImportError:
        return None


# Try to register as Celery task if available; otherwise stays a plain function
_celery = _get_celery()
if _celery is not None:
    @_celery.task(
        name="tasks.ocp_tasks.run_ocp_for_session",
        bind=True,
        queue="pipeline",
        max_retries=1,
        retry_backoff=True,
    )
    def run_ocp_for_session(self, session_id: int | str, workspace_id: int | None = None) -> dict | None:
        return _run_ocp_impl(session_id, workspace_id)
else:
    def run_ocp_for_session(session_id: int | str, workspace_id: int | None = None) -> dict | None:
        return _run_ocp_impl(session_id, workspace_id)


def _run_ocp_impl(session_id: int | str, workspace_id: int | None = None) -> dict | None:
    """Core OCP pipeline: extract → mesh → solve → calibrate → store."""
    if not _is_ocp_enabled():
        logger.info("OCP solver disabled (THEORETICAL_OCP=0)")
        return None

    try:
        import dataclasses
        import numpy as np
        import pandas as pd

        from solver.vehicle_params import OCPVehicleParams, params_for_class
        from solver.tire_model import LoadSensitiveTire
        from solver.track_model import build_mesh_from_curvature_profile, refine_mesh
        from solver.ocp_solver import solve_ocp
        from solver.param_extractor import extract_session_params
        from solver.calibrator import calibrate_params
    except ImportError as e:
        logger.warning("OCP solver dependencies not available: %s", e)
        return None

    conn = None
    try:
        conn, analysis_json, best_lap_df, curvature_profile, vehicle_params = (
            _load_session_data(session_id, workspace_id)
        )

        if best_lap_df is None or curvature_profile is None:
            logger.info("OCP skipped: missing best_lap_df or curvature_profile")
            return None

        # Build track mesh — 2000 nodes for ~1.5–2.5m resolution
        mesh = build_mesh_from_curvature_profile(curvature_profile, n_nodes=2000)
        if mesh is None:
            logger.warning("OCP skipped: could not build track mesh")
            return None

        # Build vehicle params
        if vehicle_params is not None:
            base_params = OCPVehicleParams.from_vehicle_params(vehicle_params)
        else:
            base_params = params_for_class("car")

        # Extract session-specific params
        params = extract_session_params(best_lap_df, base_params)

        # Build tire model
        tire = LoadSensitiveTire(
            mu_ref=params.mu_ref,
            Fz_ref=params.Fz_static_per_axle,
            sensitivity=params.load_sensitivity,
        )

        # Warm start from QSS if available
        warm_start = _extract_warm_start(analysis_json, mesh)

        # Stage 1: coarse solve on initial mesh
        logger.info("OCP stage 1: coarse solve for session %s (%d nodes)", session_id, len(mesh.s))
        result = solve_ocp(mesh, params, tire, warm_start=warm_start)

        # Stage 2: adaptive refinement around corners (high speed gradient zones)
        refined = refine_mesh(mesh, result.speed_profile, gradient_threshold=0.3)
        if len(refined.s) > len(mesh.s):
            logger.info(
                "OCP stage 2: refined mesh %d→%d nodes, re-solving",
                len(mesh.s), len(refined.s),
            )
            warm_refined = np.interp(refined.s, mesh.s, result.speed_profile)
            result = solve_ocp(refined, params, tire, warm_start=warm_refined)
            mesh = refined

        actual_apex = _extract_actual_apex_speeds(analysis_json)
        actual_straights = _extract_actual_straight_speeds(analysis_json)
        actual_braking = _extract_actual_braking_dists(analysis_json)
        theo_apex = _extract_theoretical_apex_speeds(result, analysis_json)

        calibration_meta = {}
        for cal_pass in range(_MAX_CALIBRATION_PASSES):
            cal = calibrate_params(
                mu_ref=params.mu_ref,
                P_max=params.P_max,
                F_brake_max=params.F_brake_max,
                actual_apex_speeds=actual_apex,
                theoretical_apex_speeds=theo_apex,
                actual_straight_end_speeds=actual_straights,
                theoretical_straight_end_speeds=[],
                actual_braking_dists=actual_braking,
                theoretical_braking_dists=[],
            )
            calibration_meta = cal.to_dict()

            if cal.residual_pct <= _CONVERGENCE_PCT:
                break

            # Update params and re-solve
            params = dataclasses.replace(
                params,
                mu_ref=cal.mu_ref_final,
                P_max=cal.P_max_final,
                F_brake_max=cal.F_brake_final,
            )
            tire = LoadSensitiveTire(
                mu_ref=params.mu_ref,
                Fz_ref=params.Fz_static_per_axle,
                sensitivity=params.load_sensitivity,
            )
            result = solve_ocp(mesh, params, tire, warm_start=result.speed_profile)
            theo_apex = _extract_theoretical_apex_speeds(result, analysis_json)

        if not result.converged:
            logger.warning("OCP solver did not converge for session %s", session_id)

        result_dict = result.to_dict()
        result_dict["calibration"] = calibration_meta

        _store_ocp_result(conn, session_id, result_dict)
        logger.info(
            "OCP result stored for session %s: %.2fs (converged=%s, %.1fs wall)",
            session_id, result.lap_time_s, result.converged,
            result.solver_meta["wall_time_s"],
        )

        # Update downstream: scoring, coaching, corner targets
        _update_downstream(conn, session_id, result, result_dict, analysis_json,
                           workspace_id=workspace_id, best_lap_df=best_lap_df)

        return result_dict

    except Exception:
        logger.warning("OCP computation failed for session %s", session_id, exc_info=True)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _load_session_data(session_id, workspace_id):
    """Load session data needed for OCP from the database.

    Reads best-lap speed trace from gps_traces, curvature from
    reference_lines, and vehicle params from analysis_json.
    """
    from web.db import get_db_connection
    from web.repos import gps_repo, theoretical_repo, lap_repo
    import numpy as np
    import pandas as pd

    conn = get_db_connection()

    # Set RLS context if PG
    if workspace_id is not None:
        _set_rls_if_pg(conn, workspace_id)

    # Load analysis_json for corners, scoring, vehicle params
    row = conn.execute(
        "SELECT analysis_json FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Session {session_id} not found")
    analysis_json = json.loads(row[0]) if row[0] else {}

    # ── Best lap speed trace from GPS trace table ──
    best_lap_df = None
    laps = lap_repo.get_laps_for_session(conn, session_id)
    best_lap_num = None
    if laps:
        for lap in laps:
            if lap.get("is_best"):
                best_lap_num = lap["lap_number"]
                break
        if best_lap_num is None:
            best_lap_num = laps[0]["lap_number"]

    if best_lap_num is not None:
        trace = gps_repo.get_gps_trace(conn, session_id, best_lap_num)
        if trace:
            dists = trace.get("distances", [])
            speeds = trace.get("speeds", [])
            if dists and speeds and len(dists) == len(speeds) and len(dists) > 10:
                # Normalize distances to start from 0
                d0 = dists[0] if dists[0] != 0 else 0
                best_lap_df = pd.DataFrame({
                    "Distance (m)": [d - d0 for d in dists],
                    "Speed (m/s)": speeds,
                })
                logger.info("OCP: loaded best lap %d (%d points)", best_lap_num, len(dists))

    # ── Curvature from reference line ──
    curvature_profile = None
    ref_line = theoretical_repo.get_reference_line(conn, session_id)
    if ref_line:
        ref_dists = ref_line.get("distances", [])
        ref_lats = ref_line.get("latitudes", [])
        ref_lons = ref_line.get("longitudes", [])
        if ref_dists and ref_lats and ref_lons and len(ref_dists) > 10:
            curvature_profile = _curvature_from_reference_line(
                np.array(ref_dists, dtype=float),
                np.array(ref_lats, dtype=float),
                np.array(ref_lons, dtype=float),
            )
            if curvature_profile is not None:
                logger.info("OCP: computed curvature from reference line (%d points)", len(curvature_profile))

    # ── Vehicle params from analysis_json ──
    vehicle_params = None
    vp_data = analysis_json.get("vehicle_params")
    if vp_data:
        from vehicle_model import VehicleParameters, VehicleClass
        vehicle_params = VehicleParameters(
            vehicle_class=VehicleClass(vp_data.get("vehicle_class", "unknown")),
            estimated_mass_kg=vp_data.get("estimated_mass_kg"),
            peak_lateral_g=vp_data.get("peak_lateral_g", 1.0),
            peak_braking_g=vp_data.get("peak_braking_g", 1.0),
            peak_traction_g=vp_data.get("peak_traction_g", 0.5),
            has_downforce=vp_data.get("has_downforce", False),
            has_abs=vp_data.get("has_abs", False),
            rolling_resistance_est=vp_data.get("rolling_resistance_est", 0.015),
            aero_drag_factor_est=vp_data.get("aero_drag_factor_est", 0.0),
        )

    return conn, analysis_json, best_lap_df, curvature_profile, vehicle_params


def _curvature_from_reference_line(distances, lats, lons):
    """Compute curvature profile from reference line GPS coordinates.

    Uses finite-difference on local ENU projection to get kappa(s).
    Returns a DataFrame with distance_m and curvature_1pm columns.
    """
    import numpy as np
    import pandas as pd

    n = len(distances)
    if n < 20:
        return None

    # Convert lat/lon to local meters (simple equirectangular)
    lat0 = np.mean(lats)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * np.cos(np.radians(lat0))
    x = (lons - lons[0]) * m_per_deg_lon
    y = (lats - lats[0]) * m_per_deg_lat

    # Smooth to reduce GPS noise (Savgol-like: local averaging)
    win = min(11, n // 4)
    if win % 2 == 0:
        win += 1
    if win >= 3:
        kernel = np.ones(win) / win
        x_s = np.convolve(x, kernel, mode="same")
        y_s = np.convolve(y, kernel, mode="same")
        # Keep original endpoints
        hw = win // 2
        x_s[:hw] = x[:hw]
        x_s[-hw:] = x[-hw:]
        y_s[:hw] = y[:hw]
        y_s[-hw:] = y[-hw:]
    else:
        x_s, y_s = x, y

    # First and second derivatives w.r.t. arc length
    ds = np.diff(distances)
    ds[ds < 1e-6] = 1e-6
    dx = np.diff(x_s) / ds
    dy = np.diff(y_s) / ds

    ddx = np.diff(dx) / ds[:-1]
    ddy = np.diff(dy) / ds[:-1]

    # Curvature: |x'y'' - y'x''| / (x'^2 + y'^2)^1.5
    dx_m = (dx[:-1] + dx[1:]) / 2
    dy_m = (dy[:-1] + dy[1:]) / 2
    denom = (dx_m**2 + dy_m**2) ** 1.5
    denom[denom < 1e-12] = 1e-12
    kappa = np.abs(dx_m * ddy - dy_m * ddx) / denom

    # Pad to match distance array length
    kappa_full = np.zeros(n)
    kappa_full[1:-1] = kappa
    kappa_full[0] = kappa[0] if len(kappa) > 0 else 0
    kappa_full[-1] = kappa[-1] if len(kappa) > 0 else 0

    # Clip extreme curvature values (GPS noise)
    kappa_full = np.clip(kappa_full, 0, 0.5)

    return pd.DataFrame({
        "distance_m": distances,
        "curvature_1pm": kappa_full,
    })

    return None


def _extract_warm_start(analysis_json: dict, mesh) -> Any:
    """Extract warm start speed profile from QSS result."""
    import numpy as np

    optimal = analysis_json.get("optimal_v2") or analysis_json.get("theoretical")
    if not optimal:
        return None

    speed_data = optimal.get("speed_profile")
    if not speed_data or not isinstance(speed_data, list):
        return None

    try:
        distances = np.array([p["distance_m"] for p in speed_data])
        speeds = np.array([p["speed_mps"] for p in speed_data])
        warm = np.interp(mesh.s, distances, speeds)
        warm = np.maximum(warm, 2.0)
        return warm
    except (KeyError, ValueError):
        return None


def _extract_actual_apex_speeds(analysis_json: dict) -> list[float]:
    """Extract actual apex speeds from corner data."""
    corners = analysis_json.get("corners", [])
    if isinstance(corners, list):
        return [c.get("apex_speed_mps", 0.0) for c in corners if c.get("apex_speed_mps")]
    return []


def _extract_actual_straight_speeds(analysis_json: dict) -> list[float]:
    """Extract peak straight-end speeds."""
    return []  # TODO: extract from speed trace straight segments


def _extract_actual_braking_dists(analysis_json: dict) -> list[float]:
    """Extract actual braking distances."""
    return []  # TODO: extract from corner events


def _extract_theoretical_apex_speeds(result, analysis_json: dict) -> list[float]:
    """Extract theoretical apex speeds from OCP result at corner locations."""
    import numpy as np
    corners = analysis_json.get("corners", [])
    if not corners:
        return []
    apex_speeds = []
    for c in corners:
        apex_m = c.get("apex_distance_m")
        if apex_m is not None:
            v = float(np.interp(apex_m, result.distance_profile, result.speed_profile))
            apex_speeds.append(v)
    return apex_speeds


def _update_downstream(conn, session_id, result, result_dict, analysis_json,
                       workspace_id=None, best_lap_df=None):
    """Re-run corner analysis, coaching, and scoring with OCP theoretical data.

    Called after _store_ocp_result so analysis_json["theoretical_ocp"] already
    exists in the DB.  Updates the same DB row with refreshed scores, corner
    metrics, and coaching text.
    """
    import numpy as np
    import pandas as pd

    try:
        # 0. Set RLS context before any writes
        _set_rls_if_pg(conn, workspace_id)

        # 1. Build data shapes from OCP result
        theo_df = _ocp_result_to_dataframe(result)
        if theo_df is None or len(theo_df) < 10:
            logger.debug("OCP downstream: could not build theoretical DataFrame")
            return

        theo_result_dict = _build_theoretical_result_dict(result)

        speeds = np.array(result.speed_profile)
        theo_metrics = {
            "best_s": float(result.lap_time_s),
            "simulation_method": "ocp",
            "method": "ocp",
            "max_speed_mps": float(speeds.max()),
            "avg_speed_mps": float(speeds.mean()),
            "min_speed_mps": float(speeds.min()),
            "confidence": 1.0 if result.converged else 0.7,
        }

        # 2. Use best_lap_df passed from caller (already loaded from DB)
        corners = analysis_json.get("corners", [])
        friction_model = analysis_json.get("friction_model") or {"max_lateral_g": 1.2}
        resampled_laps = {0: best_lap_df} if best_lap_df is not None else {}
        available_columns = set(best_lap_df.columns) if best_lap_df is not None else set()

        # 3. Build observed metrics
        observed_metrics = _extract_observed_metrics(analysis_json)
        if not observed_metrics.get("best_s"):
            logger.debug("OCP downstream: no observed best_s, skipping")
            return

        # 4. Re-run corner analysis with OCP theoretical
        corner_perfs = None
        if corners and best_lap_df is not None:
            try:
                from pipeline.stages.s10b_corners import run_corner_analysis
                corner_perfs = run_corner_analysis(
                    corners, best_lap_df, theo_df, friction_model, resampled_laps,
                )
                if corner_perfs:
                    analysis_json["corner_perfs"] = corner_perfs
            except Exception:
                logger.warning("OCP downstream: corner analysis failed", exc_info=True)

        # 5. Re-run coaching analyzers
        analyzer_bundle = None
        if corner_perfs:
            try:
                from pipeline.stages.s13_coaching_v3 import run_coaching_analyzers
                analyzer_bundle = run_coaching_analyzers(
                    corner_perfs, best_lap_df, theo_result_dict,
                    friction_model, resampled_laps, available_columns,
                )
            except Exception:
                logger.warning("OCP downstream: coaching analyzers failed", exc_info=True)

        # 6. Re-score with OCP theoretical
        from scoring.scorer import score_session

        session_type = analysis_json.get("session_type", "practice")
        new_scores = score_session(
            observed_metrics, theo_metrics, session_type,
            corner_coaching=corner_perfs or [],
        )

        # 7. Re-run enhanced coaching
        if corner_perfs:
            try:
                from pipeline.stages.s13_coaching_v3 import run_enhanced_coaching
                coaching_v2 = analysis_json.get("coaching_v3") or analysis_json.get("coaching")
                driving_style = analysis_json.get("driving_style")
                vehicle_class = (analysis_json.get("vehicle_params") or {}).get("vehicle_class", "car")
                coaching_v3 = run_enhanced_coaching(
                    corner_perfs, coaching_v2, new_scores,
                    lap_metrics=None, driving_style=driving_style,
                    analyzer_bundle=analyzer_bundle, driver_history=None,
                    vehicle_class=vehicle_class,
                )
                if coaching_v3:
                    analysis_json["coaching_v3"] = coaching_v3
            except Exception:
                logger.warning("OCP downstream: enhanced coaching failed", exc_info=True)

        # 8. Update corner speed targets via interpolation (always, even if corner analysis failed)
        _update_corner_targets(analysis_json, result, corners)

        # 9. Store everything in analysis_json
        analysis_json["score_result"] = new_scores
        analysis_json["theoretical_metrics"] = theo_metrics
        analysis_json["simulation_method"] = "ocp"

        # 10. Persist — single transaction for RLS safety
        _persist_all(conn, session_id, analysis_json, new_scores)

        logger.info(
            "OCP downstream update complete for session %s: "
            "score=%.1f/%s, method=ocp, corners=%d",
            session_id,
            new_scores.get("total_score", 0),
            new_scores.get("grade", "?"),
            len(corner_perfs) if corner_perfs else 0,
        )

    except Exception:
        logger.warning(
            "OCP downstream update failed for session %s (raw OCP data preserved)",
            session_id,
            exc_info=True,
        )


def _ocp_result_to_dataframe(result):
    """Convert TheoreticalResult to a DataFrame with distance_m, speed_mps, time_s."""
    import numpy as np
    import pandas as pd

    dist = np.array(result.distance_profile)
    speed = np.array(result.speed_profile)

    if len(dist) < 2:
        return None

    # Compute cumulative time: dt[i] = ds[i] / v_avg[i]
    ds = np.diff(dist)
    v_avg = (speed[:-1] + speed[1:]) / 2.0
    v_avg = np.maximum(v_avg, 2.0)  # avoid div-by-zero
    dt = ds / v_avg
    time_s = np.zeros(len(dist))
    time_s[1:] = np.cumsum(dt)

    return pd.DataFrame({
        "distance_m": dist,
        "speed_mps": speed,
        "time_s": time_s,
        "a_long": np.array(result.a_long_profile),
        "a_lat": np.array(result.a_lat_profile),
    })


def _build_theoretical_result_dict(result) -> dict:
    """Build the dict shape that run_coaching_analyzers expects for theoretical_result.

    Shape: {"speed_profile": [{"distance_m": ..., "speed_mps": ...}, ...], "track_length_m": float}
    """
    import numpy as np
    dist = np.array(result.distance_profile)
    speed = np.array(result.speed_profile)
    return {
        "speed_profile": [
            {"distance_m": round(float(dist[i]), 2), "speed_mps": round(float(speed[i]), 3)}
            for i in range(len(dist))
        ],
        "track_length_m": float(dist[-1]) if len(dist) > 0 else 0.0,
    }


def _set_rls_if_pg(conn, workspace_id):
    """Set workspace RLS context if running on PG."""
    if workspace_id is None:
        return
    if os.environ.get("USE_PG", "0") in ("0", "false", "no"):
        return
    try:
        from auth.workspace import set_workspace_context
        set_workspace_context(conn, workspace_id)
    except Exception:
        logger.debug("RLS context setup skipped", exc_info=True)


def _extract_observed_metrics(analysis_json: dict) -> dict:
    """Extract observed session metrics from analysis_json for scoring."""
    metrics: dict = {}

    # Best lap time
    lap_times = analysis_json.get("lap_times", [])
    if isinstance(lap_times, list) and lap_times:
        valid = [t for t in lap_times if isinstance(t, (int, float)) and t > 0]
        if valid:
            metrics["best_s"] = min(valid)
            metrics["n_laps"] = len(valid)
            import numpy as _np
            arr = _np.array(valid)
            metrics["cv_pct"] = float(_np.std(arr) / _np.mean(arr) * 100) if len(arr) > 1 else 0.0
            sorted_arr = _np.sort(arr)
            metrics["best_to_median_s"] = float(sorted_arr[0] - _np.median(arr))

    # From existing score_result (preserve non-pace metrics)
    existing = analysis_json.get("score_result", {})
    details = existing.get("details", {}) if isinstance(existing, dict) else {}

    # Speed/accel metrics from stored data
    speed_trace = analysis_json.get("speed_trace_best", [])
    if isinstance(speed_trace, list) and speed_trace:
        import numpy as _np
        speeds = [p.get("speed_mps", 0) for p in speed_trace if isinstance(p, dict)]
        if speeds:
            metrics["speed_mean_mps"] = float(_np.mean(speeds))

    # Robustness metrics (pass through from existing)
    for key in ("early_mean_s", "late_mean_s", "early_yaw_var", "late_yaw_var",
                "accel_max_mps2", "braking_max_mps2"):
        val = analysis_json.get(key)
        if val is not None:
            metrics[key] = val

    return metrics


def _update_corner_targets(analysis_json, result, corners):
    """Update corner coaching targets with OCP theoretical speeds."""
    import numpy as np

    dist = np.array(result.distance_profile)
    speed = np.array(result.speed_profile)

    corner_coaching = analysis_json.get("corner_coaching", [])
    if not isinstance(corner_coaching, list):
        corner_coaching = []

    updated_coaching = []
    for cc in corner_coaching:
        cc = dict(cc)  # copy to avoid mutating original
        apex_m = cc.get("apex_distance_m")
        entry_m = cc.get("entry_distance_m")
        exit_m = cc.get("exit_distance_m")

        if apex_m is not None:
            v_apex = float(np.interp(apex_m, dist, speed))
            cc["apex_speed_target_kmh"] = round(v_apex * 3.6, 1)
            cc["theoretical_apex_mps"] = round(v_apex, 3)
        if entry_m is not None:
            v_entry = float(np.interp(entry_m, dist, speed))
            cc["entry_speed_target_kmh"] = round(v_entry * 3.6, 1)
            cc["theoretical_entry_mps"] = round(v_entry, 3)
        if exit_m is not None:
            v_exit = float(np.interp(exit_m, dist, speed))
            cc["exit_speed_target_kmh"] = round(v_exit * 3.6, 1)
            cc["theoretical_exit_mps"] = round(v_exit, 3)

        # Recompute time loss if actual and theoretical apex known
        actual_apex = cc.get("actual_apex_speed_mps")
        if actual_apex and apex_m is not None:
            v_theo = float(np.interp(apex_m, dist, speed))
            if v_theo > 0:
                cc["speed_delta_pct"] = round(
                    100.0 * (v_theo - actual_apex) / v_theo, 1
                )

        updated_coaching.append(cc)

    analysis_json["corner_coaching"] = updated_coaching


def _persist_all(conn, session_id, analysis_json, new_scores):
    """Persist analysis_json, score_details, and session score columns in one commit.

    Uses a single conn.commit() to preserve SET LOCAL RLS context on PG.
    """
    use_pg = os.environ.get("USE_PG", "0") not in ("0", "false", "no")

    # 1. analysis_json blob
    if use_pg:
        conn.execute(
            "UPDATE sessions SET analysis_json = ?::jsonb WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )
    else:
        conn.execute(
            "UPDATE sessions SET analysis_json = ? WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )

    # 2. sessions.total_score + grade
    conn.execute(
        "UPDATE sessions SET total_score = ?, grade = ? WHERE id = ?",
        (new_scores.get("total_score"), new_scores.get("grade"), session_id),
    )

    # 3. score_details table
    try:
        from web.repos.score_repo import insert_score_details
        insert_score_details(conn, session_id, {"score_result": new_scores})
    except Exception:
        logger.debug("score_details update skipped", exc_info=True)

    # Single commit preserves SET LOCAL RLS context
    conn.commit()


def _store_ocp_result(conn, session_id, result_dict: dict):
    """Store OCP result in analysis_json using atomic jsonb_set if PG, else read-modify-write."""
    import os
    if os.environ.get("USE_PG", "0") not in ("0", "false", "no"):
        # PostgreSQL: atomic jsonb_set avoids race condition
        conn.execute(
            "UPDATE sessions SET analysis_json = jsonb_set("
            "  COALESCE(analysis_json, '{}'), '{theoretical_ocp}', ?::jsonb"
            ") WHERE id = ?",
            (json.dumps(result_dict), session_id),
        )
    else:
        # SQLite: read-modify-write (single-writer, no race)
        row = conn.execute(
            "SELECT analysis_json FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return
        analysis_json = json.loads(row[0]) if row[0] else {}
        analysis_json["theoretical_ocp"] = result_dict
        conn.execute(
            "UPDATE sessions SET analysis_json = ? WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )
    conn.commit()
