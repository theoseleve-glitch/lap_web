"""
track_surface.prescriptive.engine
=================================

Coaching engine — orchestrates registry + contexts + evidence into a
``CoachingSheet``.

Two public entry points:

    - ``run(registry, contexts, evidence, *, sessions_analyzed, laps_analyzed)``
      Low-level — takes internal research types. Used by tests and by
      callers that already hold ``WeaknessContext`` / ``Evidence`` instances.

    - ``generate_coaching_sheet(*, corner_packets, weaknesses, sessions_analyzed,
      laps_analyzed, registry=None)``
      High-level facade — takes the same upstream dict shapes the legacy
      ``generate_prescriptive_coaching`` accepts. This is what Phase-3's
      ``build_ok_raw.py`` swap will call.

Behaviour preserves legacy ``generate_prescriptive_coaching`` semantics
wherever evidence is complete, with three DESIGN DELTAS the brief requires:

    1. ``Unregistered`` weakness_keys (upstream keys the registry does not
       know) are surfaced via ``storyline[type='unregistered_weakness']``.
       Legacy silently dropped them at line 231.
    2. ``Insufficient`` patterns (required evidence absent) are surfaced
       via ``storyline[type='insufficient_data']`` with the specific
       missing fields named.
    3. ``Detected`` prescriptions carry ``not_evaluable_corners``, which
       the engine surfaces in per-corner summaries ("Data insufficient
       for: …") rather than omitting the corner.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Sequence

from track_surface.prescriptive._internal import (
    Detected,
    Evidence,
    Insufficient,
    PatternResult,
    Unregistered,
    WeaknessContext,
)
from track_surface.prescriptive.adapters import (
    context_list_from_weaknesses,
    evidence_list_from_packets,
)
from track_surface.prescriptive.patterns import build_default_registry
from track_surface.prescriptive.registry import PatternRegistry
from track_surface.prescriptive.types import (
    COACHING_SHEET_VERSION,
    CoachingSheet,
    CornerCoaching,
    FocusItem,
    Limits,
    NextRunItem,
    PlaybookMatch,
    StorylineEntry,
    ValidationCheck,
)


# Parity thresholds with legacy ``prescriptive_coaching.py``.
_CORNER_COACHING_DELTA_FLOOR_MS = 30.0   # line 368 of legacy
_VALIDATION_TARGET_CORNER_FLOOR_MS = 50.0  # line 453 of legacy
_MAX_PRIORITIES = 3                       # line 394+ of legacy
_SOURCE_TAG = "bronze_compare_plus_development_intelligence_only"


# ═══════════════════════════════════════════════════════════════
# Public entry points
# ═══════════════════════════════════════════════════════════════

def generate_coaching_sheet(
    *,
    corner_packets: Iterable[dict[str, Any]],
    weaknesses: Iterable[dict[str, Any]],
    sessions_analyzed: int,
    laps_analyzed: int,
    registry: PatternRegistry | None = None,
) -> CoachingSheet:
    """End-to-end: upstream dicts → ``CoachingSheet``.

    If ``registry`` is None, uses ``build_default_registry()`` (five built-ins).
    This is the facade Phase-3's ``build_ok_raw.py`` swap will call.
    """
    if registry is None:
        registry = build_default_registry()
    evidence = evidence_list_from_packets(corner_packets)
    contexts = context_list_from_weaknesses(
        weaknesses, sessions_analyzed=sessions_analyzed,
    )
    return run(
        registry, contexts, evidence,
        sessions_analyzed=sessions_analyzed,
        laps_analyzed=laps_analyzed,
    )


def run(
    registry: PatternRegistry,
    contexts: Sequence[WeaknessContext],
    evidence: Sequence[Evidence],
    *,
    sessions_analyzed: int,
    laps_analyzed: int,
) -> CoachingSheet:
    """Low-level engine entry. See module docstring for semantics."""
    limits = _build_limits(sessions_analyzed, laps_analyzed)

    # Empty-input short-circuit (parity with legacy line 565).
    if not evidence and not contexts:
        return CoachingSheet.empty(limits)

    evidence_by_corner: dict[int, Evidence] = {ev.corner_id: ev for ev in evidence}

    detected: list[Detected] = []
    insufficient: list[Insufficient] = []
    unregistered: list[Unregistered] = []

    for ctx in contexts:
        pattern = registry.get(ctx.key)
        if pattern is None:
            unregistered.append(Unregistered(weakness_key=ctx.key))
            continue
        scoped_evidence = [
            evidence_by_corner[cid]
            for cid in ctx.corners_observed
            if cid in evidence_by_corner
        ]
        result: PatternResult = pattern.evaluate(ctx, scoped_evidence)
        if isinstance(result, Detected):
            detected.append(result)
        elif isinstance(result, Insufficient):
            insufficient.append(result)
        # NotTriggered is silent in the published sheet.

    # Rank detected by cost_ms descending (parity with legacy line 577).
    detected.sort(key=lambda d: -d.cost_ms)

    return CoachingSheet(
        version=COACHING_SHEET_VERSION,
        source=_SOURCE_TAG,
        global_focus=tuple(_build_global_focus(detected)),
        corner_coaching=tuple(_build_corner_coaching(detected, evidence)),
        weakness_playbook_matches=tuple(_build_playbook_matches(detected)),
        next_run_plan=tuple(_build_next_run_plan(detected)),
        validation_checks=tuple(_build_validation_checks(detected, evidence)),
        storyline=tuple(_build_storyline(
            detected, insufficient, unregistered, sessions_analyzed,
        )),
        limits=limits,
    )


# ═══════════════════════════════════════════════════════════════
# Section builders
# ═══════════════════════════════════════════════════════════════

def _build_global_focus(detected: list[Detected]) -> list[FocusItem]:
    out: list[FocusItem] = []
    for i, d in enumerate(detected[:3]):
        out.append(FocusItem(
            rank=i + 1,
            weakness_key=d.weakness_key,
            title=d.title,
            severity=d.severity,
            estimated_cost_ms=round(d.cost_ms, 1),
            corners=d.affected_corners[:6],
            phase=d.phase,
            confidence=round(d.confidence, 2),
        ))
    return out


def _build_playbook_matches(detected: list[Detected]) -> list[PlaybookMatch]:
    return [
        PlaybookMatch(
            weakness_key=d.weakness_key,
            title=d.title,
            matched_playbook=True,
            corner_ids=d.affected_corners[:8],
            severity=d.severity,
            coaching_actions=d.coaching_actions,
            driver_cues=d.driver_cues,
            measurable_targets=d.measurable_targets,
            likely_causes=d.likely_causes,
            sensor_note=d.sensor_note,
            portability=d.portability,
            data_support=d.data_support,
        )
        for d in detected
    ]


def _build_corner_coaching(
    detected: list[Detected],
    evidence: Sequence[Evidence],
) -> list[CornerCoaching]:
    matches_by_corner: dict[int, list[str]] = defaultdict(list)
    for d in detected:
        for cid in d.affected_corners:
            matches_by_corner[cid].append(d.weakness_key)
    skipped_by_corner: dict[int, list[str]] = defaultdict(list)
    for d in detected:
        for cid in d.not_evaluable_corners:
            skipped_by_corner[cid].append(d.weakness_key)

    out: list[CornerCoaching] = []
    for ev in evidence:
        matching = matches_by_corner.get(ev.corner_id, [])
        skipped = skipped_by_corner.get(ev.corner_id, [])
        # Parity with legacy line 368: skip corners with no match AND
        # small time delta. NOTE: uses signed comparison (not abs) — so a
        # corner where the candidate is significantly FASTER is also
        # suppressed when unmatched. Legacy behaviour preserved.
        if not matching and not skipped and ev.time_delta_ms < _CORNER_COACHING_DELTA_FLOOR_MS:
            continue
        parts = [f"T{ev.corner_id}: {ev.time_delta_ms:+.0f} ms."]
        if matching:
            parts.append(f"Linked to: {', '.join(matching)}.")
        elif skipped:
            parts.append(f"Data insufficient for: {', '.join(skipped)}.")
        else:
            parts.append("No matched playbook.")
        out.append(CornerCoaching(
            corner_id=ev.corner_id,
            time_delta_ms=round(ev.time_delta_ms, 1),
            s_entry_m=ev.s_entry_m,
            s_exit_m=ev.s_exit_m,
            applicable_weaknesses=tuple(matching),
            primary_cause=ev.primary_cause,
            confidence=round(ev.confidence, 2),
            summary=" ".join(parts),
        ))
    return out


def _build_next_run_plan(detected: list[Detected]) -> list[NextRunItem]:
    if not detected:
        return []
    types_order = ("technical_focus", "execution_focus", "validation_metric")
    items: list[NextRunItem] = []
    for rank, d in enumerate(detected[:_MAX_PRIORITIES], start=1):
        type_tag = types_order[rank - 1]
        if type_tag == "validation_metric":
            instruction = (
                "Monitor only — do not actively change. "
                "Check if it improves passively."
            )
        else:
            instruction = (
                d.coaching_actions[0] if d.coaching_actions else "Review evidence."
            )
        validation = (
            d.measurable_targets[0] if d.measurable_targets else "Check time delta."
        )
        items.append(NextRunItem(
            rank=rank, type=type_tag, title=d.title,
            corners=d.affected_corners[:4],
            instruction=instruction, validation=validation,
        ))
    # Anti-overload — rank=0 by convention (parity with legacy line 427).
    items.append(NextRunItem(
        rank=0,
        type="anti_overload",
        title="Do not try to fix everything at once",
        corners=(),
        instruction=(
            f"Focus on \"{items[0].title}\" for the first 3–5 laps. "
            f"Only add the second focus if the first is stable. "
            f"The third item is monitor-only — just observe whether it changes."
        ),
        validation=(
            "If you are thinking about more than 2 things mid-corner, "
            "you are overloaded."
        ),
    ))
    return items[: _MAX_PRIORITIES + 1]


def _build_validation_checks(
    detected: list[Detected],
    evidence: Sequence[Evidence],
) -> list[ValidationCheck]:
    td_by_corner = {ev.corner_id: ev.time_delta_ms for ev in evidence}
    checks: list[ValidationCheck] = []
    for d in detected:
        for target in d.measurable_targets[:2]:
            best = sorted(
                cid for cid in d.affected_corners
                if td_by_corner.get(cid, 0.0) > _VALIDATION_TARGET_CORNER_FLOOR_MS
            )[:3]
            if not best:
                best = list(d.affected_corners[:3])
            metric_name = target.split(":")[0] if ":" in target else target[:40]
            checks.append(ValidationCheck(
                weakness_key=d.weakness_key,
                metric_name=metric_name,
                target_description=target,
                corners=tuple(best),
                measurement_method=d.sensor_note,
                confidence=round(d.confidence, 2),
            ))
    return checks


def _build_storyline(
    detected: list[Detected],
    insufficient: list[Insufficient],
    unregistered: list[Unregistered],
    sessions_analyzed: int,
) -> list[StorylineEntry]:
    entries: list[StorylineEntry] = []

    if detected:
        top = detected[0]
        entries.append(StorylineEntry(
            type="primary_focus",
            text=(
                f'The highest-value change right now is addressing '
                f'"{top.title}" — it costs ~{top.cost_ms:.0f} ms per '
                f'occurrence across {len(top.affected_corners)} corners and '
                f'is {top.severity} severity.'
            ),
            confidence=top.confidence,
        ))
        improving = [d for d in detected if "improving" in (d.data_support or "")]
        flat = [d for d in detected if "flat" in (d.data_support or "")]
        if improving:
            entries.append(StorylineEntry(
                type="progress",
                text=(
                    f"Already improving: "
                    f"{', '.join(d.title for d in improving[:2])}. "
                    f"Continue current approach on these."
                ),
                confidence=0.7,
            ))
        if flat:
            entries.append(StorylineEntry(
                type="plateau",
                text=(
                    f"Stalled: {', '.join(d.title for d in flat[:2])}. "
                    f"A technique change may be needed — current approach "
                    f"is not producing progress."
                ),
                confidence=0.6,
            ))

    if sessions_analyzed < 3:
        entries.append(StorylineEntry(
            type="data_warning",
            text=(
                f"Only {sessions_analyzed} session(s) analyzed. "
                f"Trend and portability claims need 3+ sessions to be reliable."
            ),
            confidence=1.0,
        ))

    # DESIGN DELTA: surface unregistered weakness keys.
    for u in unregistered:
        entries.append(StorylineEntry(
            type="unregistered_weakness",
            text=(
                f"Upstream reported weakness {u.weakness_key!r} but no "
                f"coaching playbook is registered for it — not surfaced in "
                f"prescriptions."
            ),
            confidence=1.0,
        ))

    # DESIGN DELTA: surface insufficient-data verdicts per weakness.
    for ins in insufficient:
        entries.append(StorylineEntry(
            type="insufficient_data",
            text=(
                f"Cannot evaluate {ins.weakness_key!r}: {ins.reason}. "
                f"Missing: {', '.join(ins.missing_fields)}."
            ),
            confidence=1.0,
        ))

    return entries


def _build_limits(sessions_analyzed: int, laps_analyzed: int) -> Limits:
    return Limits(
        sessions_analyzed=sessions_analyzed,
        laps_analyzed=laps_analyzed,
        brake_data=(
            "speed-derived deceleration proxy only (no brake pressure sensor)"
        ),
        throttle_data=(
            "speed-derived acceleration proxy only (no CAN throttle sensor)"
        ),
        steering_data=(
            "not available — rotation and commitment inferred from speed + line"
        ),
        cross_track_portability=(
            "unknown — all data is from a single track"
            if sessions_analyzed <= 10
            else "partially assessed"
        ),
        weather_conditions=(
            "not tracked — cannot separate grip from technique changes"
        ),
        reference_basis="session-overall best lap (not per-sector composite)",
        confidence_floor=(
            "Prescriptions with < 3 supporting occurrences are omitted. "
            "All stated confidence is relative to available evidence, "
            "not absolute."
        ),
    )
