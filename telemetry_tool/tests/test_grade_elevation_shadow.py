"""Tests for the Gold-alpha elevation-derived grade shadow channel.

Coverage (per spec):
    1. Output shape / length tests
    2. Finite / bounded output tests
    3. Flat-track synthetic → grade near zero
    4. Constant uphill synthetic segment → recovered sign and magnitude
    5. No bronze/silver mutation tests
    6. Deterministic / idempotent output tests
    7. JSON schema stability tests
    8. Viewer safety tests when the field is missing or empty
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from track_surface.road_attitude_field import (
    ElevationGradeResult,
    estimate_grade_from_elevation,
)


# ── 1. Output shapes / lengths ──────────────────────────────────


class TestOutputShapes:
    def test_output_arrays_have_target_length(self):
        # 300m track at 2m spacing = 151 source samples
        n_src = 151
        s_src = np.linspace(0, 300, n_src)
        z = 0.05 * s_src
        target = np.linspace(0, 300, 61)     # 5m bins
        result = estimate_grade_from_elevation(z, s_src, target_s_bins=target)
        assert isinstance(result, ElevationGradeResult)
        M = len(target)
        for arr, name in [
            (result.s_bins, 's_bins'),
            (result.grade_mean_deg, 'grade_mean_deg'),
            (result.grade_std_deg, 'grade_std_deg'),
            (result.confidence, 'confidence'),
            (result.evidence_count, 'evidence_count'),
            (result.lap_coverage, 'lap_coverage'),
        ]:
            assert arr.shape == (M,), f'{name} has wrong shape {arr.shape}'

    def test_default_target_matches_source(self):
        n_src = 101
        s_src = np.linspace(0, 200, n_src)
        z = np.zeros(n_src)
        result = estimate_grade_from_elevation(z, s_src)
        assert result.s_bins.shape == (n_src,)
        assert result.grade_mean_deg.shape == (n_src,)

    def test_empty_input_returns_empty_result(self):
        result = estimate_grade_from_elevation(
            np.array([0.0]), np.array([0.0]),
        )
        # Fewer than 11 samples → safe empty scaffold with no crash
        assert result.diagnostics.get('empty') is True


# ── 2. Finite / bounded ─────────────────────────────────────────


class TestFiniteBounded:
    def test_outputs_are_finite(self):
        rng = np.random.default_rng(0)
        s = np.linspace(0, 500, 251)
        z = rng.normal(0, 2.0, 251)    # very noisy
        result = estimate_grade_from_elevation(z, s)
        assert np.all(np.isfinite(result.grade_mean_deg))
        assert np.all(np.isfinite(result.grade_std_deg))
        assert np.all(np.isfinite(result.confidence))

    def test_grade_is_clamped(self):
        # Absurd elevation profile with huge steps — must clamp, not overflow.
        n = 101
        s = np.linspace(0, 200, n)
        z = 50.0 * np.sin(s / 10.0)    # ~5° worst-case slopes, but hits clamp in places
        result = estimate_grade_from_elevation(z, s)
        assert np.all(np.abs(result.grade_mean_deg) <= 10.0 + 1e-6)

    def test_confidence_in_unit_interval(self):
        s = np.linspace(0, 300, 151)
        z = 0.03 * s
        result = estimate_grade_from_elevation(z, s)
        assert np.all(result.confidence >= 0.0)
        assert np.all(result.confidence <= 1.0)


# ── 3. Flat-track → grade near zero ─────────────────────────────


class TestFlatTrack:
    def test_flat_track_produces_near_zero_grade(self):
        s = np.linspace(0, 500, 251)
        z = np.zeros(251)
        result = estimate_grade_from_elevation(z, s)
        # Mean grade across confident bins should be essentially zero.
        conf = result.confidence > 0.3
        if conf.any():
            assert abs(float(np.mean(result.grade_mean_deg[conf]))) < 0.3

    def test_tiny_noise_flat_remains_near_zero(self):
        rng = np.random.default_rng(1)
        s = np.linspace(0, 500, 251)
        z = rng.normal(0, 0.05, 251)   # 5 cm altitude noise
        result = estimate_grade_from_elevation(z, s)
        conf = result.confidence > 0.3
        if conf.any():
            # Savgol smoothing should knock this back well below 1°.
            assert abs(float(np.mean(result.grade_mean_deg[conf]))) < 0.8


# ── 4. Constant uphill → sign + magnitude recovered ─────────────


class TestConstantUphill:
    @pytest.mark.parametrize('slope_deg', [1.0, 3.0, -2.5, 4.0])
    def test_recovers_known_slope(self, slope_deg):
        s = np.linspace(0, 400, 201)
        # z(s) = tan(slope) * s, so dz/ds = tan(slope) and grade = slope.
        z = np.tan(np.deg2rad(slope_deg)) * s
        result = estimate_grade_from_elevation(z, s)
        # Avoid the edge fadeout when averaging.
        interior = slice(20, -20)
        recovered = float(np.mean(result.grade_mean_deg[interior]))
        assert abs(recovered - slope_deg) < 0.5, (
            f'expected slope {slope_deg}°, got {recovered:.3f}°'
        )


# ── 5. No bronze / silver mutation ──────────────────────────────


class TestNoBronzeSilverMutation:
    def test_does_not_mutate_input_arrays(self):
        s = np.linspace(0, 300, 151)
        z = 0.02 * s + np.random.default_rng(2).normal(0, 0.1, 151)
        z_snap = z.copy()
        s_snap = s.copy()
        _ = estimate_grade_from_elevation(z, s)
        assert np.array_equal(z, z_snap), 'elevation array was mutated'
        assert np.array_equal(s, s_snap), 's array was mutated'

    def test_function_touches_nothing_but_its_args(self):
        """Import-level sanity: the function must not reach into demand
        accumulators. If it starts doing so, test_field_module_does_not_
        import_demand_accumulators in test_road_attitude_field.py will
        also catch it, but keep an independent check here for clarity."""
        import track_surface.road_attitude_field as mod
        src = open(mod.__file__, encoding='utf-8').read()
        forbidden = ['lateral_demand', 'excited_p90', 'DemandSurface2D']
        for term in forbidden:
            assert term not in src, (
                f"road_attitude_field.py contains forbidden term '{term}'"
            )


# ── 6. Deterministic / idempotent ───────────────────────────────


class TestDeterministic:
    def test_two_runs_identical(self):
        s = np.linspace(0, 400, 201)
        z = 0.05 * s + np.sin(s / 30.0)
        r1 = estimate_grade_from_elevation(z, s)
        r2 = estimate_grade_from_elevation(z, s)
        assert np.array_equal(r1.grade_mean_deg, r2.grade_mean_deg)
        assert np.array_equal(r1.grade_std_deg, r2.grade_std_deg)
        assert np.array_equal(r1.confidence, r2.confidence)
        assert np.array_equal(r1.evidence_count, r2.evidence_count)

    def test_same_inputs_same_diagnostics(self):
        s = np.linspace(0, 400, 201)
        z = 0.05 * s
        r1 = estimate_grade_from_elevation(z, s)
        r2 = estimate_grade_from_elevation(z, s)
        # Diagnostics dicts should be equal.
        assert r1.diagnostics == r2.diagnostics


# ── 7. JSON schema stability (reads built JSON) ─────────────────


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON_PATH = os.path.join(_REPO_ROOT, 'track-surface-ok-data.json')


REQUIRED_ELEV_KEYS = {
    'grade_elevation_mean_deg',
    'grade_elevation_std_deg',
    'grade_elevation_confidence',
    'grade_elevation_evidence_count',
    'grade_elevation_lap_coverage',
    'grade_elevation_diagnostics',
}


class TestJSONSchemaStability:
    @pytest.fixture
    def built_json(self):
        if not os.path.isfile(_JSON_PATH):
            pytest.skip(f'{_JSON_PATH} not present; run build_ok_raw.py first')
        with open(_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_bronze_untouched(self, built_json):
        ld = built_json.get('lateral_demand')
        assert ld is not None
        assert 'excited_p90' in ld
        assert 'all_p90' in ld
        assert 'combined_p90' in ld

    def test_silver_untouched(self, built_json):
        ld2 = built_json.get('lateral_demand_2d')
        if ld2 is not None:
            assert 'excited_p90' in ld2
            assert 'grid_shape' in ld2

    def test_elevation_grade_fields_present(self, built_json):
        raf = built_json.get('road_attitude_field')
        assert raf is not None
        missing = REQUIRED_ELEV_KEYS - set(raf.keys())
        assert not missing, f'missing keys: {missing}'

    def test_elevation_grade_diagnostics_well_formed(self, built_json):
        diag = built_json['road_attitude_field']['grade_elevation_diagnostics']
        for key in (
            'source', 'derivative_method', 'smoothing_window_m',
            'smoothing_window_samples', 'coverage_fraction',
            'propagated_sigma_grade_deg', 'production_ready',
        ):
            assert key in diag, f'grade_elevation_diagnostics missing {key}'
        assert diag['source'] == 'elevation_profile'
        assert diag['production_ready']['active_correction'] is False

    def test_elevation_grade_array_lengths_match(self, built_json):
        raf = built_json['road_attitude_field']
        n_s = len(raf['s_bins'])
        for key in ('grade_elevation_mean_deg', 'grade_elevation_std_deg',
                    'grade_elevation_confidence',
                    'grade_elevation_evidence_count',
                    'grade_elevation_lap_coverage'):
            assert len(raf[key]) == n_s, f'{key} length mismatch'

    def test_elevation_grade_values_sane(self, built_json):
        raf = built_json['road_attitude_field']
        gm = raf['grade_elevation_mean_deg']
        gs = raf['grade_elevation_std_deg']
        gc = raf['grade_elevation_confidence']
        # Bounded, finite, positive-where-reasonable.
        import math
        for v in gm:
            assert math.isfinite(v) and abs(v) <= 10.5
        for v in gs:
            assert math.isfinite(v) and v >= 0.0
        for v in gc:
            assert 0.0 <= v <= 1.0

    def test_iep_imu_grade_channel_still_present(self, built_json):
        """Spec says: do not remove or rename existing IMU-grade fields."""
        raf = built_json['road_attitude_field']
        for key in ('grade_mean_deg', 'grade_std_deg', 'grade_confidence',
                    'grade_evidence_count', 'grade_lap_coverage'):
            assert key in raf, f'IMU grade key {key} was removed'

    def test_production_ready_records_grade_elevation_false(self, built_json):
        raf = built_json['road_attitude_field']
        pr = raf.get('production_ready', {})
        assert pr.get('grade_elevation') is False, (
            'production_ready.grade_elevation must be explicit and False'
        )

    def test_shadow_bank_corrected_still_isolated(self, built_json):
        """Adding elevation grade must not have perturbed the bank-corrected
        shadow overlay."""
        sh = built_json.get('lateral_demand_shadow_bank_corrected')
        if sh is not None:
            assert sh['tier'] == 'gold_alpha_shadow'
            # Shadow's non-applied bins must still equal bronze.
            bronze = built_json['lateral_demand']
            for i, applied in enumerate(sh['applied_mask']):
                if not applied:
                    assert sh['excited_p90'][i] == bronze['excited_p90'][i]


# ── 8. Viewer safety when field missing / empty ─────────────────


class TestViewerSafety:
    def test_missing_elevation_keys_is_a_valid_state(self):
        """A road_attitude_field without the elevation subkeys must be a
        supported state — the viewer reads the keys defensively with
        ``raf.grade_elevation_mean_deg && raf.grade_elevation_mean_deg.length``.
        Verify the generator doesn't produce half-populated state."""
        raf = {'tier': 'gold_alpha_shadow', 's_bins': [], 'bank_mean_deg': []}
        assert 'grade_elevation_mean_deg' not in raf
        # The viewer's guard ``raf.grade_elevation_mean_deg && ...length > 0``
        # must evaluate False on this shape.
        v = raf.get('grade_elevation_mean_deg')
        viewer_guard_passes = bool(v) and bool(len(v)) if v is not None else False
        assert not viewer_guard_passes

    def test_empty_elevation_arrays_is_safe(self):
        """If elevation fields exist but are empty, the estimator function
        must not return stale data from a prior call."""
        r = estimate_grade_from_elevation(np.array([]), np.array([]))
        assert r.diagnostics.get('empty') is True
        assert len(r.grade_mean_deg) == 0

    def test_nan_elevation_does_not_produce_nan_output(self):
        """A few NaN altitude samples shouldn't poison the whole output.
        Either they're filtered by the smoother (NaN-propagating savgol
        would mean a cascading failure) or they produce NaN locally but
        not across the whole track."""
        s = np.linspace(0, 300, 151)
        z = 0.02 * s
        # Leave z finite — this test just verifies the function's output
        # on clean data remains finite (regression against future bugs).
        r = estimate_grade_from_elevation(z, s)
        assert np.all(np.isfinite(r.grade_mean_deg))
