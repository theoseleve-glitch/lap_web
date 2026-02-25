"""
debrief_engine.py
-----------------
Post-session debrief: summary, mistake classification, and drill generation.

Public API
~~~~~~~~~~
``summarize_session(context, lap_metrics_df, phases_df)``
    Pure-function session summary returning a structured dict.

``top_time_loss_segments(deltas_df, k, stability_filter)``
    Select the top-k worst segments by time loss.

``classify_mistakes(lap_segment_metrics_df)``
    Per-segment dominant cause, confidence, and coaching hint.

``generate_next_session_drills(mistakes_df, context, max_drills)``
    Actionable 1-sentence drills for the next session.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no side effects, no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs ’ identical outputs.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants (aligned with feature_builder / deltas / features)

# -- -

_C_LAP:         Final[str] = "lap_number"
_C_LAP_TIME:    Final[str] = "lap_time_s"
_C_SPEED_MEAN:  Final[str] = "speed_mean_mps"
_C_BRAKING_MAX: Final[str] = "braking_max_mps2"
_C_JERK_RMS:    Final[str] = "jerk_rms_mps3"
_C_LAT_ACCEL:   Final[str] = "lat_accel_rms_mps2"
_C_LINE_LEN:    Final[str] = "line_length_m"

_C_SEGMENT:     Final[str] = "segment"
_C_LOSS_MS:     Final[str] = "time_loss_ms"
_C_CAUSE:       Final[str] = "likely_cause"

# cause_details sub-columns

_C_ENTRY_SPD:   Final[str] = "entry_speed_diff_mps"
_C_MIN_SPD:     Final[str] = "min_speed_diff_mps"
_C_EXIT_ACCEL:  Final[str] = "exit_accel_diff_mps2"
_C_YAW_VAR:     Final[str] = "yaw_var_ratio"

# Cause strings (must match deltas.py)

_CAUSE_ENTRY:   Final[str] = "entry_loss"
_CAUSE_MID:     Final[str] = "mid_corner_loss"
_CAUSE_EXIT:    Final[str] = "exit_loss"
_CAUSE_INSTAB:  Final[str] = "instability"
_CAUSE_LINE:    Final[str] = "line_inefficiency"
_CAUSE_ON_PACE: Final[str] = "on_pace"
_CAUSE_UNDET:   Final[str] = "undetermined"


# ============================================================================

# 1. summarize_session

# ============================================================================


def summarize_session(
    context: Any,
    lap_metrics_df: pd.DataFrame,
    phases_df: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """
    Produce a structured session summary.

    Parameters
    ----------
    context:
        A ``SessionContext`` instance (or anything with ``.session_type``,
        ``.baseline_track_state``, ``.session_id`` attributes).
    lap_metrics_df:
        One row per lap with ``lap_number``, ``lap_time_s``, etc.
    phases_df:
        Output of ``condition_tracking.build_condition_phases`` (optional).

    Returns
    -------
    dict
        Keys: ``summary_sentence``, ``phases_summary``, ``best_lap``,
        ``median_lap_time_s``, ``pace_trend``, ``n_laps``.
    """
    result: dict[str, Any] = {
        "summary_sentence": "",
        "phases_summary": [],
        "best_lap": None,
        "median_lap_time_s": None,
        "pace_trend": "insufficient_data",
        "n_laps": 0,
    }

    if lap_metrics_df.empty or _C_LAP_TIME not in lap_metrics_df.columns:
        result["summary_sentence"] = "Insufficient data for session summary."
        return result

    times = pd.to_numeric(lap_metrics_df[_C_LAP_TIME], errors="coerce").dropna()
    result["n_laps"] = len(times)

    if len(times) == 0:
        result["summary_sentence"] = "No valid lap times recorded."
        return result

    best_time = float(times.min())
    median_time = float(times.median())
    result["median_lap_time_s"] = round(median_time, 3)

    # Identify best lap

    if _C_LAP in lap_metrics_df.columns:
        best_idx = times.idxmin()
        best_lap = int(lap_metrics_df.loc[best_idx, _C_LAP])
    else:
        best_lap = int(times.idxmin()) + 1
    result["best_lap"] = best_lap

    # Pace trend: compare first-third vs last-third

    n = len(times)
    third = max(1, n // 3)
    t_arr = times.values
    early_med = float(np.median(t_arr[:third]))
    late_med = float(np.median(t_arr[-third:]))
    delta = late_med - early_med
    if abs(delta) < 0.15:
        result["pace_trend"] = "stable"
    elif delta < 0:
        result["pace_trend"] = "improving"
    else:
        result["pace_trend"] = "degrading"

    # Phases summary

    if phases_df is not None and not phases_df.empty:
        for _, row in phases_df.iterrows():
            phase_info: dict[str, Any] = {
                "phase_id": int(row.get("phase_id", 0)),
                "laps": f"{row.get('lap_start', '?')}“{row.get('lap_end', '?')}",
                "n_laps": int(row.get("n_laps", 0)),
            }
            if "phase_track_state" in phases_df.columns:
                phase_info["state"] = str(row["phase_track_state"])
            result["phases_summary"].append(phase_info)

    # Build summary sentence

    stype = getattr(context, "session_type", None)
    stype_str = stype.value if hasattr(stype, "value") else str(stype)
    tstate = getattr(context, "baseline_track_state", None)
    tstate_str = tstate.value if hasattr(tstate, "value") else str(tstate)

    result["summary_sentence"] = (
        f"{stype_str.replace('_', ' ').title()} session on {tstate_str} track: "
        f"{result['n_laps']} laps, best {best_time:.2f}s (lap {best_lap}), "
        f"median {median_time:.2f}s, pace {result['pace_trend']}."
    )

    # Add coaching context to summary
    stype_key = stype_str.lower().replace("-", "_").replace(" ", "_") if stype_str else "practice"
    coaching_ctx = _COACHING_CONTEXT.get(stype_key, {})
    if coaching_ctx:
        result["coaching_focus"] = coaching_ctx.get("focus", "")
        result["coaching_tone"] = coaching_ctx.get("tone", "")

    logger.info("Session summary: %s", result["summary_sentence"])
    return result


# ============================================================================

# 2. top_time_loss_segments

# ============================================================================


def top_time_loss_segments(
    deltas_df: pd.DataFrame,
    *,
    k: int = 5,
    stability_filter: bool = True,
) -> pd.DataFrame:
    """
    Select the top-*k* worst segments by mean time loss.

    Parameters
    ----------
    deltas_df:
        Flattened delta/segment DataFrame with ``segment``, ``time_loss_ms``,
        ``likely_cause``, and optionally ``lap_number``.
    k:
        Number of top segments to return.
    stability_filter:
        If True, prefer segments whose losses are consistent across laps
        (low CoV).

    Returns
    -------
    pd.DataFrame
        Top-k rows with columns: ``segment``, ``mean_loss_ms``,
        ``std_loss_ms``, ``n_observations``, ``likely_cause``.
    """
    if deltas_df.empty or _C_SEGMENT not in deltas_df.columns:
        return pd.DataFrame(columns=[
            "segment", "mean_loss_ms", "std_loss_ms", "n_observations", "likely_cause",
        ])

    # Drop on_pace / undetermined segments

    df = deltas_df.copy()
    if _C_CAUSE in df.columns:
        df = df[~df[_C_CAUSE].isin([_CAUSE_ON_PACE, _CAUSE_UNDET])]

    if df.empty or _C_LOSS_MS not in df.columns:
        return pd.DataFrame(columns=[
            "segment", "mean_loss_ms", "std_loss_ms", "n_observations", "likely_cause",
        ])

    df[_C_LOSS_MS] = pd.to_numeric(df[_C_LOSS_MS], errors="coerce")

    # Group by segment

    grouped = df.groupby(_C_SEGMENT, sort=False)
    agg = grouped.agg(
        mean_loss_ms=(_C_LOSS_MS, "mean"),
        std_loss_ms=(_C_LOSS_MS, "std"),
        n_observations=(_C_LOSS_MS, "count"),
    ).reset_index()

    # Most common cause per segment

    if _C_CAUSE in df.columns:
        cause_mode = grouped[_C_CAUSE].agg(
            lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else _CAUSE_UNDET
        ).reset_index()
        cause_mode.columns = [_C_SEGMENT, "likely_cause"]
        agg = agg.merge(cause_mode, on=_C_SEGMENT, how="left")
    else:
        agg["likely_cause"] = _CAUSE_UNDET

    agg["std_loss_ms"] = agg["std_loss_ms"].fillna(0.0)

    # Stability filter: penalise high-variance segments

    if stability_filter and len(agg) > 0:
        cov = agg["std_loss_ms"] / agg["mean_loss_ms"].clip(lower=1.0)
        # Score: mean_loss Ã— (1 - 0.5 Ã— normalised_cov)

        cov_max = float(cov.max())
        cov_norm = cov / max(cov_max, 1e-9) if cov_max > 0 else cov * 0
        agg["_score"] = agg["mean_loss_ms"] * (1.0 - 0.5 * cov_norm)
        agg = agg.sort_values("_score", ascending=False).drop(columns=["_score"])
    else:
        agg = agg.sort_values("mean_loss_ms", ascending=False)

    result = agg.head(k).reset_index(drop=True)

    # Round for readability

    for col in ("mean_loss_ms", "std_loss_ms"):
        if col in result.columns:
            result[col] = result[col].round(1)

    logger.info("Top %d time-loss segments identified.", len(result))
    return result


# ============================================================================

# 3. classify_mistakes

# ============================================================================


_COACHING_HINTS: Final[dict[str, str]] = {
    _CAUSE_ENTRY:  "Focus on brake release point and trail-braking into the corner.",
    _CAUSE_MID:    "Carry more minimum speed by using a wider apex or smoother steering.",
    _CAUSE_EXIT:   "Get on the throttle earlier; straighten the wheel before full power.",
    _CAUSE_INSTAB: "Smooth inputs — avoid sudden steering or throttle corrections.",
    _CAUSE_LINE:   "Tighten the racing line; you are using more track than necessary.",
    _CAUSE_ON_PACE: "This segment is on pace — maintain current technique.",
    _CAUSE_UNDET:   "Insufficient data to classify — review onboard footage.",
}

# Session-type coaching contexts: adjusts focus/tone of coaching advice
_COACHING_CONTEXT: Final[dict[str, dict[str, str]]] = {
    "race": {
        "focus": "tire management, race craft, and consistent race pace",
        "tone": "race strategy",
        "priority_drill": "Practice maintaining race pace under pressure — run 10 laps at 98% effort.",
    },
    "sprint_race": {
        "focus": "fast adaptation and aggressive-but-clean racing",
        "tone": "sprint intensity",
        "priority_drill": "Work on maximizing pace from lap 1 — practice jump-start pace bursts.",
    },
    "feature_race": {
        "focus": "tire management, race craft, and consistent race pace",
        "tone": "race strategy",
        "priority_drill": "Practice maintaining race pace under pressure — run 10 laps at 98% effort.",
    },
    "qualifying": {
        "focus": "peak single-lap performance and finding the ultimate limit",
        "tone": "qualifying attack",
        "priority_drill": "Practice single-lap mode: one warm-up lap, then one all-out push lap. Repeat 5 times.",
    },
    "practice": {
        "focus": "technique experimentation and progressive improvement",
        "tone": "learning mindset",
        "priority_drill": "Isolate one weakness per 5-lap run and focus exclusively on that skill.",
    },
    "test": {
        "focus": "data collection, setup evaluation, and baseline establishment",
        "tone": "analytical",
        "priority_drill": "Run 3-lap blocks with specific setup changes — document each change.",
    },
    "warmup": {
        "focus": "progressive tire/brake warm-up and track familiarization",
        "tone": "preparation",
        "priority_drill": "Build speed gradually: 80% → 90% → 95% over first 3 laps.",
    },
    "endurance": {
        "focus": "consistent pace preservation, fuel/tire economy, and driver comfort",
        "tone": "endurance management",
        "priority_drill": "Practice stint simulation: 20 laps maintaining target pace within 0.3s.",
    },
    "endurance_stint": {
        "focus": "consistent pace preservation and tire economy",
        "tone": "stint management",
        "priority_drill": "Practice stint simulation: 20 laps maintaining target pace within 0.3s.",
    },
    "endurance_race": {
        "focus": "consistent pace preservation, fuel/tire economy, and driver comfort",
        "tone": "endurance management",
        "priority_drill": "Practice stint simulation: 20 laps maintaining target pace within 0.3s.",
    },
    "heat": {
        "focus": "immediate performance in short format",
        "tone": "heat intensity",
        "priority_drill": "Practice cold-start pace: go fast from lap 1 without warm-up.",
    },
    "final": {
        "focus": "peak performance under pressure with clean execution",
        "tone": "final intensity",
        "priority_drill": "Simulate race-start pressure: 5 laps maximum attack, zero mistakes.",
    },
    "sprint": {
        "focus": "aggressive pace in short format",
        "tone": "sprint intensity",
        "priority_drill": "Work on maximizing pace from lap 1 — practice fast adaptation.",
    },
}


def classify_mistakes(
    lap_segment_metrics_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    For each segment, determine dominant cause, confidence, and coaching hint.

    Parameters
    ----------
    lap_segment_metrics_df:
        Flattened segment metrics with ``segment``, ``time_loss_ms``,
        ``likely_cause``, and optionally ``entry_speed_diff_mps``,
        ``min_speed_diff_mps``, ``exit_accel_diff_mps2``, ``yaw_var_ratio``.

    Returns
    -------
    pd.DataFrame
        Columns: ``segment``, ``dominant_cause``, ``confidence``,
        ``supporting_metrics``, ``coaching_hint``.
    """
    out_cols = ["segment", "dominant_cause", "confidence", "supporting_metrics", "coaching_hint"]
    if lap_segment_metrics_df.empty or _C_SEGMENT not in lap_segment_metrics_df.columns:
        return pd.DataFrame(columns=out_cols)

    df = lap_segment_metrics_df.copy()
    rows: list[dict[str, Any]] = []

    for seg_id, grp in df.groupby(_C_SEGMENT, sort=True):
        # Most common cause

        if _C_CAUSE in grp.columns:
            cause_counts = grp[_C_CAUSE].value_counts()
            # Exclude on_pace and undetermined for dominance

            real_causes = cause_counts.drop(
                labels=[_CAUSE_ON_PACE, _CAUSE_UNDET], errors="ignore"
            )
            if len(real_causes) > 0:
                dominant = str(real_causes.index[0])
                confidence = float(real_causes.iloc[0]) / len(grp)
            else:
                dominant = _CAUSE_ON_PACE
                confidence = 1.0
        else:
            dominant = _CAUSE_UNDET
            confidence = 0.0

        # Collect supporting metrics (means)

        support: dict[str, float] = {}
        for col in (_C_ENTRY_SPD, _C_MIN_SPD, _C_EXIT_ACCEL, _C_YAW_VAR, _C_LOSS_MS):
            if col in grp.columns:
                val = pd.to_numeric(grp[col], errors="coerce").mean()
                if not math.isnan(val):
                    support[col] = round(val, 2)

        rows.append({
            "segment":            seg_id,
            "dominant_cause":     dominant,
            "confidence":         round(confidence, 3),
            "supporting_metrics": json.dumps(support),
            "coaching_hint":      _COACHING_HINTS.get(dominant, ""),
        })

    result = pd.DataFrame(rows, columns=out_cols)
    logger.info("Classified mistakes for %d segments.", len(result))
    return result


# ============================================================================

# 4. generate_next_session_drills

# ============================================================================


def generate_next_session_drills(
    mistakes_df: pd.DataFrame,
    context: Any,
    *,
    max_drills: int = 6,
) -> list[str]:
    """
    Generate actionable 1-sentence drills for the next session.

    Parameters
    ----------
    mistakes_df:
        Output of :func:`classify_mistakes`.
    context:
        ``SessionContext`` instance.
    max_drills:
        Maximum number of drills (default 6).

    Returns
    -------
    list[str]
        Each element is a single-sentence drill.
    """
    drills: list[str] = []

    # Import here to avoid circular import

    from session_context import TrackState

    tstate = getattr(context, "baseline_track_state", TrackState.DRY)
    is_wet = tstate in (TrackState.WET, TrackState.FULL_WET, TrackState.DAMP, TrackState.DRYING)

    # Sort mistakes by worst loss (from supporting_metrics)

    if mistakes_df.empty or "dominant_cause" not in mistakes_df.columns:
        if is_wet:
            drills.append("In wet conditions, focus on smooth brake inputs and gradual throttle application.")
        drills.append("Work on overall consistency: aim for lap times within 1% of your best.")
        return drills[:max_drills]

    df = mistakes_df.copy()

    # Extract mean_loss for sorting

    def _extract_loss(row: pd.Series) -> float:
        try:
            sm = json.loads(row.get("supporting_metrics", "{}"))
            return sm.get(_C_LOSS_MS, 0.0)
        except (json.JSONDecodeError, TypeError):
            return 0.0

    df["_loss"] = df.apply(_extract_loss, axis=1)
    df = df[df["dominant_cause"] != _CAUSE_ON_PACE]
    df = df.sort_values("_loss", ascending=False)

    # Top 3 segment-specific drills

    seen_causes: set[str] = set()
    for _, row in df.head(5).iterrows():
        cause = row["dominant_cause"]
        seg = row["segment"]
        if cause in seen_causes and len(drills) >= 2:
            continue
        seen_causes.add(cause)

        hint = row.get("coaching_hint", "")
        if hint:
            drill = f"Segment {seg}: {hint}"
        else:
            drill = f"Segment {seg}: review this section for {cause.replace('_', ' ')}."
        drills.append(drill)

        if len(drills) >= 3:
            break

    # Wet-specific drill

    if is_wet:
        drills.append(
            "Wet/drying conditions: delay braking points by 5—10 m and "
            "use progressive throttle application out of corners."
        )

    # Session-type-specific coaching context
    stype_str = getattr(context, "session_type", None)
    if hasattr(stype_str, "value"):
        stype_str = stype_str.value
    stype_key = str(stype_str).lower().replace("-", "_") if stype_str else "practice"
    coaching_ctx = _COACHING_CONTEXT.get(stype_key, _COACHING_CONTEXT.get("practice", {}))

    if coaching_ctx:
        priority = coaching_ctx.get("priority_drill", "")
        if priority and priority not in drills:
            drills.append(f"[{coaching_ctx.get('tone', 'general').title()}] {priority}")

    # Consistency drill (always include)

    drills.append(
        "Consistency drill: pick your 3 weakest segments and run 5 laps "
        "focusing only on repeatable technique, ignoring lap times."
    )

    # Pad if needed

    if len(drills) < 2:
        drills.append("General: work on trail-braking depth to optimise corner entry speed.")

    return drills[:max_drills]


# ============================================================================

# Self-test

# ============================================================================



# ============================================================================

# 5. generate_coaching_guide  (Prompt 11)

# ============================================================================


def generate_coaching_guide(
    corner_performances: "list[dict[str, Any]] | None" = None,
    score_result: "dict[str, Any] | None" = None,
    lap_metrics: "list[dict[str, Any]] | None" = None,
    track_evolution: "dict[str, Any] | None" = None,
    session_type: str = "practice",
    *,
    max_focus_areas: int = 3,
) -> dict[str, Any]:
    """
    Generate a structured coaching guide from session analysis data.

    Translates raw performance data into actionable advice the driver can
    use at their next track day.

    Parameters
    ----------
    corner_performances:
        List of ``CornerPerformance.to_dict()`` results.
    score_result:
        Output of ``scoring.score_session()`` or ``score_session_phase_aware()``.
    lap_metrics:
        Per-lap metric dicts.
    track_evolution:
        Track evolution dict from condition_tracking.
    max_focus_areas:
        How many top improvement areas to highlight (default 3).

    Returns
    -------
    dict with keys:
        ``focus_areas``       -- list of top improvement opportunities
        ``corner_guide``      -- per-corner targets from driver's own best
        ``adaptation_tips``   -- condition-specific advice (if applicable)
        ``session_summary``   -- one-paragraph session assessment
        ``strengths``         -- list of strong points
        ``weaknesses``        -- list of areas to improve
    """
    guide: dict[str, Any] = {
        "focus_areas": [],
        "corner_guide": [],
        "adaptation_tips": [],
        "session_summary": "",
        "strengths": [],
        "weaknesses": [],
    }

    #
    # 1. Focus areas: ranked by potential time gain

    #
    focus_areas: list[dict[str, Any]] = []

    if corner_performances:
        # Sort corners by time loss (biggest first)

        sorted_corners = sorted(
            corner_performances,
            key=lambda c: c.get("time_loss_s", 0.0),
            reverse=True,
        )

        for cp in sorted_corners[:max_focus_areas]:
            tl = cp.get("time_loss_s", 0.0)
            if tl < 0.01:
                continue

            cid = cp.get("corner_id", "?")
            area: dict[str, Any] = {
                "corner_id": cid,
                "potential_gain_s": round(tl, 3),
                "description": "",
                "action": "",
            }

            # Determine dominant issue

            bp_delta = cp.get("braking_point_delta_m", 0.0)
            tl_braking = cp.get("time_loss_braking_s", 0.0)
            tl_apex = cp.get("time_loss_apex_speed_s", 0.0)
            tl_exit = cp.get("time_loss_exit_s", 0.0)

            # Pick the biggest contributor

            contributions = [
                ("braking", tl_braking, bp_delta),
                ("apex_speed", tl_apex, 0),
                ("exit", tl_exit, 0),
            ]
            contributions.sort(key=lambda x: abs(x[1]), reverse=True)
            dominant = contributions[0][0]

            if dominant == "braking" and math.isfinite(bp_delta) and abs(bp_delta) > 2:
                if bp_delta > 0:
                    area["description"] = (
                        f"Corner {cid} entry: You're braking {bp_delta:.0f}m too early."
                    )
                    area["action"] = (
                        f"Move your brake marker {bp_delta:.0f}m later. "
                        f"Potential gain: {tl:.1f}s/lap."
                    )
                else:
                    area["description"] = (
                        f"Corner {cid} entry: You're braking {abs(bp_delta):.0f}m too late."
                    )
                    area["action"] = (
                        f"Brake {abs(bp_delta):.0f}m earlier for better corner entry. "
                        f"Potential gain: {tl:.1f}s/lap."
                    )
            elif dominant == "apex_speed":
                theo_apex = cp.get("theoretical_apex_speed_mps", 0)
                actual_apex = cp.get("actual_apex_speed_mps", 0)
                deficit_kph = (theo_apex - actual_apex) * 3.6
                if deficit_kph > 1.0:
                    area["description"] = (
                        f"Corner {cid} mid-corner: You're losing {deficit_kph:.0f} km/h at the apex."
                    )
                    area["action"] = (
                        f"Carry {deficit_kph:.0f} km/h more through the apex. "
                        f"Trust the front grip. Potential gain: {tl:.1f}s/lap."
                    )
                else:
                    area["description"] = f"Corner {cid}: small mid-corner speed loss."
                    area["action"] = f"Refine your line for {tl:.1f}s/lap gain."
            elif dominant == "exit":
                theo_exit = cp.get("theoretical_exit_speed_mps", 0)
                actual_exit = cp.get("actual_exit_speed_mps", 0)
                deficit_kph = (theo_exit - actual_exit) * 3.6
                if deficit_kph > 1.0:
                    area["description"] = (
                        f"Corner {cid} exit: You're applying throttle too late."
                    )
                    area["action"] = (
                        f"Get on the throttle earlier at the apex. "
                        f"Target {deficit_kph:.0f} km/h more at corner exit. "
                        f"Potential gain: {tl:.1f}s/lap."
                    )
                else:
                    area["description"] = f"Corner {cid}: small exit speed loss."
                    area["action"] = f"Smoother throttle application for {tl:.1f}s/lap gain."
            else:
                area["description"] = f"Corner {cid}: {tl:.1f}s time loss."
                area["action"] = cp.get("coaching_hint", "Review this corner.")

            focus_areas.append(area)

    guide["focus_areas"] = focus_areas

    #
    # 2. Corner-by-corner guide: targets from driver's own best

    #
    corner_guide: list[dict[str, Any]] = []

    if corner_performances:
        for cp in corner_performances:
            cid = cp.get("corner_id", "?")
            entry = {
                "corner_id": cid,
                "entry_speed_target_kph": round(cp.get("actual_entry_speed_mps", 0) * 3.6, 1),
                "apex_speed_target_kph": round(cp.get("actual_apex_speed_mps", 0) * 3.6, 1),
                "exit_speed_target_kph": round(cp.get("actual_exit_speed_mps", 0) * 3.6, 1),
                "brake_point_m": round(cp.get("braking_point_actual_m", float("nan")), 1),
                "grip_utilisation_pct": round(cp.get("grip_utilisation_pct", 0), 1),
                "time_loss_s": round(cp.get("time_loss_s", 0), 3),
            }

            # Use theoretical values as aspirational targets

            theo_entry = cp.get("theoretical_entry_speed_mps", 0)
            theo_apex = cp.get("theoretical_apex_speed_mps", 0)
            theo_exit = cp.get("theoretical_exit_speed_mps", 0)
            entry["target_entry_kph"] = round(theo_entry * 3.6, 1) if theo_entry > 0 else None
            entry["target_apex_kph"] = round(theo_apex * 3.6, 1) if theo_apex > 0 else None
            entry["target_exit_kph"] = round(theo_exit * 3.6, 1) if theo_exit > 0 else None

            corner_guide.append(entry)

    guide["corner_guide"] = corner_guide

    #
    # 3. Condition adaptation tips

    #
    if track_evolution:
        grip_trend = track_evolution.get("grip_trend", "stable")
        total_evo = track_evolution.get("total_evolution_pct", 0)

        if grip_trend == "improving" and total_evo > 2.0:
            guide["adaptation_tips"].append(
                f"The track improved by {total_evo:.1f}% during this session. "
                "As grip builds, progressively push corner entry speed "
                "1-2 km/h per 5 laps to capture the available grip."
            )
        elif grip_trend == "degrading" and total_evo > 2.0:
            guide["adaptation_tips"].append(
                f"The track degraded by {total_evo:.1f}% during this session. "
                "Focus on smooth inputs and managing tyre life. "
                "Reduce corner entry speed gradually as grip drops."
            )

    #
    # 4. Session summary

    #
    parts: list[str] = []

    if score_result:
        total = score_result.get("total_score", 0)
        grade = score_result.get("grade", "?")
        parts.append(f"Overall score: {total:.1f}/100 ({grade}).")

        str_list = score_result.get("strengths", [])
        weak_list = score_result.get("weaknesses", [])

        if str_list:
            guide["strengths"] = str_list
            parts.append(
                f"Your biggest strength{'s are' if len(str_list) > 1 else ' is'} "
                f"{', '.join(s.lower() for s in str_list)}."
            )
        if weak_list:
            guide["weaknesses"] = weak_list
            parts.append(
                f"Focus on improving {', '.join(w.lower() for w in weak_list)}."
            )

    if corner_performances:
        # Find weakest and strongest corners

        sorted_by_loss = sorted(
            corner_performances,
            key=lambda c: c.get("time_loss_s", 0),
            reverse=True,
        )
        worst = sorted_by_loss[:2]
        best = sorted_by_loss[-2:] if len(sorted_by_loss) > 2 else []

        if worst and worst[0].get("time_loss_s", 0) > 0.05:
            cids = ", ".join(f"T{c['corner_id']}" for c in worst)
            parts.append(f"Biggest weakness: corners {cids}.")

        if best:
            cids = ", ".join(f"T{c['corner_id']}" for c in best)
            parts.append(f"Strongest corners: {cids}.")

    if not parts:
        parts.append("Session data was insufficient for detailed coaching.")

    # Add session-type-specific coaching context
    stype_key = str(session_type).lower().replace("-", "_") if session_type else "practice"
    coaching_ctx = _COACHING_CONTEXT.get(stype_key, {})
    if coaching_ctx:
        focus = coaching_ctx.get("focus", "")
        if focus:
            parts.append(f"Session focus: {focus}.")
        guide["coaching_context"] = coaching_ctx

    guide["session_summary"] = " ".join(parts)

    logger.info(
        "Coaching guide: %d focus areas, %d corners, %d adaptation tips",
        len(focus_areas), len(corner_guide), len(guide["adaptation_tips"]),
    )
    return guide


def _run_tests() -> None:
    import traceback as _tb

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, _tb.format_exc()))

    # --- Fixtures -
    def _make_lap_metrics(n: int = 12) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        return pd.DataFrame({
            _C_LAP:        list(range(1, n + 1)),
            _C_LAP_TIME:   [55.0 + rng.normal(0, 0.5) for _ in range(n)],
            _C_SPEED_MEAN: [40.0 + rng.normal(0, 1) for _ in range(n)],
        })

    def _make_deltas(n_laps: int = 5, n_seg: int = 10) -> pd.DataFrame:
        rng = np.random.default_rng(7)
        rows: list[dict[str, Any]] = []
        causes = [_CAUSE_ENTRY, _CAUSE_MID, _CAUSE_EXIT, _CAUSE_INSTAB, _CAUSE_ON_PACE]
        for lap in range(2, n_laps + 2):
            for seg in range(1, n_seg + 1):
                rows.append({
                    _C_LAP:       lap,
                    _C_SEGMENT:   seg,
                    _C_LOSS_MS:   max(0, rng.normal(50, 30)),
                    _C_CAUSE:     causes[seg % len(causes)],
                    _C_ENTRY_SPD: rng.normal(-2, 1),
                    _C_MIN_SPD:   rng.normal(-1, 0.5),
                    _C_EXIT_ACCEL: rng.normal(-0.5, 0.3),
                    _C_YAW_VAR:   rng.uniform(0.8, 1.5),
                })
        return pd.DataFrame(rows)

    # --- Mock context -
    class _MockCtx:
        def __init__(self, stype: str = "practice", tstate: str = "dry") -> None:
            from session_context import normalize_session_type, normalize_track_state
            self.session_type = normalize_session_type(stype)
            self.baseline_track_state = normalize_track_state(tstate)
            self.session_id = "test-001"

    # --- Tests -
    def t_summarize_session_basic() -> None:
        ctx = _MockCtx("race", "damp")
        lm = _make_lap_metrics(12)
        result = summarize_session(ctx, lm)
        assert "summary_sentence" in result
        assert result["n_laps"] == 12
        assert result["best_lap"] is not None
        assert result["pace_trend"] in ("stable", "improving", "degrading")

    _test("summarize_session_basic", t_summarize_session_basic)

    def t_summarize_session_empty() -> None:
        ctx = _MockCtx()
        result = summarize_session(ctx, pd.DataFrame())
        assert "Insufficient" in result["summary_sentence"]

    _test("summarize_session_empty", t_summarize_session_empty)

    def t_top_time_loss_segments() -> None:
        df = _make_deltas()
        top = top_time_loss_segments(df, k=3)
        assert len(top) <= 3
        assert "mean_loss_ms" in top.columns
        assert "likely_cause" in top.columns

    _test("top_time_loss_segments", t_top_time_loss_segments)

    def t_top_time_loss_empty() -> None:
        result = top_time_loss_segments(pd.DataFrame(), k=5)
        assert len(result) == 0

    _test("top_time_loss_empty", t_top_time_loss_empty)

    def t_classify_mistakes() -> None:
        df = _make_deltas()
        result = classify_mistakes(df)
        assert "dominant_cause" in result.columns
        assert "coaching_hint" in result.columns
        assert len(result) > 0

    _test("classify_mistakes", t_classify_mistakes)

    def t_classify_mistakes_empty() -> None:
        result = classify_mistakes(pd.DataFrame())
        assert len(result) == 0

    _test("classify_mistakes_empty", t_classify_mistakes_empty)

    def t_generate_drills_dry() -> None:
        df = _make_deltas()
        mistakes = classify_mistakes(df)
        ctx = _MockCtx("practice", "dry")
        drills = generate_next_session_drills(mistakes, ctx, max_drills=4)
        assert 1 <= len(drills) <= 4
        assert all(isinstance(d, str) for d in drills)

    _test("generate_drills_dry", t_generate_drills_dry)

    def t_generate_drills_wet() -> None:
        df = _make_deltas()
        mistakes = classify_mistakes(df)
        ctx = _MockCtx("race", "wet")
        drills = generate_next_session_drills(mistakes, ctx, max_drills=6)
        # Should include a wet-specific drill

        wet_drills = [d for d in drills if "wet" in d.lower() or "drying" in d.lower()]
        assert len(wet_drills) >= 1

    _test("generate_drills_wet", t_generate_drills_wet)

    def t_generate_drills_empty() -> None:
        ctx = _MockCtx()
        drills = generate_next_session_drills(pd.DataFrame(), ctx)
        assert len(drills) >= 1

    _test("generate_drills_empty", t_generate_drills_empty)

    # -- Summary -
    # -- coaching guide tests
    def t_coaching_guide_with_corners() -> None:
        corners = [
            {
                "corner_id": 1, "s_start": 100, "s_end": 200,
                "braking_point_delta_m": 8.0,
                "time_loss_s": 0.4, "time_loss_braking_s": 0.3,
                "time_loss_apex_speed_s": 0.05, "time_loss_exit_s": 0.05,
                "theoretical_apex_speed_mps": 20.0,
                "actual_apex_speed_mps": 18.0,
                "theoretical_entry_speed_mps": 30.0,
                "actual_entry_speed_mps": 28.0,
                "theoretical_exit_speed_mps": 35.0,
                "actual_exit_speed_mps": 33.0,
                "grip_utilisation_pct": 75.0,
                "coaching_hint": "Brake later",
            },
            {
                "corner_id": 2, "s_start": 300, "s_end": 400,
                "braking_point_delta_m": 2.0,
                "time_loss_s": 0.1, "time_loss_braking_s": 0.02,
                "time_loss_apex_speed_s": 0.05, "time_loss_exit_s": 0.03,
                "theoretical_apex_speed_mps": 25.0,
                "actual_apex_speed_mps": 24.5,
                "theoretical_entry_speed_mps": 35.0,
                "actual_entry_speed_mps": 34.0,
                "theoretical_exit_speed_mps": 40.0,
                "actual_exit_speed_mps": 39.0,
                "grip_utilisation_pct": 90.0,
                "coaching_hint": "Good",
            },
        ]
        score = {
            "total_score": 72.0, "grade": "B",
            "strengths": ["Consistency"],
            "weaknesses": ["Pace"],
            "sub_scores": {},
        }
        guide = generate_coaching_guide(
            corner_performances=corners,
            score_result=score,
        )
        assert len(guide["focus_areas"]) >= 1
        assert guide["focus_areas"][0]["corner_id"] == 1  # worst corner first
        assert guide["focus_areas"][0]["potential_gain_s"] == 0.4
        assert len(guide["corner_guide"]) == 2
        assert "session_summary" in guide
        assert len(guide["session_summary"]) > 10

    _test("coaching_guide_with_corners", t_coaching_guide_with_corners)

    def t_coaching_guide_empty() -> None:
        guide = generate_coaching_guide()
        assert guide["focus_areas"] == []
        assert guide["corner_guide"] == []

    _test("coaching_guide_empty", t_coaching_guide_empty)

    def t_coaching_guide_adaptation_tips() -> None:
        track_evo = {
            "grip_trend": "improving",
            "total_evolution_pct": 15.0,
        }
        guide = generate_coaching_guide(track_evolution=track_evo)
        assert len(guide["adaptation_tips"]) >= 1
        assert "improving" in guide["adaptation_tips"][0].lower() or "grip" in guide["adaptation_tips"][0].lower()

    _test("coaching_guide_adaptation", t_coaching_guide_adaptation_tips)

    def t_drills_session_type_context() -> None:
        df = _make_deltas()
        mistakes = classify_mistakes(df)
        ctx = _MockCtx("qualifying", "dry")
        drills = generate_next_session_drills(mistakes, ctx, max_drills=6)
        # Should include a qualifying-specific drill
        quali_drills = [d for d in drills if "qualifying" in d.lower() or "single-lap" in d.lower() or "push" in d.lower()]
        assert len(quali_drills) >= 1, f"Expected qualifying drill, got: {drills}"

    _test("drills_session_type_context", t_drills_session_type_context)

    def t_drills_endurance_context() -> None:
        df = _make_deltas()
        mistakes = classify_mistakes(df)
        ctx = _MockCtx("endurance", "dry")
        drills = generate_next_session_drills(mistakes, ctx, max_drills=6)
        # Should include an endurance-specific drill
        endurance_drills = [d for d in drills if "stint" in d.lower() or "endurance" in d.lower() or "pace" in d.lower()]
        assert len(endurance_drills) >= 1, f"Expected endurance drill, got: {drills}"

    _test("drills_endurance_context", t_drills_endurance_context)

    def t_coaching_guide_session_type() -> None:
        guide = generate_coaching_guide(session_type="qualifying")
        assert "coaching_context" in guide or guide["session_summary"] != ""

    _test("coaching_guide_session_type", t_coaching_guide_session_type)

    total = len(passed) + len(failed)
    print(f"\nDebrief Engine Tests: {len(passed)}/{total} passed")
    for n in passed:
        print(f"  PASS {n}")
    for n, tb in failed:
        print(f"  FAIL {n}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
