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
        from solver.track_model import build_mesh_from_curvature_profile
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

        # Build track mesh
        mesh = build_mesh_from_curvature_profile(curvature_profile, n_nodes=500)
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

        # Solve + calibrate loop (spec Section 6)
        logger.info("Starting OCP solve for session %s (%d nodes)", session_id, len(mesh.s))
        result = solve_ocp(mesh, params, tire, warm_start=warm_start)

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
        _update_downstream(conn, session_id, result, result_dict, analysis_json)

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
    """Load session data needed for OCP from the database."""
    from web.db import get_db_connection
    import pandas as pd

    conn = get_db_connection()

    row = conn.execute(
        "SELECT analysis_json FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Session {session_id} not found")

    analysis_json = json.loads(row[0]) if row[0] else {}

    best_lap_df = _reconstruct_best_lap_df(analysis_json)
    curvature_profile = _reconstruct_curvature_profile(analysis_json)

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


def _reconstruct_best_lap_df(analysis_json: dict):
    """Reconstruct best lap DataFrame from stored data."""
    import numpy as np
    import pandas as pd

    speed_trace = analysis_json.get("speed_trace_best")
    if not speed_trace:
        return None

    if isinstance(speed_trace, list) and len(speed_trace) > 10:
        df = pd.DataFrame(speed_trace)
        rename_map = {
            "distance_m": "Distance (m)",
            "speed_mps": "Speed (m/s)",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        return df

    return None


def _reconstruct_curvature_profile(analysis_json: dict):
    """Reconstruct curvature profile from stored data."""
    import pandas as pd

    curv_data = analysis_json.get("curvature_profile")
    if not curv_data:
        return None

    if isinstance(curv_data, list) and len(curv_data) > 10:
        return pd.DataFrame(curv_data)

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


def _update_downstream(conn, session_id, result, result_dict, analysis_json):
    """Re-run scoring, corner analysis, and coaching with OCP theoretical data.

    Called after _store_ocp_result so analysis_json["theoretical_ocp"] already
    exists in the DB.  This function updates the *same* DB row with refreshed
    scores, corner metrics, and coaching text derived from the OCP result.
    """
    import numpy as np
    import pandas as pd

    try:
        # 1. Build theoretical_lap DataFrame from OCP speed profile
        theo_df = _ocp_result_to_dataframe(result)
        if theo_df is None or len(theo_df) < 10:
            logger.debug("OCP downstream: could not build theoretical DataFrame")
            return

        # 2. Build theoretical_metrics dict (same shape as helpers.theoretical_metrics_from_lap)
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

        # 3. Build observed metrics from analysis_json
        observed_metrics = _extract_observed_metrics(analysis_json)
        if not observed_metrics.get("best_s"):
            logger.debug("OCP downstream: no observed best_s, skipping scoring")
            return

        # 4. Re-score with OCP theoretical
        from scoring.scorer import score_session

        session_type = analysis_json.get("session_type", "practice")
        corner_coaching = analysis_json.get("corner_coaching", [])

        new_scores = score_session(
            observed_metrics,
            theo_metrics,
            session_type,
            corner_coaching=corner_coaching,
        )

        # 5. Update analysis_json with new scores and theoretical method
        analysis_json["score_result"] = new_scores
        analysis_json["theoretical_metrics"] = theo_metrics
        analysis_json["simulation_method"] = "ocp"

        # 6. Re-run corner analysis if corners exist
        corners = analysis_json.get("corners", [])
        if corners and len(corners) > 0:
            _update_corner_targets(analysis_json, result, corners)

        # 7. Persist updated analysis_json
        _persist_updated_analysis(conn, session_id, analysis_json)

        # 8. Update score_details table (used by /scores API endpoint)
        _update_score_details_table(conn, session_id, new_scores)

        # 9. Update sessions.total_score and sessions.grade columns
        _update_session_score_columns(conn, session_id, new_scores)

        logger.info(
            "OCP downstream update complete for session %s: "
            "score=%.1f/%s, method=ocp",
            session_id,
            new_scores.get("total_score", 0),
            new_scores.get("grade", "?"),
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


def _persist_updated_analysis(conn, session_id, analysis_json):
    """Persist the fully updated analysis_json (scores + coaching + OCP) to DB."""
    import os
    if os.environ.get("USE_PG", "0") not in ("0", "false", "no"):
        conn.execute(
            "UPDATE sessions SET analysis_json = ?::jsonb WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )
    else:
        conn.execute(
            "UPDATE sessions SET analysis_json = ? WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )
    conn.commit()


def _update_score_details_table(conn, session_id, new_scores):
    """Update the score_details table so /scores API serves OCP-based scores."""
    try:
        from web.repos.score_repo import insert_score_details
        # insert_score_details expects a summary dict with "score_result" key
        summary = {"score_result": new_scores}
        insert_score_details(conn, session_id, summary)
        conn.commit()
    except Exception:
        logger.debug("score_details table update skipped", exc_info=True)


def _update_session_score_columns(conn, session_id, new_scores):
    """Update sessions.total_score and sessions.grade so list endpoint reflects OCP scores."""
    try:
        total = new_scores.get("total_score")
        grade = new_scores.get("grade")
        conn.execute(
            "UPDATE sessions SET total_score = ?, grade = ? WHERE id = ?",
            (total, grade, session_id),
        )
        conn.commit()
    except Exception:
        logger.debug("sessions score columns update skipped", exc_info=True)


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
