"""Coaching V3 data models — all dataclasses with to_dict() serialization.

Backward-compatible with the original coaching_engine.SessionCoaching:
all original fields preserved, new fields are Optional with None defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _round_or_none(val: float | None, ndigits: int) -> float | None:
    return round(val, ndigits) if val is not None else None


# ---------------------------------------------------------------------------
# Physics models
# ---------------------------------------------------------------------------

@dataclass
class BrakingBlock:
    """One of 4 braking phases: throttle→brake, straight-line, trail-brake, brake→throttle."""

    block_id: int
    name: str
    s_start: float
    s_end: float
    duration_s: float
    peak_decel_mps2: float | None = None
    overlap_m: float | None = None
    trail_pct_at_turnin: float | None = None
    release_rate_mps3: float | None = None
    release_linearity: float | None = None
    transition_duration_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "name": self.name,
            "s_start": round(self.s_start, 1),
            "s_end": round(self.s_end, 1),
            "duration_s": round(self.duration_s, 3),
            "peak_decel_mps2": _round_or_none(self.peak_decel_mps2, 2),
            "overlap_m": _round_or_none(self.overlap_m, 1),
            "trail_pct_at_turnin": _round_or_none(self.trail_pct_at_turnin, 1),
            "release_rate_mps3": _round_or_none(self.release_rate_mps3, 2),
            "release_linearity": _round_or_none(self.release_linearity, 2),
            "transition_duration_s": _round_or_none(self.transition_duration_s, 3),
        }


@dataclass
class TrailBrakeAssessment:
    """4-block braking analysis for a single corner."""

    corner_id: int
    blocks: list[BrakingBlock]
    overall_score: float
    has_trail_braking: bool
    theoretical_overlap_m: float
    actual_overlap_m: float
    time_loss_from_no_trail_s: float
    primary_issue: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "blocks": [b.to_dict() for b in self.blocks],
            "overall_score": round(self.overall_score, 1),
            "has_trail_braking": self.has_trail_braking,
            "theoretical_overlap_m": round(self.theoretical_overlap_m, 1),
            "actual_overlap_m": round(self.actual_overlap_m, 1),
            "time_loss_from_no_trail_s": round(self.time_loss_from_no_trail_s, 3),
            "primary_issue": self.primary_issue,
        }


@dataclass
class ExitSpeedCascade:
    """Exit speed → straight speed time gain chain for a corner."""

    corner_id: int
    actual_exit_speed_mps: float
    theoretical_exit_speed_mps: float
    exit_speed_delta_mps: float
    straight_length_m: float
    straight_end_speed_actual_mps: float
    straight_end_speed_theoretical_mps: float
    time_loss_in_corner_s: float
    time_loss_on_straight_s: float
    total_cascade_time_s: float
    exit_gain_needed_kmh: float
    straight_gain_resulting_kmh: float
    cascade_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "actual_exit_speed_mps": round(self.actual_exit_speed_mps, 2),
            "theoretical_exit_speed_mps": round(self.theoretical_exit_speed_mps, 2),
            "exit_speed_delta_mps": round(self.exit_speed_delta_mps, 2),
            "straight_length_m": round(self.straight_length_m, 1),
            "straight_end_speed_actual_mps": round(self.straight_end_speed_actual_mps, 2),
            "straight_end_speed_theoretical_mps": round(self.straight_end_speed_theoretical_mps, 2),
            "time_loss_in_corner_s": round(self.time_loss_in_corner_s, 3),
            "time_loss_on_straight_s": round(self.time_loss_on_straight_s, 3),
            "total_cascade_time_s": round(self.total_cascade_time_s, 3),
            "exit_gain_needed_kmh": round(self.exit_gain_needed_kmh, 1),
            "straight_gain_resulting_kmh": round(self.straight_gain_resulting_kmh, 1),
            "cascade_ratio": round(self.cascade_ratio, 2),
        }


@dataclass
class TractionBudget:
    """Friction circle utilization at entry/apex/exit of a corner."""

    corner_id: int
    entry_lateral_pct: float
    entry_longitudinal_pct: float
    entry_total_pct: float
    entry_remaining_pct: float
    apex_lateral_pct: float
    apex_longitudinal_pct: float
    apex_total_pct: float
    apex_remaining_pct: float
    exit_lateral_pct: float
    exit_longitudinal_pct: float
    exit_total_pct: float
    exit_remaining_pct: float
    theoretical_apex_total_pct: float
    grip_headroom_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "entry_lateral_pct": round(self.entry_lateral_pct, 1),
            "entry_longitudinal_pct": round(self.entry_longitudinal_pct, 1),
            "entry_total_pct": round(self.entry_total_pct, 1),
            "entry_remaining_pct": round(self.entry_remaining_pct, 1),
            "apex_lateral_pct": round(self.apex_lateral_pct, 1),
            "apex_longitudinal_pct": round(self.apex_longitudinal_pct, 1),
            "apex_total_pct": round(self.apex_total_pct, 1),
            "apex_remaining_pct": round(self.apex_remaining_pct, 1),
            "exit_lateral_pct": round(self.exit_lateral_pct, 1),
            "exit_longitudinal_pct": round(self.exit_longitudinal_pct, 1),
            "exit_total_pct": round(self.exit_total_pct, 1),
            "exit_remaining_pct": round(self.exit_remaining_pct, 1),
            "theoretical_apex_total_pct": round(self.theoretical_apex_total_pct, 1),
            "grip_headroom_pct": round(self.grip_headroom_pct, 1),
        }


@dataclass
class ThrottleLiftEvent:
    """A detected mid-corner throttle lift event."""

    corner_id: int
    s_position: float
    throttle_before_pct: float
    throttle_after_pct: float
    drop_pct: float
    drop_duration_s: float
    lateral_grip_at_lift_pct: float
    weight_shift_estimate_kg: float
    yaw_rate_change_dps: float | None = None
    resulted_in_correction: bool = False
    severity: str = "benign"

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "s_position": round(self.s_position, 1),
            "throttle_before_pct": round(self.throttle_before_pct, 1),
            "throttle_after_pct": round(self.throttle_after_pct, 1),
            "drop_pct": round(self.drop_pct, 1),
            "drop_duration_s": round(self.drop_duration_s, 3),
            "lateral_grip_at_lift_pct": round(self.lateral_grip_at_lift_pct, 1),
            "weight_shift_estimate_kg": round(self.weight_shift_estimate_kg, 1),
            "yaw_rate_change_dps": _round_or_none(self.yaw_rate_change_dps, 1),
            "resulted_in_correction": self.resulted_in_correction,
            "severity": self.severity,
        }


@dataclass
class Symptom:
    """A detected coaching-book symptom."""

    symptom_id: str
    description: str
    evidence: dict[str, float]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symptom_id": self.symptom_id,
            "description": self.description,
            "evidence": {k: round(v, 3) for k, v in self.evidence.items()},
            "confidence": round(self.confidence, 2),
        }


@dataclass
class SymptomDetection:
    """All detected symptoms for a corner."""

    corner_id: int
    symptoms: list[Symptom]

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "symptoms": [s.to_dict() for s in self.symptoms],
        }


@dataclass
class WeightTransferInsight:
    """Load transfer data for a corner."""

    corner_id: int
    entry_front_load_pct: float
    entry_rear_load_pct: float
    front_grip_bonus_pct: float
    trail_brake_front_bonus_pct: float
    exit_rear_load_pct: float
    rear_grip_bonus_pct: float
    insight_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "entry_front_load_pct": round(self.entry_front_load_pct, 1),
            "entry_rear_load_pct": round(self.entry_rear_load_pct, 1),
            "front_grip_bonus_pct": round(self.front_grip_bonus_pct, 1),
            "trail_brake_front_bonus_pct": round(self.trail_brake_front_bonus_pct, 1),
            "exit_rear_load_pct": round(self.exit_rear_load_pct, 1),
            "rear_grip_bonus_pct": round(self.rear_grip_bonus_pct, 1),
            "insight_text": self.insight_text,
        }


# ---------------------------------------------------------------------------
# Multi-session trend
# ---------------------------------------------------------------------------

@dataclass
class CornerTrend:
    """Cross-session progression data for a single corner."""

    sessions_tracked: int
    apex_speed_history: list[float]
    theoretical_apex: float
    trend_direction: str      # improving | plateau | regressing
    trend_text: str
    sessions_to_target_estimate: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions_tracked": self.sessions_tracked,
            "apex_speed_history": [round(v, 1) for v in self.apex_speed_history],
            "theoretical_apex": round(self.theoretical_apex, 1),
            "trend_direction": self.trend_direction,
            "trend_text": self.trend_text,
            "sessions_to_target_estimate": self.sessions_to_target_estimate,
        }


# ---------------------------------------------------------------------------
# Per-corner coaching detail
# ---------------------------------------------------------------------------

@dataclass
class CornerCoachingDetail:
    """Rich coaching output for a single corner."""

    corner_id: int
    corner_name: str
    # Diagnosis
    primary_cause: str
    cause_severity: str
    cause_root: str
    symptom_evidence: list[str]
    diagnosis_text: str
    # Coaching
    coaching_tip: str
    progressive_steps: list[str]
    symptom_check: str
    # Quantified impact
    time_loss_corner_s: float
    time_loss_cascade_s: float
    exit_speed_target_kmh: float | None = None
    apex_speed_target_kmh: float | None = None
    entry_speed_target_kmh: float | None = None
    braking_point_target_description: str = ""
    # Physics context
    traction_budget: TractionBudget | None = None
    trail_brake: TrailBrakeAssessment | None = None
    exit_cascade: ExitSpeedCascade | None = None
    weight_transfer_insight: str | None = None
    # Multi-session trend
    trend: CornerTrend | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "corner_name": self.corner_name,
            "primary_cause": self.primary_cause,
            "cause_severity": self.cause_severity,
            "cause_root": self.cause_root,
            "symptom_evidence": self.symptom_evidence,
            "diagnosis_text": self.diagnosis_text,
            "coaching_tip": self.coaching_tip,
            "progressive_steps": self.progressive_steps,
            "symptom_check": self.symptom_check,
            "time_loss_corner_s": round(self.time_loss_corner_s, 3),
            "time_loss_cascade_s": round(self.time_loss_cascade_s, 3),
            "exit_speed_target_kmh": _round_or_none(self.exit_speed_target_kmh, 1),
            "apex_speed_target_kmh": _round_or_none(self.apex_speed_target_kmh, 1),
            "entry_speed_target_kmh": _round_or_none(self.entry_speed_target_kmh, 1),
            "braking_point_target_description": self.braking_point_target_description,
            "traction_budget": self.traction_budget.to_dict() if self.traction_budget else None,
            "trail_brake": self.trail_brake.to_dict() if self.trail_brake else None,
            "exit_cascade": self.exit_cascade.to_dict() if self.exit_cascade else None,
            "weight_transfer_insight": self.weight_transfer_insight,
            "trend": self.trend.to_dict() if self.trend else None,
        }


# ---------------------------------------------------------------------------
# Warm-up protocol
# ---------------------------------------------------------------------------

@dataclass
class WarmUpProtocol:
    """Pre-session warm-up phases."""

    phase_1_laps: int
    phase_1_instruction: str
    phase_2_laps: int
    phase_2_instruction: str
    phase_3_instruction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_1_laps": self.phase_1_laps,
            "phase_1_instruction": self.phase_1_instruction,
            "phase_2_laps": self.phase_2_laps,
            "phase_2_instruction": self.phase_2_instruction,
            "phase_3_instruction": self.phase_3_instruction,
        }


# ---------------------------------------------------------------------------
# Extended coaching output models (backward-compatible with coaching_engine.py)
# ---------------------------------------------------------------------------

@dataclass
class FocusArea:
    """A ranked area where time is being lost — extended with progressive steps."""

    rank: int
    category: str
    time_loss_s: float
    corner_ids: list[int]
    summary: str
    advice: str
    # V3 extensions (Optional)
    progressive_steps: list[str] | None = None
    symptom_diagnosis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "rank": self.rank,
            "category": self.category,
            "time_loss_s": round(self.time_loss_s, 3),
            "corner_ids": self.corner_ids,
            "summary": self.summary,
            "advice": self.advice,
        }
        if self.progressive_steps is not None:
            d["progressive_steps"] = self.progressive_steps
        if self.symptom_diagnosis is not None:
            d["symptom_diagnosis"] = self.symptom_diagnosis
        return d


@dataclass
class Drill:
    """A targeted practice exercise — extended with difficulty progression."""

    rank: int
    title: str
    description: str
    focus_corners: list[int]
    target_metric: str
    target_improvement: str
    lap_count: int
    # V3 extensions (Optional)
    difficulty: str | None = None
    success_criteria: str | None = None
    difficulty_progression: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "rank": self.rank,
            "title": self.title,
            "description": self.description,
            "focus_corners": self.focus_corners,
            "target_metric": self.target_metric,
            "target_improvement": self.target_improvement,
            "lap_count": self.lap_count,
        }
        if self.difficulty is not None:
            d["difficulty"] = self.difficulty
        if self.success_criteria is not None:
            d["success_criteria"] = self.success_criteria
        if self.difficulty_progression is not None:
            d["difficulty_progression"] = self.difficulty_progression
        return d


@dataclass
class ProgressionInsight:
    """Lap-to-lap improvement trend — unchanged from V1."""

    metric: str
    trend: str
    detail: str
    early_value: float
    late_value: float
    change_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "trend": self.trend,
            "detail": self.detail,
            "early_value": round(self.early_value, 3),
            "late_value": round(self.late_value, 3),
            "change_pct": round(self.change_pct, 1),
        }


@dataclass
class SessionCoaching:
    """Complete coaching output for a session — V3 with backward compatibility."""

    # ── Original fields (always present) ──
    session_theme: str
    narrative: str
    strengths: list[str]
    weaknesses: list[str]
    focus_areas: list[FocusArea]
    drills: list[Drill]
    progression: list[ProgressionInsight]
    next_session_goals: list[str]
    confidence: float

    # ── V3 extensions (Optional, backward-compatible) ──
    corner_coaching: list[CornerCoachingDetail] | None = None
    trail_brake_assessment: list[TrailBrakeAssessment] | None = None
    traction_budgets: list[TractionBudget] | None = None
    exit_speed_cascades: list[ExitSpeedCascade] | None = None
    multi_session_trends: list[Any] | None = None
    mental_imagery_prompts: list[str] | None = None
    warm_up_protocol: WarmUpProtocol | None = None
    vehicle_class: str | None = None
    deferred_focus_areas: list[FocusArea] | None = None
    late_apex_reset: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            # Original fields
            "session_theme": self.session_theme,
            "narrative": self.narrative,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "focus_areas": [fa.to_dict() for fa in self.focus_areas],
            "drills": [dr.to_dict() for dr in self.drills],
            "progression": [p.to_dict() for p in self.progression],
            "next_session_goals": self.next_session_goals,
            "confidence": round(self.confidence, 2),
            # V3 fields (always emitted, None when unset)
            "corner_coaching": (
                [c.to_dict() for c in self.corner_coaching]
                if self.corner_coaching is not None else None
            ),
            "trail_brake_assessment": (
                [t.to_dict() for t in self.trail_brake_assessment]
                if self.trail_brake_assessment is not None else None
            ),
            "traction_budgets": (
                [t.to_dict() for t in self.traction_budgets]
                if self.traction_budgets is not None else None
            ),
            "exit_speed_cascades": (
                [e.to_dict() for e in self.exit_speed_cascades]
                if self.exit_speed_cascades is not None else None
            ),
            "multi_session_trends": self.multi_session_trends,
            "mental_imagery_prompts": self.mental_imagery_prompts,
            "warm_up_protocol": (
                self.warm_up_protocol.to_dict()
                if self.warm_up_protocol else None
            ),
            "vehicle_class": self.vehicle_class,
            "deferred_focus_areas": (
                [fa.to_dict() for fa in self.deferred_focus_areas]
                if self.deferred_focus_areas is not None else None
            ),
            "late_apex_reset": self.late_apex_reset,
        }
        return d
