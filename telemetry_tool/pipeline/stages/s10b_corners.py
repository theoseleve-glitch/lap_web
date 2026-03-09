"""
Stage 10b — Corner Analysis, Timelines & Intelligence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Steps 10c through 10f: corner performance analysis, event timelines,
advanced corner intelligence (brake release, coupling, targets, risk),
per-lap corner metrics, endurance analytics, and raceline optimization.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


# ── Step 10c: Corner analysis ──────────────────────────────────────────


def run_corner_analysis(
    corners: list[dict[str, Any]],
    best_lap_df: Optional[pd.DataFrame],
    theoretical_lap: Optional[pd.DataFrame],
    friction_model: Any,
    resampled_laps: dict[int, pd.DataFrame],
    excluded_laps: frozenset[int] = frozenset(),
) -> Optional[list[dict[str, Any]]]:
    """Step 10c: Corner analysis.

    Returns list of corner performance dicts, or ``None`` if
    unavailable or inputs are insufficient.
    """
    ca_mod = lazy_import("corner_analysis")
    if ca_mod is None:
        return None
    if not corners or not resampled_laps or best_lap_df is None:
        return None
    if theoretical_lap is None:
        return None

    perfs = ca_mod.analyze_corners(
        corners, best_lap_df, theoretical_lap, friction_model,
    )
    result = [p.to_dict() for p in perfs]
    n_corners = len(result)
    total_loss = sum(cp.get("time_loss_s", 0) for cp in result)
    logger.info(
        "Corner analysis: %d corners, total time loss %.3f s",
        n_corners,
        total_loss,
    )
    return result


# ── Step 10c-ii: Corner timeline detection ─────────────────────────────


def run_corner_timelines(
    corners: list[dict[str, Any]],
    best_lap_df: Optional[pd.DataFrame],
    resampled_laps: dict[int, pd.DataFrame],
    excluded_laps: frozenset[int] = frozenset(),
    *,
    data_quality: Any = None,
    theoretical_lap: Optional[pd.DataFrame] = None,
) -> list[dict[str, Any]]:
    """Step 10c-ii: Corner timeline detection.

    Returns list of timeline dicts (one per corner).
    """
    ca_mod = lazy_import("corner_analysis")
    if ca_mod is None or not hasattr(ca_mod, "detect_corner_events"):
        return []
    if not corners or best_lap_df is None:
        return []

    dq_score = getattr(data_quality, "overall_confidence", 1.0) if data_quality else 1.0

    theo_df = None
    if theoretical_lap is not None and isinstance(theoretical_lap, pd.DataFrame):
        theo_df = theoretical_lap

    timelines = []
    for c in corners:
        try:
            tl = ca_mod.detect_corner_events(c, best_lap_df, theo_df, dq_score)
            if theo_df is not None and hasattr(ca_mod, "compute_segment_losses"):
                ca_mod.compute_segment_losses(tl, best_lap_df, theo_df)
            if hasattr(ca_mod, "detect_corner_mistakes"):
                tl.mistakes = ca_mod.detect_corner_mistakes(tl, best_lap_df, c)
            timelines.append(tl)
        except Exception:
            logger.debug(
                "Corner timeline failed for corner %s",
                c.get("corner_id"),
                exc_info=True,
            )

    # Multi-lap stability
    if hasattr(ca_mod, "compute_event_stability") and resampled_laps:
        all_dfs = [
            resampled_laps[k]
            for k in sorted(resampled_laps.keys())
            if k not in excluded_laps
            and resampled_laps[k] is not None
            and len(resampled_laps[k]) >= 10
        ]
        if len(all_dfs) >= 3:
            try:
                stability = ca_mod.compute_event_stability(corners, all_dfs, dq_score)
                for tl in timelines:
                    cid_stab = stability.get(tl.corner_id, {})
                    tl.mrp_stability_std_m = cid_stab.get("MRP", 0.0)
                    tl.event_stability = cid_stab
            except Exception:
                logger.debug("Event stability failed", exc_info=True)

    result = [tl.to_dict() for tl in timelines]
    logger.info("Corner timelines: %d corners with events", len(result))
    return result


# ── Step 10c-iii: Advanced corner intelligence ─────────────────────────


def _rebuild_timeline_objects(ca_mod: Any, corner_timelines: list[dict[str, Any]]) -> list:
    """Reconstruct CornerTimeline objects from serialized dicts."""
    tl_objects = []
    for tl_dict in corner_timelines:
        events = [
            ca_mod.CornerEvent(
                ed["event_type"], ed["s_position"], ed["confidence"],
                ed["source_channel"], ed["value"], ed["available"],
            )
            for ed in tl_dict.get("events", [])
        ]
        tl_objects.append(ca_mod.CornerTimeline(
            corner_id=tl_dict["corner_id"],
            events=events,
            segment_losses_s=tl_dict.get("segment_losses_s", {}),
            segment_confidences=tl_dict.get("segment_confidences", {}),
            mistakes=tl_dict.get("mistakes", []),
            mrp_strength=tl_dict.get("mrp_strength", 0),
            mrp_stability_std_m=tl_dict.get("mrp_stability_std_m", 0),
            event_stability=tl_dict.get("event_stability", {}),
        ))
    return tl_objects


def _compute_brake_metrics(
    ca_mod: Any,
    tl_objects: list,
    corners: list[dict[str, Any]],
    best_lap_df: pd.DataFrame,
    dq_score: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute brake release and yaw coupling metrics per corner."""
    brake_release: list[dict[str, Any]] = []
    coupling: list[dict[str, Any]] = []
    for tl_obj, c in zip(tl_objects, corners):
        try:
            if hasattr(ca_mod, "compute_brake_release_metrics"):
                br = ca_mod.compute_brake_release_metrics(tl_obj, best_lap_df, c, dq_score)
                if br is not None:
                    brake_release.append({"corner_id": c.get("corner_id"), **br.to_dict()})
        except Exception:
            pass
        try:
            if hasattr(ca_mod, "compute_brake_yaw_coupling"):
                coup = ca_mod.compute_brake_yaw_coupling(tl_obj, best_lap_df, c, dq_score)
                if coup is not None:
                    coupling.append({"corner_id": c.get("corner_id"), **coup.to_dict()})
        except Exception:
            pass
    return brake_release, coupling


def _compute_corner_targets(
    ca_mod: Any,
    tl_objects: list,
    corners: list[dict[str, Any]],
    theoretical_lap: pd.DataFrame,
    best_lap_df: pd.DataFrame,
    dq_score: float,
) -> list[dict[str, Any]]:
    """Compute performance targets per corner using theoretical data."""
    targets: list[dict[str, Any]] = []
    for tl_obj, c in zip(tl_objects, corners):
        try:
            theo_tl = ca_mod.detect_corner_events(c, theoretical_lap, data_quality=dq_score)
            tgt = ca_mod.compute_corner_targets(c, tl_obj, theo_tl, theoretical_lap, best_lap_df, dq_score)
            if tgt is not None:
                if hasattr(ca_mod, "validate_corner_targets"):
                    ca_mod.validate_corner_targets(tgt, c)
                targets.append(tgt.to_dict())
        except Exception:
            pass
    return targets


def _compute_compound_metrics(
    ca_mod: Any,
    compound_groups: list,
    corner_performances: list[dict[str, Any]],
    corners: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute metrics for compound (linked) corner groups."""
    perf_objs = []
    for cp in corner_performances:
        if isinstance(cp, dict):
            perf_objs.append(ca_mod.CornerPerformance(
                corner_id=cp.get("corner_id", 0),
                s_start=cp.get("s_start", 0),
                s_end=cp.get("s_end", 0),
                time_loss_s=cp.get("time_loss_s", 0),
            ))
        else:
            perf_objs.append(cp)

    compound_data: list[dict[str, Any]] = []
    for cg in compound_groups:
        try:
            cm = ca_mod.compute_compound_metrics(cg, perf_objs, corners)
            if cm is not None:
                compound_data.append(cm.to_dict())
        except Exception:
            pass
    return compound_data


def _compute_risk_scores(
    ca_mod: Any,
    tl_objects: list,
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    excluded_laps: frozenset[int],
    dq_score: float,
) -> list[dict[str, Any]]:
    """Compute risk scores per corner across all valid laps."""
    all_dfs = [
        resampled_laps[k]
        for k in sorted(resampled_laps.keys())
        if k not in excluded_laps
        and resampled_laps[k] is not None
        and len(resampled_laps[k]) >= 10
    ]
    risk_data: list[dict[str, Any]] = []
    for tl_obj, c in zip(tl_objects, corners):
        try:
            risk = ca_mod.compute_corner_risk(tl_obj, all_dfs, c, dq_score)
            risk_data.append(risk.to_dict())
        except Exception:
            pass
    return risk_data


def run_advanced_corner_intelligence(
    corners: list[dict[str, Any]],
    corner_timelines: list[dict[str, Any]],
    corner_performances: Optional[list[dict[str, Any]]],
    best_lap_df: Optional[pd.DataFrame],
    resampled_laps: dict[int, pd.DataFrame],
    excluded_laps: frozenset[int] = frozenset(),
    *,
    data_quality: Any = None,
    theoretical_lap: Optional[pd.DataFrame] = None,
    compound_corners_raw: Optional[list] = None,
) -> Optional[dict[str, Any]]:
    """Step 10c-iii: Advanced corner intelligence.

    Returns a dict with brake_release, brake_yaw_coupling, corner_targets,
    compound_metrics, corner_risk_scores, and driver_style sub-keys.
    """
    ca_mod = lazy_import("corner_analysis")
    feat_mod = lazy_import("features")
    if ca_mod is None or not corner_timelines or best_lap_df is None:
        return None

    dq_score = getattr(data_quality, "overall_confidence", 1.0) if data_quality else 1.0
    result: dict[str, Any] = {}

    tl_objects = _rebuild_timeline_objects(ca_mod, corner_timelines)

    # Brake release + coupling
    brake_rel, coupling = _compute_brake_metrics(ca_mod, tl_objects, corners, best_lap_df, dq_score)
    result["brake_release"] = brake_rel
    result["brake_yaw_coupling"] = coupling

    # Corner targets (needs theoretical)
    if (theoretical_lap is not None
            and isinstance(theoretical_lap, pd.DataFrame)
            and hasattr(ca_mod, "compute_corner_targets")):
        result["corner_targets"] = _compute_corner_targets(
            ca_mod, tl_objects, corners, theoretical_lap, best_lap_df, dq_score,
        )

    # Compound metrics
    compound_groups = compound_corners_raw or []
    if compound_groups and corner_performances and hasattr(ca_mod, "compute_compound_metrics"):
        result["compound_metrics"] = _compute_compound_metrics(
            ca_mod, compound_groups, corner_performances, corners,
        )

    # Risk scores
    if hasattr(ca_mod, "compute_corner_risk") and resampled_laps:
        result["corner_risk_scores"] = _compute_risk_scores(
            ca_mod, tl_objects, corners, resampled_laps, excluded_laps, dq_score,
        )

    # Driver style
    if feat_mod is not None and hasattr(feat_mod, "compute_driver_style"):
        try:
            style = feat_mod.compute_driver_style(corner_performances, data_quality=dq_score)
            result["driver_style"] = style.to_dict()
        except Exception:
            pass

    return result


# ── Step 10d: Per-lap corner metrics ───────────────────────────────────


def run_per_lap_corner_metrics(
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    excluded_laps: frozenset[int] = frozenset(),
    *,
    theoretical_lap: Optional[pd.DataFrame] = None,
    friction_model: Any = None,
) -> list[dict[str, Any]]:
    """Step 10d: Per-lap corner metrics.

    Analyzes every valid lap against detected corners. Returns a list of
    metric dicts (one per corner per lap), enriched with telemetry data
    (throttle onset, brake intensity, exit accel).
    """
    ca_mod = lazy_import("corner_analysis")
    if ca_mod is None:
        return []
    if not corners or not resampled_laps:
        return []

    results: list[dict[str, Any]] = []
    sorted_keys = sorted(resampled_laps.keys())

    for lap_num in sorted_keys:
        if lap_num in excluded_laps:
            continue
        lap_df = resampled_laps[lap_num]
        if lap_df is None or len(lap_df) < 10:
            continue

        try:
            perfs = ca_mod.analyze_corners(
                corners, lap_df, theoretical_lap, friction_model,
            )
            for perf in perfs:
                d = perf.to_dict() if hasattr(perf, "to_dict") else dict(perf)
                d["lap_number"] = int(lap_num)
                # Convert time_loss_s to time_loss_ms for DB
                tl = d.get("time_loss_s", 0.0)
                d["time_loss_ms"] = round(float(tl or 0) * 1000, 1)
                # Map field names to corner_metrics columns
                d["entry_speed_mps"] = d.get("actual_entry_speed_mps")
                d["apex_speed_mps"] = d.get("actual_apex_speed_mps")
                d["exit_speed_mps"] = d.get("actual_exit_speed_mps")
                d["brake_point_m"] = d.get("braking_point_actual_m")
                d["grip_utilization"] = d.get("grip_utilisation_pct")
                if d.get("grip_utilization"):
                    d["grip_utilization"] = d["grip_utilization"] / 100.0

                # Enrich with raw telemetry metrics
                _enrich_corner_telemetry(d, lap_df)
                results.append(d)
        except Exception as exc:
            logger.debug("Corner analysis for lap %s: %s", lap_num, exc)
            continue

    if results:
        logger.info(
            "Per-lap corner metrics: %d entries across %d laps",
            len(results),
            len(set(m["lap_number"] for m in results)),
        )
    return results


def _enrich_corner_telemetry(d: dict[str, Any], lap_df: pd.DataFrame) -> None:
    """Add throttle_onset_m, exit_accel_mps2, brake_intensity from raw data."""
    try:
        s_start = d.get("s_start", 0)
        s_end = d.get("s_end", 0)

        dist_col = spd_col = accel_col = None
        for c in ("Distance (m)", "distance_m", "dist_m"):
            if c in lap_df.columns:
                dist_col = c
                break
        for c in ("Speed (m/s)", "speed_mps"):
            if c in lap_df.columns:
                spd_col = c
                break
        for c in (
            "accel_long_mps2",
            "Accel_long_G",
            "accel_long_g",
            "Longitudinal acceleration (G) *calc",
            "Acceleration (m/s\u00b2)",
            "accel_mps2",
        ):
            if c in lap_df.columns:
                accel_col = c
                break

        if not (dist_col and spd_col):
            return

        dist_arr = pd.to_numeric(lap_df[dist_col], errors="coerce").values
        spd_arr = pd.to_numeric(lap_df[spd_col], errors="coerce").values

        # Find apex index (min speed in corner)
        mask = (dist_arr >= s_start) & (dist_arr <= s_end)
        corner_idx = np.where(mask)[0]
        if len(corner_idx) <= 2:
            return

        corner_spd = spd_arr[corner_idx]
        apex_local = np.nanargmin(corner_spd)
        apex_idx = corner_idx[apex_local]

        # Throttle onset: first distance after apex where speed increases
        for k in range(apex_idx + 1, min(apex_idx + 50, len(spd_arr) - 2)):
            if spd_arr[k] > spd_arr[apex_idx] + 0.5 and spd_arr[k + 1] > spd_arr[k]:
                d["throttle_onset_m"] = float(dist_arr[k])
                break

        # Exit acceleration (avg accel in exit half)
        exit_start = corner_idx[len(corner_idx) // 2]
        exit_end = corner_idx[-1]
        if exit_end > exit_start + 1:
            exit_spds = spd_arr[exit_start : exit_end + 1]
            exit_dists = dist_arr[exit_start : exit_end + 1]
            dd = np.diff(exit_dists)
            dv = np.diff(exit_spds)
            valid_dd = dd > 0.01
            if np.any(valid_dd):
                accels = dv[valid_dd] * exit_spds[:-1][valid_dd] / dd[valid_dd]
                pos_acc = accels[accels > 0]
                if len(pos_acc) > 0:
                    d["exit_accel_mps2"] = round(float(np.mean(pos_acc)), 3)

        # Brake intensity (peak deceleration before corner)
        if accel_col:
            accel_arr = pd.to_numeric(lap_df[accel_col], errors="coerce").values
            pre_mask = (dist_arr >= s_start - 50) & (dist_arr < s_start)
            pre_idx = np.where(pre_mask)[0]
            if len(pre_idx) > 0:
                pre_accel = accel_arr[pre_idx]
                valid = pre_accel[np.isfinite(pre_accel)]
                if len(valid) > 0:
                    d["brake_intensity"] = round(float(np.min(valid)), 3)
    except Exception:
        pass  # Non-critical enrichment


# ── Step 10e: Endurance analytics ──────────────────────────────────────


def run_endurance(summary: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Step 10e: Endurance analytics.

    Returns a dict with team_coaching data, or ``None`` if unavailable.
    """
    sa_mod = lazy_import("stint_analysis")
    if sa_mod is None or not hasattr(sa_mod, "generate_team_coaching"):
        return None

    stint_data = summary.get("stint_analysis", {})
    stint_metrics = stint_data.get("stint_metrics", []) if isinstance(stint_data, dict) else []
    if not stint_metrics:
        return None

    result: dict[str, Any] = {}
    team_coaching = sa_mod.generate_team_coaching(stint_metrics)
    result["team_coaching"] = team_coaching
    return result


# ── Step 10f: Raceline optimizer ───────────────────────────────────────


def run_raceline_optimizer(
    corners: Optional[list[dict[str, Any]]],
    reference_line: Any,
    curvature_profile: Any,
    track_boundaries: Any,
    friction_circle: Any,
) -> Any:
    """Step 10f: Raceline optimizer.

    Returns the optimization result, or ``None`` if the module is
    unavailable or inputs are insufficient.
    """
    rl_mod = lazy_import("raceline_optimizer")
    if rl_mod is None:
        return None

    _COL_DIST_LOCAL = "Distance (m)"
    ref_dict = {
        "distance_m": (
            reference_line[_COL_DIST_LOCAL].values
            if isinstance(reference_line, pd.DataFrame) and _COL_DIST_LOCAL in reference_line.columns
            else np.array([])
        ),
        "curvature": (
            curvature_profile.get("curvature", np.array([]))
            if isinstance(curvature_profile, dict)
            else np.array([])
        ),
    }
    bounds_dict = (
        track_boundaries.to_dict()
        if hasattr(track_boundaries, "to_dict")
        else track_boundaries
    )
    friction_val = friction_circle if isinstance(friction_circle, (int, float)) else 1.2
    friction = {"mu": friction_val}

    return rl_mod.optimize_corner_lines(
        corners or [], ref_dict, bounds_dict, friction,
    )
