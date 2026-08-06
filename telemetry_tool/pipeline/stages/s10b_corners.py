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

import driving_events as de
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
    # (lap_number, metric dict, apex index into that lap's arrays) for every
    # corner-lap the loop below produces. Fed to _assign_throttle_onsets
    # afterwards, because the onset threshold is a per-corner aggregate over
    # every admissible lap and cannot be known inside the loop.
    _onset_pending: list[tuple[int, dict[str, Any], Optional[int]]] = []
    _failed_laps: list = []
    # Laps that completed the loop body WITHOUT raising and contributed at
    # least one metric. Deliberately not derived from `results`: a lap that
    # raises after appending some metrics is a failed lap, so counting it as
    # covered too would put it in both tallies below and could push the
    # coverage numerator above its own denominator. Its partial metrics stay
    # in `results` - discarding them would be a data change, and this is a
    # logging fix.
    _covered_laps: set[int] = set()
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
        _results_before = len(results)
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
                _apex_idx = _enrich_corner_telemetry(d, lap_df)
                _onset_pending.append((int(lap_num), d, _apex_idx))
                results.append(d)
            # Reached only if nothing above raised. A lap that raised part-way
            # is counted as failed, never as covered - see _covered_laps.
            if len(results) > _results_before:
                _covered_laps.add(int(lap_num))
        except Exception as exc:
            _failed_laps.append(lap_num)
            logger.debug("Corner analysis for lap %s: %s", lap_num, exc)
            continue

    if _failed_laps:
        # Counts laps whose corner analysis raised an exception (caught
        # above), not laps that legitimately produced zero metrics via
        # excluded_laps or the too-short-lap_df skip - those are intentional
        # and would make this warning fire on every ordinary session.
        # Denominator is _attempted, the same denominator the coverage
        # warning below builds on: laps that cleared both legitimate-skip
        # checks and genuinely entered analysis. len(sorted_keys) would also
        # count the skipped laps this warning explicitly excludes.
        logger.warning(
            "Per-lap corner metrics: %d/%d laps raised an exception during "
            "corner analysis and were skipped (first few: %s)",
            len(_failed_laps), _attempted, _failed_laps[:5],
        )

    # Second, independent signal: coverage. This is the actual regression
    # guard for the historical incident - corner spans from lap 1 matching
    # nothing on laps 2..N - which raised NO exception (analyze_corners
    # falls back / returns empty rather than raising on a degenerate mask).
    # The exception warning above could never have caught that.
    #
    # Both numerator and denominator exclude laps counted in _failed_laps:
    # those are explained by the warning above, and mixing them in here would
    # let this message's "(no exceptions raised)" claim go false when a run
    # has both some exceptions and separately-low coverage. _covered_laps is
    # accumulated in the loop rather than recomputed from `results` precisely
    # so a lap that raised after appending partial metrics cannot appear on
    # both sides. This keeps the two signals honestly non-overlapping.
    _n_covered = len(_covered_laps)
    _no_exception_attempts = _attempted - len(_failed_laps)
    if _no_exception_attempts and _n_covered < _no_exception_attempts / 2:
        logger.warning(
            "Per-lap corner metrics cover only %d/%d attempted laps that "
            "did not raise (no exceptions raised) - check the distance frame",
            _n_covered, _no_exception_attempts,
        )

    # Throttle onset, session-wide. Deliberately AFTER the per-lap loop and
    # after the failure/coverage logging above: it needs every admissible
    # lap's apex speed at each corner before it can fix that corner's one
    # threshold. Guarded independently so an unanticipated failure costs the
    # onsets only, not the brake points / apex speeds / time losses this
    # function already computed -- _safe_step discards the whole step.
    try:
        _assign_throttle_onsets(_onset_pending, resampled_laps, corners)
    except Exception:
        logger.exception("Throttle-onset assignment failed; onsets omitted")

    if results:
        logger.info(
            "Per-lap corner metrics: %d entries across %d laps",
            len(results),
            len(set(m["lap_number"] for m in results)),
        )
    return results


def _enrich_corner_telemetry(d: dict[str, Any], lap_df: pd.DataFrame) -> Optional[int]:
    """Add exit_accel_mps2 and brake_intensity from raw data.

    Returns this corner-lap's apex index INTO THE FULL LAP ARRAY, or None
    when no apex could be located. ``throttle_onset_m`` is deliberately NOT
    computed here -- it needs a per-corner threshold aggregated over every
    admissible lap, which does not exist until this whole loop has run. See
    ``_assign_throttle_onsets``.

    On a locatable apex the caller must go on to call
    ``_assign_throttle_onsets``; on None this function has already recorded
    the reason (or deliberately recorded nothing, when the derivation never
    ran at all -- see the ``throttle_onset_status`` contract in
    driving_events.py).
    """
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
            # The derivation never ran: leave throttle_onset_status absent
            # rather than inventing a refusal reason for it.
            return None

        dist_arr = pd.to_numeric(lap_df[dist_col], errors="coerce").values
        spd_arr = pd.to_numeric(lap_df[spd_col], errors="coerce").values

        # ⚠ KNOWN REMAINING SEAM — THIS MASK IS IN ABSOLUTE METRES.
        #
        # `s_start`/`s_end` are the DETECTION lap's absolute metres, and
        # `dist_arr` is THIS lap's own 0-based metres. Every resampled lap is
        # rebased to its own span (resampling.py:210-226) and real spans on
        # OK_R4 run 1198.65-1217.97 m, so this window shifts and narrows on
        # longer laps -- the same coordinate-frame defect the 2026-08-05 wave
        # fixed for `throttle_onset_m` and for the corner windows
        # (`s10d2_grip_anchor._corner_mask`, which slices `distance_norm`).
        #
        # IT IS REAL. Measured on the fixture: this mask and the normalised
        # one disagree on sample count for 35 of 72 corner-laps (49%).
        #
        # IT IS NOT URGENT, and that is measured too, not assumed. What this
        # mask actually produces downstream is the APEX -- and apex speed is
        # a MINIMUM over the window, so it only moves if the window's edge
        # crosses the trough. Comparing the two masks' apex speeds over the
        # same 72 corner-laps:
        #
        #   sample-count delta       median 0, max 2
        #   |apex speed delta|       median 0.0000 m/s, MAX 0.0563 m/s
        #   corner-laps over the `over_slowing` emit floor (0.5 m/s):  0
        #   corners whose BEST-apex lap differs between frames:  0 of 8
        #
        # So `over_slowing`'s magnitudes and its ranking are unaffected at
        # this session's geometry: the worst disagreement is ~9x below the
        # floor at which the detector will emit anything at all.
        #
        # WHY IT WAS SCOPED OUT rather than fixed here: `_enrich_corner_
        # telemetry` and `corner_analysis` feed a wide, long-standing set of
        # consumers (brake points, entry/exit speeds, time loss, coaching
        # hints, the legacy grip_utilization), so moving this frame is a
        # behaviour change across all of them and belongs in its own change
        # with its own verification -- not folded into a correctness fix for
        # driving events. The number to watch is the 0.0563 m/s: it scales
        # with lap-span spread, so a session with more variable laps than
        # this one could push it toward the floor.
        #
        # Find apex index (min speed in corner)
        mask = (dist_arr >= s_start) & (dist_arr <= s_end)
        corner_idx = np.where(mask)[0]
        if len(corner_idx) <= 2:
            d["throttle_onset_m"] = None
            d["throttle_onset_status"] = de.ONSET_NO_APEX
            return None

        corner_spd = spd_arr[corner_idx]
        apex_local = np.nanargmin(corner_spd)
        apex_idx = int(corner_idx[apex_local])

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
        return apex_idx
    except Exception:
        # Non-critical enrichment. No throttle_onset_status either: an
        # unanticipated failure here is "the derivation never ran", not a
        # named refusal we can stand behind.
        return None


# ── Throttle onset (second pass over the whole session) ────────────────
#
# `throttle_onset_m` answers "where did this lap get back on the power out of
# this corner". There is no throttle channel in this data, so it is a
# speed-derivative PROXY and its only honest use is comparing one lap against
# another AT THE SAME CORNER. That comparison means nothing unless every lap
# is measured against the SAME speed.
#
# THE DEFECT THIS REPLACES (fixed 2026-08-05). The threshold used to be
# `spd_arr[apex_idx] + 0.5` -- THIS LAP'S OWN apex speed. A faster lap enters
# the corner carrying more speed, so it had to reach a HIGHER ABSOLUTE speed
# before the threshold tripped, and its onset came out LATER. The metric was
# anti-correlated with corner performance: it penalised the driver for going
# fast. The threshold is now per-corner and SESSION-FIXED, so every lap at a
# corner is measured against one identical absolute speed.
#
# ── HOW THE BASIS WAS SELECTED, AND WHY NOT ON corr(corner_time, onset) ──
#
# The obvious score -- "is corr(corner_time, onset) positive on every corner"
# -- is NOT evidence that this metric measures throttle timing, and selecting
# on it picks the wrong basis. corr(corner_time, apex_speed) is about -0.95 on
# this session, so ANY onset that correlates with apex speed inherits a
# corner-time correlation for free. Median r^2(apex -> onset) is 0.17-0.47
# depending on basis: most of what the onset "knows" about corner time is
# just apex speed wearing a different hat.
#
# The selection criterion is therefore TWO-SIDED:
#
#   (1) ADDED INFORMATION -- does the onset explain corner-time variance
#       BEYOND apex speed? Measured as the partial correlation
#       r(corner_time, onset | apex_speed).
#   (2) NOT A RESTATEMENT -- |corr(apex, onset)| must stay bounded away from
#       1.0, or the "metric" is just apex speed rescaled.
#
# ⚠ THE TABLE BELOW WAS MEASURED IN THE BROKEN COORDINATE FRAME (final
# review, Critical 1). At the time it was taken, `_scan_onset` returned a raw
# per-lap ABSOLUTE metre, so both the redundancy column and the partial column
# carry a lap-length term. Re-measured in the canonical frame the SHIPPED
# basis reads med r(apex,onset) = -0.572 (not -0.404) and pooled partial
# = +0.098 (not +0.360). The other five rows have NOT been re-measured, so
# the table's RANKINGS on those two columns are not usable evidence any more
# and no conclusion below rests on them -- see "THE CHOICE" further down,
# whose two grounds are the degeneracy COUNT (a property of where the scan
# lands relative to the apex: frame-independent, unchanged) and the DIRECTION
# of the removed basis's correlation. Re-running the full sweep in the
# canonical frame is open work, recorded not done.
#
# Measured on data/raw/OK_R4.csv (9 laps x 8 corners), same geometric bound,
# only the threshold basis varied. "degen" counts onsets landing within 2
# samples of the apex, i.e. corner-laps where the metric has silently
# collapsed to "where the apex is". The partial column is pooled over all
# corner-laps with each channel z-scored WITHIN its corner:
#
#   basis                med r(apex,onset)  cens  degen  pooled r(ct,on|apex)
#   per-lap apex + 0.5          +0.552         0      0   0.206 [-0.03,+0.42]
#   session median + 0.5        -0.683         0     14   0.401 [+0.19,+0.58]
#   session p75 + 0.5           -0.635         0      5   0.423 [+0.21,+0.60]
#   SESSION BEST + 0.5          -0.404         1      0   0.360 [+0.03,+0.51]
#   1.03 x session best         -0.400         1      0   0.369 [+0.15,+0.56]
#   session best + 2.0          -0.267        21      0   0.529 [+0.29,+0.71]
#   session worst + 0.5         +0.045         0     53   0.142 [-0.10,+0.36]
#
# ADDED INFORMATION DOES NOT DECIDE THIS, IN EITHER DIRECTION. Do not read the
# partial column as a ranking; it is estimator-dependent and the differences
# are not significant. Of four defensible estimators, THREE put the pre-fix
# per-lap basis FIRST:
#
#   median of per-corner partials       defect +0.38 > best +0.26 > median +0.23
#   Fisher-z mean of per-corner partials defect +0.37 > median +0.32 > best +0.24
#   pooled, corner z-scored (the column) p75 > median > best > defect +0.21
#   pooled, corner centred only          defect +0.27 > best +0.26 > median +0.25
#
# Every basis is computed on the SAME corner-laps, so the comparison is paired
# and can be tested directly: the paired per-corner difference (defect - best)
# in Fisher z is +0.140, t(7) = 1.21 -- not significant; a paired
# corner-cluster bootstrap of the pooled-z difference gives -0.154, 95% CI
# [-0.325, +0.250], with the defect ahead in 29% of replicates. An earlier
# revision of this comment claimed the pooled estimate "reverses the ranking"
# and was the properly-powered one. It does not and it is not: a median of
# eight per-corner partials has SE ~ 0.12-0.14, comparable to the pooled
# statistic's naive SE (0.12) and better than its cluster-robust SE (~0.25).
#
# THE CHOICE: session best + 0.5, on the two grounds that are ESTIMATOR-FREE.
#
#   * The pre-fix per-lap basis is disqualified on the DIRECTIONAL property,
#     not on added information: median corr(apex, onset) = +0.552 and
#     corr(corner_time, onset) NEGATIVE on 6 of 8 corners means it reports the
#     faster lap as later. That is a sign, not an estimate.
#   * Among the session-fixed candidates, `best` wins on two COUNTS rather
#     than two estimates:
#       - degeneracy 0/72, against 14/72 (19%) for the session median. A
#         degenerate onset reports the apex position dressed as a throttle
#         onset -- a number that LOOKS measured and is not. `best` sits at or
#         above the top of every corner's apex-speed distribution, so no lap
#         is already above the threshold at its own apex and no onset can
#         collapse onto it.
#       - |corr(apex, onset)| 0.404, against 0.684 for the session median,
#         i.e. materially less redundant with apex speed -- criterion (2).
#         (`1.03 x session best` measures 0.400 and is indistinguishable from
#         `best` here; no superlative is claimed between those two.)
#   * `best`'s one cost is one censored corner-lap, which is strictly better
#     than a degenerate one: a censored lap is reported as `not_measurable`
#     with a named reason (see driving_events.ONSET_*), a degenerate lap is
#     silently indistinguishable from a real measurement.
#   * `best + 2.0` scores highest on added information but censors 21 of 72
#     (29%) and drops two corners entirely -- exactly the censoring bias that
#     makes naive truncation wrong.
#
# HONEST LIMIT, DO NOT OVERSTATE THIS METRIC -- AND IT GOT WORSE, NOT BETTER,
# WHEN THE FRAME WAS FIXED. "How much does the onset add beyond apex speed",
# measured on the same 71 corner-laps, before and after the coordinate-frame
# fix:
#
#   specification                    broken frame      canonical frame
#   corner z-scored, pooled          +0.360 t=3.18     +0.098 t=0.81
#   corner z-scored + lap FE         +0.099 t=0.82     +0.002 t=0.02
#   corner-cluster bootstrap 95% CI  [+0.024,+0.508]   [-0.265,+0.233]
#
# THE MECHANISM, CONFIRMED BY TWO INDEPENDENT ROUTES AGREEING: the broken
# frame's LAP-FE partial (+0.0989) and the canonical frame's POOLED partial
# (+0.0978) are the same number. A lap's length offset is, to first order, a
# lap-level constant, so lap dummies were already absorbing the artifact --
# which means the lap-FE row was ALWAYS the honest one and every other row in
# the old table was measuring coordinate frame.
#
# STATE PLAINLY: in the canonical frame the selected basis's added
# information beyond apex speed is NOT distinguishable from zero in ANY
# specification (t = 0.81 pooled, t = 0.02 under lap FE), and 28.6% of
# corner-cluster bootstrap replicates put it at or below zero. `late_throttle`
# is, on this session, a restatement of `over_slowing` that we cannot show
# carries anything of its own. It is retained on the estimator-free grounds
# only -- zero degeneracy, bounded redundancy, and the cost-ordering of its
# solo events -- and events_repo merges the pair rather than showing two
# competing corrections (see `_dedupe_by_lap_corner`), while the payload marks
# its cost as non-attributable (`driving_events.TIME_COST_ATTRIBUTION`).
#
# ESCALATED, NOT DECIDED HERE: this branch's own rule was "if a longer session
# also shows t<1 under lap FE, DROP the detector, not the threshold". That
# condition is now met on THIS session and in every specification. Dropping a
# shipped detector is a product decision.
#
# 0.5 m/s is carried over unchanged from the shipped code so this fix
# introduces no newly-tuned constant; only its reference point moved, from
# "above THIS lap's apex" to "above THIS CORNER's session-best apex".
_ONSET_THRESHOLD_MARGIN_MPS = 0.5


def _lap_distance_speed(
    lap_df: Optional[pd.DataFrame],
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """(distance, speed) for a whole lap, resolved by the same column
    precedence ``_enrich_corner_telemetry`` uses, or (None, None)."""
    if lap_df is None or not isinstance(lap_df, pd.DataFrame) or lap_df.empty:
        return None, None
    dist_col = next((c for c in ("Distance (m)", "distance_m", "dist_m")
                     if c in lap_df.columns), None)
    spd_col = next((c for c in ("Speed (m/s)", "speed_mps")
                    if c in lap_df.columns), None)
    if dist_col is None or spd_col is None:
        return None, None
    return (pd.to_numeric(lap_df[dist_col], errors="coerce").values,
            pd.to_numeric(lap_df[spd_col], errors="coerce").values)


# ── The coordinate frame the onset scan runs in ────────────────────────
#
# THE DEFECT THIS REPLACES (fixed 2026-08-05, second onset fix). The scan
# used to report ``dist_arr[k]`` -- a raw per-lap ABSOLUTE metre -- and
# `late_throttle` then differenced two of those ACROSS laps. Every resampled
# lap is rebased to ITS OWN span (resampling.py:210-226) and real spans on
# OK_R4 run 1198.65-1217.97 m, so the same piece of tarmac carries a
# different absolute metre on every lap and the difference is lap LENGTH,
# not driving.
#
# MEASURED, on the fixture, with a control that contains no behaviour at all
# -- each corner's window MIDPOINT (a fixed NORMALISED point) expressed in
# each lap's absolute metres:
#
#   cid  r(span,onset)  geom drift (m)  onset spread (m)  drift/spread
#     6      +0.921          11.55            20.06           58%
#     7      +0.809          15.12            19.83           76%
#     8      +0.778          17.61            41.20           43%
#
# The geometric control's own r against span is exactly +1.000 by
# arithmetic. Against a 2.0 m emit floor, 43-76% of the observed spread at
# the back half of the lap was guaranteed frame. The decision to emit
# flipped on 4 of 71 corner-laps, systematically: a LONGER lap reports a
# LATER onset, so it was flagged more often and harder.
#
# THE FIX: the scan runs, and the metric is stored, in ``distance_norm`` --
# the lap-length-invariant frame ``s10d2_grip_anchor._corner_mask`` already
# moved corner slicing to, for exactly this reason. ``throttle_onset_m`` is
# still published in metres, but converted ONCE, from the normalised value,
# against ONE session-wide reference length: the detection lap's span. That
# is the same lap `_corner_mask` normalises the corners' own ``s_start`` /
# ``s_end`` against, so an onset in metres stays directly comparable to the
# corner geometry it belongs to -- which it was NOT before.
#
# "Metres past the apex" was considered and rejected on measurement, not
# taste: the apex is located in the absolute frame too, so corner 8's spread
# under that definition is 41.47 m against 41.20 m absolute -- it removes
# nothing.


def _lap_norm_speed(
    lap_df: Optional[pd.DataFrame],
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """(distance_norm, speed) for a whole lap, or (None, None).

    ``distance_norm`` is preferred straight off the resampled frame because
    that is the identical array ``s10d2_grip_anchor._corner_mask`` slices
    on: the onset scan and the corner window must not disagree about where
    a corner is. It is derived from the lap's own distance span only as a
    fallback, for a frame that never went through the resampler -- the same
    arithmetic ``resampling.py:226`` applies, not a different definition.
    """
    if lap_df is None or not isinstance(lap_df, pd.DataFrame) or lap_df.empty:
        return None, None
    spd_col = next((c for c in ("Speed (m/s)", "speed_mps")
                    if c in lap_df.columns), None)
    if spd_col is None:
        return None, None
    spd = pd.to_numeric(lap_df[spd_col], errors="coerce").values

    if "distance_norm" in lap_df.columns:
        dn = pd.to_numeric(lap_df["distance_norm"], errors="coerce").values
        return dn, spd

    dist_col = next((c for c in ("Distance (m)", "distance_m", "dist_m")
                     if c in lap_df.columns), None)
    if dist_col is None:
        return None, None
    d = pd.to_numeric(lap_df[dist_col], errors="coerce").values
    d_min, d_max = float(np.nanmin(d)), float(np.nanmax(d))
    span = d_max - d_min
    if not np.isfinite(span) or span <= 0:
        return None, None
    return (d - d_min) / span, spd


def _detection_frame(
    resampled_laps: Optional[dict[Any, pd.DataFrame]],
) -> Optional[tuple[float, float]]:
    """``(d_min, span)`` of the lap the corners were detected on, or None.

    This is THE reference length: the one number every normalised onset is
    converted to metres against, for the whole session. Derived exactly the
    way ``s10d2_grip_anchor._corner_mask`` derives it (first sorted lap key,
    nanmin/nanmax of its distance column) so the metre <-> norm map used
    here is the inverse of the one used to place the corners.
    """
    if not resampled_laps:
        return None
    detection_lap = resampled_laps.get(sorted(resampled_laps.keys())[0])
    if not isinstance(detection_lap, pd.DataFrame) or detection_lap.empty:
        return None
    col = next((c for c in ("Distance (m)", "distance_m", "dist_m")
                if c in detection_lap.columns), None)
    if col is None:
        return None
    d = pd.to_numeric(detection_lap[col], errors="coerce").values
    d_min, d_max = float(np.nanmin(d)), float(np.nanmax(d))
    span = d_max - d_min
    if not np.isfinite(d_min) or not np.isfinite(span) or span <= 0:
        return None
    return d_min, span


def _onset_search_limit_m(
    corner: dict[str, Any], corners: list[dict[str, Any]],
) -> Optional[float]:
    """How far past a corner an onset scan may look, in the same absolute-
    metre frame as ``s_start``/``s_end``. None for degenerate geometry.

    Replaces a bare ``apex_idx + 50`` samples, which was a sample COUNT
    standing in for a distance and was wrong in BOTH directions on the real
    fixture. At this session's 1.20 m/sample it reached past ``s_end`` by
    35-53 m on corners 1-5 and 8, but stopped 9.3 m SHORT of ``s_end`` on
    corner 7 -- the corner with the longest exit, i.e. the one where a late
    onset matters most. It also silently rescales with any change to the
    resampler's ``n_points``, which has nothing to do with track geometry.

    ``s_end + one corner length`` is the exit span proper: a corner's exit is
    on the same scale as the corner itself. The next corner's ``s_start`` is
    the hard stop -- an onset located inside the NEXT corner is not this
    corner's exit at all. The min of the two keeps both guarantees.

    THIS IS NOT THE FRAME THE SCAN RUNS IN. ``s_start``/``s_end`` live in the
    DETECTION lap's absolute metres, and this bound used to be applied
    directly to each other lap's own 0-based metres -- systematically
    shortening the search window on longer laps, the same coordinate-frame
    error the reported onset itself carried. ``_onset_search_limit_norm``
    below is what the scan actually uses; this function stays in metres
    because that is the frame its inputs are in.
    """
    try:
        s_start = float(corner.get("s_start"))
        s_end = float(corner.get("s_end"))
    except (TypeError, ValueError):
        return None
    length = s_end - s_start
    if not np.isfinite(length) or length <= 0:
        return None

    limit = s_end + length
    for other in corners or []:
        if not isinstance(other, dict):
            continue
        try:
            other_start = float(other.get("s_start"))
        except (TypeError, ValueError):
            continue
        if np.isfinite(other_start) and other_start > s_end:
            limit = min(limit, other_start)
    return limit


def _onset_search_limit_norm(
    corner: dict[str, Any],
    corners: list[dict[str, Any]],
    frame: Optional[tuple[float, float]],
) -> Optional[float]:
    """``_onset_search_limit_m`` expressed in ``distance_norm``.

    ``frame`` is ``_detection_frame``'s ``(d_min, span)``; the map applied
    here is character-for-character the one ``s10d2_grip_anchor._corner_mask``
    applies to ``s_start``/``s_end``, so a corner's window and its onset
    bound are placed by the same arithmetic. Without ``frame`` there is no
    map and the answer is None -- a refusal, never an unconverted metre
    quietly compared against a 0-1 array.
    """
    limit_m = _onset_search_limit_m(corner, corners)
    if limit_m is None or frame is None:
        return None
    d_min, span = frame
    return (limit_m - d_min) / span


def _scan_onset(
    dist_norm_arr: np.ndarray,
    spd_arr: np.ndarray,
    apex_idx: int,
    threshold_mps: float,
    limit_norm: float,
) -> Optional[float]:
    """First sample after the apex, and no further than ``limit_norm``, that
    is above ``threshold_mps`` AND still climbing. Returns the sample's
    NORMALISED position, or None when there is no such sample -- an honest
    "did not cross", never a fabricated distance.

    Normalised, not absolute metres: see the frame block comment above
    ``_lap_norm_speed``. Both the bound and the returned value are in the
    lap-length-invariant frame, so the same tarmac gets the same number on
    every lap and a cross-lap difference is driving rather than lap length.

    ``threshold_mps`` is a SESSION-FIXED, per-corner speed: the identical
    number for every lap at this corner. That is the earlier fix, kept.
    """
    for k in range(apex_idx + 1, len(spd_arr) - 1):
        d_k = dist_norm_arr[k]
        # A non-finite position means the frame is lost, so neither the
        # bound nor the reported onset would mean anything past here.
        if not np.isfinite(d_k) or d_k > limit_norm:
            return None
        if spd_arr[k] > threshold_mps and spd_arr[k + 1] > spd_arr[k]:
            return float(d_k)
    return None


def _assign_throttle_onsets(
    pending: list[tuple[int, dict[str, Any], Optional[int]]],
    resampled_laps: dict[int, pd.DataFrame],
    corners: list[dict[str, Any]],
) -> None:
    """Fill ``throttle_onset_norm`` + ``throttle_onset_m`` +
    ``throttle_onset_status`` on every metric dict, in place, using a
    per-corner SESSION-FIXED speed threshold.

    Runs as a second pass because the threshold is an aggregate over every
    admissible lap at a corner, and no per-corner-lap function can see that.
    ``pending`` carries exactly the corner-laps the first pass produced, so
    the threshold's basis is exactly the admissible set (excluded and
    too-short laps never enter it).

    ``throttle_onset_norm`` is the MEASUREMENT: a 0-1 position in the
    lap-length-invariant frame, directly comparable across laps.
    ``throttle_onset_m`` is that same number converted to metres ONCE,
    against ONE session-wide reference length (``_detection_frame``'s span),
    for the consumers that speak metres. Both are written so a reader can
    audit the conversion instead of taking it on trust. See the frame block
    comment above ``_lap_norm_speed``.

    The caller wraps this in its own try/except rather than this function
    swallowing failures itself: the whole stage runs under ``_safe_step``,
    where a raise discards every corner metric for the session, so an
    unanticipated failure here must cost the onsets and nothing else.
    """
    by_lap: dict[Any, list[tuple[dict[str, Any], int]]] = {}
    for lap_num, metric, apex_idx in pending:
        if apex_idx is None:
            continue    # first pass already recorded why (or deliberately not)
        by_lap.setdefault(lap_num, []).append((metric, apex_idx))
    if not by_lap:
        return

    frame = _detection_frame(resampled_laps)
    arrays = {lap_num: _lap_norm_speed((resampled_laps or {}).get(lap_num))
              for lap_num in by_lap}

    # Pass A: the per-corner apex-speed distribution, read at the SAME index
    # the scan starts from, so the threshold and the scan share one notion of
    # "the apex". The MAXIMUM over that distribution becomes the threshold --
    # see the block comment above for why the max and not the median.
    apex_speeds: dict[Any, list[float]] = {}
    for lap_num, entries in by_lap.items():
        _, spd_arr = arrays[lap_num]
        if spd_arr is None:
            continue
        for metric, apex_idx in entries:
            if apex_idx >= len(spd_arr):
                continue
            v = float(spd_arr[apex_idx])
            if np.isfinite(v):
                apex_speeds.setdefault(metric.get("corner_id"), []).append(v)

    thresholds = {
        cid: float(np.max(vals)) + _ONSET_THRESHOLD_MARGIN_MPS
        for cid, vals in apex_speeds.items() if vals
    }
    limits = {
        c.get("corner_id"): _onset_search_limit_norm(c, corners, frame)
        for c in (corners or []) if isinstance(c, dict)
    }

    # Pass B: the scan itself, every lap at a corner against that corner's
    # one threshold, in the one shared normalised frame.
    n_refused = 0
    for lap_num, entries in by_lap.items():
        dn_arr, spd_arr = arrays[lap_num]
        for metric, apex_idx in entries:
            cid = metric.get("corner_id")
            metric["throttle_onset_norm"] = None
            metric["throttle_onset_m"] = None
            if frame is None:
                # No reference length means no metre value can be produced
                # without inventing one. Named rather than folded into
                # ONSET_NO_MEASUREMENT: this is a session-wide frame
                # failure, not a per-corner-lap one, and an operator seeing
                # it should look at the resampled laps, not at the driving.
                metric["throttle_onset_status"] = de.ONSET_NO_REFERENCE_FRAME
            elif dn_arr is None or spd_arr is None or apex_idx >= len(spd_arr):
                metric["throttle_onset_status"] = de.ONSET_NO_MEASUREMENT
            elif cid not in thresholds:
                metric["throttle_onset_status"] = de.ONSET_NO_SESSION_THRESHOLD
            elif limits.get(cid) is None:
                metric["throttle_onset_status"] = de.ONSET_NO_SEARCH_WINDOW
            else:
                onset_norm = _scan_onset(
                    dn_arr, spd_arr, apex_idx, thresholds[cid], limits[cid],
                )
                if onset_norm is None:
                    metric["throttle_onset_status"] = de.ONSET_NO_SPEED_CROSSING
                else:
                    d_min, span = frame
                    metric["throttle_onset_norm"] = onset_norm
                    # The single conversion. Inverse of the exact map
                    # `_onset_search_limit_norm` and `_corner_mask` apply to
                    # the corner geometry, so an onset in metres remains
                    # comparable to that corner's own s_start / s_end.
                    metric["throttle_onset_m"] = d_min + onset_norm * span
                    metric["throttle_onset_status"] = de.ONSET_MEASURED
            if metric["throttle_onset_status"] != de.ONSET_MEASURED:
                n_refused += 1

    if n_refused:
        logger.info(
            "Throttle onset: %d of %d corner-laps could not be measured "
            "(reported as not_measurable, not dropped)",
            n_refused, sum(len(v) for v in by_lap.values()),
        )


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
    mrp_mod = lazy_import("mrp_detector")
    hd_mod = lazy_import("handling_detector")

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

    # Reconstruct CornerEvents / HandlingEvent objects, exactly as the
    # TrackSections above are reconstructed.
    #
    # THE DEFECT THIS REPLACES (live in production until 2026-08-06). The two
    # producing stages serialise their output so it can sit in the JSON
    # summary -- run_mrp_detection_v2 with `.to_dict()`, run_handling_analysis_v2
    # with `e.__dict__` -- and the orchestrator feeds those dicts straight in
    # here (orchestrator.py:1304-1306). Both coaching modules do ATTRIBUTE
    # access on them (`corner_events.mrp_m`, `ev.cause`), so every section
    # raised AttributeError inside the per-section `except Exception` in
    # generate_basic_coaching, which substituted _empty_coaching. Every corner
    # of every session with MRP events reported "No data available for this
    # section." with all four time losses 0.0, while the stage logged success.
    #
    # Deliberately NOT wrapped in a try/except: a dict that no longer fits the
    # dataclass is a real contract break, and _safe_step records a raised
    # error as a failed step. Swallowing it here is what hid this for months.
    events = {
        sid: (mrp_mod.CornerEvents(**ev) if isinstance(ev, dict) else ev)
        for sid, ev in events.items()
    } if mrp_mod is not None else events
    # `handling` is NOT reliably ``{section_id: [event]}``. run_handling_analysis_v2
    # returns a STRING-keyed dict -- ``{"events": [...], "summary": {...},
    # "setup_recommendations": [...]}`` on the new path and
    # ``{"events_by_corner": {...}, "legacy": True}`` on the legacy fallback --
    # even though generate_basic_coaching's signature says
    # ``dict[int, list[HandlingEvent]]``. An earlier version of this fix
    # rebuilt every value unconditionally and died on ``for h in (True or [])``
    # from the ``"legacy": True`` entry, failing stage 10g4 on all five golden
    # datasets. Only entries that actually match the declared contract are
    # rebuilt; anything else is passed through exactly as before.
    #
    # That pass-through preserves a SEPARATE latent bug rather than guessing at
    # a fix: because the keys are strings, coaching's ``handling.get(section_id)``
    # never matches, so handling events have never reached v2 coaching at all.
    # Fixing that means settling which shape is canonical -- out of scope here.
    if hd_mod is not None:
        handling = {
            sid: (
                [(hd_mod.HandlingEvent(**h) if isinstance(h, dict) else h) for h in evs]
                if isinstance(sid, int) and isinstance(evs, list)
                else evs
            )
            for sid, evs in handling.items()
        }

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
