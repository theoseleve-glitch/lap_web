"""Tests for the AiM .xrk adapter (libxrk-backed)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from telemetry_tool.adapters.aim_adapter import AiMAdapter

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.xrk"


def test_detect_xrk(tmp_path):
    p = tmp_path / "session.xrk"
    p.write_bytes(b"\x00" * 64)
    assert AiMAdapter.detect(str(p)) >= 0.8


def test_detect_rejects_csv(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("Time,Speed\n0,1\n", encoding="utf-8")
    assert AiMAdapter.detect(str(p)) == 0.0


def test_parse_xrk_boundary_mock(monkeypatch):
    # Mock libxrk so we test the canonical mapping without a real .xrk.
    import libxrk

    class _FakeTable:
        def to_pandas(self):
            return pd.DataFrame({
                "timecodes": [0, 100, 200],  # int64 milliseconds
                "GPS Latitude": [51.5, 51.5009, 51.5018],
                "GPS Longitude": [-0.1, -0.1, -0.1],
                "GPS Altitude": [10.0, 11.0, 12.0],
                "GPS_InlineAcc": [0.1, 0.2, 0.15],
                "GPS_LateralAcc": [0.0, 0.3, 0.25],
                "Engine RPM": [9000, 9500, 10000],
            })

    class _FakeLog:
        def get_channels_as_table(self):
            return _FakeTable()

    monkeypatch.setattr(libxrk, "aim_xrk", lambda *a, **k: _FakeLog())

    df = AiMAdapter().parse("whatever.xrk")
    assert {"time_s", "lat_deg", "lon_deg", "altitude_m", "distance_m",
            "speed_mps", "accel_long_mps2", "accel_lat_mps2", "rpm"} <= set(df.columns)
    assert len(df) == 3
    assert df["lat_deg"].iloc[0] == pytest.approx(51.5)
    assert df["rpm"].iloc[1] == pytest.approx(9500)
    # time_s must be in seconds (timecodes are ms, so 100ms -> 0.1s)
    assert df["time_s"].iloc[1] == pytest.approx(0.1)
    assert df["time_s"].iloc[0] == pytest.approx(0.0)


@pytest.mark.skipif(not _FIXTURE.exists(), reason="no sample .xrk vendored")
def test_parse_xrk_real():
    df = AiMAdapter().parse(str(_FIXTURE))
    assert {"time_s", "lat_deg", "lon_deg", "speed_mps", "distance_m"} <= set(df.columns)
    assert len(df) >= 2
    assert df["lat_deg"].abs().max() <= 90.0 and df["lon_deg"].abs().max() <= 180.0
    # speed_mps should be plausible racing values (0–120 m/s max)
    assert df["speed_mps"].max() <= 120.0
    assert df["speed_mps"].min() >= 0.0
