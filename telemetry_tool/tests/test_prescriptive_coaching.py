"""Tests for prescriptive_coaching.py — 10 required categories.

1. No Bronze mutation
2. Deterministic output
3. Sparse-data safety
4. Schema stability
5. Confidence bounds
6. No beta/diagnostic dependency
7. Prescription grounding in evidence
8. Next-run plan length limits
9. Graceful insufficient-data states
10. JSON additive-only contract
"""
from __future__ import annotations

import copy
import json
import os

import numpy as np
import pytest

from track_surface.prescriptive_coaching import (
    PrescriptiveCoaching,
    WEAKNESS_PLAYBOOK,
    generate_prescriptive_coaching,
    to_json_dict,
)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON = os.path.join(_REPO, 'track-surface-ok-data.json')


def _pkt(cid, delta, ms_d=-8, brake=-6, throttle=8, exit_d=-6, line=0.5, conf=0.8):
    return {
        'corner_id': cid, 'time_delta_ms': delta,
        'primary_cause': 'test', 'confidence': conf,
        's_entry_m': cid * 100.0, 's_exit_m': cid * 100.0 + 50,
        's_apex_m': cid * 100.0 + 25,
        'evidence': {
            'min_speed_ref_kph': 50.0, 'min_speed_cand_kph': 50.0 + ms_d,
            'min_speed_delta_kph': ms_d,
            'brake_point_delta_m': brake, 'throttle_pickup_delta_m': throttle,
            'exit_speed_ref_kph': 60.0, 'exit_speed_cand_kph': 60.0 + exit_d,
            'exit_speed_delta_kph': exit_d, 'line_deviation_rms_m': line,
        },
    }

def _weak(bid, occ=50, trend='improving', cost=300, corners=None, archetypes=None, conf=0.8):
    return {
        'behavior_id': bid, 'label': bid.replace('_', ' ').title(),
        'occurrence_count': occ, 'trend': trend,
        'estimated_time_cost_ms': cost, 'confidence': conf,
        'corners_observed': corners or [1, 2, 3],
        'archetypes_observed': archetypes or ['slow_90deg', 'medium_speed'],
        'sessions_observed': ['S1', 'S2', 'S3'],
    }


# ── 1. No Bronze mutation ────────────────────────────────────────


class TestNoBronzeMutation:
    def test_inputs_not_mutated(self):
        pkts = [_pkt(1, 300), _pkt(2, 200)]
        weaks = [_weak('low_minimum_speed')]
        pkts_snap = copy.deepcopy(pkts)
        weaks_snap = copy.deepcopy(weaks)
        _ = generate_prescriptive_coaching(pkts, weaks, [], [])
        assert pkts == pkts_snap
        assert weaks == weaks_snap

    @pytest.fixture
    def built(self):
        if not os.path.isfile(_JSON):
            pytest.skip('JSON missing')
        with open(_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_bronze_unchanged(self, built):
        ld = built['lateral_demand']
        assert min(ld['excited_p90']) == pytest.approx(0.138, abs=1e-3)
        assert max(ld['excited_p90']) == pytest.approx(2.000, abs=1e-3)


# ── 2. Deterministic output ──────────────────────────────────────


class TestDeterministic:
    def test_two_runs_identical(self):
        pkts = [_pkt(i, 200 + i * 50) for i in range(1, 5)]
        weaks = [_weak('low_minimum_speed'), _weak('early_braking')]
        r1 = generate_prescriptive_coaching(pkts, weaks, [], [])
        r2 = generate_prescriptive_coaching(pkts, weaks, [], [])
        assert json.dumps(to_json_dict(r1), sort_keys=True) == json.dumps(to_json_dict(r2), sort_keys=True)


# ── 3. Sparse-data safety ────────────────────────────────────────


class TestSparseData:
    def test_empty_inputs(self):
        pc = generate_prescriptive_coaching([], [], [], [])
        assert pc.version == '1.0'
        assert any('insufficient' in s.get('type', '') for s in pc.storyline)

    def test_single_corner(self):
        pc = generate_prescriptive_coaching([_pkt(1, 100)], [], [], [])
        assert pc.version == '1.0'

    def test_single_session_warns(self):
        pkts = [_pkt(1, 300)]
        weaks = [_weak('low_minimum_speed')]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [], sessions_analyzed=1)
        assert any('session' in s.get('text', '').lower() for s in pc.storyline)


# ── 4. Schema stability ─────────────────────────────────────────


class TestSchema:
    @pytest.fixture
    def built(self):
        if not os.path.isfile(_JSON):
            pytest.skip('JSON missing')
        with open(_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_prescriptive_coaching_present(self, built):
        assert 'prescriptive_coaching' in built

    def test_required_top_keys(self, built):
        pc = built['prescriptive_coaching']
        for k in ('version', 'source', 'global_focus', 'corner_coaching',
                  'weakness_playbook_matches', 'next_run_plan',
                  'validation_checks', 'storyline', 'limits'):
            assert k in pc, f'missing key: {k}'

    def test_source_is_canonical_only(self, built):
        pc = built['prescriptive_coaching']
        assert 'bronze' in pc['source'].lower()
        assert 'beta' not in pc['source'].lower()
        assert 'diagnostic' not in pc['source'].lower()

    def test_limits_block_present(self, built):
        lim = built['prescriptive_coaching']['limits']
        for k in ('sessions_analyzed', 'laps_analyzed', 'brake_data',
                  'throttle_data', 'steering_data', 'confidence_floor'):
            assert k in lim

    def test_playbook_match_structure(self, built):
        for pm in built['prescriptive_coaching']['weakness_playbook_matches']:
            for k in ('weakness_key', 'title', 'coaching_actions',
                      'driver_cues', 'measurable_targets', 'sensor_note',
                      'portability', 'data_support'):
                assert k in pm, f'playbook match missing: {k}'


# ── 5. Confidence bounds ────────────────────────────────────────


class TestConfidenceBounds:
    def test_confidence_in_range(self):
        pkts = [_pkt(i, 300) for i in range(1, 5)]
        weaks = [_weak('low_minimum_speed', conf=0.9)]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [])
        for gf in pc.global_focus:
            assert 0.0 <= gf['confidence'] <= 1.0
        for vc in pc.validation_checks:
            assert 0.0 <= vc['confidence'] <= 1.0

    def test_storyline_confidence_present(self):
        pkts = [_pkt(1, 300)]
        weaks = [_weak('low_minimum_speed')]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [])
        for s in pc.storyline:
            assert 'confidence' in s


# ── 6. No beta/diagnostic dependency ────────────────────────────


class TestNoBetaDependency:
    def test_module_does_not_import_gold_lab(self):
        """The module must not import from gold_lab, bank-corrected, or
        diagnostic modules. Docstring mentions of these terms for
        documentation purposes are acceptable."""
        import track_surface.prescriptive_coaching as mod
        src = open(mod.__file__, encoding='utf-8').read()
        # Check for actual import statements, not documentation references
        forbidden_imports = [
            'from track_surface.gold_lab',
            'import gold_lab',
            'from track_surface.attitude_correction',
            'bank_corrected_beta',
            'lateral_demand_shadow',
        ]
        for phrase in forbidden_imports:
            assert phrase not in src, f'module imports "{phrase}" — must be canonical only'


# ── 7. Prescription grounding in evidence ────────────────────────


class TestEvidenceGrounding:
    def test_measurable_targets_contain_numbers(self):
        pkts = [_pkt(1, 500, ms_d=-12)]
        weaks = [_weak('low_minimum_speed', cost=500)]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [])
        for pm in pc.weakness_playbook_matches:
            for t in pm['measurable_targets']:
                assert any(c.isdigit() for c in t), f'target has no numbers: {t}'

    def test_coaching_actions_are_parameterised(self):
        pkts = [_pkt(1, 400, brake=-10)]
        weaks = [_weak('early_braking', cost=400, corners=[1])]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [])
        for pm in pc.weakness_playbook_matches:
            if pm['weakness_key'] == 'early_braking':
                # Should contain parameterised distances, not raw templates
                joined = ' '.join(pm['coaching_actions'])
                assert '{' not in joined, f'unresolved template: {joined}'

    def test_sensor_note_present(self):
        pkts = [_pkt(1, 300)]
        weaks = [_weak('low_minimum_speed')]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [])
        for pm in pc.weakness_playbook_matches:
            assert pm['sensor_note'], 'sensor_note must not be empty'


# ── 8. Next-run plan length limits ───────────────────────────────


class TestNextRunPlanLimits:
    def test_max_3_priorities_plus_anti_overload(self):
        pkts = [_pkt(i, 300) for i in range(1, 8)]
        weaks = [_weak(k) for k in list(WEAKNESS_PLAYBOOK.keys())[:5]]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [])
        # Max 3 priorities + 1 anti-overload = 4 total
        assert len(pc.next_run_plan) <= 4

    def test_anti_overload_present(self):
        pkts = [_pkt(1, 300), _pkt(2, 250)]
        weaks = [_weak('low_minimum_speed'), _weak('early_braking')]
        pc = generate_prescriptive_coaching(pkts, weaks, [], [])
        types = [p['type'] for p in pc.next_run_plan]
        assert 'anti_overload' in types

    def test_empty_plan_when_no_evidence(self):
        pc = generate_prescriptive_coaching([], [], [], [])
        assert len(pc.next_run_plan) == 0


# ── 9. Graceful insufficient-data states ────────────────────────


class TestInsufficientData:
    def test_no_crash_on_missing_evidence_fields(self):
        # Packet with None for optional evidence fields
        pkt = {
            'corner_id': 1, 'time_delta_ms': 200, 'primary_cause': 'test',
            'confidence': 0.5, 's_entry_m': 100, 's_exit_m': 150, 's_apex_m': 125,
            'evidence': {
                'min_speed_ref_kph': 50, 'min_speed_cand_kph': 45,
                'min_speed_delta_kph': -5,
                'brake_point_delta_m': None,
                'throttle_pickup_delta_m': None,
                'exit_speed_ref_kph': 60, 'exit_speed_cand_kph': 55,
                'exit_speed_delta_kph': -5,
                'line_deviation_rms_m': 0.3,
            },
        }
        weaks = [_weak('low_minimum_speed', corners=[1])]
        pc = generate_prescriptive_coaching([pkt], weaks, [], [])
        assert pc.version == '1.0'

    def test_zero_laps_produces_limits(self):
        pc = generate_prescriptive_coaching([], [], [], [], laps_analyzed=0)
        assert pc.limits['laps_analyzed'] == 0


# ── 10. JSON additive-only contract ──────────────────────────────


class TestAdditiveOnly:
    @pytest.fixture
    def built(self):
        if not os.path.isfile(_JSON):
            pytest.skip('JSON missing')
        with open(_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_prescriptive_coaching_is_separate_key(self, built):
        # Must not collide with canonical keys
        canonical = {'lateral_demand', 'lateral_demand_2d', 'track',
                     'elevation', 'boundaries', 'drivers', 'stats'}
        pc_keys = set(built['prescriptive_coaching'].keys())
        assert canonical.isdisjoint(pc_keys)

    def test_silver_unchanged(self, built):
        ld2 = built.get('lateral_demand_2d')
        if ld2:
            assert ld2['grid_shape'] == [301, 17]
            assert ld2['on_line_mean_demand'] == pytest.approx(0.547, abs=1e-3)
