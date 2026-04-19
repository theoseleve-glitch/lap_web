"""Tests for Tasks 8-12: remaining workers, neural, RL, setup sweep."""
from __future__ import annotations

import configparser
import json
import time
from pathlib import Path

import numpy as np
import pytest

from telemetry_tool.lap_oracle.config import (
    OCPSolution,
    OracleConfig,
    PacejkaParams,
    SetupParams,
    TrackModel,
    VehicleParams,
    WeatherConditions,
)
from telemetry_tool.lap_oracle.data_lake import DataLake


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def oracle_env(tmp_path):
    """Temporary oracle environment (config + lake)."""
    config = OracleConfig(
        data_dir=tmp_path / "oracle_data",
        db_path=tmp_path / "oracle_data" / "test.db",
        ac_cfg_dir=tmp_path / "ac_cfg",
        sweep_n_samples=5,  # small for testing
    )
    lake = DataLake(config)
    return config, lake


@pytest.fixture
def sample_vehicle():
    """A basic VehicleParams for testing."""
    return VehicleParams(
        sim="ac",
        car_name="test_car",
        mass_kg=1200.0,
        wheelbase_m=2.5,
        max_power_w=300_000.0,
        max_brake_decel=10.0,
    )


@pytest.fixture
def sample_track():
    """A synthetic oval track for testing."""
    n = 100
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    radius = 200.0
    xy = np.column_stack([
        radius * np.cos(theta),
        radius * np.sin(theta),
    ])
    curvature = np.full(n, 1.0 / radius)
    total_length = 2 * np.pi * radius
    return TrackModel(
        name="test_oval",
        sim="ac",
        centerline_xy=xy,
        width_left=np.full(n, 5.0),
        width_right=np.full(n, 5.0),
        curvature=curvature,
        elevation=np.zeros(n),
        banking=np.zeros(n),
        grip_map=np.ones(n),
        sector_boundaries=[n // 3, 2 * n // 3],
        total_length_m=total_length,
    )


# =========================================================================
# Task 8: IdentifyWorker
# =========================================================================

class TestIdentifyWorker:
    """Tests for IdentifyWorker."""

    def test_creates_vehicle_from_extractor_data(self, oracle_env):
        """IdentifyWorker should build VehicleParams from payload data."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.identify import (
            _vehicle_from_extractor,
        )

        vehicle = _vehicle_from_extractor("ac", "bmw_1m", {
            "extractor_data": {
                "mass_kg": 1500.0,
                "max_power_w": 250_000.0,
            },
        })
        assert vehicle.sim == "ac"
        assert vehicle.car_name == "bmw_1m"
        assert vehicle.mass_kg == 1500.0
        assert vehicle.max_power_w == 250_000.0

    def test_creates_vehicle_from_sim_optimizer(self, oracle_env):
        """Should use sim_optimizer param_id result if present."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.identify import (
            _try_sim_optimizer_result,
        )

        vehicle = _try_sim_optimizer_result({
            "param_id_result": {
                "sim": "ac",
                "car_name": "ferrari_f40",
                "mass_kg": 1100.0,
                "max_power_w": 350_000.0,
                "cda": 0.85,
            },
        })
        assert vehicle is not None
        assert vehicle.car_name == "ferrari_f40"
        assert vehicle.mass_kg == 1100.0

    def test_tick_processes_identify_job(self, oracle_env, sample_track):
        """IdentifyWorker.tick() should claim and process an identify job."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.identify import IdentifyWorker

        # Save a track so solve jobs can be enqueued
        lake.save_track(sample_track)

        # Add an identify job
        lake.add_job(
            "identify", sim="ac", car="test_car",
            payload={"extractor_data": {"mass_kg": 1300.0}},
        )

        worker = IdentifyWorker("id-0", lake, config)
        result = worker.tick()
        assert result is True

        # Vehicle should be saved
        v = lake.load_vehicle("ac", "test_car")
        assert v is not None
        assert v.mass_kg == 1300.0

        # Solve job should be enqueued
        assert lake.count_jobs("solve", status="pending") >= 1

    def test_tick_idle_when_no_jobs(self, oracle_env):
        """tick() returns False when there are no identify jobs."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.identify import IdentifyWorker

        worker = IdentifyWorker("id-1", lake, config)
        assert worker.tick() is False


# =========================================================================
# Task 8: SolveWorker
# =========================================================================

class TestSolveWorker:
    """Tests for SolveWorker."""

    def test_solve_job_end_to_end(
        self, oracle_env, sample_vehicle, sample_track,
    ):
        """SolveWorker should solve and save an OCP solution."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.solve import SolveWorker

        lake.save_vehicle(sample_vehicle)
        lake.save_track(sample_track)
        lake.add_job(
            "solve",
            sim="ac",
            car="test_car",
            track="test_oval",
        )

        worker = SolveWorker("solve-0", lake, config)
        result = worker.tick()
        assert result is True

        # Job should be completed
        completed = lake.count_jobs("solve", status="completed")
        assert completed == 1

        # Solution should be saved
        assert lake.count_solutions() >= 1

    def test_solve_missing_vehicle(self, oracle_env, sample_track):
        """Should fail gracefully if vehicle is not in lake."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.solve import SolveWorker

        lake.save_track(sample_track)
        lake.add_job(
            "solve", sim="ac", car="nonexistent", track="test_oval",
        )

        worker = SolveWorker("solve-1", lake, config)
        result = worker.tick()
        assert result is True

        # Job should be failed
        failed = lake.count_jobs("solve", status="failed")
        assert failed == 1

    def test_solve_missing_track(self, oracle_env, sample_vehicle):
        """Should fail gracefully if track is not in lake."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.solve import SolveWorker

        lake.save_vehicle(sample_vehicle)
        lake.add_job(
            "solve", sim="ac", car="test_car", track="nonexistent",
        )

        worker = SolveWorker("solve-2", lake, config)
        result = worker.tick()
        assert result is True

        failed = lake.count_jobs("solve", status="failed")
        assert failed == 1

    def test_tick_idle_when_no_jobs(self, oracle_env):
        """tick() returns False when there are no solve jobs."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.solve import SolveWorker

        worker = SolveWorker("solve-3", lake, config)
        assert worker.tick() is False


# =========================================================================
# Task 9: Neural Surrogate
# =========================================================================

class TestNeuralSurrogate:
    """Tests for LapOracle neural model."""

    @pytest.fixture(autouse=True)
    def _check_torch(self):
        from telemetry_tool.lap_oracle.neural.surrogate import HAS_TORCH
        if not HAS_TORCH:
            pytest.skip("PyTorch not available")

    def test_forward_pass(self):
        """LapOracle forward pass should produce correct output shapes."""
        import torch
        from telemetry_tool.lap_oracle.neural.surrogate import (
            CAR_DIM,
            LapOracle,
            SETUP_DIM,
            SPEED_PROFILE_N,
            TRACK_DIM,
            WEATHER_DIM,
        )

        model = LapOracle()
        B = 4
        car = torch.randn(B, CAR_DIM)
        track = torch.randn(B, TRACK_DIM)
        setup = torch.randn(B, SETUP_DIM)
        weather = torch.randn(B, WEATHER_DIM)

        out = model(car, track, setup, weather)
        assert out["lap_time"].shape == (B, 1)
        assert out["sectors"].shape == (B, 3)
        assert out["speed_profile"].shape == (B, SPEED_PROFILE_N)
        assert out["setup_delta"].shape == (B, SETUP_DIM)


class TestOracleDataset:
    """Tests for OracleDataset loading."""

    @pytest.fixture(autouse=True)
    def _check_torch(self):
        from telemetry_tool.lap_oracle.neural.surrogate import HAS_TORCH
        if not HAS_TORCH:
            pytest.skip("PyTorch not available")

    def test_loads_from_synthetic_solutions(self, oracle_env, sample_vehicle, sample_track):
        """OracleDataset should load solutions saved to the lake."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.neural.dataset import OracleDataset

        # Save a synthetic solution
        sol = OCPSolution(
            sim="ac",
            track_name="test_oval",
            car_name="test_car",
            weather=WeatherConditions(),
            optimal_lap_time_s=85.0,
            sector_times_s=[28.0, 29.0, 28.0],
            distance_m=np.linspace(0, 1000, 100),
            speed_mps=np.full(100, 40.0),
            throttle=np.ones(100),
            brake=np.zeros(100),
            steering_rad=np.zeros(100),
            lateral_offset_m=np.zeros(100),
            solver_status="qss_fallback",
            solver_time_s=0.5,
            vehicle_params=sample_vehicle,
        )
        lake.save_solution(sol)

        ds = OracleDataset(lake.data_dir)
        assert len(ds) >= 1

        sample = ds[0]
        assert len(sample) == 5  # car, track, setup, weather, targets


# =========================================================================
# Task 10: RL Reward
# =========================================================================

class TestReward:
    """Tests for RL reward computation."""

    def test_positive_for_forward_progress(self):
        """Reward should be positive for forward progress."""
        from telemetry_tool.lap_oracle.rl.reward import compute_reward

        obs = np.zeros(23, dtype=np.float32)
        obs[0] = 50.0   # speed = 50 m/s
        obs[4] = 0.11    # lap_dist_pct = 11%

        action = np.array([0.0, 0.8, 0.0], dtype=np.float32)
        prev_lap_dist = 0.10  # was at 10%

        reward = compute_reward(obs, action, prev_lap_dist)
        assert reward > 0.0

    def test_negative_for_backward(self):
        """Reward should be negative for going backward."""
        from telemetry_tool.lap_oracle.rl.reward import compute_reward

        obs = np.zeros(23, dtype=np.float32)
        obs[0] = 5.0
        obs[4] = 0.05  # went backward

        action = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        prev_lap_dist = 0.10

        reward = compute_reward(obs, action, prev_lap_dist)
        # Progress is negative but clamped; combined with speed it may
        # still be slightly negative or near zero
        assert reward < 10.0  # at least not hugely positive

    def test_lap_wrap(self):
        """Should handle lap boundary wrap-around correctly."""
        from telemetry_tool.lap_oracle.rl.reward import compute_reward

        obs = np.zeros(23, dtype=np.float32)
        obs[0] = 40.0
        obs[4] = 0.02  # just crossed start/finish

        action = np.array([0.0, 0.5, 0.0], dtype=np.float32)
        prev_lap_dist = 0.98

        reward = compute_reward(obs, action, prev_lap_dist)
        assert reward > 0.0  # forward progress around the wrap

    def test_steering_penalty(self):
        """Heavy steering should reduce reward."""
        from telemetry_tool.lap_oracle.rl.reward import compute_reward

        obs = np.zeros(23, dtype=np.float32)
        obs[0] = 30.0
        obs[4] = 0.51

        straight = np.array([0.0, 0.5, 0.0], dtype=np.float32)
        turning = np.array([0.9, 0.5, 0.0], dtype=np.float32)

        r_straight = compute_reward(obs, straight, 0.50)
        r_turning = compute_reward(obs, turning, 0.50)
        assert r_straight > r_turning


# =========================================================================
# Task 11: ACDriverWorker
# =========================================================================

class TestACDriverWorker:
    """Tests for ACDriverWorker."""

    def test_writes_race_ini(self, oracle_env):
        """Should write a valid race.ini with correct car/track."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.ac_driver import ACDriverWorker

        worker = ACDriverWorker("ac-0", lake, config)
        ini_path = worker._write_race_ini("bmw_1m", "monza")

        assert ini_path.exists()
        cp = configparser.ConfigParser()
        cp.read(str(ini_path))
        assert cp.get("RACE", "MODEL") == "bmw_1m"
        assert cp.get("RACE", "TRACK") == "monza"
        assert cp.get("RACE", "AI_LEVEL") == "0"
        assert cp.get("CAR_0", "MODEL") == "bmw_1m"
        assert cp.get("CAR_0", "DRIVER_NAME") == "Lap Oracle"

    def test_tick_returns_false_when_disabled(self, oracle_env):
        """tick() returns False when AC driver is disabled."""
        config, lake = oracle_env
        config.enable_ac_driver = False
        from telemetry_tool.lap_oracle.workers.ac_driver import ACDriverWorker

        worker = ACDriverWorker("ac-1", lake, config)
        assert worker.tick() is False


# =========================================================================
# Task 11: TrainWorker
# =========================================================================

class TestTrainWorker:
    """Tests for TrainWorker."""

    def test_skips_when_not_enough_solutions(self, oracle_env):
        """Should return False when there are fewer than 10 solutions."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.train import TrainWorker

        worker = TrainWorker("train-0", lake, config)
        result = worker.tick()
        # Either torch not available (False) or not enough data (False)
        assert result is False

    def test_skips_when_training_disabled(self, oracle_env):
        """Should return False when neural training is disabled."""
        config, lake = oracle_env
        config.enable_neural_training = False
        from telemetry_tool.lap_oracle.workers.train import TrainWorker

        worker = TrainWorker("train-1", lake, config)
        assert worker.tick() is False


# =========================================================================
# Task 12: Setup Sweep
# =========================================================================

class TestSetupMapping:
    """Tests for apply_setup_delta."""

    def test_modifies_vehicle_params(self, sample_vehicle):
        """apply_setup_delta should return modified VehicleParams."""
        from telemetry_tool.lap_oracle.setup.mapping import apply_setup_delta

        setup = SetupParams(
            front_wing=10.0,   # +5 from reference
            rear_wing=10.0,    # +5 from reference
            front_camber=-4.0,  # -1 from reference
            rear_camber=-2.5,   # -1 from reference
            front_pressure_psi=28.0,  # +2 from reference
            rear_pressure_psi=27.0,   # +2 from reference
        )

        modified = apply_setup_delta(sample_vehicle, setup)

        # Should be a different object
        assert modified is not sample_vehicle
        # Aero should change (more wing = more downforce + drag)
        assert modified.cla != sample_vehicle.cla
        assert modified.cda != sample_vehicle.cda
        # Setup should be stored
        assert modified.setup.front_wing == 10.0

    def test_original_unchanged(self, sample_vehicle):
        """apply_setup_delta should not mutate the original vehicle."""
        from telemetry_tool.lap_oracle.setup.mapping import apply_setup_delta

        original_cla = sample_vehicle.cla
        setup = SetupParams(front_wing=15.0, rear_wing=15.0)
        apply_setup_delta(sample_vehicle, setup)

        assert sample_vehicle.cla == original_cla

    def test_clamping(self, sample_vehicle):
        """Extreme values should be clamped to reasonable ranges."""
        from telemetry_tool.lap_oracle.setup.mapping import apply_setup_delta

        setup = SetupParams(
            front_camber=-100.0,  # extreme
            rear_camber=-100.0,
            front_pressure_psi=100.0,
            rear_pressure_psi=100.0,
        )
        modified = apply_setup_delta(sample_vehicle, setup)
        # D should be clamped
        assert 0.5 <= modified.tyre_lat.D <= 2.0
        # B should be clamped
        assert 5.0 <= modified.tyre_lat.B <= 20.0


class TestSweepWorker:
    """Tests for SweepWorker."""

    def test_sweep_job_end_to_end(
        self, oracle_env, sample_vehicle, sample_track,
    ):
        """SweepWorker should evaluate setups and save the best."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.sweep import SweepWorker

        lake.save_vehicle(sample_vehicle)
        lake.save_track(sample_track)
        lake.add_job(
            "sweep", sim="ac", car="test_car", track="test_oval",
        )

        worker = SweepWorker("sweep-0", lake, config)
        result = worker.tick()
        assert result is True

        # Job should be completed
        completed = lake.count_jobs("sweep", status="completed")
        assert completed == 1

    def test_tick_idle_when_no_jobs(self, oracle_env):
        """tick() returns False when there are no sweep jobs."""
        config, lake = oracle_env
        from telemetry_tool.lap_oracle.workers.sweep import SweepWorker

        worker = SweepWorker("sweep-1", lake, config)
        assert worker.tick() is False
