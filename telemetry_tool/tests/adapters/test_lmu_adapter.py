"""Tests for the LMU / rFactor 2 CSV telemetry adapter."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import math

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.adapters.lmu_adapter import LMUAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_lmu_csv(tmp_path: Path, *, columns: list[str] | None = None,
                   rows: list[list] | None = None) -> Path:
    """Write a synthetic LMU/rF2 CSV and return the path."""
    if columns is None:
        columns = [
            "mLapStartET", "mElapsedTime", "mLapNumber", "mLapDist",
            "mPos.x", "mPos.y", "mPos.z",
            "mLocalVel.x", "mLocalVel.y", "mLocalVel.z",
            "mLocalAccel.x", "mLocalAccel.y",
            "mSteer", "mThrottle", "mBrake", "mGear", "mRPM",
            "mWheels[0].mTemperature", "mWheels[1].mTemperature",
            "mWheels[2].mTemperature", "mWheels[3].mTemperature",
            "mWheels[0].mPressure", "mWheels[1].mPressure",
            "mWheels[2].mPressure", "mWheels[3].mPressure",
            "mWheels[0].mWear", "mWheels[1].mWear",
            "mWheels[2].mWear", "mWheels[3].mWear",
        ]
    if rows is None:
        rows = [
            # mLapStartET, mElapsedTime, mLapNumber, mLapDist,
            # mPos.x, mPos.y, mPos.z,
            # mLocalVel.x, mLocalVel.y, mLocalVel.z,
            # mLocalAccel.x, mLocalAccel.y,
            # mSteer, mThrottle, mBrake, mGear, mRPM,
            # tire temps (FL,FR,RL,RR), pressures (FL,FR,RL,RR), wear (FL,FR,RL,RR)
            [0.0, 0.0, 1, 0.0,
             100.0, 10.0, 200.0,
             30.0, 0.0, 40.0,
             2.5, -1.5,
             0.5, 0.8, 0.2, 3, 8500,
             85.0, 86.0, 82.0, 83.0,
             180.0, 181.0, 178.0, 179.0,
             0.95, 0.94, 0.96, 0.95],
            [0.0, 0.0111, 1, 5.0,
             105.0, 10.1, 205.0,
             31.0, 0.5, 41.0,
             1.0, -0.8,
             -0.3, 0.9, 0.1, 4, 9200,
             86.0, 87.0, 83.0, 84.0,
             180.5, 181.5, 178.5, 179.5,
             0.94, 0.93, 0.95, 0.94],
            [0.0, 0.0222, 1, 10.5,
             110.0, 10.2, 210.0,
             32.0, 1.0, 42.0,
             -3.0, 2.0,
             0.0, 0.3, 0.9, 2, 6000,
             87.0, 88.0, 84.0, 85.0,
             181.0, 182.0, 179.0, 180.0,
             0.93, 0.92, 0.94, 0.93],
        ]

    csv_path = tmp_path / "lmu_sample.csv"
    header = ",".join(columns)
    data_lines = [",".join(str(v) for v in row) for row in rows]
    csv_path.write_text(header + "\n" + "\n".join(data_lines) + "\n")
    return csv_path


def _write_wrong_format_csv(tmp_path: Path) -> Path:
    """Write a non-LMU CSV for negative detection tests."""
    content = """\
Time (s),Speed (m/s),Distance (m),Lap #,Latitude (deg),Longitude (deg)
0.0,10.0,0.0,1,51.5074,-0.1278
0.1,10.5,1.0,1,51.5075,-0.1279
"""
    csv_path = tmp_path / "racechrono_sample.csv"
    csv_path.write_text(content)
    return csv_path


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestLMUDetection:
    def test_detect_high_confidence_full_header(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        conf = LMUAdapter.detect(str(csv_path))
        assert conf >= 0.85

    def test_detect_medium_confidence_two_sentinels(self, tmp_path):
        csv_path = _write_lmu_csv(
            tmp_path,
            columns=["mThrottle", "mBrake", "someOther"],
            rows=[[0.5, 0.3, 1.0], [0.6, 0.2, 2.0]],
        )
        conf = LMUAdapter.detect(str(csv_path))
        assert conf == pytest.approx(0.5)

    def test_detect_low_confidence_one_sentinel(self, tmp_path):
        csv_path = _write_lmu_csv(
            tmp_path,
            columns=["mThrottle", "someOther", "anotherCol"],
            rows=[[0.5, 1.0, 2.0]],
        )
        conf = LMUAdapter.detect(str(csv_path))
        assert conf == pytest.approx(0.3)

    def test_detect_zero_for_wrong_format(self, tmp_path):
        csv_path = _write_wrong_format_csv(tmp_path)
        conf = LMUAdapter.detect(str(csv_path))
        assert conf == 0.0

    def test_detect_zero_for_nonexistent_file(self):
        assert LMUAdapter.detect("/nonexistent/path/file.csv") == 0.0

    def test_detect_zero_for_empty_file(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("")
        assert LMUAdapter.detect(str(empty)) == 0.0

    def test_detect_zero_for_non_csv(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text('{"key": "value"}')
        assert LMUAdapter.detect(str(path)) == 0.0


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestLMUParsing:
    def test_parse_returns_dataframe(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3

    def test_canonical_columns_present(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        expected = {
            "time_s", "speed_mps", "pos_x_m", "pos_y_m", "altitude_m",
            "accel_long_mps2", "accel_lat_mps2",
            "steering_angle_deg", "throttle_pct", "brake_pct",
            "gear", "rpm", "distance_m", "lap_number",
        }
        for col in expected:
            assert col in df.columns, f"Missing column: {col}"

    def test_throttle_conversion_0_1_to_pct(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        # First row: mThrottle=0.8 -> 80%
        assert df["throttle_pct"].iloc[0] == pytest.approx(80.0)

    def test_brake_conversion_0_1_to_pct(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        # First row: mBrake=0.2 -> 20%
        assert df["brake_pct"].iloc[0] == pytest.approx(20.0)

    def test_steering_conversion(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        # First row: mSteer=0.5 -> 0.5*180 = 90 degrees
        assert df["steering_angle_deg"].iloc[0] == pytest.approx(90.0)

    def test_speed_computed_from_velocity_magnitude(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        # First row: vx=30, vy=0, vz=40 -> sqrt(900+0+1600) = 50.0
        assert df["speed_mps"].iloc[0] == pytest.approx(50.0)

    def test_position_mapping_y_up_convention(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        # mPos.x -> pos_x_m, mPos.z -> pos_y_m, mPos.y -> altitude_m
        assert df["pos_x_m"].iloc[0] == pytest.approx(100.0)
        assert df["pos_y_m"].iloc[0] == pytest.approx(200.0)
        assert df["altitude_m"].iloc[0] == pytest.approx(10.0)

    def test_time_from_elapsed_time_column(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        # mElapsedTime is in seconds, mapped to time_s
        assert "time_s" in df.columns
        assert df["time_s"].iloc[0] == pytest.approx(0.0)

    def test_time_synthesised_when_no_time_column(self, tmp_path):
        csv_path = _write_lmu_csv(
            tmp_path,
            columns=["mThrottle", "mBrake", "mGear",
                      "mLocalVel.x", "mLocalVel.y", "mLocalVel.z"],
            rows=[
                [0.5, 0.2, 3, 10.0, 0.0, 10.0],
                [0.6, 0.1, 4, 11.0, 0.0, 11.0],
                [0.3, 0.9, 2, 8.0, 0.0, 8.0],
            ],
        )
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        assert "time_s" in df.columns
        # 90 Hz -> period = 1/90
        assert df["time_s"].iloc[0] == pytest.approx(0.0)
        assert df["time_s"].iloc[1] == pytest.approx(1.0 / 90.0, rel=1e-4)

    def test_gear_direct_integer(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        assert df["gear"].iloc[0] == pytest.approx(3.0)

    def test_tire_temp_columns(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        assert df["tire_temp_fl"].iloc[0] == pytest.approx(85.0)
        assert df["tire_temp_fr"].iloc[0] == pytest.approx(86.0)
        assert df["tire_temp_rl"].iloc[0] == pytest.approx(82.0)
        assert df["tire_temp_rr"].iloc[0] == pytest.approx(83.0)

    def test_tire_pressure_columns(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        assert df["tire_pressure_fl"].iloc[0] == pytest.approx(180.0)
        assert df["tire_pressure_fr"].iloc[0] == pytest.approx(181.0)

    def test_tire_wear_columns(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        df = adapter.parse(str(csv_path))
        assert df["tire_wear_fl"].iloc[0] == pytest.approx(0.95)
        assert df["tire_wear_rr"].iloc[0] == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------

class TestLMUMetadata:
    def test_metadata_returns_expected_keys(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        adapter.parse(str(csv_path))
        meta = adapter.metadata()
        assert isinstance(meta, dict)
        assert meta["source"] == "lmu"
        assert meta["format"] == "lmu"
        assert "file_name" in meta

    def test_available_channels_returns_list(self, tmp_path):
        csv_path = _write_lmu_csv(tmp_path)
        adapter = LMUAdapter()
        adapter.parse(str(csv_path))
        channels = adapter.available_channels()
        assert isinstance(channels, list)
        assert len(channels) > 0
        assert "speed_mps" in channels
        assert "throttle_pct" in channels

    def test_format_name(self):
        assert LMUAdapter.FORMAT_NAME == "lmu"

    def test_extensions(self):
        assert ".csv" in LMUAdapter.EXTENSIONS
