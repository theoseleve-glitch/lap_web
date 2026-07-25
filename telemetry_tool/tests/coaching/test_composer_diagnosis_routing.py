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
from coaching.composers.corner_composer import _resolve_cause, compose_corner_coaching
from coaching.composers.session_composer import _aggregate_corner_diagnosis
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


def test_diagnosis_routed_severity_defaults_to_moderate_not_mild():
    """A diagnosis-routed (branch-0) cause must NOT derive its severity from
    the wrong-unit TIME delta (which would collapse to 'mild' since the
    thresholds are km/h). Interim honest default is a neutral 'moderate' until
    magnitude-severity wiring lands. `mid_corner_speed_loss` thresholds are
    {mild:2.0, moderate:5.0} km/h, so a 0.3 s time delta would be 'mild' under
    the old (buggy) unit-mismatched path — this pins the 'moderate' fix."""
    tax = CauseTaxonomy()
    diag = {"label": "low_min_speed", "confidence": "high"}
    detail = compose_corner_coaching(
        corner_perf={"corner_id": 1, "time_loss_apex_speed_s": 0.3},
        trail_brake=None, traction=None, exit_cascade=None, symptoms=None,
        throttle_lifts=[], weight_transfer=None, taxonomy=tax,
        vehicle_class="car", diagnosis=diag,
    )
    assert detail.primary_cause == "mid_corner_speed_loss"
    assert detail.cause_severity == "moderate"


def test_no_diagnosis_severity_still_from_taxonomy():
    """The moderate override is scoped to diagnosis-routed causes ONLY — the
    no-diagnosis (metric) path must still derive severity from the taxonomy
    thresholds, unchanged. A large braking-point delta stays severe/moderate,
    NOT forced to a flat 'moderate'."""
    tax = CauseTaxonomy()
    detail = compose_corner_coaching(
        corner_perf={"corner_id": 1, "braking_point_delta_m": 30.0},
        trail_brake=None, traction=None, exit_cascade=None, symptoms=None,
        throttle_lifts=[], weight_transfer=None, taxonomy=tax,
        vehicle_class="car", diagnosis=None,
    )
    assert detail.primary_cause == "early_braking_confidence"
    # 30 m >> severe threshold (20 m) → taxonomy derives 'severe', proving the
    # override didn't leak onto the metric path.
    assert detail.cause_severity == "severe"


# ---------------------------------------------------------------------------
# Direct unit tests for `_aggregate_corner_diagnosis` — the classifier's raw
# per-LAP per-corner grid collapsed to one cell per corner. This is the most
# logic-dense piece of the task and is otherwise only reached indirectly.
#
# Grid shape: {lap_str: {corner_str: {"label", "confidence"}}}.
# ---------------------------------------------------------------------------

def _lap_metrics(*pairs):
    """Build lap_metrics rows from (lap_number, lap_time_s) pairs."""
    return [{"lap_number": ln, "lap_time_s": lt} for ln, lt in pairs]


def test_aggregate_uses_best_lap_cell_verbatim():
    """When a best lap is identifiable AND has a cell for the corner, that
    cell is used AS-IS — even when a different label is modal across laps."""
    grid = {
        "1": {"3": {"label": "low_min_speed", "confidence": "high"}},
        "2": {"3": {"label": "late_apex", "confidence": "high"}},   # best lap
        "3": {"3": {"label": "low_min_speed", "confidence": "high"}},
    }
    # Lap 2 is fastest → its cell (late_apex) wins over the modal low_min_speed.
    lm = _lap_metrics((1, 60.5), (2, 59.8), (3, 60.1))
    out = _aggregate_corner_diagnosis(grid, corner_id=3, lap_metrics=lm)
    assert out == {"label": "late_apex", "confidence": "high"}


def test_aggregate_best_lap_good_suppresses_to_none():
    """A best lap whose corner cell is 'good' means the corner was clean on the
    driver's best effort → no diagnosis (does NOT fall through to modal)."""
    grid = {
        "1": {"3": {"label": "low_min_speed", "confidence": "high"}},
        "2": {"3": {"label": "good", "confidence": "high"}},   # best lap: clean here
        "3": {"3": {"label": "low_min_speed", "confidence": "high"}},
    }
    lm = _lap_metrics((1, 60.5), (2, 59.8), (3, 60.1))
    out = _aggregate_corner_diagnosis(grid, corner_id=3, lap_metrics=lm)
    assert out is None


def test_aggregate_no_best_lap_uses_modal_label():
    """With no identifiable best lap (lap_metrics=None), the most-frequent
    non-'good' label across laps wins."""
    grid = {
        "1": {"3": {"label": "low_min_speed", "confidence": "high"}},
        "2": {"3": {"label": "late_apex", "confidence": "high"}},
        "3": {"3": {"label": "low_min_speed", "confidence": "high"}},   # modal: 2x low_min_speed
    }
    out = _aggregate_corner_diagnosis(grid, corner_id=3, lap_metrics=None)
    assert out["label"] == "low_min_speed"


def test_aggregate_modal_confidence_high_only_on_strict_majority():
    """Modal-path confidence is 'high' only when > 50% of the laps carrying the
    modal label recorded it high — a strict majority, not a tie."""
    # 3 laps of the modal label: 2 high + 1 low → strict majority high.
    grid_majority = {
        "1": {"3": {"label": "low_min_speed", "confidence": "high"}},
        "2": {"3": {"label": "low_min_speed", "confidence": "high"}},
        "3": {"3": {"label": "low_min_speed", "confidence": "low"}},
    }
    out = _aggregate_corner_diagnosis(grid_majority, corner_id=3, lap_metrics=None)
    assert out == {"label": "low_min_speed", "confidence": "high"}

    # 1 high + 1 low = exactly 50% → NOT a strict majority → low.
    grid_tie = {
        "1": {"3": {"label": "low_min_speed", "confidence": "high"}},
        "2": {"3": {"label": "low_min_speed", "confidence": "low"}},
    }
    out_tie = _aggregate_corner_diagnosis(grid_tie, corner_id=3, lap_metrics=None)
    assert out_tie == {"label": "low_min_speed", "confidence": "low"}

    # Minority high (1 high + 2 low) → low.
    grid_minority = {
        "1": {"3": {"label": "low_min_speed", "confidence": "high"}},
        "2": {"3": {"label": "low_min_speed", "confidence": "low"}},
        "3": {"3": {"label": "low_min_speed", "confidence": "low"}},
    }
    out_min = _aggregate_corner_diagnosis(grid_minority, corner_id=3, lap_metrics=None)
    assert out_min["confidence"] == "low"


def test_aggregate_best_lap_missing_cell_falls_through_to_modal():
    """If the best lap has NO cell for this corner (e.g. metrics extraction
    failed on it), fall through to modal rather than returning None."""
    grid = {
        "1": {"3": {"label": "late_apex", "confidence": "high"}},
        "2": {"5": {"label": "low_min_speed", "confidence": "high"}},   # best lap: no corner 3
        "3": {"3": {"label": "late_apex", "confidence": "high"}},
    }
    lm = _lap_metrics((1, 60.5), (2, 59.8), (3, 60.1))   # lap 2 fastest but lacks corner 3
    out = _aggregate_corner_diagnosis(grid, corner_id=3, lap_metrics=lm)
    assert out["label"] == "late_apex"   # modal across laps 1 & 3


def test_aggregate_empty_or_all_good_returns_none():
    """No map, no cells for the corner, or all-'good' cells → None."""
    assert _aggregate_corner_diagnosis(None, corner_id=3, lap_metrics=None) is None
    assert _aggregate_corner_diagnosis({}, corner_id=3, lap_metrics=None) is None
    all_good = {
        "1": {"3": {"label": "good", "confidence": "high"}},
        "2": {"3": {"label": "good", "confidence": "high"}},
    }
    # No identifiable best lap → modal path finds only 'good' → None.
    assert _aggregate_corner_diagnosis(all_good, corner_id=3, lap_metrics=None) is None
