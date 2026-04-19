"""
track_surface.prescriptive.serialization
========================================

Serialise a ``CoachingSheet`` into the public JSON dict.

This is the ONE place where published DTOs become dicts/lists. The shape
must remain identical to the output of legacy ``to_json_dict`` so that
``lap-studio-live.html`` and ``ouest-karting-live.html`` continue to work
without any frontend change during the Phase-3 producer swap.

Any change to the dict shape emitted here is a published-contract change
and requires a version bump of ``COACHING_SHEET_VERSION`` + ADR.
"""
from __future__ import annotations

from typing import Any

from track_surface.prescriptive.types import (
    CoachingSheet,
    CornerCoaching,
    FocusItem,
    Limits,
    NextRunItem,
    PlaybookMatch,
    StorylineEntry,
    ValidationCheck,
)


def to_json_dict(sheet: CoachingSheet) -> dict[str, Any]:
    """``CoachingSheet`` → JSON dict (the shape embedded in
    ``track-surface-ok-data.json``).

    Tuples become lists. All other field names and value types are
    preserved exactly as defined in the public DTOs.
    """
    return {
        "version": sheet.version,
        "source": sheet.source,
        "global_focus": [_focus_item(f) for f in sheet.global_focus],
        "corner_coaching": [_corner_coaching(c) for c in sheet.corner_coaching],
        "weakness_playbook_matches": [
            _playbook_match(m) for m in sheet.weakness_playbook_matches
        ],
        "next_run_plan": [_next_run_item(n) for n in sheet.next_run_plan],
        "validation_checks": [
            _validation_check(v) for v in sheet.validation_checks
        ],
        "storyline": [_storyline_entry(s) for s in sheet.storyline],
        "limits": _limits(sheet.limits),
    }


# ── leaf writers ────────────────────────────────────────────────

def _focus_item(fi: FocusItem) -> dict[str, Any]:
    return {
        "rank": fi.rank,
        "weakness_key": fi.weakness_key,
        "title": fi.title,
        "severity": fi.severity,
        "estimated_cost_ms": fi.estimated_cost_ms,
        "corners": list(fi.corners),
        "phase": fi.phase,
        "confidence": fi.confidence,
    }


def _playbook_match(pm: PlaybookMatch) -> dict[str, Any]:
    return {
        "weakness_key": pm.weakness_key,
        "title": pm.title,
        "matched_playbook": pm.matched_playbook,
        "corner_ids": list(pm.corner_ids),
        "severity": pm.severity,
        "coaching_actions": list(pm.coaching_actions),
        "driver_cues": list(pm.driver_cues),
        "measurable_targets": list(pm.measurable_targets),
        "likely_causes": list(pm.likely_causes),
        "sensor_note": pm.sensor_note,
        "portability": pm.portability,
        "data_support": pm.data_support,
    }


def _corner_coaching(cc: CornerCoaching) -> dict[str, Any]:
    return {
        "corner_id": cc.corner_id,
        "time_delta_ms": cc.time_delta_ms,
        "s_entry_m": cc.s_entry_m,
        "s_exit_m": cc.s_exit_m,
        "applicable_weaknesses": list(cc.applicable_weaknesses),
        "primary_cause": cc.primary_cause,
        "confidence": cc.confidence,
        "summary": cc.summary,
    }


def _next_run_item(n: NextRunItem) -> dict[str, Any]:
    return {
        "rank": n.rank,
        "type": n.type,
        "title": n.title,
        "corners": list(n.corners),
        "instruction": n.instruction,
        "validation": n.validation,
    }


def _validation_check(v: ValidationCheck) -> dict[str, Any]:
    return {
        "weakness_key": v.weakness_key,
        "metric_name": v.metric_name,
        "target_description": v.target_description,
        "corners": list(v.corners),
        "measurement_method": v.measurement_method,
        "confidence": v.confidence,
    }


def _storyline_entry(s: StorylineEntry) -> dict[str, Any]:
    return {
        "type": s.type,
        "text": s.text,
        "confidence": s.confidence,
    }


def _limits(lim: Limits) -> dict[str, Any]:
    return {
        "sessions_analyzed": lim.sessions_analyzed,
        "laps_analyzed": lim.laps_analyzed,
        "brake_data": lim.brake_data,
        "throttle_data": lim.throttle_data,
        "steering_data": lim.steering_data,
        "cross_track_portability": lim.cross_track_portability,
        "weather_conditions": lim.weather_conditions,
        "reference_basis": lim.reference_basis,
        "confidence_floor": lim.confidence_floor,
    }
