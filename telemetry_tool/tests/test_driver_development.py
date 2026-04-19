"""Tests for the Driver Development Intelligence engine.

Covers: pattern detection, trend computation, priority ranking, sparse-data
handling, determinism, JSON schema, and Bronze identity preservation.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from track_surface.driver_development import (
    CornerFeatures,
    DevelopmentIntelligence,
    analyze_development,
    classify_corner_archetype,
    to_json_dict,
)


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON_PATH = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')


# ── Synthetic data builder ──────────────────────────────────────


def _make_cf(
    lap_id: str = 'lap_0',
    session_id: str = 'S1',
    corner_id: int = 1,
    time_delta_ms: float = 200.0,
    min_speed_delta: float = -5.0,
    throttle_delta: float = 8.0,
    brake_delta: float = -6.0,
    exit_delta: float = -4.0,
    line_dev: float = 0.3,
    primary: str = 'low_minimum_speed',
    conf: float = 0.6,
    archetype: str = 'medium_speed',
) -> CornerFeatures:
    return CornerFeatures(
        lap_id=lap_id, session_id=session_id, corner_id=corner_id,
        archetype=archetype, time_delta_ms=time_delta_ms,
        min_speed_delta_kph=min_speed_delta,
        brake_point_delta_m=brake_delta,
        throttle_pickup_delta_m=throttle_delta,
        exit_speed_delta_kph=exit_delta,
        line_deviation_m=line_dev,
        primary_cause=primary, confidence=conf,
    )


def _make_dataset(n_laps: int = 20, n_sessions: int = 4, n_corners: int = 5):
    """Build a consistent multi-session dataset with known patterns."""
    features = []
    lap_times = {}
    sessions = [f'S{i}' for i in range(1, n_sessions + 1)]
    lap_id = 0
    for si, sess in enumerate(sessions):
        for j in range(n_laps // n_sessions):
            lid = f'lap_{lap_id}_{sess}'
            lap_times[lid] = 80.0 - si * 2.0 + j * 0.3  # improving over sessions
            for c in range(1, n_corners + 1):
                # Inject known weaknesses:
                # - Late throttle on every lap, corners 2+3
                # - Low min speed on half the laps, all corners
                thr_delta = 10.0 if c in (2, 3) else 0.0
                min_delta = -6.0 if (j % 2 == 0) else -1.0
                # Corners 4+5 are "near reference" (low delta) to test strength detection
                td = 150.0 + c * 20 - si * 10 if c <= 3 else 20.0 + j * 2
                features.append(_make_cf(
                    lap_id=lid, session_id=sess, corner_id=c,
                    time_delta_ms=td,
                    min_speed_delta=min_delta,
                    throttle_delta=thr_delta,
                    brake_delta=-2.0,
                    exit_delta=-3.0 if c <= 3 else 0.5,
                    line_dev=0.5,
                    archetype='slow_90deg' if c <= 2 else 'medium_speed',
                ))
            lap_id += 1
    return features, lap_times, sessions


# ── Corner archetype classification ─────────────────────────────


class TestCornerArchetype:
    def test_slow_hairpin(self):
        assert classify_corner_archetype(25.0, 0.10, 20.0) == 'slow_hairpin'

    def test_slow_90(self):
        assert classify_corner_archetype(40.0, 0.05, 30.0) == 'slow_90deg'

    def test_medium(self):
        assert classify_corner_archetype(50.0, 0.04, 40.0) == 'medium_speed'

    def test_fast(self):
        assert classify_corner_archetype(70.0, 0.02, 50.0) == 'fast_corner'


# ── Pattern detection ────────────────────────────────────────────


class TestPatternDetection:
    def test_detects_known_weaknesses(self):
        features, lap_times, sessions = _make_dataset()
        di = analyze_development(features, lap_times, sessions)
        weakness_ids = {w.behavior_id for w in di.recurring_weaknesses}
        # Should detect late throttle (injected on corners 2+3)
        assert 'late_throttle_pickup' in weakness_ids
        # Should detect low minimum speed (injected on 50% of laps)
        assert 'low_minimum_speed' in weakness_ids

    def test_detects_strengths_when_present(self):
        features, lap_times, sessions = _make_dataset()
        di = analyze_development(features, lap_times, sessions)
        # At least some strength should be detected from the consistent brake point
        # (brake_delta = -2.0, within strong_braking threshold of ±3.0)
        strength_ids = {s.behavior_id for s in di.recurring_strengths}
        assert 'strong_braking' in strength_ids

    def test_no_patterns_with_insufficient_data(self):
        # Only 1 lap, 1 corner — cannot detect recurring patterns.
        cf = _make_cf(lap_id='lap_0', session_id='S1', corner_id=1)
        di = analyze_development([cf], {'lap_0': 80.0}, ['S1'])
        assert di.overall_direction == 'insufficient_data'
        assert di.analysis_confidence < 0.3


# ── Priority ranking ────────────────────────────────────────────


class TestPriorityRanking:
    def test_priorities_sorted_by_score(self):
        features, lap_times, sessions = _make_dataset()
        di = analyze_development(features, lap_times, sessions)
        scores = [f.priority_score for f in di.priority_focuses]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_at_most_3_priorities(self):
        features, lap_times, sessions = _make_dataset()
        di = analyze_development(features, lap_times, sessions)
        assert len(di.priority_focuses) <= 3

    def test_priorities_are_weaknesses_only(self):
        features, lap_times, sessions = _make_dataset()
        di = analyze_development(features, lap_times, sessions)
        weakness_ids = {w.behavior_id for w in di.recurring_weaknesses}
        for f in di.priority_focuses:
            assert f.behavior_id in weakness_ids


# ── Trend computation ────────────────────────────────────────────


class TestTrends:
    def test_improving_direction(self):
        features, lap_times, sessions = _make_dataset()
        di = analyze_development(features, lap_times, sessions)
        # Dataset has lap times improving over sessions (80→72).
        assert di.overall_direction == 'improving'

    def test_flat_with_identical_sessions(self):
        features = []
        lap_times = {}
        sessions = ['S1', 'S2', 'S3']
        for si, sess in enumerate(sessions):
            for j in range(5):
                lid = f'lap_{si*5+j}_{sess}'
                lap_times[lid] = 80.0 + j * 0.1  # same pace each session
                for c in range(1, 4):
                    features.append(_make_cf(
                        lap_id=lid, session_id=sess, corner_id=c,
                        time_delta_ms=100.0, min_speed_delta=-2.0,
                    ))
        di = analyze_development(features, lap_times, sessions)
        assert di.overall_direction in ('flat', 'consolidating')


# ── Sparse data handling ────────────────────────────────────────


class TestSparseData:
    def test_single_session_degrades_gracefully(self):
        features = [_make_cf(lap_id=f'lap_{i}', session_id='S1', corner_id=c)
                    for i in range(5) for c in range(1, 4)]
        lap_times = {f'lap_{i}': 80.0 for i in range(5)}
        di = analyze_development(features, lap_times, ['S1'])
        # Should produce output without crashing.
        assert di.sessions_analyzed == 1
        # Should warn about insufficient data for trends.
        assert any('warning' in s.get('type', '') for s in di.storyline)

    def test_empty_features_degrades(self):
        di = analyze_development([], {}, [])
        assert di.overall_direction == 'insufficient_data'
        assert di.analysis_confidence < 0.3


# ── Determinism ─────────────────────────────────────────────────


class TestDeterminism:
    def test_two_runs_identical(self):
        features, lap_times, sessions = _make_dataset()
        d1 = analyze_development(features, lap_times, sessions)
        d2 = analyze_development(features, lap_times, sessions)
        j1 = json.dumps(to_json_dict(d1), sort_keys=True)
        j2 = json.dumps(to_json_dict(d2), sort_keys=True)
        assert j1 == j2


# ── JSON schema stability ───────────────────────────────────────


class TestJSONSchema:
    @pytest.fixture
    def built(self):
        if not os.path.isfile(_JSON_PATH):
            pytest.skip(f'{_JSON_PATH} missing')
        with open(_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_development_intelligence_present(self, built):
        assert 'development_intelligence' in built

    def test_required_top_level_keys(self, built):
        di = built['development_intelligence']
        for k in ('version', 'sessions_analyzed', 'laps_analyzed',
                  'analysis_confidence', 'overall_direction',
                  'recurring_weaknesses', 'recurring_strengths',
                  'priority_focuses', 'storyline'):
            assert k in di, f'missing key: {k}'

    def test_weakness_packet_structure(self, built):
        di = built['development_intelligence']
        for w in di['recurring_weaknesses']:
            for k in ('behavior_id', 'label', 'occurrence_count',
                      'sessions_observed', 'trend', 'confidence',
                      'estimated_time_cost_ms', 'explanation'):
                assert k in w, f'weakness missing key: {k}'

    def test_priority_focus_structure(self, built):
        di = built['development_intelligence']
        for f in di['priority_focuses']:
            for k in ('rank', 'label', 'priority_score',
                      'why_it_matters', 'where_it_shows',
                      'success_next_session'):
                assert k in f, f'focus missing key: {k}'

    def test_storyline_structure(self, built):
        di = built['development_intelligence']
        for s in di['storyline']:
            assert 'type' in s
            assert 'text' in s
            assert 'confidence' in s

    def test_bronze_unchanged(self, built):
        ld = built['lateral_demand']
        assert min(ld['excited_p90']) == pytest.approx(0.138, abs=1e-3)
        assert max(ld['excited_p90']) == pytest.approx(2.000, abs=1e-3)


# ── No mutation ─────────────────────────────────────────────────


class TestNoMutation:
    def test_analyze_does_not_mutate_inputs(self):
        import copy
        features, lap_times, sessions = _make_dataset()
        features_snap = copy.deepcopy(features)
        _ = analyze_development(features, lap_times, sessions)
        for orig, after in zip(features_snap, features):
            assert orig.time_delta_ms == after.time_delta_ms
            assert orig.min_speed_delta_kph == after.min_speed_delta_kph
