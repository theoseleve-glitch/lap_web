"""Tests for phone_mount_estimator.py — phone IMU/GPS to kart frame estimation."""
from __future__ import annotations

import numpy as np
import pytest

from phone_mount_estimator import (
    PhoneMountEstimate,
    estimate_phone_mount,
    estimate_gravity,
    estimate_forward_axis,
    build_rotation_matrix,
    detect_mount_instability,
)

_G = 9.80665


# ── Test fixtures ────────────────────────────────────────────────


def make_static_data(n=500, gravity_phone=(0, 0, -1), noise=0.005):
    """Stationary phone with known orientation."""
    rng = np.random.default_rng(42)
    accel = np.tile(np.array(gravity_phone), (n, 1)) + rng.normal(0, noise, (n, 3))
    gyro = rng.normal(0, 1.0, (n, 3))  # small gyro noise
    speed = np.zeros(n)
    timestamps = np.arange(n) * 0.04  # 25Hz
    return accel, gyro, speed, timestamps


def make_straight_line_data(
    n=2000,
    gravity_phone=(0, 0, -1),
    forward_phone=(1, 0, 0),
    noise=0.01,
):
    """Phone at constant orientation, vehicle accelerating then decelerating
    along forward_phone."""
    rng = np.random.default_rng(0)
    timestamps = np.arange(n) * 0.04

    # Speed profile: 0 -> 30 m/s -> 5 m/s -> 30 m/s
    t = timestamps
    speed = 5.0 + 12.5 * (1 + np.sin(t * 2 * np.pi / 20.0))  # oscillates 5-30 m/s
    dv_dt = np.gradient(speed) / 0.04  # m/s²

    # Vehicle acceleration along forward_phone, in g
    fwd = np.array(forward_phone, dtype=float)
    fwd /= np.linalg.norm(fwd)
    veh_accel = np.outer(dv_dt / _G, fwd)  # (n, 3)

    # Total accel = gravity + vehicle
    g_vec = np.array(gravity_phone, dtype=float)
    accel = g_vec[None, :] + veh_accel + rng.normal(0, noise, (n, 3))
    gyro = rng.normal(0, 0.5, (n, 3))
    return accel, gyro, speed, timestamps


def make_sudden_rotation_data(n=2000):
    """Phone orientation changes mid-data (mount slip)."""
    rng = np.random.default_rng(1)
    timestamps = np.arange(n) * 0.04
    accel = np.zeros((n, 3))
    accel[:n // 2] = np.array([0, 0, -1])
    accel[n // 2:] = np.array([0.5, 0, -0.866])  # ~30° rotation
    accel += rng.normal(0, 0.01, (n, 3))
    gyro = rng.normal(0, 1.0, (n, 3))
    speed = np.full(n, 15.0)
    return accel, gyro, speed, timestamps


# ── 1. Static test: stable gravity ──────────────────────────────


class TestStaticGravity:
    def test_constant_orientation_stable_gravity(self):
        accel, gyro, _, ts = make_static_data(n=500)
        g_vec, stability = estimate_gravity(accel, gyro, ts)
        # Gravity should be near (0, 0, -1) within noise
        assert abs(g_vec[0]) < 0.05
        assert abs(g_vec[1]) < 0.05
        assert abs(g_vec[2] - (-1.0)) < 0.05
        # Stability should be high for static data
        assert stability > 0.7

    def test_tilted_phone_gravity(self):
        # Phone tilted 45 degrees: gravity should be (sin45, 0, -cos45)
        accel, gyro, _, ts = make_static_data(
            n=500, gravity_phone=(np.sin(np.pi / 4), 0, -np.cos(np.pi / 4)),
        )
        g_vec, stability = estimate_gravity(accel, gyro, ts)
        assert abs(g_vec[0] - np.sin(np.pi / 4)) < 0.05
        assert abs(g_vec[2] - (-np.cos(np.pi / 4))) < 0.05
        # Magnitude still ~1g
        assert abs(np.linalg.norm(g_vec) - 1.0) < 0.05


# ── 2. Straight-line motion: forward axis recovery ─────────────


class TestForwardAxisRecovery:
    def test_forward_aligns_with_velocity_direction(self):
        # Phone with X axis aligned with vehicle forward
        accel, gyro, speed, ts = make_straight_line_data(
            n=2000, forward_phone=(1, 0, 0),
        )
        gravity = np.array([0, 0, -1.0])
        fwd, conf = estimate_forward_axis(accel, gravity, speed, ts)
        assert fwd is not None
        assert conf > 0.5
        # Forward should be close to (1, 0, 0)
        # Allow either +X or -X (sign ambiguity from correlation)
        cos_sim = abs(np.dot(fwd, [1, 0, 0]))
        assert cos_sim > 0.9

    def test_forward_with_tilted_phone(self):
        # Phone Y axis is forward (e.g. portrait mount)
        accel, gyro, speed, ts = make_straight_line_data(
            n=2000, forward_phone=(0, 1, 0),
        )
        gravity = np.array([0, 0, -1.0])
        fwd, conf = estimate_forward_axis(accel, gravity, speed, ts)
        assert fwd is not None
        cos_sim = abs(np.dot(fwd, [0, 1, 0]))
        assert cos_sim > 0.9


# ── 3. Noisy IMU: stable output ────────────────────────────────


class TestNoisyIMU:
    def test_high_noise_stable_output(self):
        # 5x more noise than usual
        accel, gyro, speed, ts = make_straight_line_data(n=3000, noise=0.05)
        result = estimate_phone_mount(accel, gyro, speed, ts)
        # Should still produce a result, with reduced quality
        assert isinstance(result, PhoneMountEstimate)
        assert 0.0 <= result.orientation_quality <= 1.0
        # Gravity still recoverable
        assert abs(np.linalg.norm(result.gravity_vector) - 1.0) < 0.1


# ── 4. Low-speed: low confidence forward axis ───────────────────


class TestLowSpeedConfidence:
    def test_all_low_speed_marks_low_confidence(self):
        # All samples below min_speed
        accel, gyro, _, ts = make_static_data(n=1000)
        speed = np.full(1000, 1.0)  # below 5 m/s threshold
        result = estimate_phone_mount(accel, gyro, speed, ts)
        # Forward axis should fail; orientation quality should be low
        assert result.confidence_flags.get('forward_axis_known') is False
        assert result.orientation_quality < 0.3

    def test_no_acceleration_events_low_confidence(self):
        # Constant high speed, no accel events
        n = 1000
        ts = np.arange(n) * 0.04
        speed = np.full(n, 15.0)  # constant — no dv_dt
        accel = np.tile([0, 0, -1.0], (n, 1)) + np.random.normal(0, 0.005, (n, 3))
        gyro = np.zeros((n, 3))
        result = estimate_phone_mount(accel, gyro, speed, ts)
        # Should detect insufficient excitation
        assert (result.orientation_quality < 0.5
                or result.confidence_flags.get('forward_axis_known') is False)


# ── 5. Sudden rotation: instability flag ───────────────────────


class TestInstabilityDetection:
    def test_sudden_orientation_change_triggers_flag(self):
        accel, gyro, speed, ts = make_sudden_rotation_data(n=2000)
        instability = detect_mount_instability(accel, gyro, ts, window_s=2.0)
        assert instability['mount_unstable'] is True
        assert instability['max_gravity_drift_g'] > 0.15

    def test_stable_mount_no_flag(self):
        accel, gyro, speed, ts = make_static_data(n=1000)
        instability = detect_mount_instability(accel, gyro, ts, window_s=2.0)
        assert instability['mount_unstable'] is False
        assert instability['max_gravity_drift_g'] < 0.05

    def test_top_level_instability_propagates(self):
        accel, gyro, speed, ts = make_sudden_rotation_data(n=2000)
        result = estimate_phone_mount(accel, gyro, speed, ts)
        assert result.mount_unstable is True


# ── 6. Rotation matrix sanity ──────────────────────────────────


class TestRotationMatrix:
    def test_identity_when_phone_aligned_with_kart(self):
        # Forward = +X, gravity = -Z (phone Z-up)
        # In our convention, kart Z is up (-gravity), kart X is forward
        # So this should give identity
        gravity = np.array([0, 0, -1.0])
        forward = np.array([1, 0, 0])
        R = build_rotation_matrix(forward, gravity)
        # R should be identity (rows are kart axes in phone frame)
        assert np.allclose(R, np.eye(3), atol=1e-6)

    def test_rotation_orthonormal(self):
        gravity = np.array([0.1, 0.2, -0.97])
        forward = np.array([0.7, 0.7, 0.0])
        R = build_rotation_matrix(forward, gravity)
        # R must be orthonormal: R @ R.T = I
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-6)
        # det = +1 (proper rotation, not reflection)
        assert abs(np.linalg.det(R) - 1.0) < 1e-6

    def test_kart_z_axis_is_up(self):
        # Whatever the phone orientation, kart Z should point UP (opposite gravity)
        gravity = np.array([0.3, 0.4, -0.86])
        forward = np.array([1.0, 0.0, 0.0])
        R = build_rotation_matrix(forward, gravity)
        # R[2, :] is kart Z in phone frame; should be -gravity / |gravity|
        kart_z_in_phone = R[2, :]
        expected = -gravity / np.linalg.norm(gravity)
        assert np.allclose(kart_z_in_phone, expected, atol=1e-6)


# ── 7. End-to-end ──────────────────────────────────────────────


class TestEndToEnd:
    def test_full_pipeline_returns_estimate(self):
        accel, gyro, speed, ts = make_straight_line_data(n=2000)
        result = estimate_phone_mount(accel, gyro, speed, ts)
        assert isinstance(result, PhoneMountEstimate)
        assert result.R_phone_to_kart.shape == (3, 3)
        assert result.gravity_vector.shape == (3,)
        assert 0.0 <= result.orientation_quality <= 1.0
        assert isinstance(result.mount_unstable, bool)
        assert isinstance(result.confidence_flags, dict)


# ── 8. Kart-vibration robustness (the regression that prompted v2) ───
#
# These cover the failure mode that motivated the detector redesign:
# normal kart sessions have continuous high-frequency vibration AND
# sustained-centripetal cornering that the previous adjacent-window
# accel-median comparison misclassified as mount slip.


def make_karty_data(
    n: int = 6000,
    *,
    g_phone=(0.05, 0.0, -0.998),     # phone tilted ~3° — typical mounting
    vibration_g: float = 0.08,        # high-frequency vibration amplitude
    lap_period_s: float = 30.0,       # one lap cadence
    corner_amp_g: float = 0.9,        # peak lateral G during corners
    corner_long_amp_g: float = 0.45,  # peak longitudinal G during braking
    n_corners_per_lap: int = 4,
    corner_duration_s: float = 3.0,
    seed: int = 11,
):
    """Synthetic 'normal kart session' data: vibration + corners with straights.

    Realistic profile: straights at near-zero lateral/longitudinal accel,
    punctuated by short corner events (~3 s each, a few per lap). Vibration
    is continuous. No mount slip.
    """
    rng = np.random.default_rng(seed)
    dt = 0.04
    timestamps = np.arange(n) * dt

    g_vec = np.array(g_phone, dtype=float)

    # Build per-lap corner events: brief Gaussian bumps in lateral accel,
    # alternating sign (left/right turns), each preceded by a small braking
    # bump on longitudinal.
    accel = np.tile(g_vec, (n, 1))
    corner_centers_per_lap = np.linspace(
        0.15, 0.85, n_corners_per_lap,
    ) * lap_period_s
    for lap_start_s in np.arange(0, timestamps[-1] + lap_period_s, lap_period_s):
        for i, c_offset in enumerate(corner_centers_per_lap):
            c_t = lap_start_s + c_offset
            if c_t > timestamps[-1]:
                break
            sign = 1.0 if i % 2 == 0 else -1.0
            # Gaussian envelope, ~corner_duration_s wide
            envelope = np.exp(-((timestamps - c_t) ** 2) / (2 * (corner_duration_s / 2.4) ** 2))
            accel[:, 1] += sign * corner_amp_g * envelope                 # lateral
            # Braking just before the corner, throttle just after
            brake_env = np.exp(-((timestamps - (c_t - corner_duration_s * 0.6)) ** 2)
                               / (2 * (corner_duration_s / 3.0) ** 2))
            accel[:, 0] -= corner_long_amp_g * brake_env                  # braking (-x)
            accel[:, 0] += 0.3 * corner_long_amp_g * envelope             # mid-corner throttle

    # High-frequency vibration on all axes (Gaussian, ~25 Hz character).
    accel += rng.normal(0, vibration_g, (n, 3))

    # Gyro: yaw rate spikes during corners only.
    gyro = rng.normal(0, 2.0, (n, 3))
    yaw = np.zeros(n)
    for lap_start_s in np.arange(0, timestamps[-1] + lap_period_s, lap_period_s):
        for i, c_offset in enumerate(corner_centers_per_lap):
            c_t = lap_start_s + c_offset
            if c_t > timestamps[-1]:
                break
            sign = 1.0 if i % 2 == 0 else -1.0
            envelope = np.exp(-((timestamps - c_t) ** 2) / (2 * (corner_duration_s / 2.4) ** 2))
            yaw += sign * 80.0 * envelope
    gyro[:, 2] += yaw

    # Speed: drops during braking, recovers on straights.
    speed = np.full(n, 18.0)
    for lap_start_s in np.arange(0, timestamps[-1] + lap_period_s, lap_period_s):
        for i, c_offset in enumerate(corner_centers_per_lap):
            c_t = lap_start_s + c_offset
            if c_t > timestamps[-1]:
                break
            envelope = np.exp(-((timestamps - c_t) ** 2) / (2 * (corner_duration_s / 2.0) ** 2))
            speed -= 6.0 * envelope
    speed = np.clip(speed, 5.0, 30.0)
    return accel, gyro, speed, timestamps


class TestKartVibrationRobustness:
    def test_vibration_alone_does_not_trigger_unstable(self):
        # Pure vibration on a stationary phone should not be flagged as slip.
        rng = np.random.default_rng(99)
        n = 3000
        ts = np.arange(n) * 0.04
        accel = np.tile([0, 0, -1.0], (n, 1)) + rng.normal(0, 0.10, (n, 3))
        gyro = rng.normal(0, 5.0, (n, 3))
        report = detect_mount_instability(accel, gyro, ts)
        assert report['mount_unstable'] is False, (
            f"vibration alone marked mount_unstable; "
            f"max_slip_drift_g={report['max_gravity_drift_g']:.4f}"
        )
        # Vibration metric should reflect the noise level we put in.
        assert report['vibration_metric_g'] > 0.05

    def test_kart_session_not_globally_unstable(self):
        accel, gyro, speed, ts = make_karty_data(n=6000)
        report = detect_mount_instability(accel, gyro, ts)
        assert report['mount_unstable'] is False, (
            "normal kart session (vibration + corners, no slip) must not "
            "trigger global mount_unstable; "
            f"max_slip_drift_g={report['max_gravity_drift_g']:.4f}"
        )

    def test_kart_session_top_level_estimate_not_unstable(self):
        # End-to-end: estimate_phone_mount on kart-like data must not return
        # mount_unstable=True simply because of vibration + corners.
        accel, gyro, speed, ts = make_karty_data(n=6000)
        result = estimate_phone_mount(accel, gyro, speed, ts)
        assert result.mount_unstable is False, (
            "estimate_phone_mount marked normal kart-like session as unstable; "
            f"max_slip_drift_g={result.confidence_flags.get('max_slip_drift_g')}, "
            f"vibration_metric_g={result.confidence_flags.get('vibration_metric_g')}"
        )

    def test_real_slip_still_detected_inside_kart_noise(self):
        # Build a kart-noise session, then inject a real mount slip mid-way.
        accel, gyro, speed, ts = make_karty_data(n=6000)
        slip_idx = len(ts) // 2
        # Rotate the second half by ~25° about phone X axis (real reorientation).
        c, s_ = np.cos(np.deg2rad(25.0)), np.sin(np.deg2rad(25.0))
        R_slip = np.array([[1, 0, 0], [0, c, -s_], [0, s_, c]])
        accel[slip_idx:] = accel[slip_idx:] @ R_slip.T
        gyro[slip_idx:] = gyro[slip_idx:] @ R_slip.T
        report = detect_mount_instability(accel, gyro, ts)
        assert report['mount_unstable'] is True, (
            "real 25° slip inside kart noise was not detected; "
            f"max_slip_drift_g={report['max_gravity_drift_g']:.4f}"
        )

    def test_diagnostic_fields_populated(self):
        accel, gyro, speed, ts = make_karty_data(n=4000)
        report = detect_mount_instability(accel, gyro, ts)
        # Legacy fields preserved for backward compat.
        for k in ('mount_unstable', 'low_confidence', 'max_gravity_drift_g'):
            assert k in report, f"legacy key {k} missing"
        # New diagnostic fields present.
        for k in (
            'max_slip_drift_g', 'total_drift_g', 'vibration_metric_g',
            'low_dynamic_frac', 'n_windows_total', 'n_windows_assessed',
            'mean_low_dynamic_samples_per_window', 'instability_mask',
            'reason', 'thresholds',
        ):
            assert k in report, f"new diagnostic key {k} missing"
        # instability_mask should match window count.
        assert len(report['instability_mask']) == report['n_windows_total']
        # Threshold dict should expose the values that were used.
        assert 'slip_threshold_g' in report['thresholds']
        assert 'window_s' in report['thresholds']

    def test_per_window_mask_propagates_to_confidence_flags(self):
        # End-to-end: PhoneMountEstimate.confidence_flags should carry the
        # per-window instability mask for downstream gating.
        accel, gyro, speed, ts = make_karty_data(n=4000)
        result = estimate_phone_mount(accel, gyro, speed, ts)
        assert 'instability_mask' in result.confidence_flags
        assert 'vibration_metric_g' in result.confidence_flags
        assert isinstance(result.confidence_flags['instability_mask'], list)


class TestSlowDriftCase:
    def test_slow_drift_triggers_low_confidence(self):
        # Phone gradually drifts ~10° over the session — soft drift, not a step.
        rng = np.random.default_rng(33)
        n = 6000
        ts = np.arange(n) * 0.04
        # Linearly interpolate gravity from (0,0,-1) to (sin10°, 0, -cos10°).
        rad = np.deg2rad(10.0)
        g_start = np.array([0.0, 0.0, -1.0])
        g_end = np.array([np.sin(rad), 0.0, -np.cos(rad)])
        alpha = np.linspace(0, 1, n)[:, None]
        accel = (1 - alpha) * g_start + alpha * g_end + rng.normal(0, 0.005, (n, 3))
        gyro = rng.normal(0, 1.0, (n, 3))
        report = detect_mount_instability(accel, gyro, ts)
        # Drift is large enough to flag low_confidence even if it doesn't
        # cross the slip threshold (no abrupt step).
        assert report['low_confidence'] is True
        assert report['total_drift_g'] > 0.05
