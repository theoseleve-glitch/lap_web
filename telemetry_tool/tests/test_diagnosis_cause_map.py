"""Tests for coaching.diagnosis_cause_map — every mapped cause id must be
real (exist in the taxonomy AND some drill's applicable_causes), and every
diagnosis label the classifier can actually emit must resolve (via
corner_diagnosis._CAUSAL_PARENT) to a mapped root, so a real diagnosis never
falls through to "Unknown" in the downstream drill-selection composer
(Task 5).
"""
from __future__ import annotations

from coaching.diagnosis_cause_map import DIAGNOSIS_LABEL_TO_CAUSE
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.templates.drills import DRILL_LIBRARY
from coaching import corner_diagnosis as cd


def _drill_causes() -> set[str]:
    s: set[str] = set()
    for d in DRILL_LIBRARY.values():
        s.update(d.get("applicable_causes", []))
    return s


def test_every_mapped_cause_is_real():
    tax, drills = CauseTaxonomy(), _drill_causes()
    for label, cause in DIAGNOSIS_LABEL_TO_CAUSE.items():
        assert tax.get_cause(cause) is not None, f"{label}->{cause} not in taxonomy"
        assert cause in drills, f"{label}->{cause} not in DRILL_LIBRARY"


# Every non-"good" label in corner_diagnosis's 23-label taxonomy (all label
# constants except cd.GOOD, which means "no issue" and never needs a cause).
# Verified against the real module (2026-07) rather than assumed.
_ALL_EMITTABLE_LABELS = [
    cd.ENTRY_OVERSPEED, cd.ENTRY_UNDERSPEED, cd.LATE_BRAKING, cd.EARLY_BRAKING,
    cd.ENTRY_UNDERSTEER, cd.ENTRY_OVERSTEER, cd.INSUFFICIENT_TRAIL_BRAKE, cd.EXCESSIVE_TRAIL_BRAKE,
    cd.LOW_MIN_SPEED, cd.EARLY_APEX, cd.LATE_APEX, cd.MID_CORNER_UNDERSTEER,
    cd.MID_CORNER_OVERSTEER, cd.COAST_HESITATION,
    cd.EXIT_UNDERSTEER, cd.EXIT_OVERSTEER, cd.EARLY_THROTTLE, cd.LATE_ROTATION,
    cd.LATE_THROTTLE, cd.THROTTLE_LIFT,
    cd.SLOW_EXIT, cd.SCRAPPY,
]


def _emittable_roots() -> set[str]:
    return {cd._CAUSAL_PARENT.get(lbl, lbl) for lbl in _ALL_EMITTABLE_LABELS}


def test_all_emittable_diagnosis_roots_are_mapped():
    # every non-good/None label the classifier can emit, resolved to its root,
    # must map, so a real diagnosis never falls through to Unknown.
    for root in _emittable_roots():
        assert root in DIAGNOSIS_LABEL_TO_CAUSE, f"unmapped diagnosis root {root}"


def test_no_stray_map_keys():
    # every key should be a genuine resolvable root -- guards against dead
    # entries surviving a future label/causal-chain refactor.
    stray = set(DIAGNOSIS_LABEL_TO_CAUSE) - _emittable_roots()
    assert not stray, f"map has keys that are not real diagnosis roots: {stray}"
