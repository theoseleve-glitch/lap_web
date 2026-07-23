"""AI Coaching Engine — session narrative synthesis and drill generation.

Builds on the existing per-corner coaching data (CoachingV2) to produce:
1. **Session debrief** — thematic narrative connecting corner-level insights
2. **Progression analysis** — lap-to-lap improvement trends
3. **Practice drills** — targeted exercises for the next session
4. **Priority focus areas** — ranked list of where time is being lost

The engine is rule-based and deterministic — no external AI model required.
All inputs come from the existing analysis pipeline (corner_performances,
CoachingV2, scores, driving style, lap metrics).

Usage::

    from coaching_engine import generate_session_coaching
    result = generate_session_coaching(
        corners=corner_data,
        coaching_v2=coaching_v2_dict,
        scores=score_result,
        lap_metrics=lap_metrics_list,
        driving_style=style_dict,
    )
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from coaching.models import FocusArea, Drill, ProgressionInsight, SessionCoaching

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
#
# FocusArea / Drill / ProgressionInsight / SessionCoaching now come from the
# canonical coaching/models.py — this engine only builds them from their base
# fields (see docstrings there); the V3-only fields default to None and are
# still emitted by the shared to_dict(), so callers of GET /sessions/<id>/coaching
# see one contract regardless of which engine produced the result.


# ---------------------------------------------------------------------------
# Cause categories
# ---------------------------------------------------------------------------

_CAUSE_CATEGORIES: dict[str, str] = {
    "early_braking": "braking",
    "late_braking": "braking",
    "low_apex_speed": "apex_speed",
    "slow_exit": "exit_traction",
    "poor_line": "line",
    "grip_limited": "apex_speed",
    "traction_limited": "exit_traction",
    "braking_limited": "braking",
}

_CATEGORY_ADVICE: dict[str, str] = {
    "braking": "Work on brake point consistency — pick a visual marker and commit to it.",
    "apex_speed": "Trust the grip and carry more speed into the apex. Look further ahead through the corner.",
    "exit_traction": "Get on throttle earlier with progressive application. Focus on unwinding the steering before accelerating.",
    "line": "Tighten your racing line. Use reference points for turn-in, apex, and exit.",
    "consistency": "Focus on repeatability — same braking point, same turn-in, every lap.",
}

_CATEGORY_DRILL: dict[str, dict[str, str]] = {
    "braking": {
        "title": "Brake Point Precision Drill",
        "description": (
            "Pick a fixed braking marker for each focus corner. "
            "Run 5 laps hitting the exact same point every time. "
            "Gradually move the marker 1m later each set of 5 laps."
        ),
        "target_metric": "braking_point_delta_m",
        "target_improvement": "Reduce brake point variance to <2m",
    },
    "apex_speed": {
        "title": "Apex Speed Carry Drill",
        "description": (
            "Enter focus corners 2 km/h faster than comfortable. "
            "Hold minimum speed through the apex. "
            "If you run wide, you've found the limit — back off 1 km/h."
        ),
        "target_metric": "apex_speed_ratio",
        "target_improvement": "Increase apex speed by 3-5%",
    },
    "exit_traction": {
        "title": "Throttle Application Drill",
        "description": (
            "At each focus corner, apply throttle 0.5s earlier than usual. "
            "Use progressive pedal (25% → 50% → 100%) to avoid wheelspin. "
            "Track exit speed improvement."
        ),
        "target_metric": "throttle_onset_delay_m",
        "target_improvement": "Reduce throttle delay by 5m",
    },
    "line": {
        "title": "Racing Line Precision Drill",
        "description": (
            "Follow the kerbs: use turn-in, apex, and exit kerbs as physical markers. "
            "Run 5 slow laps focusing purely on hitting the geometric line. "
            "Then gradually increase pace while maintaining line discipline."
        ),
        "target_metric": "line_variation_index",
        "target_improvement": "Reduce line variation by 20%",
    },
    "consistency": {
        "title": "Consistency Metronome Drill",
        "description": (
            "Target your 3rd-best lap time (not fastest). "
            "Run 10 consecutive laps within 0.3s of that target. "
            "Focus on rhythm, not outright speed."
        ),
        "target_metric": "lap_time_cv_pct",
        "target_improvement": "Reduce lap time CV below 1.5%",
    },
}


# ---------------------------------------------------------------------------
# Theme classification
# ---------------------------------------------------------------------------

def _classify_session_theme(
    scores: dict[str, Any],
    focus_areas: list[FocusArea],
    progression: list[ProgressionInsight],
) -> str:
    """Generate a 1-sentence session characterization."""
    total = scores.get("total_score", 0)
    grade = scores.get("grade", "?")
    pace = scores.get("sub_scores", {}).get("pace", {}).get("score", 0)
    consistency = scores.get("sub_scores", {}).get("consistency", {}).get("score", 0)

    # Check progression trend
    improving = any(p.trend == "improving" for p in progression)

    if total >= 85:
        theme = f"Outstanding session ({grade}) — near-optimal execution across all corners."
    elif total >= 70:
        top_issue = focus_areas[0].category if focus_areas else "consistency"
        theme = f"Strong session ({grade}) with room to improve {top_issue.replace('_', ' ')}."
    elif pace > consistency + 5:
        theme = f"Fast but inconsistent ({grade}) — raw pace is there but lap-to-lap variation is high."
    elif consistency > pace + 5:
        theme = f"Consistent but lacking pace ({grade}) — great repeatability, time to push the limit."
    elif improving:
        theme = f"Learning session ({grade}) — clear improvement trend through the stint."
    else:
        top_issue = focus_areas[0].category if focus_areas else "overall pace"
        theme = f"Development session ({grade}) — primary focus needed on {top_issue.replace('_', ' ')}."

    return theme


# ---------------------------------------------------------------------------
# Focus area aggregation
# ---------------------------------------------------------------------------

def _aggregate_focus_areas(corners: list[dict[str, Any]]) -> list[FocusArea]:
    """Group corner time losses by cause category and rank by total impact."""
    category_data: dict[str, dict[str, Any]] = {}

    for c in corners:
        cause = c.get("primary_cause", "")
        category = _CAUSE_CATEGORIES.get(cause, "consistency")
        loss = c.get("time_loss_total_s") or c.get("time_loss_s") or 0
        cid = c.get("corner_id", 0)

        if loss <= 0.01:
            continue

        if category not in category_data:
            category_data[category] = {"loss": 0.0, "ids": []}
        category_data[category]["loss"] += loss
        category_data[category]["ids"].append(cid)

    # Sort by total time loss descending
    ranked = sorted(category_data.items(), key=lambda x: x[1]["loss"], reverse=True)

    areas = []
    for rank, (cat, data) in enumerate(ranked, 1):
        ids_str = ", ".join(f"C{i}" for i in data["ids"][:5])
        areas.append(FocusArea(
            rank=rank,
            category=cat,
            time_loss_s=data["loss"],
            corner_ids=data["ids"],
            summary=f"{cat.replace('_', ' ').title()}: {data['loss']:.3f}s lost across {ids_str}",
            advice=_CATEGORY_ADVICE.get(cat, "Focus on improving technique in these corners."),
        ))

    return areas[:5]  # Top 5 focus areas


# ---------------------------------------------------------------------------
# Progression analysis
# ---------------------------------------------------------------------------

def _analyze_progression(lap_metrics: list[dict[str, Any]]) -> list[ProgressionInsight]:
    """Detect lap-to-lap improvement/degradation trends."""
    if not lap_metrics or len(lap_metrics) < 3:
        return []

    insights = []

    # Lap time progression
    times = [m.get("lap_time_s", 0) for m in lap_metrics if m.get("lap_time_s")]
    if len(times) >= 3:
        n = len(times)
        third = max(1, n // 3)
        early = sum(times[:third]) / third
        late = sum(times[-third:]) / third
        change = ((late - early) / early) * 100 if early > 0 else 0

        if change < -1.0:
            trend = "improving"
            detail = f"Lap times improved by {abs(change):.1f}% from early to late stint ({early:.2f}s → {late:.2f}s)."
        elif change > 2.0:
            trend = "degrading"
            detail = f"Lap times degraded by {change:.1f}% — possible tire wear or fatigue ({early:.2f}s → {late:.2f}s)."
        else:
            trend = "stable"
            detail = f"Lap times remained stable throughout ({early:.2f}s → {late:.2f}s)."

        insights.append(ProgressionInsight(
            metric="lap_time_s",
            trend=trend,
            detail=detail,
            early_value=early,
            late_value=late,
            change_pct=change,
        ))

    # Speed consistency progression
    speeds = [m.get("speed_max_mps", 0) for m in lap_metrics if m.get("speed_max_mps")]
    if len(speeds) >= 3:
        n = len(speeds)
        third = max(1, n // 3)
        early_spd = sum(speeds[:third]) / third
        late_spd = sum(speeds[-third:]) / third
        spd_change = ((late_spd - early_spd) / early_spd) * 100 if early_spd > 0 else 0

        if abs(spd_change) > 2.0:
            trend = "improving" if spd_change > 0 else "degrading"
            detail = f"Top speed {'increased' if spd_change > 0 else 'decreased'} by {abs(spd_change):.1f}%."
        else:
            trend = "stable"
            detail = "Top speed remained consistent across the stint."

        insights.append(ProgressionInsight(
            metric="top_speed",
            trend=trend,
            detail=detail,
            early_value=early_spd,
            late_value=late_spd,
            change_pct=spd_change,
        ))

    return insights


# ---------------------------------------------------------------------------
# Drill generation
# ---------------------------------------------------------------------------

def _generate_drills(focus_areas: list[FocusArea]) -> list[Drill]:
    """Create practice drills targeting the top focus areas."""
    drills = []
    for rank, area in enumerate(focus_areas[:3], 1):
        template = _CATEGORY_DRILL.get(area.category, _CATEGORY_DRILL["consistency"])
        drills.append(Drill(
            rank=rank,
            title=template["title"],
            description=template["description"],
            focus_corners=area.corner_ids[:4],
            target_metric=template["target_metric"],
            target_improvement=template["target_improvement"],
            lap_count=5 if rank == 1 else 3,
        ))
    return drills


# ---------------------------------------------------------------------------
# Narrative generation
# ---------------------------------------------------------------------------

def _generate_narrative(
    theme: str,
    scores: dict[str, Any],
    focus_areas: list[FocusArea],
    progression: list[ProgressionInsight],
    coaching_v2: Optional[dict[str, Any]],
    driving_style: Optional[dict[str, Any]],
    corner_count: int,
) -> str:
    """Build a multi-sentence debrief narrative."""
    parts = [theme]

    # Score summary
    total = scores.get("total_score", 0)
    sub = scores.get("sub_scores", {})
    pace = sub.get("pace", {}).get("score", 0)
    consistency = sub.get("consistency", {}).get("score", 0)
    execution = sub.get("execution", {}).get("score", 0)
    robustness = sub.get("robustness", {}).get("score", 0)

    parts.append(
        f"Scored {total}/100 (Pace {pace}/25, Consistency {consistency}/25, "
        f"Execution {execution}/25, Robustness {robustness}/25) "
        f"across {corner_count} corners."
    )

    # Driving style context
    if driving_style:
        label = driving_style.get("style_label", "")
        conf = driving_style.get("style_confidence", 0)
        if label and conf > 0.3:
            parts.append(f"Driving style classified as '{label}' (confidence {conf:.0%}).")

    # Progression context
    time_prog = next((p for p in progression if p.metric == "lap_time_s"), None)
    if time_prog:
        parts.append(time_prog.detail)

    # Top focus area
    if focus_areas:
        top = focus_areas[0]
        total_loss = sum(fa.time_loss_s for fa in focus_areas)
        pct = (top.time_loss_s / total_loss * 100) if total_loss > 0 else 0
        parts.append(
            f"Primary time loss: {top.category.replace('_', ' ')} "
            f"({top.time_loss_s:.3f}s, {pct:.0f}% of total). {top.advice}"
        )

    # Coaching V2 summary
    if coaching_v2:
        n_confirm = len(coaching_v2.get("confirmations", []))
        n_correct = len(coaching_v2.get("corrections", []))
        if n_confirm > 0:
            parts.append(f"{n_confirm} corners executed well — maintain these strengths.")
        if n_correct > 0:
            parts.append(f"{n_correct} corners identified for improvement.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Strengths / weaknesses extraction
# ---------------------------------------------------------------------------

def _extract_strengths_weaknesses(
    scores: dict[str, Any],
    coaching_v2: Optional[dict[str, Any]],
    focus_areas: list[FocusArea],
    driving_style: Optional[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Extract human-readable strengths and weaknesses."""
    strengths: list[str] = []
    weaknesses: list[str] = []

    sub = scores.get("sub_scores", {})

    # Score-based
    for name, label in [("pace", "Pace"), ("consistency", "Consistency"),
                         ("execution", "Execution"), ("robustness", "Robustness")]:
        s = sub.get(name, {}).get("score", 0)
        pct = sub.get(name, {}).get("pct", (s / 25 * 100) if s else 0)
        if pct >= 80:
            strengths.append(f"{label} is excellent ({s}/25)")
        elif pct < 50:
            weaknesses.append(f"{label} needs work ({s}/25)")

    # Coaching V2 confirmations
    if coaching_v2:
        for conf in coaching_v2.get("confirmations", [])[:3]:
            text = conf.get("text", "")
            if text:
                strengths.append(text)

    # Driving style strengths
    if driving_style:
        for s in (driving_style.get("strengths") or [])[:2]:
            if s and s not in strengths:
                strengths.append(s)

    # Focus area weaknesses
    for fa in focus_areas[:3]:
        weaknesses.append(fa.summary)

    return strengths[:5], weaknesses[:5]


# ---------------------------------------------------------------------------
# Next session goals
# ---------------------------------------------------------------------------

def _generate_goals(
    focus_areas: list[FocusArea],
    coaching_v2: Optional[dict[str, Any]],
    scores: dict[str, Any],
) -> list[str]:
    """Generate 3 actionable goals for the next session."""
    goals: list[str] = []

    # From coaching V2 objectives
    if coaching_v2:
        for obj in coaching_v2.get("objectives", [])[:2]:
            text = obj.get("text", "")
            if text:
                goals.append(text)

    # From focus areas
    for fa in focus_areas:
        if len(goals) >= 3:
            break
        goal = f"Reduce {fa.category.replace('_', ' ')} time loss by 50% ({fa.time_loss_s:.3f}s → {fa.time_loss_s / 2:.3f}s)"
        if goal not in goals:
            goals.append(goal)

    # Consistency goal if CV is high
    sub = scores.get("sub_scores", {})
    consistency_pct = sub.get("consistency", {}).get("pct", 100)
    if consistency_pct < 60 and len(goals) < 3:
        goals.append("Improve lap-to-lap consistency — target <1.5% coefficient of variation")

    return goals[:3]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_session_coaching(
    *,
    corners: list[dict[str, Any]],
    coaching_v2: Optional[dict[str, Any]] = None,
    scores: Optional[dict[str, Any]] = None,
    lap_metrics: Optional[list[dict[str, Any]]] = None,
    driving_style: Optional[dict[str, Any]] = None,
) -> SessionCoaching:
    """Generate a comprehensive coaching debrief for a session.

    Parameters
    ----------
    corners : list
        Corner performance data (from ``/corners`` endpoint or pipeline).
    coaching_v2 : dict, optional
        Structured coaching output from ``generate_coaching_v2()``.
    scores : dict, optional
        Session scores with ``total_score``, ``grade``, ``sub_scores``.
    lap_metrics : list, optional
        Per-lap metrics for progression analysis.
    driving_style : dict, optional
        Driving style classification result.

    Returns
    -------
    SessionCoaching
        Complete coaching output with narrative, drills, and goals.
    """
    scores = scores or {"total_score": 0, "grade": "?", "sub_scores": {}}

    # 1. Aggregate focus areas from corner data
    focus_areas = _aggregate_focus_areas(corners)

    # 2. Analyze lap-to-lap progression
    progression = _analyze_progression(lap_metrics or [])

    # 3. Classify session theme
    theme = _classify_session_theme(scores, focus_areas, progression)

    # 4. Generate narrative
    narrative = _generate_narrative(
        theme, scores, focus_areas, progression,
        coaching_v2, driving_style, len(corners),
    )

    # 5. Extract strengths and weaknesses
    strengths, weaknesses = _extract_strengths_weaknesses(
        scores, coaching_v2, focus_areas, driving_style,
    )

    # 6. Generate practice drills
    drills = _generate_drills(focus_areas)

    # 7. Generate next session goals
    goals = _generate_goals(focus_areas, coaching_v2, scores)

    # 8. Calculate confidence
    confidence = 1.0
    if not coaching_v2:
        confidence -= 0.2
    if not lap_metrics or len(lap_metrics) < 3:
        confidence -= 0.2
    if not driving_style:
        confidence -= 0.1
    if len(corners) < 3:
        confidence -= 0.3
    confidence = max(0.1, confidence)

    return SessionCoaching(
        session_theme=theme,
        narrative=narrative,
        strengths=strengths,
        weaknesses=weaknesses,
        focus_areas=focus_areas,
        drills=drills,
        progression=progression,
        next_session_goals=goals,
        confidence=confidence,
    )
