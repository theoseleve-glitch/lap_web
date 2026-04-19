"""
track_surface/driver_development.py
------------------------------------
Driver Development Intelligence engine.

Ingests per-corner compare packets from multiple laps × multiple sessions
and produces:

    • Recurring weakness/strength profiles
    • Session-to-session trend signals
    • Corner-archetype classification
    • Priority training focuses
    • Development storyline statements

Every claim is backed by repeated measured evidence. Sparse-data cases
degrade to explicit "insufficient evidence" rather than fake confidence.

The engine is deterministic and pure — it never mutates input data.

Invariant: canonical Bronze signals only. Gold Lab signals may appear as
metadata enrichment but never redefine a progress conclusion.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ─────────────────────────────────────────────────────────────────
# Corner archetypes
# ─────────────────────────────────────────────────────────────────

CORNER_ARCHETYPES = (
    'slow_hairpin',        # peak speed < 35 kph, high curvature
    'slow_90deg',          # peak speed 35-45 kph, moderate curvature
    'medium_speed',        # 45-60 kph
    'fast_corner',         # > 60 kph
    'chicane',             # rapid curvature sign change (adjacent corners)
    'traction_exit',       # speed builds strongly after apex
)


def classify_corner_archetype(
    min_speed_kph: float,
    peak_curvature: float,
    corner_length_m: float,
) -> str:
    if min_speed_kph < 35.0 and abs(peak_curvature) > 0.06:
        return 'slow_hairpin'
    if min_speed_kph < 45.0:
        return 'slow_90deg'
    if min_speed_kph < 60.0:
        return 'medium_speed'
    return 'fast_corner'


# ─────────────────────────────────────────────────────────────────
# Feature schema — what we extract per (lap, corner)
# ─────────────────────────────────────────────────────────────────


@dataclass
class CornerFeatures:
    """Per-corner features extracted from a single lap's compare packet."""
    lap_id: str
    session_id: str
    corner_id: int
    archetype: str
    time_delta_ms: float
    min_speed_delta_kph: float
    brake_point_delta_m: Optional[float]
    throttle_pickup_delta_m: Optional[float]
    exit_speed_delta_kph: float
    line_deviation_m: float
    primary_cause: str
    confidence: float

    @classmethod
    def from_corner_packet(
        cls,
        pkt: dict,
        lap_id: str,
        session_id: str,
        archetype: str,
    ) -> 'CornerFeatures':
        ev = pkt.get('evidence', {})
        return cls(
            lap_id=lap_id,
            session_id=session_id,
            corner_id=pkt['corner_id'],
            archetype=archetype,
            time_delta_ms=float(pkt.get('time_delta_ms', 0.0)),
            min_speed_delta_kph=float(ev.get('min_speed_delta_kph', 0.0) or 0.0),
            brake_point_delta_m=ev.get('brake_point_delta_m'),
            throttle_pickup_delta_m=ev.get('throttle_pickup_delta_m'),
            exit_speed_delta_kph=float(ev.get('exit_speed_delta_kph', 0.0) or 0.0),
            line_deviation_m=float(ev.get('line_deviation_rms_m', 0.0) or 0.0),
            primary_cause=pkt.get('primary_cause', 'uncertain'),
            confidence=float(pkt.get('confidence', 0.0)),
        )


# ─────────────────────────────────────────────────────────────────
# Behavioral pattern detection
# ─────────────────────────────────────────────────────────────────


# Named weakness/strength categories with detection logic.
#
# Since v2.0.0 of the coaching library (see docs/coaching_ontology_migration.md)
# this dict is reconstructed from ``track_surface.coaching_library`` at import
# time. The library is now the single source of truth for pattern meaning,
# trainability, and detection logic. Consumer-specific legacy keys such as
# 'low_minimum_speed' (alias of canonical 'apex_low_speed') are preserved via
# the library's ``consumer_keys`` mapping.
from track_surface.coaching_library import (
    behavior_defs_dict as _library_behavior_defs_dict,
)

BEHAVIOR_DEFS = _library_behavior_defs_dict(consumer='driver_development')


@dataclass
class BehaviorPattern:
    """A recurring behavioral pattern detected across laps."""
    behavior_id: str
    label: str
    is_weakness: bool
    occurrence_count: int
    total_laps: int
    sessions_observed: list[str]
    corners_observed: list[int]
    archetypes_observed: list[str]
    estimated_time_cost_ms: float   # median time delta across occurrences
    trend: str                      # 'improving', 'flat', 'regressing', 'unstable', 'insufficient'
    trend_evidence: str
    confidence: float
    portability: str                # 'track_specific', 'likely_portable', 'unknown'
    explanation: str


def _detect_patterns(
    features: list[CornerFeatures],
    session_ids: list[str],
) -> list[BehaviorPattern]:
    """Scan all corner features for recurring behavioral patterns."""
    patterns: list[BehaviorPattern] = []
    total_laps = len(set(cf.lap_id for cf in features))
    session_set = sorted(set(session_ids))

    for behav_id, defn in BEHAVIOR_DEFS.items():
        # Find all occurrences.
        hits = [cf for cf in features if defn['test'](cf)]
        if len(hits) < 3:
            continue  # not enough evidence to call it recurring

        sessions_hit = sorted(set(cf.session_id for cf in hits))
        corners_hit = sorted(set(cf.corner_id for cf in hits))
        archetypes_hit = sorted(set(cf.archetype for cf in hits))

        # Is it a weakness or strength?
        is_weakness = defn['trainable'] > 0.0

        # Time cost: median of time_delta_ms across occurrences.
        time_costs = [cf.time_delta_ms for cf in hits]
        estimated_cost = float(np.median(time_costs))

        # Trend: does the metric improve across sessions?
        trend, trend_ev = _compute_trend(hits, session_set, defn)

        # Confidence: from occurrence rate and session spread.
        occurrence_rate = len(hits) / max(total_laps * len(corners_hit) / 9.0, 1.0)
        session_spread = len(sessions_hit) / max(len(session_set), 1)
        confidence = min(1.0, 0.4 * min(1.0, len(hits) / 10.0)
                         + 0.3 * occurrence_rate
                         + 0.3 * session_spread)

        # Portability: if it appears across many corner archetypes, it's
        # likely a driver habit (portable). If only in one archetype, it
        # may be track-specific.
        if len(archetypes_hit) >= 3:
            portability = 'likely_portable'
        elif len(archetypes_hit) >= 2:
            portability = 'unknown'
        else:
            portability = 'track_specific'
        # With only one track we can't claim portability confidently.
        if len(set(session_ids)) <= 5:
            portability = 'unknown (single track dataset)'

        explanation = _build_pattern_explanation(
            defn['label'], len(hits), total_laps, sessions_hit,
            corners_hit, archetypes_hit, estimated_cost, trend,
        )

        patterns.append(BehaviorPattern(
            behavior_id=behav_id,
            label=defn['label'],
            is_weakness=is_weakness,
            occurrence_count=len(hits),
            total_laps=total_laps,
            sessions_observed=sessions_hit,
            corners_observed=corners_hit,
            archetypes_observed=archetypes_hit,
            estimated_time_cost_ms=round(estimated_cost, 1),
            trend=trend,
            trend_evidence=trend_ev,
            confidence=round(confidence, 2),
            portability=portability,
            explanation=explanation,
        ))

    return patterns


def _compute_trend(
    hits: list[CornerFeatures],
    session_order: list[str],
    defn: dict,
) -> tuple[str, str]:
    """Compute per-session average metric and detect linear trend."""
    if len(session_order) < 3:
        return 'insufficient', f'only {len(session_order)} sessions'

    per_session: dict[str, list[float]] = defaultdict(list)
    for cf in hits:
        val = getattr(cf, defn['metric_key'].replace('_delta', '_delta'), None)
        if val is None:
            val = cf.time_delta_ms
        if isinstance(val, (int, float)) and math.isfinite(val):
            per_session[cf.session_id].append(float(val))

    # Build session-ordered averages.
    sess_means: list[float] = []
    for sid in session_order:
        vals = per_session.get(sid, [])
        if vals:
            sess_means.append(float(np.median(vals)))

    if len(sess_means) < 3:
        return 'insufficient', f'{len(sess_means)} session points'

    # Linear regression over session index.
    x = np.arange(len(sess_means), dtype=float)
    y = np.array(sess_means)
    slope = float(np.polyfit(x, y, 1)[0])

    # Interpret: for weaknesses where "positive metric = bad" or
    # "negative metric = bad", check slope direction.
    direction = defn.get('direction', '')
    if direction == 'positive_is_bad':
        # Decreasing slope = improving (metric getting smaller)
        if slope < -0.5:
            return 'improving', f'slope {slope:.2f}/session'
        elif slope > 0.5:
            return 'regressing', f'slope {slope:.2f}/session'
    elif direction in ('negative_is_bad', 'positive_is_good'):
        # Increasing slope = improving
        if slope > 0.5:
            return 'improving', f'slope {slope:.2f}/session'
        elif slope < -0.5:
            return 'regressing', f'slope {slope:.2f}/session'

    # Check stability
    std = float(np.std(sess_means))
    if std < 1.0:
        return 'flat', f'std {std:.2f} across sessions'
    return 'unstable', f'std {std:.2f}, slope {slope:.2f}'


def _build_pattern_explanation(
    label: str, count: int, total_laps: int,
    sessions: list[str], corners: list[int],
    archetypes: list[str], cost_ms: float, trend: str,
) -> str:
    rate = count / max(total_laps, 1) * 100
    parts = [
        f'"{label}" appeared in {count} of {total_laps} laps ({rate:.0f}%) '
        f'across {len(sessions)} session(s).',
    ]
    if len(corners) <= 3:
        parts.append(f'Most prominent at Turn(s) {", ".join(str(c) for c in corners)}.')
    else:
        parts.append(f'Observed at {len(corners)} different corners.')
    if len(archetypes) > 1:
        parts.append(f'Spans corner types: {", ".join(archetypes)}.')
    if abs(cost_ms) > 10:
        parts.append(f'Median time cost: {cost_ms:+.0f} ms per occurrence.')
    parts.append(f'Trend: {trend}.')
    return ' '.join(parts)


# ─────────────────────────────────────────────────────────────────
# Priority ranking
# ─────────────────────────────────────────────────────────────────


@dataclass
class TrainingFocus:
    rank: int
    behavior_id: str
    label: str
    priority_score: float
    time_cost_ms: float
    recurrence_rate: float
    confidence: float
    why_it_matters: str
    where_it_shows: str
    what_defines_it: str
    success_next_session: str


def _rank_priorities(
    patterns: list[BehaviorPattern],
    n: int = 3,
) -> list[TrainingFocus]:
    """Rank weaknesses by: time_cost × recurrence × confidence × trainability."""
    weaknesses = [p for p in patterns if p.is_weakness]
    if not weaknesses:
        return []

    scored: list[tuple[float, BehaviorPattern]] = []
    for p in weaknesses:
        defn = BEHAVIOR_DEFS.get(p.behavior_id, {})
        trainable = defn.get('trainable', 0.5)
        recurrence = p.occurrence_count / max(p.total_laps, 1)
        score = (
            abs(p.estimated_time_cost_ms) * 0.001  # normalize ms to ~seconds
            * recurrence
            * p.confidence
            * trainable
        )
        scored.append((score, p.behavior_id, p))
    scored.sort(key=lambda t: (-t[0], t[1]))

    focuses: list[TrainingFocus] = []
    for rank, (score, _bid, p) in enumerate(scored[:n], start=1):
        defn = BEHAVIOR_DEFS.get(p.behavior_id, {})
        corners_str = ', '.join(f'T{c}' for c in p.corners_observed[:5])
        focuses.append(TrainingFocus(
            rank=rank,
            behavior_id=p.behavior_id,
            label=p.label,
            priority_score=round(score, 3),
            time_cost_ms=p.estimated_time_cost_ms,
            recurrence_rate=round(p.occurrence_count / max(p.total_laps, 1), 2),
            confidence=p.confidence,
            why_it_matters=(
                f'Costs ~{abs(p.estimated_time_cost_ms):.0f} ms each time it appears, '
                f'which happens on {p.occurrence_count}/{p.total_laps} laps. '
                f'Trend: {p.trend}.'
            ),
            where_it_shows=corners_str,
            what_defines_it=defn.get('label', p.label),
            success_next_session=(
                f'Reduce occurrences from {p.occurrence_count} to '
                f'<{max(1, p.occurrence_count - 3)} laps. '
                f'Target: reduce median cost by >{max(10, abs(p.estimated_time_cost_ms) * 0.2):.0f} ms.'
            ),
        ))
    return focuses


# ─────────────────────────────────────────────────────────────────
# Session-level metrics + consistency
# ─────────────────────────────────────────────────────────────────


@dataclass
class SessionSummary:
    session_id: str
    n_laps: int
    best_lap_time_s: float
    median_lap_time_s: float
    lap_time_std_s: float
    mean_analysis_confidence: float


def _summarize_sessions(
    features: list[CornerFeatures],
    lap_times: dict[str, float],       # lap_id -> lap_time
    session_ids: list[str],
) -> list[SessionSummary]:
    """Per-session summary."""
    # Group laps by session
    session_laps: dict[str, list[str]] = defaultdict(list)
    for cf in features:
        if cf.lap_id not in session_laps[cf.session_id]:
            session_laps[cf.session_id].append(cf.lap_id)

    summaries = []
    for sid in sorted(set(session_ids)):
        lids = session_laps.get(sid, [])
        times = [lap_times.get(lid, 0.0) for lid in lids if lid in lap_times]
        if not times:
            continue
        confs = [cf.confidence for cf in features if cf.session_id == sid]
        summaries.append(SessionSummary(
            session_id=sid,
            n_laps=len(times),
            best_lap_time_s=round(min(times), 3),
            median_lap_time_s=round(float(np.median(times)), 3),
            lap_time_std_s=round(float(np.std(times)), 3),
            mean_analysis_confidence=round(float(np.mean(confs)) if confs else 0.0, 2),
        ))
    return summaries


# ─────────────────────────────────────────────────────────────────
# Storyline generation
# ─────────────────────────────────────────────────────────────────


def _generate_storyline(
    patterns: list[BehaviorPattern],
    sessions: list[SessionSummary],
    focuses: list[TrainingFocus],
) -> list[dict]:
    """Rule-based storyline statements. Each is backed by specific evidence."""
    statements: list[dict] = []

    # Overall direction
    if len(sessions) >= 3:
        times = [s.best_lap_time_s for s in sessions]
        if times[-1] < times[0] - 0.5:
            statements.append({
                'type': 'direction',
                'text': (
                    f'Best lap improved from {times[0]:.2f}s to {times[-1]:.2f}s '
                    f'across {len(sessions)} sessions.'
                ),
                'confidence': 0.9,
            })
        elif times[-1] > times[0] + 0.5:
            statements.append({
                'type': 'direction',
                'text': f'Best lap slowed from {times[0]:.2f}s to {times[-1]:.2f}s.',
                'confidence': 0.9,
            })

    # Consistency
    if len(sessions) >= 2:
        stds = [s.lap_time_std_s for s in sessions]
        if stds[-1] < stds[0] * 0.7:
            statements.append({
                'type': 'consistency',
                'text': 'Lap-to-lap consistency improved.',
                'confidence': 0.7,
            })
        elif stds[-1] > stds[0] * 1.3:
            statements.append({
                'type': 'consistency',
                'text': (
                    'Raw speed may be improving, but session consistency worsened.'
                ),
                'confidence': 0.6,
            })

    # Recurring weakness pattern
    improving_w = [p for p in patterns if p.is_weakness and p.trend == 'improving']
    flat_w = [p for p in patterns if p.is_weakness and p.trend == 'flat']
    if improving_w:
        names = ', '.join(p.label for p in improving_w[:2])
        statements.append({
            'type': 'progress',
            'text': f'Improving areas: {names}.',
            'confidence': 0.7,
        })
    if flat_w:
        names = ', '.join(p.label for p in flat_w[:2])
        statements.append({
            'type': 'plateau',
            'text': f'Areas needing attention (flat trend): {names}.',
            'confidence': 0.6,
        })

    # Training priority
    if focuses:
        f = focuses[0]
        statements.append({
            'type': 'priority',
            'text': (
                f'Top training priority: {f.label}. '
                f'This costs ~{abs(f.time_cost_ms):.0f} ms on {f.recurrence_rate*100:.0f}% of laps.'
            ),
            'confidence': f.confidence,
        })

    # Evidence guard
    if len(sessions) < 3:
        statements.append({
            'type': 'warning',
            'text': (
                f'Only {len(sessions)} session(s) analyzed. '
                f'Trend and portability claims require more data.'
            ),
            'confidence': 1.0,
        })

    return statements


# ─────────────────────────────────────────────────────────────────
# Overall direction
# ─────────────────────────────────────────────────────────────────


def _overall_direction(sessions: list[SessionSummary]) -> str:
    if len(sessions) < 2:
        return 'insufficient_data'
    times = [s.best_lap_time_s for s in sessions]
    delta = times[-1] - times[0]
    if delta < -0.5:
        return 'improving'
    if delta > 0.5:
        return 'regressing'
    stds = [s.lap_time_std_s for s in sessions]
    if stds[-1] < stds[0] * 0.8:
        return 'consolidating'
    return 'flat'


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


@dataclass
class DevelopmentIntelligence:
    version: str = '1.0'
    sessions_analyzed: int = 0
    laps_analyzed: int = 0
    track_name: str = ''
    analysis_confidence: float = 0.0
    overall_direction: str = 'insufficient_data'
    session_summaries: list[SessionSummary] = field(default_factory=list)
    recurring_weaknesses: list[BehaviorPattern] = field(default_factory=list)
    recurring_strengths: list[BehaviorPattern] = field(default_factory=list)
    priority_focuses: list[TrainingFocus] = field(default_factory=list)
    storyline: list[dict] = field(default_factory=list)


def analyze_development(
    all_corner_features: list[CornerFeatures],
    lap_times: dict[str, float],
    session_order: list[str],
    track_name: str = '',
) -> DevelopmentIntelligence:
    """Main entry point for the development intelligence engine.

    Parameters
    ----------
    all_corner_features : flat list of per-(lap, corner) features from
        running the compare engine on all laps.
    lap_times : {lap_id: lap_time_s} for every lap analyzed.
    session_order : ordered session IDs (e.g., ['OK_FP+Q', 'OK_R1', ...]).
    track_name : human-readable track name.

    Returns
    -------
    DevelopmentIntelligence
    """
    n_laps = len(set(cf.lap_id for cf in all_corner_features))
    n_sessions = len(set(session_order))

    if n_laps < 3:
        return DevelopmentIntelligence(
            sessions_analyzed=n_sessions,
            laps_analyzed=n_laps,
            track_name=track_name,
            analysis_confidence=0.1,
            overall_direction='insufficient_data',
            storyline=[{
                'type': 'warning',
                'text': f'Only {n_laps} lap(s) analyzed. Need at least 3 for meaningful patterns.',
                'confidence': 1.0,
            }],
        )

    patterns = _detect_patterns(all_corner_features, session_order)
    weaknesses = sorted(
        [p for p in patterns if p.is_weakness],
        key=lambda p: -abs(p.estimated_time_cost_ms),
    )
    strengths = sorted(
        [p for p in patterns if not p.is_weakness],
        key=lambda p: -p.occurrence_count,
    )
    focuses = _rank_priorities(patterns)
    sessions = _summarize_sessions(all_corner_features, lap_times, session_order)
    storyline = _generate_storyline(patterns, sessions, focuses)
    direction = _overall_direction(sessions)

    # Overall analysis confidence.
    conf = min(1.0, 0.3 * min(1.0, n_laps / 20.0)
               + 0.3 * min(1.0, n_sessions / 5.0)
               + 0.2 * (float(np.mean([p.confidence for p in patterns])) if patterns else 0.0)
               + 0.2 * (1.0 if len(weaknesses) + len(strengths) >= 3 else 0.5))

    return DevelopmentIntelligence(
        version='1.0',
        sessions_analyzed=n_sessions,
        laps_analyzed=n_laps,
        track_name=track_name,
        analysis_confidence=round(conf, 2),
        overall_direction=direction,
        session_summaries=sessions,
        recurring_weaknesses=weaknesses,
        recurring_strengths=strengths,
        priority_focuses=focuses,
        storyline=storyline,
    )


def to_json_dict(di: DevelopmentIntelligence) -> dict:
    """JSON-safe serialization."""
    def _pat(p: BehaviorPattern) -> dict:
        return {
            'behavior_id': p.behavior_id,
            'label': p.label,
            'is_weakness': p.is_weakness,
            'occurrence_count': p.occurrence_count,
            'total_laps': p.total_laps,
            'sessions_observed': p.sessions_observed,
            'corners_observed': p.corners_observed,
            'archetypes_observed': p.archetypes_observed,
            'estimated_time_cost_ms': p.estimated_time_cost_ms,
            'trend': p.trend,
            'trend_evidence': p.trend_evidence,
            'confidence': p.confidence,
            'portability': p.portability,
            'explanation': p.explanation,
        }

    def _foc(f: TrainingFocus) -> dict:
        return {
            'rank': f.rank,
            'behavior_id': f.behavior_id,
            'label': f.label,
            'priority_score': f.priority_score,
            'time_cost_ms': f.time_cost_ms,
            'recurrence_rate': f.recurrence_rate,
            'confidence': f.confidence,
            'why_it_matters': f.why_it_matters,
            'where_it_shows': f.where_it_shows,
            'what_defines_it': f.what_defines_it,
            'success_next_session': f.success_next_session,
        }

    def _sess(s: SessionSummary) -> dict:
        return {
            'session_id': s.session_id,
            'n_laps': s.n_laps,
            'best_lap_time_s': s.best_lap_time_s,
            'median_lap_time_s': s.median_lap_time_s,
            'lap_time_std_s': s.lap_time_std_s,
            'mean_analysis_confidence': s.mean_analysis_confidence,
        }

    return {
        'version': di.version,
        'sessions_analyzed': di.sessions_analyzed,
        'laps_analyzed': di.laps_analyzed,
        'track_name': di.track_name,
        'analysis_confidence': di.analysis_confidence,
        'overall_direction': di.overall_direction,
        'session_summaries': [_sess(s) for s in di.session_summaries],
        'recurring_weaknesses': [_pat(p) for p in di.recurring_weaknesses],
        'recurring_strengths': [_pat(p) for p in di.recurring_strengths],
        'priority_focuses': [_foc(f) for f in di.priority_focuses],
        'storyline': di.storyline,
    }
