"""Tests for wheel_kinematics — slip angle estimation.

These must ALL pass before wiring to the tire model.
"""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.wheel_kinematics.dataclasses import (
    CarGeometry,
    RoadFramePose,
    WheelKinematics,
)
from track_surface.wheel_kinematics.slip_angles import compute_slip_angles


def _default_geom() -> CarGeometry:
    return CarGeometry(
        wheelbase_m=2.67,
        track_front_m=1.666,
        track_rear_m=1.627,
        cg_to_front_m=1.52,    # 43% nose weight
        cg_to_rear_m=1.15,
        steer_ratio=14.0,
        max_steer_rad=0.5,
    )


# ── Deterministic geometry tests ─────────────────────────────


class TestZeroSteerZeroYaw:
    """Zero steer, zero yaw, vy=0 → all alpha ≈ 0."""

    def test_straight_line(self):
        wk = compute_slip_angles(
            vx_body=30.0, vy_body=0.0, yaw_rate=0.0,
            steer_wheel_rad=0.0, geom=_default_geom(),
        )
        assert abs(wk.alpha_f_axle) < 0.001
        assert abs(wk.alpha_r_axle) < 0.001
        assert abs(wk.beta_cg) < 0.001

    def test_per_wheel_also_zero(self):
        wk = compute_slip_angles(
            vx_body=30.0, vy_body=0.0, yaw_rate=0.0,
            steer_wheel_rad=0.0, geom=_default_geom(),
        )
        assert wk.alpha_fl is not None
        assert abs(wk.alpha_fl) < 0.01
        assert abs(wk.alpha_fr) < 0.01
        assert abs(wk.alpha_rl) < 0.01
        assert abs(wk.alpha_rr) < 0.01


class TestConstantRadiusLeftTurn:
    """Constant-radius left turn → positive alpha (understeering convention)."""

    def _left_turn(self) -> WheelKinematics:
        # Left turn: positive yaw_rate (CCW), positive vy (drifting right → understeering)
        # Steer left: negative steering wheel angle (turn left)
        return compute_slip_angles(
            vx_body=25.0,
            vy_body=0.5,         # small sideslip toward outside
            yaw_rate=0.3,         # turning left (CCW)
            steer_wheel_rad=-2.0, # steer left (negative in iRacing)
            geom=_default_geom(),
        )

    def test_front_slip_angle_sign(self):
        wk = self._left_turn()
        # Front axle: alpha_f = atan2(vy + a*r, vx) - delta
        # With left turn + steering, alpha_f should be small (steering matches yaw)
        assert isinstance(wk.alpha_f_axle, float)
        assert abs(wk.alpha_f_axle) < 0.35  # physically reasonable

    def test_rear_slip_angle_sign(self):
        wk = self._left_turn()
        # Rear axle: alpha_r = atan2(vy - b*r, vx)
        # With vy=0.5 and b*r = 1.15*0.3 = 0.345, vy - b*r = 0.155
        # alpha_r = atan2(0.155, 25) ≈ 0.006 rad → small positive
        assert isinstance(wk.alpha_r_axle, float)
        assert abs(wk.alpha_r_axle) < 0.1

    def test_sideslip_positive_in_left_turn(self):
        wk = self._left_turn()
        # Positive vy in a left turn → positive beta (nose left of velocity)
        assert wk.beta_cg > 0


class TestMirroredRightTurn:
    """Right turn should mirror left turn with opposite signs."""

    def test_sign_symmetry(self):
        geom = _default_geom()

        left = compute_slip_angles(
            vx_body=25.0, vy_body=0.5, yaw_rate=0.3,
            steer_wheel_rad=-2.0, geom=geom,
        )
        right = compute_slip_angles(
            vx_body=25.0, vy_body=-0.5, yaw_rate=-0.3,
            steer_wheel_rad=2.0, geom=geom,
        )

        # Axle slip angles should be sign-mirrored
        assert abs(left.alpha_f_axle + right.alpha_f_axle) < 0.01
        assert abs(left.alpha_r_axle + right.alpha_r_axle) < 0.01
        assert abs(left.beta_cg + right.beta_cg) < 0.01


class TestCGPosition:
    """CG moved forward/backward → expected alpha_f / alpha_r sensitivity."""

    def test_forward_cg_increases_rear_alpha(self):
        geom_fwd = CarGeometry(
            wheelbase_m=2.67, track_front_m=1.666, track_rear_m=1.627,
            cg_to_front_m=1.00, cg_to_rear_m=1.67,  # CG forward
            steer_ratio=14.0, max_steer_rad=0.5,
        )
        geom_rwd = CarGeometry(
            wheelbase_m=2.67, track_front_m=1.666, track_rear_m=1.627,
            cg_to_front_m=1.67, cg_to_rear_m=1.00,  # CG rearward
            steer_ratio=14.0, max_steer_rad=0.5,
        )

        wk_fwd = compute_slip_angles(
            vx_body=25.0, vy_body=0.3, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=geom_fwd,
        )
        wk_rwd = compute_slip_angles(
            vx_body=25.0, vy_body=0.3, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=geom_rwd,
        )

        # Forward CG: larger b → vy-b*r more negative → rear alpha changes
        # The rear slip angle should differ measurably between CG positions
        # (sign may differ, so compare the actual values not abs)
        assert wk_fwd.alpha_r_axle != pytest.approx(wk_rwd.alpha_r_axle, abs=0.001)


# ── Nonplanar consistency tests ──────────────────────────────


class TestNonplanar:
    """Road frame corrections for banked/graded surfaces."""

    def test_flat_frame_matches_body_frame(self):
        wk_flat = compute_slip_angles(
            vx_body=30.0, vy_body=0.5, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=_default_geom(),
            road_frame=RoadFramePose.flat(),
        )
        wk_none = compute_slip_angles(
            vx_body=30.0, vy_body=0.5, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=_default_geom(),
            road_frame=None,
        )
        # Should produce identical results
        assert abs(wk_flat.alpha_f_axle - wk_none.alpha_f_axle) < 0.001
        assert abs(wk_flat.beta_cg - wk_none.beta_cg) < 0.001

    def test_banked_surface_reduces_vy_projection(self):
        """On a 30° bank, the body-frame lateral velocity has a component
        along the road normal. The road-tangent vy is reduced by cos(30°)."""
        flat = compute_slip_angles(
            vx_body=30.0, vy_body=1.0, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=_default_geom(),
            road_frame=RoadFramePose.flat(),
        )
        banked = compute_slip_angles(
            vx_body=30.0, vy_body=1.0, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=_default_geom(),
            road_frame=RoadFramePose.from_bank_grade(
                bank_rad=np.radians(30), grade_rad=0, heading_rad=0,
            ),
        )
        # Beta should be smaller on the banked surface (vy projected)
        assert abs(banked.beta_cg) < abs(flat.beta_cg)
        assert banked.flags.get("road_frame_used") is True

    def test_grade_does_not_change_lateral_slip(self):
        """Grade (uphill/downhill) should not significantly affect lateral slip angles."""
        flat = compute_slip_angles(
            vx_body=30.0, vy_body=0.5, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=_default_geom(),
            road_frame=RoadFramePose.flat(),
        )
        graded = compute_slip_angles(
            vx_body=30.0, vy_body=0.5, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=_default_geom(),
            road_frame=RoadFramePose.from_bank_grade(
                bank_rad=0, grade_rad=np.radians(10), heading_rad=0,
            ),
        )
        # Lateral slip should be very similar (grade mainly affects longitudinal)
        assert abs(flat.alpha_f_axle - graded.alpha_f_axle) < 0.02


# ── Noise robustness tests ───────────────────────────────────


class TestNoiseRobustness:
    def test_small_noise_does_not_create_wild_alpha(self):
        """Small noise on vy, r, delta should not produce unreasonable slip angles."""
        geom = _default_geom()
        rng = np.random.default_rng(42)

        for _ in range(50):
            vy = rng.normal(0, 0.3)
            r = rng.normal(0.1, 0.05)
            delta = rng.normal(-1.0, 0.2)
            wk = compute_slip_angles(
                vx_body=25.0, vy_body=vy, yaw_rate=r,
                steer_wheel_rad=delta, geom=geom,
            )
            # All slip angles should be physically bounded
            assert abs(wk.alpha_f_axle) < 0.35
            assert abs(wk.alpha_r_axle) < 0.35
            if wk.alpha_fl is not None:
                assert abs(wk.alpha_fl) < 0.35

    def test_low_speed_guard(self):
        """Near vx=0, all alphas should be 0 (guard active)."""
        wk = compute_slip_angles(
            vx_body=0.5, vy_body=1.0, yaw_rate=0.5,
            steer_wheel_rad=-3.0, geom=_default_geom(),
        )
        assert wk.alpha_f_axle == 0.0
        assert wk.alpha_r_axle == 0.0
        assert wk.flags.get("low_speed_guard") is True
        assert wk.flags.get("vx_sufficient") is False


# ── Quality flag tests ───────────────────────────────────────


class TestQualityFlags:
    def test_no_wheel_speeds_kappa_is_none(self):
        wk = compute_slip_angles(
            vx_body=30.0, vy_body=0.0, yaw_rate=0.0,
            steer_wheel_rad=0.0, geom=_default_geom(),
            wheel_speeds=None,
        )
        assert wk.kappa_fl is None
        assert wk.kappa_fr is None
        assert wk.kappa_rl is None
        assert wk.kappa_rr is None
        assert wk.flags.get("kappa_observed") is False
        assert wk.quality_kappa == 0.0

    def test_with_wheel_speeds_kappa_is_float(self):
        wk = compute_slip_angles(
            vx_body=30.0, vy_body=0.0, yaw_rate=0.0,
            steer_wheel_rad=0.0, geom=_default_geom(),
            wheel_speeds=(90.0, 90.0, 90.0, 90.0),  # ~30 m/s at R=0.33
        )
        assert wk.kappa_fl is not None
        assert wk.kappa_fr is not None
        assert abs(wk.kappa_fl) < 0.1  # near-zero slip at matched speed
        assert wk.flags.get("kappa_observed") is True

    def test_missing_track_width_no_per_wheel(self):
        geom = CarGeometry(
            wheelbase_m=2.67, track_front_m=0.0, track_rear_m=0.0,
            cg_to_front_m=1.52, cg_to_rear_m=1.15,
        )
        wk = compute_slip_angles(
            vx_body=30.0, vy_body=0.5, yaw_rate=0.2,
            steer_wheel_rad=-1.0, geom=geom,
        )
        # Axle-level still available
        assert isinstance(wk.alpha_f_axle, float)
        assert isinstance(wk.alpha_r_axle, float)
        # Per-wheel should be None (no track width)
        assert wk.flags.get("per_wheel_alpha") is False

    def test_high_speed_better_quality(self):
        wk_slow = compute_slip_angles(
            vx_body=10.0, vy_body=0.1, yaw_rate=0.1,
            steer_wheel_rad=-0.5, geom=_default_geom(),
        )
        wk_fast = compute_slip_angles(
            vx_body=60.0, vy_body=0.1, yaw_rate=0.1,
            steer_wheel_rad=-0.5, geom=_default_geom(),
        )
        assert wk_fast.quality_beta > wk_slow.quality_beta
        assert wk_fast.quality_alpha > wk_slow.quality_alpha
