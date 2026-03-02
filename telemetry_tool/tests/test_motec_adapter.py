"""Tests for the MoTeC i2 CSV adapter."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is on the path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.adapters.motec_adapter import MoTeCAdapter

_G = 9.80665


# ---------------------------------------------------------------------------
# CSV fixtures
# ---------------------------------------------------------------------------

_MOTEC_CSV_BASIC = textwrap.dedent("""\
    Time,Beacon,Engine RPM,Throttle Pos,Brake Press,Ground Speed,GPS Lat,GPS Long
    0.0,0,5000,80.0,0.0,25.0,50.437,6.025
    0.033,0,5500,100.0,0.0,28.0,50.438,6.026
    0.066,0,4000,0.0,60.0,22.0,50.439,6.027
    0.100,1,6000,90.0,0.0,30.0,50.440,6.028
""")

_MOTEC_CSV_WITH_UNITS = textwrap.dedent("""\
    Time,Beacon,Engine RPM,Throttle Pos,Brake Press,Ground Speed
    s,,rpm,%,%,m/s
    0.0,0,5000,80.0,0.0,25.0
    0.033,0,5500,100.0,0.0,28.0
    0.066,0,4000,0.0,60.0,22.0
""")

_MOTEC_CSV_WITH_ACCEL = textwrap.dedent("""\
    Time,Beacon,Engine RPM,Throttle Pos,Brake Press,Ground Speed,Lateral G,Longitudinal G,Yaw Rate
    0.0,0,5000,80.0,0.0,25.0,0.5,0.3,10.0
    0.033,0,5500,100.0,0.0,28.0,0.8,0.6,15.0
    0.066,0,4000,0.0,60.0,22.0,1.2,-0.5,-5.0
""")

_MOTEC_CSV_FULL = textwrap.dedent("""\
    Time,Beacon,Engine RPM,Throttle Pos,Brake Press,Ground Speed,GPS Lat,GPS Long,Lateral G,Longitudinal G,Yaw Rate,Oil Temp,Water Temp,Fuel,Tyre Temp FL,Tyre Temp FR,Tyre Temp RL,Tyre Temp RR,Steer Angle,Lap
    0.0,0,5000,80.0,0.0,25.0,50.437,6.025,0.5,0.3,10.0,95.0,85.0,40.0,90.0,91.0,85.0,86.0,5.0,1
    0.033,0,5500,100.0,0.0,28.0,50.438,6.026,0.8,0.6,15.0,96.0,86.0,39.5,91.0,92.0,86.0,87.0,-2.0,1
    0.066,1,4000,0.0,60.0,22.0,50.439,6.027,1.2,-0.5,-5.0,97.0,87.0,39.0,92.0,93.0,87.0,88.0,30.0,2
""")

_MOTEC_CSV_RPM_NO_BEACON = textwrap.dedent("""\
    Time,Engine RPM,Throttle Pos,Brake Press,Ground Speed,GPS Lat,GPS Long
    0.0,5000,80.0,0.0,25.0,50.437,6.025
    0.033,5500,100.0,0.0,28.0,50.438,6.026
""")

_NOT_MOTEC_CSV = textwrap.dedent("""\
    speedKmh,gas,brake,steerAngle,rpms,gear
    120.5,0.8,0.0,5.2,6500,3
    130.0,1.0,0.0,-2.1,7200,3
""")

_GENERIC_CSV = textwrap.dedent("""\
    Manufacturer,Model,Year,Price
    Toyota,Camry,2024,30000
    Honda,Civic,2024,28000
""")


@pytest.fixture
def motec_basic_csv(tmp_path) -> Path:
    p = tmp_path / "motec_basic.csv"
    p.write_text(_MOTEC_CSV_BASIC, encoding="utf-8")
    return p


@pytest.fixture
def motec_units_csv(tmp_path) -> Path:
    p = tmp_path / "motec_units.csv"
    p.write_text(_MOTEC_CSV_WITH_UNITS, encoding="utf-8")
    return p


@pytest.fixture
def motec_accel_csv(tmp_path) -> Path:
    p = tmp_path / "motec_accel.csv"
    p.write_text(_MOTEC_CSV_WITH_ACCEL, encoding="utf-8")
    return p


@pytest.fixture
def motec_full_csv(tmp_path) -> Path:
    p = tmp_path / "motec_full.csv"
    p.write_text(_MOTEC_CSV_FULL, encoding="utf-8")
    return p


@pytest.fixture
def motec_no_beacon_csv(tmp_path) -> Path:
    p = tmp_path / "motec_no_beacon.csv"
    p.write_text(_MOTEC_CSV_RPM_NO_BEACON, encoding="utf-8")
    return p


@pytest.fixture
def non_motec_csv(tmp_path) -> Path:
    p = tmp_path / "not_motec.csv"
    p.write_text(_NOT_MOTEC_CSV, encoding="utf-8")
    return p


@pytest.fixture
def generic_csv(tmp_path) -> Path:
    p = tmp_path / "generic.csv"
    p.write_text(_GENERIC_CSV, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------
class TestMoTeCDetect:
    """Verify detect() identifies MoTeC files correctly."""

    def test_detect_motec_basic_high_confidence(self, motec_basic_csv):
        confidence = MoTeCAdapter.detect(str(motec_basic_csv))
        assert confidence > 0.8

    def test_detect_motec_full_high_confidence(self, motec_full_csv):
        confidence = MoTeCAdapter.detect(str(motec_full_csv))
        assert confidence > 0.8

    def test_detect_motec_no_beacon_moderate(self, motec_no_beacon_csv):
        """Engine RPM + Throttle + Brake + Ground Speed -> should detect."""
        confidence = MoTeCAdapter.detect(str(motec_no_beacon_csv))
        assert confidence > 0.5

    def test_detect_non_motec_low_confidence(self, non_motec_csv):
        confidence = MoTeCAdapter.detect(str(non_motec_csv))
        assert confidence < 0.5

    def test_detect_generic_csv_zero(self, generic_csv):
        confidence = MoTeCAdapter.detect(str(generic_csv))
        assert confidence == 0.0

    def test_detect_nonexistent_file(self, tmp_path):
        confidence = MoTeCAdapter.detect(str(tmp_path / "nope.csv"))
        assert confidence == 0.0

    def test_detect_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        confidence = MoTeCAdapter.detect(str(p))
        assert confidence < 0.5


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------
class TestMoTeCParse:
    """Verify parse() produces correct canonical columns and conversions."""

    def test_parse_returns_dataframe(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_basic_csv))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 4

    def test_parse_has_canonical_columns(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_basic_csv))
        assert "time_s" in df.columns
        assert "rpm" in df.columns
        assert "throttle_pct" in df.columns
        assert "brake_pct" in df.columns
        assert "speed_mps" in df.columns
        assert "lat_deg" in df.columns
        assert "lon_deg" in df.columns

    def test_time_values_preserved(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_basic_csv))
        assert df["time_s"].iloc[0] == pytest.approx(0.0, abs=1e-6)
        assert df["time_s"].iloc[1] == pytest.approx(0.033, rel=1e-3)

    def test_rpm_values_preserved(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_basic_csv))
        assert df["rpm"].iloc[0] == pytest.approx(5000.0, rel=1e-4)

    def test_speed_values_m_per_s(self, motec_basic_csv):
        """Ground Speed=25.0 should remain 25.0 (below 120 threshold)."""
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_basic_csv))
        assert df["speed_mps"].iloc[0] == pytest.approx(25.0, rel=1e-4)

    def test_beacon_column_removed(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_basic_csv))
        assert "Beacon" not in df.columns

    def test_units_row_skipped(self, motec_units_csv):
        """MoTeC CSV with units row: should have 3 data rows, not 4."""
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_units_csv))
        assert len(df) == 3
        # First data row should be numeric, not the units row.
        assert df["time_s"].iloc[0] == pytest.approx(0.0, abs=1e-6)
        assert df["rpm"].iloc[0] == pytest.approx(5000.0, rel=1e-4)


# ---------------------------------------------------------------------------
# G-force conversion tests
# ---------------------------------------------------------------------------
class TestMoTeCAccelConversion:
    """Verify G-force columns are converted to m/s^2."""

    def test_lateral_g_to_mps2(self, motec_accel_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_accel_csv))
        assert "accel_lat_mps2" in df.columns
        # 0.5 G * 9.80665 = 4.903325
        assert df["accel_lat_mps2"].iloc[0] == pytest.approx(0.5 * _G, rel=1e-4)

    def test_longitudinal_g_to_mps2(self, motec_accel_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_accel_csv))
        assert "accel_long_mps2" in df.columns
        # 0.3 G * 9.80665 = 2.941995
        assert df["accel_long_mps2"].iloc[0] == pytest.approx(0.3 * _G, rel=1e-4)

    def test_yaw_rate_preserved(self, motec_accel_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_accel_csv))
        assert "yaw_rate_dps" in df.columns
        assert df["yaw_rate_dps"].iloc[0] == pytest.approx(10.0, rel=1e-4)


# ---------------------------------------------------------------------------
# Full data tests
# ---------------------------------------------------------------------------
class TestMoTeCFullData:
    """Verify full MoTeC export with all channel types."""

    def test_oil_temp(self, motec_full_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_full_csv))
        assert "oil_temp" in df.columns
        assert df["oil_temp"].iloc[0] == pytest.approx(95.0, rel=1e-4)

    def test_water_temp(self, motec_full_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_full_csv))
        assert "water_temp" in df.columns
        assert df["water_temp"].iloc[0] == pytest.approx(85.0, rel=1e-4)

    def test_fuel(self, motec_full_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_full_csv))
        assert "fuel_kg" in df.columns
        assert df["fuel_kg"].iloc[0] == pytest.approx(40.0, rel=1e-4)

    def test_tire_temp(self, motec_full_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_full_csv))
        assert "tire_temp_fl" in df.columns
        assert df["tire_temp_fl"].iloc[0] == pytest.approx(90.0, rel=1e-4)

    def test_steering_angle(self, motec_full_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_full_csv))
        assert "steering_angle_deg" in df.columns
        assert df["steering_angle_deg"].iloc[0] == pytest.approx(5.0, rel=1e-4)

    def test_lap_number(self, motec_full_csv):
        adapter = MoTeCAdapter()
        df = adapter.parse(str(motec_full_csv))
        assert "lap_number" in df.columns
        assert df["lap_number"].iloc[0] == pytest.approx(1.0, rel=1e-4)
        assert df["lap_number"].iloc[2] == pytest.approx(2.0, rel=1e-4)


# ---------------------------------------------------------------------------
# available_channels and data_tier tests
# ---------------------------------------------------------------------------
class TestMoTeCChannels:
    """Verify available_channels() and data_tier()."""

    def test_available_channels_basic(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        adapter.parse(str(motec_basic_csv))
        channels = adapter.available_channels()
        assert "time_s" in channels
        assert "rpm" in channels
        assert "throttle_pct" in channels
        assert "speed_mps" in channels

    def test_available_channels_empty_before_parse(self):
        adapter = MoTeCAdapter()
        assert adapter.available_channels() == []

    def test_data_tier_basic_at_least_1(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        adapter.parse(str(motec_basic_csv))
        tier = adapter.data_tier()
        assert tier >= 1

    def test_data_tier_with_accel_at_least_2(self, motec_accel_csv):
        adapter = MoTeCAdapter()
        adapter.parse(str(motec_accel_csv))
        tier = adapter.data_tier()
        assert tier >= 2

    def test_data_tier_full_at_least_3(self, motec_full_csv):
        """Full data with accel + controls should be tier >= 3."""
        adapter = MoTeCAdapter()
        adapter.parse(str(motec_full_csv))
        tier = adapter.data_tier()
        assert tier >= 3


# ---------------------------------------------------------------------------
# metadata and FORMAT_NAME tests
# ---------------------------------------------------------------------------
class TestMoTeCMetadata:
    """Verify metadata and FORMAT_NAME."""

    def test_format_name(self):
        assert MoTeCAdapter.FORMAT_NAME == "motec"

    def test_metadata_has_format(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        adapter.parse(str(motec_basic_csv))
        meta = adapter.metadata()
        assert meta["format"] == "motec"

    def test_metadata_empty_before_parse(self):
        adapter = MoTeCAdapter()
        assert adapter.metadata() == {}

    def test_metadata_has_sample_count(self, motec_basic_csv):
        adapter = MoTeCAdapter()
        adapter.parse(str(motec_basic_csv))
        meta = adapter.metadata()
        assert meta["sample_count"] == 4
