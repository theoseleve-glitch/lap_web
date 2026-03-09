"""Adaptation scorer — how well the driver adapts to changing conditions."""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

from scoring.constants import (
    ADAPT_FULL_RATIO,
    ADAPT_MIN_EVOLUTION_PCT,
    ADAPT_V2_DECAY_EXP,
    ADAPT_V2_PHASE_PACE_FULL_PCT,
    ADAPT_V2_PHASE_PACE_WEIGHT,
    ADAPT_V2_PHASE_PACE_ZERO_PCT,
    ADAPT_V2_STABLE_DEFAULT_FRAC,
    ADAPT_V2_TECHNIQUE_WEIGHT,
    ADAPT_V2_TRANSITION_FULL_LAPS,
    ADAPT_V2_TRANSITION_WEIGHT,
    ADAPT_V2_TRANSITION_ZERO_LAPS,
    ADAPT_W_CAPTURE,
    ADAPT_W_INTRA_PHASE,
    ADAPT_ZERO_RATIO,
    CONSISTENCY_FULL_CV_PCT,
    CONSISTENCY_ZERO_CV_PCT,
    MAX_ADAPTATION,
)
from scoring.helpers import _ratio_score

logger = logging.getLogger(__name__)


def _compute_adaptation_score(
    phases_df: pd.DataFrame,
    lap_to_phase: dict[int, int],
    lap_metrics: list[dict[str, Any]],
    *,
    track_evolution: "dict[str, Any] | None" = None,
) -> float:
    """
    Score how effectively the driver adapts to changing conditions.

    Two components:

    1. **Grip capture ratio** (60%): For each phase transition, how much
       of the track's grip improvement did the driver actually capture
       in their lap times?  If the track improved 5% but the driver
       only improved 2%, the capture ratio is 0.4.

    2. **Intra-phase consistency** (40%): CV% measured *within* each
       stable phase, not across the whole evolving session.

    When ``track_evolution`` data is available (from
    :func:`condition_tracking.compute_track_evolution_rate`), the grip
    capture ratio uses the phase median paces.  Otherwise, falls back
    to a slope-based heuristic.

    Returns a float bounded [0, 1].
    """
    if len(phases_df) < 2:
        return 0.5  # single phase -> neutral

    lm_df = pd.DataFrame(lap_metrics)
    if "lap_number" not in lm_df.columns or "lap_time_s" not in lm_df.columns:
        return 0.5

    lm_df["lap_time_s"] = pd.to_numeric(lm_df["lap_time_s"], errors="coerce")
    lm_df = lm_df.dropna(subset=["lap_time_s"]).sort_values("lap_number")
    lm_df["_phase"] = lm_df["lap_number"].map(lap_to_phase)

    # --- Component 1: Grip capture ratio -
    capture_ratio = _compute_grip_capture(
        phases_df, lm_df, track_evolution,
    )

    # --- Component 2: Intra-phase consistency -
    intra_cv = _compute_intra_phase_cv(phases_df, lm_df)

    # Combine

    capture_score = _ratio_score(
        capture_ratio, ADAPT_FULL_RATIO, ADAPT_ZERO_RATIO,
        higher_is_better=True,
    )

    # Intra-phase CV scoring: use dry thresholds (within a phase, conditions

    # are approximately stable so normal CV expectations apply)

    cv_score = _ratio_score(
        intra_cv, CONSISTENCY_FULL_CV_PCT, CONSISTENCY_ZERO_CV_PCT,
        higher_is_better=False,
    ) if not math.isnan(intra_cv) else 0.5

    adaptation = ADAPT_W_CAPTURE * capture_score + ADAPT_W_INTRA_PHASE * cv_score

    logger.info(
        "Adaptation: capture_ratio=%.3f (score=%.3f), "
        "intra_cv=%.2f%% (score=%.3f), combined=%.3f",
        capture_ratio, capture_score, intra_cv, cv_score, adaptation,
    )
    return float(np.clip(adaptation, 0.0, 1.0))


def _score_adaptation_v2(
    *,
    lap_metrics: list[dict[str, Any]],
    weather_timeline: Optional[pd.DataFrame] = None,
    theory_best: Optional[float] = None,
) -> float:
    """
    Weather-aware adaptation scoring (V2).

    Produces a weighted score in [0, MAX_ADAPTATION] based on three
    sub-metrics:

    1. **Transition Speed** (40%): After a phase change, how many laps
       until pace stabilises.  Full marks at <= 2 laps, zero at >= 8.
    2. **Phase-Relative Pace** (35%): Best lap in each phase vs
       grip-adjusted theoretical.  Full marks at <= 3% gap, zero >= 12%.
    3. **Condition-Appropriate Execution** (25%): Did driving technique
       change in the right direction between phases?

    When *weather_timeline* is None or has a single phase, returns a
    neutral score of 75% of MAX_ADAPTATION.
    """
    neutral = round(MAX_ADAPTATION * ADAPT_V2_STABLE_DEFAULT_FRAC, 4)

    # --- Guard: no weather data or single phase -> neutral -
    if weather_timeline is None or len(weather_timeline) < 2:
        return neutral
    if not lap_metrics:
        return neutral

    lm_df = pd.DataFrame(lap_metrics)
    if "lap_number" not in lm_df.columns or "lap_time_s" not in lm_df.columns:
        return neutral

    lm_df["lap_time_s"] = pd.to_numeric(lm_df["lap_time_s"], errors="coerce")
    lm_df = lm_df.dropna(subset=["lap_time_s"]).sort_values("lap_number").reset_index(drop=True)

    if lm_df.empty:
        return neutral

    # Build phase mapping from weather_timeline
    wt = weather_timeline.copy().sort_values("start_lap").reset_index(drop=True)
    phases: list[dict[str, Any]] = []
    for _, row in wt.iterrows():
        phases.append({
            "phase_id": int(row.get("phase_id", len(phases))),
            "start_lap": int(row["start_lap"]),
            "end_lap": int(row["end_lap"]),
            "avg_grip": float(row.get("avg_grip", 100.0)),
            "condition": str(row.get("condition", "unknown")),
        })

    if len(phases) < 2:
        return neutral

    # Map each lap to its phase
    def _lap_phase(lap_num: int) -> Optional[int]:
        for p in phases:
            if int(p["start_lap"]) <= lap_num <= int(p["end_lap"]):
                return int(p["phase_id"])
        return None

    lm_df["_phase_id"] = lm_df["lap_number"].apply(_lap_phase)
    lm_df = lm_df.dropna(subset=["_phase_id"])
    lm_df["_phase_id"] = lm_df["_phase_id"].astype(int)

    # ---- Sub-metric 1: Transition Speed (40%) ----
    transition_scores: list[float] = []
    for i in range(1, len(phases)):
        cur_phase = phases[i]
        phase_laps = lm_df[lm_df["_phase_id"] == cur_phase["phase_id"]].sort_values("lap_number")
        if len(phase_laps) < 3:
            continue

        times = phase_laps["lap_time_s"].values
        # Compute rolling CV of 3 laps
        phase_mean = float(np.mean(times))
        phase_cv = float(np.std(times) / phase_mean) if phase_mean > 0 else 0.0
        threshold_cv = 2.0 * phase_cv if phase_cv > 0 else 0.02

        # Count laps until rolling 3-lap CV drops below threshold
        stabilised_at = len(times)  # worst case
        for j in range(2, len(times)):
            window = times[max(0, j - 2):j + 1]
            w_mean = float(np.mean(window))
            w_cv = float(np.std(window) / w_mean) if w_mean > 0 else 0.0
            if w_cv <= threshold_cv:
                stabilised_at = j + 1  # 1-indexed lap count into phase
                break

        t_score = _ratio_score(
            float(stabilised_at),
            ADAPT_V2_TRANSITION_FULL_LAPS,
            ADAPT_V2_TRANSITION_ZERO_LAPS,
            higher_is_better=False,
            exp=ADAPT_V2_DECAY_EXP,
        )
        transition_scores.append(t_score)

    trans_sub = float(np.mean(transition_scores)) if transition_scores else 0.5

    # ---- Sub-metric 2: Phase-Relative Pace (35%) ----
    pace_scores: list[float] = []
    for p in phases:
        phase_laps = lm_df[lm_df["_phase_id"] == p["phase_id"]]
        if phase_laps.empty:
            continue
        best_in_phase = float(phase_laps["lap_time_s"].min())

        if theory_best is not None and theory_best > 0:
            avg_grip = float(p["avg_grip"])
            if avg_grip <= 0:
                avg_grip = 100.0
            adjusted_theory = theory_best / math.sqrt(avg_grip / 100.0)
            gap_pct = (best_in_phase - adjusted_theory) / adjusted_theory * 100.0
            gap_pct = max(0.0, gap_pct)  # negative gap means faster than theory
        else:
            # No theory available -- give partial credit
            gap_pct = 6.0  # midpoint

        p_score = _ratio_score(
            gap_pct,
            ADAPT_V2_PHASE_PACE_FULL_PCT,
            ADAPT_V2_PHASE_PACE_ZERO_PCT,
            higher_is_better=False,
            exp=ADAPT_V2_DECAY_EXP,
        )
        pace_scores.append(p_score)

    pace_sub = float(np.mean(pace_scores)) if pace_scores else 0.5

    # ---- Sub-metric 3: Condition-Appropriate Execution (25%) ----
    technique_scores: list[float] = []
    for i in range(1, len(phases)):
        prev_phase = phases[i - 1]
        cur_phase = phases[i]
        prev_laps = lm_df[lm_df["_phase_id"] == prev_phase["phase_id"]]
        cur_laps = lm_df[lm_df["_phase_id"] == cur_phase["phase_id"]]

        if prev_laps.empty or cur_laps.empty:
            continue

        # Determine if transitioning to wetter or drier conditions
        going_wet = float(cur_phase["avg_grip"]) < float(prev_phase["avg_grip"])
        checks = 0
        correct = 0

        # Check jerk_rms: should decrease in wet (smoother driving)
        if "jerk_rms_mps3" in lm_df.columns:
            prev_jerk = pd.to_numeric(prev_laps.get("jerk_rms_mps3", pd.Series(dtype=float)), errors="coerce").mean()
            cur_jerk = pd.to_numeric(cur_laps.get("jerk_rms_mps3", pd.Series(dtype=float)), errors="coerce").mean()
            if math.isfinite(prev_jerk) and math.isfinite(cur_jerk):
                checks += 1
                if going_wet and cur_jerk < prev_jerk:
                    correct += 1
                elif not going_wet and cur_jerk >= prev_jerk:
                    correct += 1

        # Check braking: should decrease in wet (less available grip)
        if "braking_max_mps2" in lm_df.columns:
            prev_brake = pd.to_numeric(prev_laps.get("braking_max_mps2", pd.Series(dtype=float)), errors="coerce").mean()
            cur_brake = pd.to_numeric(cur_laps.get("braking_max_mps2", pd.Series(dtype=float)), errors="coerce").mean()
            if math.isfinite(prev_brake) and math.isfinite(cur_brake):
                checks += 1
                if going_wet and cur_brake < prev_brake:
                    correct += 1
                elif not going_wet and cur_brake >= prev_brake:
                    correct += 1

        # Check line_length: should increase in wet (wider lines)
        if "line_length_m" in lm_df.columns:
            prev_line = pd.to_numeric(prev_laps.get("line_length_m", pd.Series(dtype=float)), errors="coerce").mean()
            cur_line = pd.to_numeric(cur_laps.get("line_length_m", pd.Series(dtype=float)), errors="coerce").mean()
            if math.isfinite(prev_line) and math.isfinite(cur_line):
                checks += 1
                if going_wet and cur_line > prev_line:
                    correct += 1
                elif not going_wet and cur_line <= prev_line:
                    correct += 1

        if checks > 0:
            technique_scores.append(correct / checks)
        else:
            technique_scores.append(0.5)  # no data -> neutral

    tech_sub = float(np.mean(technique_scores)) if technique_scores else 0.5

    # ---- Combine sub-metrics ----
    combined = (
        ADAPT_V2_TRANSITION_WEIGHT * trans_sub
        + ADAPT_V2_PHASE_PACE_WEIGHT * pace_sub
        + ADAPT_V2_TECHNIQUE_WEIGHT * tech_sub
    )

    score = float(np.clip(combined, 0.0, 1.0)) * MAX_ADAPTATION

    logger.info(
        "Adaptation V2: trans=%.3f, pace=%.3f, tech=%.3f, combined=%.3f, "
        "score=%.2f/%.0f",
        trans_sub, pace_sub, tech_sub, combined, score, MAX_ADAPTATION,
    )

    return round(score, 4)


def _compute_grip_capture(
    phases_df: pd.DataFrame,
    lm_df: pd.DataFrame,
    track_evolution: "dict[str, Any] | None",
) -> float:
    """
    Compute how much of the track's pace improvement the driver captured.

    If track_evolution provides per_lap_expected_s, compare the driver's
    actual improvement to the expected improvement from track evolution.
    Otherwise, use a slope-based heuristic.
    """
    # Use track evolution data if available

    if (track_evolution is not None
            and track_evolution.get("phase_paces")
            and len(track_evolution["phase_paces"]) >= 2):
        phase_paces = track_evolution["phase_paces"]
        expected_improvement = phase_paces[0]["median_s"] - phase_paces[-1]["median_s"]
        if expected_improvement <= 0:
            return 0.5  # track not improving -> neutral

        # Driver's actual improvement across same phases

        first_pid = phase_paces[0]["phase_id"]
        last_pid = phase_paces[-1]["phase_id"]
        first_laps = lm_df[lm_df["_phase"] == first_pid]["lap_time_s"]
        last_laps = lm_df[lm_df["_phase"] == last_pid]["lap_time_s"]

        if first_laps.empty or last_laps.empty:
            return 0.5

        driver_improvement = float(first_laps.median()) - float(last_laps.median())
        if expected_improvement > 0.5:  # meaningful evolution
            return float(np.clip(driver_improvement / expected_improvement, 0.0, 1.5))
        return 0.5

    # Fallback: slope-based heuristic (first 5 laps of each new phase)

    slopes: list[float] = []
    for pid in sorted(phases_df["phase_id"].unique()):
        if pid == 0:
            continue
        phase_laps = lm_df[lm_df["_phase"] == pid].head(5)
        if len(phase_laps) < 3:
            continue
        x = np.arange(len(phase_laps), dtype=float)
        y = phase_laps["lap_time_s"].values.astype(float)
        x_mean = x.mean()
        y_mean = y.mean()
        denom = float(((x - x_mean) ** 2).sum())
        if denom < 1e-12:
            continue
        slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
        slopes.append(slope)

    if not slopes:
        return 0.5

    mean_slope = float(np.mean(slopes))
    # Negative slope = improving = good adaptation

    # Map: -2 s/lap -> 1.0, 0 -> 0.5, +2 -> 0.0

    return float(np.clip(0.5 - mean_slope / 4.0, 0.0, 1.0))


def _compute_intra_phase_cv(
    phases_df: pd.DataFrame,
    lm_df: pd.DataFrame,
) -> float:
    """
    Weighted-average CV% computed WITHIN each phase (not across
    the whole evolving session).
    """
    total_laps = 0
    weighted_cv = 0.0

    for pid in sorted(phases_df["phase_id"].unique()):
        phase_times = lm_df[lm_df["_phase"] == pid]["lap_time_s"].dropna()
        if len(phase_times) < 3:
            continue
        mean_t = float(phase_times.mean())
        if mean_t <= 0:
            continue
        cv = float(phase_times.std() / mean_t * 100.0)
        n = len(phase_times)
        weighted_cv += cv * n
        total_laps += n

    if total_laps == 0:
        return float("nan")
    return weighted_cv / total_laps


def _compute_phase_scores(
    phases_df: pd.DataFrame,
    lap_to_phase: dict[int, int],
    lap_metrics: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Per-phase pace/consistency/stability sub-scores."""
    lm_df = pd.DataFrame(lap_metrics)
    if "lap_number" not in lm_df.columns or "lap_time_s" not in lm_df.columns:
        return {}

    lm_df["lap_time_s"] = pd.to_numeric(lm_df["lap_time_s"], errors="coerce")
    lm_df["_phase"] = lm_df["lap_number"].map(lap_to_phase)

    result: dict[int, dict[str, Any]] = {}
    for pid, grp in lm_df.groupby("_phase", sort=True):
        times = grp["lap_time_s"].dropna()
        if len(times) < 2:
            continue
        best = float(times.min())
        median = float(times.median())
        cv = float(times.std() / times.mean() * 100) if times.mean() > 0 else 0.0

        # Simple sub-scores normalised 0-1
        pace_sub = max(0.0, 1.0 - (median - best) / max(best, 1.0))
        cons_sub = max(0.0, 1.0 - cv / 5.0)  # 5% cv -> 0

        # Stability: jerk_rms if available
        jerk_col = "jerk_rms_mps3"
        if jerk_col in grp.columns:
            jerk_vals = pd.to_numeric(grp[jerk_col], errors="coerce").dropna()
            stab_sub = max(0.0, 1.0 - float(jerk_vals.std() / jerk_vals.mean())
                          ) if len(jerk_vals) > 1 and jerk_vals.mean() > 0 else 0.5
        else:
            stab_sub = 0.5

        result[int(pid)] = {
            "n_laps": len(times),
            "best_s": round(best, 3),
            "median_s": round(median, 3),
            "cv_pct": round(cv, 2),
            "pace_sub": round(pace_sub, 4),
            "consistency_sub": round(cons_sub, 4),
            "stability_sub": round(stab_sub, 4),
        }
    return result
