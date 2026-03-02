"""Tests for the RaceChrono adapter."""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is on the path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.adapters.racechrono_adapter import RaceChronoAdapter


# ---------------------------------------------------------------------------
# CSV fixtures
# ---------------------------------------------------------------------------
_RACECHRONO_CSV_BASIC = textwrap.dedent("""\
    RaceChrono Pro v7.3 export
    Session: Spa 2024
    Track: Circuit de Spa-Francorchamps
    ,
    Time (s), Lap #, Distance (m), Speed (m/s), Latitude (deg), Longitude (deg)
    0.0,1,0.0,0.0,50.4372,6.0253
    0.1,1,0.5,18.3,50.4373,6.0254
    0.2,1,2.3,22.1,50.4374,6.0255
    0.3,2,5.0,25.0,50.4375,6.0256
""")

_RACECHRONO_CSV_WITH_ACCEL = textwrap.dedent("""\
    RaceChrono Pro v7.3 export
    Session: Monza 2024
    ,
    Time (s), Lap #, Distance (m), Speed (m/s), Latitude (deg), Longitude (deg), Longitudinal acceleration (G) *calc, Lateral acceleration (G) *calc, Yaw rate (deg/s), Bearing (deg), Altitude (m)
    0.0,1,0.0,0.0,50.437,6.025,0.1,0.05,0.0,90.0,100.0
    0.1,1,0.5,18.3,50.438,6.026,0.3,0.10,1.5,91.0,100.5
    0.2,1,2.3,22.1,50.439,6.027,0.2,0.15,2.0,92.0,101.0
    0.3,2,5.0,25.0,50.440,6.028,0.4,0.20,0.5,93.0,101.5
""")

_RACECHRONO_CSV_WITH_CONTROLS = textwrap.dedent("""\
    RaceChrono Pro v7.3 export
    Session: Brands Hatch 2024
    ,
    Time (s), Lap #, Distance (m), Speed (m/s), Latitude (deg), Longitude (deg), Longitudinal acceleration (G) *calc, Lateral acceleration (G) *calc, Throttle position (%), Brake pressure (%), Steering angle (deg)
    0.0,1,0.0,0.0,50.437,6.025,0.1,0.05,80.0,0.0,5.0
    0.1,1,0.5,18.3,50.438,6.026,0.3,0.10,100.0,0.0,-10.0
    0.2,1,2.3,22.1,50.439,6.027,-0.2,0.30,0.0,80.0,45.0
    0.3,2,5.0,25.0,50.440,6.028,0.4,0.05,50.0,10.0,0.0
""")

_NOT_RACECHRONO_CSV = textwrap.dedent("""\
    Manufacturer,Model,Year,Price
    Toyota,Camry,2024,30000
    Honda,Civic,2024,28000
    Ford,Focus,2024,26000
""")

_RACECHRONO_CALC_PREFERENCE = textwrap.dedent("""\
    RaceChrono export
    ,
    Time (s), Speed (m/s), Speed (m/s) *calc, Latitude (deg), Longitude (deg)
    0.0,10.0,10.5,50.0,6.0
    0.1,15.0,15.5,50.1,6.1
""")


@pytest.fixture
def racechrono_basic_csv(tmp_path) -> Path:
    """Write a basic RaceChrono CSV to a temp file."""
    p = tmp_path / "basic.csv"
    p.write_text(_RACECHRONO_CSV_BASIC, encoding="utf-8")
    return p


@pytest.fixture
def racechrono_accel_csv(tmp_path) -> Path:
    """Write a RaceChrono CSV with acceleration columns."""
    p = tmp_path / "accel.csv"
    p.write_text(_RACECHRONO_CSV_WITH_ACCEL, encoding="utf-8")
    return p


@pytest.fixture
def racechrono_controls_csv(tmp_path) -> Path:
    """Write a RaceChrono CSV with throttle/brake/steering columns."""
    p = tmp_path / "controls.csv"
    p.write_text(_RACECHRONO_CSV_WITH_CONTROLS, encoding="utf-8")
    return p


@pytest.fixture
def non_racechrono_csv(tmp_path) -> Path:
    """Write a non-RaceChrono CSV."""
    p = tmp_path / "not_racechrono.csv"
    p.write_text(_NOT_RACECHRONO_CSV, encoding="utf-8")
    return p


@pytest.fixture
def calc_preference_csv(tmp_path) -> Path:
    """CSV with both Speed (m/s) and Speed (m/s) *calc."""
    p = tmp_path / "calc_pref.csv"
    p.write_text(_RACECHRONO_CALC_PREFERENCE, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------
class TestRaceChronoDetect:
    """Verify that the detect() method identifies RaceChrono files."""

    def test_detect_racechrono_basic(self, racechrono_basic_csv):
        confidence = RaceChronoAdapter.detect(str(racechrono_basic_csv))
        assert confidence > 0.8

    def test_detect_racechrono_with_accel(self, racechrono_accel_csv):
        confidence = RaceChronoAdapter.detect(str(racechrono_accel_csv))
        assert confidence > 0.8

    def test_detect_non_racechrono(self, non_racechrono_csv):
        confidence = RaceChronoAdapter.detect(str(non_racechrono_csv))
        assert confidence < 0.5

    def test_detect_nonexistent_file(self, tmp_path):
        confidence = RaceChronoAdapter.detect(str(tmp_path / "does_not_exist.csv"))
        assert confidence == 0.0

    def test_detect_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        confidence = RaceChronoAdapter.detect(str(p))
        assert confidence < 0.5


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------
class TestRaceChronoParse:
    """Verify that parse() produces canonical column names."""

    def test_parse_basic_returns_dataframe(self, racechrono_basic_csv):
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(racechrono_basic_csv))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 4

    def test_parse_basic_has_canonical_columns(self, racechrono_basic_csv):
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(racechrono_basic_csv))
        assert "time_s" in df.columns
        assert "speed_mps" in df.columns
        assert "lat_deg" in df.columns
        assert "lon_deg" in df.columns
        assert "distance_m" in df.columns
        assert "lap_number" in df.columns

    def test_parse_basic_no_raw_racechrono_names(self, racechrono_basic_csv):
        """After parsing, raw RaceChrono column names should be gone."""
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(racechrono_basic_csv))
        raw_names = {"Time (s)", "Lap #", "Speed (m/s)", "Latitude (deg)", "Longitude (deg)"}
        for raw in raw_names:
            assert raw not in df.columns, f"Raw name '{raw}' should be renamed"

    def test_parse_accel_converts_g_to_mps2(self, racechrono_accel_csv):
        """G-force columns should be converted to m/s^2 (multiply by 9.80665)."""
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(racechrono_accel_csv))
        assert "accel_long_mps2" in df.columns
        assert "accel_lat_mps2" in df.columns
        # First row: 0.1 G * 9.80665 = 0.980665 m/s^2
        assert df["accel_long_mps2"].iloc[0] == pytest.approx(0.1 * 9.80665, rel=1e-4)
        # First row: 0.05 G * 9.80665 = 0.4903325 m/s^2
        assert df["accel_lat_mps2"].iloc[0] == pytest.approx(0.05 * 9.80665, rel=1e-4)

    def test_parse_accel_has_yaw_and_heading(self, racechrono_accel_csv):
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(racechrono_accel_csv))
        assert "yaw_rate_dps" in df.columns
        assert "heading_deg" in df.columns
        assert "altitude_m" in df.columns

    def test_parse_controls_has_throttle_brake_steering(self, racechrono_controls_csv):
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(racechrono_controls_csv))
        assert "throttle_pct" in df.columns
        assert "brake_pct" in df.columns
        assert "steering_angle_deg" in df.columns

    def test_parse_preserves_data_values(self, racechrono_basic_csv):
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(racechrono_basic_csv))
        assert df["speed_mps"].iloc[1] == pytest.approx(18.3, rel=1e-4)
        assert df["lat_deg"].iloc[0] == pytest.approx(50.4372, rel=1e-6)

    def test_parse_calc_preference(self, calc_preference_csv):
        """When both raw and *calc columns exist, prefer *calc."""
        adapter = RaceChronoAdapter()
        df = adapter.parse(str(calc_preference_csv))
        # *calc values are 10.5 and 15.5; raw values are 10.0 and 15.0
        assert df["speed_mps"].iloc[0] == pytest.approx(10.5, rel=1e-4)
        assert df["speed_mps"].iloc[1] == pytest.approx(15.5, rel=1e-4)


# ---------------------------------------------------------------------------
# available_channels tests
# ---------------------------------------------------------------------------
class TestRaceChronoChannels:
    """Verify available_channels() after parsing."""

    def test_available_channels_basic(self, racechrono_basic_csv):
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_basic_csv))
        channels = adapter.available_channels()
        assert "time_s" in channels
        assert "speed_mps" in channels
        assert "lat_deg" in channels
        assert "lon_deg" in channels

    def test_available_channels_empty_before_parse(self):
        adapter = RaceChronoAdapter()
        channels = adapter.available_channels()
        assert channels == []

    def test_available_channels_with_accel(self, racechrono_accel_csv):
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_accel_csv))
        channels = adapter.available_channels()
        assert "accel_long_mps2" in channels
        assert "accel_lat_mps2" in channels
        assert "yaw_rate_dps" in channels
        assert "heading_deg" in channels


# ---------------------------------------------------------------------------
# data_tier tests
# ---------------------------------------------------------------------------
class TestRaceChronoDataTier:
    """Verify data_tier() using channel_registry.detect_data_tier."""

    def test_data_tier_basic_at_least_1(self, racechrono_basic_csv):
        """Basic RaceChrono CSV with time+speed+GPS should be tier >= 1."""
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_basic_csv))
        tier = adapter.data_tier()
        assert tier >= 1

    def test_data_tier_with_accel_at_least_2(self, racechrono_accel_csv):
        """RaceChrono CSV with accel columns should be tier >= 2."""
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_accel_csv))
        tier = adapter.data_tier()
        assert tier >= 2

    def test_data_tier_with_controls_at_least_3(self, racechrono_controls_csv):
        """RaceChrono CSV with throttle+brake+steering should be tier >= 3."""
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_controls_csv))
        tier = adapter.data_tier()
        assert tier >= 3


# ---------------------------------------------------------------------------
# metadata tests
# ---------------------------------------------------------------------------
class TestRaceChronoMetadata:
    """Verify metadata() returns parsed pre-header rows."""

    def test_metadata_contains_session(self, racechrono_basic_csv):
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_basic_csv))
        meta = adapter.metadata()
        assert isinstance(meta, dict)
        assert "session" in meta
        assert "Spa 2024" in meta["session"]

    def test_metadata_contains_track(self, racechrono_basic_csv):
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_basic_csv))
        meta = adapter.metadata()
        assert "track" in meta

    def test_metadata_empty_before_parse(self):
        adapter = RaceChronoAdapter()
        meta = adapter.metadata()
        assert meta == {}

    def test_metadata_from_accel_csv(self, racechrono_accel_csv):
        adapter = RaceChronoAdapter()
        adapter.parse(str(racechrono_accel_csv))
        meta = adapter.metadata()
        assert "session" in meta
        assert "Monza" in meta["session"]


# ---------------------------------------------------------------------------
# FORMAT_NAME test
# ---------------------------------------------------------------------------
class TestRaceChronoFormatName:
    """Verify FORMAT_NAME is set correctly."""

    def test_format_name(self):
        assert RaceChronoAdapter.FORMAT_NAME == "racechrono"
