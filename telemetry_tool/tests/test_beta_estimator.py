"""Tests for beta_estimator.py — complementary filter sideslip estimation."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.beta_estimator import (
    BetaEstimatorConfig,
    estimate_beta_batch,
    estimate_beta_offline_smooth,
)


def _constant(n: int, val: float) -> np.ndarray:
    return np.full(n, val)


# ── Deterministic geometry tests ─────────────────────────────


class TestStraightLine:
    """Straight line, no yaw, no lateral accel → beta ≈ 0."""

    def test_beta_zero_on_straight(self):
        N = 200
        vy, beta, std, q = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.0),
            a_lat_tire=_constant(N, 0.0),
            cg_to_rear_m=1.15,
        )
        # After convergence, beta should be near zero
        assert np.abs(beta[-50:]).mean() < 0.005
        assert np.abs(vy[-50:]).mean() < 0.1

    def test_quality_high_on_fast_straight(self):
        N = 200
        _, _, _, q = estimate_beta_batch(
            speed=_constant(N, 50.0),
            yaw_rate=_constant(N, 0.0),
            a_lat_tire=_constant(N, 0.0),
            cg_to_rear_m=1.15,
        )
        assert q[-1] > 0.5


class TestLeftRightSymmetry:
    """Left and right turns should produce sign-mirrored beta."""

    def test_mirrored_turns(self):
        N = 300
        b = 1.15
        # Left turn: positive yaw rate
        vy_l, beta_l, _, _ = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.3),
            a_lat_tire=_constant(N, -2.0),  # tire pushes left (negative in body)
            cg_to_rear_m=b,
        )
        # Right turn: negative yaw rate
        vy_r, beta_r, _, _ = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, -0.3),
            a_lat_tire=_constant(N, 2.0),
            cg_to_rear_m=b,
        )
        # Should be sign-mirrored after convergence
        assert abs(beta_l[-50:].mean() + beta_r[-50:].mean()) < 0.01
        assert abs(vy_l[-50:].mean() + vy_r[-50:].mean()) < 0.2


class TestConstantRadiusTurn:
    """At steady cornering, beta should converge to a stable value."""

    def test_converges_to_steady_state(self):
        N = 500
        b = 1.15
        vx = 25.0
        r = 0.2  # yaw rate for a moderate left turn

        # At steady state: vy_kin = -b × r = -0.23 m/s
        # a_lat_tire = vx × r = 5.0 m/s² (centripetal demand from tires)
        a_lat = vx * r  # steady-state centripetal

        vy, beta, std, q = estimate_beta_batch(
            speed=_constant(N, vx),
            yaw_rate=_constant(N, r),
            a_lat_tire=_constant(N, a_lat),
            cg_to_rear_m=b,
        )
        # After convergence:
        # kinematic: vy = -b × r = -0.23
        # integrated: vy_dot = a_lat - vx*r = 0 → vy_int stays near initial
        #   + drift correction pulls toward kinematic
        # So vy should converge to ~-0.23
        vy_steady = vy[-100:].mean()
        assert abs(vy_steady - (-b * r)) < 0.3  # within 0.3 m/s of kinematic

        # Beta should be negative (nose points left of velocity in a left turn)
        beta_steady = beta[-100:].mean()
        expected_beta = np.arctan2(-b * r, vx)
        assert abs(beta_steady - expected_beta) < 0.02

    def test_std_decreases_over_time(self):
        """Uncertainty should decrease as the filter converges."""
        N = 500
        _, _, std, _ = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.15),
            a_lat_tire=_constant(N, 4.5),
            cg_to_rear_m=1.15,
        )
        # Early std should be higher than late std
        assert std[:50].mean() > std[-50:].mean()


# ── Low-speed guard ──────────────────────────────────────────


class TestLowSpeedGuard:
    def test_beta_zero_at_low_speed(self):
        N = 100
        vy, beta, _, q = estimate_beta_batch(
            speed=_constant(N, 2.0),  # below 5 m/s guard
            yaw_rate=_constant(N, 0.5),  # high yaw (pit maneuver)
            a_lat_tire=_constant(N, 3.0),
            cg_to_rear_m=1.15,
        )
        # All should be zero / low quality
        assert np.all(beta == 0.0)
        assert np.all(vy == 0.0)
        assert np.all(q == 0.0)

    def test_integral_resets_at_low_speed(self):
        """After a low-speed period, the integral should not carry stale state."""
        N = 300
        speed = np.concatenate([
            _constant(100, 30.0),  # cruising
            _constant(50, 2.0),    # pit / slow
            _constant(150, 30.0),  # back to cruising
        ])
        vy, beta, _, q = estimate_beta_batch(
            speed=speed,
            yaw_rate=_constant(N, 0.0),
            a_lat_tire=_constant(N, 0.0),
            cg_to_rear_m=1.15,
        )
        # After the slow period, beta should recover to ~0 quickly
        assert np.abs(beta[-50:]).mean() < 0.01


# ── Noise robustness ─────────────────────────────────────────


class TestNoiseRobustness:
    def test_moderate_noise_bounded_output(self):
        """Noisy inputs should not produce wild beta."""
        N = 500
        rng = np.random.default_rng(42)
        vy, beta, _, _ = estimate_beta_batch(
            speed=30.0 + rng.normal(0, 1.0, N),
            yaw_rate=0.1 + rng.normal(0, 0.05, N),
            a_lat_tire=3.0 + rng.normal(0, 0.5, N),
            cg_to_rear_m=1.15,
        )
        # All beta should stay within clamp bounds
        assert np.all(np.abs(beta) <= 0.26)
        assert np.all(np.abs(vy) <= 5.1)

    def test_noise_does_not_inflate_quality(self):
        """Noisy conditions should reduce quality, not inflate it."""
        N = 500
        rng = np.random.default_rng(42)
        _, _, _, q_noisy = estimate_beta_batch(
            speed=30.0 + rng.normal(0, 2.0, N),
            yaw_rate=0.1 + rng.normal(0, 0.2, N),  # high noise
            a_lat_tire=3.0 + rng.normal(0, 2.0, N),
            cg_to_rear_m=1.15,
        )
        _, _, _, q_clean = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.1),
            a_lat_tire=_constant(N, 3.0),
            cg_to_rear_m=1.15,
        )
        # Noisy should have lower average quality
        assert q_noisy.mean() <= q_clean.mean()


# ── Banking / road frame ─────────────────────────────────────


class TestBankingConsistency:
    def test_road_quality_propagates(self):
        """Low road quality should reduce beta quality."""
        N = 200
        _, _, _, q_good = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.1),
            a_lat_tire=_constant(N, 3.0),
            cg_to_rear_m=1.15,
            road_quality=_constant(N, 1.0),
        )
        _, _, _, q_bad = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.1),
            a_lat_tire=_constant(N, 3.0),
            cg_to_rear_m=1.15,
            road_quality=_constant(N, 0.3),
        )
        assert q_bad.mean() < q_good.mean()


# ── Uncertainty monotonicity ─────────────────────────────────


class TestUncertainty:
    def test_higher_speed_lower_uncertainty(self):
        N = 200
        _, _, std_slow, _ = estimate_beta_batch(
            speed=_constant(N, 15.0),
            yaw_rate=_constant(N, 0.1),
            a_lat_tire=_constant(N, 1.5),
            cg_to_rear_m=1.15,
        )
        _, _, std_fast, _ = estimate_beta_batch(
            speed=_constant(N, 50.0),
            yaw_rate=_constant(N, 0.1),
            a_lat_tire=_constant(N, 5.0),
            cg_to_rear_m=1.15,
        )
        assert std_fast[-50:].mean() < std_slow[-50:].mean()

    def test_no_fabricated_confidence(self):
        """At minimum speed, quality must be zero — no fabrication."""
        N = 100
        _, _, _, q = estimate_beta_batch(
            speed=_constant(N, 4.0),
            yaw_rate=_constant(N, 0.5),
            a_lat_tire=_constant(N, 5.0),
            cg_to_rear_m=1.15,
        )
        assert np.all(q == 0.0)


# ── Offline smoother ─────────────────────────────────────────


class TestOfflineSmoother:
    def test_smoother_at_least_as_good_as_forward(self):
        """Offline smoother should have equal or better quality."""
        N = 500
        rng = np.random.default_rng(42)
        speed = 30.0 + rng.normal(0, 0.5, N)
        yr = 0.15 + rng.normal(0, 0.02, N)
        alat = 4.5 + rng.normal(0, 0.3, N)
        b = 1.15

        _, _, std_fwd, q_fwd = estimate_beta_batch(
            speed=speed, yaw_rate=yr, a_lat_tire=alat, cg_to_rear_m=b,
        )
        _, _, std_sm, q_sm = estimate_beta_offline_smooth(
            speed=speed, yaw_rate=yr, a_lat_tire=alat, cg_to_rear_m=b,
        )
        # Smoother std should be ≤ forward std on average
        assert std_sm[-100:].mean() <= std_fwd[-100:].mean() + 0.01

    def test_smoother_straight_line_stays_zero(self):
        N = 300
        vy, beta, _, _ = estimate_beta_offline_smooth(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.0),
            a_lat_tire=_constant(N, 0.0),
            cg_to_rear_m=1.15,
        )
        assert np.abs(beta).mean() < 0.005


# ── Fallback behavior ────────────────────────────────────────


class TestFallback:
    def test_missing_road_quality_still_works(self):
        """If road_quality is None, estimator should still run."""
        N = 200
        vy, beta, std, q = estimate_beta_batch(
            speed=_constant(N, 30.0),
            yaw_rate=_constant(N, 0.1),
            a_lat_tire=_constant(N, 3.0),
            cg_to_rear_m=1.15,
            road_quality=None,
        )
        assert len(beta) == N
        assert np.all(np.isfinite(beta))
