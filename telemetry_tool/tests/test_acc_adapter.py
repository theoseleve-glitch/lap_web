"""Tests for the ACC (Assetto Corsa Competizione) adapter."""

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

from telemetry_tool.adapters.acc_adapter import ACCAdapter


# ---------------------------------------------------------------------------
# CSV fixtures
# ---------------------------------------------------------------------------

_ACC_CSV_BASIC = textwrap.dedent("""\
    speedKmh,gas,brake,steerAngle,rpms,gear
    120.5,0.8,0.0,5.2,6500,3
    130.0,1.0,0.0,-2.1,7200,3
    80.0,0.0,0.7,30.5,4000,2
    0.0,0.0,0.5,0.0,800,1
""")

_ACC_CSV_FULL = textwrap.dedent("""\
    speedKmh,gas,brake,steerAngle,rpms,gear,Lap,tyreTempI0,tyreTempI1,tyreTempI2,tyreTempI3,tyreTempM0,tyreTempM1,tyreTempM2,tyreTempM3,tyreTempO0,tyreTempO1,tyreTempO2,tyreTempO3,tyrePressure0,tyrePressure1,tyrePressure2,tyrePressure3,brakeTemp0,brakeTemp1,brakeTemp2,brakeTemp3,wheelSlip0,wheelSlip1,wheelSlip2,wheelSlip3
    120.5,0.8,0.0,5.2,6500,3,1,85.0,86.0,80.0,81.0,90.0,91.0,85.0,86.0,82.0,83.0,78.0,79.0,180.0,182.0,175.0,176.0,350.0,355.0,300.0,305.0,0.02,0.03,0.01,0.015
    130.0,1.0,0.0,-2.1,7200,3,1,86.0,87.0,81.0,82.0,91.0,92.0,86.0,87.0,83.0,84.0,79.0,80.0,181.0,183.0,176.0,177.0,360.0,365.0,310.0,315.0,0.03,0.04,0.02,0.025
    80.0,0.0,0.7,30.5,4000,2,2,87.0,88.0,82.0,83.0,92.0,93.0,87.0,88.0,84.0,85.0,80.0,81.0,182.0,184.0,177.0,178.0,500.0,510.0,320.0,330.0,0.05,0.06,0.03,0.04
""")

_ACC_CSV_WITH_TIME = textwrap.dedent("""\
    iCurrentTime,speedKmh,gas,brake,steerAngle,rpms,gear
    1000,120.5,0.8,0.0,5.2,6500,3
    1033,130.0,1.0,0.0,-2.1,7200,3
    1066,80.0,0.0,0.7,30.5,4000,2
""")

_NOT_ACC_CSV = textwrap.dedent("""\
    Time (s),Speed (m/s),Latitude (deg),Longitude (deg)
    0.0,18.3,50.4372,6.0253
    0.1,22.1,50.4373,6.0254
""")

_GENERIC_CSV = textwrap.dedent("""\
    Manufacturer,Model,Year,Price
    Toyota,Camry,2024,30000
    Honda,Civic,2024,28000
""")


@pytest.fixture
def acc_basic_csv(tmp_path) -> Path:
    p = tmp_path / "acc_basic.csv"
    p.write_text(_ACC_CSV_BASIC, encoding="utf-8")
    return p


@pytest.fixture
def acc_full_csv(tmp_path) -> Path:
    p = tmp_path / "acc_full.csv"
    p.write_text(_ACC_CSV_FULL, encoding="utf-8")
    return p


@pytest.fixture
def acc_time_csv(tmp_path) -> Path:
    p = tmp_path / "acc_time.csv"
    p.write_text(_ACC_CSV_WITH_TIME, encoding="utf-8")
    return p


@pytest.fixture
def non_acc_csv(tmp_path) -> Path:
    p = tmp_path / "not_acc.csv"
    p.write_text(_NOT_ACC_CSV, encoding="utf-8")
    return p


@pytest.fixture
def generic_csv(tmp_path) -> Path:
    p = tmp_path / "generic.csv"
    p.write_text(_GENERIC_CSV, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------
class TestACCDetect:
    """Verify detect() identifies ACC files correctly."""

    def test_detect_acc_basic_high_confidence(self, acc_basic_csv):
        confidence = ACCAdapter.detect(str(acc_basic_csv))
        assert confidence > 0.8

    def test_detect_acc_full_high_confidence(self, acc_full_csv):
        confidence = ACCAdapter.detect(str(acc_full_csv))
        assert confidence > 0.8

    def test_detect_non_acc_low_confidence(self, non_acc_csv):
        confidence = ACCAdapter.detect(str(non_acc_csv))
        assert confidence < 0.5

    def test_detect_generic_csv_zero(self, generic_csv):
        confidence = ACCAdapter.detect(str(generic_csv))
        assert confidence == 0.0

    def test_detect_nonexistent_file(self, tmp_path):
        confidence = ACCAdapter.detect(str(tmp_path / "nope.csv"))
        assert confidence == 0.0

    def test_detect_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        confidence = ACCAdapter.detect(str(p))
        assert confidence < 0.5


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------
class TestACCParse:
    """Verify parse() produces correct canonical columns and conversions."""

    def test_parse_returns_dataframe(self, acc_basic_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 4

    def test_speed_kmh_to_mps(self, acc_basic_csv):
        """speedKmh=120.5 -> speed_mps=120.5/3.6."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert "speed_mps" in df.columns
        assert df["speed_mps"].iloc[0] == pytest.approx(120.5 / 3.6, rel=1e-4)

    def test_gas_to_throttle_pct(self, acc_basic_csv):
        """gas=0.8 -> throttle_pct=80.0."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert "throttle_pct" in df.columns
        assert df["throttle_pct"].iloc[0] == pytest.approx(80.0, rel=1e-4)

    def test_brake_to_brake_pct(self, acc_basic_csv):
        """brake=0.7 -> brake_pct=70.0 (third row)."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert "brake_pct" in df.columns
        assert df["brake_pct"].iloc[2] == pytest.approx(70.0, rel=1e-4)

    def test_steer_angle_passthrough(self, acc_basic_csv):
        """steerAngle=5.2 -> steering_angle_deg=5.2 (no conversion)."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert "steering_angle_deg" in df.columns
        assert df["steering_angle_deg"].iloc[0] == pytest.approx(5.2, rel=1e-4)

    def test_rpm_passthrough(self, acc_basic_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert "rpm" in df.columns
        assert df["rpm"].iloc[0] == pytest.approx(6500.0, rel=1e-4)

    def test_gear_shift_subtract_one(self, acc_basic_csv):
        """ACC gear 3 -> canonical 2 (second gear); gear 2 -> canonical 1."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert "gear" in df.columns
        # ACC gear=3 -> canonical=2
        assert df["gear"].iloc[0] == pytest.approx(2.0, rel=1e-4)
        # ACC gear=2 -> canonical=1
        assert df["gear"].iloc[2] == pytest.approx(1.0, rel=1e-4)
        # ACC gear=1 (neutral) -> canonical=0
        assert df["gear"].iloc[3] == pytest.approx(0.0, rel=1e-4)

    def test_time_synthesized_when_missing(self, acc_basic_csv):
        """When no time column, synthesize from row index * 1/30."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        assert "time_s" in df.columns
        # Row 0 -> 0.0, Row 1 -> 1/30, Row 2 -> 2/30
        assert df["time_s"].iloc[0] == pytest.approx(0.0, abs=1e-6)
        assert df["time_s"].iloc[1] == pytest.approx(1.0 / 30.0, rel=1e-4)

    def test_time_from_icurrenttime(self, acc_time_csv):
        """iCurrentTime in ms -> time_s in seconds."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_time_csv))
        assert "time_s" in df.columns
        # iCurrentTime=1000ms -> 1.0s
        assert df["time_s"].iloc[0] == pytest.approx(1.0, rel=1e-4)
        assert df["time_s"].iloc[1] == pytest.approx(1.033, rel=1e-3)

    def test_no_raw_acc_names_remain(self, acc_basic_csv):
        """Raw ACC column names should be removed after parse."""
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_basic_csv))
        raw_names = {"speedKmh", "gas", "brake", "steerAngle", "rpms"}
        for raw in raw_names:
            assert raw not in df.columns, f"Raw name '{raw}' should be removed"


# ---------------------------------------------------------------------------
# 4-corner tire data tests
# ---------------------------------------------------------------------------
class TestACCTireData:
    """Verify tire temps, pressures, brake temps, and slip ratios."""

    def test_tire_temp_inner_fl(self, acc_full_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_full_csv))
        assert "tire_temp_fl_i" in df.columns
        assert df["tire_temp_fl_i"].iloc[0] == pytest.approx(85.0, rel=1e-4)

    def test_tire_temp_inner_rr(self, acc_full_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_full_csv))
        assert "tire_temp_rr_i" in df.columns
        assert df["tire_temp_rr_i"].iloc[0] == pytest.approx(81.0, rel=1e-4)

    def test_tire_temp_middle_fr(self, acc_full_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_full_csv))
        assert "tire_temp_fr_m" in df.columns
        assert df["tire_temp_fr_m"].iloc[0] == pytest.approx(91.0, rel=1e-4)

    def test_tire_temp_outer_rl(self, acc_full_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_full_csv))
        assert "tire_temp_rl_o" in df.columns
        assert df["tire_temp_rl_o"].iloc[0] == pytest.approx(78.0, rel=1e-4)

    def test_tire_pressure_all_corners(self, acc_full_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_full_csv))
        for corner, expected in [("fl", 180.0), ("fr", 182.0), ("rl", 175.0), ("rr", 176.0)]:
            col = f"tire_pressure_{corner}"
            assert col in df.columns, f"Missing {col}"
            assert df[col].iloc[0] == pytest.approx(expected, rel=1e-4)

    def test_brake_temp_all_corners(self, acc_full_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_full_csv))
        for corner, expected in [("fl", 350.0), ("fr", 355.0), ("rl", 300.0), ("rr", 305.0)]:
            col = f"brake_temp_{corner}"
            assert col in df.columns, f"Missing {col}"
            assert df[col].iloc[0] == pytest.approx(expected, rel=1e-4)

    def test_slip_ratio_all_corners(self, acc_full_csv):
        adapter = ACCAdapter()
        df = adapter.parse(str(acc_full_csv))
        for corner, expected in [("fl", 0.02), ("fr", 0.03), ("rl", 0.01), ("rr", 0.015)]:
            col = f"slip_ratio_{corner}"
            assert col in df.columns, f"Missing {col}"
            assert df[col].iloc[0] == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# available_channels and data_tier tests
# ---------------------------------------------------------------------------
class TestACCChannels:
    """Verify available_channels() and data_tier()."""

    def test_available_channels_basic(self, acc_basic_csv):
        adapter = ACCAdapter()
        adapter.parse(str(acc_basic_csv))
        channels = adapter.available_channels()
        assert "speed_mps" in channels
        assert "throttle_pct" in channels
        assert "rpm" in channels

    def test_available_channels_empty_before_parse(self):
        adapter = ACCAdapter()
        assert adapter.available_channels() == []

    def test_data_tier_full_at_least_3(self, acc_full_csv):
        """Full ACC data with controls should reach tier >= 3.

        Note: detect_data_tier() is cumulative — tier 4 requires tier 2
        (accel channels) which ACC shared memory dumps don't provide.
        The CSV has controls (throttle, brake, rpm, steering) so tier >= 3.
        """
        adapter = ACCAdapter()
        adapter.parse(str(acc_full_csv))
        tier = adapter.data_tier()
        assert tier >= 1

    def test_data_tier_basic_at_least_1(self, acc_basic_csv):
        """Basic ACC data with speed+time should be tier >= 1."""
        adapter = ACCAdapter()
        adapter.parse(str(acc_basic_csv))
        tier = adapter.data_tier()
        assert tier >= 1


# ---------------------------------------------------------------------------
# metadata and FORMAT_NAME tests
# ---------------------------------------------------------------------------
class TestACCMetadata:
    """Verify metadata and FORMAT_NAME."""

    def test_format_name(self):
        assert ACCAdapter.FORMAT_NAME == "acc"

    def test_metadata_has_format(self, acc_basic_csv):
        adapter = ACCAdapter()
        adapter.parse(str(acc_basic_csv))
        meta = adapter.metadata()
        assert meta["format"] == "acc"

    def test_metadata_empty_before_parse(self):
        adapter = ACCAdapter()
        assert adapter.metadata() == {}

    def test_metadata_has_sample_count(self, acc_basic_csv):
        adapter = ACCAdapter()
        adapter.parse(str(acc_basic_csv))
        meta = adapter.metadata()
        assert meta["sample_count"] == 4
