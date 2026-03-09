"""Tests for the iRacing telemetry adapter.

Covers format detection, column mapping, unit conversions, time synthesis,
tire zone mapping, tire wear aggregation, partial CSV handling, and data
tier classification.
"""

from __future__ import annotations

import math
import textwrap

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.adapters.iracing_adapter import IRacingAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def iracing_full_csv(tmp_path):
    """Full iRacing export with all major channels."""
    header = (
        "Lap,LapDist,Speed,Throttle,Brake,Clutch,Gear,RPM,"
        "SteeringWheelAngle,Lat,Lon,Alt,LatAccel,LonAccel,YawRate,"
        "LFtempCL,LFtempCM,LFtempCR,"
        "RFtempCL,RFtempCM,RFtempCR,"
        "LRtempCL,LRtempCM,LRtempCR,"
        "RRtempCL,RRtempCM,RRtempCR,"
        "LFpressure,RFpressure,LRpressure,RRpressure,"
        "FuelLevel,"
        "LFspd,RFspd,LRspd,RRspd,"
        "LFwearL,LFwearM,LFwearR,"
        "RFwearL,RFwearM,RFwearR,"
        "LRwearL,LRwearM,LRwearR,"
        "RRwearL,RRwearM,RRwearR,"
        "AirTemp,TrackTemp"
    )
    row1 = (
        "1,0.0,0.0,0.0,0.0,0.0,1,800,"
        "-0.5,45.123,-73.456,100.0,0.0,0.0,0.0,"
        "80.0,82.0,79.0,"
        "81.0,83.0,80.0,"
        "78.0,80.0,77.0,"
        "79.0,81.0,78.0,"
        "172.0,172.0,165.0,165.0,"
        "45.2,"
        "0.0,0.0,0.0,0.0,"
        "98.0,97.0,96.0,"
        "97.0,96.0,95.0,"
        "99.0,98.0,97.0,"
        "98.0,97.0,96.0,"
        "25.0,35.0"
    )
    row2 = (
        "1,10.5,22.3,1.0,0.0,0.0,2,4500,"
        "0.0367,45.124,-73.457,100.1,0.3,5.2,0.021,"
        "82.0,84.0,81.0,"
        "83.0,85.0,82.0,"
        "80.0,82.0,79.0,"
        "81.0,83.0,80.0,"
        "174.0,174.0,167.0,167.0,"
        "45.1,"
        "22.1,22.4,22.2,22.5,"
        "97.5,96.5,95.5,"
        "96.5,95.5,94.5,"
        "98.5,97.5,96.5,"
        "97.5,96.5,95.5,"
        "25.5,36.0"
    )
    row3 = (
        "1,25.0,33.5,0.8,0.2,0.0,3,6200,"
        "0.15,45.125,-73.458,100.2,1.2,-1.5,0.05,"
        "84.0,86.0,83.0,"
        "85.0,87.0,84.0,"
        "82.0,84.0,81.0,"
        "83.0,85.0,82.0,"
        "176.0,176.0,169.0,169.0,"
        "44.9,"
        "33.3,33.6,33.4,33.7,"
        "97.0,96.0,95.0,"
        "96.0,95.0,94.0,"
        "98.0,97.0,96.0,"
        "97.0,96.0,95.0,"
        "26.0,37.0"
    )

    csv_path = tmp_path / "iracing_full.csv"
    csv_path.write_text(f"{header}\n{row1}\n{row2}\n{row3}\n", encoding="utf-8")
    return str(csv_path)


@pytest.fixture
def iracing_partial_csv(tmp_path):
    """Partial iRacing export with only basic channels."""
    content = textwrap.dedent("""\
        Lap,Speed,Throttle,Brake
        1,0.0,0.0,1.0
        1,15.5,0.8,0.0
        1,28.3,1.0,0.0
        2,30.0,0.6,0.3
    """)
    csv_path = tmp_path / "iracing_partial.csv"
    csv_path.write_text(content, encoding="utf-8")
    return str(csv_path)


@pytest.fixture
def iracing_with_session_time(tmp_path):
    """iRacing export with an explicit SessionTime column."""
    content = textwrap.dedent("""\
        SessionTime,Lap,Speed,Throttle,Brake,RPM,Gear,SteeringWheelAngle
        0.0,1,0.0,0.0,1.0,800,1,0.0
        0.5,1,10.0,0.5,0.0,3000,2,0.1
        1.0,1,20.0,1.0,0.0,5000,3,-0.05
    """)
    csv_path = tmp_path / "iracing_sessiontime.csv"
    csv_path.write_text(content, encoding="utf-8")
    return str(csv_path)


@pytest.fixture
def racechrono_csv(tmp_path):
    """RaceChrono CSV -- should NOT be detected as iRacing."""
    content = textwrap.dedent("""\
        Time (s),Speed (m/s),Lap #,Latitude (deg),Longitude (deg)
        0.0,0.0,1,45.0,-73.0
        0.1,5.5,1,45.001,-73.001
    """)
    csv_path = tmp_path / "racechrono.csv"
    csv_path.write_text(content, encoding="utf-8")
    return str(csv_path)


@pytest.fixture
def non_csv_file(tmp_path):
    """A non-CSV binary file."""
    bin_path = tmp_path / "data.bin"
    bin_path.write_bytes(b"\x00\x01\x02\x03\x04\x05")
    return str(bin_path)


@pytest.fixture
def empty_file(tmp_path):
    """An empty file."""
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDetect:
    """Tests for IRacingAdapter.detect()."""

    def test_detect_full_iracing_high_confidence(self, iracing_full_csv):
        """Full iRacing CSV should return confidence > 0.8."""
        conf = IRacingAdapter.detect(iracing_full_csv)
        assert conf > 0.8

    def test_detect_partial_iracing_high_confidence(self, iracing_partial_csv):
        """Partial iRacing CSV with 4 sentinel columns should return > 0.8."""
        conf = IRacingAdapter.detect(iracing_partial_csv)
        assert conf > 0.8

    def test_detect_racechrono_low_confidence(self, racechrono_csv):
        """RaceChrono CSV should return confidence < 0.5."""
        conf = IRacingAdapter.detect(racechrono_csv)
        assert conf < 0.5

    def test_detect_nonexistent_file(self):
        """Non-existent file returns 0.0."""
        conf = IRacingAdapter.detect("/nonexistent/path/file.csv")
        assert conf == 0.0

    def test_detect_binary_file(self, non_csv_file):
        """Binary file with non-CSV extension returns 0.0."""
        conf = IRacingAdapter.detect(non_csv_file)
        assert conf == 0.0

    def test_detect_empty_file(self, empty_file):
        """Empty file returns 0.0."""
        conf = IRacingAdapter.detect(empty_file)
        assert conf == 0.0

    def test_detect_wrong_extension(self, tmp_path):
        """File with .png extension returns 0.0."""
        p = tmp_path / "data.png"
        p.write_text("Lap,Speed,Throttle,Brake,RPM\n1,10,0.5,0.0,3000\n")
        assert IRacingAdapter.detect(str(p)) == 0.0

    def test_detect_session_time_csv(self, iracing_with_session_time):
        """iRacing CSV with SessionTime should still be detected."""
        conf = IRacingAdapter.detect(iracing_with_session_time)
        assert conf > 0.8


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestParse:
    """Tests for IRacingAdapter.parse()."""

    def test_column_mapping_full(self, iracing_full_csv):
        """All expected canonical columns are present after parsing."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        expected_canonical = {
            "lap_number", "distance_m", "speed_mps", "time_s",
            "throttle_pct", "brake_pct", "clutch_pct",
            "gear", "rpm", "steering_angle_deg",
            "lat_deg", "lon_deg", "altitude_m",
            "accel_lat_mps2", "accel_long_mps2", "yaw_rate_dps",
            "tire_pressure_fl", "tire_pressure_fr",
            "tire_pressure_rl", "tire_pressure_rr",
            "wheel_speed_fl", "wheel_speed_fr",
            "wheel_speed_rl", "wheel_speed_rr",
            "fuel_kg",
            "air_temp", "track_temp",
        }
        for col in expected_canonical:
            assert col in df.columns, f"Missing canonical column: {col}"

    def test_throttle_conversion(self, iracing_full_csv):
        """Throttle 0.0-1.0 is converted to 0-100%."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: Throttle=0.0 -> 0.0%, Row 2: Throttle=1.0 -> 100.0%
        assert df["throttle_pct"].iloc[0] == pytest.approx(0.0)
        assert df["throttle_pct"].iloc[1] == pytest.approx(100.0)

    def test_brake_conversion(self, iracing_full_csv):
        """Brake 0.0-1.0 is converted to 0-100%."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: Brake=0.0 -> 0%, Row 3: Brake=0.2 -> 20%
        assert df["brake_pct"].iloc[0] == pytest.approx(0.0)
        assert df["brake_pct"].iloc[2] == pytest.approx(20.0)

    def test_clutch_conversion(self, iracing_full_csv):
        """Clutch 0.0-1.0 is converted to 0-100%."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # All rows have Clutch=0.0 -> 0%
        assert df["clutch_pct"].iloc[0] == pytest.approx(0.0)

    def test_steering_angle_radians_to_degrees(self, iracing_full_csv):
        """SteeringWheelAngle is converted from radians to degrees."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: SteeringWheelAngle = -0.5 rad -> -28.6479... deg
        expected_deg = -0.5 * (180.0 / math.pi)
        assert df["steering_angle_deg"].iloc[0] == pytest.approx(expected_deg, rel=1e-3)

    def test_yaw_rate_radians_to_degrees(self, iracing_full_csv):
        """YawRate is converted from rad/s to deg/s."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 2: YawRate = 0.021 rad/s -> ~1.203 deg/s
        expected_dps = 0.021 * (180.0 / math.pi)
        assert df["yaw_rate_dps"].iloc[1] == pytest.approx(expected_dps, rel=1e-3)

    def test_tire_temp_zone_mapping_left_side(self, iracing_full_csv):
        """Left-side tires: CL=outer, CR=inner."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: LFtempCL=80.0 -> tire_temp_fl_o, LFtempCR=79.0 -> tire_temp_fl_i
        assert df["tire_temp_fl_o"].iloc[0] == pytest.approx(80.0)
        assert df["tire_temp_fl_m"].iloc[0] == pytest.approx(82.0)
        assert df["tire_temp_fl_i"].iloc[0] == pytest.approx(79.0)

        # Rear left
        assert df["tire_temp_rl_o"].iloc[0] == pytest.approx(78.0)
        assert df["tire_temp_rl_m"].iloc[0] == pytest.approx(80.0)
        assert df["tire_temp_rl_i"].iloc[0] == pytest.approx(77.0)

    def test_tire_temp_zone_mapping_right_side(self, iracing_full_csv):
        """Right-side tires: CL=inner, CR=outer."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: RFtempCL=81.0 -> tire_temp_fr_i, RFtempCR=80.0 -> tire_temp_fr_o
        assert df["tire_temp_fr_i"].iloc[0] == pytest.approx(81.0)
        assert df["tire_temp_fr_m"].iloc[0] == pytest.approx(83.0)
        assert df["tire_temp_fr_o"].iloc[0] == pytest.approx(80.0)

        # Rear right
        assert df["tire_temp_rr_i"].iloc[0] == pytest.approx(79.0)
        assert df["tire_temp_rr_m"].iloc[0] == pytest.approx(81.0)
        assert df["tire_temp_rr_o"].iloc[0] == pytest.approx(78.0)

    def test_tire_temp_aggregates(self, iracing_full_csv):
        """Average tire temp per corner is computed from zone columns."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: FL zones = 80.0, 82.0, 79.0 -> avg = 80.333...
        expected_fl = (80.0 + 82.0 + 79.0) / 3.0
        assert df["tire_temp_fl"].iloc[0] == pytest.approx(expected_fl, rel=1e-3)

        # FR zones = 81.0, 83.0, 80.0 -> avg = 81.333...
        expected_fr = (81.0 + 83.0 + 80.0) / 3.0
        assert df["tire_temp_fr"].iloc[0] == pytest.approx(expected_fr, rel=1e-3)

    def test_fuel_litre_to_kg(self, iracing_full_csv):
        """FuelLevel is converted from litres to kg (density 0.75 kg/L)."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: FuelLevel=45.2 L -> 45.2 * 0.75 = 33.9 kg
        assert df["fuel_kg"].iloc[0] == pytest.approx(45.2 * 0.75, rel=1e-3)

    def test_time_synthesised_at_60hz(self, iracing_full_csv):
        """time_s is synthesised from row index at 60 Hz."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        period = 1.0 / 60.0
        assert df["time_s"].iloc[0] == pytest.approx(0.0)
        assert df["time_s"].iloc[1] == pytest.approx(period)
        assert df["time_s"].iloc[2] == pytest.approx(2.0 * period)

    def test_session_time_used_when_present(self, iracing_with_session_time):
        """SessionTime column is used directly instead of synthesis."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_with_session_time)

        assert df["time_s"].iloc[0] == pytest.approx(0.0)
        assert df["time_s"].iloc[1] == pytest.approx(0.5)
        assert df["time_s"].iloc[2] == pytest.approx(1.0)

    def test_tire_wear_averaged(self, iracing_full_csv):
        """Tire wear per corner is averaged from 3 zones."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 1: LFwearL=98.0, LFwearM=97.0, LFwearR=96.0 -> avg=97.0
        assert df["tire_wear_fl"].iloc[0] == pytest.approx(97.0, rel=1e-3)

        # RF: 97.0, 96.0, 95.0 -> avg=96.0
        assert df["tire_wear_fr"].iloc[0] == pytest.approx(96.0, rel=1e-3)

    def test_speed_no_conversion(self, iracing_full_csv):
        """Speed is already in m/s -- no conversion applied."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        assert df["speed_mps"].iloc[1] == pytest.approx(22.3)
        assert df["speed_mps"].iloc[2] == pytest.approx(33.5)

    def test_accel_no_conversion(self, iracing_full_csv):
        """LatAccel and LonAccel are already in m/s^2."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        # Row 2: LatAccel=0.3, LonAccel=5.2
        assert df["accel_lat_mps2"].iloc[1] == pytest.approx(0.3)
        assert df["accel_long_mps2"].iloc[1] == pytest.approx(5.2)

    def test_environment_channels(self, iracing_full_csv):
        """AirTemp and TrackTemp are mapped without conversion."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        assert df["air_temp"].iloc[0] == pytest.approx(25.0)
        assert df["track_temp"].iloc[0] == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# Partial CSV tests
# ---------------------------------------------------------------------------

class TestPartialCSV:
    """Tests for handling partial iRacing CSV exports."""

    def test_partial_csv_no_crash(self, iracing_partial_csv):
        """Parsing a partial CSV (Lap, Speed, Throttle, Brake) should not
        crash."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_partial_csv)

        assert len(df) == 4
        assert "speed_mps" in df.columns
        assert "throttle_pct" in df.columns
        assert "brake_pct" in df.columns

    def test_partial_csv_time_synthesised(self, iracing_partial_csv):
        """Partial CSV without SessionTime gets synthesised time_s."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_partial_csv)

        assert "time_s" in df.columns
        assert df["time_s"].iloc[0] == pytest.approx(0.0)

    def test_partial_csv_missing_columns_not_in_result(self, iracing_partial_csv):
        """Columns absent from CSV are not in the DataFrame."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_partial_csv)

        # These columns are not in the partial CSV.
        assert "tire_temp_fl_o" not in df.columns
        assert "fuel_kg" not in df.columns
        assert "wheel_speed_fl" not in df.columns

    def test_partial_csv_conversions_applied(self, iracing_partial_csv):
        """Throttle/Brake conversions are still applied in partial CSV."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_partial_csv)

        # Row 1: Throttle=0.0 -> 0%, Brake=1.0 -> 100%
        assert df["throttle_pct"].iloc[0] == pytest.approx(0.0)
        assert df["brake_pct"].iloc[0] == pytest.approx(100.0)

        # Row 2: Throttle=0.8 -> 80%
        assert df["throttle_pct"].iloc[1] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Metadata and channels tests
# ---------------------------------------------------------------------------

class TestMetadataAndChannels:
    """Tests for metadata() and available_channels()."""

    def test_metadata_source(self, iracing_full_csv):
        """metadata() returns source=iracing."""
        adapter = IRacingAdapter()
        adapter.parse(iracing_full_csv)

        meta = adapter.metadata()
        assert meta["source"] == "iracing"

    def test_metadata_before_parse(self):
        """metadata() returns empty dict before parse() is called."""
        adapter = IRacingAdapter()
        assert adapter.metadata() == {}

    def test_available_channels_before_parse(self):
        """available_channels() returns empty list before parse()."""
        adapter = IRacingAdapter()
        assert adapter.available_channels() == []

    def test_available_channels_full(self, iracing_full_csv):
        """Full CSV produces a comprehensive channel list."""
        adapter = IRacingAdapter()
        adapter.parse(iracing_full_csv)

        channels = adapter.available_channels()
        assert "throttle_pct" in channels
        assert "brake_pct" in channels
        assert "tire_temp_fl" in channels
        assert "tire_temp_fl_o" in channels
        assert "wheel_speed_fl" in channels
        assert "fuel_kg" in channels
        assert "time_s" in channels

    def test_available_channels_partial(self, iracing_partial_csv):
        """Partial CSV has fewer channels."""
        adapter = IRacingAdapter()
        adapter.parse(iracing_partial_csv)

        channels = adapter.available_channels()
        assert "throttle_pct" in channels
        assert "brake_pct" in channels
        assert "speed_mps" in channels
        # These should NOT be present:
        assert "tire_temp_fl" not in channels
        assert "fuel_kg" not in channels


# ---------------------------------------------------------------------------
# Data tier tests
# ---------------------------------------------------------------------------

class TestDataTier:
    """Tests for data_tier()."""

    def test_full_csv_tier_at_least_4(self, iracing_full_csv):
        """Full iRacing CSV with tire temps + wheel speeds should be >= tier 4."""
        adapter = IRacingAdapter()
        adapter.parse(iracing_full_csv)

        tier = adapter.data_tier()
        assert tier >= 4

    def test_full_csv_tier_5_with_fuel(self, iracing_full_csv):
        """Full CSV includes fuel_kg -> should qualify for tier 5."""
        adapter = IRacingAdapter()
        adapter.parse(iracing_full_csv)

        tier = adapter.data_tier()
        assert tier == 5

    def test_partial_csv_tier(self, iracing_partial_csv):
        """Partial CSV (speed + throttle + brake) should be tier 1."""
        adapter = IRacingAdapter()
        adapter.parse(iracing_partial_csv)

        # Only has time_s, speed_mps, throttle_pct, brake_pct, lap_number
        # Tier 1 requires time_s + speed_mps (both present).
        # Tier 2 requires accel_long_mps2 + accel_lat_mps2 (absent).
        tier = adapter.data_tier()
        assert tier == 1

    def test_data_tier_before_parse(self):
        """data_tier() returns 0 before parse()."""
        adapter = IRacingAdapter()
        assert adapter.data_tier() == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case and robustness tests."""

    def test_format_name(self):
        """FORMAT_NAME is 'iracing'."""
        assert IRacingAdapter.FORMAT_NAME == "iracing"

    def test_semicolon_delimited(self, tmp_path):
        """Semicolon-delimited iRacing CSV is detected."""
        content = "Lap;Speed;Throttle;Brake;RPM;Gear\n1;10.0;0.5;0.0;3000;2\n"
        p = tmp_path / "iracing_semi.csv"
        p.write_text(content, encoding="utf-8")

        conf = IRacingAdapter.detect(str(p))
        assert conf > 0.8

    def test_latin1_encoding(self, tmp_path):
        """File with latin-1 encoding is handled."""
        content = "Lap,Speed,Throttle,Brake,RPM\n1,10.0,0.5,0.0,3000\n"
        p = tmp_path / "latin1.csv"
        p.write_bytes(content.encode("latin-1"))

        adapter = IRacingAdapter()
        df = adapter.parse(str(p))
        assert len(df) == 1
        assert df["speed_mps"].iloc[0] == pytest.approx(10.0)

    def test_whitespace_in_column_names(self, tmp_path):
        """Column names with leading/trailing whitespace are handled."""
        content = " Lap , Speed , Throttle , Brake , RPM \n1,10.0,0.5,0.0,3000\n"
        p = tmp_path / "whitespace.csv"
        p.write_text(content, encoding="utf-8")

        adapter = IRacingAdapter()
        df = adapter.parse(str(p))
        assert "speed_mps" in df.columns
        assert "throttle_pct" in df.columns

    def test_gear_values_preserved(self, iracing_full_csv):
        """Gear values are preserved as-is (int)."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        assert df["gear"].iloc[0] == pytest.approx(1)
        assert df["gear"].iloc[1] == pytest.approx(2)
        assert df["gear"].iloc[2] == pytest.approx(3)

    def test_pressure_no_conversion(self, iracing_full_csv):
        """Tire pressure values are passed through as kPa."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        assert df["tire_pressure_fl"].iloc[0] == pytest.approx(172.0)
        assert df["tire_pressure_rr"].iloc[0] == pytest.approx(165.0)

    def test_wheel_speed_no_conversion(self, iracing_full_csv):
        """Wheel speeds are passed through in m/s."""
        adapter = IRacingAdapter()
        df = adapter.parse(iracing_full_csv)

        assert df["wheel_speed_fl"].iloc[1] == pytest.approx(22.1)
        assert df["wheel_speed_rr"].iloc[1] == pytest.approx(22.5)

    def test_multiple_parse_calls(self, iracing_full_csv, iracing_partial_csv):
        """Calling parse() twice resets state correctly."""
        adapter = IRacingAdapter()

        # Parse full CSV.
        df1 = adapter.parse(iracing_full_csv)
        channels1 = adapter.available_channels()
        assert "fuel_kg" in channels1

        # Parse partial CSV -- fuel_kg should be gone.
        df2 = adapter.parse(iracing_partial_csv)
        channels2 = adapter.available_channels()
        assert "fuel_kg" not in channels2
