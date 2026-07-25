"""Maps corner-diagnosis root labels to existing coaching-taxonomy cause ids.

`coaching.corner_diagnosis` classifies each corner into one label from its own
23-label vocabulary (`entry_understeer`, `early_throttle`, ...). That
vocabulary differs from the coaching taxonomy / `DRILL_LIBRARY` cause ids
(`mid_corner_speed_loss`, `early_braking_confidence`, ...). This module bridges
the two so a diagnosed root cause can drive drill selection (Task 5).

Every diagnosis label the classifier can emit (all label constants in
`corner_diagnosis` except `GOOD`, which means "no issue" and needs no cause)
first resolves to its causal root via
`corner_diagnosis._CAUSAL_PARENT.get(label, label)` -- e.g. `exit_understeer`'s
root is `early_throttle`; `early_apex`'s root is `entry_understeer` (one hop
only, matching `_CAUSAL_PARENT`'s own single-level child->parent chain).
`DIAGNOSIS_LABEL_TO_CAUSE` maps every one of those 15 distinct resolved roots
to the semantically-closest EXISTING `coaching/taxonomy/causes.json` cause id
that is ALSO covered by some drill's `applicable_causes` in
`coaching/templates/drills.py`. This is guard-enforced by
`vocabulary_check.assert_cause_vocabulary_integrity`.

No new taxonomy or drill ids were invented for this map: all 26 real taxonomy
cause ids already appear in some drill's `applicable_causes`, so unlike Phase
1's `insufficient_brake_pressure` fix, no `applicable_causes` gap-fill was
needed here (verified in `tests/test_diagnosis_cause_map.py` and noted in the
P2-Task-3 report).

The 26-id taxonomy is coarser than the 22-label (excl. GOOD) physics-based
diagnosis vocabulary, so a few roots legitimately share a taxonomy id:
- `excess_steering_angle` ("...indicating understeer or over-rotation") is the
  best existing match for THREE roots: `entry_understeer` (the "understeer"
  reading), `mid_corner_oversteer` (the "over-rotation" reading), and
  `early_throttle` (the taxonomy has no "throttle applied too early" exit-
  category cause; the closest available captures early_throttle's documented
  downstream consequence, `exit_understeer` -- this is the weakest/least clean
  mapping in this table, see the report).
- `late_apex_excessive` covers both `late_apex` and `late_rotation` (both
  describe the car completing its direction change later than ideal, just via
  different metrics -- apex-speed position vs. MRP delta).
- `early_braking_confidence` covers both `early_braking` (near-identical
  wording to the taxonomy symptom) and `entry_underspeed` (a plausible
  consequence of the same confidence-driven premature braking).
"""
from __future__ import annotations

from coaching import corner_diagnosis as cd

DIAGNOSIS_LABEL_TO_CAUSE: dict[str, str] = {
    # Entry-phase roots
    cd.ENTRY_OVERSPEED: "corner_entry_too_fast",
    cd.ENTRY_UNDERSPEED: "early_braking_confidence",
    cd.LATE_BRAKING: "late_braking_aggressive",
    cd.EARLY_BRAKING: "early_braking_confidence",
    cd.INSUFFICIENT_TRAIL_BRAKE: "no_trail_braking",
    cd.ENTRY_UNDERSTEER: "excess_steering_angle",
    # Apex / mid-corner roots
    cd.LOW_MIN_SPEED: "mid_corner_speed_loss",
    cd.LATE_APEX: "late_apex_excessive",
    cd.MID_CORNER_OVERSTEER: "excess_steering_angle",
    cd.COAST_HESITATION: "hesitant_throttle",
    # Exit roots
    cd.EARLY_THROTTLE: "excess_steering_angle",
    cd.EXIT_OVERSTEER: "mid_corner_lift",
    cd.LATE_ROTATION: "late_apex_excessive",
    # Overall roots
    cd.SLOW_EXIT: "poor_exit_speed",
    cd.SCRAPPY: "mid_corner_correction",
}
