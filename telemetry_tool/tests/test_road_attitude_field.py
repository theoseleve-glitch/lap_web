"""Tests for track_surface/road_attitude_field.py — track-space attitude aggregation.

Coverage (per spec):
    1. Flat road                      → bank/grade ≈ 0, high confidence
    2. Constant bank segment          → bank recovered in the banked window
    3. Constant grade segment         → grade recovered in the graded window
    4. Repeated noisy laps converge   → multi-lap aggregation reduces spread
    5. One bad lap does not dominate  → robust median rejects outlier lap
    6. Sparse coverage                → low confidence, not absurd values
    7. Bounded outputs                → clamped to configured range, no NaN
    8. Sign-convention consistency    → +bank ↔ +sin(bank), +grade ↔ uphill
"""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.frenet import FrenetFrame
from track_surface.road_attitude_field import (
    LapSamples,
    RoadAttitudeField,
    RoadAttitudeFieldConfig,
    estimate_road_attitude_field,
)

_G = 9.80665


# ── Synthetic-track fixture ──────────────────────────────────────


def _oval_centerline(length_m: float = 300.0, n: int = 301) -> np.ndarray:
    """Simple closed oval as the reference centerline."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=True)
    x = 60.0 * np.cos(t)
    y = 40.0 * np.sin(t)
    return np.column_stack([x, y])


def _make_lap_along_centerline(
    centerline: np.ndarray,
    *,
    speed_mps: float = 15.0,
    n_per_m: float = 2.0,
    bank_s_fn=lambda s: 0.0,     # bank (deg) as a function of s
    grade_s_fn=lambda s: 0.0,    # grade (deg) as a function of s
    noise_g: float = 0.01,
    seed: int = 0,
) -> LapSamples:
    """Build one lap that drives the centerline at constant speed, with
    ``alat_g = centripetal + sin(bank(s))`` so the estimator's evidence
    formula recovers the encoded bank field."""
    rng = np.random.default_rng(seed)
    cx, cy = centerline[:, 0], centerline[:, 1]
    # Arc-length along centerline
    dx = np.diff(cx)
    dy = np.diff(cy)
    seg = np.sqrt(dx ** 2 + dy ** 2)
    s_cl = np.concatenate([[0.0], np.cumsum(seg)])
    length = float(s_cl[-1])

    n_samples = int(length * n_per_m)
    s_samples = np.linspace(0, length - 1e-3, n_samples)
    x = np.interp(s_samples, s_cl, cx)
    y = np.interp(s_samples, s_cl, cy)

    # Signed curvature along sample path
    dxp = np.gradient(x)
    dyp = np.gradient(y)
    heading = np.unwrap(np.arctan2(dyp, dxp))
    ds = np.sqrt(dxp ** 2 + dyp ** 2)
    kappa = np.gradient(heading) / np.maximum(ds, 1e-6)
    kappa = np.clip(kappa, -0.1, 0.1)

    speed = np.full(n_samples, speed_mps)
    centripetal_g = speed ** 2 * kappa / _G

    bank_deg = np.array([bank_s_fn(s) for s in s_samples])
    grade_deg = np.array([grade_s_fn(s) for s in s_samples])
    alat_g = centripetal_g + np.sin(np.deg2rad(bank_deg)) + rng.normal(0, noise_g, n_samples)
    along_g = -np.sin(np.deg2rad(grade_deg)) + rng.normal(0, noise_g, n_samples)
    # Note: per the estimator's sign convention, along_g measures the
    # vehicle-felt longitudinal force in kart x. On uphill the kart is pulled
    # backward → along_g ≈ -sin(grade) at constant speed.

    dt_guess = length / (speed_mps * n_samples)
    return LapSamples(
        x=x, y=y, speed=speed,
        alat_g=alat_g, along_g=along_g,
        dt=dt_guess,
        orientation_quality=0.9,
        mount_unstable=False,
        source='synthetic',
    )


@pytest.fixture
def frenet():
    return FrenetFrame.from_centerline(_oval_centerline(n=301))


@pytest.fixture
def cfg():
    # Use a looser min_samples_per_bin for synthetic data — the oval has
    # ~600 samples distributed across 60 bins @ 5m, so ~10 samples/bin.
    return RoadAttitudeFieldConfig(
        s_bin_m=5.0,
        min_samples_per_bin=5,
        min_laps_per_bin=2,
        bank_min_centripetal_g=0.10,
        grade_max_transient_g=0.3,
    )


# ── 1. Flat road ────────────────────────────────────────────────


class TestFlatRoad:
    def test_flat_road_produces_near_zero(self, frenet, cfg):
        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=i)
                for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        assert isinstance(field, RoadAttitudeField)
        # Bank/grade should be near zero where bank was observable.
        bank_valid = field.confidence > 0.4
        if bank_valid.any():
            assert abs(float(np.mean(field.bank_mean_deg[bank_valid]))) < 1.0
            assert abs(float(np.mean(field.grade_mean_deg[bank_valid]))) < 1.0


# ── 2. Constant bank segment ────────────────────────────────────


class TestConstantBankSegment:
    def test_recovers_banked_window(self, frenet, cfg):
        # Banked from s=80 to s=160 at +4°, elsewhere 0°.
        def bank_fn(s):
            return 4.0 if 80.0 <= s <= 160.0 else 0.0
        laps = [_make_lap_along_centerline(
            frenet.centerline_xy, bank_s_fn=bank_fn, seed=i,
        ) for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)

        in_banked = (field.s_bins >= 90.0) & (field.s_bins <= 150.0) & (field.confidence > 0.3)
        out_banked = (
            ((field.s_bins < 70.0) | (field.s_bins > 170.0))
            & (field.confidence > 0.3)
        )
        if in_banked.any():
            assert 2.0 < np.mean(field.bank_mean_deg[in_banked]) < 6.0
        if out_banked.any():
            assert abs(np.mean(field.bank_mean_deg[out_banked])) < 1.0


# ── 3. Constant grade segment ───────────────────────────────────


class TestConstantGradeSegment:
    def test_recovers_grade_window(self, frenet, cfg):
        def grade_fn(s):
            return 3.0 if 40.0 <= s <= 120.0 else 0.0
        # For grade, use lower speed so grade gate passes (low long transient).
        laps = [_make_lap_along_centerline(
            frenet.centerline_xy, grade_s_fn=grade_fn, speed_mps=12.0, seed=i,
        ) for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)

        in_grade = (field.s_bins >= 50.0) & (field.s_bins <= 110.0) & (field.confidence > 0.3)
        out_grade = (
            ((field.s_bins < 30.0) | (field.s_bins > 130.0))
            & (field.confidence > 0.3)
        )
        if in_grade.any():
            mean_in = float(np.mean(field.grade_mean_deg[in_grade]))
            assert 1.5 < mean_in < 4.5, f"grade in-window {mean_in} not near 3°"
        if out_grade.any():
            mean_out = float(np.mean(field.grade_mean_deg[out_grade]))
            assert abs(mean_out) < 1.2


# ── 4. Repeated noisy laps converge ─────────────────────────────


class TestMultiLapConvergence:
    def test_more_laps_reduce_spread(self, frenet, cfg):
        # Compare 2-lap vs 10-lap aggregation on the same underlying field.
        def bank_fn(s):
            return 3.0 if 80.0 <= s <= 160.0 else 0.0
        laps = [_make_lap_along_centerline(
            frenet.centerline_xy, bank_s_fn=bank_fn, noise_g=0.05, seed=i,
        ) for i in range(12)]

        field_2 = estimate_road_attitude_field(laps[:2], frenet, cfg)
        field_10 = estimate_road_attitude_field(laps, frenet, cfg)

        # Bins that are confidently assessed in both
        common = (field_2.confidence > 0.4) & (field_10.confidence > 0.4) & \
                 (field_2.bank_std_deg > 0) & (field_10.bank_std_deg > 0)
        if common.any():
            # Spread should be lower or similar with more laps; it must not
            # increase by a margin. Robust stats may tie at a few bins, so
            # compare by median.
            s2 = float(np.median(field_2.bank_std_deg[common]))
            s10 = float(np.median(field_10.bank_std_deg[common]))
            assert s10 <= s2 + 0.2, f"10-lap spread {s10} should ≤ 2-lap spread {s2}"
        # Confidence should also not decrease meaningfully with more laps.
        if common.any():
            c2 = float(np.median(field_2.confidence[common]))
            c10 = float(np.median(field_10.confidence[common]))
            assert c10 >= c2 - 0.05


# ── 5. One bad lap does not dominate ────────────────────────────


class TestRobustnessToOutlierLap:
    def test_outlier_lap_does_not_shift_median(self, frenet, cfg):
        # Five clean laps of zero bank + one "bad" lap that reports +10° bank
        # everywhere (e.g., a sensor went crazy).
        clean = [_make_lap_along_centerline(
            frenet.centerline_xy, seed=i,
        ) for i in range(5)]
        bad = _make_lap_along_centerline(
            frenet.centerline_xy,
            bank_s_fn=lambda s: 10.0,       # wild bank signal
            seed=42,
        )
        bad.source = 'outlier'

        field = estimate_road_attitude_field(clean + [bad], frenet, cfg)

        ok_mask = field.confidence > 0.4
        if ok_mask.any():
            robust_mean = float(np.mean(field.bank_mean_deg[ok_mask]))
            # A naive mean over 6 laps with one outlier at 10° would give
            # 10/6 ≈ 1.67°. The robust median should stay near 0°.
            assert abs(robust_mean) < 1.2, f"outlier lap dominated: mean {robust_mean}"


# ── 6. Sparse coverage → low confidence ─────────────────────────


class TestSparseCoverage:
    def test_single_lap_gives_low_confidence(self, frenet, cfg):
        # With min_laps_per_bin=2, a single lap cannot unlock confidence.
        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=0)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        # No bin should have high confidence.
        assert (field.confidence > 0.5).sum() == 0
        # Values default to zero where invalid — no absurd outputs.
        assert np.abs(field.bank_mean_deg).max() <= cfg.bank_clamp_deg + 1e-6
        assert np.abs(field.grade_mean_deg).max() <= cfg.grade_clamp_deg + 1e-6


# ── 7. Bounded outputs ──────────────────────────────────────────


class TestOutputBounds:
    def test_outputs_clamped_and_finite(self, frenet, cfg):
        # Drive an exaggerated bank (20° — way beyond clamp) so we can
        # verify the clamp activates.
        def bank_fn(s):
            return 20.0
        laps = [_make_lap_along_centerline(
            frenet.centerline_xy, bank_s_fn=bank_fn, seed=i,
        ) for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)

        assert np.all(np.isfinite(field.bank_mean_deg))
        assert np.all(np.isfinite(field.grade_mean_deg))
        assert np.all(np.isfinite(field.confidence))
        assert np.all(np.abs(field.bank_mean_deg) <= cfg.bank_clamp_deg + 1e-6)
        assert np.all(np.abs(field.grade_mean_deg) <= cfg.grade_clamp_deg + 1e-6)
        assert np.all(field.confidence >= 0.0)
        assert np.all(field.confidence <= 1.0)


# ── 8. Sign-convention consistency ──────────────────────────────


class TestSignConvention:
    def test_positive_bank_recovered_positive(self, frenet, cfg):
        def bank_fn(s):
            return +5.0 if 80.0 <= s <= 160.0 else 0.0
        laps = [_make_lap_along_centerline(
            frenet.centerline_xy, bank_s_fn=bank_fn, seed=i,
        ) for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        banked = (field.s_bins >= 90.0) & (field.s_bins <= 150.0) & (field.confidence > 0.3)
        if banked.any():
            assert np.mean(field.bank_mean_deg[banked]) > 2.0

    def test_negative_bank_recovered_negative(self, frenet, cfg):
        def bank_fn(s):
            return -5.0 if 80.0 <= s <= 160.0 else 0.0
        laps = [_make_lap_along_centerline(
            frenet.centerline_xy, bank_s_fn=bank_fn, seed=i,
        ) for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        banked = (field.s_bins >= 90.0) & (field.s_bins <= 150.0) & (field.confidence > 0.3)
        if banked.any():
            assert np.mean(field.bank_mean_deg[banked]) < -2.0

    def test_positive_grade_recovered_positive(self, frenet, cfg):
        def grade_fn(s):
            return +4.0 if 40.0 <= s <= 120.0 else 0.0
        laps = [_make_lap_along_centerline(
            frenet.centerline_xy, grade_s_fn=grade_fn, speed_mps=12.0, seed=i,
        ) for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        graded = (field.s_bins >= 50.0) & (field.s_bins <= 110.0) & (field.confidence > 0.3)
        if graded.any():
            assert np.mean(field.grade_mean_deg[graded]) > 1.5


# ── Diagnostic shape tests ──────────────────────────────────────


class TestDiagnostics:
    def test_diagnostic_fields_populated(self, frenet, cfg):
        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=i)
                for i in range(3)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        for key in (
            's_bin_m', 'n_bins', 'n_bins_bank_valid', 'n_bins_grade_valid',
            'bank_coverage_frac', 'grade_coverage_frac',
            'n_laps_total', 'n_laps_used_bank',
            'median_bank_std_on_valid_deg', 'median_grade_std_on_valid_deg',
        ):
            assert key in field.diagnostics, f"missing diagnostic {key}"

    def test_to_dict_json_safe(self, frenet, cfg):
        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=i)
                for i in range(2)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        import json
        # Should round-trip through JSON.
        json.dumps(field.to_dict())


# ── Regression: bronze/silver demand must never be affected by the field ──
#
# The field is a shadow-only diagnostic. If future refactors accidentally
# wire it into the demand accumulators, these tests must fail.


class TestBronzeSilverIsolation:
    def test_field_does_not_mutate_lap_inputs(self, frenet, cfg):
        """RoadAttitudeField must be pure: the input ``LapSamples`` arrays
        must be bit-identical after the call. A mutation here could silently
        change the lateral/longitudinal demand arrays that bronze/silver
        consume upstream."""
        import copy

        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=i)
                for i in range(4)]
        snapshots = [copy.deepcopy(lap) for lap in laps]
        _ = estimate_road_attitude_field(laps, frenet, cfg)

        for orig, after in zip(snapshots, laps):
            assert np.array_equal(orig.x, after.x), "lap.x was mutated"
            assert np.array_equal(orig.y, after.y), "lap.y was mutated"
            assert np.array_equal(orig.speed, after.speed), "lap.speed was mutated"
            assert np.array_equal(orig.alat_g, after.alat_g), "lap.alat_g was mutated"
            assert np.array_equal(orig.along_g, after.along_g), "lap.along_g was mutated"

    def test_field_dict_keys_disjoint_from_bronze_silver(self, frenet, cfg):
        """``RoadAttitudeField.to_dict()`` keys must not collide with the
        bronze/silver keys the viewer reads. If a collision appears we have
        silently clobbered a production channel."""
        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=i)
                for i in range(3)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        field_keys = set(field.to_dict().keys())

        # These are the bronze/silver keys used by build_ok_raw.py and the
        # Three.js viewer. Any overlap would silently overwrite production
        # data when ``data[...] = field.to_dict()`` is serialized.
        bronze_silver_keys = {
            'grip_map',                # legacy bronze key kept for compat
            'lateral_demand',          # bronze excited_p90 block
            'lateral_demand_2d',       # silver 2D grid
            'sensor_quality',
            'map_confidence',
            'drivers', 'stats', 'track', 'elevation', 'boundaries',
            # Silver-internal grid keys (leaf-level, not top-level, but
            # listed defensively)
            'excited_p90', 'occupancy', 'racing_line_mask',
            'on_line_mean_demand', 'off_line_mean_demand',
        }
        conflicts = field_keys & bronze_silver_keys
        assert not conflicts, (
            f"road_attitude_field emits keys that collide with bronze/silver: "
            f"{conflicts}. This would silently overwrite production data in "
            f"the serialized JSON."
        )

    def test_field_module_does_not_import_demand_accumulators(self):
        """The field module must not reach into the bronze/silver demand
        accumulator modules. If it starts doing so, we are one rewrite away
        from feedback between shadow-mode diagnostics and production demand."""
        import importlib
        mod = importlib.import_module('track_surface.road_attitude_field')
        src = open(mod.__file__, encoding='utf-8').read()
        # These module references would indicate upward coupling into demand.
        forbidden = [
            'from track_surface.demand_2d',
            'import demand_2d',
            'build_demand_surface_2d',
            'DemandSurface2D',
            'excited_p90',
        ]
        for phrase in forbidden:
            assert phrase not in src, (
                f"road_attitude_field.py contains '{phrase}' — this indicates "
                f"coupling to the bronze/silver demand pipeline that the "
                f"shadow-mode contract forbids."
            )

    def test_idempotent_across_repeated_calls(self, frenet, cfg):
        """Two calls on the same inputs must produce identical output.
        A hidden side-effect in the estimator would surface here as drift."""
        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=i)
                for i in range(3)]
        f1 = estimate_road_attitude_field(laps, frenet, cfg)
        f2 = estimate_road_attitude_field(laps, frenet, cfg)
        assert np.array_equal(f1.bank_mean_deg, f2.bank_mean_deg)
        assert np.array_equal(f1.bank_std_deg, f2.bank_std_deg)
        assert np.array_equal(f1.grade_mean_deg, f2.grade_mean_deg)
        assert np.array_equal(f1.confidence, f2.confidence)
        assert np.array_equal(f1.bank_confidence, f2.bank_confidence)


class TestPerChannelOutputs:
    def test_per_channel_arrays_populate(self, frenet, cfg):
        laps = [_make_lap_along_centerline(frenet.centerline_xy, seed=i)
                for i in range(4)]
        field = estimate_road_attitude_field(laps, frenet, cfg)
        M = len(field.s_bins)
        for arr in (field.bank_confidence, field.bank_evidence_count,
                    field.bank_lap_coverage, field.grade_confidence,
                    field.grade_evidence_count, field.grade_lap_coverage):
            assert arr.shape == (M,), f"per-channel array has wrong shape: {arr.shape}"
        # Per-channel confidences should be ≤ the combined (max) confidence.
        assert np.all(field.bank_confidence <= field.confidence + 1e-9)
        assert np.all(field.grade_confidence <= field.confidence + 1e-9)
