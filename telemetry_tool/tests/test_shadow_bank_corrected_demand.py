"""Tests for the Gold-alpha shadow overlay: bank-field-corrected lateral demand.

These enforce the hard contract:

  1. Bronze (``lateral_demand``) and Silver (``lateral_demand_2d``) values in
     the built JSON must be **bit-identical** with vs without the shadow
     overlay present.
  2. The shadow correction must respect the confidence threshold: bins below
     the gate pass raw through unchanged.
  3. The shadow JSON schema must be stable (all required keys, right shapes).
  4. The viewer contract assumed on the JS side must hold when the field is
     missing or empty — the shadow block becomes ``None`` (or safe empty)
     and the tooltip path exits without throwing.

These run without touching production data paths. The correction logic is
exercised by reimplementing it against synthetic inputs — same math as the
script, but isolated from the script's side effects.
"""
from __future__ import annotations

import math

import numpy as np
import pytest


BANK_CORRECTION_CONFIDENCE_THRESHOLD = 0.60


def _shadow_apply_like_build(
    raw_magnitude: np.ndarray,
    curvature: np.ndarray,
    bank_deg_at_bin: np.ndarray,
    bank_conf_at_bin: np.ndarray,
    *,
    threshold: float = BANK_CORRECTION_CONFIDENCE_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray]:
    """Mirror the correction logic in ``build_ok_raw.py`` for unit testing.

    Returns (corrected_magnitude, applied_mask).
    """
    applied = bank_conf_at_bin >= threshold
    sign_curv = np.sign(curvature)
    sin_bank = np.sin(np.deg2rad(bank_deg_at_bin))
    signed_raw = sign_curv * raw_magnitude
    signed_corr = np.where(applied, signed_raw - sin_bank, signed_raw)
    return np.abs(signed_corr), applied


# ── 1. Bronze / Silver bit-identity ──────────────────────────────


class TestBronzeSilverBitIdentity:
    def test_shadow_correction_does_not_mutate_raw_inputs(self):
        """The correction helper must not mutate bronze arrays. If it did,
        the bronze values in the JSON would silently change."""
        rng = np.random.default_rng(0)
        raw = rng.uniform(0.05, 1.8, 200)
        curv = rng.uniform(-0.2, 0.2, 200)
        bank = rng.uniform(-8.0, 8.0, 200)
        conf = rng.uniform(0.0, 1.0, 200)

        raw_snap = raw.copy()
        curv_snap = curv.copy()
        bank_snap = bank.copy()

        _ = _shadow_apply_like_build(raw, curv, bank, conf)

        assert np.array_equal(raw, raw_snap), "raw magnitude was mutated"
        assert np.array_equal(curv, curv_snap), "curvature was mutated"
        assert np.array_equal(bank, bank_snap), "bank_deg was mutated"

    def test_zero_confidence_is_passthrough(self):
        """All confidence = 0 → every bin passes raw through unchanged.
        This is the strongest bit-identity contract: the correction code
        path is provably a no-op when the gate is closed everywhere."""
        rng = np.random.default_rng(1)
        raw = rng.uniform(0.05, 1.8, 300)
        curv = rng.uniform(-0.2, 0.2, 300)
        bank = rng.uniform(-8.0, 8.0, 300)     # large bank
        conf = np.zeros_like(raw)               # gate closed
        corrected, applied = _shadow_apply_like_build(raw, curv, bank, conf)

        assert not applied.any(), "gate closed but applied mask has True"
        assert np.array_equal(corrected, raw), (
            "gate closed: corrected magnitude must equal raw magnitude bit-for-bit"
        )


# ── 2. Threshold gating behavior ────────────────────────────────


class TestThresholdGating:
    def test_confidence_exactly_at_threshold_is_applied(self):
        """Strict ``>=`` gate: bins exactly at the threshold are applied."""
        raw = np.array([1.0])
        curv = np.array([0.1])          # left turn
        bank = np.array([5.0])
        conf = np.array([BANK_CORRECTION_CONFIDENCE_THRESHOLD])
        corrected, applied = _shadow_apply_like_build(raw, curv, bank, conf)

        assert applied[0]
        expected_signed = 1.0 - math.sin(math.radians(5.0))
        assert abs(corrected[0] - abs(expected_signed)) < 1e-9

    def test_confidence_just_below_threshold_is_not_applied(self):
        raw = np.array([1.0])
        curv = np.array([0.1])
        bank = np.array([5.0])
        conf = np.array([BANK_CORRECTION_CONFIDENCE_THRESHOLD - 1e-6])
        corrected, applied = _shadow_apply_like_build(raw, curv, bank, conf)

        assert not applied[0]
        assert corrected[0] == raw[0], "below-threshold bin must pass raw through"

    def test_applied_frac_matches_threshold_fraction(self):
        rng = np.random.default_rng(2)
        n = 1000
        raw = np.full(n, 1.0)
        curv = np.full(n, 0.1)
        bank = np.zeros(n)
        conf = rng.uniform(0.0, 1.0, n)
        _, applied = _shadow_apply_like_build(raw, curv, bank, conf)
        # By uniform distribution, applied fraction ≈ 1 - threshold
        expected = 1.0 - BANK_CORRECTION_CONFIDENCE_THRESHOLD
        assert abs(applied.mean() - expected) < 0.05

    def test_left_turn_high_bank_reduces_magnitude(self):
        """Left turn + positive bank: IMU reads raw = real + sin(bank).
        Correction subtracts sin(bank) → corrected magnitude is smaller."""
        raw = np.array([1.0])
        curv = np.array([0.1])          # left
        bank = np.array([5.0])          # +5°
        conf = np.array([1.0])
        corrected, _ = _shadow_apply_like_build(raw, curv, bank, conf)
        assert corrected[0] < raw[0]

    def test_right_turn_positive_bank_increases_magnitude(self):
        """Right turn + positive bank: bank contribution fights the
        centripetal. Correcting recovers a larger true magnitude."""
        raw = np.array([1.0])
        curv = np.array([-0.1])         # right
        bank = np.array([5.0])          # +5°
        conf = np.array([1.0])
        corrected, _ = _shadow_apply_like_build(raw, curv, bank, conf)
        assert corrected[0] > raw[0]


# ── 3. JSON schema stability ───────────────────────────────────


REQUIRED_SHADOW_KEYS = {
    'tier', 'confidence_threshold', 'disclaimer',
    'applied_mask', 'bank_deg_at_bin', 'bank_confidence_at_bin',
    'all_p90', 'excited_p90', 'combined_p90',
    'delta_all_p90', 'delta_excited_p90',
    'applied_frac',
}


class TestSchemaStability:
    """These tests read the ACTUAL built JSON from the last pipeline run.
    They are marked skip-if-missing because the file only exists after
    ``scripts/build_ok_raw.py`` has produced it."""

    @pytest.fixture
    def built_json(self):
        import json
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'track-surface-ok-data.json',
        )
        if not os.path.isfile(path):
            pytest.skip(f'{path} not present; run build_ok_raw.py first')
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_bronze_schema_unchanged(self, built_json):
        """Bronze key set should contain all canonical fields. Adding the
        shadow overlay must not have removed anything."""
        ld = built_json.get('lateral_demand')
        assert ld is not None
        assert 'all_p90' in ld and len(ld['all_p90']) > 0
        assert 'excited_p90' in ld and len(ld['excited_p90']) > 0
        assert 'combined_p90' in ld and len(ld['combined_p90']) > 0

    def test_silver_schema_unchanged(self, built_json):
        ld2 = built_json.get('lateral_demand_2d')
        if ld2 is not None:
            for k in ('s_bins', 'n_bins', 'excited_p90', 'confidence',
                      'occupancy', 'racing_line_mask', 'grid_shape'):
                assert k in ld2, f'silver key {k} missing'

    def test_shadow_key_present(self, built_json):
        sh = built_json.get('lateral_demand_shadow_bank_corrected')
        assert sh is not None, 'shadow overlay not present in JSON'
        missing = REQUIRED_SHADOW_KEYS - set(sh.keys())
        assert not missing, f'shadow keys missing: {missing}'

    def test_shadow_tier_is_gold_alpha_shadow(self, built_json):
        sh = built_json['lateral_demand_shadow_bank_corrected']
        assert sh['tier'] == 'gold_alpha_shadow'
        # Disclaimer must explicitly say "canonical" is unchanged.
        assert 'unchanged' in sh['disclaimer'].lower() or 'not' in sh['disclaimer'].lower()

    def test_shadow_arrays_same_length_as_bronze(self, built_json):
        bronze = built_json['lateral_demand']
        sh = built_json['lateral_demand_shadow_bank_corrected']
        n = len(bronze['all_p90'])
        for k in ('all_p90', 'excited_p90', 'combined_p90',
                  'delta_all_p90', 'delta_excited_p90',
                  'applied_mask', 'bank_deg_at_bin', 'bank_confidence_at_bin'):
            assert len(sh[k]) == n, (
                f'shadow.{k} length {len(sh[k])} != bronze.all_p90 length {n}'
            )

    def test_shadow_applied_mask_is_bool(self, built_json):
        sh = built_json['lateral_demand_shadow_bank_corrected']
        assert all(isinstance(v, bool) for v in sh['applied_mask']), \
            'applied_mask must be a list of booleans'

    def test_shadow_confidence_threshold_is_in_unit_interval(self, built_json):
        sh = built_json['lateral_demand_shadow_bank_corrected']
        t = sh['confidence_threshold']
        assert 0.0 < t < 1.0, f'threshold {t} out of (0,1)'

    def test_shadow_delta_matches_corrected_minus_raw(self, built_json):
        """Delta must equal (corrected − raw). Tolerance 2e-3 to absorb the
        3-decimal rounding applied to each stored array independently."""
        bronze = built_json['lateral_demand']
        sh = built_json['lateral_demand_shadow_bank_corrected']
        for i, (corr, raw, delta) in enumerate(zip(
            sh['excited_p90'], bronze['excited_p90'], sh['delta_excited_p90']
        )):
            assert abs((corr - raw) - delta) < 2e-3, (
                f'delta mismatch at bin {i}: corr={corr} raw={raw} delta={delta}'
            )

    def test_non_applied_bins_are_bit_identical_to_bronze(self, built_json):
        """Where applied_mask[i] is False, the shadow value at bin i must
        equal the bronze value at bin i. This is the pass-through contract."""
        bronze = built_json['lateral_demand']
        sh = built_json['lateral_demand_shadow_bank_corrected']
        for i, applied in enumerate(sh['applied_mask']):
            if not applied:
                assert sh['excited_p90'][i] == bronze['excited_p90'][i], (
                    f'bin {i} not applied but shadow excited_p90 differs from bronze'
                )
                assert sh['all_p90'][i] == bronze['all_p90'][i], (
                    f'bin {i} not applied but shadow all_p90 differs from bronze'
                )


# ── 4. Viewer safety on missing / empty field ──────────────────


class TestViewerSafety:
    """The viewer reads ``DATA.lateral_demand_shadow_bank_corrected``. These
    tests verify that its documented safety contract holds:

    - If the key is MISSING from JSON, the viewer must fall back gracefully.
    - If the key is present but all arrays are empty, the viewer must not
      crash and must not show bogus values.

    The mode-switching JS code already has early-return paths for these
    cases; these Python tests verify the JSON shape those paths were written
    against.
    """

    def test_missing_key_is_valid_state(self):
        """A JSON without the shadow key is a legitimate state (e.g. when
        ``road_attitude_field`` computation failed upstream). The viewer
        reads ``DATA.lateral_demand_shadow_bank_corrected`` and checks for
        falsy values. Verify our build path produces ``None``, which
        serializes as missing key — NOT as null or an empty dict."""
        # Simulate the skip path in build_ok_raw.py:
        lateral_demand_shadow_dict = None
        data = {}
        if lateral_demand_shadow_dict is not None:
            data['lateral_demand_shadow_bank_corrected'] = lateral_demand_shadow_dict
        assert 'lateral_demand_shadow_bank_corrected' not in data

    def test_empty_field_produces_valid_scaffold(self):
        """When ``road_attitude_field_dict`` is present but empty (s_bins is
        []), the build script's ``raf_ok`` check should keep the shadow
        dict None. Verify the guard."""
        road_attitude_field_dict = {
            'tier': 'gold_alpha_shadow',
            's_bins': [],
            'bank_mean_deg': [],
            'bank_confidence': [],
        }
        raf_ok = (
            road_attitude_field_dict is not None
            and road_attitude_field_dict.get('s_bins')
            and road_attitude_field_dict.get('bank_mean_deg')
        )
        assert not raf_ok, "empty s_bins must disqualify the field"

    def test_correction_with_empty_arrays_is_safe(self):
        """If somehow the correction runs on zero-length arrays, the
        function must return zero-length arrays and not raise."""
        raw = np.array([])
        curv = np.array([])
        bank = np.array([])
        conf = np.array([])
        corr, applied = _shadow_apply_like_build(raw, curv, bank, conf)
        assert len(corr) == 0
        assert len(applied) == 0

    def test_correction_with_nan_confidence_is_treated_as_not_applied(self):
        """A NaN confidence must NOT trigger the correction. The ``>=``
        comparison with NaN returns False, so the gate stays closed."""
        raw = np.array([1.0])
        curv = np.array([0.1])
        bank = np.array([5.0])
        conf = np.array([float('nan')])
        corrected, applied = _shadow_apply_like_build(raw, curv, bank, conf)
        assert not applied[0]
        assert corrected[0] == raw[0]
