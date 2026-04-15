"""Tests for road_attitude_estimator.py — bank/grade estimation from phone IMU + GPS.

Test coverage (per spec):
    1. Flat road                  — bank ≈ 0, grade ≈ 0, reasonable quality
    2. Constant grade             — known uphill recovered within tolerance
    3. Constant bank              — known bank recovered under low-dynamic conditions
    4. Dynamic contamination      — strong long. accel reduces confidence
    5. Low-speed                  — confidence drops, instability flags raised
    6. Mount instability          — unstable mount propagates to all samples
    7. Output sanity              — bounded, finite, correct shapes/types

The estimator separates road tilt from vehicle motion. It does NOT estimate
tire-road friction. These tests verify it correctly attributes the gravity-like
component of measured accel to road attitude (after subtracting expected
vehicle accel from GPS speed and curvature).
"""
from __future__ import annotations

import numpy as np
import pytest

from phone_mount_estimator import PhoneMountEstimate
from road_attitude_estimator import RoadAttitudeEstimate, estimate_road_attitude

_G = 9.80665


# ── Mount fixtures ──────────────────────────────────────────────


def _level_mount(orientation_quality: float = 0.9, unstable: bool = False) -> PhoneMountEstimate:
    """Phone perfectly aligned with kart (R = identity), gravity = (0, 0, -1)."""
    return PhoneMountEstimate(
        R_phone_to_kart=np.eye(3),
        gravity_vector=np.array([0.0, 0.0, -1.0]),
        orientation_quality=orientation_quality,
        mount_unstable=unstable,
        confidence_flags={'forward_axis_known': True},
    )


# ── Data-generation helpers ─────────────────────────────────────


def _make_session(
    n: int,
    *,
    g_kart: tuple[float, float, float] = (0.0, 0.0, -1.0),
    speed_mps: float | np.ndarray = 15.0,
    noise: float = 0.005,
    dt: float = 0.04,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build (accel_phone, gyro_phone, gps_speed, timestamps) for a steady scene.

    With R = identity and the phone aligned with the kart, the phone's measured
    accel equals the kart-frame accel, which (with no vehicle dynamics) is just
    the gravity vector projected into the kart frame — i.e. ``g_kart``.
    """
    rng = np.random.default_rng(seed)
    timestamps = np.arange(n) * dt
    if np.isscalar(speed_mps):
        gps_speed = np.full(n, float(speed_mps))
    else:
        gps_speed = np.asarray(speed_mps, dtype=float)
    accel = np.tile(np.array(g_kart, dtype=float), (n, 1)) + rng.normal(0, noise, (n, 3))
    gyro = rng.normal(0, 0.5, (n, 3))
    return accel, gyro, gps_speed, timestamps


# ── 1. Flat road ────────────────────────────────────────────────


class TestFlatRoad:
    def test_flat_road_bank_and_grade_near_zero(self):
        # Phone level, level road, steady speed → no tilt of any kind.
        accel, gyro, speed, ts = _make_session(n=600, g_kart=(0, 0, -1))
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        assert isinstance(result, RoadAttitudeEstimate)
        # Bank and grade should both stay essentially zero on a flat road.
        assert abs(result.mean_bank_deg) < 1.0
        assert abs(result.mean_grade_deg) < 1.0
        # Most of the segment should be considered usable.
        high_conf_frac = result.confidence_flags['high_confidence_fraction']
        assert high_conf_frac > 0.5

    def test_flat_road_no_unstable_propagation(self):
        accel, gyro, speed, ts = _make_session(n=600, g_kart=(0, 0, -1))
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())
        # On flat steady data, only the very-low-speed bookends (if any) should flag.
        # Here speed is constant 15 m/s so nothing should flag.
        assert result.unstable_segments.sum() == 0


# ── 2. Constant grade ──────────────────────────────────────────


class TestConstantGrade:
    @pytest.mark.parametrize("grade_true_deg", [3.0, 5.0, -4.0])
    def test_known_grade_recovered(self, grade_true_deg):
        # On an inclined road, gravity in the kart frame has an x-component
        # equal to -sin(grade) (uphill → gravity pulls backward along forward axis).
        rad = np.deg2rad(grade_true_deg)
        g_kart = (-np.sin(rad), 0.0, -np.cos(rad))
        accel, gyro, speed, ts = _make_session(n=800, g_kart=g_kart)
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        # Recovered grade should match within ~1° (smoothing + clamping tolerance).
        assert abs(result.mean_grade_deg - grade_true_deg) < 1.0
        # Bank should remain near zero — the road is not banked.
        assert abs(result.mean_bank_deg) < 1.0


# ── 3. Constant bank ───────────────────────────────────────────


class TestConstantBank:
    @pytest.mark.parametrize("bank_true_deg", [3.0, 5.0, -4.0])
    def test_known_bank_recovered_low_dynamic(self, bank_true_deg):
        # Banked road, no curvature, no acceleration → bank fully observable.
        # Per code convention, +bank means gravity has +y component in kart frame.
        rad = np.deg2rad(bank_true_deg)
        g_kart = (0.0, np.sin(rad), -np.cos(rad))
        accel, gyro, speed, ts = _make_session(n=800, g_kart=g_kart)
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        assert abs(result.mean_bank_deg - bank_true_deg) < 1.0
        # No grade — the road is only banked.
        assert abs(result.mean_grade_deg) < 1.0


# ── 4. Dynamic contamination ───────────────────────────────────


class TestDynamicContamination:
    def test_hard_braking_lowers_quality(self):
        """High |dv/dt| segments should have lower attitude_quality than calm segments."""
        n = 1500
        dt = 0.04
        ts = np.arange(n) * dt

        # First half: steady 15 m/s. Second half: hard braking 15 → 0 m/s.
        speed = np.empty(n)
        speed[: n // 2] = 15.0
        # Braking spans the second half (~30 s) — well above the 3 m/s² penalty knee.
        speed[n // 2:] = np.linspace(15.0, 0.0, n - n // 2)

        # Phone reads gravity + reaction to vehicle accel along kart x.
        # dv/dt is negative during braking (deceleration), so the phone reads
        # negative on x — but we feed that consistently so the estimator can
        # subtract it via gps-speed-derived dv/dt. Quality should still drop
        # because of the dynamic_score penalty.
        rng = np.random.default_rng(2)
        dv_dt = np.gradient(speed) / dt           # m/s²
        long_g = dv_dt / _G                       # phone measures reaction → +dv_dt_g on x
        accel = np.zeros((n, 3))
        accel[:, 0] = long_g + rng.normal(0, 0.005, n)
        accel[:, 1] = rng.normal(0, 0.005, n)
        accel[:, 2] = -1.0 + rng.normal(0, 0.005, n)
        gyro = rng.normal(0, 0.5, (n, 3))

        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        # Compare interior quality of both halves (avoid filter edge effects).
        margin = 100
        calm_q = result.attitude_quality[margin: n // 2 - margin].mean()
        brake_q = result.attitude_quality[n // 2 + margin: -margin].mean()
        assert brake_q < calm_q, f"braking quality {brake_q:.3f} should be < calm {calm_q:.3f}"

    def test_high_curvature_lowers_quality(self):
        """High lateral demand from curvature should reduce confidence."""
        n = 1200
        accel, gyro, speed, ts = _make_session(n=n)
        # Cornering segment in the middle 1/3 of the run — curvature 0.05 1/m at 15 m/s
        # gives v²κ/g ≈ 1.15 g lateral, well above the 0.5 g penalty knee.
        curvature = np.zeros(n)
        curvature[n // 3: 2 * n // 3] = 0.05

        result = estimate_road_attitude(
            accel, gyro, speed, ts, _level_mount(), curvature=curvature,
        )

        margin = 80
        straight_q = np.concatenate([
            result.attitude_quality[margin: n // 3 - margin],
            result.attitude_quality[2 * n // 3 + margin: -margin],
        ]).mean()
        corner_q = result.attitude_quality[n // 3 + margin: 2 * n // 3 - margin].mean()
        assert corner_q < straight_q


# ── 5. Low-speed ───────────────────────────────────────────────


class TestLowSpeed:
    def test_below_min_speed_marks_unstable(self):
        # All samples below half the min_speed threshold (default 5/2 = 2.5 m/s).
        accel, gyro, _, ts = _make_session(n=500, speed_mps=1.0)
        speed = np.full(500, 1.0)
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        # Every sample should be flagged unstable due to low speed.
        assert result.unstable_segments.all()
        # And confidence should be visibly degraded.
        assert result.confidence_flags['unstable_fraction'] == 1.0

    def test_low_speed_lowers_speed_score(self):
        # Speeds at 2 m/s — below the 5 m/s knee, so speed_score = 0 for all samples.
        accel, gyro, _, ts = _make_session(n=500, speed_mps=2.0)
        speed = np.full(500, 2.0)
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        assert result.confidence_flags['mean_speed_score'] == 0.0
        # Mean attitude quality should be capped well below 1 because speed_score
        # contributes 30% of the composite.
        assert result.attitude_quality.mean() < 0.7


# ── 6. Mount instability propagation ──────────────────────────


class TestMountInstabilityPropagation:
    def test_unstable_mount_marks_all_samples(self):
        accel, gyro, speed, ts = _make_session(n=500)
        unstable_mount = _level_mount(orientation_quality=0.3, unstable=True)
        result = estimate_road_attitude(accel, gyro, speed, ts, unstable_mount)

        # Mount instability must propagate — every sample is suspect.
        assert result.unstable_segments.all()
        assert result.confidence_flags['mount_unstable'] is True

    def test_low_orientation_quality_lowers_mount_score(self):
        # Mount quality contributes 20% of the composite — low quality → lower bound.
        accel, gyro, speed, ts = _make_session(n=600)
        result_high = estimate_road_attitude(
            accel, gyro, speed, ts, _level_mount(orientation_quality=0.95),
        )
        result_low = estimate_road_attitude(
            accel, gyro, speed, ts, _level_mount(orientation_quality=0.1),
        )
        assert result_low.attitude_quality.mean() < result_high.attitude_quality.mean()
        assert result_low.confidence_flags['mount_orientation_quality'] < 0.5
        assert result_high.confidence_flags['mount_orientation_quality'] > 0.5


# ── 7. Output sanity ──────────────────────────────────────────


class TestOutputSanity:
    def test_output_shapes_and_types(self):
        n = 500
        accel, gyro, speed, ts = _make_session(n=n)
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        assert result.bank_deg.shape == (n,)
        assert result.grade_deg.shape == (n,)
        assert result.attitude_quality.shape == (n,)
        assert result.unstable_segments.shape == (n,)
        assert result.unstable_segments.dtype == bool
        assert isinstance(result.mean_bank_deg, float)
        assert isinstance(result.mean_grade_deg, float)
        assert isinstance(result.confidence_flags, dict)

    def test_outputs_finite(self):
        accel, gyro, speed, ts = _make_session(n=500)
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        assert np.all(np.isfinite(result.bank_deg))
        assert np.all(np.isfinite(result.grade_deg))
        assert np.all(np.isfinite(result.attitude_quality))
        assert np.isfinite(result.mean_bank_deg)
        assert np.isfinite(result.mean_grade_deg)

    def test_outputs_bounded(self):
        # Even with extreme synthetic data, outputs should respect the configured
        # clamps so downstream physical interpretations stay sane.
        n = 600
        # Wildly tilted scene: should be clamped, not wrap or NaN.
        rad = np.deg2rad(45.0)
        accel, gyro, speed, ts = _make_session(
            n=n, g_kart=(-np.sin(rad), np.sin(rad) * np.cos(rad), -np.cos(rad) ** 2),
        )
        result = estimate_road_attitude(
            accel, gyro, speed, ts, _level_mount(),
            bank_max_deg=12.0, grade_max_deg=10.0,
        )

        assert np.all(np.abs(result.bank_deg) <= 12.0 + 1e-6)
        assert np.all(np.abs(result.grade_deg) <= 10.0 + 1e-6)
        assert np.all(result.attitude_quality >= 0.0)
        assert np.all(result.attitude_quality <= 1.0)

    def test_insufficient_data_returns_safe_empty(self):
        # Below the n<50 threshold the estimator must return a safe empty result
        # rather than crash — downstream code reads attitude_quality unconditionally.
        accel, gyro, speed, ts = _make_session(n=30)
        result = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())

        assert isinstance(result, RoadAttitudeEstimate)
        assert result.confidence_flags.get('insufficient_data') is True
        assert result.attitude_quality.sum() == 0.0
        assert result.unstable_segments.all()

    def test_curvature_flag_in_confidence(self):
        accel, gyro, speed, ts = _make_session(n=500)
        # Without curvature
        r1 = estimate_road_attitude(accel, gyro, speed, ts, _level_mount())
        assert r1.confidence_flags['curvature_available'] is False
        # With curvature
        curv = np.zeros(500)
        r2 = estimate_road_attitude(accel, gyro, speed, ts, _level_mount(), curvature=curv)
        assert r2.confidence_flags['curvature_available'] is True
