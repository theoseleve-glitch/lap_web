"""Session composer — assembles full SessionCoaching from corner analyses.

Orchestration order:
1. corner_composer for each corner → CornerCoachingDetail list
2. Rank by cascade time loss
3. Build focus areas from top causes
4. focus_limiter → max 2 primary + deferred
5. Select drills matching focus area causes
6. confidence_framer → rewrite strengths/weaknesses
7. progressive_coach → 3 goals + warm-up + late apex reset
8. Select narrative + mental imagery
"""
from __future__ import annotations

import math
import statistics
from typing import Any

from coaching.models import (
    CornerCoachingDetail, Drill, FocusArea, ProgressionInsight,
    SessionCoaching, WarmUpProtocol,
)
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.composers.corner_composer import compose_corner_coaching
from coaching.composers.focus_limiter import limit_focus_areas
from coaching.composers.progressive_coach import (
    generate_warm_up, generate_next_session_goals, generate_late_apex_reset,
)
from coaching.composers.confidence_framer import reframe_strengths
from coaching.templates.drills import DRILL_LIBRARY
from coaching.templates.narratives import SESSION_NARRATIVES
from coaching.templates.mental_imagery import MENTAL_IMAGERY


def compose_session_coaching(
    corner_perfs: list[dict],
    coaching_v2: dict | None,
    scores: dict,
    lap_metrics: list | None,
    driving_style: dict | None,
    analyzer_results: dict,
    taxonomy: CauseTaxonomy,
    vehicle_class: str = "car",
    driver_history: dict | None = None,
    previous_goals: list[str] | None = None,
    corner_diagnosis: dict | None = None,
) -> SessionCoaching:
    """Assemble the full V3 coaching output for a session.

    `corner_diagnosis`, when given, is the classifier's raw per-LAP
    per-corner grid (`{lap_str: {corner_str: {"label", "confidence"}}}` — see
    `coaching.corner_diagnosis.classify_all_corners` /
    `pipeline.stages.s10h_diagnosis`). It is collapsed to one aggregated cell
    per corner via `_aggregate_corner_diagnosis` and threaded into
    `compose_corner_coaching` as `diagnosis=`. `None` (no classifier run, or
    nothing to diagnose) preserves Phase-1 behavior exactly.
    """

    # ── 1. Build per-corner coaching ──
    corner_coaching: list[CornerCoachingDetail] = []
    for cp in corner_perfs:
        cid = cp["corner_id"]
        trail = _get_for_corner(analyzer_results.get("trail_brakes"), cid)
        traction = _get_for_corner(analyzer_results.get("traction_budgets"), cid)
        cascade = _get_for_corner(analyzer_results.get("exit_cascades"), cid)
        symptoms = _get_for_corner(analyzer_results.get("symptoms"), cid)
        lifts = _get_lifts_for_corner(analyzer_results.get("throttle_lifts"), cid)
        wt = _get_for_corner(analyzer_results.get("weight_transfers"), cid)
        diagnosis = _aggregate_corner_diagnosis(corner_diagnosis, cid, lap_metrics)

        detail = compose_corner_coaching(
            corner_perf=cp,
            trail_brake=trail,
            traction=traction,
            exit_cascade=cascade,
            symptoms=symptoms,
            throttle_lifts=lifts,
            weight_transfer=wt,
            taxonomy=taxonomy,
            vehicle_class=vehicle_class,
            driver_history=driver_history,
            diagnosis=diagnosis,
        )
        corner_coaching.append(detail)

    # ── 2. Sort by cascade time loss (descending) ──
    corner_coaching.sort(key=lambda c: c.time_loss_cascade_s, reverse=True)

    # ── 3. Build focus areas from top causes ──
    raw_focus = _build_focus_areas(corner_coaching)

    # ── 4. Limit to max 2 ──
    primary_areas, deferred_areas = limit_focus_areas(raw_focus)

    # ── 5. Select drills ──
    drills = _select_drills(primary_areas, corner_coaching, vehicle_class)

    # ── 6. Strengths/weaknesses ──
    raw_strengths = scores.get("strengths", []) or []
    raw_weaknesses = scores.get("weaknesses", []) or []
    root_causes = [fa.category for fa in primary_areas]
    corner_names = []
    for fa in primary_areas:
        for cid in fa.corner_ids[:1]:
            corner_names.append(f"T{cid}")

    strengths, weaknesses = reframe_strengths(
        raw_strengths, raw_weaknesses, root_causes, corner_names or None,
    )

    # ── 7. Progressive coaching ──
    warm_up = generate_warm_up(primary_areas, vehicle_class)
    goals = generate_next_session_goals(primary_areas)
    late_apex = generate_late_apex_reset(
        [c.trend for c in corner_coaching if c.trend],
    )

    # ── 8. Narrative + theme ──
    grade = scores.get("grade", "C")
    narrative_subs = _build_narrative_subs(
        vehicle_class, primary_areas, strengths, weaknesses, lap_metrics,
    )
    session_theme, narrative = _pick_narrative(grade, primary_areas, narrative_subs)

    # ── 9. Mental imagery ──
    imagery_prompts = _pick_mental_imagery(primary_areas)

    # ── 10. Progression from lap metrics ──
    progression = _build_progression(lap_metrics)

    # ── 11. Confidence score ──
    total_score = scores.get("total_score", 50)
    confidence = min(1.0, total_score / 100.0)

    # ── 12. Collect physics summaries ──
    trail_brakes = [c.trail_brake for c in corner_coaching if c.trail_brake]
    traction_budgets = [c.traction_budget for c in corner_coaching if c.traction_budget]
    exit_cascades = [c.exit_cascade for c in corner_coaching if c.exit_cascade]

    return SessionCoaching(
        session_theme=session_theme,
        narrative=narrative,
        strengths=strengths,
        weaknesses=weaknesses,
        focus_areas=primary_areas,
        drills=drills,
        progression=progression,
        next_session_goals=goals,
        confidence=confidence,
        corner_coaching=corner_coaching,
        trail_brake_assessment=trail_brakes if trail_brakes else None,
        traction_budgets=traction_budgets if traction_budgets else None,
        exit_speed_cascades=exit_cascades if exit_cascades else None,
        warm_up_protocol=warm_up,
        vehicle_class=vehicle_class,
        deferred_focus_areas=deferred_areas if deferred_areas else None,
        late_apex_reset=late_apex,
        mental_imagery_prompts=imagery_prompts if imagery_prompts else None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_for_corner(items: list | dict | None, corner_id: int):
    """Extract analyzer result for a specific corner from a list or dict."""
    if items is None:
        return None
    if isinstance(items, dict):
        return items.get(corner_id)
    if isinstance(items, list):
        for item in items:
            cid = getattr(item, "corner_id", None)
            if cid is None and isinstance(item, dict):
                cid = item.get("corner_id")
            if cid == corner_id:
                return item
    return None


def _best_lap_number(lap_metrics: list | None) -> int | None:
    """Identify the driver's best (fastest, finite-time) lap number from
    `lap_metrics`, if lap-level data with an identifiable lap_number + time is
    available. Returns `None` when it isn't — callers then fall back to modal
    aggregation across all laps instead of a single representative one."""
    if not lap_metrics:
        return None

    best_num = None
    best_time = None
    for lm in lap_metrics:
        if not isinstance(lm, dict):
            continue
        lap_num = lm.get("lap_number")
        lap_time = lm.get("lap_time_s")
        if lap_time is None:
            lap_time = lm.get("lap_time")
        if lap_num is None or lap_time is None:
            continue
        try:
            lap_time = float(lap_time)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(lap_time):
            continue
        if best_time is None or lap_time < best_time:
            best_time = lap_time
            best_num = lap_num

    return best_num


def _aggregate_corner_diagnosis(
    corner_diagnosis: dict | None,
    corner_id: int,
    lap_metrics: list | None,
) -> dict | None:
    """Collapse the classifier's per-LAP per-corner grid to one cell for
    *corner_id* — the shape `compose_corner_coaching` (-> `_resolve_cause`)
    consumes.

    Aggregation (documented per the P2-Task-5 design):
    1. BEST LAP: if a best/representative lap is identifiable from
       `lap_metrics` (`_best_lap_number` — the fastest lap with a finite
       time) AND that lap has a recorded cell for this corner, use that cell
       as-is. It's the single most representative sample of how the driver
       actually took the corner on their best effort, so no further
       aggregation across other laps is needed.
    2. MODAL FALLBACK: otherwise (no identifiable best lap, or that lap has
       no cell for this corner — e.g. metrics extraction failed for it),
       fall back to the most-frequent ("modal") non-None/non-"good" label
       across every lap that has a cell for this corner. The returned
       `confidence` is "high" only when a MAJORITY (>50%) of the laps
       carrying that modal label recorded it "high" — one lucky high-
       confidence read surrounded by low-confidence noise should not be
       enough to override the metric-based branches.
    Returns `None` when there is nothing to aggregate: no map, no cells for
    this corner, or every recorded cell is "good" (no issue) / label-less.
    """
    if not corner_diagnosis:
        return None

    corner_key = str(corner_id)
    cells: list[tuple[str, dict]] = []
    for lap_key, corner_map in corner_diagnosis.items():
        if not isinstance(corner_map, dict):
            continue
        cell = corner_map.get(corner_key)
        if cell and cell.get("label"):
            cells.append((str(lap_key), cell))

    if not cells:
        return None

    # 1. Best/representative lap, if identifiable.
    best_lap_num = _best_lap_number(lap_metrics)
    if best_lap_num is not None:
        match = next((cell for lap_key, cell in cells if lap_key == str(best_lap_num)), None)
        if match is not None:
            if match["label"] == "good":
                return None
            return {"label": match["label"], "confidence": match.get("confidence", "low")}
        # No cell for the best lap on this corner -- fall through to modal.

    # 2. Modal fallback across non-"good" labels.
    non_good = [cell for _, cell in cells if cell["label"] != "good"]
    if not non_good:
        return None

    by_label: dict[str, list[dict]] = {}
    for cell in non_good:
        by_label.setdefault(cell["label"], []).append(cell)

    modal_label = max(by_label, key=lambda lbl: len(by_label[lbl]))
    modal_cells = by_label[modal_label]
    high_count = sum(1 for c in modal_cells if c.get("confidence") == "high")
    confidence = "high" if high_count > len(modal_cells) / 2 else "low"

    return {"label": modal_label, "confidence": confidence}


def _get_lifts_for_corner(items: list | dict | None, corner_id: int) -> list:
    """Extract all throttle lift events for a corner."""
    if items is None:
        return []
    if isinstance(items, dict):
        result = items.get(corner_id)
        return result if isinstance(result, list) else ([result] if result else [])
    if isinstance(items, list):
        return [
            item for item in items
            if (getattr(item, "corner_id", None) == corner_id
                or (isinstance(item, dict) and item.get("corner_id") == corner_id))
        ]
    return []


def _build_focus_areas(corner_coaching: list[CornerCoachingDetail]) -> list[FocusArea]:
    """Group corners by primary_cause category, sum time losses, build FocusAreas."""
    cause_groups: dict[str, dict] = {}

    for cc in corner_coaching:
        cat = cc.cause_root  # e.g. "technique", "confidence"
        if cat not in cause_groups:
            cause_groups[cat] = {
                "category": cat,
                "time_loss_s": 0.0,
                "corner_ids": [],
                "summaries": [],
                "steps": [],
            }
        cause_groups[cat]["time_loss_s"] += cc.time_loss_cascade_s
        cause_groups[cat]["corner_ids"].append(cc.corner_id)
        if cc.coaching_tip and len(cause_groups[cat]["summaries"]) < 2:
            cause_groups[cat]["summaries"].append(cc.coaching_tip[:120])
        if cc.progressive_steps and not cause_groups[cat]["steps"]:
            cause_groups[cat]["steps"] = cc.progressive_steps

    # Sort by total time loss
    sorted_groups = sorted(cause_groups.values(), key=lambda g: g["time_loss_s"], reverse=True)

    areas = []
    for rank, group in enumerate(sorted_groups, 1):
        summary = "; ".join(group["summaries"]) if group["summaries"] else f"{group['category']} issues"
        areas.append(FocusArea(
            rank=rank,
            category=group["category"],
            time_loss_s=group["time_loss_s"],
            corner_ids=group["corner_ids"],
            summary=summary,
            advice=f"Focus on {group['category']} improvements.",
            progressive_steps=group["steps"] if group["steps"] else None,
        ))

    return areas


def _select_drills(
    focus_areas: list[FocusArea],
    corner_coaching: list[CornerCoachingDetail],
    vehicle_class: str,
) -> list[Drill]:
    """Select 2-4 drills matching focus area causes."""
    # Collect primary causes from the focus area corners
    target_causes = set()
    focus_corner_ids = set()
    for fa in focus_areas:
        target_causes.add(fa.category)
        focus_corner_ids.update(fa.corner_ids)

    # Also add specific cause_ids from corner coaching
    for cc in corner_coaching:
        if cc.corner_id in focus_corner_ids:
            target_causes.add(cc.primary_cause)

    selected: list[Drill] = []
    rank = 1

    for drill_id, drill_data in DRILL_LIBRARY.items():
        if rank > 4:
            break
        applicable = set(drill_data.get("applicable_causes", []))
        if applicable & target_causes:
            # Pick difficulty based on focus area count
            difficulty = "beginner" if len(focus_areas) >= 2 else "intermediate"
            level = drill_data["difficulty_levels"].get(difficulty, {})

            selected.append(Drill(
                rank=rank,
                title=drill_data["title"],
                description=level.get("description", drill_data["title"]),
                focus_corners=list(focus_corner_ids)[:5],
                target_metric=drill_data.get("applicable_causes", ["general"])[0],
                target_improvement=level.get("success_criteria", "Improve consistency"),
                lap_count=level.get("lap_count", 5),
                difficulty=difficulty,
                success_criteria=level.get("success_criteria"),
                difficulty_progression=drill_data["difficulty_levels"],
            ))
            rank += 1

    # Guarantee at least 1 drill
    if not selected:
        selected.append(Drill(
            rank=1,
            title="General Consistency Drill",
            description="Focus on repeating the same line and inputs for 5 laps.",
            focus_corners=list(focus_corner_ids)[:3] or [1],
            target_metric="consistency",
            target_improvement="Reduce lap time variance",
            lap_count=5,
        ))

    return selected


class _SafeDict(dict):
    """dict for str.format_map that degrades a missing key to an em-dash
    instead of raising KeyError (which would otherwise force callers to fall
    back to the raw, un-rendered template and leak a literal `{token}`)."""

    def __missing__(self, key):
        return "—"


def _build_narrative_subs(
    vehicle_class: str,
    primary_areas: list[FocusArea],
    strengths: list[str],
    weaknesses: list[str],
    lap_metrics: list | None,
) -> dict:
    """Assemble real substitution values for SESSION_NARRATIVES templates.

    Only ever includes a key when a genuine measured/derived value backs it.
    `_pick_narrative` renders with `_SafeDict`, so any token a chosen variant
    needs but that isn't backed by real data here degrades to an em-dash
    rather than a fabricated number — no-fabrication rule.
    """
    subs: dict = {"vehicle_class": vehicle_class}

    if primary_areas:
        # Real, already-computed cascade time loss for the top focus area —
        # not a fabricated stand-in for "gap to theoretical".
        subs["time_delta_s"] = primary_areas[0].time_loss_s
        subs["corner_count"] = len(primary_areas[0].corner_ids)

    if strengths:
        subs["primary_strength"] = strengths[0]
    if weaknesses:
        subs["primary_weakness"] = weaknesses[0]

    lap_times = [
        float(lm.get("lap_time_s") or lm.get("lap_time"))
        for lm in (lap_metrics or [])
        if isinstance(lm, dict) and (lm.get("lap_time_s") or lm.get("lap_time")) is not None
    ]
    if len(lap_times) >= 2:
        subs["std_dev_s"] = statistics.pstdev(lap_times)
        subs["clean_laps"] = len(lap_times)

    return subs


def _pick_narrative(
    grade: str, focus_areas: list[FocusArea], subs: dict,
) -> tuple[str, str]:
    """Select, then RENDER, the session theme and narrative from templates."""
    if grade in ("S", "A"):
        band = "S-A"
    elif grade in ("B", "C"):
        band = "B-C"
    else:
        band = "D-F"

    # Pick theme based on top focus area
    theme = "general"
    if focus_areas:
        cat = focus_areas[0].category
        theme_map = {
            "technique": "technique", "confidence": "consistency",
            "line": "technique", "aggression": "pace",
            "awareness": "consistency", "balance": "technique",
        }
        theme = theme_map.get(cat, "general")

    # A "consistency" narrative needs a real std_dev_s, rendered with a
    # numeric format spec ({std_dev_s:.2f}) — a missing value can't safely
    # degrade to an em-dash there (format spec would crash on a string).
    # Without lap-level data to compute a real one, tell an honest general
    # story instead of fabricating a variance figure.
    if theme == "consistency" and "std_dev_s" not in subs:
        theme = "general"

    key = (band, theme)
    variants = SESSION_NARRATIVES.get(key)
    if not variants:
        # Fallback to general for this band
        variants = SESSION_NARRATIVES.get((band, "general"), ["Good session overall."])

    narrative = variants[0].format_map(_SafeDict(subs))

    # Theme headline
    theme_headlines = {
        "S-A": "Exceptional Session",
        "B-C": "Solid Foundation",
        "D-F": "Building Blocks",
    }
    session_theme = theme_headlines.get(band, "Session Review")

    return session_theme, narrative


def _pick_mental_imagery(focus_areas: list[FocusArea]) -> list[str]:
    """Select 1-2 mental imagery scripts matching focus areas."""
    prompts = []
    # Map categories to imagery themes
    cat_to_imagery = {
        "confidence": "braking_confidence",
        "technique": "trail_braking",
        "line": "cornering_flow",
        "aggression": "exit_speed",
        "awareness": "consistency_focus",
        "balance": "weight_transfer",
        "fear": "braking_confidence",
    }

    seen = set()
    for fa in focus_areas[:2]:
        imagery_key = cat_to_imagery.get(fa.category, "consistency_focus")
        if imagery_key not in seen and imagery_key in MENTAL_IMAGERY:
            seen.add(imagery_key)
            entry = MENTAL_IMAGERY[imagery_key]
            prompts.append(entry.get("in_session", entry.get("pre_session", "")))

    return prompts


def _build_progression(lap_metrics: list | None) -> list[ProgressionInsight]:
    """Extract lap-to-lap progression from metrics if available."""
    if not lap_metrics or len(lap_metrics) < 3:
        return []

    insights = []
    # Check lap time trend
    lap_times = []
    for lm in lap_metrics:
        if isinstance(lm, dict):
            lt = lm.get("lap_time_s") or lm.get("lap_time")
            if lt is not None:
                lap_times.append(float(lt))

    if len(lap_times) >= 3:
        early = sum(lap_times[:3]) / 3
        late = sum(lap_times[-3:]) / 3
        change_pct = (late - early) / early * 100 if early > 0 else 0.0

        if change_pct < -1:
            trend = "improving"
            detail = f"Lap times improved by {abs(change_pct):.1f}% through the session"
        elif change_pct > 2:
            trend = "degrading"
            detail = f"Lap times degraded by {change_pct:.1f}% — potential tyre wear or fatigue"
        else:
            trend = "stable"
            detail = "Consistent pace throughout the session"

        insights.append(ProgressionInsight(
            metric="lap_time",
            trend=trend,
            detail=detail,
            early_value=early,
            late_value=late,
            change_pct=change_pct,
        ))

    return insights
