"""Tests for parameter extraction from session data."""
import numpy as np
import pandas as pd
import pytest

from solver.param_extractor import extract_session_params
from solver.vehicle_params import params_for_class

_G = 9.80665


class TestExtractSessionParams:

    def _make_lap_df(self, n=200):
        dist = np.linspace(0, 1000, n)
        speed = np.full(n, 25.0)
        speed[50:70] = np.linspace(25, 15, 20)
        speed[70:100] = 15.0
        speed[100:130] = np.linspace(15, 25, 30)
        a_long = np.gradient(speed ** 2, dist) / 2.0
        a_lat = np.zeros(n)
        a_lat[70:100] = 8.0
        return pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "accel_long_mps2": a_long,
            "accel_lat_mps2": a_lat,
        })

    def test_extracts_mu_ref(self):
        df = self._make_lap_df()
        base = params_for_class("car")
        result = extract_session_params(df, base)
        assert result.mu_ref == pytest.approx(8.0 / _G, rel=0.05)

    def test_extracts_P_max(self):
        df = self._make_lap_df()
        base = params_for_class("car")
        result = extract_session_params(df, base)
        assert result.P_max > 0

    def test_extracts_F_brake_max(self):
        df = self._make_lap_df()
        base = params_for_class("car")
        result = extract_session_params(df, base)
        assert result.F_brake_max > 0

    def test_no_accel_columns_uses_defaults(self):
        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.full(100, 20.0),
        })
        base = params_for_class("kart")
        base.mu_ref = 1.0
        result = extract_session_params(df, base)
        assert result.mu_ref == 1.0
