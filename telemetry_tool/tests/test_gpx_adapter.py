"""Tests for the GPX adapter."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from telemetry_tool.adapters.gpx_adapter import GPXAdapter

_GPX = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
      <trk><name>lap</name><trkseg>
        <trkpt lat="51.5000000" lon="-0.1000000"><ele>10.0</ele><time>2024-01-01T00:00:00Z</time></trkpt>
        <trkpt lat="51.5009000" lon="-0.1000000"><ele>11.0</ele><time>2024-01-01T00:00:01Z</time></trkpt>
        <trkpt lat="51.5018000" lon="-0.1000000"><ele>12.0</ele><time>2024-01-01T00:00:02Z</time></trkpt>
      </trkseg></trk>
    </gpx>
""")

_NOT_GPX = textwrap.dedent("""\
    Time (s),Speed (m/s),Lap #
    0.0,25.0,1
""")


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_detect_gpx(tmp_path):
    path = _write(tmp_path, "track.gpx", _GPX)
    assert GPXAdapter.detect(path) >= 0.9


def test_detect_rejects_csv(tmp_path):
    path = _write(tmp_path, "session.csv", _NOT_GPX)
    assert GPXAdapter.detect(path) == 0.0


def test_parse_gpx_channels(tmp_path):
    path = _write(tmp_path, "track.gpx", _GPX)
    adapter = GPXAdapter()
    df = adapter.parse(path)
    assert {"time_s", "lat_deg", "lon_deg", "altitude_m",
            "speed_mps", "distance_m", "heading_deg"} <= set(df.columns)
    assert len(df) == 3
    assert df["lat_deg"].iloc[0] == pytest.approx(51.5, abs=1e-4)
    assert df["altitude_m"].iloc[-1] == pytest.approx(12.0)
    # ~100 m/s north over 1 s steps (0.0009 deg lat ~= 100 m)
    assert df["speed_mps"].iloc[-1] == pytest.approx(100.0, abs=5.0)
    assert "gpx" == adapter.metadata()["format"]
    assert adapter.data_tier() >= 1
