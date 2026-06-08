"""Tests for the Garmin FIT adapter."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from telemetry_tool.adapters.fit_adapter import FITAdapter

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_activity.fit"


def test_detect_fit_by_magic(tmp_path):
    header = struct.pack("<BBHI4sH", 14, 0x20, 0, 0, b".FIT", 0)
    p = tmp_path / "ride.fit"
    p.write_bytes(header + b"\x00" * 4)
    assert FITAdapter.detect(str(p)) >= 0.9


def test_detect_rejects_non_fit(tmp_path):
    p = tmp_path / "not.fit"
    p.write_bytes(b"\x0e\x20\x00\x00\x00\x00\x00\x00JUNKxx")
    assert FITAdapter.detect(str(p)) == 0.0


def test_parse_fit_channels():
    assert _FIXTURE.exists(), "vendored sample_activity.fit missing"
    adapter = FITAdapter()
    df = adapter.parse(str(_FIXTURE))
    assert {"time_s", "lat_deg", "lon_deg", "speed_mps", "distance_m"} <= set(df.columns)
    assert len(df) >= 2
    assert df["lat_deg"].abs().max() <= 90.0
    assert df["lon_deg"].abs().max() <= 180.0
    assert (df["speed_mps"] >= 0).all()
    assert df["time_s"].iloc[0] == pytest.approx(0.0, abs=1e-6)

    # Spot-checks derived from inspecting the vendored fixture:
    # garmin-edge-820-bike.fit — 15 GPS rows.
    # First GPS record: position_lat=446375435 sc, position_long=-1456338541 sc,
    # enhanced_speed=6.951 m/s, heart_rate=101 bpm.
    assert len(df) == 15
    assert df["lat_deg"].iloc[0] == pytest.approx(37.4148, abs=1e-4)
    assert df["lon_deg"].iloc[0] == pytest.approx(-122.0689, abs=1e-4)
    assert df["speed_mps"].iloc[0] == pytest.approx(6.951, abs=1e-3)

    # File has heart_rate — column must be present.
    assert "heart_rate_bpm" in df.columns
    assert df["heart_rate_bpm"].iloc[0] == pytest.approx(101.0, abs=0.5)
