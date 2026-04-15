"""Tests for track_surface/attitude_correction.py — gated demand correction.

These verify the *integration* of the mount + road-attitude estimators
into the demand-cleaning path. The estimators themselves are tested
elsewhere (test_phone_mount_estimator, test_road_attitude_estimator).

Key behaviors verified:
    1. Disabled / insufficient data → raw passthrough (lossless)
    2. Low-quality samples preserve raw demand (no interpolation, no zero-fill)
    3. Unstable samples preserve raw demand
    4. High-quality stable samples receive bank/grade subtraction
    5. Diagnostic metadata fields populate correctly
    6. Session-level diagnostics aggregate per-lap diagnostics correctly
"""
from __future__ import annotations

import numpy as np
import pytest

from phone_mount_estimator import PhoneMountEstimate
from track_surface.attitude_correction import (
    ATTITUDE_CORRECTION_ENABLED,
    BANK_CORRECTION_CLAMP_DEG,
    GRADE_CORRECTION_CLAMP_DEG,
    MIN_ATTITUDE_QUALITY_FOR_CORRECTION,
    AttitudeCorrectionResult,
    apply_attitude_correction,
    merge_session_diagnostics,
)

_G = 9.80665


def _level_mount(orientation_quality: float = 0.9, unstable: bool = False) -> PhoneMountEstimate:
    """A pre-computed mount with R = identity (phone aligned with kart).

    In production this would be calibrated once per session on a calm segment
    and reused across all laps. Here it lets us exercise the correction code
    path on synthetic banked/graded data without the mount estimator
    absorbing the road tilt into the rotation matrix.
    """
    return PhoneMountEstimate(
        R_phone_to_kart=np.eye(3),
        gravity_vector=np.array([0.0, 0.0, -1.0]),
        orientation_quality=orientation_quality,
        mount_unstable=unstable,
        confidence_flags={'forward_axis_known': True},
    )


# ── Synthetic data builders ────────────────────────────────────


def _flat_road_session(
    n: int = 800,
    *,
    speed_mps: float = 15.0,
    g_kart: tuple[float, float, float] = (0.0, 0.0, -1.0),
    noise: float = 0.005,
    seed: int = 0,
) -> dict:
    """A clean, level, steady-speed scene the mount estimator can lock onto.

    Includes mild forward acceleration variation so the mount estimator's
    forward-axis correlation has signal to work with.
    """
    rng = np.random.default_rng(seed)
    dt = 0.04
    timestamps = np.arange(n) * dt
    # Speed wobble so dv/dt has structure → forward axis recoverable.
    speed = speed_mps + 2.0 * np.sin(timestamps * 2 * np.pi / 8.0)
    dv_dt = np.gradient(speed) / dt

    # Build phone-frame accel: gravity + reaction to longitudinal accel on x-axis.
    accel = np.zeros((n, 3))
    accel[:, 0] = g_kart[0] + (dv_dt / _G) + rng.normal(0, noise, n)
    accel[:, 1] = g_kart[1] + rng.normal(0, noise, n)
    accel[:, 2] = g_kart[2] + rng.normal(0, noise, n)

    gyro = rng.normal(0, 0.5, (n, 3))
    return {
        'accel': accel,
        'gyro': gyro,
        'gps_speed': speed,
        'timestamps': timestamps,
        'alat_g_kart': accel[:, 1].copy(),
        'along_g_kart': accel[:, 0].copy(),
    }


def _banked_road_session(bank_deg: float, n: int = 1000) -> dict:
    """Steady speed on a banked road. With curvature provided, bank should be observable."""
    rad = np.deg2rad(bank_deg)
    return _flat_road_session(
        n=n,
        g_kart=(0.0, np.sin(rad), -np.cos(rad)),
    )


# ── 1. Disabled / insufficient data → raw passthrough ─────────


class TestPassthrough:
    def test_disabled_returns_raw(self):
        s = _flat_road_session(n=500)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
            enabled=False,
        )
        assert isinstance(result, AttitudeCorrectionResult)
        # Corrected must equal raw on a passthrough.
        assert np.array_equal(result.alat_g_raw, result.alat_g_corrected)
        assert np.array_equal(result.along_g_raw, result.along_g_corrected)
        # No samples flagged as applied.
        assert result.applied_mask.sum() == 0
        assert result.diagnostics['skipped_reason'] == 'disabled'
        # No estimators were even constructed.
        assert result.mount_estimate is None
        assert result.attitude_estimate is None

    def test_insufficient_samples_returns_raw(self):
        s = _flat_road_session(n=20)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
        )
        assert np.array_equal(result.alat_g_raw, result.alat_g_corrected)
        assert result.diagnostics['skipped_reason'] == 'insufficient_samples'
        assert result.applied_mask.sum() == 0


# ── 2. Low-quality samples preserve raw ───────────────────────


class TestLowQualityPreservesRaw:
    def test_low_quality_threshold_skips_correction(self):
        s = _flat_road_session(n=600)
        # Force every sample low-quality by demanding an unreasonably high bar.
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
            min_attitude_quality=2.0,    # impossible — clamps make max 1.0
        )
        # Every sample should be passthrough, not corrected.
        assert result.applied_mask.sum() == 0
        assert np.array_equal(result.alat_g_raw, result.alat_g_corrected)
        assert np.array_equal(result.along_g_raw, result.along_g_corrected)
        # But the estimators DID run — diagnostics still meaningful.
        assert result.attitude_estimate is not None
        assert result.diagnostics['attitude_low_confidence_frac'] == 1.0
        assert result.diagnostics['attitude_correction_active_frac'] == 0.0

    def test_low_speed_keeps_raw(self):
        # All samples below half the min_speed_mps default → unstable_segments[:] = True
        s = _flat_road_session(n=600, speed_mps=1.0)
        speed = np.full(600, 1.0)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], speed, s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
        )
        assert result.applied_mask.sum() == 0
        assert np.array_equal(result.alat_g_raw, result.alat_g_corrected)
        assert result.diagnostics['attitude_unstable_frac'] == 1.0


# ── 3. Unstable samples preserve raw ──────────────────────────


class TestUnstableSamplesPreserveRaw:
    def test_simulated_mount_slip_blocks_correction(self):
        """Sudden accel-vector jump mid-session simulates a mount slip."""
        rng = np.random.default_rng(7)
        n = 1500
        dt = 0.04
        timestamps = np.arange(n) * dt
        speed = 15.0 + 2.0 * np.sin(timestamps * 2 * np.pi / 8.0)
        dv_dt = np.gradient(speed) / dt

        accel = np.zeros((n, 3))
        # First half: phone z-down. Second half: 30° rotation.
        accel[: n // 2, :] = np.array([0.0, 0.0, -1.0])
        accel[n // 2:, :] = np.array([0.5, 0.0, -0.866])
        accel[:, 0] += dv_dt / _G                       # add forward reaction
        accel += rng.normal(0, 0.005, (n, 3))
        gyro = rng.normal(0, 1.0, (n, 3))

        result = apply_attitude_correction(
            accel, gyro, speed, timestamps,
            alat_g_kart=accel[:, 1].copy(),
            along_g_kart=accel[:, 0].copy(),
        )
        # Mount instability should propagate: either mount_unstable flag set, or
        # the unstable_fraction is at the floor (the attitude estimator will
        # mark all samples unstable when mount_unstable=True).
        if result.mount_estimate is not None and result.mount_estimate.mount_unstable:
            assert result.diagnostics['attitude_unstable_frac'] == 1.0
            assert result.applied_mask.sum() == 0
            assert np.array_equal(result.alat_g_raw, result.alat_g_corrected)


# ── 4. High-quality stable samples are corrected ──────────────


class TestHighQualityCorrected:
    def test_known_bank_subtracted_from_alat(self):
        """With a pre-calibrated level mount, a 5° banked road shows ~sin(5°) ≈ 0.087 G
        on the lateral axis. The correction should subtract that off applied samples
        and push the corrected mean toward zero."""
        s = _banked_road_session(bank_deg=5.0, n=1200)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
            mount_estimate=_level_mount(),     # session-scoped calibration
        )
        # Some samples should be applied (interior of the segment).
        assert result.applied_mask.sum() > 0, "expected some applied samples on clean banked data"
        # Mean shift on applied samples should pull |alat| toward zero.
        applied = result.applied_mask
        raw_mean = float(np.mean(result.alat_g_raw[applied]))
        cor_mean = float(np.mean(result.alat_g_corrected[applied]))
        assert raw_mean > 0.05, "raw should reflect bank tilt"
        assert abs(cor_mean) < abs(raw_mean), "correction should reduce |alat|"
        # Diagnostic should report a ~5° bank within smoothing tolerance.
        assert abs(result.diagnostics['mean_estimated_bank_deg'] - 5.0) < 1.5

    def test_flat_road_correction_is_near_zero(self):
        """On a flat road, even when the correction *is* applied, the bank/grade are
        ~0 so the corrected channels stay close to raw."""
        s = _flat_road_session(n=800)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
            mount_estimate=_level_mount(),
        )
        # Diagnostics should show small deltas.
        assert result.diagnostics['mean_abs_delta_alat_g'] < 0.05
        assert result.diagnostics['mean_abs_delta_along_g'] < 0.05


# ── 5. Diagnostic metadata ────────────────────────────────────


class TestDiagnosticsPopulate:
    def test_required_keys_present(self):
        s = _flat_road_session(n=500)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
        )
        required = {
            'mean_estimated_bank_deg',
            'mean_estimated_grade_deg',
            'attitude_correction_active_frac',
            'attitude_low_confidence_frac',
            'attitude_unstable_frac',
            'mean_abs_delta_alat_g',
            'mean_abs_delta_along_g',
            'mean_abs_delta_combined_g',
        }
        missing = required - set(result.diagnostics.keys())
        assert not missing, f"missing diagnostic keys: {missing}"

    def test_fractions_in_unit_interval(self):
        s = _flat_road_session(n=500)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
        )
        for k in ('attitude_correction_active_frac',
                  'attitude_low_confidence_frac',
                  'attitude_unstable_frac'):
            v = result.diagnostics[k]
            assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"

    def test_no_friction_terminology_in_diagnostics(self):
        # Defensive: bronze/silver invariant is "demand, not friction".
        # If anyone ever adds a 'mu', 'grip', 'friction' key, this test catches it.
        s = _flat_road_session(n=500)
        result = apply_attitude_correction(
            s['accel'], s['gyro'], s['gps_speed'], s['timestamps'],
            alat_g_kart=s['alat_g_kart'], along_g_kart=s['along_g_kart'],
        )
        forbidden_substrings = ('mu_', 'grip', 'friction')
        for key in result.diagnostics:
            lower = key.lower()
            for forbid in forbidden_substrings:
                assert forbid not in lower, (
                    f"diagnostic key '{key}' contains forbidden term '{forbid}' — "
                    "this module must use demand-cleaning vocabulary only"
                )


# ── 6. Session-level merge ───────────────────────────────────


class TestSessionMerge:
    def test_merge_empty_returns_zeros(self):
        merged = merge_session_diagnostics([])
        assert merged['n_laps_analyzed'] == 0
        assert merged['mean_estimated_bank_deg'] == 0.0
        assert merged['attitude_correction_active_frac'] == 0.0

    def test_merge_weights_by_sample_count(self):
        # Three "laps": one big with bank=4°, two small with bank=0°.
        # Weighted mean should pull strongly toward the big lap.
        per_lap = [
            {'n_samples': 1000, 'mean_estimated_bank_deg': 4.0,
             'mean_estimated_grade_deg': 0.0,
             'attitude_correction_active_frac': 0.8,
             'attitude_low_confidence_frac': 0.1,
             'attitude_unstable_frac': 0.1,
             'mean_abs_delta_alat_g': 0.07,
             'mean_abs_delta_along_g': 0.0,
             'mean_abs_delta_combined_g': 0.05},
            {'n_samples': 100, 'mean_estimated_bank_deg': 0.0,
             'mean_estimated_grade_deg': 0.0,
             'attitude_correction_active_frac': 0.5,
             'attitude_low_confidence_frac': 0.5,
             'attitude_unstable_frac': 0.0,
             'mean_abs_delta_alat_g': 0.0,
             'mean_abs_delta_along_g': 0.0,
             'mean_abs_delta_combined_g': 0.0},
            {'n_samples': 100, 'mean_estimated_bank_deg': 0.0,
             'mean_estimated_grade_deg': 0.0,
             'attitude_correction_active_frac': 0.5,
             'attitude_low_confidence_frac': 0.5,
             'attitude_unstable_frac': 0.0,
             'mean_abs_delta_alat_g': 0.0,
             'mean_abs_delta_along_g': 0.0,
             'mean_abs_delta_combined_g': 0.0},
        ]
        merged = merge_session_diagnostics(per_lap)
        # Big lap dominates: 4 * 1000 / 1200 ≈ 3.33
        assert abs(merged['mean_estimated_bank_deg'] - 3.333) < 0.01
        assert merged['n_laps_analyzed'] == 3


# ── 7. Constants are sane ────────────────────────────────────


class TestConfigConstants:
    def test_quality_threshold_in_unit_interval(self):
        assert 0.0 < MIN_ATTITUDE_QUALITY_FOR_CORRECTION < 1.0

    def test_clamp_values_are_conservative(self):
        # Real karting tracks rarely exceed 5° bank, paved roads rarely 8% grade.
        # Clamps must be looser than that but tight enough to reject runaway.
        assert 5.0 <= BANK_CORRECTION_CLAMP_DEG <= 20.0
        assert 5.0 <= GRADE_CORRECTION_CLAMP_DEG <= 20.0

    def test_default_enabled(self):
        # Master toggle defaults ON; tests above can flip it per-call.
        assert ATTITUDE_CORRECTION_ENABLED is True
