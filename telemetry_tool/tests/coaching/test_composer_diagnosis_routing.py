"""P2-Task 5 — route drill selection through corner_diagnosis.

Contract:
1. A HIGH-confidence diagnosis cell drives `_resolve_cause` outright (new
   BRANCH 0, highest priority) — resolving the label to its causal root via
   `corner_diagnosis._CAUSAL_PARENT`, then mapping that root to a taxonomy
   cause via `diagnosis_cause_map.DIAGNOSIS_LABEL_TO_CAUSE`.
2. A LOW-confidence diagnosis (yaw labels without a reliable corroboration
   channel) must NOT drive the cause — it falls through to the existing
   symptom/metric branches, honoring the honesty gate.
3. With no diagnosis at all, behavior is byte-for-byte Phase-1 (backward
   compatible).
"""
from coaching.composers.corner_composer import _resolve_cause
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.diagnosis_cause_map import DIAGNOSIS_LABEL_TO_CAUSE


def test_high_confidence_diagnosis_drives_cause():
    tax = CauseTaxonomy()
    diag = {"label": "low_min_speed", "confidence": "high"}   # non-yaw, cleanly mapped
    cause, _ = _resolve_cause({"corner_id": 1}, symptoms=None, trail_brake=None,
                              throttle_lifts=[], taxonomy=tax, diagnosis=diag)
    from coaching import corner_diagnosis as cd
    assert cause == DIAGNOSIS_LABEL_TO_CAUSE[cd._CAUSAL_PARENT.get("low_min_speed", "low_min_speed")]


def test_low_confidence_diagnosis_does_not_drive_cause():
    tax = CauseTaxonomy()
    diag = {"label": "exit_oversteer", "confidence": "low"}    # unreliable yaw label
    cause, _ = _resolve_cause({"corner_id": 1, "time_loss_apex_speed_s": 0.3}, symptoms=None,
                              trail_brake=None, throttle_lifts=[], taxonomy=tax, diagnosis=diag)
    assert cause != DIAGNOSIS_LABEL_TO_CAUSE.get("early_throttle")  # fell through to metric branch
    assert cause == "mid_corner_speed_loss"  # the apex-loss metric branch wins instead


def test_no_diagnosis_preserves_phase1_behavior():
    tax = CauseTaxonomy()
    cause, _ = _resolve_cause({"corner_id": 1, "time_loss_braking_s": 0.4}, symptoms=None,
                              trail_brake=None, throttle_lifts=[], taxonomy=tax, diagnosis=None)
    assert cause == "insufficient_brake_pressure"  # unchanged Phase-1 metric-branch result
