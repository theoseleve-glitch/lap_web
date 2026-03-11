"""Corner composer — builds CornerCoachingDetail from analyzer outputs.

Resolution order:
1. Symptom-based diagnosis (highest confidence symptom wins)
2. Metric-based: braking point delta → speed deltas → fallback to largest time_loss phase
3. Template lookup from CORNER_TIPS[(cause, severity, vehicle)]
"""
from __future__ import annotations

from telemetry_tool.coaching.models import (
    CornerCoachingDetail, ExitSpeedCascade, SymptomDetection,
    TractionBudget, TrailBrakeAssessment, WeightTransferInsight,
    ThrottleLiftEvent,
)
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy
from telemetry_tool.coaching.templates.corner_tips import CORNER_TIPS

# Symptom → cause_id mapping
_SYMPTOM_TO_CAUSE = {
    "early_apex": "early_apex",
    "understeer_entry": "understeer_entry",
    "mid_corner_speed_loss": "mid_corner_lift",
}


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
) -> CornerCoachingDetail:
    """Resolve primary cause for a corner and build full coaching detail."""

    corner_id = corner_perf["corner_id"]
    corner_name = f"T{corner_id}"

    # ── 1. Resolve primary cause ──
    cause_id, delta_value = _resolve_cause(
        corner_perf, symptoms, trail_brake, throttle_lifts, taxonomy,
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
    placeholders = _build_placeholders(corner_perf, corner_name, exit_cascade)
    try:
        coaching_tip = template["tip"].format(**placeholders)
    except (KeyError, IndexError):
        coaching_tip = template["tip"]

    progressive_steps = []
    for step in template["progressive_steps"]:
        try:
            progressive_steps.append(step.format(**placeholders))
        except (KeyError, IndexError):
            progressive_steps.append(step)

    symptom_check = template["symptom_check"]

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
) -> tuple[str, float]:
    """Return (cause_id, delta_value) using symptom → metric → fallback priority."""

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
        return "mid_corner_lift", dangerous_lifts[0].throttle_drop_pct

    # 5. Speed-based: find largest time loss phase
    phases = {
        "time_loss_braking_s": "insufficient_brake_pressure",
        "time_loss_apex_speed_s": "low_apex_speed",
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
    return "low_apex_speed", corner_perf.get("time_loss_s", 0.1) or 0.1


def _build_placeholders(
    corner_perf: dict,
    corner_name: str,
    exit_cascade: ExitSpeedCascade | None,
) -> dict:
    """Build placeholder dict for template formatting."""
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
        "exit_speed_loss_kmh": 0.0,
        "cascade_time_s": 0.0,
        "pct_increase": 0.0,
        "throttle_drop_pct": 0.0,
        "lift_duration_s": 0.0,
        "grip_pct": corner_perf.get("grip_utilisation_pct", 50.0) or 50.0,
        "weight_shift_kg": 0.0,
        "yaw_spike": 0.0,
    }

    if exit_cascade:
        placeholders["exit_speed_loss_kmh"] = exit_cascade.exit_gain_needed_kmh
        placeholders["cascade_time_s"] = exit_cascade.total_cascade_time_s

    return placeholders


def _mps_to_kmh(mps: float | None) -> float | None:
    if mps is None:
        return None
    return round(mps * 3.6, 1)
