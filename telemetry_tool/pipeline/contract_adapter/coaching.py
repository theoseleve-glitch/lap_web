"""Build a CoachingContract from a real-life pipeline summary.

Flow:
    summary  ->  prescriptive.engine.generate_coaching_sheet()  ->  CoachingSheet
    CoachingSheet  ->  (reshape helpers, F5-F7)                 ->  CoachingContract

The prescriptive engine is invoked on demand because the current pipeline
does not include a prescriptive stage. We could add one (one new stage at
the end of orchestrator.run_full_analysis) but that touches pipeline code
the session brief declares out of scope -- so we keep the invocation inside
the adapter.

Engine signature (from track_surface.prescriptive.engine):
    generate_coaching_sheet(*, corner_packets, weaknesses,
                             sessions_analyzed, laps_analyzed, registry=None)

When the summary does not carry `corner_packets` or `weaknesses`, we
fall back to `CoachingSheet.empty(...)` so the contract is always valid.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from telemetry_tool.web.schemas.contracts import CoachingContract
from telemetry_tool.web.schemas.contracts.coaching import (
    CornerCoachingItem,
    CornerCueItem,
    FocusItem,
    NextRunItem,
    StorylineItem,
    ValidationCheck,
)

logger = logging.getLogger(__name__)

# F5 mapping -- CoachingSheet.StorylineEntry.type -> CoachingContract state
_STATE_MAP = {
    "primary_focus": "Detected",
    "progress": "NotTriggered",
    "plateau": "NotTriggered",
    "data_warning": "Insufficient",
    "insufficient_data": "Insufficient",
    "unregistered_weakness": "Unregistered",
}


def _reshape_global_focus(items: Iterable[Any]) -> list[FocusItem]:
    return [
        FocusItem(
            rank=int(it.rank),
            weakness_key=str(it.weakness_key),
            title=str(it.title),
            severity=it.severity,
            corner_ids=[str(c) for c in (it.corners or ())],
            cost_ms=float(it.estimated_cost_ms) if it.estimated_cost_ms is not None else None,
        )
        for it in (items or ())
    ]


def _reshape_storyline(
    entries: Iterable[Any],
    focus_items: list[FocusItem],
) -> list[StorylineItem]:
    out: list[StorylineItem] = []
    focus_by_rank = {f.rank: f for f in focus_items}
    for idx, e in enumerate(entries or (), start=1):
        t = str(e.type)
        state = _STATE_MAP.get(t, "NotTriggered")
        if state == "Detected" and 1 in focus_by_rank:
            wkey = focus_by_rank[1].weakness_key
        else:
            wkey = f"storyline_{idx}"
        detail = None if t in _STATE_MAP else t  # preserve unknown type as detail
        out.append(StorylineItem(
            weakness_key=wkey,
            state=state,
            headline=str(e.text),
            detail=detail,
        ))
    return out


def _reshape_corner_coaching(
    corners: Iterable[Any],
    playbook_matches: Iterable[Any],
) -> dict[str, CornerCoachingItem]:
    pm_by_key = {pm.weakness_key: pm for pm in (playbook_matches or ())}
    out: dict[str, CornerCoachingItem] = {}
    for cc in corners or ():
        cid = str(cc.corner_id)
        cues: list[CornerCueItem] = []
        for wkey in (cc.applicable_weaknesses or ()):
            pm = pm_by_key.get(wkey)
            cue_text = (
                str(pm.driver_cues[0])
                if (pm and pm.driver_cues)
                else str(getattr(cc, "summary", "") or "")
            )
            severity = (pm.severity if pm else "medium")
            cues.append(CornerCueItem(
                weakness_key=str(wkey),
                phase="brake_release",  # default; domain corner_coaching has no phase
                severity=severity,
                cue_text=cue_text,
                cost_ms=None,
            ))
        out[cid] = CornerCoachingItem(corner_id=cid, items=cues)
    return out


def _reshape_validation_checks(vcs: Iterable[Any]) -> list[ValidationCheck]:
    out: list[ValidationCheck] = []
    for vc in vcs or ():
        corners = tuple(vc.corners or ())
        cid = str(corners[0]) if len(corners) == 1 else None
        out.append(ValidationCheck(
            check_id=f"{vc.weakness_key}:{vc.metric_name}",
            description=str(vc.metric_name),
            measurable_target=(str(vc.target_description) if vc.target_description else None),
            corner_id=cid,
        ))
    return out


def _reshape_next_run(items: Iterable[Any]) -> list[NextRunItem]:
    return [
        NextRunItem(
            item_type=it.type,  # already a Literal on the domain side
            title=str(it.title),
            body=(
                f"{it.instruction} / {it.validation}"
                if getattr(it, "validation", None)
                else str(it.instruction)
            ),
            weakness_key=None,  # not carried by domain NextRunItem
        )
        for it in (items or ())
    ]


def _not_evaluable(summary: dict[str, Any], coached_ids: set[str]) -> list[str]:
    """F7: corners known to the pipeline but absent from the coaching sheet."""
    all_corners = summary.get("corners") or []
    all_ids: set[str] = set()
    for c in all_corners:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        if cid is not None:
            all_ids.add(str(cid))
    return sorted(all_ids - coached_ids)


def _empty_sheet(reason: str):
    from track_surface.prescriptive.types import CoachingSheet, Limits
    return CoachingSheet.empty(Limits(
        sessions_analyzed=0, laps_analyzed=0,
        brake_data=reason, throttle_data="n/a", steering_data="n/a",
        cross_track_portability="n/a", weather_conditions="n/a",
        reference_basis="n/a", confidence_floor="n/a",
    ))


def _invoke_prescriptive_engine(summary: dict[str, Any]):
    """F4: delegate to the prescriptive engine.

    Engine wants `corner_packets` + `weaknesses` lists. We read those from
    `summary["corner_packets"]` and `summary["weaknesses"]`; if either is
    missing the adapter returns an empty sheet rather than guessing the
    upstream shape.
    """
    try:
        from track_surface.prescriptive.engine import generate_coaching_sheet
    except Exception:
        logger.warning("prescriptive engine unavailable", exc_info=True)
        return _empty_sheet("engine_unavailable")

    corner_packets = summary.get("corner_packets")
    weaknesses = summary.get("weaknesses")
    if corner_packets is None and weaknesses is None:
        # Pipeline didn't materialize prescriptive inputs yet.
        return _empty_sheet("no_prescriptive_inputs")

    laps_analyzed = len([
        t for t in (summary.get("lap_times") or [])
        if isinstance(t, (int, float)) and t > 0
    ])
    try:
        return generate_coaching_sheet(
            corner_packets=corner_packets or [],
            weaknesses=weaknesses or [],
            sessions_analyzed=1,
            laps_analyzed=laps_analyzed,
        )
    except Exception:
        logger.exception("prescriptive engine raised")
        return _empty_sheet("engine_error")


def build_coaching_contract(
    summary: dict[str, Any],
    *,
    sheet: Any = None,
) -> CoachingContract:
    """Produce a CoachingContract. `sheet` is injectable for testing."""
    sheet = sheet if sheet is not None else _invoke_prescriptive_engine(summary)
    focus = _reshape_global_focus(getattr(sheet, "global_focus", ()))
    corner_cc = _reshape_corner_coaching(
        getattr(sheet, "corner_coaching", ()),
        getattr(sheet, "weakness_playbook_matches", ()),
    )
    return CoachingContract(
        version=getattr(sheet, "version", "1.0"),
        storyline=_reshape_storyline(getattr(sheet, "storyline", ()), focus),
        global_focus=focus,
        corner_coaching=corner_cc,
        not_evaluable_corners=_not_evaluable(summary, set(corner_cc.keys())),
        validation_checks=_reshape_validation_checks(getattr(sheet, "validation_checks", ())),
        next_run=_reshape_next_run(getattr(sheet, "next_run_plan", ())),
    )
