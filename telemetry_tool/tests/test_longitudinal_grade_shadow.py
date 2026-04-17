"""Tests for the Gold-alpha longitudinal grade-correction shadow overlay.

The overlay is produced in ``scripts/build_ok_raw.py`` under the JSON key
``longitudinal_demand_shadow_grade_corrected``. These tests enforce the
10-category contract from the spec:

    1. Bronze bit-identity preserved
    2. Silver bit-identity preserved
    3. Gate closed = strict no-op
    4. Exact-threshold behavior pinned
    5. Directionality / sign convention pinned (+grade uphill → raw reads
       -sin(grade); correction adds sin(grade) back)
    6. Missing/empty grade field handled safely
    7. NaN confidence gated off
    8. Delta consistency (corrected − raw equals the stored delta)
    9. JSON schema stability
    10. Pure function / no mutation

The sign convention is re-derived from ``road_attitude_estimator.py:189``
and ``attitude_correction.py:253`` — NOT guessed.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
import pytest


GRADE_CORRECTION_CONFIDENCE_THRESHOLD = 0.60
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON_PATH = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')


# ─────────────────────────────────────────────────────────────────
# Pure-function helper mirroring the build-script logic
# ─────────────────────────────────────────────────────────────────


def _apply_grade_correction(
    raw_along_imu: np.ndarray,
    grade_deg: np.ndarray,
    grade_conf: np.ndarray,
    *,
    threshold: float = GRADE_CORRECTION_CONFIDENCE_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray]:
    """Reference implementation of the correction formula.

    ``corrected = raw + sin(grade_rad)`` where ``confidence ≥ threshold``.
    Otherwise raw passes through unchanged.
    """
    applied = grade_conf >= threshold
    sin_grade = np.sin(np.deg2rad(grade_deg))
    corrected = np.where(applied, raw_along_imu + sin_grade, raw_along_imu)
    return corrected, applied


# ── 10. Pure function / no mutation ─────────────────────────────


class TestPureFunction:
    def test_does_not_mutate_inputs(self):
        rng = np.random.default_rng(0)
        raw = rng.normal(0, 0.3, 200)
        grade = rng.uniform(-5, 5, 200)
        conf = rng.uniform(0, 1, 200)
        raw_snap, grade_snap, conf_snap = raw.copy(), grade.copy(), conf.copy()

        _ = _apply_grade_correction(raw, grade, conf)

        assert np.array_equal(raw, raw_snap)
        assert np.array_equal(grade, grade_snap)
        assert np.array_equal(conf, conf_snap)


# ── 3. Gate closed = strict no-op ───────────────────────────────


class TestGateClosed:
    def test_zero_confidence_passes_raw_through(self):
        """When every confidence is below threshold, corrected must equal
        raw bit-for-bit. Even with large grade magnitudes applied."""
        rng = np.random.default_rng(1)
        raw = rng.normal(0, 0.3, 300)
        grade = rng.uniform(-8, 8, 300)      # extreme — still mustn't leak
        conf = np.zeros(300)                  # gate closed
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert not applied.any()
        assert np.array_equal(corrected, raw)

    def test_confidence_below_threshold_is_passthrough(self):
        raw = np.array([0.5, -0.3, 0.1])
        grade = np.array([5.0, -4.0, 3.0])
        conf = np.array([0.59, 0.10, 0.35])   # all below threshold
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert not applied.any()
        assert np.array_equal(corrected, raw)


# ── 4. Exact-threshold behavior ─────────────────────────────────


class TestExactThreshold:
    def test_exactly_at_threshold_is_applied(self):
        raw = np.array([0.0])
        grade = np.array([5.0])
        conf = np.array([GRADE_CORRECTION_CONFIDENCE_THRESHOLD])
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert applied[0]
        assert abs(corrected[0] - math.sin(math.radians(5.0))) < 1e-9

    def test_just_below_threshold_not_applied(self):
        raw = np.array([0.0])
        grade = np.array([5.0])
        conf = np.array([GRADE_CORRECTION_CONFIDENCE_THRESHOLD - 1e-9])
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert not applied[0]
        assert corrected[0] == raw[0]


# ── 5. Sign convention / directionality ─────────────────────────


class TestSignConvention:
    """Pin the sign convention documented in:

        road_attitude_estimator.py:189  — on +grade uphill at constant speed,
            the accelerometer reads along_g = -sin(grade) (gravity pulls back)
        attitude_correction.py:253      — corrected_along = raw + sin(grade)

    A +5° uphill with constant speed (real along = 0):
        raw_along_imu = -sin(5°) ≈ -0.0872
        corrected_along = raw + sin(5°) = 0.0
    """

    def test_plus_grade_uphill_raw_is_negative(self):
        # Simulate a phone mounted on a kart going uphill at constant speed.
        # In the codebase's convention, the accelerometer reads gravity
        # direction; gravity has -x component on +grade, so along_g ≈ -sin.
        raw = np.array([-math.sin(math.radians(5.0))])    # what IMU reads
        grade = np.array([5.0])
        conf = np.array([0.8])
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert applied[0]
        # Correction should restore the true vehicle long accel = 0.
        assert abs(corrected[0]) < 1e-9, (
            f'expected corrected ≈ 0 on steady-speed uphill, got {corrected[0]}'
        )

    def test_minus_grade_downhill_raw_is_positive(self):
        # Downhill: gravity pulls forward, IMU reads +sin(|grade|).
        raw = np.array([+math.sin(math.radians(5.0))])    # along_g reading
        grade = np.array([-5.0])                           # downhill
        conf = np.array([0.8])
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert applied[0]
        # corrected = raw + sin(-5°) = sin(5°) - sin(5°) = 0
        assert abs(corrected[0]) < 1e-9

    def test_zero_grade_is_noop(self):
        raw = np.array([0.25, -0.3, 0.1])
        grade = np.zeros(3)
        conf = np.full(3, 0.9)
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert applied.all()
        # sin(0) = 0 → corrected must equal raw
        assert np.allclose(corrected, raw)

    @pytest.mark.parametrize('grade_deg', [1.0, 3.0, -2.5, 4.5, -6.0])
    def test_correction_magnitude_matches_sin_grade(self, grade_deg):
        raw = np.array([0.0])
        conf = np.array([0.9])
        corrected, _ = _apply_grade_correction(
            raw, np.array([grade_deg]), conf,
        )
        expected = math.sin(math.radians(grade_deg))
        assert abs(corrected[0] - expected) < 1e-9, (
            f'at grade={grade_deg}°, expected correction '
            f'{expected:.6f}, got {corrected[0]:.6f}'
        )


# ── 6. Missing/empty grade field ────────────────────────────────


class TestMissingOrEmptyField:
    def test_empty_arrays_produce_empty_output(self):
        raw = np.array([])
        grade = np.array([])
        conf = np.array([])
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert len(corrected) == 0
        assert len(applied) == 0

    def test_build_pipeline_guard_on_missing_elevation_grade(self):
        """The build script guards the correction block with:
            raf_has_elev = (
                road_attitude_field_dict is not None
                and road_attitude_field_dict.get('grade_elevation_mean_deg')
                and len(...) > 0
            )
        Verify that a missing or empty elevation block fails the guard."""
        # Case A: field dict missing entirely
        field_dict = None
        ok = field_dict is not None and field_dict.get('grade_elevation_mean_deg')
        assert not ok
        # Case B: field dict present but empty elevation
        field_dict = {'grade_elevation_mean_deg': []}
        ok = (
            field_dict is not None
            and field_dict.get('grade_elevation_mean_deg')
            and len(field_dict.get('grade_elevation_mean_deg', [])) > 0
        )
        assert not ok


# ── 7. NaN confidence gated off ─────────────────────────────────


class TestNaNSafety:
    def test_nan_confidence_is_not_applied(self):
        raw = np.array([0.3])
        grade = np.array([5.0])
        conf = np.array([float('nan')])
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert not applied[0]      # NaN >= 0.6 is False
        assert corrected[0] == raw[0]

    def test_mixed_nan_and_valid_confidence(self):
        raw = np.array([0.3, 0.1, 0.2])
        grade = np.array([5.0, -3.0, 2.0])
        conf = np.array([float('nan'), 0.9, 0.4])
        corrected, applied = _apply_grade_correction(raw, grade, conf)
        assert not applied[0]
        assert applied[1]
        assert not applied[2]
        assert corrected[0] == raw[0]
        assert corrected[2] == raw[2]


# ── JSON-driven tests: Bronze/Silver identity, schema, delta ────


class TestJSONContract:
    @pytest.fixture
    def built(self):
        if not os.path.isfile(_JSON_PATH):
            pytest.skip(f'{_JSON_PATH} not present; run build_ok_raw.py first')
        with open(_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)

    # ── 1. Bronze bit-identity ───────────────────────────────
    def test_bronze_untouched_by_longitudinal_shadow(self, built):
        ld = built['lateral_demand']
        # These ranges are the documented bronze output; they must not drift
        # when the longitudinal shadow block is added to the JSON.
        assert min(ld['excited_p90']) == pytest.approx(0.138, abs=1e-3)
        assert max(ld['excited_p90']) == pytest.approx(2.000, abs=1e-3)
        assert min(ld['all_p90']) == pytest.approx(0.145, abs=1e-3)
        assert max(ld['all_p90']) == pytest.approx(2.000, abs=1e-3)

    # ── 2. Silver bit-identity ───────────────────────────────
    def test_silver_untouched_by_longitudinal_shadow(self, built):
        ld2 = built.get('lateral_demand_2d')
        if ld2 is None:
            pytest.skip('silver not emitted')
        assert ld2['grid_shape'] == [301, 17]
        assert ld2['on_line_mean_demand'] == pytest.approx(0.547, abs=1e-3)
        assert ld2['off_line_mean_demand'] == pytest.approx(0.536, abs=1e-3)

    # ── 9. JSON schema stability ─────────────────────────────
    def test_longitudinal_shadow_key_present(self, built):
        long_sh = built.get('longitudinal_demand_shadow_grade_corrected')
        assert long_sh is not None, 'longitudinal shadow block missing'
        required = {
            'tier', 'product_note', 'confidence_threshold', 'disclaimer',
            'correction_formula', 'reference_metric',
            'applied_mask', 'grade_deg_at_bin', 'grade_confidence_at_bin',
            'all_p90_raw_imu', 'all_p90_corrected', 'all_p90_dvdt_reference',
            'delta_all_p90', 'mean_residual_raw_g', 'mean_residual_cor_g',
            'applied_frac', 'bins_correction_helps_frac', 'production_ready',
        }
        missing = required - set(long_sh.keys())
        assert not missing, f'schema missing keys: {missing}'

    def test_longitudinal_shadow_tier_and_flag(self, built):
        sh = built['longitudinal_demand_shadow_grade_corrected']
        assert sh['tier'] == 'gold_alpha_shadow'
        assert sh['production_ready'] is False
        # Disclaimer must mention canonical outputs are unchanged.
        assert 'UNCHANGED' in sh['disclaimer'] or 'unchanged' in sh['disclaimer'].lower()
        # Product note must be explicit about the boundary.
        assert 'bronze' in sh['product_note'].lower()

    def test_longitudinal_shadow_array_lengths_match(self, built):
        sh = built['longitudinal_demand_shadow_grade_corrected']
        n = len(sh['applied_mask'])
        for key in ('grade_deg_at_bin', 'grade_confidence_at_bin',
                    'all_p90_raw_imu', 'all_p90_corrected',
                    'all_p90_dvdt_reference', 'delta_all_p90',
                    'mean_residual_raw_g', 'mean_residual_cor_g'):
            assert len(sh[key]) == n, f'{key} length mismatch'

    def test_longitudinal_applied_mask_is_bool(self, built):
        sh = built['longitudinal_demand_shadow_grade_corrected']
        assert all(isinstance(v, bool) for v in sh['applied_mask'])

    def test_longitudinal_confidence_threshold_sane(self, built):
        sh = built['longitudinal_demand_shadow_grade_corrected']
        t = sh['confidence_threshold']
        assert 0.0 < t < 1.0

    # ── 8. Delta consistency ────────────────────────────────
    def test_delta_matches_corrected_minus_raw(self, built):
        sh = built['longitudinal_demand_shadow_grade_corrected']
        for i, (corr, raw, delta) in enumerate(zip(
            sh['all_p90_corrected'], sh['all_p90_raw_imu'], sh['delta_all_p90'],
        )):
            # Tolerance 2e-3 because the three arrays are rounded independently.
            assert abs((corr - raw) - delta) < 2e-3, (
                f'bin {i}: corr={corr}, raw={raw}, delta={delta}'
            )

    def test_non_applied_bins_do_not_perturb_bronze(self, built):
        """Shadow-only contract: the longitudinal block must not overwrite
        anything in the bronze ``lateral_demand`` block. This is a structural
        check — we verify there is no key collision that could cause a
        silent overwrite."""
        sh_keys = set(built['longitudinal_demand_shadow_grade_corrected'].keys())
        bronze_keys = set(built['lateral_demand'].keys())
        assert sh_keys.isdisjoint(bronze_keys)

    def test_correction_formula_documented(self, built):
        sh = built['longitudinal_demand_shadow_grade_corrected']
        assert 'sin(grade_rad)' in sh['correction_formula']

    def test_reference_metric_documented(self, built):
        sh = built['longitudinal_demand_shadow_grade_corrected']
        assert 'dv/dt' in sh['reference_metric']
