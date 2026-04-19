"""Shared fixtures for adapter tests."""
from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def write_vbox_sample(path: Path) -> Path:
    """Write a minimal VBOX .vbo sample file and return its path."""
    content = """\
[header]
satellites
time
latitude
longitude
velocity knots
heading
height
vert vel
[column names]
sats time lat long velocity heading height vertvel
[data]
8 120000 3060000 -00060000 58.0 180.0 100.0 0.5
9 120100 3060010 -00060010 59.5 181.0 100.1 0.3
10 120200 3060020 -00060020 60.0 182.0 100.2 0.1
"""
    vbo = path / "sample.vbo"
    vbo.write_text(content)
    return vbo


def write_racebox_csv_sample(path: Path) -> Path:
    """Write a minimal RaceBox CSV sample and return its path."""
    content = """\
UTC Time,Latitude,Longitude,Speed(km/h),Altitude(m),Heading
2026-03-19T10:00:00.000Z,51.5074,-0.1278,80.5,30.0,180.0
2026-03-19T10:00:00.100Z,51.5075,-0.1279,82.0,30.1,181.0
2026-03-19T10:00:00.200Z,51.5076,-0.1280,83.5,30.2,182.0
"""
    csv = path / "racebox_sample.csv"
    csv.write_text(content)
    return csv


def write_qstarz_csv_sample(path: Path) -> Path:
    """Write a minimal Qstarz CSV sample and return its path."""
    content = """\
INDEX,RCR,DATE,TIME,LATITUDE N/S,LONGITUDE E/W,HEIGHT,SPEED,HEADING
1,T,2026/03/19,10:00:00.000,51.5074000N,000.1278000W,30.0,80.5,180.0
2,T,2026/03/19,10:00:00.100,51.5075000N,000.1279000W,30.1,82.0,181.0
3,T,2026/03/19,10:00:00.200,51.5076000N,000.1280000W,30.2,83.5,182.0
"""
    csv = path / "qstarz_sample.csv"
    csv.write_text(content)
    return csv


def write_racechrono_csv_sample(path: Path) -> Path:
    """Write a minimal RaceChrono CSV sample and return its path."""
    content = """\
Logged at 10 Hz
Time (s),Speed (m/s),Distance (m),Lap #,Latitude (deg),Longitude (deg)
0.0,10.0,0.0,1,51.5074,-0.1278
0.1,10.5,1.0,1,51.5075,-0.1279
0.2,11.0,2.1,1,51.5076,-0.1280
"""
    csv = path / "racechrono_sample.csv"
    csv.write_text(content)
    return csv
