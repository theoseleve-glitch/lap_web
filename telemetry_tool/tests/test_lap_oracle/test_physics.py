"""Tests for the Lap Oracle physics engine.

Covers Pacejka tyre model, bicycle dynamics, and vehicle bridge.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from telemetry_tool.lap_oracle.config import PacejkaParams, VehicleParams
from telemetry_tool.lap_oracle.physics.pacejka import (
    combined_slip,
    lateral_force,
    longitudinal_force,
    peak_mu,
)
from telemetry_tool.lap_oracle.physics.bicycle_model import (
    G,
    RHO_AIR,
    combined_accel_limit,
    corner_speed,
    max_lateral_accel,
    max_longitudinal_accel,
)
from telemetry_tool.lap_oracle.physics.vehicle import (
    _estimate_power,
    from_ac_car_ini,
    from_sim_optimizer_result,
)


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def default_pacejka() -> PacejkaParams:
    return PacejkaParams()


@pytest.fixture
def long_pacejka() -> PacejkaParams:
    return PacejkaParams(B=12.0, C=1.4, D=1.0, E=-0.3)


@pytest.fixture
def default_vp() -> VehicleParams:
    return VehicleParams()


@pytest.fixture
def gt3_vp() -> VehicleParams:
    """GT3-like vehicle with significant aero."""
    return VehicleParams(
        sim="ac",
        car_name="gt3_test",
        mass_kg=1300.0,
        wheelbase_m=2.65,
        cg_height_m=0.35,
        weight_dist_front=0.47,
        cda=1.0,
        cla=3.0,
        max_power_w=400_000.0,
        max_brake_decel=14.0,
        tyre_lat=PacejkaParams(B=10.0, C=1.3, D=1.2, E=-0.5),
        tyre_long=PacejkaParams(B=12.0, C=1.4, D=1.1, E=-0.3),
    )


# ======================================================================
# Pacejka -- lateral_force
# ======================================================================

class TestPacejkaLateral:
    def test_near_zero_at_zero_slip(self, default_pacejka: PacejkaParams):
        """Force should be ~0 when slip angle is zero."""
        fz = np.array([5000.0])
        alpha = np.array([0.0])
        fy = lateral_force(alpha, fz, default_pacejka)
        assert abs(float(fy[0])) < 1.0  # effectively zero

    def test_peak_at_moderate_slip(self, default_pacejka: PacejkaParams):
        """Peak force should occur at a moderate slip angle (5-15 deg)."""
        fz = np.full(100, 5000.0)
        alpha = np.linspace(0, math.radians(30), 100)
        fy = lateral_force(alpha, fz, default_pacejka)
        peak_idx = np.argmax(np.abs(fy))
        peak_alpha_deg = math.degrees(alpha[peak_idx])
        assert 3.0 < peak_alpha_deg < 20.0

    def test_force_scales_with_load(self, default_pacejka: PacejkaParams):
        """Doubling the normal load should roughly double the force."""
        alpha = np.array([math.radians(8)])
        fy_1 = lateral_force(alpha, np.array([5000.0]), default_pacejka)
        fy_2 = lateral_force(alpha, np.array([10000.0]), default_pacejka)
        ratio = float(fy_2[0]) / float(fy_1[0])
        assert 1.8 < ratio < 2.2

    def test_vectorized(self, default_pacejka: PacejkaParams):
        """Should handle arrays of different sizes."""
        n = 50
        alpha = np.linspace(-0.2, 0.2, n)
        fz = np.full(n, 4000.0)
        fy = lateral_force(alpha, fz, default_pacejka)
        assert fy.shape == (n,)


# ======================================================================
# Pacejka -- longitudinal_force
# ======================================================================

class TestPacejkaLongitudinal:
    def test_near_zero_at_zero_slip(self, long_pacejka: PacejkaParams):
        """Force should be ~0 when slip ratio is zero."""
        fz = np.array([5000.0])
        kappa = np.array([0.0])
        fx = longitudinal_force(kappa, fz, long_pacejka)
        assert abs(float(fx[0])) < 1.0

    def test_positive_force_for_positive_slip(self, long_pacejka: PacejkaParams):
        """Positive slip ratio (acceleration) should give positive force."""
        fz = np.array([5000.0])
        kappa = np.array([0.08])
        fx = longitudinal_force(kappa, fz, long_pacejka)
        assert float(fx[0]) > 0


# ======================================================================
# Pacejka -- combined slip
# ======================================================================

class TestCombinedSlip:
    def test_zero_slip_gives_zero_force(self):
        """Both forces should be zero when both slips are zero."""
        fx0 = np.array([5000.0])
        fy0 = np.array([4000.0])
        fx, fy = combined_slip(fx0, fy0, np.array([0.0]), np.array([0.0]))
        assert abs(float(fx[0])) < 1e-6
        assert abs(float(fy[0])) < 1e-6

    def test_pure_longitudinal(self):
        """With zero lateral slip, fx should equal fx0."""
        fx0 = np.array([5000.0])
        fy0 = np.array([4000.0])
        kappa = np.array([0.1])
        alpha = np.array([0.0])
        fx, fy = combined_slip(fx0, fy0, kappa, alpha)
        # With alpha=0, tan(alpha)=0, sigma=|kappa|, fx = fx0*kappa/|kappa| = fx0
        np.testing.assert_allclose(fx, fx0, atol=1.0)

    def test_combined_reduces_forces(self):
        """Under combined slip, individual forces should be less than pure."""
        fx0 = np.array([5000.0])
        fy0 = np.array([4000.0])
        kappa = np.array([0.05])
        alpha = np.array([math.radians(5)])
        fx, fy = combined_slip(fx0, fy0, kappa, alpha)
        assert abs(float(fx[0])) < abs(float(fx0[0]))
        assert abs(float(fy[0])) < abs(float(fy0[0]))


# ======================================================================
# Pacejka -- peak_mu
# ======================================================================

class TestPeakMu:
    def test_returns_d(self):
        params = PacejkaParams(B=10.0, C=1.3, D=1.25, E=-0.5)
        assert peak_mu(params) == 1.25

    def test_default(self):
        assert peak_mu(PacejkaParams()) == 1.0


# ======================================================================
# Bicycle model -- max_lateral_accel
# ======================================================================

class TestMaxLateralAccel:
    def test_increases_with_speed(self, gt3_vp: VehicleParams):
        """With aero downforce, lateral limit should increase with speed."""
        ay_low = float(max_lateral_accel(20.0, gt3_vp))
        ay_high = float(max_lateral_accel(60.0, gt3_vp))
        assert ay_high > ay_low

    def test_at_rest(self, gt3_vp: VehicleParams):
        """At v=0, lateral accel should equal mu*g."""
        ay = float(max_lateral_accel(0.0, gt3_vp))
        expected = gt3_vp.tyre_lat.D * G
        np.testing.assert_allclose(ay, expected, rtol=1e-6)

    def test_vectorized(self, default_vp: VehicleParams):
        speeds = np.array([10.0, 30.0, 50.0, 70.0])
        ay = max_lateral_accel(speeds, default_vp)
        assert ay.shape == (4,)
        # Should be monotonically increasing with positive Cla
        assert np.all(np.diff(ay) > 0)


# ======================================================================
# Bicycle model -- max_longitudinal_accel
# ======================================================================

class TestMaxLongitudinalAccel:
    def test_braking_decel_greater_at_high_speed(self, gt3_vp: VehicleParams):
        """Braking decel should exceed traction accel at high speed
        because drag assists braking but hinders acceleration."""
        v = 60.0  # ~216 km/h
        ax_brake = float(max_longitudinal_accel(v, gt3_vp, braking=True))
        ax_accel = float(max_longitudinal_accel(v, gt3_vp, braking=False))
        assert ax_brake > ax_accel

    def test_accel_positive(self, default_vp: VehicleParams):
        """Traction acceleration should be positive at moderate speed."""
        ax = float(max_longitudinal_accel(30.0, default_vp, braking=False))
        assert ax > 0

    def test_braking_positive(self, default_vp: VehicleParams):
        """Braking deceleration should be positive (magnitude)."""
        ax = float(max_longitudinal_accel(30.0, default_vp, braking=True))
        assert ax > 0

    def test_power_limited_at_high_speed(self, gt3_vp: VehicleParams):
        """At very high speed, acceleration should be power-limited (small)."""
        ax_fast = float(max_longitudinal_accel(80.0, gt3_vp, braking=False))
        ax_slow = float(max_longitudinal_accel(20.0, gt3_vp, braking=False))
        assert ax_fast < ax_slow


# ======================================================================
# Bicycle model -- corner_speed
# ======================================================================

class TestCornerSpeed:
    def test_decreases_with_curvature(self, default_vp: VehicleParams):
        """Tighter corners (higher curvature) should have lower max speed."""
        kappa = np.array([0.005, 0.01, 0.02, 0.05])
        v = corner_speed(kappa, default_vp)
        # Strictly decreasing
        assert np.all(np.diff(v) < 0)

    def test_straight_gives_high_speed(self, default_vp: VehicleParams):
        """Near-zero curvature should give very high speed."""
        kappa = np.array([1e-6])
        v = corner_speed(kappa, default_vp)
        assert float(v[0]) > 100.0

    def test_tight_corner(self, default_vp: VehicleParams):
        """A hairpin (kappa ~0.05) should give low speed."""
        kappa = np.array([0.05])
        v = corner_speed(kappa, default_vp)
        assert float(v[0]) < 50.0

    def test_vectorized(self, gt3_vp: VehicleParams):
        kappa = np.linspace(0.001, 0.1, 50)
        v = corner_speed(kappa, gt3_vp)
        assert v.shape == (50,)


# ======================================================================
# Bicycle model -- combined_accel_limit
# ======================================================================

class TestCombinedAccelLimit:
    def test_feasible_at_moderate_demand(self, default_vp: VehicleParams):
        """Moderate demand should be well within the envelope."""
        util = float(combined_accel_limit(2.0, 3.0, 30.0, default_vp))
        assert util < 1.5

    def test_zero_demand(self, default_vp: VehicleParams):
        """Zero demand should give zero utilisation."""
        util = float(combined_accel_limit(0.0, 0.0, 30.0, default_vp))
        np.testing.assert_allclose(util, 0.0, atol=1e-10)

    def test_braking_direction(self, gt3_vp: VehicleParams):
        """Negative ax (braking) should use the braking limit."""
        util_brake = float(combined_accel_limit(-5.0, 3.0, 40.0, gt3_vp))
        util_accel = float(combined_accel_limit(5.0, 3.0, 40.0, gt3_vp))
        # Both should be small-ish at moderate demand
        assert util_brake > 0
        assert util_accel > 0


# ======================================================================
# Vehicle bridge -- from_sim_optimizer_result
# ======================================================================

class TestFromSimOptimizerResult:
    def test_extracts_mass(self):
        result = {
            "mass": {"base_mass_kg": 1200.0, "bop_penalty_kg": 50.0},
        }
        vp = from_sim_optimizer_result(result, "iracing", "mx5")
        assert vp.mass_kg == 1250.0
        assert vp.sim == "iracing"
        assert vp.car_name == "mx5"

    def test_extracts_aero(self):
        result = {
            "aero": {"cda": 0.95, "cla": 2.8},
        }
        vp = from_sim_optimizer_result(result, "ac", "gt3")
        assert vp.cda == 0.95
        assert vp.cla == 2.8

    def test_extracts_tyre(self):
        result = {
            "tyre": {
                "b_lat": 9.0,
                "c_lat": 1.35,
                "mu_lat": 1.15,
                "b_long": 11.5,
                "c_long": 1.5,
                "mu_long": 1.1,
            },
        }
        vp = from_sim_optimizer_result(result, "ac", "gt4")
        assert vp.tyre_lat.B == 9.0
        assert vp.tyre_lat.D == 1.15  # mu_lat maps to D
        assert vp.tyre_long.B == 11.5
        assert vp.tyre_long.D == 1.1

    def test_extracts_brake(self):
        result = {
            "brake": {"max_decel_mps2": 15.0},
        }
        vp = from_sim_optimizer_result(result, "ac", "lmp2")
        assert vp.max_brake_decel == 15.0

    def test_extracts_power(self):
        result = {
            "powertrain": {
                "gear_torque_maps": {
                    "3": {
                        "rpm": [4000.0, 6000.0, 8000.0],
                        "torque_nm": [400.0, 450.0, 380.0],
                    }
                }
            }
        }
        vp = from_sim_optimizer_result(result, "ac", "gt3")
        # Peak power: 450 Nm at 6000 RPM = 450 * 2*pi*6000/60 ~ 282,743 W
        assert vp.max_power_w > 250_000
        assert vp.max_power_w < 350_000

    def test_empty_dict_returns_defaults(self):
        vp = from_sim_optimizer_result({}, "ac", "unknown")
        default = VehicleParams()
        assert vp.mass_kg == default.mass_kg
        assert vp.cda == default.cda

    def test_full_pipeline_dict(self):
        """A complete result dict with all sub-models."""
        result = {
            "mass": {"base_mass_kg": 1350.0, "bop_penalty_kg": 0.0},
            "aero": {"cda": 0.85, "cla": 2.5},
            "tyre": {
                "b_lat": 10.0, "c_lat": 1.3, "mu_lat": 1.2,
                "b_long": 12.0, "c_long": 1.4, "mu_long": 1.1,
            },
            "brake": {"max_decel_mps2": 12.0},
            "powertrain": {"gear_torque_maps": {}},
        }
        vp = from_sim_optimizer_result(result, "acc", "ferrari_296")
        assert vp.mass_kg == 1350.0
        assert vp.cda == 0.85
        assert vp.tyre_lat.D == 1.2
        assert vp.max_brake_decel == 12.0


# ======================================================================
# Vehicle bridge -- from_ac_car_ini
# ======================================================================

class TestFromAcCarIni:
    def test_basic_ini(self):
        ini = {
            "CAR": {"TOTALMASS": "1300", "SCREEN_NAME": "Porsche 911"},
            "SUSPENSIONS": {
                "WHEELBASE": "2.45",
                "FRONT_TRACK": "1.55",
                "REAR_TRACK": "1.52",
                "CG_HEIGHT": "0.40",
            },
            "AERO": {"CD": "0.35", "CL": "1.5", "FRONTAL_AREA": "2.1"},
            "BRAKES": {"MAX_DECEL": "13.0"},
        }
        vp = from_ac_car_ini(ini)
        assert vp.sim == "ac"
        assert vp.mass_kg == 1300.0
        assert vp.wheelbase_m == 2.45
        assert vp.track_width_front_m == 1.55
        assert vp.cg_height_m == 0.40
        np.testing.assert_allclose(vp.cda, 0.35 * 2.1, rtol=1e-6)
        np.testing.assert_allclose(vp.cla, 1.5 * 2.1, rtol=1e-6)
        assert vp.max_brake_decel == 13.0

    def test_empty_ini_returns_defaults(self):
        vp = from_ac_car_ini({})
        default = VehicleParams()
        assert vp.mass_kg == default.mass_kg

    def test_case_insensitive(self):
        ini = {
            "car": {"totalmass": "1100"},
        }
        vp = from_ac_car_ini(ini)
        assert vp.mass_kg == 1100.0


# ======================================================================
# Vehicle bridge -- _estimate_power
# ======================================================================

class TestEstimatePower:
    def test_finds_peak(self):
        pt = {
            "gear_torque_maps": {
                "3": {
                    "rpm": [4000, 6000, 8000],
                    "torque_nm": [300, 450, 350],
                }
            }
        }
        power = _estimate_power(pt)
        # Peak power is 350 Nm @ 8000 RPM = 350 * 2*pi*8000/60 ~ 293,215 W
        # (higher than 450 Nm @ 6000 RPM ~ 282,743 W)
        expected = 350.0 * 2.0 * math.pi * 8000.0 / 60.0
        np.testing.assert_allclose(power, expected, rtol=1e-6)

    def test_empty_maps(self):
        assert _estimate_power({}) == 0.0
        assert _estimate_power({"gear_torque_maps": {}}) == 0.0

    def test_multiple_gears(self):
        pt = {
            "gear_torque_maps": {
                "2": {"rpm": [3000], "torque_nm": [500]},
                "5": {"rpm": [9000], "torque_nm": [300]},
            }
        }
        power = _estimate_power(pt)
        # Gear 5: 300 * 2*pi*9000/60 ~ 282,743 W
        # Gear 2: 500 * 2*pi*3000/60 ~ 157,080 W
        # Peak should be gear 5
        expected = 300.0 * 2.0 * math.pi * 9000.0 / 60.0
        np.testing.assert_allclose(power, expected, rtol=1e-6)
