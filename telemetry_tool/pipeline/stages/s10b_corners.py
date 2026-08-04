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
    _failed_laps: list = []
    _attempted = 0
    sorted_keys = sorted(resampled_laps.keys())

    for lap_num in sorted_keys:
        if lap_num in excluded_laps:
            continue
        lap_df = resampled_laps[lap_num]
        if lap_df is None or len(lap_df) < 10:
            continue

        # Counted here, not reconstructed afterward: this is a lap that
        # cleared both legitimate-skip checks above and is genuinely about
        # to be analyzed, whether or not analysis then raises or comes back
        # empty.
        _attempted += 1
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
            _failed_laps.append(lap_num)
            logger.debug("Corner analysis for lap %s: %s", lap_num, exc)
            continue

    if _failed_laps:
        # Counts laps whose corner analysis raised an exception (caught
        # above), not laps that legitimately produced zero metrics via
        # excluded_laps or the too-short-lap_df skip - those are intentional
        # and would make this warning fire on every ordinary session.
        # "attempted" is len(sorted_keys) - the laps this function actually
        # looped over - rather than reconstructed from results + failures,
        # so it can't drift out of sync.
        logger.warning(
            "Per-lap corner metrics: %d/%d laps raised an exception during "
            "corner analysis and were skipped (first few: %s)",
            len(_failed_laps), len(sorted_keys), _failed_laps[:5],
        )

    # Second, independent signal: coverage. This is the actual regression
    # guard for the historical incident - corner spans from lap 1 matching
    # nothing on laps 2..N - which raised NO exception (analyze_corners
    # falls back / returns empty rather than raising on a degenerate mask).
    # The exception warning above could never have caught that.
    #
    # Denominator excludes laps already counted in _failed_laps: those are
    # explained by the warning above, and mixing them in here would let this
    # message's "(no exceptions raised)" claim go false when a run has both
    # some exceptions and separately-low coverage. This keeps the two
    # signals honestly non-overlapping rather than merged.
    _covered_laps = len(set(m["lap_number"] for m in results))
    _no_exception_attempts = _attempted - len(_failed_laps)
    if _no_exception_attempts and _covered_laps < _no_exception_attempts / 2:
        logger.warning(
            "Per-lap corner metrics cover only %d/%d attempted laps that "
            "did not raise (no exceptions raised) - check the distance frame",
            _covered_laps, _no_exception_attempts,
        )

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

    # compute_reference_line() emits "distance_m" (snake_case OUT_DIST),
    # not the RaceChrono "Distance (m)". Accept both for resilience.
    _ref_dist_col = next(
        (
            c
            for c in ("distance_m", "Distance (m)")
            if isinstance(reference_line, pd.DataFrame) and c in reference_line.columns
        ),
        None,
    )
    ref_dict = {
        "distance_m": (
            reference_line[_ref_dist_col].values
            if _ref_dist_col is not None
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


# ── Step 10g: Track Decomposition (v2 corner coaching) ─────────────


def run_track_decomposition_v2(
    best_lap_df: Optional[pd.DataFrame],
    conn: Any = None,
    session_id: str = "",
    fallback_corners: Optional[list[dict[str, Any]]] = None,
) -> Optional[list[dict[str, Any]]]:
    """Step 10g: Decompose track into typed sections.

    Priority order:
    1. User-defined corners from ``user_corners`` table
    2. Autonomous ``decompose_track()``
    3. Fallback: convert step-06b corners into v2 sections
    """
    td_mod = lazy_import("track_decomposition")
    if td_mod is None or best_lap_df is None:
        return None

    # Check for user-defined corners
    if conn is not None and session_id:
        try:
            rows = conn.execute(
                "SELECT * FROM user_corners WHERE session_id = ? ORDER BY corner_index",
                (session_id,)
            ).fetchall()
            if rows:
                logger.info("Using %d user-defined corners for session %s", len(rows), session_id)
                return _user_corners_to_sections(rows, best_lap_df, td_mod)
        except Exception:
            logger.debug("user_corners table check failed, using autonomous", exc_info=True)
            # Day-14: roll back the aborted transaction so subsequent
            # queries on this shared connection (S10h_fetch_user_corners
            # uses the same conn) don't cascade with InFailedSqlTransaction.
            # The actual user_corners table is now created by migration
            # 059, so this guard is belt-and-suspenders for any future
            # query failure on the same connection.
            try:
                conn.rollback()
            except Exception:
                pass

    # Autonomous decomposition
    sections = td_mod.decompose_track(best_lap_df)
    if sections:
        logger.info("Track decomposition: %d sections", len(sections))
        return [s.to_dict() for s in sections]

    # Fallback: convert step-06b corners into v2 sections
    if fallback_corners:
        logger.info("decompose_track returned 0 sections; using %d step-06b corners as fallback", len(fallback_corners))
        return _legacy_corners_to_sections(fallback_corners, td_mod)

    logger.info("Track decomposition: 0 sections (no fallback corners)")
    return []


def _user_corners_to_sections(rows, best_lap_df, td_mod):
    """Convert user-defined corner rows to TrackSection list."""
    from corner_focus import score_exit_importance
    sections = []
    for i, row in enumerate(rows):
        row_dict = dict(row) if hasattr(row, 'keys') else row
        s_entry = row_dict.get("s_entry", 0)
        s_exit = row_dict.get("s_exit", 0)
        s_apex = row_dict.get("s_apex")

        # Compute exit importance based on distance to next corner
        if i + 1 < len(rows):
            next_row = dict(rows[i + 1]) if hasattr(rows[i + 1], 'keys') else rows[i + 1]
            next_entry = next_row.get("s_entry", s_exit)
            straight_length = next_entry - s_exit
        else:
            straight_length = 100.0  # default for last corner

        section = td_mod.TrackSection(
            section_id=i + 1,
            section_type="corner",
            corner_type="user_defined",
            s_start=s_entry,
            s_end=s_exit,
            direction=None,
            geometric_apex=s_apex,
            exit_importance=score_exit_importance(straight_length),
            sub_corners=None,
        )
        sections.append(section.to_dict())
    return sections


def _legacy_corners_to_sections(
    corners: list[dict[str, Any]], td_mod: Any,
) -> list[dict[str, Any]]:
    """Convert step-06b corner dicts into v2 TrackSection dicts."""
    try:
        from corner_focus import score_exit_importance
    except ImportError:
        def score_exit_importance(d: float) -> float:  # type: ignore[misc]
            return min(1.0, d / 200.0)

    sections = []
    for i, c in enumerate(corners):
        s_start = c.get("s_start") or c.get("distance_start") or 0
        s_end = c.get("s_end") or c.get("distance_end") or 0
        s_apex = c.get("s_apex") or c.get("distance_apex")
        direction = c.get("direction")

        # Exit importance from distance to next corner
        if i + 1 < len(corners):
            nc = corners[i + 1]
            ns = nc.get("s_start") or nc.get("distance_start") or s_end
            straight = ns - s_end
        else:
            straight = 100.0

        section = td_mod.TrackSection(
            section_id=c.get("corner_id", i + 1),
            section_type="corner",
            corner_type="detected",
            s_start=s_start,
            s_end=s_end,
            direction=direction,
            geometric_apex=s_apex,
            exit_importance=score_exit_importance(straight),
            sub_corners=None,
        )
        sections.append(section.to_dict())
    return sections


def run_mrp_detection_v2(
    sections: Optional[list[dict[str, Any]]],
    best_lap_df: Optional[pd.DataFrame],
) -> Optional[dict[int, dict[str, Any]]]:
    """Step 10g2: Detect MRP + events for each corner section."""
    mrp_mod = lazy_import("mrp_detector")
    td_mod = lazy_import("track_decomposition")
    if mrp_mod is None or td_mod is None or sections is None or best_lap_df is None:
        return None

    # Reconstruct TrackSection objects
    section_objs = []
    for sd in sections:
        section_objs.append(td_mod.TrackSection(
            section_id=sd["section_id"],
            section_type=sd["section_type"],
            corner_type=sd.get("corner_type"),
            s_start=sd["s_start"],
            s_end=sd["s_end"],
            direction=sd.get("direction"),
            geometric_apex=sd.get("geometric_apex"),
            exit_importance=sd.get("exit_importance", 0.0),
            sub_corners=sd.get("sub_corners"),
        ))

    events = mrp_mod.detect_all_mrp(section_objs, best_lap_df)
    result = {}
    for sid, ev in events.items():
        result[sid] = ev.to_dict() if hasattr(ev, 'to_dict') else ev
    logger.info("MRP detection: %d corners with events", len(result))
    return result


def run_handling_analysis_v2(
    sections: Optional[list[dict[str, Any]]],
    best_lap_df: Optional[pd.DataFrame],
    available_columns: Optional[set[str]] = None,
    best_lap_number: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Step 10g3: Detect understeer/oversteer with 17-detector Bayesian fusion.

    Uses the full handling detection system (telemetry_tool.handling.runner)
    with per-session calibration, 17 detectors, and Bayesian fusion.
    Falls back to the legacy single-detector method if the new system fails.
    """
    if best_lap_df is None or len(best_lap_df) < 50:
        return None

    # Try new multi-detector system first
    try:
        from telemetry_tool.handling.runner import run_handling_analysis

        # Find columns (support both raw and canonical names)
        def _col(candidates, df=best_lap_df):
            for c in candidates:
                if c in df.columns:
                    return df[c].values
            return None

        time_s = _col(["Time (s)", "time_s"])
        dist_m = _col(["Distance (m)", "distance_m"])
        speed = _col(["Speed (m/s)", "speed_mps", "Speed (m/s) *calc"])
        a_lat = _col(["Lateral acceleration (G) *calc", "accel_lat_mps2", "Lateral acceleration (G)"])
        a_lon = _col(["Longitudinal acceleration (G) *calc", "accel_long_mps2", "Longitudinal acceleration (G)"])
        bearing = _col(["Bearing (deg)", "heading_deg"])
        lat_deg = _col(["Latitude (deg)", "lat_deg"])
        lon_deg = _col(["Longitude (deg)", "lon_deg"])
        lap_col = _col(["Lap #", "lap_number"])

        # Convert accel from m/s2 to G if needed
        if a_lat is not None and np.nanmax(np.abs(a_lat)) > 5:
            a_lat = a_lat / 9.80665
        if a_lon is not None and np.nanmax(np.abs(a_lon)) > 5:
            a_lon = a_lon / 9.80665

        required = [time_s, dist_m, speed, a_lat, a_lon, bearing, lat_deg, lon_deg]
        if any(x is None for x in required):
            logger.debug("Missing columns for new handling analysis, falling back to legacy")
            return _legacy_handling_analysis(sections, best_lap_df)

        if best_lap_number is None:
            best_lap_number = 1
        if lap_col is None:
            lap_col = np.ones(len(time_s))

        result = run_handling_analysis(
            time_s=time_s, dist_m=dist_m, speed_mps=speed,
            a_lat_g=a_lat, a_lon_g=a_lon, bearing_deg=bearing,
            lat_deg=lat_deg, lon_deg=lon_deg, lap_col=lap_col,
            best_lap=best_lap_number,
            wheelbase_m=1.0, vehicle_class="kart",
        )

        # Add setup recommendations
        from telemetry_tool.handling.setup_recommender import recommend_setup_changes
        result["setup_recommendations"] = recommend_setup_changes(result.get("events", []))

        logger.info("New handling analysis: %d corners, %d events, tendency=%s",
                     result.get("summary", {}).get("n_corners", 0),
                     result.get("summary", {}).get("n_events", 0),
                     result.get("summary", {}).get("tendency", "?"))
        return result

    except Exception:
        logger.warning("New handling analysis failed, falling back to legacy", exc_info=True)
        return _legacy_handling_analysis(sections, best_lap_df)


def _legacy_handling_analysis(sections, best_lap_df):
    """Fallback to the original single-detector handling analysis."""
    hd_mod = lazy_import("handling_detector")
    if hd_mod is None or sections is None:
        return None

    events_by_corner = {}
    for sd in sections:
        if sd.get("section_type") != "corner":
            continue
        try:
            dist_col = next((c for c in ("Distance (m)", "distance_m") if c in best_lap_df.columns), None)
            speed_col = next((c for c in ("Speed (m/s)", "speed_mps") if c in best_lap_df.columns), None)
            if not dist_col or not speed_col:
                continue
            mask = (best_lap_df[dist_col] >= sd["s_start"]) & (best_lap_df[dist_col] <= sd["s_end"])
            sec = best_lap_df[mask]
            if len(sec) < 5:
                continue
            curvature = np.ones(len(sec)) * 0.01
            headings = np.cumsum(curvature * np.diff(np.concatenate([[0], sec[dist_col].values])))
            accel_long = None
            for c in ("accel_long_mps2", "Longitudinal acceleration (G) *calc"):
                if c in sec.columns:
                    accel_long = sec[c].values
                    break
            evts = hd_mod.detect_handling(
                corner_id=sd["section_id"], distances=sec[dist_col].values,
                speeds=sec[speed_col].values, reference_curvature=curvature,
                actual_headings=headings, accel_long=accel_long,
                geometric_apex_m=sd.get("geometric_apex"),
            )
            if evts:
                events_by_corner[sd["section_id"]] = [e.__dict__ if hasattr(e, "__dict__") else e for e in evts]
        except Exception:
            pass

    return {"events_by_corner": events_by_corner, "legacy": True}


def run_coaching_v2(
    sections: Optional[list[dict[str, Any]]],
    events: Optional[dict],
    handling: Optional[dict],
    best_lap_df: Optional[pd.DataFrame],
    theoretical: Optional[dict] = None,
    friction: Optional[float] = None,
    available_columns: Optional[set[str]] = None,
) -> Optional[list[dict[str, Any]]]:
    """Step 10g4: Generate coaching for all sections."""
    adv_mod = lazy_import("coaching_advanced")
    basic_mod = lazy_import("coaching_basic")
    td_mod = lazy_import("track_decomposition")

    if sections is None or best_lap_df is None:
        return None
    if basic_mod is None:
        return None

    # Reconstruct TrackSection objects
    section_objs = []
    for sd in sections:
        section_objs.append(td_mod.TrackSection(
            section_id=sd["section_id"],
            section_type=sd["section_type"],
            corner_type=sd.get("corner_type"),
            s_start=sd["s_start"],
            s_end=sd["s_end"],
            direction=sd.get("direction"),
            geometric_apex=sd.get("geometric_apex"),
            exit_importance=sd.get("exit_importance", 0.0),
            sub_corners=sd.get("sub_corners"),
        ))

    # Determine tier
    tier = "basic"
    if adv_mod is not None and available_columns:
        tier = adv_mod.get_coaching_tier(available_columns)

    events = events or {}
    handling = handling or {}

    if tier == "advanced" and adv_mod is not None:
        coaching = adv_mod.generate_advanced_coaching(
            section_objs, events, handling, best_lap_df, theoretical, friction,
        )
    else:
        coaching = basic_mod.generate_basic_coaching(
            section_objs, events, handling, best_lap_df, theoretical, friction,
        )

    result = []
    for sc in coaching:
        d = sc.__dict__.copy() if hasattr(sc, '__dict__') else dict(sc)
        # Serialize nested objects
        if hasattr(d.get("section"), "to_dict"):
            d["section"] = d["section"].to_dict()
        if hasattr(d.get("events"), "to_dict"):
            d["events"] = d["events"].to_dict()
        if d.get("handling"):
            d["handling"] = [h.__dict__ if hasattr(h, '__dict__') else h for h in d["handling"]]
        result.append(d)

    logger.info("Coaching v2: %d sections coached (tier=%s)", len(result), tier)
    return result
