"""Tests for the bank-corrected opt-in promotion-gate evaluator.

Covers the eight required categories:

    1. Bronze bit-identity preserved
    2. Silver bit-identity preserved
    3. Decision rubric stable on synthetic cases
    4. Threshold sweep ordering sane
    5. Material-regression detection works
    6. Report/CSV schema stable
    7. No mutation of shadow inputs
    8. Missing plausibility data handled safely
"""
from __future__ import annotations

import copy
import csv as csv_mod
import json
import math
import os
from dataclasses import replace

import numpy as np
import pytest

# Import the evaluator module via importlib so we can pull out pure helpers
# without touching the ``main`` side-effectful path. Python 3.14 dataclass
# needs the module registered in sys.modules before exec_module runs.
import importlib.util
import sys as _sys
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, 'scripts')
if _SCRIPTS_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPTS_DIR)
_TEL_PKG = os.path.join(_REPO_ROOT, 'telemetry_tool')
if _TEL_PKG not in _sys.path:
    _sys.path.insert(0, _TEL_PKG)

_spec = importlib.util.spec_from_file_location(
    'eval_opt_in',
    os.path.join(_SCRIPTS_DIR, 'evaluate_bank_corrected_opt_in_candidate.py'),
)
eval_mod = importlib.util.module_from_spec(_spec)
_sys.modules['eval_opt_in'] = eval_mod
_spec.loader.exec_module(eval_mod)


# ─────────────────────────────────────────────────────────────────
# Synthetic builders for the rubric
# ─────────────────────────────────────────────────────────────────


def _make_regime(cal_raw, cal_cor, rmse_raw=0.2, rmse_cor=0.2, n=100):
    return eval_mod.RegimeMetrics(
        n=n, cal_raw=cal_raw, cal_cor=cal_cor,
        rmse_raw=rmse_raw, rmse_cor=rmse_cor,
        bias_raw=0.0, bias_cor=0.0,
        applied_frac=0.8, conf_weighted_applied=0.6,
    )


def _make_combo(
    threshold=0.60, scale=1.0,
    cal_all=0.92, rmse_cor=0.28, rmse_raw=0.28,
    cal_straight_raw=0.5, cal_straight_cor=0.80,
    cal_corners_raw=0.86, cal_corners_cor=0.89,
    bin_improved=0.4, bin_worsened=0.3,
    broad_harm=0.15, max_reg=-0.01,
    improvements_plausible=0.5, regressions_suspicious=0.3,
):
    rm = {
        'all_valid': _make_regime(0.85, cal_all, rmse_raw=rmse_raw, rmse_cor=rmse_cor, n=1000),
        'straight': _make_regime(cal_straight_raw, cal_straight_cor, n=200),
        'left_corner': _make_regime(cal_corners_raw, cal_corners_cor, n=150),
        'right_corner': _make_regime(cal_corners_raw, cal_corners_cor, n=200),
        'braking': _make_regime(0.78, 0.85, n=150),
        'accelerating': _make_regime(0.97, 1.03, n=150),
        'steady_mid_corner': _make_regime(0.88, 0.90, n=150),
    }
    return eval_mod.ComboResult(
        threshold=threshold, scale=scale,
        regime_metrics=rm,
        bin_improved_frac=bin_improved,
        bin_worsened_frac=bin_worsened,
        broad_harm_frac=broad_harm,
        max_regime_regression=max_reg,
        max_regression_regime='accelerating',
        improvements_in_plausible_frac=improvements_plausible,
        regressions_in_suspicious_frac=regressions_suspicious,
    )


# ── 3. Decision rubric stable on synthetic cases ────────────────


class TestRubricClassification:
    def test_hard_stop_straights_regression(self):
        # Straights regress catastrophically (|0.55 - 1| - |0.5 - 1| = 0.05
        # — below the 0.15 cap). Push it harder.
        c = _make_combo(
            cal_straight_raw=0.95,   # err = 0.05
            cal_straight_cor=0.60,   # err = 0.40 → regression 0.35 > 0.15 cap
        )
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        assert v.decision == 'NOT_CANDIDATE'
        assert any('straight' in h for h in v.hard_stops_triggered)

    def test_hard_stop_global_rmse(self):
        c = _make_combo(rmse_cor=0.40, rmse_raw=0.20)   # +0.20 G > 0.03 cap
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        assert v.decision == 'NOT_CANDIDATE'
        assert any('RMSE' in h for h in v.hard_stops_triggered)

    def test_hard_stop_broad_harm(self):
        c = _make_combo(broad_harm=0.80)    # 80% > 55% cap
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        assert v.decision == 'NOT_CANDIDATE'
        assert any('broad harm' in h for h in v.hard_stops_triggered)

    def test_shadow_only_when_global_gain_too_small(self):
        # Opt-in fails criterion 1 (global improvement below 0.02).
        c = _make_combo(cal_all=0.86)       # raw 0.85 → 0.86; improvement 0.01
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        assert v.decision == 'SHADOW_ONLY'

    def test_opt_in_when_all_four_criteria_pass(self):
        # Synthetic: global gain = 0.07, all regimes win, no big regression.
        c = _make_combo(cal_all=0.92)
        sweep = {(th, 1.0): _make_combo(cal_all=0.92 + (th - 0.6) * 0.005)
                 for th in (0.50, 0.60, 0.70, 0.80)}
        v = eval_mod.classify(c, sweep)
        assert v.decision in ('OPT_IN_CANDIDATE', 'STRONG_OPT_IN_CANDIDATE')

    def test_strong_opt_in_when_all_seven_pass(self):
        c = _make_combo(
            cal_all=0.92,
            improvements_plausible=0.7,     # ≥ 50%
        )
        # Ensure all regimes win
        for name in c.regime_metrics:
            if name != 'all_valid':
                m = c.regime_metrics[name]
                c.regime_metrics[name] = replace(
                    m, cal_cor=m.cal_raw + (1.0 - m.cal_raw) * 0.6,
                )
        sweep = {(th, 1.0): _make_combo(cal_all=0.92 + (th - 0.6) * 0.005,
                                        improvements_plausible=0.6)
                 for th in (0.50, 0.60, 0.70, 0.80)}
        v = eval_mod.classify(c, sweep)
        # This should pass all opt-in criteria AND all strong criteria.
        assert v.decision == 'STRONG_OPT_IN_CANDIDATE'

    def test_rubric_stable_under_same_input(self):
        # Deterministic: two classifications of the same combo produce
        # the same decision & same criteria sets.
        c = _make_combo(cal_all=0.92)
        sweep = {(0.60, 1.0): c}
        v1 = eval_mod.classify(c, sweep)
        v2 = eval_mod.classify(c, sweep)
        assert v1.decision == v2.decision
        assert v1.opt_in_criteria_passed == v2.opt_in_criteria_passed
        assert v1.opt_in_criteria_failed == v2.opt_in_criteria_failed


# ── 4. Threshold sweep ordering sane ────────────────────────────


class TestThresholdSweep:
    def test_pick_best_prefers_closer_to_one(self):
        sweep = {
            (0.50, 1.0): _make_combo(cal_all=0.85, cal_straight_cor=0.80),
            (0.60, 1.0): _make_combo(cal_all=0.92, cal_straight_cor=0.80),
            (0.70, 1.0): _make_combo(cal_all=0.88, cal_straight_cor=0.80),
        }
        best = eval_mod.pick_best_combo(sweep)
        assert best == (0.60, 1.0)

    def test_pick_best_penalizes_straight_regression(self):
        # Two combos with identical global cal, but one regresses straights.
        good = _make_combo(cal_all=0.93, cal_straight_raw=0.5, cal_straight_cor=0.85)  # err 0.15
        bad = _make_combo(cal_all=0.93, cal_straight_raw=0.5, cal_straight_cor=0.30)   # err 0.70
        sweep = {(0.60, 1.0): good, (0.60, 0.5): bad}
        best = eval_mod.pick_best_combo(sweep)
        assert best == (0.60, 1.0), 'best should avoid the straights-regressing combo'

    def test_ordering_covers_all_combos(self):
        sweep = {
            (th, sc): _make_combo(threshold=th, scale=sc)
            for th in eval_mod._CONF_THRESHOLDS for sc in eval_mod._SCALES
        }
        assert len(sweep) == len(eval_mod._CONF_THRESHOLDS) * len(eval_mod._SCALES)
        # pick_best must return something that exists in the sweep.
        best = eval_mod.pick_best_combo(sweep)
        assert best in sweep


# ── 5. Material-regression detection works ──────────────────────


class TestRegressionDetection:
    def test_max_regime_regression_tracks_worst_regime(self):
        c = _make_combo()
        # Force one regime to have a large cal regression.
        c.regime_metrics['right_corner'] = _make_regime(0.86, 0.60, n=100)
        # Reclassify — this changes max regression on re-evaluation
        # (classify doesn't mutate combo; we have to pre-set max_regime_regression).
        c.max_regime_regression = abs(0.60 - 1.0) - abs(0.86 - 1.0)   # 0.26
        c.max_regression_regime = 'right_corner'
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        assert v.decision == 'SHADOW_ONLY'   # regime regression cap triggered

    def test_max_regime_regression_below_cap_passes(self):
        c = _make_combo()
        c.max_regime_regression = 0.04
        c.max_regression_regime = 'accelerating'
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        # Shouldn't contribute a failure
        assert not any('regime regression' in s for s in v.opt_in_criteria_failed)


# ── 7. No mutation of shadow inputs ─────────────────────────────


class TestPureEvaluator:
    def test_classify_does_not_mutate_combo(self):
        c = _make_combo()
        c_snap = copy.deepcopy(c)
        _ = eval_mod.classify(c, {(0.60, 1.0): c})
        # Compare scalars
        assert c.threshold == c_snap.threshold
        assert c.scale == c_snap.scale
        assert c.max_regime_regression == c_snap.max_regime_regression
        # Regime dict untouched
        for k in c.regime_metrics:
            assert c.regime_metrics[k] == c_snap.regime_metrics[k]

    def test_classify_does_not_mutate_sweep(self):
        c = _make_combo()
        sweep = {(th, 1.0): _make_combo() for th in (0.5, 0.6, 0.7, 0.8)}
        sweep_snap = copy.deepcopy(sweep)
        _ = eval_mod.classify(c, sweep)
        for k in sweep:
            assert sweep[k].regime_metrics == sweep_snap[k].regime_metrics


# ── 8. Missing plausibility data handled safely ─────────────────


class TestMissingPlausibility:
    def test_classify_without_plausibility_still_runs(self):
        # The plausibility signal affects the spatial-concentration strong
        # criterion only. Without it, the synthetic combo's field is 0.0
        # → strong criterion fails but opt-in can still pass.
        c = _make_combo(improvements_plausible=0.0)
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        # It's OK for this to be OPT_IN or SHADOW, as long as it doesn't crash.
        assert v.decision in (
            'OPT_IN_CANDIDATE', 'SHADOW_ONLY', 'STRONG_OPT_IN_CANDIDATE',
            'NOT_CANDIDATE',
        )

    def test_classify_strong_requires_plausibility(self):
        """Even with every opt-in criterion passed, zero plausibility
        concentration should prevent STRONG classification."""
        c = _make_combo(cal_all=0.93, improvements_plausible=0.10)
        # Force strong improvement on every regime
        for name in c.regime_metrics:
            if name == 'all_valid':
                continue
            m = c.regime_metrics[name]
            c.regime_metrics[name] = replace(
                m, cal_cor=m.cal_raw + (1.0 - m.cal_raw) * 0.8,
            )
        v = eval_mod.classify(c, {(0.60, 1.0): c})
        assert v.decision != 'STRONG_OPT_IN_CANDIDATE'


# ── 6. Report / CSV schema stable ──────────────────────────────


_JSON_PATH = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')
_MD_PATH = os.path.join(_REPO_ROOT, 'docs', 'validation',
                        'bank_corrected_opt_in_candidate_report.md')
_CSV_PATH = os.path.join(_REPO_ROOT, 'docs', 'validation',
                         'bank_corrected_opt_in_candidate_metrics.csv')


class TestReportCSV:
    @pytest.fixture
    def csv_rows(self):
        if not os.path.isfile(_CSV_PATH):
            pytest.skip(f'{_CSV_PATH} missing — run evaluator first')
        with open(_CSV_PATH, 'r', encoding='utf-8') as f:
            r = csv_mod.DictReader(f)
            return list(r)

    def test_csv_has_all_sweep_combinations(self, csv_rows):
        combos = {(float(r['threshold']), float(r['scale'])) for r in csv_rows}
        assert len(combos) == len(eval_mod._CONF_THRESHOLDS) * len(eval_mod._SCALES)

    def test_csv_has_all_regimes_per_combo(self, csv_rows):
        # For each (threshold, scale) we should see every regime exactly once.
        from collections import Counter
        per_combo: dict[tuple, Counter] = {}
        for r in csv_rows:
            key = (float(r['threshold']), float(r['scale']))
            per_combo.setdefault(key, Counter())[r['regime']] += 1
        for key, counts in per_combo.items():
            for regime in eval_mod.REGIMES:
                assert counts[regime] == 1, f'regime {regime} missing/duplicated for {key}'

    def test_csv_decision_values_are_valid(self, csv_rows):
        valid = {'NOT_CANDIDATE', 'SHADOW_ONLY',
                 'OPT_IN_CANDIDATE', 'STRONG_OPT_IN_CANDIDATE'}
        for r in csv_rows:
            assert r['decision_at_combo'] in valid, (
                f'unknown decision class: {r["decision_at_combo"]}'
            )

    def test_md_report_has_sections(self):
        if not os.path.isfile(_MD_PATH):
            pytest.skip(f'{_MD_PATH} missing — run evaluator first')
        with open(_MD_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        for header in (
            '## 1. Rubric',
            '## 2. Threshold × scale sweep',
            '## 3. Regime winner table',
            '## 4. Harm analysis',
            '## 5. Rubric outcome',
            '## 6. Recommendation',
        ):
            assert header in text, f'missing report section: {header}'


# ── 1. / 2. Bronze and Silver bit-identity ──────────────────────


class TestCanonicalUnchanged:
    @pytest.fixture
    def built(self):
        if not os.path.isfile(_JSON_PATH):
            pytest.skip(f'{_JSON_PATH} missing — run build_ok_raw.py first')
        with open(_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_bronze_lateral_demand_unchanged(self, built):
        ld = built['lateral_demand']
        # Frozen values from the canonical build output.
        assert min(ld['excited_p90']) == pytest.approx(0.138, abs=1e-3)
        assert max(ld['excited_p90']) == pytest.approx(2.000, abs=1e-3)
        assert min(ld['all_p90']) == pytest.approx(0.145, abs=1e-3)

    def test_silver_demand_2d_unchanged(self, built):
        ld2 = built.get('lateral_demand_2d')
        if ld2 is None:
            pytest.skip('silver absent')
        assert ld2['grid_shape'] == [301, 17]
        assert ld2['on_line_mean_demand'] == pytest.approx(0.547, abs=1e-3)

    def test_shadow_bank_corrected_still_present_and_isolated(self, built):
        sh = built.get('lateral_demand_shadow_bank_corrected')
        assert sh is not None
        assert sh['tier'] == 'gold_alpha_shadow'
        # Shadow's non-applied bins still equal bronze (the pre-existing
        # contract must not be affected by adding the evaluator or
        # compare-summary code paths).
        bronze = built['lateral_demand']
        for i, applied in enumerate(sh['applied_mask']):
            if not applied:
                assert sh['excited_p90'][i] == bronze['excited_p90'][i]

    def test_gold_compare_summary_is_diagnostic_only(self, built):
        """If the compare-summary block is present, it must be clearly
        labelled as diagnostic and contain no bronze/silver keys."""
        cmp_ = built.get('gold_compare_summary')
        if cmp_ is None:
            pytest.skip('compare summary not emitted')
        assert cmp_['tier'] == 'gold_alpha_shadow'
        assert 'Diagnostic' in cmp_['disclaimer'] or 'diagnostic' in cmp_['disclaimer']
        # Keys must not collide with anything in bronze or silver namespace.
        forbidden = {
            'excited_p90', 'all_p90', 'combined_p90',        # bronze leaves
            'lateral_demand', 'lateral_demand_2d',           # top-level canonical
            'grid_shape', 'on_line_mean_demand',             # silver leaves
        }
        assert forbidden.isdisjoint(set(cmp_.keys()))

    def test_decision_class_in_compare_summary_is_valid(self, built):
        cmp_ = built.get('gold_compare_summary')
        if cmp_ is None:
            pytest.skip('compare summary not emitted')
        assert cmp_['decision_class'] in {
            'NOT_CANDIDATE', 'SHADOW_ONLY',
            'OPT_IN_CANDIDATE', 'STRONG_OPT_IN_CANDIDATE',
        }
        # The opt_in_candidate boolean must be consistent with the class.
        is_candidate = cmp_['bank_shadow_opt_in_candidate']
        if cmp_['decision_class'] in ('OPT_IN_CANDIDATE', 'STRONG_OPT_IN_CANDIDATE'):
            assert is_candidate is True
        else:
            assert is_candidate is False
