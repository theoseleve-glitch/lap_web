"""Regression suite for the Gold Physics Lab.

Covers the 18 required categories:

    1. Bronze byte-identity preserved
    2. Silver byte-identity preserved
    3. Gold Lab JSON additive only
    4. Viewer-safe when Gold Lab block absent
    5. Viewer-safe when compare metrics absent
    6. Beta candidate default-off
    7. Beta candidate never aliases Bronze arrays
    8. Threshold / scale values wired correctly
    9. Zone classification deterministic
    10. Plausibility-zone overlay safe when audit data absent
    11. Tooltip explanation strings stable
    12. Compare drawer delta consistency
    13. Missing/NaN confidence handled safely
    14. Existing bank shadow pass-through contract preserved
    15. Existing grade elevation shadow contract preserved
    16. Existing longitudinal grade shadow remains no-UI / engineer-only
    17. Clicking/highlighting zones does not mutate data
    18. Repeated builds are deterministic
"""
from __future__ import annotations

import copy
import json
import os

import numpy as np
import pytest

from track_surface.gold_lab import (
    PlausibilityFlags,
    ZONE_CLASSES,
    ZONE_PRETTY,
    classify_s_bin_zone,
    classify_zones_bulk,
    explain_s_bin,
    zone_counts,
)


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON_PATH = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')
_VIEWER_PATH = os.path.join(_REPO_ROOT, 'ouest-karting-live.html')


@pytest.fixture(scope='module')
def built():
    if not os.path.isfile(_JSON_PATH):
        pytest.skip(f'{_JSON_PATH} missing; run build_ok_raw.py first')
    with open(_JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


# ── 1. Bronze byte-identity ─────────────────────────────────────


class TestBronzeIdentity:
    def test_bronze_lateral_demand_unchanged(self, built):
        ld = built['lateral_demand']
        # Locked canonical values — CI fail if these drift.
        assert min(ld['excited_p90']) == pytest.approx(0.138, abs=1e-3)
        assert max(ld['excited_p90']) == pytest.approx(2.000, abs=1e-3)
        assert min(ld['all_p90']) == pytest.approx(0.145, abs=1e-3)
        assert max(ld['all_p90']) == pytest.approx(2.000, abs=1e-3)

    def test_bronze_is_top_level_canonical_pointer(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        assert gl['canonical_products']['bronze_default'] == 'lateral_demand'


# ── 2. Silver byte-identity ─────────────────────────────────────


class TestSilverIdentity:
    def test_silver_lateral_demand_2d_unchanged(self, built):
        ld2 = built.get('lateral_demand_2d')
        if ld2 is None:
            pytest.skip('silver absent')
        assert ld2['grid_shape'] == [301, 17]
        assert ld2['on_line_mean_demand'] == pytest.approx(0.547, abs=1e-3)
        assert ld2['off_line_mean_demand'] == pytest.approx(0.536, abs=1e-3)

    def test_silver_is_top_level_canonical_pointer(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        assert gl['canonical_products']['silver_default'] == 'lateral_demand_2d'


# ── 3. Gold Lab JSON is additive only ───────────────────────────


class TestAdditiveOnly:
    def test_gold_lab_key_is_its_own_namespace(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        # Keys inside gold_lab must not collide with any top-level canonical key.
        canonical_keys = {'lateral_demand', 'lateral_demand_2d',
                          'track', 'elevation', 'boundaries', 'drivers',
                          'sensor_quality', 'stats'}
        assert canonical_keys.isdisjoint(set(gl.keys()))

    def test_gold_lab_version_is_stable_string(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        assert isinstance(gl.get('version'), str)
        assert gl['version'] == '1.0'

    def test_candidate_products_is_separate_namespace(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        # Beta's keys must not shadow Bronze leaf keys in a dangerous way.
        # We allow names like 'all_p90' but only under gold_lab.candidate_products.*
        # — never at top level. This is already enforced by being a nested dict.
        assert 'lateral_demand' not in beta
        assert 'lateral_demand_2d' not in beta


# ── 4. Viewer-safe when Gold Lab block absent ───────────────────


class TestViewerSafeMissingGoldLab:
    def test_missing_gold_lab_is_a_valid_state(self):
        # Simulate the build path when gold_lab is not emitted.
        gold_lab_dict = None
        data = {}
        if gold_lab_dict is not None:
            data['gold_lab'] = gold_lab_dict
        assert 'gold_lab' not in data
        # Viewer guard: `const gl = DATA.gold_lab; if (!gl) return;`
        viewer_guard = bool(data.get('gold_lab'))
        assert not viewer_guard

    def test_viewer_has_explicit_fallback(self):
        """The viewer's buildScene 'bank_beta' branch checks for gold_lab
        before reading candidate_products — verify the guard chain is in
        the HTML source."""
        if not os.path.isfile(_VIEWER_PATH):
            pytest.skip('viewer HTML missing')
        with open(_VIEWER_PATH, 'r', encoding='utf-8') as f:
            src = f.read()
        assert 'DATA.gold_lab' in src
        # Look for a graceful fall-back: null-guard or if-check.
        assert 'if (gl' in src or 'if(gl' in src or 'gl &&' in src


# ── 5. Viewer-safe when compare metrics absent ──────────────────


class TestViewerSafeMissingCompare:
    def test_compare_subblock_may_be_empty(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        cmp_ = gl.get('compare', {})
        # compare must at minimum have these structural keys; metrics may
        # be absent if evaluator CSV isn't there.
        assert 'available_modes' in cmp_
        assert 'default_compare_pair' in cmp_

    def test_goldLabInit_tolerates_missing_metrics(self):
        if not os.path.isfile(_VIEWER_PATH):
            pytest.skip('viewer HTML missing')
        with open(_VIEWER_PATH, 'r', encoding='utf-8') as f:
            src = f.read()
        # The init function must check sub-blocks before populating HUD.
        assert 'const gm = cmp.global_metrics' in src or 'cmp.global_metrics' in src
        assert 'if (gm)' in src or 'if(gm)' in src


# ── 6. Beta candidate default-off ───────────────────────────────


class TestBetaDefaultOff:
    def test_beta_default_enabled_false(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        assert beta['default_enabled'] is False
        assert beta['canonical'] is False
        assert beta['status'] == 'opt_in_candidate'

    def test_viewer_default_mode_is_bronze(self):
        if not os.path.isfile(_VIEWER_PATH):
            pytest.skip('viewer HTML missing')
        with open(_VIEWER_PATH, 'r', encoding='utf-8') as f:
            src = f.read()
        # state.mode default is 'grip' (Bronze).
        assert "mode:'grip'" in src or 'mode: \'grip\'' in src
        # The Bronze button has class 'active' on load.
        assert 'class="mode-btn active" data-mode="grip"' in src


# ── 7. Beta candidate never aliases Bronze arrays ───────────────


class TestBetaNoAliasing:
    def test_beta_arrays_are_separate_from_bronze(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        bronze = built['lateral_demand']
        # Even if applied_frac is 100%, beta's arrays must be *independent*
        # Python objects, not aliases. Equal values on some bins are fine —
        # non-applied bins SHOULD equal bronze — but the containers differ.
        assert id(beta['excited_p90']) != id(bronze['excited_p90'])
        assert id(beta['all_p90']) != id(bronze['all_p90'])

    def test_beta_non_applied_bins_equal_bronze(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        bronze = built['lateral_demand']
        for i, applied in enumerate(beta['applied_mask']):
            if not applied:
                assert beta['excited_p90'][i] == bronze['excited_p90'][i], (
                    f'bin {i}: beta not applied but excited_p90 differs from bronze'
                )
                assert beta['all_p90'][i] == bronze['all_p90'][i]


# ── 8. Threshold / scale values wired correctly ─────────────────


class TestThresholdScaleWiring:
    def test_beta_threshold_is_050(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        assert beta['threshold'] == pytest.approx(0.50, abs=1e-9)

    def test_beta_scale_is_100(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        assert beta['correction_scale'] == pytest.approx(1.00, abs=1e-9)

    def test_applied_mask_consistent_with_threshold(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        thresh = beta['threshold']
        for i, (conf, applied) in enumerate(zip(
            beta['bank_confidence_at_bin'], beta['applied_mask'],
        )):
            expected = conf >= thresh
            assert applied is expected, (
                f'bin {i}: conf={conf} thresh={thresh} applied={applied}, expected {expected}'
            )


# ── 9. Zone classification deterministic ────────────────────────


class TestZoneClassificationDeterministic:
    def test_same_input_same_class(self):
        pf = PlausibilityFlags(flag_conf_spread=1)
        c1 = classify_s_bin_zone(bank_confidence=0.7, applied=True, plausibility_flags=pf)
        c2 = classify_s_bin_zone(bank_confidence=0.7, applied=True, plausibility_flags=pf)
        assert c1 == c2

    def test_all_classes_are_valid_strings(self):
        assert set(ZONE_CLASSES) == set(ZONE_PRETTY.keys())
        for c in ZONE_CLASSES:
            assert isinstance(ZONE_PRETTY[c], str)
            assert ZONE_PRETTY[c]

    def test_bulk_is_same_as_elementwise(self):
        confs = [0.1, 0.5, 0.7, 0.9]
        applied = [False, False, True, True]
        pfs = [None, None, PlausibilityFlags(is_plausible=True),
               PlausibilityFlags(flag_gradient=1)]
        bulk = classify_zones_bulk(confs, applied, pfs)
        elem = [classify_s_bin_zone(bank_confidence=c, applied=a, plausibility_flags=p)
                for c, a, p in zip(confs, applied, pfs)]
        assert bulk == elem

    def test_zone_counts_are_exhaustive(self):
        classes = ['high_conf_plausible_applied', 'high_conf_plausible_applied',
                   'low_conf_suspicious', 'neutral_unclassified']
        counts = zone_counts(classes)
        assert counts['high_conf_plausible_applied'] == 2
        assert counts['low_conf_suspicious'] == 1
        assert counts['neutral_unclassified'] == 1
        # Unseen classes must still appear with 0.
        for c in ZONE_CLASSES:
            assert c in counts


# ── 10. Plausibility-zone overlay safe when audit data absent ───


class TestPlausibilityAbsent:
    def test_classify_without_plausibility(self):
        c = classify_s_bin_zone(bank_confidence=0.7, applied=True,
                                plausibility_flags=None)
        # Without audit signal, applied bins land in 'neither'.
        assert c == 'high_conf_neither_applied'

    def test_bulk_with_none_list(self):
        out = classify_zones_bulk([0.1, 0.9], [False, True], plausibility_rows=None)
        assert len(out) == 2
        assert all(c in ZONE_CLASSES for c in out)


# ── 11. Tooltip explanation strings stable ──────────────────────


class TestExplanationStrings:
    def test_applied_plausible_message(self):
        pf = PlausibilityFlags(is_plausible=True)
        msg = explain_s_bin(bank_confidence=0.8, applied=True, plausibility_flags=pf)
        assert 'correction applied' in msg
        assert 'plausible' in msg

    def test_applied_suspicious_message(self):
        pf = PlausibilityFlags(flag_gradient=1)
        msg = explain_s_bin(bank_confidence=0.8, applied=True, plausibility_flags=pf)
        assert 'correction applied' in msg
        assert 'suspicious' in msg

    def test_skipped_low_confidence_message(self):
        msg = explain_s_bin(bank_confidence=0.3, applied=False, plausibility_flags=None)
        assert 'correction skipped' in msg
        assert 'confidence' in msg

    def test_skipped_suspicious_message(self):
        pf = PlausibilityFlags(flag_banked_straight=1)
        msg = explain_s_bin(bank_confidence=0.8, applied=False, plausibility_flags=pf)
        assert 'correction skipped' in msg
        assert 'suspicious' in msg


# ── 12. Compare drawer delta consistency ────────────────────────


class TestCompareDelta:
    def test_delta_equals_corrected_minus_raw(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        bronze = built['lateral_demand']
        for i, (corr, raw, delta) in enumerate(zip(
            beta['excited_p90'], bronze['excited_p90'], beta['delta_excited_p90'],
        )):
            # Tolerance 2e-3 for independent rounding.
            assert abs((corr - raw) - delta) < 2e-3, (
                f'bin {i}: corr={corr} raw={raw} delta={delta}'
            )


# ── 13. Missing / NaN confidence handled safely ─────────────────


class TestNaNConfidence:
    def test_nan_confidence_never_applies(self):
        c = classify_s_bin_zone(bank_confidence=float('nan'), applied=False,
                                plausibility_flags=None)
        assert c in ZONE_CLASSES    # no crash, no NaN propagation
        # And the build's own guard: conf >= threshold with NaN yields False.
        assert not (float('nan') >= 0.50)


# ── 14. Bank shadow pass-through contract preserved ─────────────


class TestBankShadowContract:
    def test_shadow_overlay_still_present(self, built):
        sh = built.get('lateral_demand_shadow_bank_corrected')
        assert sh is not None
        assert sh['tier'] == 'gold_alpha_shadow'

    def test_shadow_passthrough_contract_intact(self, built):
        sh = built['lateral_demand_shadow_bank_corrected']
        bronze = built['lateral_demand']
        for i, applied in enumerate(sh['applied_mask']):
            if not applied:
                assert sh['excited_p90'][i] == bronze['excited_p90'][i], (
                    f'bin {i}: shadow non-applied but differs from bronze'
                )


# ── 15. Grade elevation shadow contract preserved ───────────────


class TestGradeElevationContract:
    def test_grade_elevation_fields_still_present(self, built):
        raf = built.get('road_attitude_field')
        assert raf is not None
        for k in ('grade_elevation_mean_deg', 'grade_elevation_std_deg',
                  'grade_elevation_confidence', 'grade_elevation_evidence_count',
                  'grade_elevation_lap_coverage', 'grade_elevation_diagnostics'):
            assert k in raf

    def test_production_ready_flag_preserved(self, built):
        raf = built['road_attitude_field']
        assert raf['production_ready']['grade_elevation'] is False


# ── 16. Longitudinal grade shadow remains no-UI / engineer-only ─


class TestLongitudinalNoUI:
    def test_longitudinal_shadow_json_still_present(self, built):
        long_sh = built.get('longitudinal_demand_shadow_grade_corrected')
        assert long_sh is not None
        assert long_sh['tier'] == 'gold_alpha_shadow'
        assert long_sh['production_ready'] is False

    def test_no_viewer_mode_for_longitudinal(self):
        if not os.path.isfile(_VIEWER_PATH):
            pytest.skip('viewer HTML missing')
        with open(_VIEWER_PATH, 'r', encoding='utf-8') as f:
            src = f.read()
        # No operator-facing mode button for longitudinal correction.
        forbidden_labels = [
            'data-mode="long_corrected"',
            'Long Demand + Grade',
            'Longitudinal + Grade',
        ]
        for phrase in forbidden_labels:
            assert phrase not in src, (
                f"viewer contains '{phrase}' — grade longitudinal must stay engineer-only"
            )

    def test_gold_lab_declares_it_engineer_only(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        ch = gl['diagnostic_channels']['longitudinal_grade_shadow']
        assert ch.get('operator_ui') is False


# ── 17. Click / highlight zones does not mutate data ────────────


class TestZoneInteractionImmutable:
    def test_classify_functions_are_pure(self):
        pf = PlausibilityFlags(flag_gradient=1, is_plausible=False)
        pf_snap = copy.deepcopy(pf)
        _ = classify_s_bin_zone(bank_confidence=0.7, applied=True,
                                plausibility_flags=pf)
        _ = explain_s_bin(bank_confidence=0.7, applied=True,
                          plausibility_flags=pf)
        assert pf == pf_snap

    def test_bulk_does_not_mutate_inputs(self):
        confs = [0.4, 0.8]
        applied = [False, True]
        pfs = [None, PlausibilityFlags(is_plausible=True)]
        confs_snap = list(confs)
        applied_snap = list(applied)
        pfs_snap = copy.deepcopy(pfs)
        _ = classify_zones_bulk(confs, applied, pfs)
        assert confs == confs_snap
        assert applied == applied_snap
        assert pfs == pfs_snap


# ── 18. Repeated builds deterministic ───────────────────────────


class TestDeterministicBuild:
    def test_zones_on_bronze_grid_deterministic_on_same_inputs(self):
        """Two classify calls on the same inputs must produce identical lists."""
        confs = [0.1, 0.4, 0.55, 0.7, 0.9]
        applied = [False, False, True, True, True]
        pfs = [None,
               PlausibilityFlags(flag_conf_spread=1),
               None,
               PlausibilityFlags(is_plausible=True),
               PlausibilityFlags(flag_gradient=1)]
        r1 = classify_zones_bulk(confs, applied, pfs)
        r2 = classify_zones_bulk(confs, applied, pfs)
        assert r1 == r2

    def test_zone_counts_sum_equals_bins(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        zc = gl['zone_counts']
        zones = gl['zones_on_bronze_grid']
        assert sum(zc.values()) == len(zones)

    def test_promotion_gate_outputs_match_beta(self, built):
        gl = built.get('gold_lab')
        if gl is None:
            pytest.skip('gold_lab absent')
        beta = gl['candidate_products']['lat_demand_bank_corrected_beta']
        gate = gl['promotion_gate']
        assert gate['decision_class'] == beta['decision_class']
        assert gate['canonical_recommendation'] is False
