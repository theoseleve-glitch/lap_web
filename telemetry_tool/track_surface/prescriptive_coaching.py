"""
track_surface/prescriptive_coaching.py
--------------------------------------

.. deprecated:: v1.0
    This module has been superseded by the ``track_surface.prescriptive``
    package (typed DTOs, registry-driven patterns, explicit Unregistered
    and Insufficient states). ``scripts/build_ok_raw.py`` now calls
    ``track_surface.prescriptive.generate_coaching_sheet`` instead of
    ``generate_prescriptive_coaching``. This file is retained for:

    - ``WEAKNESS_PLAYBOOK`` — imported by
      ``tests/test_prescriptive_patterns.py`` as the parity anchor against
      the new pattern classes.
    - One-cycle rollback safety.

    Delete in a follow-up once the new package has run in prod without
    regression.

Prescriptive coaching engine — converts canonical Bronze-derived compare
evidence and development intelligence into structured coaching playbooks.

This module is a PURE READ-ONLY consumer of:
  • data.session_compare.corner_packets
  • data.development_intelligence.recurring_weaknesses
  • data.development_intelligence.priority_focuses
  • data.development_intelligence.session_summaries
  • data.development_intelligence.storyline

It does NOT consume beta, diagnostic, Gold Lab, or any non-canonical channel.

Every prescription is:
  • scoped to specific corners and a driving phase
  • backed by measured evidence (speed-derived; no invented sensors)
  • tagged with confidence and explicit limits
  • designed to be validated on the next run

Output: data.prescriptive_coaching (see to_json_dict for schema).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ─────────────────────────────────────────────────────────────────
# Weakness taxonomy — playbook definitions
# ─────────────────────────────────────────────────────────────────

# WEAKNESS_PLAYBOOK is reconstructed from the canonical coaching library at
# import time. The library is the single authoritative source of the
# playbook content, phase tags, and sensor notes. The legacy key
# 'low_minimum_speed' is preserved via the library's consumer_keys mapping
# so downstream code — and the parity tests in test_prescriptive_patterns.py
# — continue to see the same dict shape.
#
# See docs/coaching_ontology_migration.md for full migration rationale.
# Note: this module is already deprecated (its public entry point is the
# track_surface.prescriptive package). The WEAKNESS_PLAYBOOK export is
# retained only as a parity anchor for downstream tests.
from track_surface.coaching_library import (
    weakness_playbook_dict as _library_weakness_playbook_dict,
)


def _legacy_list_shape(d: dict) -> dict:
    """Cast library dict values (which use list types already) into the
    exact legacy shape expected by pre-existing consumers / tests.

    Library already returns lists; kept here as an explicit seam for any
    future shape divergence (e.g. if the library switched to tuples).
    """
    return {
        k: {
            'title': v['title'],
            'phase': v['phase'],
            'likely_causes': list(v['likely_causes']),
            'coaching_actions': list(v['coaching_actions']),
            'driver_cues': list(v['driver_cues']),
            'sensor_note': v['sensor_note'],
        }
        for k, v in d.items()
    }


WEAKNESS_PLAYBOOK = _legacy_list_shape(
    _library_weakness_playbook_dict(consumer='prescriptive_coaching')
)


# ─────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────


@dataclass
class Prescription:
    """One prescriptive coaching item for a specific weakness × corner set."""
    weakness_key: str
    title: str
    corner_ids: list[int]
    phase: str
    severity: str                 # 'high' | 'medium' | 'low'
    recurrence: int
    estimated_cost_ms: float
    likely_causes: list[str]
    coaching_actions: list[str]
    driver_cues: list[str]
    measurable_targets: list[str]
    next_stint_validation: list[str]
    evidence_confidence: float
    portability: str
    data_support: str
    sensor_note: str


@dataclass
class NextRunPlan:
    """Top-priority plan for the next on-track session."""
    technical_focus: str
    execution_focus: str
    validation_metric: str
    anti_overload: str


@dataclass
class ValidationCheck:
    """One measurable check to verify improvement."""
    weakness_key: str
    metric_name: str
    current_value: str
    target_value: str
    measurement_method: str
    corners: list[int]


@dataclass
class PrescriptiveCoaching:
    version: str = '1.0'
    source: str = 'bronze_compare_plus_development_intelligence_only'
    global_focus: list[dict] = field(default_factory=list)
    corner_coaching: list[dict] = field(default_factory=list)
    weakness_playbook_matches: list[dict] = field(default_factory=list)
    next_run_plan: list[dict] = field(default_factory=list)
    validation_checks: list[dict] = field(default_factory=list)
    storyline: list[dict] = field(default_factory=list)
    limits: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Core engine
# ─────────────────────────────────────────────────────────────────


def _severity(cost_ms: float) -> str:
    if cost_ms > 400:
        return 'high'
    if cost_ms > 150:
        return 'medium'
    return 'low'


def _portability(archetypes: list[str], sessions: int) -> str:
    if sessions < 3:
        return 'unknown (too few sessions)'
    if len(set(archetypes)) >= 3:
        return 'likely portable (seen across multiple corner types)'
    if len(set(archetypes)) >= 2:
        return 'possibly portable'
    return 'may be track-specific (single corner type)'


def _build_prescriptions(
    weaknesses: list[dict],
    corner_packets: list[dict],
    sessions_analyzed: int,
) -> list[Prescription]:
    """Build one Prescription per weakness that has a matching playbook."""
    prescriptions: list[Prescription] = []

    for w in weaknesses:
        wk = w.get('behavior_id', '')
        playbook = WEAKNESS_PLAYBOOK.get(wk)
        if playbook is None:
            continue

        corners = w.get('corners_observed', [])
        archetypes = w.get('archetypes_observed', [])
        cost = float(w.get('estimated_time_cost_ms', 0))
        recurrence = int(w.get('occurrence_count', 0))
        trend = w.get('trend', 'unknown')
        conf = float(w.get('confidence', 0))

        # Find the worst corner for this weakness (highest delta).
        worst_corners = []
        for cid in corners:
            pkt = next((p for p in corner_packets if p['corner_id'] == cid), None)
            if pkt:
                worst_corners.append((pkt['time_delta_ms'], cid, pkt))
        worst_corners.sort(reverse=True)

        # Compute adjustment targets from evidence.
        brake_deltas = []
        throttle_deltas = []
        min_speed_deltas = []
        exit_speed_deltas = []
        line_devs = []
        for _, _, pkt in worst_corners:
            ev = pkt.get('evidence', {})
            if ev.get('brake_point_delta_m') is not None:
                brake_deltas.append(float(ev['brake_point_delta_m']))
            if ev.get('throttle_pickup_delta_m') is not None:
                throttle_deltas.append(float(ev['throttle_pickup_delta_m']))
            min_speed_deltas.append(float(ev.get('min_speed_delta_kph', 0) or 0))
            exit_speed_deltas.append(float(ev.get('exit_speed_delta_kph', 0) or 0))
            line_devs.append(float(ev.get('line_deviation_rms_m', 0) or 0))

        med_brake = float(np.median(brake_deltas)) if brake_deltas else 0.0
        med_throttle = float(np.median(throttle_deltas)) if throttle_deltas else 0.0
        med_min_spd = float(np.median(min_speed_deltas)) if min_speed_deltas else 0.0
        med_exit_spd = float(np.median(exit_speed_deltas)) if exit_speed_deltas else 0.0
        med_line = float(np.median(line_devs)) if line_devs else 0.0

        # Parameterize the playbook templates.
        target_kph = max(2.0, abs(med_min_spd) * 0.3)
        brake_adjust_m = max(2.0, abs(med_brake) * 0.4)
        throttle_adjust_m = max(2.0, abs(med_throttle) * 0.4)
        exit_adjust_m = max(2.0, abs(med_exit_spd) * 0.3)

        fmt_vars = {
            'target_kph': f'{target_kph:.0f}',
            'brake_adjust_m': f'{brake_adjust_m:.0f}',
            'throttle_adjust_m': f'{throttle_adjust_m:.0f}',
            'exit_adjust_m': f'{exit_adjust_m:.0f}',
        }

        def _fmt(template_list: list[str]) -> list[str]:
            out = []
            for t in template_list:
                try:
                    out.append(t.format(**fmt_vars))
                except (KeyError, IndexError):
                    out.append(t)
            return out

        # Build measurable targets.
        measurable = []
        if abs(med_min_spd) > 2:
            measurable.append(
                f'Minimum speed at affected corners rises by {abs(med_min_spd) * 0.3:.0f}+ km/h'
            )
        if abs(med_brake) > 3:
            measurable.append(
                f'Brake point moves {abs(med_brake) * 0.3:.0f}+ m later (speed-derived proxy)'
            )
        if abs(med_throttle) > 3:
            measurable.append(
                f'Throttle pickup moves {abs(med_throttle) * 0.3:.0f}+ m earlier (speed-derived proxy)'
            )
        if abs(med_exit_spd) > 2:
            measurable.append(
                f'Exit speed improves by {abs(med_exit_spd) * 0.3:.0f}+ km/h'
            )
        if med_line > 1.0:
            measurable.append(
                f'Line deviation drops below {max(0.5, med_line * 0.6):.1f} m RMS'
            )
        if not measurable:
            measurable.append(f'Time delta at affected corners reduces by {cost * 0.2:.0f}+ ms')

        # Build validation checks.
        validation = []
        if measurable:
            validation.append(f'After 3 focused laps, check: {measurable[0]}')
        validation.append(
            f'If improved: lock in the new approach for the rest of the session'
        )
        validation.append(
            f'If no change after 5 laps: the root cause may be different — reassess'
        )

        # Data support statement.
        data_support = (
            f'{recurrence} occurrences across {len(corners)} corners in '
            f'{sessions_analyzed} sessions. Trend: {trend}. '
            f'Evidence confidence: {conf:.0%}.'
        )

        prescriptions.append(Prescription(
            weakness_key=wk,
            title=playbook['title'],
            corner_ids=corners[:8],
            phase=playbook['phase'],
            severity=_severity(cost),
            recurrence=recurrence,
            estimated_cost_ms=round(cost, 1),
            likely_causes=playbook['likely_causes'],
            coaching_actions=_fmt(playbook['coaching_actions']),
            driver_cues=playbook['driver_cues'],
            measurable_targets=measurable,
            next_stint_validation=validation,
            evidence_confidence=round(conf, 2),
            portability=_portability(archetypes, sessions_analyzed),
            data_support=data_support,
            sensor_note=playbook['sensor_note'],
        ))

    return prescriptions


def _build_corner_coaching(
    corner_packets: list[dict],
    prescriptions: list[Prescription],
) -> list[dict]:
    """Per-corner coaching summary: which prescriptions apply here."""
    corner_coaching = []
    for pkt in corner_packets:
        cid = pkt['corner_id']
        td = pkt['time_delta_ms']
        matching = [p.weakness_key for p in prescriptions if cid in p.corner_ids]
        if not matching and td < 30:
            continue
        corner_coaching.append({
            'corner_id': cid,
            'time_delta_ms': round(td, 1),
            's_entry_m': pkt.get('s_entry_m'),
            's_exit_m': pkt.get('s_exit_m'),
            'applicable_weaknesses': matching,
            'primary_cause': pkt.get('primary_cause', 'unknown'),
            'confidence': pkt.get('confidence', 0.0),
            'summary': (
                f'T{cid}: {td:+.0f} ms. '
                + (f'Linked to: {", ".join(matching)}.' if matching else 'No matched playbook.')
            ),
        })
    return corner_coaching


def _build_next_run_plan(
    prescriptions: list[Prescription],
    priorities: list[dict],
) -> list[dict]:
    """Max 3 priorities + anti-overload note."""
    # Sort by severity then estimated cost.
    ranked = sorted(prescriptions, key=lambda p: -p.estimated_cost_ms)
    plans: list[dict] = []
    if len(ranked) >= 1:
        p = ranked[0]
        plans.append({
            'rank': 1,
            'type': 'technical_focus',
            'title': p.title,
            'corners': p.corner_ids[:4],
            'instruction': p.coaching_actions[0] if p.coaching_actions else 'Review evidence.',
            'validation': p.measurable_targets[0] if p.measurable_targets else 'Check time delta.',
        })
    if len(ranked) >= 2:
        p = ranked[1]
        plans.append({
            'rank': 2,
            'type': 'execution_focus',
            'title': p.title,
            'corners': p.corner_ids[:4],
            'instruction': p.coaching_actions[0] if p.coaching_actions else 'Review evidence.',
            'validation': p.measurable_targets[0] if p.measurable_targets else 'Check time delta.',
        })
    if len(ranked) >= 3:
        p = ranked[2]
        plans.append({
            'rank': 3,
            'type': 'validation_metric',
            'title': p.title,
            'corners': p.corner_ids[:4],
            'instruction': 'Monitor only — do not actively change. Check if it improves passively.',
            'validation': p.measurable_targets[0] if p.measurable_targets else 'Check time delta.',
        })

    # Anti-overload.
    if plans:
        plans.append({
            'rank': 0,
            'type': 'anti_overload',
            'title': 'Do not try to fix everything at once',
            'corners': [],
            'instruction': (
                f'Focus on #{plans[0]["title"]} for the first 3–5 laps. '
                f'Only add the second focus if the first is stable. '
                f'The third item is monitor-only — just observe whether it changes.'
            ),
            'validation': 'If you are thinking about more than 2 things mid-corner, you are overloaded.',
        })

    return plans[:4]  # max 3 priorities + 1 anti-overload


def _build_validation_checks(
    prescriptions: list[Prescription],
    corner_packets: list[dict],
) -> list[dict]:
    """Measurable checks tied to specific corners and metrics."""
    checks: list[dict] = []
    for p in prescriptions:
        for target in p.measurable_targets[:2]:
            best_corners = sorted(
                [cid for cid in p.corner_ids if any(
                    pk['corner_id'] == cid and pk['time_delta_ms'] > 50
                    for pk in corner_packets
                )],
            )[:3]
            if not best_corners:
                best_corners = p.corner_ids[:3]
            checks.append({
                'weakness_key': p.weakness_key,
                'metric_name': target.split(':')[0] if ':' in target else target[:40],
                'target_description': target,
                'corners': best_corners,
                'measurement_method': p.sensor_note,
                'confidence': p.evidence_confidence,
            })
    return checks


def _build_storyline(
    prescriptions: list[Prescription],
    dev_storyline: list[dict],
    sessions_analyzed: int,
) -> list[dict]:
    """Prescriptive narrative layer — evidence-backed, not motivational."""
    lines: list[dict] = []

    if prescriptions:
        top = prescriptions[0]
        lines.append({
            'type': 'primary_focus',
            'text': (
                f'The highest-value change right now is addressing '
                f'"{top.title}" — it costs ~{top.estimated_cost_ms:.0f} ms per '
                f'occurrence across {len(top.corner_ids)} corners and is '
                f'{top.severity} severity.'
            ),
            'confidence': top.evidence_confidence,
        })

    improving = [p for p in prescriptions if 'improving' in (p.data_support or '')]
    flat = [p for p in prescriptions if 'flat' in (p.data_support or '')]
    if improving:
        lines.append({
            'type': 'progress',
            'text': (
                f'Already improving: {", ".join(p.title for p in improving[:2])}. '
                f'Continue current approach on these.'
            ),
            'confidence': 0.7,
        })
    if flat:
        lines.append({
            'type': 'plateau',
            'text': (
                f'Stalled: {", ".join(p.title for p in flat[:2])}. '
                f'A technique change may be needed — current approach is not producing progress.'
            ),
            'confidence': 0.6,
        })

    if sessions_analyzed < 3:
        lines.append({
            'type': 'data_warning',
            'text': (
                f'Only {sessions_analyzed} session(s) analyzed. '
                f'Trend and portability claims need 3+ sessions to be reliable.'
            ),
            'confidence': 1.0,
        })

    return lines


def _build_limits(sessions_analyzed: int, n_laps: int) -> dict:
    """Explicit declaration of what the coaching can and cannot claim."""
    return {
        'sessions_analyzed': sessions_analyzed,
        'laps_analyzed': n_laps,
        'brake_data': 'speed-derived deceleration proxy only (no brake pressure sensor)',
        'throttle_data': 'speed-derived acceleration proxy only (no CAN throttle sensor)',
        'steering_data': 'not available — rotation and commitment inferred from speed + line',
        'cross_track_portability': (
            'unknown — all data is from a single track'
            if sessions_analyzed <= 10
            else 'partially assessed'
        ),
        'weather_conditions': 'not tracked — cannot separate grip from technique changes',
        'reference_basis': 'session-overall best lap (not per-sector composite)',
        'confidence_floor': (
            'Prescriptions with < 3 supporting occurrences are omitted. '
            'All stated confidence is relative to available evidence, not absolute.'
        ),
    }


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def generate_prescriptive_coaching(
    corner_packets: list[dict],
    weaknesses: list[dict],
    priorities: list[dict],
    dev_storyline: list[dict],
    sessions_analyzed: int = 1,
    laps_analyzed: int = 0,
    track_name: str = '',
) -> PrescriptiveCoaching:
    """Main entry point.

    All inputs come from canonical Bronze-derived outputs only.
    """
    if not corner_packets and not weaknesses:
        return PrescriptiveCoaching(
            limits=_build_limits(sessions_analyzed, laps_analyzed),
            storyline=[{
                'type': 'insufficient_data',
                'text': 'No compare evidence or weakness patterns available.',
                'confidence': 1.0,
            }],
        )

    prescriptions = _build_prescriptions(weaknesses, corner_packets, sessions_analyzed)
    # Sort by estimated cost descending.
    prescriptions.sort(key=lambda p: -p.estimated_cost_ms)

    corner_coaching = _build_corner_coaching(corner_packets, prescriptions)
    next_plan = _build_next_run_plan(prescriptions, priorities)
    validation = _build_validation_checks(prescriptions, corner_packets)
    storyline = _build_storyline(prescriptions, dev_storyline, sessions_analyzed)
    limits = _build_limits(sessions_analyzed, laps_analyzed)

    global_focus = []
    for i, p in enumerate(prescriptions[:3]):
        global_focus.append({
            'rank': i + 1,
            'weakness_key': p.weakness_key,
            'title': p.title,
            'severity': p.severity,
            'estimated_cost_ms': p.estimated_cost_ms,
            'corners': p.corner_ids[:6],
            'phase': p.phase,
            'confidence': p.evidence_confidence,
        })

    playbook_matches = []
    for p in prescriptions:
        playbook_matches.append({
            'weakness_key': p.weakness_key,
            'title': p.title,
            'matched_playbook': p.weakness_key in WEAKNESS_PLAYBOOK,
            'corner_ids': p.corner_ids,
            'severity': p.severity,
            'coaching_actions': p.coaching_actions,
            'driver_cues': p.driver_cues,
            'measurable_targets': p.measurable_targets,
            'likely_causes': p.likely_causes,
            'sensor_note': p.sensor_note,
            'portability': p.portability,
            'data_support': p.data_support,
        })

    return PrescriptiveCoaching(
        version='1.0',
        source='bronze_compare_plus_development_intelligence_only',
        global_focus=global_focus,
        corner_coaching=corner_coaching,
        weakness_playbook_matches=playbook_matches,
        next_run_plan=next_plan,
        validation_checks=validation,
        storyline=storyline,
        limits=limits,
    )


def to_json_dict(pc: PrescriptiveCoaching) -> dict:
    return {
        'version': pc.version,
        'source': pc.source,
        'global_focus': pc.global_focus,
        'corner_coaching': pc.corner_coaching,
        'weakness_playbook_matches': pc.weakness_playbook_matches,
        'next_run_plan': pc.next_run_plan,
        'validation_checks': pc.validation_checks,
        'storyline': pc.storyline,
        'limits': pc.limits,
    }
