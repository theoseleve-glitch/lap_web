"""Cross-format detection: every sample routes to exactly one adapter."""
from __future__ import annotations

import struct
import textwrap
from pathlib import Path

import pytest

from telemetry_tool.adapters import detect_format  # registers all adapters

_GPX = textwrap.dedent("""\
    <?xml version="1.0"?>
    <gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
      <trk><trkseg>
        <trkpt lat="51.5" lon="-0.1"><time>2024-01-01T00:00:00Z</time></trkpt>
        <trkpt lat="51.5009" lon="-0.1"><time>2024-01-01T00:00:01Z</time></trkpt>
      </trkseg></trk></gpx>
""")

_NMEA = textwrap.dedent("""\
    $GPRMC,120000.00,A,5114.0000,N,00010.0000,W,10.0,90.0,010124,,,A*6A
    $GPRMC,120001.00,A,5114.0000,N,00010.0100,W,12.0,90.0,010124,,,A*6C
""")

_RACEBOX = textwrap.dedent("""\
    UTC Time,Latitude,Longitude,Speed(km/h),Altitude(m),Heading
    2024-01-01T00:00:00Z,51.5,-0.1,36.0,10.0,90.0
    2024-01-01T00:00:01Z,51.5009,-0.1,40.0,11.0,90.0
""")

_TRACKADDICT = textwrap.dedent("""\
    # RaceRender Data: TrackAddict 4.3.5 on Android 9 (Mode: 0)
    "Time","UTC Time","Lap","Latitude","Longitude","Altitude (m)","Speed (Km/h)","Heading","Accel X","Accel Y","Accel Z"
    0.00,1700000000.0,0,51.5,-0.1,10.0,36.0,90.0,0.1,0.2,0.98
    0.10,1700000000.1,0,51.5,-0.0998,10.1,40.0,90.0,0.1,0.2,0.99
""")

_FIT_HEADER = struct.pack("<BBHI4sH", 14, 0x20, 0, 0, b".FIT", 0) + b"\x00" * 4


def _write(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("name,content,expected", [
    ("track.gpx", _GPX, "gpx"),
    ("drive.nmea", _NMEA, "nmea"),
    ("session.csv", _RACEBOX, "racebox_csv"),
    ("log.csv", _TRACKADDICT, "trackaddict"),
])
def test_detection_routes_correctly(tmp_path, name, content, expected):
    path = _write(tmp_path, name, content)
    cls, conf = detect_format(path)
    assert cls is not None, f"{name} matched no adapter"
    assert cls.FORMAT_NAME == expected
    assert conf >= 0.5
    # Unambiguous winner: no OTHER registered adapter scores as high as the winner.
    # (GenericCSVAdapter is a catch-all and may score up to 0.7 on a GPS CSV, so we
    #  assert strict-top-winner rather than "only one adapter >= 0.5".)
    from telemetry_tool.adapters.registry import _ADAPTERS
    contenders = [
        c.FORMAT_NAME for c in _ADAPTERS
        if c is not cls and c.detect(path) >= conf
    ]
    assert contenders == [], (
        f"{name}: {cls.FORMAT_NAME} (conf {conf}) is not the unambiguous winner; "
        f"also matched at >= conf: {contenders}"
    )


def test_fit_detection_routes(tmp_path):
    from telemetry_tool.adapters import detect_format
    p = tmp_path / "ride.fit"
    p.write_bytes(_FIT_HEADER)
    cls, conf = detect_format(str(p))
    assert cls is not None and cls.FORMAT_NAME == "fit" and conf >= 0.5
