"""Tests for the load-sensitive tire model."""
import math
import pytest
import numpy as np

from solver.tire_model import LoadSensitiveTire

_G = 9.80665


class TestGripCurve:
    def test_at_reference_load(self):
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        assert tire.mu(3000.0) == pytest.approx(1.2, abs=1e-9)

    def test_higher_load_less_grip(self):
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        mu_high = tire.mu(6000.0)
        assert mu_high < 1.2
        assert mu_high == pytest.approx(1.2 * 2**(-0.1), rel=1e-6)

    def test_lower_load_more_grip_coeff(self):
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        mu_low = tire.mu(1500.0)
        assert mu_low > 1.2

    def test_zero_load_returns_zero_force(self):
        tire = LoadSensitiveTire(mu_ref=1.2, Fz_ref=3000.0, sensitivity=-0.1)
        assert tire.max_force(0.0) == pytest.approx(0.0)


class TestFrictionEllipse:
    def test_pure_lateral_at_limit(self):
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5000.0, sensitivity=0.0)
        Fz = 5000.0
        Fy_max = tire.mu(Fz) * Fz
        util = tire.ellipse_utilisation(Fx=0.0, Fy=Fy_max, Fz=Fz)
        assert util == pytest.approx(1.0, abs=1e-6)

    def test_combined_over_limit(self):
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5000.0, sensitivity=0.0)
        Fz = 5000.0
        F_max = tire.mu(Fz) * Fz
        util = tire.ellipse_utilisation(Fx=0.8*F_max, Fy=0.8*F_max, Fz=Fz)
        assert util > 1.0

    def test_combined_under_limit(self):
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5000.0, sensitivity=0.0)
        Fz = 5000.0
        F_max = tire.mu(Fz) * Fz
        util = tire.ellipse_utilisation(Fx=0.5*F_max, Fy=0.5*F_max, Fz=Fz)
        assert util < 1.0

    def test_accel_domain_conversion(self):
        tire = LoadSensitiveTire(mu_ref=1.0, Fz_ref=5886.0, sensitivity=0.0)
        mass = 1200.0
        Fz = 5886.0
        a_max = tire.a_max(Fz, mass)
        assert a_max == pytest.approx(5886.0 / 1200.0, rel=1e-3)
