"""Tests for the Generic CSV adapter (catch-all)."""

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

from telemetry_tool.adapters.generic_csv_adapter import GenericCSVAdapter


# ---------------------------------------------------------------------------
# CSV fixtures
# ---------------------------------------------------------------------------

_GENERIC_TELEMETRY_CSV = textwrap.dedent("""\
    Time_s,Speed,Throttle,Brake,Lap
    0.0,25.0,80.0,0.0,1
    0.033,28.0,100.0,0.0,1
    0.066,22.0,0.0,60.0,1
    0.100,30.0,90.0,0.0,2
""")

_F1_GAME_CSV = textwrap.dedent("""\
    m_speed,m_throttle,m_brake,m_gear,m_engineRPM,m_lapDistance
    180.0,1.0,0.0,5,11000,150.5
    200.0,0.8,0.0,6,12000,200.0
    120.0,0.0,0.9,3,8000,250.3
""")

_OBD_CSV = textwrap.dedent("""\
    Timestamp_s,Vehicle Speed,Engine RPM,Throttle Position,Altitude
    0.0,60.0,2500,35.0,150.0
    1.0,65.0,2800,45.0,152.0
    2.0,55.0,2200,25.0,148.0
""")

_VBOX_STYLE_CSV = textwrap.dedent("""\
    Time_s,Speed,Latitude,Longitude,Distance
    0.0,15.0,51.500,0.100,0.0
    0.1,18.0,51.501,0.101,1.5
    0.2,20.0,51.502,0.102,3.3
""")

_MINIMAL_CSV = textwrap.dedent("""\
    Time_s,Speed
    0.0,10.0
    0.1,12.0
    0.2,14.0
""")

_SINGLE_MATCH_CSV = textwrap.dedent("""\
    Speed,Color,Size
    10.0,Red,Large
    12.0,Blue,Small
""")

_NO_MATCH_CSV = textwrap.dedent("""\
    Manufacturer,Model,Year,Price
    Toyota,Camry,2024,30000
    Honda,Civic,2024,28000
""")

_KMH_SPEED_CSV = textwrap.dedent("""\
    Time_s,Speed,Throttle,Brake
    0.0,180.0,80.0,0.0
    0.033,200.0,100.0,0.0
    0.066,150.0,0.0,60.0
""")

_01_SCALE_CSV = textwrap.dedent("""\
    Time_s,Speed,Throttle,Brake
    0.0,25.0,0.8,0.0
    0.033,28.0,1.0,0.0
    0.066,22.0,0.0,0.7
""")


@pytest.fixture
def generic_telemetry_csv(tmp_path) -> Path:
    p = tmp_path / "generic_telem.csv"
    p.write_text(_GENERIC_TELEMETRY_CSV, encoding="utf-8")
    return p


@pytest.fixture
def f1_game_csv(tmp_path) -> Path:
    p = tmp_path / "f1_game.csv"
    p.write_text(_F1_GAME_CSV, encoding="utf-8")
    return p


@pytest.fixture
def obd_csv(tmp_path) -> Path:
    p = tmp_path / "obd.csv"
    p.write_text(_OBD_CSV, encoding="utf-8")
    return p


@pytest.fixture
def vbox_csv(tmp_path) -> Path:
    p = tmp_path / "vbox.csv"
    p.write_text(_VBOX_STYLE_CSV, encoding="utf-8")
    return p


@pytest.fixture
def minimal_csv(tmp_path) -> Path:
    p = tmp_path / "minimal.csv"
    p.write_text(_MINIMAL_CSV, encoding="utf-8")
    return p


@pytest.fixture
def single_match_csv(tmp_path) -> Path:
    p = tmp_path / "single_match.csv"
    p.write_text(_SINGLE_MATCH_CSV, encoding="utf-8")
    return p


@pytest.fixture
def no_match_csv(tmp_path) -> Path:
    p = tmp_path / "no_match.csv"
    p.write_text(_NO_MATCH_CSV, encoding="utf-8")
    return p


@pytest.fixture
def kmh_speed_csv(tmp_path) -> Path:
    p = tmp_path / "kmh_speed.csv"
    p.write_text(_KMH_SPEED_CSV, encoding="utf-8")
    return p


@pytest.fixture
def scale_01_csv(tmp_path) -> Path:
    p = tmp_path / "scale_01.csv"
    p.write_text(_01_SCALE_CSV, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------
class TestGenericCSVDetect:
    """Verify detect() returns appropriate confidence levels."""

    def test_detect_generic_telemetry(self, generic_telemetry_csv):
        """5 matched channels -> confidence = min(0.7, 0.5) = 0.5."""
        confidence = GenericCSVAdapter.detect(str(generic_telemetry_csv))
        assert 0.3 <= confidence <= 0.7

    def test_detect_f1_game(self, f1_game_csv):
        """F1 game columns should match several channels."""
        confidence = GenericCSVAdapter.detect(str(f1_game_csv))
        assert 0.2 <= confidence <= 0.7

    def test_detect_obd(self, obd_csv):
        """OBD columns should match speed, rpm, throttle, altitude, time."""
        confidence = GenericCSVAdapter.detect(str(obd_csv))
        assert 0.2 <= confidence <= 0.7

    def test_detect_never_above_0_7(self, generic_telemetry_csv):
        """Generic adapter confidence must never exceed 0.7."""
        confidence = GenericCSVAdapter.detect(str(generic_telemetry_csv))
        assert confidence <= 0.7

    def test_detect_never_above_0_8(self, vbox_csv):
        """Even with many matches, must stay below 0.8."""
        confidence = GenericCSVAdapter.detect(str(vbox_csv))
        assert confidence < 0.8

    def test_detect_minimal_matches(self, minimal_csv):
        """Two matched channels -> confidence = 0.2."""
        confidence = GenericCSVAdapter.detect(str(minimal_csv))
        assert 0.1 <= confidence <= 0.7

    def test_detect_single_match_zero(self, single_match_csv):
        """Only 1 channel matched -> returns 0.0 (< 2 threshold)."""
        confidence = GenericCSVAdapter.detect(str(single_match_csv))
        assert confidence == 0.0

    def test_detect_no_match_zero(self, no_match_csv):
        confidence = GenericCSVAdapter.detect(str(no_match_csv))
        assert confidence == 0.0

    def test_detect_nonexistent_file(self, tmp_path):
        confidence = GenericCSVAdapter.detect(str(tmp_path / "nope.csv"))
        assert confidence == 0.0

    def test_detect_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        confidence = GenericCSVAdapter.detect(str(p))
        assert confidence < 0.5


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------
class TestGenericCSVParse:
    """Verify parse() with fuzzy column matching."""

    def test_parse_returns_dataframe(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(generic_telemetry_csv))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 4

    def test_parse_matches_time(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(generic_telemetry_csv))
        assert "time_s" in df.columns
        assert df["time_s"].iloc[0] == pytest.approx(0.0, abs=1e-6)

    def test_parse_matches_speed(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(generic_telemetry_csv))
        assert "speed_mps" in df.columns

    def test_parse_matches_throttle(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(generic_telemetry_csv))
        assert "throttle_pct" in df.columns
        assert df["throttle_pct"].iloc[0] == pytest.approx(80.0, rel=1e-4)

    def test_parse_matches_brake(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(generic_telemetry_csv))
        assert "brake_pct" in df.columns

    def test_parse_matches_lap(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(generic_telemetry_csv))
        assert "lap_number" in df.columns
        assert df["lap_number"].iloc[0] == pytest.approx(1.0, rel=1e-4)

    def test_parse_f1_game_columns(self, f1_game_csv):
        """F1 game: m_speed, m_throttle, m_brake, m_gear, m_engineRPM."""
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(f1_game_csv))
        assert "speed_mps" in df.columns
        assert "throttle_pct" in df.columns
        assert "brake_pct" in df.columns
        assert "gear" in df.columns
        assert "rpm" in df.columns

    def test_parse_obd_columns(self, obd_csv):
        """OBD: Vehicle Speed, Engine RPM, Throttle Position."""
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(obd_csv))
        assert "speed_mps" in df.columns
        assert "rpm" in df.columns
        assert "throttle_pct" in df.columns

    def test_parse_vbox_columns(self, vbox_csv):
        """VBOX: Speed, Latitude, Longitude, Distance."""
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(vbox_csv))
        assert "speed_mps" in df.columns
        assert "distance_m" in df.columns


# ---------------------------------------------------------------------------
# Unit guessing tests
# ---------------------------------------------------------------------------
class TestGenericCSVUnitGuessing:
    """Verify automatic unit detection and conversion."""

    def test_speed_kmh_auto_convert(self, kmh_speed_csv):
        """Speed values > 120 -> assume km/h, divide by 3.6."""
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(kmh_speed_csv))
        assert "speed_mps" in df.columns
        # 180 km/h -> 50 m/s
        assert df["speed_mps"].iloc[0] == pytest.approx(180.0 / 3.6, rel=1e-3)

    def test_throttle_01_scale_to_100(self, scale_01_csv):
        """Throttle max ~1.0 -> multiply by 100."""
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(scale_01_csv))
        assert "throttle_pct" in df.columns
        # 0.8 -> 80.0
        assert df["throttle_pct"].iloc[0] == pytest.approx(80.0, rel=1e-3)

    def test_brake_01_scale_to_100(self, scale_01_csv):
        """Brake max ~0.7 -> multiply by 100."""
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(scale_01_csv))
        assert "brake_pct" in df.columns
        # 0.7 -> 70.0
        assert df["brake_pct"].iloc[2] == pytest.approx(70.0, rel=1e-3)

    def test_speed_mps_no_conversion(self, generic_telemetry_csv):
        """Speed values <= 120 -> assume m/s, no conversion."""
        adapter = GenericCSVAdapter()
        df = adapter.parse(str(generic_telemetry_csv))
        assert df["speed_mps"].iloc[0] == pytest.approx(25.0, rel=1e-4)


# ---------------------------------------------------------------------------
# available_channels and data_tier tests
# ---------------------------------------------------------------------------
class TestGenericCSVChannels:
    """Verify available_channels() and data_tier()."""

    def test_available_channels_generic(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        adapter.parse(str(generic_telemetry_csv))
        channels = adapter.available_channels()
        assert "time_s" in channels
        assert "speed_mps" in channels

    def test_available_channels_empty_before_parse(self):
        adapter = GenericCSVAdapter()
        assert adapter.available_channels() == []

    def test_data_tier_at_least_1(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        adapter.parse(str(generic_telemetry_csv))
        tier = adapter.data_tier()
        assert tier >= 1


# ---------------------------------------------------------------------------
# metadata and FORMAT_NAME tests
# ---------------------------------------------------------------------------
class TestGenericCSVMetadata:
    """Verify metadata and FORMAT_NAME."""

    def test_format_name(self):
        assert GenericCSVAdapter.FORMAT_NAME == "generic_csv"

    def test_metadata_has_format(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        adapter.parse(str(generic_telemetry_csv))
        meta = adapter.metadata()
        assert meta["format"] == "generic_csv"

    def test_metadata_empty_before_parse(self):
        adapter = GenericCSVAdapter()
        assert adapter.metadata() == {}

    def test_metadata_has_sample_count(self, generic_telemetry_csv):
        adapter = GenericCSVAdapter()
        adapter.parse(str(generic_telemetry_csv))
        meta = adapter.metadata()
        assert meta["sample_count"] == 4
