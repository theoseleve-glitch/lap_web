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

_MAX_CALIBRATION_PASSES = 1
_CONVERGENCE_PCT = 2.0  # residual % threshold (relaxed for speed)


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
        soft_time_limit=120,   # 2 min — IPOPT should converge within 1000 iters
        time_limit=180,        # 3 min hard kill
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

        # Adaptive mesh: ~3-4m spacing, clamped 150–400 nodes
        track_len = float(curvature_profile["distance_m"].iloc[-1] - curvature_profile["distance_m"].iloc[0])
        n_nodes = max(150, min(400, int(track_len / 3)))
        logger.info("OCP mesh: track_len=%.0fm → %d nodes (%.1fm spacing)", track_len, n_nodes, track_len / n_nodes)
        mesh = build_mesh_from_curvature_profile(curvature_profile, n_nodes=n_nodes)
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

        # Single-stage solve (refinement skipped for speed — target <30s/lap)
        logger.info("OCP solve: session %s, %d nodes", session_id, len(mesh.s))
        result = solve_ocp(mesh, params, tire, warm_start=warm_start, max_iter=1000, tol=1e-4)

        actual_apex, theo_apex = _extract_paired_apex_speeds(analysis_json, result, best_lap_df)
        actual_straights, theo_straights = _extract_paired_straight_speeds(analysis_json, result, best_lap_df)
        actual_braking, theo_braking = _extract_paired_braking_dists(result, analysis_json)

        logger.info("OCP calibration data: %d apex pairs, %d straight pairs, %d braking pairs",
                     len(actual_apex), len(actual_straights), len(actual_braking))

        calibration_meta = {}
        for cal_pass in range(_MAX_CALIBRATION_PASSES):
            cal = calibrate_params(
                mu_ref=params.mu_ref,
                P_max=params.P_max,
                F_brake_max=params.F_brake_max,
                actual_apex_speeds=actual_apex,
                theoretical_apex_speeds=theo_apex,
                actual_straight_end_speeds=actual_straights,
                theoretical_straight_end_speeds=theo_straights,
                actual_braking_dists=actual_braking,
                theoretical_braking_dists=theo_braking,
            )
            calibration_meta = cal.to_dict()

            if cal.residual_pct <= _CONVERGENCE_PCT:
                break

            # Update params and re-solve (clamp to prevent degenerate values).
            # Upper clamp on mu_ref: no tire exceeds ~2.2 (same ceiling as
            # param_extractor); calibration overshoot indicates GPS/curvature
            # noise, not superhuman grip.
            params = dataclasses.replace(
                params,
                mu_ref=min(max(cal.mu_ref_final, 0.3), 2.2),
                P_max=max(cal.P_max_final, 1000.0),
                F_brake_max=max(cal.F_brake_final, 500.0),
            )
            tire = LoadSensitiveTire(
                mu_ref=params.mu_ref,
                Fz_ref=params.Fz_static_per_axle,
                sensitivity=params.load_sensitivity,
            )
            result = solve_ocp(mesh, params, tire, warm_start=result.speed_profile)
            actual_apex, theo_apex = _extract_paired_apex_speeds(analysis_json, result, best_lap_df)
            actual_straights, theo_straights = _extract_paired_straight_speeds(analysis_json, result, best_lap_df)
            actual_braking, theo_braking = _extract_paired_braking_dists(result, analysis_json)

        if not result.converged:
            logger.warning("OCP solver did not converge for session %s", session_id)

        result_dict = result.to_dict()
        result_dict["calibration"] = calibration_meta
        result_dict["corner_times"] = _compute_corner_times(result, analysis_json)

        # Store OCP result in the in-memory analysis_json so that
        # _update_downstream (which persists analysis_json) doesn't
        # overwrite it with the stale pre-OCP version.
        analysis_json["theoretical_ocp"] = result_dict

        # Safety persist: write OCP result now, before downstream.
        # If downstream crashes, OCP data is still in the DB.
        _persist_ocp_only(conn, session_id, analysis_json)

        logger.info(
            "OCP result stored for session %s: %.2fs (converged=%s, %.1fs wall)",
            session_id, result.lap_time_s, result.converged,
            result.solver_meta["wall_time_s"],
        )

        # Update downstream: scoring, coaching, corner targets.
        # _persist_all inside _update_downstream writes the complete
        # analysis_json (including theoretical_ocp + scores) in a single commit.
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

    Connection lifecycle: creates a connection and returns it on success.
    On failure, closes the connection before re-raising to prevent leaks.
    """
    from web.db import get_db_connection
    from web.repos import gps_repo, theoretical_repo, lap_repo
    import numpy as np
    import pandas as pd

    conn = get_db_connection()
    try:
        # Set RLS context if PG
        if workspace_id is not None:
            _set_rls_if_pg(conn, workspace_id)

        # Load analysis_json for corners, scoring, vehicle params
        row = conn.execute(
            "SELECT analysis_json FROM sessions WHERE session_id = :sid",
            {"sid": session_id},
        ).fetchone()
        if row is None:
            raise ValueError(f"Session {session_id} not found")
        raw = row["analysis_json"] if isinstance(row, dict) else row[0]
        analysis_json = json.loads(raw) if raw else {}

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
                    data = {
                        "Distance (m)": [d - d0 for d in dists],
                        "Speed (m/s)": speeds,
                    }
                    # Include acceleration data for param_extractor if available
                    accel_lat = trace.get("accel_lat")
                    accel_long = trace.get("accel_long")
                    if accel_lat and len(accel_lat) == len(dists):
                        data["accel_lat_mps2"] = accel_lat
                    if accel_long and len(accel_long) == len(dists):
                        data["accel_long_mps2"] = accel_long
                    best_lap_df = pd.DataFrame(data)
                    logger.info("OCP: loaded best lap %d (%d points, accel=%s)",
                                best_lap_num, len(dists),
                                "lat+long" if accel_lat and accel_long else
                                "lat" if accel_lat else
                                "long" if accel_long else "none")

        # ── Curvature from reference line ──
        curvature_profile = None
        ref_line = theoretical_repo.get_reference_line(conn, session_id)
        if ref_line:
            ref_dists = ref_line.get("distances", [])
            ref_lats = ref_line.get("latitudes", [])
            ref_lons = ref_line.get("longitudes", [])
            if (ref_dists and ref_lats and ref_lons
                    and len(ref_dists) > 10
                    and len(ref_dists) == len(ref_lats) == len(ref_lons)):
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
            try:
                from vehicle_model import VehicleParameters, VehicleClass
                vc_str = vp_data.get("vehicle_class", "unknown")
                try:
                    vc = VehicleClass(vc_str)
                except ValueError:
                    logger.warning("Unknown vehicle_class %r, falling back to UNKNOWN", vc_str)
                    vc = VehicleClass.UNKNOWN
                vehicle_params = VehicleParameters(
                    vehicle_class=vc,
                    estimated_mass_kg=vp_data.get("estimated_mass_kg"),
                    peak_lateral_g=vp_data.get("peak_lateral_g", 1.0),
                    peak_braking_g=vp_data.get("peak_braking_g", 1.0),
                    peak_traction_g=vp_data.get("peak_traction_g", 0.5),
                    has_downforce=vp_data.get("has_downforce", False),
                    has_abs=vp_data.get("has_abs", False),
                    rolling_resistance_est=vp_data.get("rolling_resistance_est", 0.015),
                    aero_drag_factor_est=vp_data.get("aero_drag_factor_est", 0.0),
                    downforce_coeff_est=vp_data.get("downforce_coeff_est", 0.0),
                )
            except Exception:
                logger.warning("Failed to parse vehicle_params, using class defaults", exc_info=True)

        return conn, analysis_json, best_lap_df, curvature_profile, vehicle_params

    except Exception:
        # Close connection on failure to prevent leak — caller never
        # receives the conn reference, so it can't close it.
        try:
            conn.close()
        except Exception:
            pass
        raise


def _curvature_from_reference_line(distances, lats, lons):
    """Compute curvature profile from reference line GPS coordinates.

    Uses finite-difference on local ENU projection to get kappa(s).
    Returns a DataFrame with distance_m and curvature_1pm columns.
    """
    import numpy as np
    import pandas as pd

    # Filter out NaN in lat/lon (GPS dropouts)
    valid = np.isfinite(distances) & np.isfinite(lats) & np.isfinite(lons)
    distances = distances[valid]
    lats = lats[valid]
    lons = lons[valid]

    # Ensure strictly increasing distances (GPS can produce duplicates/decreases)
    mono_mask = np.concatenate(([True], np.diff(distances) > 0.01))
    distances = distances[mono_mask]
    lats = lats[mono_mask]
    lons = lons[mono_mask]

    n = len(distances)
    if n < 20:
        return None

    # Convert lat/lon to local meters (simple equirectangular)
    lat0 = np.mean(lats)  # safe: NaN filtered above
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

    # Enforce periodicity for closed circuits: the solver constrains
    # v[0] == v[N-1], so start/end curvatures must match to avoid
    # conflicting friction ellipse constraints at the join.
    if n > 2:
        kappa_avg = (kappa_full[0] + kappa_full[-1]) / 2.0
        kappa_full[0] = kappa_avg
        kappa_full[-1] = kappa_avg

    return pd.DataFrame({
        "distance_m": distances,
        "curvature_1pm": kappa_full,
    })


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
        distances = np.array([p["distance_m"] for p in speed_data], dtype=float)
        speeds = np.array([p["speed_mps"] for p in speed_data], dtype=float)
        # Filter NaN from QSS result before interpolating
        valid = np.isfinite(distances) & np.isfinite(speeds)
        if valid.sum() < 10:
            return None
        d_valid = distances[valid]
        s_valid = speeds[valid]
        # np.interp requires monotonically increasing xp; enforce it by
        # sorting on distance (handles rare corruption / duplicate distances).
        sort_idx = np.argsort(d_valid)
        d_valid = d_valid[sort_idx]
        s_valid = s_valid[sort_idx]
        warm = np.interp(mesh.s, d_valid, s_valid)
        warm = np.maximum(warm, 2.0)
        # Final NaN safety (shouldn't happen after filtering, but belt-and-suspenders)
        warm = np.nan_to_num(warm, nan=10.0)
        return warm
    except (KeyError, ValueError, TypeError):
        return None


def _extract_paired_apex_speeds(analysis_json: dict, result, best_lap_df=None):
    """Extract paired (actual, theoretical) apex speeds for calibration.

    Returns two lists of the same length — one actual, one theoretical —
    for the exact same corners.  This guarantees actual[i] and theoretical[i]
    always refer to the same corner, preventing calibration drift from
    misaligned independent filtering.
    """
    import numpy as np
    corners = analysis_json.get("corners", [])
    if not isinstance(corners, list) or not corners:
        return [], []
    if best_lap_df is None:
        return [], []
    dist_col = best_lap_df.get("Distance (m)")
    speed_col = best_lap_df.get("Speed (m/s)")
    if dist_col is None or speed_col is None:
        return [], []
    drv_dist = np.array(dist_col, dtype=float)
    drv_speed = np.array(speed_col, dtype=float)
    actual, theo = [], []
    for c in corners:
        s_apex = c.get("s_apex")
        if s_apex is None:
            continue
        v_actual = float(np.interp(float(s_apex), drv_dist, drv_speed))
        v_theo = float(np.interp(float(s_apex), result.distance_profile, result.speed_profile))
        if v_actual > 0.5 and v_theo > 0.5:
            actual.append(v_actual)
            theo.append(v_theo)
    return actual, theo


def _extract_paired_straight_speeds(analysis_json: dict, result, best_lap_df=None):
    """Extract paired (actual, theoretical) straight-end speeds for calibration.

    Speed at corner entry (s_start) approximates peak speed at the end of
    the preceding straight.  Returns paired lists for P_max calibration.
    """
    import numpy as np
    corners = analysis_json.get("corners", [])
    if not isinstance(corners, list) or not corners:
        return [], []
    if best_lap_df is None:
        return [], []
    dist_col = best_lap_df.get("Distance (m)")
    speed_col = best_lap_df.get("Speed (m/s)")
    if dist_col is None or speed_col is None:
        return [], []
    drv_dist = np.array(dist_col, dtype=float)
    drv_speed = np.array(speed_col, dtype=float)
    actual, theo = [], []
    for c in corners:
        s_start = c.get("s_start")
        if s_start is None:
            continue
        v_actual = float(np.interp(float(s_start), drv_dist, drv_speed))
        v_theo = float(np.interp(float(s_start), result.distance_profile, result.speed_profile))
        if v_actual > 0.5 and v_theo > 0.5:
            actual.append(v_actual)
            theo.append(v_theo)
    return actual, theo


def _extract_paired_braking_dists(result, analysis_json: dict):
    """Extract paired (actual, theoretical) braking distances for calibration.

    Returns two lists of the same length — one actual, one theoretical —
    for the exact same corners.  Uses paired iteration to prevent the
    independent-filter pairing bug where different d > 1.0 thresholds
    could cause misaligned lists.
    """
    import math
    import numpy as np

    corner_perfs = analysis_json.get("corner_performances", [])
    if not isinstance(corner_perfs, list) or not corner_perfs:
        return [], []

    dist_arr = np.array(result.distance_profile, dtype=float)
    speed_arr = np.array(result.speed_profile, dtype=float)
    if len(dist_arr) < 10:
        return [], []

    # Compute acceleration profile from OCP speed
    ds = np.diff(dist_arr)
    dv = np.diff(speed_arr)
    avg_v = (speed_arr[:-1] + speed_arr[1:]) / 2.0 + 1e-6
    dt = np.where(ds > 0.01, ds / avg_v, 0.01)
    accel = dv / dt
    accel = np.where(np.isfinite(accel), accel, 0.0)

    actual, theo = [], []
    for cp in corner_perfs:
        s_start = cp.get("s_start")
        bp_actual = cp.get("braking_point_actual_m")
        if s_start is None or bp_actual is None:
            continue
        if not math.isfinite(float(bp_actual)) or not math.isfinite(float(s_start)):
            continue

        s_start_f = float(s_start)
        d_actual = abs(s_start_f - float(bp_actual))

        # Find OCP braking point: walk backwards from s_start along
        # the OCP profile until deceleration ends (accel >= 0)
        idx = np.searchsorted(dist_arr, s_start_f) - 1
        if idx < 1 or idx >= len(accel):
            continue
        brake_start_idx = idx
        while brake_start_idx > 0 and accel[brake_start_idx] < -0.5:
            brake_start_idx -= 1
        theo_bp = float(dist_arr[brake_start_idx])
        d_theo = abs(s_start_f - theo_bp)

        # Both must be meaningful braking events (> 1m)
        if d_actual > 1.0 and d_theo > 1.0:
            actual.append(d_actual)
            theo.append(d_theo)

    return actual, theo


# Backwards-compatible wrappers (used only in _run_ocp_impl call site)
def _extract_actual_braking_dists(analysis_json: dict) -> list[float]:
    """Extract actual braking distances (legacy wrapper — prefer _extract_paired_braking_dists)."""
    import math
    corner_perfs = analysis_json.get("corner_performances", [])
    if not isinstance(corner_perfs, list):
        return []
    dists = []
    for cp in corner_perfs:
        bp = cp.get("braking_point_actual_m")
        s_start = cp.get("s_start")
        if bp is not None and s_start is not None:
            if math.isfinite(float(bp)) and math.isfinite(float(s_start)):
                d = abs(float(s_start) - float(bp))
                if d > 1.0:
                    dists.append(d)
    return dists


def _extract_theoretical_braking_dists(result, analysis_json: dict) -> list[float]:
    """Extract theoretical braking distances (legacy wrapper — prefer _extract_paired_braking_dists)."""
    _, theo = _extract_paired_braking_dists(result, analysis_json)
    return theo


def _compute_corner_times(result, analysis_json: dict) -> list[dict]:
    """Compute per-corner theoretical time from OCP speed profile.

    For each corner with s_start/s_end, integrates dt = ds / v_avg over the
    OCP speed profile to get the theoretical time through that corner.
    Returns list of {"corner_id", "time_s", "apex_speed_mps", "min_speed_mps"}.
    """
    import numpy as np

    corners = analysis_json.get("corners", [])
    if not corners:
        return []

    dist = np.array(result.distance_profile, dtype=float)
    speed = np.array(result.speed_profile, dtype=float)
    if len(dist) < 2:
        return []

    # Precompute cumulative time
    ds = np.diff(dist)
    v_avg = np.maximum((speed[:-1] + speed[1:]) / 2.0, 2.0)
    dt = ds / v_avg
    cum_time = np.zeros(len(dist))
    cum_time[1:] = np.cumsum(dt)

    corner_times = []
    for c in corners:
        cid = c.get("corner_id")
        s_start = c.get("s_start")
        s_end = c.get("s_end")
        s_apex = c.get("s_apex")
        if s_start is None or s_end is None:
            continue

        s_start_f = float(s_start)
        s_end_f = float(s_end)

        # Interpolate cumulative time at entry and exit
        t_entry = float(np.interp(s_start_f, dist, cum_time))
        t_exit = float(np.interp(s_end_f, dist, cum_time))

        if s_end_f >= s_start_f:
            corner_time = t_exit - t_entry
        else:
            # Corner wraps around start/finish line (s_start > s_end).
            # Time = (track_end - entry) + (exit - track_start).
            total_time = cum_time[-1]
            corner_time = (total_time - t_entry) + t_exit

        # Speed at apex
        apex_speed = None
        if s_apex is not None:
            apex_speed = round(float(np.interp(float(s_apex), dist, speed)), 3)

        # Min speed in corner section
        if s_end_f >= s_start_f:
            mask = (dist >= s_start_f) & (dist <= s_end_f)
        else:
            # Wrap-around: corner spans start/finish line
            mask = (dist >= s_start_f) | (dist <= s_end_f)
        section_speeds = speed[mask]
        min_speed = round(float(section_speeds.min()), 3) if len(section_speeds) > 0 else apex_speed

        corner_times.append({
            "corner_id": cid,
            "time_s": round(corner_time, 4),
            "apex_speed_mps": apex_speed,
            "min_speed_mps": min_speed,
        })

    return corner_times


def _update_downstream(conn, session_id, result, result_dict, analysis_json,
                       workspace_id=None, best_lap_df=None):
    """Re-run corner analysis, coaching, and scoring with OCP theoretical data.

    Called after analysis_json["theoretical_ocp"] is set in-memory and
    persisted via _persist_ocp_only.  Updates the same DB row with
    refreshed scores, corner metrics, and coaching text.
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
        # Compute theoretical accel/braking from speed profile + distance
        dists = np.array(result.distance_profile)
        if len(speeds) > 1 and len(dists) == len(speeds):
            ds = np.diff(dists)
            dv = np.diff(speeds)
            dt_seg = np.where(ds > 0, ds / ((speeds[:-1] + speeds[1:]) / 2 + 1e-6), 0.1)
            accel_arr = dv / dt_seg
            accel_arr = accel_arr[np.isfinite(accel_arr)]
            theo_accel_max = float(np.max(accel_arr)) if len(accel_arr) > 0 else 0.0
            theo_brake_max = float(np.max(np.abs(accel_arr[accel_arr < 0]))) if np.any(accel_arr < 0) else 0.0
        else:
            theo_accel_max = 0.0
            theo_brake_max = 0.0

        theo_metrics = {
            "best_s": float(result.lap_time_s),
            "simulation_method": "ocp",
            "method": "ocp",
            "max_speed_mps": float(speeds.max()),
            "avg_speed_mps": float(speeds.mean()),
            "min_speed_mps": float(speeds.min()),
            "speed_mean_mps": float(speeds.mean()),
            "accel_max_mps2": theo_accel_max,
            "braking_max_mps2": theo_brake_max,
            "confidence": 1.0 if result.converged else 0.7,
        }

        # 2. Use best_lap_df passed from caller (already loaded from DB)
        corners = analysis_json.get("corners", [])
        friction_model = analysis_json.get("friction_model") or {"max_lateral_g": 1.2}
        resampled_laps = {0: best_lap_df} if best_lap_df is not None else {}
        available_columns = set(best_lap_df.columns) if best_lap_df is not None else set()

        # 3. Build observed metrics
        observed_metrics = _extract_observed_metrics(analysis_json, best_lap_df)
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
                    analysis_json["corner_performances"] = corner_perfs
            except Exception:
                logger.warning("OCP downstream: corner analysis failed", exc_info=True)

        # 5. Re-run coaching analyzers
        #    Build a coaching-compatible theoretical DataFrame with column names
        #    that analyze_exit_cascades expects: "Distance (m)" and "Speed (m/s)".
        #    The dict format (theo_result_dict) silently fails in exit cascade
        #    analysis because it lacks .empty and column access.
        theo_coaching_df = pd.DataFrame({
            "Distance (m)": np.array(result.distance_profile),
            "Speed (m/s)": np.array(result.speed_profile),
        })

        analyzer_bundle = None
        if corner_perfs:
            try:
                from pipeline.stages.s13_coaching_v3 import run_coaching_analyzers
                analyzer_bundle = run_coaching_analyzers(
                    corner_perfs, best_lap_df, theo_coaching_df,
                    friction_model, resampled_laps, available_columns,
                )
            except Exception:
                logger.warning("OCP downstream: coaching analyzers failed", exc_info=True)

        # 6. Re-score with OCP theoretical
        new_scores = analysis_json.get("score_result", {})
        try:
            from scoring.scorer import score_session

            session_type = analysis_json.get("session_type", "practice")
            new_scores = score_session(
                observed_metrics, theo_metrics, session_type,
                corner_coaching=corner_perfs or [],
            )
        except Exception:
            logger.warning("OCP downstream: scoring failed, keeping existing scores", exc_info=True)

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
        "accel_long_mps2": np.array(result.a_long_profile),
        "accel_lat_mps2": np.array(result.a_lat_profile),
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


def _extract_observed_metrics(analysis_json: dict, best_lap_df=None) -> dict:
    """Extract observed session metrics from analysis_json + best_lap_df for scoring."""
    import numpy as _np
    metrics: dict = {}

    # Best lap time
    lap_times = analysis_json.get("lap_times", [])
    if isinstance(lap_times, list) and lap_times:
        valid = [t for t in lap_times if isinstance(t, (int, float)) and t > 0]
        if valid:
            metrics["best_s"] = min(valid)
            metrics["n_laps"] = len(valid)
            arr = _np.array(valid)
            metrics["cv_pct"] = float(_np.std(arr) / _np.mean(arr) * 100) if len(arr) > 1 else 0.0
            sorted_arr = _np.sort(arr)
            metrics["best_to_median_s"] = float(sorted_arr[0] - _np.median(arr))

    # Speed/accel metrics — compute directly from best_lap_df (pipeline doesn't
    # store speed_trace_best in analysis_json, so we must use the raw data)
    if best_lap_df is not None:
        if "Speed (m/s)" in best_lap_df.columns:
            speed_arr = best_lap_df["Speed (m/s)"].to_numpy(dtype=float)
            speed_valid = speed_arr[_np.isfinite(speed_arr) & (speed_arr > 0.5)]
            if len(speed_valid) > 0:
                metrics["speed_mean_mps"] = float(_np.mean(speed_valid))
        if "accel_long_mps2" in best_lap_df.columns:
            accel = best_lap_df["accel_long_mps2"].to_numpy(dtype=float)
            accel_valid = accel[_np.isfinite(accel)]
            if len(accel_valid) > 0:
                metrics["accel_max_mps2"] = float(_np.max(accel_valid))
                braking = _np.abs(accel_valid[accel_valid < 0])
                if len(braking) > 0:
                    metrics["braking_max_mps2"] = float(_np.max(braking))

    # Robustness metrics (pass through from existing analysis_json or score_result)
    for key in ("early_mean_s", "late_mean_s", "early_yaw_var", "late_yaw_var",
                "accel_max_mps2", "braking_max_mps2"):
        if key not in metrics:
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

    # If corner_coaching is empty but raw corners exist, seed from corners
    # (happens when pipeline's theoretical stage produced method=none)
    if not corner_coaching and corners:
        corner_coaching = [dict(c) for c in corners if isinstance(c, dict)]

    updated_coaching = []
    for cc in corner_coaching:
        cc = dict(cc)  # copy to avoid mutating original
        # Corner coaching entries may use either set of field names:
        #   - Corner detection:  s_start, s_end, s_apex
        #   - Coaching stage:    entry_distance_m, exit_distance_m, apex_distance_m
        # Must use `is not None` (not `or`) because 0.0 is a valid distance
        # at the start/finish line — `or` treats 0.0 as falsy.
        _s = cc.get("s_start")
        entry_m = _s if _s is not None else cc.get("entry_distance_m")
        _s = cc.get("s_end")
        exit_m = _s if _s is not None else cc.get("exit_distance_m")
        _s = cc.get("s_apex")
        apex_m = _s if _s is not None else cc.get("apex_distance_m")
        if apex_m is None and entry_m is not None and exit_m is not None:
            e, x = float(entry_m), float(exit_m)
            if e <= x:
                apex_m = (e + x) / 2.0
            else:
                # Wrap-around corner: entry near track end, exit near start.
                # Simple midpoint would land on the opposite side of the track.
                track_len = float(dist[-1]) if len(dist) > 0 else 1.0
                span = (track_len - e) + x
                apex_m = (e + span / 2.0) % track_len

        if apex_m is not None:
            v_apex = float(np.interp(float(apex_m), dist, speed))
            cc["apex_speed_target_kmh"] = round(v_apex * 3.6, 1)
            cc["theoretical_apex_mps"] = round(v_apex, 3)
        if entry_m is not None:
            v_entry = float(np.interp(float(entry_m), dist, speed))
            cc["entry_speed_target_kmh"] = round(v_entry * 3.6, 1)
            cc["theoretical_entry_mps"] = round(v_entry, 3)
        if exit_m is not None:
            v_exit = float(np.interp(float(exit_m), dist, speed))
            cc["exit_speed_target_kmh"] = round(v_exit * 3.6, 1)
            cc["theoretical_exit_mps"] = round(v_exit, 3)

        # Recompute time loss if actual and theoretical apex known
        actual_apex = cc.get("actual_apex_speed_mps")
        if actual_apex is not None and apex_m is not None:
            v_theo = float(np.interp(float(apex_m), dist, speed))
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
    # 1. analysis_json blob (column is text, not jsonb — no cast needed)
    conn.execute(
        "UPDATE sessions SET analysis_json = :aj WHERE session_id = :sid",
        {"aj": json.dumps(analysis_json), "sid": session_id},
    )

    # 2. Sync OCP-updated corner coaching to theoretical_data table.
    #    The corners API reads from theoretical_data.corner_coaching_json,
    #    not from sessions.analysis_json, so this is necessary for the
    #    frontend to see OCP speed targets.
    corner_coaching = analysis_json.get("corner_coaching")
    if corner_coaching:
        try:
            conn.execute(
                "UPDATE theoretical_data SET corner_coaching_json = :ccj WHERE session_id = :sid",
                {"ccj": json.dumps(corner_coaching), "sid": session_id},
            )
        except Exception:
            logger.debug("theoretical_data corner_coaching update skipped", exc_info=True)

    # 3. sessions.total_score + grade
    conn.execute(
        "UPDATE sessions SET total_score = :ts, grade = :gr WHERE session_id = :sid",
        {"ts": new_scores.get("total_score"), "gr": new_scores.get("grade"), "sid": session_id},
    )

    # 4. score_details table
    try:
        from web.repos.score_repo import insert_score_details
        insert_score_details(conn, session_id, {"score_result": new_scores})
    except Exception:
        logger.debug("score_details update skipped", exc_info=True)

    # Single commit preserves SET LOCAL RLS context
    conn.commit()


def _persist_ocp_only(conn, session_id, analysis_json: dict):
    """Safety persist: write the current analysis_json (with theoretical_ocp) to DB.

    Called before downstream processing so the OCP result survives even
    if scoring/coaching crashes.  _update_downstream will overwrite this
    with the full analysis_json (scores + coaching + OCP) on success.
    """
    conn.execute(
        "UPDATE sessions SET analysis_json = :aj WHERE session_id = :sid",
        {"aj": json.dumps(analysis_json), "sid": session_id},
    )
    conn.commit()
