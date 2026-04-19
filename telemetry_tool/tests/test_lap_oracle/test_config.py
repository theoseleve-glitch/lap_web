"""Tests for telemetry_tool.lap_oracle.config dataclasses."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from telemetry_tool.lap_oracle.config import (
    DATA_ZIPS,
    ORACLE_DATA,
    ORACLE_DB,
    PROJECT_ROOT,
    SIM_PATHS,
    OracleConfig,
    OCPSolution,
    PacejkaParams,
    SetupParams,
    TrackModel,
    VehicleParams,
    WeatherConditions,
)


# -- PacejkaParams -----------------------------------------------------

class TestPacejkaParams:
    def test_defaults(self):
        p = PacejkaParams()
        assert p.B == 10.0
        assert p.C == 1.3
        assert p.D == 1.0
        assert p.E == -0.5

    def test_frozen(self):
        p = PacejkaParams()
        with pytest.raises(AttributeError):
            p.B = 99.0  # type: ignore[misc]

    def test_array_roundtrip(self):
        p = PacejkaParams(B=8.0, C=1.1, D=0.9, E=-0.7)
        arr = p.to_array()
        assert arr.shape == (4,)
        p2 = PacejkaParams.from_array(arr)
        assert p2 == p

    def test_dict_roundtrip(self):
        p = PacejkaParams(B=11.0, C=1.5, D=1.2, E=-0.1)
        d = p.to_dict()
        assert isinstance(d, dict)
        p2 = PacejkaParams.from_dict(d)
        assert p2 == p


# -- SetupParams -------------------------------------------------------

class TestSetupParams:
    def test_n_params(self):
        assert SetupParams.n_params() == 19

    def test_array_roundtrip(self):
        s = SetupParams()
        arr = s.to_array()
        assert arr.shape == (19,)
        assert arr.dtype == np.float64
        s2 = SetupParams.from_array(arr)
        assert s2 == s

    def test_array_roundtrip_custom(self):
        s = SetupParams(front_wing=8.0, rear_wing=7.0, brake_bias=0.60)
        arr = s.to_array()
        s2 = SetupParams.from_array(arr)
        assert s2.front_wing == 8.0
        assert s2.rear_wing == 7.0
        assert s2.brake_bias == 0.60

    def test_from_array_wrong_size(self):
        with pytest.raises(ValueError, match="Expected 19"):
            SetupParams.from_array(np.zeros(5))

    def test_dict_roundtrip(self):
        s = SetupParams(diff_preload=55.0)
        d = s.to_dict()
        s2 = SetupParams.from_dict(d)
        assert s2 == s


# -- VehicleParams -----------------------------------------------------

class TestVehicleParams:
    def test_defaults(self):
        v = VehicleParams()
        assert v.mass_kg == 1300.0
        assert v.wheelbase_m == 2.65
        assert v.cla == 2.5
        assert v.max_power_w == 400_000.0

    def test_nested_defaults(self):
        v = VehicleParams()
        assert isinstance(v.tyre_lat, PacejkaParams)
        assert v.tyre_lat.B == 10.0
        assert v.tyre_long.B == 12.0
        assert v.tyre_long.E == -0.3
        assert isinstance(v.setup, SetupParams)

    def test_dict_roundtrip(self):
        v = VehicleParams(
            sim="ac",
            car_name="ks_ferrari_488_gt3",
            mass_kg=1250.0,
            tyre_lat=PacejkaParams(B=9.0, C=1.2, D=0.95, E=-0.6),
            tyre_long=PacejkaParams(B=11.0, C=1.3, D=1.0, E=-0.4),
            setup=SetupParams(front_wing=7.0, rear_wing=6.0),
        )
        d = v.to_dict()
        # Verify it is a plain dict (JSON-serializable structure)
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

        v2 = VehicleParams.from_dict(d)
        assert v2.sim == "ac"
        assert v2.car_name == "ks_ferrari_488_gt3"
        assert v2.mass_kg == 1250.0
        assert v2.tyre_lat == PacejkaParams(B=9.0, C=1.2, D=0.95, E=-0.6)
        assert v2.tyre_long == PacejkaParams(B=11.0, C=1.3, D=1.0, E=-0.4)
        assert v2.setup.front_wing == 7.0
        assert v2.setup.rear_wing == 6.0

    def test_dict_roundtrip_with_defaults(self):
        """Default VehicleParams survives to_dict/from_dict."""
        v = VehicleParams()
        d = v.to_dict()
        v2 = VehicleParams.from_dict(d)
        assert v2.mass_kg == v.mass_kg
        assert v2.tyre_lat == v.tyre_lat
        assert v2.tyre_long == v.tyre_long
        assert v2.setup == v.setup


# -- TrackModel --------------------------------------------------------

class TestTrackModel:
    def test_n_points_empty(self):
        t = TrackModel()
        assert t.n_points == 0

    def test_n_points(self):
        xy = np.array([[0, 0], [1, 0], [2, 0], [3, 0]], dtype=np.float64)
        t = TrackModel(centerline_xy=xy)
        assert t.n_points == 4

    def test_ds(self):
        xy = np.array([
            [0.0, 0.0],
            [3.0, 0.0],
            [3.0, 4.0],
        ], dtype=np.float64)
        t = TrackModel(centerline_xy=xy)
        ds = t.ds
        assert ds.shape == (2,)
        np.testing.assert_allclose(ds[0], 3.0)
        np.testing.assert_allclose(ds[1], 4.0)

    def test_ds_empty(self):
        t = TrackModel()
        assert t.ds.shape == (0,)

    def test_ds_single_point(self):
        xy = np.array([[1.0, 2.0]], dtype=np.float64)
        t = TrackModel(centerline_xy=xy)
        assert t.ds.shape == (0,)

    def test_sector_boundaries(self):
        t = TrackModel(sector_boundaries=[0, 100, 250])
        assert t.sector_boundaries == [0, 100, 250]


# -- WeatherConditions -------------------------------------------------

class TestWeatherConditions:
    def test_defaults(self):
        w = WeatherConditions()
        assert w.air_temp_c == 25.0
        assert w.track_temp_c == 35.0
        assert w.grip_multiplier == 1.0
        assert w.is_wet is False

    def test_frozen(self):
        w = WeatherConditions()
        with pytest.raises(AttributeError):
            w.air_temp_c = 30.0  # type: ignore[misc]

    def test_to_array_shape(self):
        w = WeatherConditions()
        arr = w.to_array()
        assert arr.shape == (10,)
        assert arr.dtype == np.float64

    def test_to_array_values(self):
        w = WeatherConditions(
            air_temp_c=25.0,
            track_temp_c=35.0,
            humidity_pct=0.5,
            is_wet=False,
            rain_intensity=0.0,
            wind_speed_ms=0.0,
            wind_direction_rad=0.0,
            grip_multiplier=1.0,
        )
        arr = w.to_array()
        np.testing.assert_allclose(arr[0], 25.0 / 50.0)       # air_temp
        np.testing.assert_allclose(arr[1], 35.0 / 70.0)       # track_temp
        np.testing.assert_allclose(arr[2], 0.5)                # humidity
        np.testing.assert_allclose(arr[3], 0.0)                # is_wet
        np.testing.assert_allclose(arr[4], 0.0)                # rain
        np.testing.assert_allclose(arr[5], 0.0)                # wind speed
        np.testing.assert_allclose(arr[6], 0.0)                # sin(0)
        np.testing.assert_allclose(arr[7], 1.0)                # cos(0)
        np.testing.assert_allclose(arr[8], 1.0)                # grip
        np.testing.assert_allclose(arr[9], 10.0 / 30.0)       # delta

    def test_to_array_wet(self):
        w = WeatherConditions(is_wet=True, rain_intensity=0.8)
        arr = w.to_array()
        assert arr[3] == 1.0
        np.testing.assert_allclose(arr[4], 0.8)

    def test_hashable(self):
        """Frozen dataclass should be hashable for use as dict key."""
        w1 = WeatherConditions()
        w2 = WeatherConditions(air_temp_c=30.0)
        s = {w1, w2}
        assert len(s) == 2


# -- OCPSolution -------------------------------------------------------

class TestOCPSolution:
    def test_defaults(self):
        sol = OCPSolution()
        assert sol.solver_status == "unsolved"
        assert sol.optimal_lap_time_s == 0.0
        assert sol.vehicle_params is None

    def test_with_data(self):
        sol = OCPSolution(
            sim="ac",
            track_name="monza",
            car_name="gt3",
            optimal_lap_time_s=98.5,
            sector_times_s=[32.1, 33.2, 33.2],
            distance_m=np.linspace(0, 5800, 500),
            speed_mps=np.ones(500) * 60.0,
            solver_status="optimal",
        )
        assert sol.distance_m.shape == (500,)
        assert sol.solver_status == "optimal"
        assert len(sol.sector_times_s) == 3


# -- OracleConfig ------------------------------------------------------

class TestOracleConfig:
    def test_defaults(self):
        cfg = OracleConfig()
        assert cfg.run_hours == 48.0
        assert cfg.harvest_workers == 4
        assert cfg.identify_workers == 2
        assert cfg.solve_workers == 4
        assert cfg.sweep_workers == 2
        assert cfg.enable_ac_driver is True
        assert cfg.enable_neural_training is True
        assert cfg.ocp_n_points == 500
        assert cfg.ocp_max_solve_time == 120.0
        assert cfg.ac_bridge_port == 9876
        assert cfg.ac_launch_timeout == 90
        assert cfg.ac_max_retries == 3
        assert cfg.neural_lr == 1e-3
        assert cfg.neural_batch_size == 2048
        assert cfg.neural_checkpoint_minutes == 30
        assert cfg.sweep_n_samples == 100

    def test_paths_are_path_objects(self):
        cfg = OracleConfig()
        assert isinstance(cfg.data_dir, Path)
        assert isinstance(cfg.db_path, Path)
        assert isinstance(cfg.ac_exe, Path)
        assert isinstance(cfg.ac_cfg_dir, Path)
        assert isinstance(cfg.ac_apps_dir, Path)

    def test_override(self):
        cfg = OracleConfig(run_hours=24.0, harvest_workers=8)
        assert cfg.run_hours == 24.0
        assert cfg.harvest_workers == 8

    def test_rl_defaults(self):
        cfg = OracleConfig()
        assert cfg.rl_lr == 3e-4
        assert cfg.rl_gamma == 0.99
        assert cfg.rl_batch_size == 256
        assert cfg.rl_buffer_size == 100_000


# -- Module-level constants --------------------------------------------

class TestConstants:
    def test_project_root(self):
        assert PROJECT_ROOT.is_dir()

    def test_oracle_paths(self):
        assert ORACLE_DATA == PROJECT_ROOT / "data" / "oracle"
        assert ORACLE_DB == ORACLE_DATA / "oracle.db"

    def test_sim_paths_keys(self):
        assert set(SIM_PATHS.keys()) == {"ac", "acc", "lmu", "iracing"}
        assert len(SIM_PATHS["ac"]) == 2
        assert len(SIM_PATHS["acc"]) == 1
        assert len(SIM_PATHS["lmu"]) == 1
        assert len(SIM_PATHS["iracing"]) == 1

    def test_data_zips_keys(self):
        expected = {
            "f1_2022", "f1_2023", "f1_2024", "f1_2025", "f1_2026",
            "raw_kart", "dallara", "motorsport", "simulated", "kaggle_f1",
        }
        assert set(DATA_ZIPS.keys()) == expected
        for v in DATA_ZIPS.values():
            assert isinstance(v, Path)
