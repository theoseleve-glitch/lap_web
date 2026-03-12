"""Tests for OCP vehicle parameters and load transfer."""
import math
import pytest

from solver.vehicle_params import OCPVehicleParams, params_for_class
from solver.load_transfer import compute_load_transfer, compute_lateral_load_transfer


class TestOCPVehicleParams:
    def test_kart_defaults(self):
        p = params_for_class("kart")
        assert p.mass == 160.0
        assert p.h_cg == 0.25
        assert p.wheelbase == 1.05
        assert p.track_width == 1.2
        assert p.Cd == 0.5
        assert p.Cl == 0.0
        assert p.rho == 1.225
        assert p.Cr == 0.015
        assert p.load_sensitivity == -0.08

    def test_car_defaults(self):
        p = params_for_class("car")
        assert p.mass == 1200.0
        assert p.h_cg == 0.45
        assert p.Cd == 0.35
        assert p.Cl == 0.1
        assert p.Cr == 0.012
        assert p.load_sensitivity == -0.15

    def test_from_vehicle_parameters(self):
        from vehicle_model import VehicleParameters, VehicleClass
        vp = VehicleParameters(
            vehicle_class=VehicleClass.KART,
            estimated_mass_kg=155.0,
            peak_lateral_g=1.3,
            peak_braking_g=1.1,
            peak_traction_g=0.8,
            has_downforce=False,
            has_abs=False,
            rolling_resistance_est=0.013,
            aero_drag_factor_est=0.0,
        )
        p = OCPVehicleParams.from_vehicle_params(vp)
        assert p.mass == 155.0
        assert p.Cr == 0.013
        assert p.mu_ref == pytest.approx(1.3, abs=0.01)

    def test_unknown_class_uses_car_defaults(self):
        p = params_for_class("unknown")
        assert p.mass == 1200.0


class TestLoadTransfer:
    def test_longitudinal_braking(self):
        p = params_for_class("car")
        dFz_front, dFz_rear = compute_load_transfer(p, a_long=-10.0, a_lat=0.0)
        expected = 1200 * 10 * 0.45 / 2.6
        assert dFz_front == pytest.approx(expected, rel=0.01)
        assert dFz_rear == pytest.approx(-expected, rel=0.01)

    def test_lateral_cornering(self):
        p = params_for_class("car")
        dFz_outer, dFz_inner = compute_lateral_load_transfer(p, a_lat=10.0)
        expected = 1200 * 10 * 0.45 / 1.55
        assert dFz_outer == pytest.approx(expected, rel=0.01)
        assert dFz_inner == pytest.approx(-expected, rel=0.01)

    def test_zero_accel_no_transfer(self):
        p = params_for_class("kart")
        dFz_front, dFz_rear = compute_load_transfer(p, a_long=0.0, a_lat=0.0)
        assert dFz_front == pytest.approx(0.0)
        assert dFz_rear == pytest.approx(0.0)
