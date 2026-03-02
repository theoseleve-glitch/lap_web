"""Integration tests: adapter registry wired into the pipeline ingest stage."""

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

from telemetry_tool.adapters import parse_file, detect_format


# ---------------------------------------------------------------------------
# Fixtures — minimal CSV samples for each adapter format
# ---------------------------------------------------------------------------

_IRACING_CSV = textwrap.dedent("""\
    Lap,LapDist,Speed,Throttle,Brake,Gear,RPM,SteeringWheelAngle,Lat,Lon,Alt,LatAccel,LonAccel,YawRate
    1,0.0,0.0,0.0,0.0,1,800,-0.5,45.123,-73.456,100.0,0.0,0.0,0.0
    1,10.5,22.3,100.0,0.0,2,4500,2.1,45.124,-73.457,100.1,0.3,5.2,1.2
""")

_ACC_CSV = textwrap.dedent("""\
    speedKmh,gas,brake,steerAngle,rpms,gear
    120.5,0.8,0.0,5.2,6500,3
    130.0,1.0,0.0,-2.1,7200,3
""")

_MOTEC_CSV = textwrap.dedent("""\
    Beacon,Engine RPM,Ground Speed,Throttle Pos,Brake Pos,Gear,Steering Angle
    0,6500,120.5,80.0,0.0,3,5.2
    1,7200,130.0,100.0,0.0,3,-2.1
""")

_RACECHRONO_CSV = textwrap.dedent("""\
    RaceChrono Pro v7.3 export
    Session: Test 2024
    ,
    Time (s), Lap #, Distance (m), Speed (m/s), Latitude (deg), Longitude (deg)
    0.0,1,0.0,25.0,50.4372,6.0253
    0.1,1,2.5,28.0,50.4373,6.0254
""")

_GENERIC_TELEMETRY_CSV = textwrap.dedent("""\
    Timestamp_s,Vehicle Speed,Throttle Position,Brake Pressure,Altitude
    0.0,25.0,80.0,0.0,150.0
    1.0,28.0,100.0,0.0,152.0
""")


@pytest.fixture
def iracing_csv(tmp_path) -> Path:
    p = tmp_path / "iracing_session.csv"
    p.write_text(_IRACING_CSV, encoding="utf-8")
    return p


@pytest.fixture
def acc_csv(tmp_path) -> Path:
    p = tmp_path / "acc_session.csv"
    p.write_text(_ACC_CSV, encoding="utf-8")
    return p


@pytest.fixture
def motec_csv(tmp_path) -> Path:
    p = tmp_path / "motec_session.csv"
    p.write_text(_MOTEC_CSV, encoding="utf-8")
    return p


@pytest.fixture
def racechrono_csv(tmp_path) -> Path:
    p = tmp_path / "racechrono_session.csv"
    p.write_text(_RACECHRONO_CSV, encoding="utf-8")
    return p


@pytest.fixture
def generic_csv(tmp_path) -> Path:
    p = tmp_path / "generic_session.csv"
    p.write_text(_GENERIC_TELEMETRY_CSV, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test: parse_file routes to the correct adapter
# ---------------------------------------------------------------------------
class TestAdapterRouting:
    """Verify that parse_file auto-detects the correct format."""

    def test_iracing_detected(self, iracing_csv):
        df, adapter = parse_file(str(iracing_csv))
        assert adapter.FORMAT_NAME == "iracing"
        assert isinstance(df, pd.DataFrame)
        assert "throttle_pct" in df.columns

    def test_acc_detected(self, acc_csv):
        df, adapter = parse_file(str(acc_csv))
        assert adapter.FORMAT_NAME == "acc"
        assert "speed_mps" in df.columns

    def test_motec_detected(self, motec_csv):
        df, adapter = parse_file(str(motec_csv))
        assert adapter.FORMAT_NAME == "motec"
        assert "rpm" in df.columns

    def test_racechrono_detected(self, racechrono_csv):
        df, adapter = parse_file(str(racechrono_csv))
        assert adapter.FORMAT_NAME == "racechrono"
        assert "speed_mps" in df.columns

    def test_generic_fallback(self, generic_csv):
        df, adapter = parse_file(str(generic_csv))
        assert adapter.FORMAT_NAME == "generic_csv"
        assert "speed_mps" in df.columns

    def test_unknown_format_raises(self, tmp_path):
        f = tmp_path / "garbage.csv"
        f.write_text("color,fruit\nred,apple\nblue,banana\n", encoding="utf-8")
        with pytest.raises(ValueError, match="No adapter matched"):
            parse_file(str(f))


# ---------------------------------------------------------------------------
# Test: adapter metadata enrichment
# ---------------------------------------------------------------------------
class TestAdapterMetadata:
    """Verify adapters produce metadata, channels, and data tier."""

    def test_iracing_channels_and_tier(self, iracing_csv):
        df, adapter = parse_file(str(iracing_csv))
        channels = adapter.available_channels()
        assert len(channels) >= 5
        assert adapter.data_tier() >= 1

    def test_acc_metadata(self, acc_csv):
        df, adapter = parse_file(str(acc_csv))
        meta = adapter.metadata()
        assert meta["format"] == "acc"
        assert "sample_count" in meta

    def test_motec_metadata(self, motec_csv):
        df, adapter = parse_file(str(motec_csv))
        meta = adapter.metadata()
        assert meta["format"] == "motec"

    def test_generic_data_tier(self, generic_csv):
        df, adapter = parse_file(str(generic_csv))
        assert adapter.data_tier() >= 1


# ---------------------------------------------------------------------------
# Test: detect_format confidence ordering
# ---------------------------------------------------------------------------
class TestDetectFormatConfidence:
    """Verify format-specific adapters out-score the generic adapter."""

    def test_iracing_beats_generic(self, iracing_csv):
        from telemetry_tool.adapters.iracing_adapter import IRacingAdapter
        from telemetry_tool.adapters.generic_csv_adapter import GenericCSVAdapter

        iracing_conf = IRacingAdapter.detect(str(iracing_csv))
        generic_conf = GenericCSVAdapter.detect(str(iracing_csv))
        assert iracing_conf > generic_conf

    def test_acc_beats_generic(self, acc_csv):
        from telemetry_tool.adapters.acc_adapter import ACCAdapter
        from telemetry_tool.adapters.generic_csv_adapter import GenericCSVAdapter

        acc_conf = ACCAdapter.detect(str(acc_csv))
        generic_conf = GenericCSVAdapter.detect(str(acc_csv))
        assert acc_conf > generic_conf

    def test_motec_beats_generic(self, motec_csv):
        from telemetry_tool.adapters.motec_adapter import MoTeCAdapter
        from telemetry_tool.adapters.generic_csv_adapter import GenericCSVAdapter

        motec_conf = MoTeCAdapter.detect(str(motec_csv))
        generic_conf = GenericCSVAdapter.detect(str(motec_csv))
        assert motec_conf > generic_conf
