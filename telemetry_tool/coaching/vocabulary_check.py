"""Fail-loud guard: every cause id _resolve_cause can emit must exist in BOTH
the taxonomy and DRILL_LIBRARY, so vocabulary drift can never silently collapse
every corner to 'Unknown cause'.

RESOLVABLE_CAUSE_IDS is the full, real set of cause ids that
`coaching.composers.corner_composer._resolve_cause` can return, verified by
reading its symptom-path (`_SYMPTOM_TO_CAUSE`) and metric-path branches:

- "early_apex"                  — symptom path, symptom_id "early_apex" (direct)
- "mid_corner_lift"             — symptom path, symptom_id "mid_corner_speed_loss"
                                   (mapped via _SYMPTOM_TO_CAUSE), and metric
                                   path (dangerous throttle lifts)
- "early_braking_confidence"    — metric path, braking_point_delta_m > 5.0
- "late_braking_aggressive"     — metric path, braking_point_delta_m < -3.0
- "no_trail_braking"            — metric path, trail_brake.has_trail_braking is False
- "insufficient_brake_pressure" — metric path, largest phase loss = time_loss_braking_s
- "mid_corner_speed_loss"       — metric path, largest phase loss = time_loss_apex_speed_s,
                                   and the final fallback branch
- "late_throttle_application"   — metric path, largest phase loss = time_loss_exit_s

Note: `_SYMPTOM_TO_CAUSE` also maps symptom_id "understeer_entry" -> cause_id
"understeer_entry", but that cause id does not exist anywhere in the taxonomy
(causes.json), so the `if taxonomy.get_cause(cause_id):` guard in
`_resolve_cause` always rejects it and falls through to the metric path.
"understeer_entry" can therefore never actually be returned and is correctly
excluded from this set — do not add it back without also adding a taxonomy
entry for it and verifying it can be returned.
"""
from __future__ import annotations

RESOLVABLE_CAUSE_IDS = frozenset({
    "early_apex",
    "early_braking_confidence", "late_braking_aggressive", "no_trail_braking",
    "mid_corner_lift", "insufficient_brake_pressure", "mid_corner_speed_loss",
    "late_throttle_application",
})


def assert_cause_vocabulary_integrity() -> None:
    from coaching.taxonomy.causes import CauseTaxonomy
    from coaching.templates.drills import DRILL_LIBRARY
    tax = CauseTaxonomy()
    drill_causes: set[str] = set()
    for d in DRILL_LIBRARY.values():
        drill_causes.update(d.get("applicable_causes", []))
    missing = [
        cid for cid in RESOLVABLE_CAUSE_IDS
        if tax.get_cause(cid) is None or cid not in drill_causes
    ]
    if missing:
        raise ValueError(f"Cause vocabulary drift — ids not in taxonomy∩drills: {sorted(missing)}")
