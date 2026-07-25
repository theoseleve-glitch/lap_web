"""Corner composer — builds CornerCoachingDetail from analyzer outputs.

Resolution order:
0. Diagnosis-based (Phase 2, Task 5): a HIGH-confidence corner-diagnosis
   classifier label (the physics-derived root cause) wins outright — this is
   the new PRIMARY driver of drill selection. A missing diagnosis, or one
   whose confidence is "low" (unreliable yaw labels — see
   `coaching.corner_diagnosis._YAW_RESIDUAL_LABELS`), does not participate
   here and falls through to the branches below, which stay byte-for-byte
   Phase-1 behavior.
1. Symptom-based diagnosis (highest confidence symptom wins) — fallback
2. Metric-based: braking point delta → speed deltas → fallback to largest time_loss phase
3. Template lookup from CORNER_TIPS[(cause, severity, vehicle)]
"""
from __future__ import annotations

from coaching import corner_diagnosis as cd
from coaching.diagnosis_cause_map import DIAGNOSIS_LABEL_TO_CAUSE
from coaching.models import (
    CornerCoachingDetail, ExitSpeedCascade, SymptomDetection,
    TractionBudget, TrailBrakeAssessment, WeightTransferInsight,
    ThrottleLiftEvent,
)
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.templates.corner_tips import CORNER_TIPS

# Symptom → cause_id mapping
_SYMPTOM_TO_CAUSE = {
    "early_apex": "early_apex",
    "understeer_entry": "understeer_entry",
    "mid_corner_speed_loss": "mid_corner_lift",
}

# Diagnosis-routed cause → corner_perf time-loss key it's most semantically
# tied to. Reuses the same three phase buckets (braking / apex / exit) branch
# 2's metric path already keys off of — used only to size the cause's
# severity delta; a cause with no matching real measurement here falls back
# to `_DIAGNOSIS_DEFAULT_DELTA` rather than fabricating one.
_CAUSE_TIME_LOSS_KEY = {
    "corner_entry_too_fast": "time_loss_braking_s",
    "early_braking_confidence": "time_loss_braking_s",
    "late_braking_aggressive": "time_loss_braking_s",
    "no_trail_braking": "time_loss_braking_s",
    "excess_steering_angle": "time_loss_apex_speed_s",
    "mid_corner_speed_loss": "time_loss_apex_speed_s",
    "late_apex_excessive": "time_loss_apex_speed_s",
    "hesitant_throttle": "time_loss_apex_speed_s",
    "mid_corner_correction": "time_loss_apex_speed_s",
    "mid_corner_lift": "time_loss_exit_s",
    "poor_exit_speed": "time_loss_exit_s",
}

# Moderate-severity default used when a diagnosis-routed cause has no
# corresponding real time_loss measurement on corner_perf (mirrors the
# moderate-threshold default the symptom branch already falls back to).
_DIAGNOSIS_DEFAULT_DELTA = 10.0


def compose_corner_coaching(
    corner_perf: dict,
    trail_brake: TrailBrakeAssessment | None,
    traction: TractionBudget | None,
    exit_cascade: ExitSpeedCascade | None,
    symptoms: SymptomDetection | None,
    throttle_lifts: list[ThrottleLiftEvent],
    weight_transfer: WeightTransferInsight | None,
    taxonomy: CauseTaxonomy,
    vehicle_class: str,
    driver_history: dict | None = None,
    diagnosis: dict | None = None,
) -> CornerCoachingDetail:
    """Resolve primary cause for a corner and build full coaching detail.

    `diagnosis`, when given, is this corner's aggregated corner-diagnosis
    cell (`{"label": str, "confidence": "high"|"low"}` — see
    `session_composer._aggregate_corner_diagnosis`). It is `None` for callers
    that never ran the classifier (Phase-1 behavior, unchanged).
    """

    corner_id = corner_perf["corner_id"]
    corner_name = f"T{corner_id}"

    # ── 1. Resolve primary cause ──
    cause_id, delta_value = _resolve_cause(
        corner_perf, symptoms, trail_brake, throttle_lifts, taxonomy,
        diagnosis=diagnosis,
    )

    # ── 2. Get severity ──
    severity = taxonomy.get_severity(cause_id, delta_value)
    cause_def = taxonomy.get_cause(cause_id)
    root_cause = cause_def["root_cause"] if cause_def else "technique"
    diagnosis_text = cause_def["diagnosis"] if cause_def else "Unknown cause"

    # ── 3. Look up template ──
    template_key = (cause_id, severity, vehicle_class)
    template = CORNER_TIPS.get(template_key)

    # Fallback: try other vehicle, then generic moderate
    if template is None:
        fallback_vehicle = "car" if vehicle_class == "kart" else "kart"
        template = CORNER_TIPS.get((cause_id, severity, fallback_vehicle))
    if template is None:
        template = CORNER_TIPS.get((cause_id, "moderate", vehicle_class))
    if template is None:
        template = {
            "tip": f"Focus on improving {cause_id.replace('_', ' ')} at {corner_name}.",
            "progressive_steps": [
                "Start with awareness — watch for the symptom.",
                "Make one small adjustment per session.",
                "Consolidate the change with consistent repetition.",
            ],
            "symptom_check": cause_def["symptom"] if cause_def else "Review telemetry",
        }

    # ── 4. Fill template placeholders ──
    placeholders = _build_placeholders(corner_perf, corner_name, exit_cascade, throttle_lifts)
    safe_placeholders = _SafeDict(placeholders)
    coaching_tip = template["tip"].format_map(safe_placeholders)
    progressive_steps = [
        step.format_map(safe_placeholders) for step in template["progressive_steps"]
    ]
    symptom_check = template["symptom_check"].format_map(safe_placeholders)

    # ── 5. Symptom evidence ──
    symptom_evidence = []
    if symptoms:
        for s in symptoms.symptoms:
            symptom_evidence.append(s.description)

    # ── 6. Speed targets ──
    entry_target = _mps_to_kmh(corner_perf.get("theoretical_entry_speed_mps"))
    apex_target = _mps_to_kmh(corner_perf.get("theoretical_apex_speed_mps"))
    exit_target = _mps_to_kmh(corner_perf.get("theoretical_exit_speed_mps"))

    # ── 7. Cascade time loss ──
    time_loss_corner = corner_perf.get("time_loss_s", 0.0) or 0.0
    time_loss_cascade = time_loss_corner
    if exit_cascade:
        time_loss_cascade = exit_cascade.total_cascade_time_s

    # ── 8. Weight transfer text ──
    wt_text = weight_transfer.insight_text if weight_transfer else None

    return CornerCoachingDetail(
        corner_id=corner_id,
        corner_name=corner_name,
        primary_cause=cause_id,
        cause_severity=severity,
        cause_root=root_cause,
        symptom_evidence=symptom_evidence,
        diagnosis_text=diagnosis_text,
        coaching_tip=coaching_tip,
        progressive_steps=progressive_steps,
        symptom_check=symptom_check,
        time_loss_corner_s=time_loss_corner,
        time_loss_cascade_s=time_loss_cascade,
        exit_speed_target_kmh=exit_target,
        apex_speed_target_kmh=apex_target,
        entry_speed_target_kmh=entry_target,
        traction_budget=traction,
        trail_brake=trail_brake,
        exit_cascade=exit_cascade,
        weight_transfer_insight=wt_text,
    )


def _resolve_cause(
    corner_perf: dict,
    symptoms: SymptomDetection | None,
    trail_brake: TrailBrakeAssessment | None,
    throttle_lifts: list[ThrottleLiftEvent],
    taxonomy: CauseTaxonomy,
    diagnosis: dict | None = None,
) -> tuple[str, float]:
    """Return (cause_id, delta_value) using diagnosis → symptom → metric → fallback priority."""

    # 0. Diagnosis-based (Phase 2, Task 5): a HIGH-confidence corner-diagnosis
    # label is the physics-derived root cause and outranks every branch below.
    # Low-confidence cells (unreliable yaw labels — the honesty gate) and a
    # missing diagnosis both fall straight through, unchanged.
    if diagnosis and diagnosis.get("confidence") == "high":
        label = diagnosis.get("label")
        if label:
            root_label = cd._CAUSAL_PARENT.get(label, label)
            diag_cause_id = DIAGNOSIS_LABEL_TO_CAUSE.get(root_label)
            if diag_cause_id and taxonomy.get_cause(diag_cause_id):
                time_loss_key = _CAUSE_TIME_LOSS_KEY.get(diag_cause_id)
                delta = corner_perf.get(time_loss_key) if time_loss_key else None
                delta = abs(delta) if delta else _DIAGNOSIS_DEFAULT_DELTA
                return diag_cause_id, delta

    # 1. Symptom-based: highest confidence symptom
    if symptoms and symptoms.symptoms:
        best = max(symptoms.symptoms, key=lambda s: s.confidence)
        cause_id = _SYMPTOM_TO_CAUSE.get(best.symptom_id, best.symptom_id)
        if taxonomy.get_cause(cause_id):
            # Use evidence value if available, otherwise default to moderate threshold
            delta = next(iter(best.evidence.values()), 10.0)
            return cause_id, delta

    # 2. Braking point delta
    bp_delta = corner_perf.get("braking_point_delta_m", 0.0) or 0.0
    if bp_delta > 5.0:
        return "early_braking_confidence", bp_delta
    if bp_delta < -3.0:
        return "late_braking_aggressive", abs(bp_delta)

    # 3. Trail braking issues
    if trail_brake and not trail_brake.has_trail_braking:
        return "no_trail_braking", trail_brake.time_loss_from_no_trail_s

    # 4. Throttle lifts
    dangerous_lifts = [tl for tl in throttle_lifts if tl.severity == "dangerous"]
    if dangerous_lifts:
        return "mid_corner_lift", dangerous_lifts[0].drop_pct

    # 5. Speed-based: find largest time loss phase
    phases = {
        "time_loss_braking_s": "insufficient_brake_pressure",
        "time_loss_apex_speed_s": "mid_corner_speed_loss",
        "time_loss_exit_s": "late_throttle_application",
    }
    best_phase = None
    best_loss = 0.0
    for key, cause in phases.items():
        loss = abs(corner_perf.get(key, 0.0) or 0.0)
        if loss > best_loss:
            best_loss = loss
            best_phase = cause

    if best_phase and best_loss > 0.01:
        return best_phase, best_loss

    # 6. Fallback
    return "mid_corner_speed_loss", corner_perf.get("time_loss_s", 0.1) or 0.1


class _SafeDict(dict):
    """dict for str.format_map that degrades a missing key to an em-dash
    instead of raising KeyError. Templates are rendered with this so a
    token an entry needs — but that has no real measurement backing it —
    reads as "insufficient data" rather than either crashing, leaking a raw
    `{token}`, or (the no-fabrication rule) silently showing a hardcoded
    0.0/0.0% as if it were a genuine measurement."""

    def __missing__(self, key):
        return "—"


def _build_placeholders(
    corner_perf: dict,
    corner_name: str,
    exit_cascade: ExitSpeedCascade | None,
    throttle_lifts: list[ThrottleLiftEvent] | None = None,
) -> dict:
    """Build placeholder dict for template formatting.

    Only ever includes a key when a real analyzer/corner_perf value backs
    it. Missing keys are NOT filled with a hardcoded 0.0 — templates are
    rendered via `_SafeDict`, which degrades an absent token to an em-dash
    instead (see `compose_corner_coaching`).
    """
    bp_delta = corner_perf.get("braking_point_delta_m", 0.0) or 0.0
    time_loss = corner_perf.get("time_loss_s", 0.0) or 0.0

    placeholders = {
        "corner_name": corner_name,
        "delta_m": abs(bp_delta),
        "variance_m": abs(bp_delta) * 0.5,
        "step_m": max(1.0, abs(bp_delta) / 3),
        "current_m": abs(bp_delta),
        "step1_m": abs(bp_delta) * 0.66,
        "step2_m": abs(bp_delta) * 0.33,
        "target_delta_m": 2.0,
        "time_loss_s": time_loss,
        "grip_pct": corner_perf.get("grip_utilisation_pct", 50.0) or 50.0,
    }

    if exit_cascade:
        placeholders["exit_speed_loss_kmh"] = exit_cascade.exit_gain_needed_kmh
        placeholders["cascade_time_s"] = exit_cascade.total_cascade_time_s

    # Throttle-lift-derived magnitudes — real measurements when a lift event
    # is present for this corner, omitted (never a fabricated 0.0/0.0%)
    # otherwise. Prefer the "dangerous" lift (the one that would have driven
    # cause selection) if there is one, else the first detected lift.
    if throttle_lifts:
        lift = next(
            (tl for tl in throttle_lifts if tl.severity == "dangerous"),
            throttle_lifts[0],
        )
        placeholders["throttle_drop_pct"] = lift.drop_pct
        placeholders["lift_duration_s"] = lift.drop_duration_s
        placeholders["weight_shift_kg"] = lift.weight_shift_estimate_kg
        if lift.yaw_rate_change_dps is not None:
            placeholders["yaw_spike"] = abs(lift.yaw_rate_change_dps)

    # NOTE: `pct_increase` (peak brake-pressure / steering-angle deficit vs.
    # a reference lap) has no corresponding analyzer output anywhere in this
    # codebase today. It is deliberately left out of `placeholders` rather
    # than hardcoded to 0.0 — a template that needs it renders "—%" via
    # `_SafeDict` instead of a fabricated measurement.

    return placeholders


def _mps_to_kmh(mps: float | None) -> float | None:
    if mps is None:
        return None
    return round(mps * 3.6, 1)
