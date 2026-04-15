"""Tests for the Codemasters F1 game CSV telemetry adapter."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.adapters.f1_adapter import F1Adapter

_G = 9.80665


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_f1_csv(tmp_path: Path, *, columns: list[str] | None = None,
                  rows: list[list] | None = None) -> Path:
    """Write a synthetic F1 game CSV and return the path."""
    if columns is None:
        columns = [
            "m_sessionTime", "m_currentLapNum", "m_lapDistance",
            "m_worldPositionX", "m_worldPositionY", "m_worldPositionZ",
            "m_speed", "m_gForceLateral", "m_gForceLongitudinal",
            "m_gForceVertical",
            "m_throttle", "m_brake", "m_steer", "m_gear", "m_engineRPM",
            "m_tyresSurfaceTemperature_FL", "m_tyresSurfaceTemperature_FR",
            "m_tyresSurfaceTemperature_RL", "m_tyresSurfaceTemperature_RR",
            "m_tyresInnerTemperature_FL", "m_tyresInnerTemperature_FR",
            "m_tyresInnerTemperature_RL", "m_tyresInnerTemperature_RR",
            "m_tyresPressure_FL", "m_tyresPressure_FR",
            "m_tyresPressure_RL", "m_tyresPressure_RR",
            "m_tyresWear_FL", "m_tyresWear_FR",
            "m_tyresWear_RL", "m_tyresWear_RR",
        ]
    if rows is None:
        rows = [
            # sessionTime, lapNum, lapDist,
            # posX, posY, posZ,
            # speed, gLat, gLong, gVert,
            # throttle, brake, steer, gear, rpm,
            # surfTemp FL/FR/RL/RR, innerTemp FL/FR/RL/RR,
            # pressure FL/FR/RL/RR, wear FL/FR/RL/RR
            [0.0, 1, 0.0,
             100.0, 5.0, 200.0,
             55.0, 1.5, 0.8, 0.1,
             0.9, 0.1, 0.4, 5, 11000,
             95.0, 96.0, 90.0, 91.0,
             105.0, 106.0, 100.0, 101.0,
             200.0, 201.0, 195.0, 196.0,
             0.92, 0.91, 0.93, 0.92],
            [0.0167, 1, 5.5,
             105.0, 5.1, 205.0,
             58.0, -0.5, 1.2, -0.05,
             1.0, 0.0, -0.2, 6, 11800,
             96.0, 97.0, 91.0, 92.0,
             106.0, 107.0, 101.0, 102.0,
             200.5, 201.5, 195.5, 196.5,
             0.91, 0.90, 0.92, 0.91],
            [0.0333, 1, 11.2,
             110.0, 5.2, 210.0,
             40.0, 2.0, -2.5, 0.3,
             0.2, 0.85, 0.7, 3, 7500,
             97.0, 98.0, 92.0, 93.0,
             107.0, 108.0, 102.0, 103.0,
             201.0, 202.0, 196.0, 197.0,
             0.90, 0.89, 0.91, 0.90],
        ]

    csv_path = tmp_path / "f1_sample.csv"
    header = ",".join(columns)
    data_lines = [",".join(str(v) for v in row) for row in rows]
    csv_path.write_text(header + "\n" + "\n".join(data_lines) + "\n")
    return csv_path


def _write_f1_alt_csv(tmp_path: Path) -> Path:
    """Write a synthetic F1 CSV with alternate column names (no m_ prefix)."""
    columns = [
        "sessionTime", "currentLapNum", "lapDistance",
        "worldPositionX", "worldPositionY", "worldPositionZ",
        "speed", "gForceLateral", "gForceLongitudinal",
        "throttle", "brake", "steer", "gear", "engineRPM",
    ]
    rows = [
        [0.0, 1, 0.0, 100.0, 5.0, 200.0, 50.0, 1.0, 0.5, 0.8, 0.2, 0.3, 4, 9000],
        [0.017, 1, 5.0, 105.0, 5.1, 205.0, 52.0, -0.3, 0.8, 0.9, 0.1, -0.1, 5, 9500],
    ]
    csv_path = tmp_path / "f1_alt_sample.csv"
    header = ",".join(columns)
    data_lines = [",".join(str(v) for v in row) for row in rows]
    csv_path.write_text(header + "\n" + "\n".join(data_lines) + "\n")
    return csv_path


def _write_wrong_format_csv(tmp_path: Path) -> Path:
    """Write a non-F1 CSV for negative detection tests."""
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

class TestF1Detection:
    def test_detect_high_confidence_full_header(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        conf = F1Adapter.detect(str(csv_path))
        assert conf >= 0.85

    def test_detect_medium_confidence_two_sentinels(self, tmp_path):
        csv_path = _write_f1_csv(
            tmp_path,
            columns=["m_throttle", "m_brake", "someOther"],
            rows=[[0.5, 0.3, 1.0], [0.6, 0.2, 2.0]],
        )
        conf = F1Adapter.detect(str(csv_path))
        assert conf == pytest.approx(0.5)

    def test_detect_low_confidence_one_sentinel(self, tmp_path):
        csv_path = _write_f1_csv(
            tmp_path,
            columns=["m_throttle", "someOther", "anotherCol"],
            rows=[[0.5, 1.0, 2.0]],
        )
        conf = F1Adapter.detect(str(csv_path))
        assert conf == pytest.approx(0.3)

    def test_detect_alt_names_three_or_more(self, tmp_path):
        csv_path = _write_f1_alt_csv(tmp_path)
        conf = F1Adapter.detect(str(csv_path))
        assert conf == pytest.approx(0.7)

    def test_detect_zero_for_wrong_format(self, tmp_path):
        csv_path = _write_wrong_format_csv(tmp_path)
        conf = F1Adapter.detect(str(csv_path))
        assert conf == 0.0

    def test_detect_zero_for_nonexistent_file(self):
        assert F1Adapter.detect("/nonexistent/path/file.csv") == 0.0

    def test_detect_zero_for_empty_file(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("")
        assert F1Adapter.detect(str(empty)) == 0.0

    def test_detect_zero_for_non_csv(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text('{"key": "value"}')
        assert F1Adapter.detect(str(path)) == 0.0


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestF1Parsing:
    def test_parse_returns_dataframe(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3

    def test_canonical_columns_present(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        expected = {
            "time_s", "speed_mps", "pos_x_m", "pos_y_m", "altitude_m",
            "accel_lat_mps2", "accel_long_mps2",
            "throttle_pct", "brake_pct", "steering_angle_deg",
            "gear", "rpm", "distance_m", "lap_number",
        }
        for col in expected:
            assert col in df.columns, f"Missing column: {col}"

    def test_throttle_conversion_0_1_to_pct(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # First row: m_throttle=0.9 -> 90%
        assert df["throttle_pct"].iloc[0] == pytest.approx(90.0)

    def test_brake_conversion_0_1_to_pct(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # First row: m_brake=0.1 -> 10%
        assert df["brake_pct"].iloc[0] == pytest.approx(10.0)

    def test_gforce_conversion_to_mps2(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # First row: m_gForceLateral=1.5G -> 1.5*9.80665
        assert df["accel_lat_mps2"].iloc[0] == pytest.approx(1.5 * _G, rel=1e-3)
        # First row: m_gForceLongitudinal=0.8G -> 0.8*9.80665
        assert df["accel_long_mps2"].iloc[0] == pytest.approx(0.8 * _G, rel=1e-3)

    def test_vertical_gforce_conversion(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # First row: m_gForceVertical=0.1G
        assert df["accel_vert_mps2"].iloc[0] == pytest.approx(0.1 * _G, rel=1e-3)

    def test_steering_conversion(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # First row: m_steer=0.4 -> 0.4*180 = 72 degrees
        assert df["steering_angle_deg"].iloc[0] == pytest.approx(72.0)

    def test_speed_direct_mps(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # First row: m_speed=55.0 -> 55.0 m/s (no conversion)
        assert df["speed_mps"].iloc[0] == pytest.approx(55.0)

    def test_position_mapping_y_up_convention(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # m_worldPositionX -> pos_x_m, m_worldPositionZ -> pos_y_m
        # m_worldPositionY -> altitude_m
        assert df["pos_x_m"].iloc[0] == pytest.approx(100.0)
        assert df["pos_y_m"].iloc[0] == pytest.approx(200.0)
        assert df["altitude_m"].iloc[0] == pytest.approx(5.0)

    def test_time_from_session_time_column(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert "time_s" in df.columns
        assert df["time_s"].iloc[0] == pytest.approx(0.0)

    def test_time_synthesised_when_no_time_column(self, tmp_path):
        csv_path = _write_f1_csv(
            tmp_path,
            columns=["m_throttle", "m_brake", "m_speed", "m_gear"],
            rows=[
                [0.5, 0.2, 40.0, 3],
                [0.6, 0.1, 42.0, 4],
                [0.3, 0.9, 30.0, 2],
            ],
        )
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert "time_s" in df.columns
        # 60 Hz -> period = 1/60
        assert df["time_s"].iloc[0] == pytest.approx(0.0)
        assert df["time_s"].iloc[1] == pytest.approx(1.0 / 60.0, rel=1e-4)

    def test_gear_direct_integer(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert df["gear"].iloc[0] == pytest.approx(5.0)

    def test_tire_surface_temp_columns(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert df["tire_temp_fl"].iloc[0] == pytest.approx(95.0)
        assert df["tire_temp_fr"].iloc[0] == pytest.approx(96.0)
        assert df["tire_temp_rl"].iloc[0] == pytest.approx(90.0)
        assert df["tire_temp_rr"].iloc[0] == pytest.approx(91.0)

    def test_tire_inner_temp_columns(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert df["tire_temp_fl_i"].iloc[0] == pytest.approx(105.0)
        assert df["tire_temp_fr_i"].iloc[0] == pytest.approx(106.0)

    def test_tire_pressure_columns(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert df["tire_pressure_fl"].iloc[0] == pytest.approx(200.0)
        assert df["tire_pressure_rr"].iloc[0] == pytest.approx(196.0)

    def test_tire_wear_columns(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert df["tire_wear_fl"].iloc[0] == pytest.approx(0.92)
        assert df["tire_wear_rr"].iloc[0] == pytest.approx(0.92)


# ---------------------------------------------------------------------------
# Alternate column names (no m_ prefix)
# ---------------------------------------------------------------------------

class TestF1AltColumns:
    def test_parse_alt_columns(self, tmp_path):
        csv_path = _write_f1_alt_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        assert isinstance(df, pd.DataFrame)
        assert "speed_mps" in df.columns
        assert "throttle_pct" in df.columns
        assert df["speed_mps"].iloc[0] == pytest.approx(50.0)
        # throttle=0.8 -> 80%
        assert df["throttle_pct"].iloc[0] == pytest.approx(80.0)

    def test_parse_alt_gforce_conversion(self, tmp_path):
        csv_path = _write_f1_alt_csv(tmp_path)
        adapter = F1Adapter()
        df = adapter.parse(str(csv_path))
        # gForceLateral=1.0G -> 9.80665
        assert df["accel_lat_mps2"].iloc[0] == pytest.approx(1.0 * _G, rel=1e-3)


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------

class TestF1Metadata:
    def test_metadata_returns_expected_keys(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        adapter.parse(str(csv_path))
        meta = adapter.metadata()
        assert isinstance(meta, dict)
        assert meta["source"] == "f1_game"
        assert meta["format"] == "f1_game"
        assert "file_name" in meta

    def test_available_channels_returns_list(self, tmp_path):
        csv_path = _write_f1_csv(tmp_path)
        adapter = F1Adapter()
        adapter.parse(str(csv_path))
        channels = adapter.available_channels()
        assert isinstance(channels, list)
        assert len(channels) > 0
        assert "speed_mps" in channels
        assert "throttle_pct" in channels

    def test_format_name(self):
        assert F1Adapter.FORMAT_NAME == "f1_game"

    def test_extensions(self):
        assert ".csv" in F1Adapter.EXTENSIONS
