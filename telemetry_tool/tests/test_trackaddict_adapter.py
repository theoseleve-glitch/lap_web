"""Tests for the TrackAddict / RaceRender CSV adapter."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from telemetry_tool.adapters.trackaddict_adapter import TrackAddictAdapter

_TA = textwrap.dedent("""\
    # RaceRender Data: TrackAddict 4.3.5 on Android 9 [samsung SM-N960F] (Mode: 0)
    # GPS: Android; Mode: Android
    "Time","UTC Time","Lap","Latitude","Longitude","Altitude (m)","Speed (Km/h)","Heading","Accuracy (m)","Accel X","Accel Y","Accel Z","Brake (calculated)"
    0.00,1700000000.0,0,51.5000000,-0.1000000,10.0,36.0,90.0,3.0,0.10,0.20,0.98,0.0
    0.10,1700000000.1,0,51.5000000,-0.0998500,10.1,40.0,90.0,3.0,0.12,0.22,0.99,0.0
    0.20,1700000000.2,1,51.5000000,-0.0997000,10.2,44.0,90.0,3.0,0.11,0.25,1.00,0.1
""")

_NOT_TA = textwrap.dedent("""\
    Time (s),Speed (m/s),Lap #
    0.0,25.0,1
""")


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_detect_trackaddict(tmp_path):
    assert TrackAddictAdapter.detect(_write(tmp_path, "log.csv", _TA)) >= 0.9


def test_detect_rejects_plain_csv(tmp_path):
    assert TrackAddictAdapter.detect(_write(tmp_path, "s.csv", _NOT_TA)) == 0.0


def test_parse_trackaddict_channels(tmp_path):
    adapter = TrackAddictAdapter()
    df = adapter.parse(_write(tmp_path, "log.csv", _TA))
    assert {"time_s", "lat_deg", "lon_deg", "altitude_m", "speed_mps",
            "heading_deg", "lap_number", "distance_m",
            "accel_lat_mps2", "accel_long_mps2", "accel_vert_mps2"} <= set(df.columns)
    assert len(df) == 3
    assert df["speed_mps"].iloc[0] == pytest.approx(10.0, abs=0.01)
    assert df["accel_vert_mps2"].iloc[0] == pytest.approx(0.98 * 9.80665, abs=0.01)
    assert "UTC Time" not in df.columns
    assert "Brake (calculated)" not in df.columns
    assert adapter.metadata()["format"] == "trackaddict"
