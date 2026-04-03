"""Tests for telemetry_tool.lap_oracle.data_lake."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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


# -- helpers ---------------------------------------------------------------

def _make_lake(tmp_path: Path) -> DataLake:
    """Create a DataLake rooted at *tmp_path*."""
    cfg = OracleConfig(data_dir=tmp_path, db_path=tmp_path / "test.db")
    return DataLake(config=cfg)


def _sample_vehicle() -> VehicleParams:
    return VehicleParams(
        sim="ac",
        car_name="ks_ferrari_488_gt3",
        mass_kg=1250.0,
        wheelbase_m=2.70,
        tyre_lat=PacejkaParams(B=9.0, C=1.2, D=0.95, E=-0.6),
        tyre_long=PacejkaParams(B=11.0, C=1.3, D=1.0, E=-0.4),
        setup=SetupParams(front_wing=7.0, rear_wing=6.0),
    )


def _sample_track(n: int = 100) -> TrackModel:
    t = np.linspace(0, 2 * np.pi, n)
    return TrackModel(
        name="monza",
        sim="ac",
        centerline_xy=np.column_stack([np.cos(t), np.sin(t)]),
        width_left=np.full(n, 5.0),
        width_right=np.full(n, 5.0),
        curvature=np.sin(t),
        elevation=np.zeros(n),
        banking=np.zeros(n),
        grip_map=np.ones(n),
        sector_boundaries=[0, 33, 66],
        total_length_m=5793.0,
    )


def _sample_solution() -> OCPSolution:
    n = 50
    return OCPSolution(
        sim="ac",
        track_name="monza",
        car_name="gt3",
        weather=WeatherConditions(air_temp_c=25.0, is_wet=False),
        optimal_lap_time_s=98.5,
        sector_times_s=[32.1, 33.2, 33.2],
        distance_m=np.linspace(0, 5800, n),
        speed_mps=np.ones(n) * 60.0,
        throttle=np.ones(n),
        brake=np.zeros(n),
        steering_rad=np.zeros(n),
        lateral_offset_m=np.zeros(n),
        solver_status="optimal",
        solver_time_s=12.3,
        vehicle_params=_sample_vehicle(),
    )


# -- Job lifecycle ---------------------------------------------------------

class TestJobLifecycle:
    def test_add_claim_complete(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        jid = lake.add_job("solve", sim="ac", car="gt3", track="monza")
        assert isinstance(jid, int)

        claimed = lake.claim_job("solve", "worker-1")
        assert claimed is not None
        assert claimed["id"] == jid
        assert claimed["status"] == "running"
        assert claimed["worker_id"] == "worker-1"

        lake.complete_job(jid, result={"lap_time": 98.5})
        assert lake.count_jobs("solve", "completed") == 1

    def test_complete_with_error(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        jid = lake.add_job("harvest")
        lake.claim_job("harvest", "w1")
        lake.complete_job(jid, error="boom")
        assert lake.count_jobs("harvest", "failed") == 1
        assert lake.count_jobs("harvest", "completed") == 0

    def test_claim_returns_none_when_empty(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        assert lake.claim_job("solve", "w1") is None

    def test_claim_returns_none_after_all_claimed(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.add_job("identify")
        lake.claim_job("identify", "w1")
        assert lake.claim_job("identify", "w2") is None

    def test_priority_ordering(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.add_job("solve", priority=1.0)
        lake.add_job("solve", priority=5.0)
        lake.add_job("solve", priority=3.0)
        claimed = lake.claim_job("solve", "w1")
        assert claimed is not None
        assert claimed["priority"] == 5.0

    def test_invalid_job_type(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        with pytest.raises(ValueError, match="Invalid job_type"):
            lake.add_job("invalid_type")


# -- job_exists ------------------------------------------------------------

class TestJobExists:
    def test_exists_for_pending(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.add_job("solve", sim="ac", car="gt3", track="monza")
        assert lake.job_exists("solve", "ac", "gt3", "monza") is True

    def test_not_exists_missing(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        assert lake.job_exists("solve", "ac", "gt3", "spa") is False

    def test_not_exists_after_failure(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        jid = lake.add_job("solve", sim="ac", car="gt3", track="monza")
        lake.claim_job("solve", "w1")
        lake.complete_job(jid, error="oops")
        assert lake.job_exists("solve", "ac", "gt3", "monza") is False


# -- Vehicle roundtrip -----------------------------------------------------

class TestVehicle:
    def test_roundtrip(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        v = _sample_vehicle()
        path = lake.save_vehicle(v)
        assert path.exists()

        loaded = lake.load_vehicle("ac", "ks_ferrari_488_gt3")
        assert loaded is not None
        assert loaded.sim == "ac"
        assert loaded.car_name == "ks_ferrari_488_gt3"
        assert loaded.mass_kg == 1250.0
        assert loaded.wheelbase_m == 2.70
        assert loaded.tyre_lat == v.tyre_lat
        assert loaded.tyre_long == v.tyre_long
        assert loaded.setup.front_wing == 7.0

    def test_load_missing(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        assert lake.load_vehicle("ac", "nonexistent") is None

    def test_list_vehicles(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.save_vehicle(_sample_vehicle())
        lake.save_vehicle(VehicleParams(sim="acc", car_name="amr_v8"))
        pairs = lake.list_vehicles()
        assert len(pairs) == 2
        assert ("ac", "ks_ferrari_488_gt3") in pairs
        assert ("acc", "amr_v8") in pairs


# -- Track roundtrip -------------------------------------------------------

class TestTrack:
    def test_roundtrip(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        t = _sample_track(100)
        path = lake.save_track(t)
        assert path.exists()

        loaded = lake.load_track("ac", "monza")
        assert loaded is not None
        assert loaded.name == "monza"
        assert loaded.sim == "ac"
        assert loaded.centerline_xy.shape == (100, 2)
        assert loaded.width_left.shape == (100,)
        assert loaded.curvature.shape == (100,)
        assert loaded.total_length_m == 5793.0
        assert loaded.sector_boundaries == [0, 33, 66]
        np.testing.assert_allclose(
            loaded.centerline_xy, t.centerline_xy, atol=1e-10,
        )

    def test_load_missing(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        assert lake.load_track("ac", "nope") is None

    def test_list_tracks(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.save_track(_sample_track())
        lake.save_track(TrackModel(
            name="spa", sim="acc",
            centerline_xy=np.zeros((10, 2)),
            width_left=np.ones(10), width_right=np.ones(10),
            curvature=np.zeros(10), elevation=np.zeros(10),
            banking=np.zeros(10), grip_map=np.ones(10),
            total_length_m=7004.0,
        ))
        pairs = lake.list_tracks()
        assert len(pairs) == 2
        assert ("ac", "monza") in pairs
        assert ("acc", "spa") in pairs


# -- Solution save ---------------------------------------------------------

class TestSolution:
    def test_save_increments_count(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        assert lake.count_solutions() == 0
        lake.save_solution(_sample_solution())
        assert lake.count_solutions() == 1

    def test_save_creates_files(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        npz_path = lake.save_solution(_sample_solution())
        assert npz_path.exists()
        meta_path = npz_path.parent / (npz_path.stem + "_meta.json")
        assert meta_path.exists()

    def test_wet_suffix(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        sol = OCPSolution(
            sim="ac", track_name="monza", car_name="gt3",
            weather=WeatherConditions(air_temp_c=15.0, is_wet=True),
            distance_m=np.zeros(10), speed_mps=np.zeros(10),
            throttle=np.zeros(10), brake=np.zeros(10),
            steering_rad=np.zeros(10), lateral_offset_m=np.zeros(10),
        )
        p = lake.save_solution(sol)
        assert "wet_15c" in p.stem


# -- Progress summary ------------------------------------------------------

class TestProgress:
    def test_summary_structure(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.add_job("solve", sim="ac", car="gt3", track="monza")
        lake.add_job("harvest")
        lake.save_vehicle(_sample_vehicle())
        lake.save_track(_sample_track())
        lake.save_solution(_sample_solution())
        lake.log_progress("solve", combos_solved=1)

        summary = lake.get_progress_summary()
        assert "jobs" in summary
        assert "vehicles" in summary
        assert "tracks" in summary
        assert "solutions" in summary
        assert summary["vehicles"] == 1
        assert summary["tracks"] == 1
        assert summary["solutions"] == 1
        assert summary["jobs"]["solve"]["pending"] == 1
        assert summary["jobs"]["harvest"]["pending"] == 1


# -- count_jobs edge cases -------------------------------------------------

class TestCountJobs:
    def test_count_all(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.add_job("solve")
        lake.add_job("harvest")
        assert lake.count_jobs() == 2

    def test_count_by_type(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.add_job("solve")
        lake.add_job("solve")
        lake.add_job("harvest")
        assert lake.count_jobs(job_type="solve") == 2
        assert lake.count_jobs(job_type="harvest") == 1

    def test_count_by_status(self, tmp_path: Path):
        lake = _make_lake(tmp_path)
        lake.add_job("solve")
        lake.add_job("solve")
        lake.claim_job("solve", "w1")
        assert lake.count_jobs(status="pending") == 1
        assert lake.count_jobs(status="running") == 1
