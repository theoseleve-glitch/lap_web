"""
track_surface/coaching_intelligence.py
--------------------------------------
Coaching Intelligence engine — transforms compare evidence + development
intelligence into actionable, evidence-backed coaching interventions.

This is the layer that turns "what happened" into "what to change next."

Every output is:
  - scoped to specific corner(s) and driving phase
  - backed by measured evidence (not templates)
  - ranked by expected gain x confidence x trainability
  - honest about uncertainty

The engine is a pure read-only consumer of existing canonical outputs.
It does NOT recalculate physics or modify Bronze/Silver/Gold data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ─────────────────────────────────────────────────────────────────
# Intervention classes — each has detection logic + coaching template
# ─────────────────────────────────────────────────────────────────

PHASES = ('entry', 'brake_release', 'apex', 'exit', 'straight')

# INTERVENTION_CLASSES is reconstructed from the canonical coaching library
# at import time. The library is the single authoritative source of pattern
# meaning, trainability, detection logic, and confidence functions. Legacy
# keys ('apex_speed_deficit', 'late_throttle_application', 'path_variance')
# are preserved via the library's consumer_keys mapping so downstream code
# — and existing tests — continue to see the same interface.
#
# See docs/coaching_ontology_migration.md for the migration rationale and
# the four-way additive compatibility story.
from track_surface.coaching_library import (
    intervention_classes_dict as _library_intervention_classes_dict,
)

INTERVENTION_CLASSES = _library_intervention_classes_dict(consumer='coaching_intelligence')


# ─────────────────────────────────────────────────────────────────
# Coaching action dataclass
# ─────────────────────────────────────────────────────────────────


@dataclass
class CoachingAction:
    id: str
    title: str
    problem_type: str
    corners: list[int]
    phase: str
    evidence: dict
    coach_hypothesis: str
    driver_instruction: str
    attempt_protocol: str
    success_metric: str
    estimated_gain_ms: float
    trainability: float
    confidence: float
    priority_score: float
    status: str             # 'focus_now' | 'secondary' | 'monitor'
    canonical_basis: bool = True


# ─────────────────────────────────────────────────────────────────
# Intervention detection
# ─────────────────────────────────────────────────────────────────


def _detect_interventions(
    corner_packets: list[dict],
    weaknesses: list[dict],
) -> list[dict]:
    """Detect intervention instances from corner evidence."""
    interventions: list[dict] = []

    for pkt in corner_packets:
        ev = pkt.get('evidence', {})
        td = pkt.get('time_delta_ms', 0)
        if td <= 10:    # not a meaningful loss
            continue

        for int_id, defn in INTERVENTION_CLASSES.items():
            if defn['detect'](ev):
                conf = defn['confidence_fn'](ev, pkt)
                interventions.append({
                    'intervention_type': int_id,
                    'corner_id': pkt['corner_id'],
                    'phase': defn['phase'],
                    'time_delta_ms': td,
                    'confidence': conf,
                    'trainability': defn['trainability'],
                    'evidence': ev,
                    'label': defn['label'],
                    'pkt': pkt,
                })

    return interventions


def _aggregate_into_actions(
    interventions: list[dict],
    weaknesses: list[dict],
    sessions_analyzed: int,
) -> list[CoachingAction]:
    """Group interventions by type and produce coaching actions."""
    # Group by intervention type
    by_type: dict[str, list[dict]] = {}
    for inv in interventions:
        by_type.setdefault(inv['intervention_type'], []).append(inv)

    actions: list[CoachingAction] = []
    for int_type, instances in by_type.items():
        defn = INTERVENTION_CLASSES[int_type]
        corners = sorted(set(inv['corner_id'] for inv in instances))
        total_gain = sum(inv['time_delta_ms'] for inv in instances)
        mean_gain = total_gain / len(instances)
        best_conf = max(inv['confidence'] for inv in instances)

        # Cross-reference with development intelligence weaknesses.
        recurrence = 0
        trend = 'unknown'
        for w in weaknesses:
            # Match by overlapping corners and behavior similarity
            w_corners = set(w.get('corners_observed', []))
            overlap = len(set(corners) & w_corners)
            if overlap >= 1:
                recurrence = max(recurrence, w.get('occurrence_count', 0))
                trend = w.get('trend', trend)

        # Priority scoring
        recurrence_factor = min(1.0, recurrence / 100.0) if recurrence else 0.3
        priority = (
            mean_gain * 0.001          # normalize ms to ~seconds scale
            * len(corners)             # more affected corners = higher priority
            * best_conf
            * defn['trainability']
            * (1.0 + 0.3 * recurrence_factor)
        )

        # Generate evidence-backed coaching language.
        hyp, instr, protocol, metric = _generate_coaching_language(
            int_type, defn, instances, corners, trend,
        )

        actions.append(CoachingAction(
            id=f'action_{int_type}_{corners[0]}',
            title=defn['label'],
            problem_type=int_type,
            corners=corners,
            phase=defn['phase'],
            evidence={
                'time_cost_ms': round(total_gain, 1),
                'mean_per_corner_ms': round(mean_gain, 1),
                'affected_corners': len(corners),
                'recurrence': recurrence,
                'trend': trend,
                'confidence': round(best_conf, 2),
                'supporting_metrics': _extract_supporting_metrics(instances),
            },
            coach_hypothesis=hyp,
            driver_instruction=instr,
            attempt_protocol=protocol,
            success_metric=metric,
            estimated_gain_ms=round(total_gain * 0.3, 1),  # conservative: 30% of theoretical
            trainability=defn['trainability'],
            confidence=round(best_conf, 2),
            priority_score=round(priority, 3),
            status='focus_now',
            canonical_basis=True,
        ))

    # Rank by priority and assign status.
    actions.sort(key=lambda a: -a.priority_score)
    for i, a in enumerate(actions):
        if i == 0:
            a.status = 'focus_now'
        elif i <= 2:
            a.status = 'secondary'
        else:
            a.status = 'monitor'

    return actions


def _extract_supporting_metrics(instances: list[dict]) -> dict:
    """Aggregate key metrics across instances of an intervention."""
    ms_deltas = [inv['evidence'].get('min_speed_delta_kph', 0) or 0 for inv in instances]
    brake_deltas = [inv['evidence'].get('brake_point_delta_m') for inv in instances
                    if inv['evidence'].get('brake_point_delta_m') is not None]
    throttle_deltas = [inv['evidence'].get('throttle_pickup_delta_m') for inv in instances
                       if inv['evidence'].get('throttle_pickup_delta_m') is not None]
    exit_deltas = [inv['evidence'].get('exit_speed_delta_kph', 0) or 0 for inv in instances]
    line_devs = [inv['evidence'].get('line_deviation_rms_m', 0) or 0 for inv in instances]

    return {
        'median_min_speed_delta_kph': round(float(np.median(ms_deltas)), 1) if ms_deltas else None,
        'median_brake_delta_m': round(float(np.median(brake_deltas)), 1) if brake_deltas else None,
        'median_throttle_delta_m': round(float(np.median(throttle_deltas)), 1) if throttle_deltas else None,
        'median_exit_speed_delta_kph': round(float(np.median(exit_deltas)), 1) if exit_deltas else None,
        'median_line_deviation_m': round(float(np.median(line_devs)), 2) if line_devs else None,
    }


# ─────────────────────────────────────────────────────────────────
# Coaching language generation — evidence-driven, not template
# ─────────────────────────────────────────────────────────────────


def _generate_coaching_language(
    int_type: str,
    defn: dict,
    instances: list[dict],
    corners: list[int],
    trend: str,
) -> tuple[str, str, str, str]:
    """Generate (hypothesis, instruction, protocol, success_metric).

    Every sentence references actual measured values from the evidence.
    """
    metrics = _extract_supporting_metrics(instances)
    corner_str = ', '.join(f'T{c}' for c in corners[:5])
    n_corners = len(corners)
    total_ms = sum(inv['time_delta_ms'] for inv in instances)
    mean_ms = total_ms / max(len(instances), 1)
    ms_delta = metrics.get('median_min_speed_delta_kph')
    brake_delta = metrics.get('median_brake_delta_m')
    throttle_delta = metrics.get('median_throttle_delta_m')
    exit_delta = metrics.get('median_exit_speed_delta_kph')
    line_dev = metrics.get('median_line_deviation_m')

    # ── Per-type coaching ──

    if int_type == 'entry_speed_surrender':
        hyp = (
            f'At {corner_str}, braking starts '
            f'{abs(brake_delta):.0f} m earlier than reference '
            f'and minimum speed is {abs(ms_delta):.1f} km/h lower. '
            f'The speed is being given away on entry before the corner demands it.'
        )
        instr = (
            f'Delay the initial brake application by {min(10, abs(brake_delta) * 0.5):.0f} m. '
            f'Do NOT brake later by guessing — use a visual reference point '
            f'{abs(brake_delta) * 0.3:.0f}–{abs(brake_delta) * 0.5:.0f} m closer to the corner. '
            f'Maintain the same peak brake pressure.'
        )
        protocol = (
            f'On the next 3 laps, focus ONLY on {corner_str}. '
            f'Move your braking reference closer by one kart-length at a time. '
            f'If the kart feels stable, hold; if it slides, back off one step.'
        )
        metric = (
            f'Success = brake point moves {abs(brake_delta) * 0.3:.0f}+ m later '
            f'AND minimum speed rises by {abs(ms_delta) * 0.3:.0f}+ km/h '
            f'with no exit speed loss.'
        )

    elif int_type == 'conservative_brake_release':
        hyp = (
            f'At {corner_str}, the brake point is close to reference '
            f'but minimum speed is {abs(ms_delta):.1f} km/h lower. '
            f'The likely cause is holding brake pressure too long through the '
            f'release phase, scrubbing speed before apex.'
        )
        instr = (
            f'Focus on the RELEASE, not the initial application. '
            f'Begin trailing off brake pressure {max(3, abs(ms_delta) * 0.4):.0f} m '
            f'earlier before the apex, aiming to arrive at minimum speed with '
            f'less pedal. The goal is a smoother, longer release — not less braking overall.'
        )
        protocol = (
            f'On the next 3 laps, treat {corner_str} as "release practice" corners. '
            f'Consciously start releasing pressure when you begin to turn in. '
            f'If the kart understeers, you released too much too early; if it '
            f'still scrubs speed, hold a touch more through mid-corner.'
        )
        metric = (
            f'Success = minimum speed rises by {abs(ms_delta) * 0.3:.0f}+ km/h '
            f'at {corner_str} without moving the brake point earlier.'
        )

    elif int_type == 'apex_speed_deficit':
        hyp = (
            f'At {corner_str}, minimum speed is {abs(ms_delta):.1f} km/h lower than reference '
            f'despite brake and throttle timing being close to normal. '
            f'The speed loss is concentrated around the apex — likely a commitment '
            f'or rotation issue rather than a pedal-timing problem.'
        )
        instr = (
            f'Protect the minimum speed by carrying {abs(ms_delta) * 0.3:.0f}–{abs(ms_delta) * 0.5:.0f} km/h '
            f'more through the middle of the corner. This means less steering input '
            f'at turn-in (wider entry) or more confidence through the loaded phase.'
        )
        protocol = (
            f'On the next 3 laps, at {corner_str}, focus on keeping speed UP through '
            f'the middle of the corner rather than on braking or throttle. '
            f'Use a wider entry line if needed to maintain flow.'
        )
        metric = (
            f'Success = apex minimum speed rises by {abs(ms_delta) * 0.3:.0f}+ km/h '
            f'with line deviation stable or decreasing.'
        )

    elif int_type == 'late_throttle_application':
        hyp = (
            f'At {corner_str}, throttle pickup is '
            f'{abs(throttle_delta):.0f} m later than reference. '
            f'The corner is being driven correctly up to the apex, but '
            f'power application is delayed, costing exit speed.'
        )
        instr = (
            f'Begin initial throttle application {abs(throttle_delta) * 0.5:.0f}–'
            f'{abs(throttle_delta) * 0.7:.0f} m earlier. '
            f'Start with partial throttle (30–50%) — the goal is earlier '
            f'commitment, not harder acceleration.'
        )
        protocol = (
            f'On the next 3 laps, treat {corner_str} as "early throttle" corners. '
            f'As soon as you begin to unwind steering, introduce throttle. '
            f'If the kart pushes wide, reduce initial throttle percentage, '
            f'but keep the APPLICATION POINT early.'
        )
        metric = (
            f'Success = throttle pickup moves {abs(throttle_delta) * 0.3:.0f}+ m earlier '
            f'AND exit speed improves by {abs(exit_delta) * 0.3:.0f}+ km/h.'
        )

    elif int_type == 'weak_exit_build':
        hyp = (
            f'At {corner_str}, exit speed is {abs(exit_delta):.1f} km/h lower '
            f'than reference despite similar throttle timing. '
            f'The speed build out of the corner is too gradual — possibly from '
            f'a tighter exit line, excess steering angle, or insufficient commitment.'
        )
        instr = (
            f'Open the exit earlier: begin straightening the wheel '
            f'{max(3, abs(exit_delta) * 0.4):.0f} m before you normally would. '
            f'Use the full track width on exit. '
            f'Every meter of extra straightening translates to exit speed.'
        )
        protocol = (
            f'On the next 3 laps, at {corner_str}, look at the exit kerb or '
            f'track edge earlier than usual and let the kart run wide. '
            f'If exit speed improves but entry suffers, prioritize exit — '
            f'it carries onto the following straight.'
        )
        metric = (
            f'Success = exit speed improves by {abs(exit_delta) * 0.3:.0f}+ km/h '
            f'at {corner_str} with no increase in line deviation.'
        )

    elif int_type == 'path_variance':
        hyp = (
            f'At {corner_str}, the driven line deviates by {line_dev:.1f} m RMS '
            f'from the reference. This path inconsistency makes it harder to '
            f'optimize speed because the corner geometry changes lap to lap.'
        )
        instr = (
            f'Pick ONE line through {corner_str} and repeat it exactly. '
            f'Use a fixed turn-in point, apex reference, and exit target. '
            f'Do not experiment with multiple lines during the same session.'
        )
        protocol = (
            f'On the next 5 laps, drive {corner_str} with maximum line '
            f'repeatability as the ONLY goal. Speed is secondary. '
            f'Once the line is consistent, speed improvements will come from '
            f'adding commitment within a stable geometry.'
        )
        metric = (
            f'Success = line deviation drops below {max(0.3, line_dev * 0.5):.1f} m RMS '
            f'over 5+ consecutive laps.'
        )

    else:
        hyp = f'Pattern detected at {corner_str}: {defn["label"]}.'
        instr = 'Review corner evidence for specific changes.'
        protocol = f'Focus on {corner_str} for the next 3 laps.'
        metric = f'Reduce time delta by {mean_ms * 0.2:.0f}+ ms at {corner_str}.'

    # Append trend context if available.
    if trend == 'improving':
        hyp += ' This area is already improving.'
    elif trend == 'flat':
        hyp += ' This area has been flat — a new approach may be needed.'
    elif trend == 'regressing':
        hyp += ' This area is getting worse — address it before it compounds.'

    return hyp, instr, protocol, metric


# ─────────────────────────────────────────────────────────────────
# Corner family analysis
# ─────────────────────────────────────────────────────────────────


def _detect_corner_families(
    actions: list[CoachingAction],
    weaknesses: list[dict],
) -> list[dict]:
    """Detect when the same intervention type spans 3+ corners → systemic habit."""
    families = []
    for a in actions:
        if len(a.corners) >= 3:
            families.append({
                'problem_type': a.problem_type,
                'corners': a.corners,
                'label': f'Systemic: {a.title} across {len(a.corners)} corners',
                'implication': (
                    'This is likely a driver habit, not a corner-specific issue. '
                    'Fixing it in any ONE corner should transfer to others.'
                ),
            })
    return families


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


@dataclass
class CoachingIntelligence:
    version: str = '1.0'
    actions: list[CoachingAction] = field(default_factory=list)
    corner_families: list[dict] = field(default_factory=list)
    focus_summary: str = ''
    secondary_summary: str = ''
    monitor_summary: str = ''
    confidence_note: str = ''
    sessions_context: str = ''


def generate_coaching(
    corner_packets: list[dict],
    weaknesses: list[dict],
    priorities: list[dict],
    sessions_analyzed: int = 1,
    track_name: str = '',
) -> CoachingIntelligence:
    """Main entry point: produce structured coaching from evidence.

    Parameters
    ----------
    corner_packets : from data.session_compare.corner_packets
    weaknesses : from data.development_intelligence.recurring_weaknesses
    priorities : from data.development_intelligence.priority_focuses
    sessions_analyzed : number of sessions in the development profile
    track_name : for context in coaching text
    """
    if not corner_packets:
        return CoachingIntelligence(
            confidence_note='No corner evidence available.',
        )

    interventions = _detect_interventions(corner_packets, weaknesses)
    actions = _aggregate_into_actions(interventions, weaknesses, sessions_analyzed)
    families = _detect_corner_families(actions, weaknesses)

    focus = [a for a in actions if a.status == 'focus_now']
    secondary = [a for a in actions if a.status == 'secondary']
    monitor = [a for a in actions if a.status == 'monitor']

    focus_sum = ''
    if focus:
        f = focus[0]
        focus_sum = (
            f'PRIMARY: {f.title} at {", ".join("T" + str(c) for c in f.corners[:4])}. '
            f'Estimated recoverable: {f.estimated_gain_ms:.0f} ms. '
            f'{f.driver_instruction}'
        )

    sec_sum = ''
    if secondary:
        names = '; '.join(f'{a.title} ({", ".join("T" + str(c) for c in a.corners[:3])})'
                          for a in secondary[:2])
        sec_sum = f'NEXT: {names}.'

    mon_sum = ''
    if monitor:
        mon_sum = f'{len(monitor)} additional pattern(s) detected but lower priority.'

    conf_note = ''
    if sessions_analyzed < 3:
        conf_note = (
            f'Based on {sessions_analyzed} session(s). '
            f'Trend reliability improves with 3+ sessions.'
        )
    elif sessions_analyzed >= 5:
        conf_note = (
            f'Based on {sessions_analyzed} sessions at {track_name}. '
            f'Pattern evidence is strong for this track.'
        )

    return CoachingIntelligence(
        version='1.0',
        actions=actions,
        corner_families=families,
        focus_summary=focus_sum,
        secondary_summary=sec_sum,
        monitor_summary=mon_sum,
        confidence_note=conf_note,
        sessions_context=f'{sessions_analyzed} sessions at {track_name}',
    )


def to_json_dict(ci: CoachingIntelligence) -> dict:
    """JSON-safe serialization."""
    def _act(a: CoachingAction) -> dict:
        return {
            'id': a.id,
            'title': a.title,
            'problem_type': a.problem_type,
            'corners': a.corners,
            'phase': a.phase,
            'evidence': a.evidence,
            'coach_hypothesis': a.coach_hypothesis,
            'driver_instruction': a.driver_instruction,
            'attempt_protocol': a.attempt_protocol,
            'success_metric': a.success_metric,
            'estimated_gain_ms': a.estimated_gain_ms,
            'trainability': a.trainability,
            'confidence': a.confidence,
            'priority_score': a.priority_score,
            'status': a.status,
            'canonical_basis': a.canonical_basis,
        }

    return {
        'version': ci.version,
        'actions': [_act(a) for a in ci.actions],
        'corner_families': ci.corner_families,
        'focus_summary': ci.focus_summary,
        'secondary_summary': ci.secondary_summary,
        'monitor_summary': ci.monitor_summary,
        'confidence_note': ci.confidence_note,
        'sessions_context': ci.sessions_context,
    }
