"""Tests for the NMEA 0183 adapter."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from telemetry_tool.adapters.nmea_adapter import NMEAAdapter

# RMC = position/speed/course; GGA = altitude. 5114.0000,N = 51.2333 deg.
_NMEA = textwrap.dedent("""\
    $GPGGA,120000.00,5114.0000,N,00010.0000,W,1,08,0.9,45.0,M,,,,*47
    $GPRMC,120000.00,A,5114.0000,N,00010.0000,W,10.000,90.0,010124,,,A*6A
    $GPGGA,120001.00,5114.0000,N,00010.0100,W,1,08,0.9,46.0,M,,,,*42
    $GPRMC,120001.00,A,5114.0000,N,00010.0100,W,12.000,90.0,010124,,,A*6C
    $GPGGA,120002.00,5114.0000,N,00010.0200,W,1,08,0.9,47.0,M,,,,*41
    $GPRMC,120002.00,A,5114.0000,N,00010.0200,W,14.000,90.0,010124,,,A*6F
""")

_NOT_NMEA = textwrap.dedent("""\
    Time (s),Speed (m/s),Lap #
    0.0,25.0,1
""")


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_detect_nmea(tmp_path):
    path = _write(tmp_path, "drive.nmea", _NMEA)
    assert NMEAAdapter.detect(path) >= 0.8


def test_detect_rejects_csv(tmp_path):
    path = _write(tmp_path, "session.txt", _NOT_NMEA)
    assert NMEAAdapter.detect(path) == 0.0


def test_parse_nmea_channels(tmp_path):
    path = _write(tmp_path, "drive.nmea", _NMEA)
    adapter = NMEAAdapter()
    df = adapter.parse(path)
    assert {"time_s", "lat_deg", "lon_deg", "speed_mps"} <= set(df.columns)
    assert len(df) == 3
    assert df["lat_deg"].iloc[0] == pytest.approx(51.2333, abs=1e-3)
    assert df["lon_deg"].iloc[0] == pytest.approx(-0.16667, abs=1e-3)
    # 10 knots -> ~5.144 m/s
    assert df["speed_mps"].iloc[0] == pytest.approx(5.144, abs=0.01)
    assert df["altitude_m"].iloc[0] == pytest.approx(45.0, abs=0.5)
    assert df["time_s"].iloc[0] == pytest.approx(0.0)
