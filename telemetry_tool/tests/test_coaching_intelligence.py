"""Tests for the Coaching Intelligence engine."""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from track_surface.coaching_intelligence import (
    CoachingAction, CoachingIntelligence,
    generate_coaching, to_json_dict,
    INTERVENTION_CLASSES, PHASES,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')


def _pkt(cid, delta, ms_delta=-8.0, brake=-6.0, throttle=8.0, exit_delta=-6.0, line=0.5, conf=0.8):
    return {
        'corner_id': cid, 'time_delta_ms': delta, 'primary_cause': 'test', 'confidence': conf,
        'evidence': {
            'min_speed_ref_kph': 50.0, 'min_speed_cand_kph': 50.0 + ms_delta,
            'min_speed_delta_kph': ms_delta,
            'brake_point_delta_m': brake, 'throttle_pickup_delta_m': throttle,
            'exit_speed_ref_kph': 60.0, 'exit_speed_cand_kph': 60.0 + exit_delta,
            'exit_speed_delta_kph': exit_delta, 'line_deviation_rms_m': line,
        },
    }


class TestInterventionDetection:
    def test_detects_entry_speed_surrender(self):
        pkt = _pkt(1, 300, ms_delta=-8, brake=-10)
        ci = generate_coaching([pkt], [], [])
        types = {a.problem_type for a in ci.actions}
        assert 'entry_speed_surrender' in types

    def test_detects_conservative_brake_release(self):
        pkt = _pkt(1, 300, ms_delta=-10, brake=-2)
        ci = generate_coaching([pkt], [], [])
        types = {a.problem_type for a in ci.actions}
        assert 'conservative_brake_release' in types

    def test_detects_late_throttle(self):
        pkt = _pkt(1, 200, ms_delta=-2, brake=0, throttle=12)
        ci = generate_coaching([pkt], [], [])
        types = {a.problem_type for a in ci.actions}
        assert 'late_throttle_application' in types

    def test_detects_path_variance(self):
        pkt = _pkt(1, 200, line=2.5)
        ci = generate_coaching([pkt], [], [])
        types = {a.problem_type for a in ci.actions}
        assert 'path_variance' in types

    def test_small_delta_ignored(self):
        pkt = _pkt(1, 5, ms_delta=-1, brake=0, throttle=0, exit_delta=0, line=0.1)
        ci = generate_coaching([pkt], [], [])
        assert len(ci.actions) == 0


class TestCoachingLanguage:
    def test_hypothesis_contains_evidence_numbers(self):
        pkt = _pkt(1, 500, ms_delta=-12, brake=-8)
        ci = generate_coaching([pkt], [], [])
        for a in ci.actions:
            assert any(c.isdigit() for c in a.coach_hypothesis), \
                f'hypothesis has no numbers: {a.coach_hypothesis}'

    def test_instruction_is_specific(self):
        pkt = _pkt(1, 500, ms_delta=-10, brake=-2)
        ci = generate_coaching([pkt], [], [])
        for a in ci.actions:
            assert len(a.driver_instruction) > 30
            assert any(c.isdigit() for c in a.driver_instruction)

    def test_success_metric_is_measurable(self):
        pkt = _pkt(1, 500, ms_delta=-10, brake=-2)
        ci = generate_coaching([pkt], [], [])
        for a in ci.actions:
            assert 'success' in a.success_metric.lower() or 'km/h' in a.success_metric or 'ms' in a.success_metric

    def test_no_generic_phrases(self):
        pkts = [_pkt(i, 300) for i in range(1, 5)]
        ci = generate_coaching(pkts, [], [])
        # These are generic standalone coaching phrases. Note: "brake later"
        # is allowed when qualified (e.g. "Do NOT brake later by guessing").
        forbidden = ['carry more speed', 'be smoother', 'keep practicing', 'try harder']
        for a in ci.actions:
            for phrase in forbidden:
                assert phrase not in a.driver_instruction.lower(), \
                    f'generic phrase "{phrase}" found in instruction'


class TestPriorityRanking:
    def test_actions_sorted_by_priority(self):
        pkts = [
            _pkt(1, 800, ms_delta=-15, brake=-12),
            _pkt(2, 200, ms_delta=-3, brake=-1, throttle=8),
            _pkt(3, 500, ms_delta=-10, brake=-2),
        ]
        ci = generate_coaching(pkts, [], [])
        scores = [a.priority_score for a in ci.actions]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_focus_now_is_first(self):
        pkts = [_pkt(i, 300 + i * 100) for i in range(1, 6)]
        ci = generate_coaching(pkts, [], [])
        if ci.actions:
            assert ci.actions[0].status == 'focus_now'

    def test_at_most_one_focus_now(self):
        pkts = [_pkt(i, 300 + i * 100) for i in range(1, 6)]
        ci = generate_coaching(pkts, [], [])
        focus_count = sum(1 for a in ci.actions if a.status == 'focus_now')
        assert focus_count <= 1


class TestEvidenceScoping:
    def test_corners_are_specific(self):
        pkts = [_pkt(3, 400, ms_delta=-10, brake=-8)]
        ci = generate_coaching(pkts, [], [])
        for a in ci.actions:
            assert 3 in a.corners

    def test_phase_is_valid(self):
        pkts = [_pkt(1, 300)]
        ci = generate_coaching(pkts, [], [])
        for a in ci.actions:
            assert a.phase in PHASES

    def test_confidence_in_range(self):
        pkts = [_pkt(1, 300)]
        ci = generate_coaching(pkts, [], [])
        for a in ci.actions:
            assert 0.0 <= a.confidence <= 1.0

    def test_estimated_gain_is_conservative(self):
        pkt = _pkt(1, 1000, ms_delta=-15, brake=-10)
        ci = generate_coaching([pkt], [], [])
        for a in ci.actions:
            assert a.estimated_gain_ms <= 1000 * 0.5  # never more than 50% of raw delta

    def test_canonical_basis_always_true(self):
        pkts = [_pkt(1, 300)]
        ci = generate_coaching(pkts, [], [])
        for a in ci.actions:
            assert a.canonical_basis is True


class TestSparseData:
    def test_empty_packets_graceful(self):
        ci = generate_coaching([], [], [])
        assert len(ci.actions) == 0
        assert 'no corner evidence' in ci.confidence_note.lower()

    def test_single_session_context(self):
        pkts = [_pkt(1, 300)]
        ci = generate_coaching(pkts, [], [], sessions_analyzed=1)
        assert '1 session' in ci.confidence_note


class TestDeterminism:
    def test_two_runs_identical(self):
        pkts = [_pkt(i, 200 + i * 50) for i in range(1, 6)]
        c1 = generate_coaching(pkts, [], [])
        c2 = generate_coaching(pkts, [], [])
        j1 = json.dumps(to_json_dict(c1), sort_keys=True)
        j2 = json.dumps(to_json_dict(c2), sort_keys=True)
        assert j1 == j2


class TestJSONSchema:
    @pytest.fixture
    def built(self):
        if not os.path.isfile(_JSON):
            pytest.skip('JSON missing')
        with open(_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_coaching_intelligence_present(self, built):
        assert 'coaching_intelligence' in built

    def test_required_keys(self, built):
        ci = built['coaching_intelligence']
        for k in ('version', 'actions', 'corner_families', 'focus_summary',
                  'secondary_summary', 'confidence_note'):
            assert k in ci

    def test_action_structure(self, built):
        for a in built['coaching_intelligence']['actions']:
            for k in ('id', 'title', 'problem_type', 'corners', 'phase',
                      'evidence', 'coach_hypothesis', 'driver_instruction',
                      'attempt_protocol', 'success_metric', 'estimated_gain_ms',
                      'trainability', 'confidence', 'priority_score', 'status',
                      'canonical_basis'):
                assert k in a, f'action missing key: {k}'

    def test_bronze_unchanged(self, built):
        ld = built['lateral_demand']
        assert min(ld['excited_p90']) == pytest.approx(0.138, abs=1e-3)
        assert max(ld['excited_p90']) == pytest.approx(2.000, abs=1e-3)

    def test_no_mutation(self):
        import copy
        pkts = [_pkt(1, 300)]
        pkts_snap = copy.deepcopy(pkts)
        _ = generate_coaching(pkts, [], [])
        assert pkts == pkts_snap
