# telemetry_tool/tests/test_solver_result.py
"""Tests for TheoreticalResult serialization."""
import numpy as np
import pytest

from solver.result import TheoreticalResult


class TestTheoreticalResult:

    def test_to_dict_has_required_keys(self):
        r = TheoreticalResult(
            lap_time_s=45.123,
            speed_profile=np.array([20.0, 25.0, 30.0]),
            distance_profile=np.array([0.0, 100.0, 200.0]),
            a_long_profile=np.array([1.0, 0.5, -0.3]),
            a_lat_profile=np.array([0.0, 2.0, 5.0]),
            corner_times=[],
            vehicle_params_used={"mass": 160.0},
            calibration={},
            solver_meta={"iterations": 50, "converged": True},
            tier=1,
            converged=True,
        )
        d = r.to_dict()
        assert d["lap_time_s"] == pytest.approx(45.123, abs=0.001)
        assert d["tier"] == 1
        assert d["converged"] is True
        assert len(d["speed_profile"]) == 3
        assert d["speed_profile"][0]["distance_m"] == pytest.approx(0.0)
        assert d["speed_profile"][1]["speed_mps"] == pytest.approx(25.0)
        # Required top-level keys from spec Section 7
        for key in ("lap_time_s", "speed_profile", "corner_times",
                     "vehicle_params_used", "calibration", "solver_meta",
                     "tier", "converged"):
            assert key in d

    def test_to_dict_speed_profile_entry_keys(self):
        r = TheoreticalResult(
            lap_time_s=30.0,
            speed_profile=np.array([15.0]),
            distance_profile=np.array([50.0]),
            a_long_profile=np.array([-1.0]),
            a_lat_profile=np.array([3.0]),
            corner_times=[], vehicle_params_used={},
            calibration={}, solver_meta={}, tier=1,
        )
        entry = r.to_dict()["speed_profile"][0]
        assert set(entry.keys()) == {"distance_m", "speed_mps", "a_long", "a_lat"}
