"""
Stage 10a — Per-Corner OCP Solve
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs a per-corner QSS min-time solve on each detected corner BEFORE the
full-lap theoretical solver. Produces optimal speed profiles and 3 ranked
actionables per corner.

The per-corner results are later used to warm-start the full-lap solver
(Stage 10) for better convergence and globally-informed optimization.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"


def run_corner_ocp(
    corners: list[dict[str, Any]],
    best_lap_df: Optional[pd.DataFrame],
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: Optional[pd.DataFrame],
    friction_circle: Any,
    *,
    excluded_laps: frozenset[int] = frozenset(),
    margin_m: float = 50.0,
) -> Optional[list[dict[str, Any]]]:
    """Run per-corner QSS solve on each corner.

    Parameters
    ----------
    corners : list of corner dicts with s_start, s_end, s_apex, corner_id
    best_lap_df : DataFrame of the best lap (distance, speed, etc.)
    resampled_laps : all resampled laps
    curvature_profile : DataFrame with Distance (m) and curvature columns
    friction_circle : friction/envelope object (CapabilityEnvelope or dict)
    margin_m : extra distance before/after corner for approach/exit context

    Returns
    -------
    List of CornerOCPResult.to_dict() dicts, or None if inputs insufficient.
    """
    if not corners or best_lap_df is None or curvature_profile is None:
        logger.info("S10a: skipping — missing corners, best lap, or curvature")
        return None

    try:
        from kart_envelope.solver.corner_solver import (
            solve_corner_qss,
            solve_corner_qss_envelope,
            generate_actionables,
            CornerOCPResult,
        )
    except ImportError:
        logger.warning("S10a: corner_solver not available")
        return None

    # Extract curvature and distance arrays from profile
    curv_col = None
    for col in curvature_profile.columns:
        if "curvature" in col.lower() or "kappa" in col.lower():
            curv_col = col
            break
    if curv_col is None:
        logger.warning("S10a: no curvature column found in curvature_profile")
        return None

    dist_col = None
    for col in curvature_profile.columns:
        if "distance" in col.lower() or col == _COL_DIST:
            dist_col = col
            break
    if dist_col is None and _COL_DIST in curvature_profile.columns:
        dist_col = _COL_DIST

    if dist_col is None:
        logger.warning("S10a: no distance column found in curvature_profile")
        return None

    full_dist = curvature_profile[dist_col].values.astype(float)
    full_curv = curvature_profile[curv_col].values.astype(float)

    # Get best lap speed profile for boundary conditions + actual comparison
    if _COL_DIST in best_lap_df.columns and _COL_SPEED in best_lap_df.columns:
        best_dist = best_lap_df[_COL_DIST].values.astype(float)
        best_speed = best_lap_df[_COL_SPEED].values.astype(float)
    else:
        logger.warning("S10a: best lap missing Distance/Speed columns")
        return None

    # Determine friction coefficient
    mu = _extract_mu(friction_circle)

    # Check if we have a full CapabilityEnvelope
    has_envelope = hasattr(friction_circle, "max_cornering_speed") and hasattr(
        friction_circle, "max_longitudinal_accel"
    )

    results: list[dict[str, Any]] = []

    for corner in corners:
        cid = corner.get("corner_id")
        s_start = corner.get("s_start")
        s_end = corner.get("s_end")

        if cid is None or s_start is None or s_end is None:
            continue

        try:
            result = _solve_single_corner(
                corner_id=cid,
                s_start=s_start,
                s_end=s_end,
                margin_m=margin_m,
                full_dist=full_dist,
                full_curv=full_curv,
                best_dist=best_dist,
                best_speed=best_speed,
                mu=mu,
                envelope=friction_circle if has_envelope else None,
            )
            if result is not None:
                results.append(result.to_dict())
        except Exception:
            logger.warning("S10a: corner %s solve failed", cid, exc_info=True)

    if not results:
        return None

    total_delta = sum(r.get("time_delta_s", 0) for r in results)
    logger.info(
        "S10a: solved %d/%d corners, total time delta %.3f s",
        len(results), len(corners), total_delta,
    )
    return results


def _solve_single_corner(
    corner_id: int,
    s_start: float,
    s_end: float,
    margin_m: float,
    full_dist: np.ndarray,
    full_curv: np.ndarray,
    best_dist: np.ndarray,
    best_speed: np.ndarray,
    mu: float,
    envelope: Any | None = None,
) -> "CornerOCPResult | None":
    """Solve a single corner and generate actionables."""
    from kart_envelope.solver.corner_solver import (
        solve_corner_qss,
        solve_corner_qss_envelope,
        generate_actionables,
    )

    # Expand zone with margin
    zone_start = s_start - margin_m
    zone_end = s_end + margin_m

    # Slice curvature to zone
    mask = (full_dist >= zone_start) & (full_dist <= zone_end)
    if mask.sum() < 3:
        return None

    seg_dist = full_dist[mask]
    seg_curv = full_curv[mask]

    # Get boundary speeds from best lap
    v_entry = float(np.interp(zone_start, best_dist, best_speed))
    v_exit = float(np.interp(zone_end, best_dist, best_speed))

    # Get actual speeds at corner phases from best lap
    actual_entry = float(np.interp(s_start, best_dist, best_speed))
    actual_apex_dist = (s_start + s_end) / 2.0
    actual_apex = float(np.interp(actual_apex_dist, best_dist, best_speed))
    actual_exit = float(np.interp(s_end, best_dist, best_speed))

    # Compute actual time through corner
    cmask = (best_dist >= s_start) & (best_dist <= s_end)
    actual_time = 0.0
    if cmask.sum() >= 2:
        cd = best_dist[cmask]
        cs = best_speed[cmask]
        for i in range(len(cd) - 1):
            v_avg = (cs[i] + cs[i + 1]) / 2.0
            if v_avg > 0.1:
                actual_time += (cd[i + 1] - cd[i]) / v_avg

    # Solve OCP
    if envelope is not None:
        result = solve_corner_qss_envelope(
            curvature=seg_curv,
            distances=seg_dist,
            envelope=envelope,
            v_entry=v_entry,
            v_exit=v_exit,
        )
    else:
        result = solve_corner_qss(
            curvature=seg_curv,
            distances=seg_dist,
            mu=mu,
            v_entry=v_entry,
            v_exit=v_exit,
        )

    result.corner_id = corner_id
    result.actual_entry_speed = actual_entry
    result.actual_apex_speed = actual_apex
    result.actual_exit_speed = actual_exit
    result.actual_time_s = actual_time
    result.time_delta_s = actual_time - result.optimal_time_s
    result.speed_delta_apex = actual_apex - result.optimal_apex_speed

    # Get brake/throttle distances if available (for actionable generation)
    # These come from the speed profile: brake point = where speed starts dropping,
    # throttle point = where speed starts increasing after apex
    opt_speeds = np.array(result.speeds)
    opt_dists = np.array(result.distances)
    optimal_brake_dist = _find_brake_point(opt_dists, opt_speeds)
    actual_brake_dist = _find_brake_point(best_dist[(best_dist >= zone_start) & (best_dist <= zone_end)],
                                          best_speed[(best_dist >= zone_start) & (best_dist <= zone_end)])
    optimal_throttle_dist = _find_throttle_point(opt_dists, opt_speeds)
    actual_throttle_dist = _find_throttle_point(best_dist[(best_dist >= zone_start) & (best_dist <= zone_end)],
                                                best_speed[(best_dist >= zone_start) & (best_dist <= zone_end)])

    # Generate 3 actionables
    corner_length = s_end - s_start
    result.actionables = generate_actionables(
        result,
        actual_brake_dist=actual_brake_dist,
        optimal_brake_dist=optimal_brake_dist,
        actual_throttle_dist=actual_throttle_dist,
        optimal_throttle_dist=optimal_throttle_dist,
        corner_length_m=max(corner_length, 10.0),
    )

    return result


def _extract_mu(friction_circle: Any) -> float:
    """Extract friction coefficient from whatever object we got."""
    if hasattr(friction_circle, "mu_session"):
        return float(friction_circle.mu_session)
    if hasattr(friction_circle, "mu"):
        return float(friction_circle.mu)
    if isinstance(friction_circle, dict):
        return float(friction_circle.get("mu", friction_circle.get("mu_session", 1.2)))
    return 1.2  # safe default for karts


def _find_brake_point(distances: np.ndarray, speeds: np.ndarray) -> float | None:
    """Find distance where speed starts decreasing (brake application)."""
    if len(distances) < 3 or len(speeds) < 3:
        return None
    dv = np.diff(speeds)
    for i in range(len(dv)):
        if dv[i] < -0.5:  # speed dropping > 0.5 m/s per step
            return float(distances[i])
    return None


def _find_throttle_point(distances: np.ndarray, speeds: np.ndarray) -> float | None:
    """Find distance where speed starts increasing after the apex (throttle on)."""
    if len(distances) < 3 or len(speeds) < 3:
        return None
    apex_idx = int(np.argmin(speeds))
    dv = np.diff(speeds[apex_idx:])
    for i in range(len(dv)):
        if dv[i] > 0.3:  # speed increasing > 0.3 m/s per step
            return float(distances[apex_idx + i])
    return None
