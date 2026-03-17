"""Endurance scoring — per-stint, per-driver, and team-level scoring.

Reuses the existing scoring.scorer.score_session() by computing metrics
from lap subsets, then aggregates across stints and drivers.
"""
from __future__ import annotations

import statistics
from typing import Any


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

    # Traffic time loss detection: triplet analysis
    # If lap N is 2s+ slower than both N-1 and N+1, it's a traffic loss
    traffic_losses: list[dict] = []
    traffic_total_s = 0.0
    for j in range(1, len(times) - 1):
        prev_t = times[j - 1]
        curr_t = times[j]
        next_t = times[j + 1]
        neighbor_mean = (prev_t + next_t) / 2
        delta = curr_t - neighbor_mean
        if delta >= 2.0 and curr_t > prev_t + 2.0 and curr_t > next_t + 2.0:
            traffic_losses.append({
                "lap_index": j,
                "lap_time_s": round(curr_t, 3),
                "neighbor_mean_s": round(neighbor_mean, 3),
                "time_lost_s": round(delta, 3),
            })
            traffic_total_s += delta

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
) -> dict[str, Any]:
    """Build the team-level report from driver reports.

    Args:
        driver_reports: {driver_name: compute_driver_report() output}
        total_laps: Total laps in the race.
        total_stints: Total stints detected.
        total_time_s: Total race time in seconds (optional).

    Returns:
        Team report with driver comparison and aggregated scores.
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

    # Total traffic stats
    team_traffic_total = sum(dr.get("traffic_total_s", 0) for dr in comparison)
    team_traffic_count = sum(dr.get("traffic_count", 0) for dr in comparison)

    return {
        "total_laps": total_laps,
        "total_time_s": total_time_s,
        "total_stints": total_stints,
        "drivers": drivers,
        "driver_comparison": comparison,
        "traffic_total_s": round(team_traffic_total, 3),
        "traffic_count": team_traffic_count,
        "scores": team_scores,
    }
