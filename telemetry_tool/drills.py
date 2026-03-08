"""
drills.py
---------
Practice drill registry and session plan generator.

Maps detected driving issues (from CoachingV2 corrections) to measurable
practice drills. Generates a structured practice plan with warmup, drills,
evaluation, and reflection.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Drill:
    drill_id: str
    title: str
    goal: str
    setup: str
    execution: str
    success_criteria: dict
    required_channels: list
    issue_types: list

    def to_dict(self) -> dict:
        return {
            "drill_id": self.drill_id,
            "title": self.title,
            "goal": self.goal,
            "setup": self.setup,
            "execution": self.execution,
            "success_criteria": self.success_criteria,
            "required_channels": self.required_channels,
            "issue_types": self.issue_types,
        }


@dataclass
class PracticePlan:
    warmup: dict
    drills: list
    evaluation: dict
    reflection: str
    channel_warnings: list
    provenance_ref: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "warmup": self.warmup,
            "drills": [d if isinstance(d, dict) else d for d in self.drills],
            "evaluation": self.evaluation,
            "reflection": self.reflection,
            "channel_warnings": self.channel_warnings,
            "provenance_ref": self.provenance_ref,
        }


DRILL_REGISTRY: list[Drill] = [
    Drill(
        drill_id="brake_release_progressive",
        title="Progressive Brake Release",
        goal="Smooth, linear brake release to maximise mid-corner grip",
        setup="Pick a medium-speed corner with clear braking zone",
        execution="Focus on releasing brake pressure linearly from 100% to 0% over the release phase. No sudden drops.",
        success_criteria={"release_linearity_r2": ">0.8"},
        required_channels=["Brake (%)", "accel_long"],
        issue_types=["over_drop", "late_release"],
    ),
    Drill(
        drill_id="trail_brake_hold",
        title="Trail Brake Hold",
        goal="Maintain light brake pressure past turn-in to rotate the car",
        setup="Select an understeer-prone corner",
        execution="After initial braking, hold 10-20% brake into the apex. Feel the rear rotate.",
        success_criteria={"brake_at_apex_pct": ">5"},
        required_channels=["Brake (%)", "yaw_rate"],
        issue_types=["under_rotation"],
    ),
    Drill(
        drill_id="rotation_timing",
        title="Rotation Timing",
        goal="Achieve rotation before throttle application",
        setup="Pick a corner where you tend to apply power too early",
        execution="Wait for the car to rotate (yaw rate peak) before any throttle. Be patient.",
        success_criteria={"throttle_after_mrp": "true"},
        required_channels=["yaw_rate", "accel_long"],
        issue_types=["power_before_rotation", "rotation_too_late"],
    ),
    Drill(
        drill_id="mrp_consistency",
        title="MRP Consistency",
        goal="Hit the same rotation point every lap",
        setup="Choose a corner and mark a reference point",
        execution="Aim for the same yaw rate peak position (within 3m) every lap.",
        success_criteria={"mrp_std_m": "<3.0"},
        required_channels=["yaw_rate"],
        issue_types=["mrp_drift", "mrp_plateau"],
    ),
    Drill(
        drill_id="compound_rhythm",
        title="Compound Corner Rhythm",
        goal="Connect compound corners with a smooth rhythm",
        setup="Identify a compound corner group (e.g. chicane or esses)",
        execution="Focus on the transition between corners. Sacrifice entry of second corner for better exit.",
        success_criteria={"compound_time_loss_s": "<0.1"},
        required_channels=["speed", "accel_long"],
        issue_types=["compound_setup_error"],
    ),
    Drill(
        drill_id="kink_sacrifice",
        title="Kink Sacrifice Strategy",
        goal="Maintain speed through kinks by accepting sub-optimal line",
        setup="Identify flat-out kinks where you currently lift",
        execution="Stay flat through the kink even if the line isn't perfect. Build confidence gradually.",
        success_criteria={"min_speed_increase_kmh": ">2"},
        required_channels=["speed", "position"],
        issue_types=["kink_trap"],
    ),
    Drill(
        drill_id="line_precision",
        title="Line Precision",
        goal="Reduce lap-to-lap variation in racing line",
        setup="Pick 3 reference corners",
        execution="Hit the same apex, same turn-in point, same exit point for 5 consecutive laps.",
        success_criteria={"position_std_m": "<1.5"},
        required_channels=["position"],
        issue_types=["line_variance"],
    ),
    Drill(
        drill_id="exit_commitment",
        title="Exit Commitment",
        goal="Full throttle commitment on corner exit",
        setup="Pick a corner where you tend to hesitate on exit",
        execution="Once you decide to go to throttle, commit fully. No partial lifts.",
        success_criteria={"throttle_hesitation_count": "0"},
        required_channels=["accel_long", "speed"],
        issue_types=["early_lift", "traction_limited"],
    ),
]

# Build lookup: issue_type -> list of drills
_ISSUE_TO_DRILLS: dict[str, list[Drill]] = {}
for _d in DRILL_REGISTRY:
    for _it in _d.issue_types:
        _ISSUE_TO_DRILLS.setdefault(_it, []).append(_d)


def map_issues_to_drills(
    coaching_v2: dict,
    available_channels: list[str],
) -> list[dict]:
    """Select drills measurable with available channels."""
    corrections = coaching_v2.get("corrections", [])
    if not corrections:
        return []

    seen_drills = set()
    result = []

    for correction in corrections:
        reason = correction.get("reason_code", "")
        matching_drills = _ISSUE_TO_DRILLS.get(reason, [])
        for drill in matching_drills:
            if drill.drill_id in seen_drills:
                continue
            seen_drills.add(drill.drill_id)
            # Check channel availability
            missing = [ch for ch in drill.required_channels if ch not in available_channels]
            result.append({
                "drill_id": drill.drill_id,
                "title": drill.title,
                "corner_id": correction.get("corner_id"),
                "reason_code": reason,
                "missing_channels": missing,
            })

    return result


def generate_practice_plan(
    coaching_v2: dict,
    available_channels: list[str],
    max_drills: int = 2,
) -> PracticePlan:
    """Build session plan: warmup + drills + evaluation + reflection."""
    mapped = map_issues_to_drills(coaching_v2, available_channels)

    # Filter to drills with no missing channels (or minimal missing)
    usable = [m for m in mapped if not m.get("missing_channels")]
    partially_usable = [m for m in mapped if m.get("missing_channels")]

    selected = usable[:max_drills]
    if len(selected) < max_drills:
        selected.extend(partially_usable[:max_drills - len(selected)])

    channel_warnings = []
    for m in mapped:
        for ch in m.get("missing_channels", []):
            warning = f"Drill '{m['title']}' needs {ch} sensor"
            if warning not in channel_warnings:
                channel_warnings.append(warning)

    drills_list = []
    for i, m in enumerate(selected):
        drill_def = next((d for d in DRILL_REGISTRY if d.drill_id == m["drill_id"]), None)
        if drill_def:
            drills_list.append({
                "drill_id": m["drill_id"],
                "title": drill_def.title,
                "corner_ids": [m.get("corner_id")],
                "reps": 5,
                "target_metric": list(drill_def.success_criteria.keys())[0] if drill_def.success_criteria else None,
                "setup": drill_def.setup,
                "execution": drill_def.execution,
            })

    objectives = coaching_v2.get("objectives", [])
    reflection_text = "Compare your drill performance to baseline. "
    if objectives:
        reflection_text += f"Focus on: {objectives[0].get('text', 'your top priority')}."

    return PracticePlan(
        warmup={"laps": 3, "focus": "baseline pace — no pushing, find rhythm"},
        drills=drills_list,
        evaluation={"laps": 2, "compare_to": "baseline"},
        reflection=reflection_text,
        channel_warnings=channel_warnings,
    )
