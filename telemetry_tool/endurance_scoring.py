"""Endurance scoring — per-stint, per-driver, and team-level scoring.

Reuses the existing scoring.scorer.score_session() by computing metrics
from lap subsets, then aggregates across stints and drivers.

Track-evolution-aware pace: when lap times show a clear improvement trend
(e.g. track rubbering in), the pace score uses running-PB deltas instead
of static median-vs-best.  This rewards drivers who consistently stay near
their evolving capability rather than penalising early laps.
"""
from __future__ import annotations

import statistics
from typing import Any


# ── Track-evolution-aware pace ─────────────────────────────────────────

# Minimum laps to attempt trend detection
_TREND_MIN_LAPS = 6
# Slope threshold: at least 0.03 s/lap improvement (negative slope)
_TREND_SLOPE_THRESHOLD = -0.03
# R² threshold: trend must explain at least 25% of variance
_TREND_R2_THRESHOLD = 0.25
# Scoring: mean running-PB delta → score (/25)
_RPB_FULL_DELTA_S = 0.2   # ≤0.2 s mean delta = full marks
_RPB_ZERO_DELTA_S = 3.0   # ≥3.0 s mean delta = zero


def running_pb_pace(
    times: list[float],
    condition: str = "dry",
) -> tuple[float | None, dict]:
    """Compute pace score using running-PB deltas.

    When track evolution is detected (negative slope + decent R²), each
    lap is compared against the best lap *up to that point* — not the
    session-end PB.  The mean of those deltas drives the score.

    For ``condition="mixed"``, trend detection is bypassed — conditions
    changing mid-stint inherently cause track evolution, so running-PB
    is always applied (minimum lap count still required).

    Returns (score, details_dict) or (None, details_dict) if no clear
    trend is found.
    """
    n = len(times)
    if n < _TREND_MIN_LAPS:
        return None, {"trend": False, "reason": "too_few_laps"}

    # ── Linear regression: time vs lap index ───────────────────
    x_mean = (n - 1) / 2.0
    y_mean = sum(times) / n
    ss_xy = sum((i - x_mean) * (t - y_mean) for i, t in enumerate(times))
    ss_xx = sum((i - x_mean) ** 2 for i in range(n))
    slope = ss_xy / ss_xx if ss_xx > 0 else 0.0

    # R² — how well does the linear model fit?
    ss_yy = sum((t - y_mean) ** 2 for t in times)
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_xx > 0 and ss_yy > 0 else 0.0

    # "mixed" condition = conditions changed mid-stint → always apply running-PB
    force = condition.lower() == "mixed"

    if not force and (slope > _TREND_SLOPE_THRESHOLD or r_squared < _TREND_R2_THRESHOLD):
        return None, {
            "trend": False,
            "slope_s_per_lap": round(slope, 4),
            "r_squared": round(r_squared, 4),
        }

    # ── Compute running-PB deltas ──────────────────────────────
    running_pb = float("inf")
    deltas: list[float] = []
    for t in times:
        running_pb = min(running_pb, t)
        deltas.append(t - running_pb)

    mean_delta = statistics.mean(deltas) if deltas else 0.0

    # ── Score: lower mean_delta = better ───────────────────────
    # Linear interpolation within [_RPB_FULL_DELTA_S, _RPB_ZERO_DELTA_S]
    clamped = max(_RPB_FULL_DELTA_S, min(mean_delta, _RPB_ZERO_DELTA_S))
    ratio = 1.0 - (clamped - _RPB_FULL_DELTA_S) / (_RPB_ZERO_DELTA_S - _RPB_FULL_DELTA_S)
    score = round(ratio * 25.0, 1)

    return score, {
        "trend": True,
        "method": "running_pb_mixed" if force else "running_pb",
        "slope_s_per_lap": round(slope, 4),
        "r_squared": round(r_squared, 4),
        "mean_running_pb_delta_s": round(mean_delta, 3),
        "n_new_pbs": sum(1 for d in deltas if d == 0.0),
        "score": score,
    }


# ── Traffic time loss (running-PB method) ──────────────────────────────

_TRAFFIC_THRESHOLD_S = 0.5
_DEGRADE_MIN_FLAGGED = 5
_DEGRADE_SLOPE_THRESHOLD = 0.02   # positive slope = track getting slower
_DEGRADE_R2_THRESHOLD = 0.20


def compute_traffic_losses(
    times: list[float],
) -> tuple[list[dict], float, int, dict | None]:
    """Compute traffic time losses using running-PB + 0.5 s threshold.

    If 5+ laps are flagged, checks for track degradation (positive slope
    in lap times with decent R²).  When degradation is detected the
    reference shifts to a trend line so genuine slowdown isn't penalised.

    Returns (losses_list, total_s, count, degradation_info_or_None).
    """
    n = len(times)
    if n < 2:
        return [], 0.0, 0, None

    # ── Pass 1: raw running-PB losses ──────────────────────────
    raw_losses: list[tuple[int, float, float, float]] = []  # (idx, time, rb, excess)
    running_best = float("inf")
    for j, t in enumerate(times):
        running_best = min(running_best, t)
        excess = t - running_best - _TRAFFIC_THRESHOLD_S
        if excess > 0:
            raw_losses.append((j, t, running_best, excess))

    # ── Pass 2: degradation check ──────────────────────────────
    degradation = None
    if len(raw_losses) >= _DEGRADE_MIN_FLAGGED and n >= _TREND_MIN_LAPS:
        x_mean = (n - 1) / 2.0
        y_mean = sum(times) / n
        ss_xy = sum((i - x_mean) * (t - y_mean) for i, t in enumerate(times))
        ss_xx = sum((i - x_mean) ** 2 for i in range(n))
        slope = ss_xy / ss_xx if ss_xx > 0 else 0.0
        ss_yy = sum((t - y_mean) ** 2 for t in times)
        r_sq = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_xx > 0 and ss_yy > 0 else 0.0

        if slope >= _DEGRADE_SLOPE_THRESHOLD and r_sq >= _DEGRADE_R2_THRESHOLD:
            # Track is getting slower — recalculate using trend-adjusted reference.
            # predicted(j) = y_mean + slope * (j - x_mean)
            # time_lost = lap_time - predicted(j) - threshold  (only if > 0)
            degradation = {
                "detected": True,
                "slope_s_per_lap": round(slope, 4),
                "r_squared": round(r_sq, 4),
                "raw_flagged": len(raw_losses),
            }
            adjusted_losses: list[tuple[int, float, float, float]] = []
            for j, t in enumerate(times):
                predicted = y_mean + slope * (j - x_mean)
                excess = t - predicted - _TRAFFIC_THRESHOLD_S
                if excess > 0:
                    adjusted_losses.append((j, t, round(predicted, 3), excess))
            raw_losses = adjusted_losses
            degradation["adjusted_flagged"] = len(adjusted_losses)

    # ── Build output ───────────────────────────────────────────
    losses = []
    total_s = 0.0
    for idx, lap_t, ref, excess in raw_losses:
        losses.append({
            "lap_index": idx,
            "lap_time_s": round(lap_t, 3),
            "running_best_s": round(ref, 3),
            "time_lost_s": round(excess, 3),
        })
        total_s += excess

    return losses, round(total_s, 3), len(losses), degradation


def compute_stint_scores(
    all_laps: list[dict[str, Any]],
    stint: dict[str, Any],
    condition: str = "dry",
) -> dict[str, Any]:
    """Score a single stint using only laps within its range.

    Args:
        all_laps: Full session lap list (with lap_number, lap_time_s, is_valid).
        stint: Stint dict with start_lap, end_lap, stint_number.
        condition: Track condition for this stint (dry/damp/wet).

    Returns:
        Dict with best_lap_s, mean_lap_s, lap_count, consistency_cv_pct,
        pace_fade_pct, scores {pace, consistency, robustness}.
    """
    start = stint["start_lap"]
    end = stint["end_lap"]

    stint_laps = [
        lap for lap in all_laps
        if start <= lap["lap_number"] <= end
        and lap.get("is_valid", True)
        and lap.get("lap_time_s") is not None
        and lap["lap_time_s"] > 0
    ]

    if not stint_laps:
        return {
            "stint_number": stint.get("stint_number"),
            "best_lap_s": None,
            "mean_lap_s": None,
            "lap_count": 0,
            "consistency_cv_pct": None,
            "pace_fade_pct": None,
            "scores": {"pace": 0, "consistency": 0, "robustness": 0},
        }

    times = [lap["lap_time_s"] for lap in stint_laps]
    best = min(times)
    mean = statistics.mean(times)
    median = statistics.median(times)
    std = statistics.stdev(times) if len(times) > 1 else 0
    cv = (std / mean * 100) if mean > 0 else 0

    # Pace fade: compare first third vs last third
    n = len(times)
    third = max(1, n // 3)
    early_mean = statistics.mean(times[:third])
    late_mean = statistics.mean(times[-third:])
    fade_pct = ((late_mean - early_mean) / early_mean * 100) if early_mean > 0 else 0

    # Score via existing scorer
    metrics = {
        "best_s": best,
        "mean_s": mean,
        "median_s": median,
        "std_s": std,
        "n_valid_laps": len(times),
        "best_to_median_s": median - best,
        "early_mean_s": early_mean,
        "late_mean_s": late_mean,
        "early_yaw_var": 0,
        "late_yaw_var": 0,
    }

    try:
        from scoring.scorer import score_session
        result = score_session(
            metrics, {},
            session_type="endurance_stint",
            track_state=condition,
        )
        subs = result.get("sub_scores", {})
        scores = {
            "pace": round(subs.get("pace", {}).get("score", 0), 1),
            "consistency": round(subs.get("consistency", {}).get("score", 0), 1),
            "robustness": round(subs.get("robustness", {}).get("score", 0), 1),
        }
    except Exception:
        scores = {"pace": 0, "consistency": 0, "robustness": 0}

    traffic_losses, traffic_total_s, traffic_count, track_degradation = compute_traffic_losses(times)

    return {
        "stint_number": stint.get("stint_number"),
        "best_lap_s": round(best, 3),
        "mean_lap_s": round(mean, 3),
        "lap_count": len(times),
        "consistency_cv_pct": round(cv, 2),
        "pace_fade_pct": round(fade_pct, 2),
        "traffic_losses": traffic_losses,
        "traffic_total_s": round(traffic_total_s, 3),
        "traffic_count": len(traffic_losses),
        "scores": scores,
    }


def compute_driver_report(
    driver_name: str,
    stint_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate stint results for a single driver.

    Args:
        driver_name: Driver name.
        stint_results: List of compute_stint_scores() outputs for this driver's stints.

    Returns:
        Dict with driver stats, best_per_stint progression, aggregated scores.
    """
    valid_stints = [s for s in stint_results if s.get("lap_count", 0) > 0]

    if not valid_stints:
        return {
            "driver_name": driver_name,
            "total_laps": 0,
            "total_stints": 0,
            "stints": stint_results,
            "best_lap_s": None,
            "mean_lap_s": None,
            "consistency_cv_pct": None,
            "best_per_stint": [],
            "scores": {"pace": 0, "consistency": 0, "robustness": 0},
        }

    total_laps = sum(s["lap_count"] for s in valid_stints)

    # Group stints by condition for fair comparison
    conditions = set(s.get("condition", "dry") for s in valid_stints)

    # Best lap per condition (don't compare wet best vs dry best)
    best_per_condition: dict[str, float] = {}
    for cond in conditions:
        cond_stints = [s for s in valid_stints if s.get("condition", "dry") == cond]
        if cond_stints:
            best_per_condition[cond] = min(s["best_lap_s"] for s in cond_stints)
    best_lap = min(best_per_condition.values()) if best_per_condition else None

    # Weighted mean pace per condition
    mean_per_condition: dict[str, float] = {}
    for cond in conditions:
        cond_stints = [s for s in valid_stints if s.get("condition", "dry") == cond]
        cond_laps = sum(s["lap_count"] for s in cond_stints)
        if cond_laps > 0:
            mean_per_condition[cond] = sum(s["mean_lap_s"] * s["lap_count"] for s in cond_stints) / cond_laps
    weighted_mean = sum(s["mean_lap_s"] * s["lap_count"] for s in valid_stints) / total_laps

    # Best lap per stint (for progression chart)
    best_per_stint = [
        {"stint_number": s["stint_number"], "best_lap_s": s["best_lap_s"], "condition": s.get("condition", "dry")}
        for s in valid_stints
    ]

    # Consistency = mean of per-stint consistency scores (not inter-stint CV)
    stint_consistency_scores = [s["scores"].get("consistency", 0) for s in valid_stints if s.get("scores")]
    mean_consistency = statistics.mean(stint_consistency_scores) if stint_consistency_scores else 0

    # Aggregate scores: consistency uses mean of stint scores, others weighted by laps
    agg_scores: dict[str, float] = {}
    for key in ("pace", "robustness"):
        weighted = sum(s["scores"].get(key, 0) * s["lap_count"] for s in valid_stints)
        agg_scores[key] = round(weighted / total_laps, 1)
    agg_scores["consistency"] = round(mean_consistency, 1)

    # Traffic time loss across all stints
    driver_traffic_total = sum(s.get("traffic_total_s", 0) for s in valid_stints)
    driver_traffic_count = sum(s.get("traffic_count", 0) for s in valid_stints)

    # Execution score = 25 - penalty from traffic losses
    # Every 1s of traffic loss = -0.5 points (max 25, min 0)
    execution_raw = max(0, 25 - driver_traffic_total * 0.5)
    agg_scores["execution"] = round(execution_raw, 1)

    # CV for display: mean of per-stint CVs (not inter-stint)
    stint_cvs = [s.get("consistency_cv_pct", 0) for s in valid_stints if s.get("consistency_cv_pct") is not None]
    display_cv = statistics.mean(stint_cvs) if stint_cvs else 0

    return {
        "driver_name": driver_name,
        "total_laps": total_laps,
        "total_stints": len(valid_stints),
        "stints": stint_results,
        "best_lap_s": round(best_lap, 3) if best_lap else None,
        "mean_lap_s": round(weighted_mean, 3),
        "consistency_cv_pct": round(display_cv, 2),
        "best_per_stint": best_per_stint,
        "best_per_condition": {k: round(v, 3) for k, v in best_per_condition.items()},
        "mean_per_condition": {k: round(v, 3) for k, v in mean_per_condition.items()},
        "conditions": sorted(conditions),
        "traffic_total_s": round(driver_traffic_total, 3),
        "traffic_count": driver_traffic_count,
        "scores": agg_scores,
    }


def compute_team_report(
    driver_reports: dict[str, dict[str, Any]],
    total_laps: int,
    total_stints: int,
    total_time_s: float | None = None,
    stint_results: list[dict[str, Any]] | None = None,
    pit_threshold_s: float = 30.0,
) -> dict[str, Any]:
    """Build the team-level report from driver reports.

    Args:
        driver_reports: {driver_name: compute_driver_report() output}
        total_laps: Total laps in the race.
        total_stints: Total stints detected.
        total_time_s: Total race time in seconds (optional).
        stint_results: Raw stint result dicts (for pit analysis).
        pit_threshold_s: Target pit stop duration (from user config).

    Returns:
        Team report with driver comparison, time loss breakdown, and coaching.
    """
    drivers = list(driver_reports.keys())
    comparison = list(driver_reports.values())

    # Aggregate team scores (weighted by lap count across all drivers)
    team_scores: dict[str, float] = {}
    for key in ("pace", "consistency", "robustness", "execution"):
        total_weighted = sum(
            dr["scores"].get(key, 0) * dr["total_laps"]
            for dr in comparison if dr["total_laps"] > 0
        )
        total_driver_laps = sum(dr["total_laps"] for dr in comparison)
        team_scores[key] = round(total_weighted / total_driver_laps, 1) if total_driver_laps > 0 else 0

    # ── Traffic time loss ──────────────────────────────────────
    team_traffic_total = sum(dr.get("traffic_total_s", 0) for dr in comparison)
    team_traffic_count = sum(dr.get("traffic_count", 0) for dr in comparison)

    # ── Pit time loss ──────────────────────────────────────────
    # pit_loss = n_pits * (avg_pit_duration - threshold)
    pit_stints = []
    if stint_results:
        for s in stint_results:
            pt = s.get("pit_lap_time_s")
            if pt and pt > 0:
                mean_lap = s.get("mean_lap_s") or s.get("best_lap_s") or 0
                pit_dur = max(0, pt - mean_lap)
                pit_stints.append({
                    "stint_number": s.get("stint_number"),
                    "driver_name": s.get("driver_name"),
                    "pit_duration_s": round(pit_dur, 1),
                })

    n_pits = len(pit_stints)
    avg_pit_s = statistics.mean(p["pit_duration_s"] for p in pit_stints) if pit_stints else 0
    pit_excess_s = max(0, avg_pit_s - pit_threshold_s) if pit_stints else 0
    pit_time_loss_s = round(n_pits * pit_excess_s, 1)

    # ── Total time loss ────────────────────────────────────────
    total_time_loss_s = round(team_traffic_total + pit_time_loss_s, 1)

    # ── Coaching ───────────────────────────────────────────────
    coaching = _build_coaching(
        traffic_total_s=team_traffic_total,
        traffic_count=team_traffic_count,
        pit_time_loss_s=pit_time_loss_s,
        n_pits=n_pits,
        avg_pit_s=avg_pit_s,
        pit_threshold_s=pit_threshold_s,
        total_time_loss_s=total_time_loss_s,
        comparison=comparison,
        total_time_s=total_time_s,
    )

    return {
        "total_laps": total_laps,
        "total_time_s": total_time_s,
        "total_stints": total_stints,
        "drivers": drivers,
        "driver_comparison": comparison,
        "traffic_total_s": round(team_traffic_total, 3),
        "traffic_count": team_traffic_count,
        "pit_stops": pit_stints,
        "n_pits": n_pits,
        "avg_pit_s": round(avg_pit_s, 1),
        "pit_threshold_s": pit_threshold_s,
        "pit_time_loss_s": pit_time_loss_s,
        "total_time_loss_s": total_time_loss_s,
        "coaching": coaching,
        "scores": team_scores,
    }


def _build_coaching(
    *,
    traffic_total_s: float,
    traffic_count: int,
    pit_time_loss_s: float,
    n_pits: int,
    avg_pit_s: float,
    pit_threshold_s: float,
    total_time_loss_s: float,
    comparison: list[dict[str, Any]],
    total_time_s: float | None,
) -> list[dict[str, str]]:
    """Generate coaching insights from time loss analysis."""
    tips: list[dict[str, str]] = []

    # Headline
    if total_time_loss_s > 0:
        parts = []
        if traffic_total_s > 0:
            parts.append(f"{traffic_total_s:.1f}s in traffic")
        if pit_time_loss_s > 0:
            parts.append(f"{pit_time_loss_s:.1f}s in slow pits")
        breakdown = " + ".join(parts) if parts else ""
        tips.append({
            "priority": "high",
            "area": "time_loss",
            "message": f"Total time loss: {total_time_loss_s:.1f}s ({breakdown}). "
                       "This is recoverable time — focus areas below.",
        })

    # Pit coaching
    if pit_time_loss_s > 0:
        tips.append({
            "priority": "high" if pit_time_loss_s > 10 else "medium",
            "area": "pits",
            "message": f"Pit stops averaged {avg_pit_s:.0f}s vs {pit_threshold_s:.0f}s target "
                       f"({n_pits} stops × {avg_pit_s - pit_threshold_s:.0f}s excess = "
                       f"{pit_time_loss_s:.1f}s lost). Drill pit entry/exit timing and driver changes.",
        })

    # Traffic coaching
    if traffic_total_s > 5:
        # Find worst-affected driver
        worst_driver = max(comparison, key=lambda d: d.get("traffic_total_s", 0))
        wd_name = worst_driver.get("driver_name", "?")
        wd_loss = worst_driver.get("traffic_total_s", 0)
        tips.append({
            "priority": "high" if traffic_total_s > 15 else "medium",
            "area": "traffic",
            "message": f"{traffic_count} traffic incidents cost {traffic_total_s:.1f}s. "
                       f"Worst affected: {wd_name} ({wd_loss:.1f}s). "
                       "Work on race-craft — earlier overtaking, better positioning into corners.",
        })
    elif traffic_count > 0:
        tips.append({
            "priority": "low",
            "area": "traffic",
            "message": f"Minor traffic: {traffic_count} incidents, {traffic_total_s:.1f}s — good race-craft.",
        })

    # Pace balance
    if len(comparison) >= 2:
        sorted_pace = sorted(comparison, key=lambda d: d.get("best_lap_s") or 999)
        fastest = sorted_pace[0]
        slowest = sorted_pace[-1]
        gap = (slowest.get("best_lap_s") or 0) - (fastest.get("best_lap_s") or 0)
        if gap > 1.0:
            tips.append({
                "priority": "medium",
                "area": "driver_balance",
                "message": f"Pace gap between {fastest['driver_name']} and {slowest['driver_name']}: "
                           f"{gap:.1f}s. "
                           f"Equalise with coaching for {slowest['driver_name']} on braking points and corner entry.",
            })

    # Time loss as % of race
    if total_time_s and total_time_s > 0 and total_time_loss_s > 0:
        pct = total_time_loss_s / total_time_s * 100
        if pct > 1:
            tips.append({
                "priority": "low",
                "area": "efficiency",
                "message": f"Time loss represents {pct:.1f}% of total race time — "
                           f"eliminating it could gain {total_time_loss_s / (comparison[0].get('mean_lap_s') or 85):.1f} equivalent laps.",
            })

    if not tips:
        tips.append({
            "priority": "low",
            "area": "general",
            "message": "Clean race — no significant time loss from traffic or pits.",
        })

    return tips
