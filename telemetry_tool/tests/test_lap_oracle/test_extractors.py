"""Tests for lap_oracle extractor modules."""
from __future__ import annotations

import json
import struct
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest

from telemetry_tool.lap_oracle.extractors.ac_files import (
    discover_ac_cars,
    parse_ac_car_data,
    parse_ac_ini,
)
from telemetry_tool.lap_oracle.extractors.acc_files import (
    discover_acc_setups,
    parse_acc_setup,
)
from telemetry_tool.lap_oracle.extractors.f1_zips import (
    _parse_path_metadata,
    process_f1_zip,
)
from telemetry_tool.lap_oracle.extractors.iracing_ibt import (
    extract_positions,
    extract_telemetry_channels,
)
from telemetry_tool.lap_oracle.extractors.lmu_files import (
    discover_lmu_vehicles,
    parse_lmu_hdv,
)


# =========================================================================
# AC INI parser
# =========================================================================

class TestParseAcIni:
    """Tests for parse_ac_ini."""

    def test_basic_sections(self):
        text = """
[BASIC]
totalmass=1340
; a comment
wheelbase=2.65

[ENGINE]
bhp=400
max_rpm=7200
"""
        result = parse_ac_ini(text)
        assert "BASIC" in result
        assert result["BASIC"]["totalmass"] == "1340"
        assert result["BASIC"]["wheelbase"] == "2.65"
        assert result["ENGINE"]["bhp"] == "400"

    def test_inline_comments(self):
        text = "[SECTION]\nkey=value ; comment\nkey2=10 // another"
        result = parse_ac_ini(text)
        assert result["SECTION"]["key"] == "value"
        assert result["SECTION"]["key2"] == "10"

    def test_empty_input(self):
        assert parse_ac_ini("") == {"__root__": {}}

    def test_slash_comments_skipped(self):
        text = "// full line comment\n[S]\nk=v"
        result = parse_ac_ini(text)
        assert result["S"]["k"] == "v"

    def test_semicolon_comments_skipped(self):
        text = "; full line comment\n[S]\nk=v"
        result = parse_ac_ini(text)
        assert result["S"]["k"] == "v"

    def test_root_keys(self):
        text = "bare_key=42\n[SECTION]\nother=1"
        result = parse_ac_ini(text)
        assert result["__root__"]["bare_key"] == "42"

    def test_whitespace_handling(self):
        text = "[  SPACES  ]\n  key  =  value  "
        result = parse_ac_ini(text)
        assert "SPACES" in result
        assert result["SPACES"]["key"] == "value"


# =========================================================================
# AC car data extraction
# =========================================================================

class TestAcCarData:
    """Tests for parse_ac_car_data with synthetic data."""

    def test_parse_from_plain_data_dir(self, tmp_path):
        """Car folder with plain data/ subfolder."""
        car_dir = tmp_path / "test_car"
        data_dir = car_dir / "data"
        data_dir.mkdir(parents=True)

        (data_dir / "car.ini").write_text(
            "[BASIC]\ntotalmass=1200\n[CAR]\nwheelbase=2.5\ncg_height=0.32\n"
        )
        result = parse_ac_car_data(car_dir)
        assert result is not None
        assert result["mass_kg"] == 1200.0
        assert result["car_name"] == "test_car"
        assert result["sim"] == "ac"

    def test_parse_from_acd_zip(self, tmp_path):
        """Car folder with data.acd (ZIP) containing car.ini + drivetrain.ini."""
        car_dir = tmp_path / "zip_car"
        car_dir.mkdir()

        acd_path = car_dir / "data.acd"
        with zipfile.ZipFile(str(acd_path), "w") as zf:
            zf.writestr(
                "car.ini",
                "[BASIC]\ntotalmass=980\n",
            )
            zf.writestr(
                "drivetrain.ini",
                "[ENGINE]\nbhp=150\n",
            )
        result = parse_ac_car_data(car_dir)
        assert result is not None
        assert result["mass_kg"] == 980.0
        assert abs(result["max_power_w"] - 150 * 745.7) < 1.0

    def test_returns_none_for_missing_data(self, tmp_path):
        """No data.acd or data/ folder."""
        car_dir = tmp_path / "empty_car"
        car_dir.mkdir()
        assert parse_ac_car_data(car_dir) is None

    def test_returns_none_if_no_mass(self, tmp_path):
        """car.ini exists but has no totalmass."""
        car_dir = tmp_path / "no_mass"
        data_dir = car_dir / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "car.ini").write_text("[ENGINE]\nbhp=200\n")
        assert parse_ac_car_data(car_dir) is None


class TestDiscoverAcCars:
    """discover_ac_cars should not crash even if paths are missing."""

    def test_does_not_crash(self):
        # May return empty list if AC not installed
        result = discover_ac_cars()
        assert isinstance(result, list)


# =========================================================================
# iRacing .ibt extraction
# =========================================================================

def _make_ibt_file(
    tmp_path: Path,
    lat_values: list[float],
    lon_values: list[float],
) -> Path:
    """Create a minimal synthetic .ibt file."""
    num_samples = len(lat_values)
    num_vars = 2  # Lat + Lon
    var_header_offset = 144  # Right after disk header (padded to 112 + 32)
    # We'll use a simpler layout: 112 disk header, then var headers, then
    # session info, then data

    # Session info (empty)
    session_info = b"---\n"
    session_info_len = len(session_info)

    # Pad to next boundary
    var_headers_size = num_vars * 144
    session_info_offset = 112 + var_headers_size  # actually at var_header_offset=144
    # Let's keep it cleaner: disk_header=112, var_headers start at 144

    # Actually let's just pack it properly:
    # Disk header: 112 bytes
    # Var headers: at offset 144, 2 * 144 = 288 bytes (end at 432)
    # Session info: at offset 432, 4 bytes
    # Data: at offset 436

    var_hdr_off = 144
    session_info_off = var_hdr_off + num_vars * 144
    session_info_len_padded = len(session_info)
    data_start = session_info_off + session_info_len_padded

    # buf_len = 8 (Lat double) + 8 (Lon double) = 16
    buf_len = 16
    lat_offset = 0
    lon_offset = 8

    # Build disk header (112 bytes)
    disk_hdr = bytearray(112)
    struct.pack_into("<i", disk_hdr, 0, 2)       # version
    struct.pack_into("<i", disk_hdr, 4, 0)       # status
    struct.pack_into("<i", disk_hdr, 8, 60)      # tick_rate
    struct.pack_into("<i", disk_hdr, 16, session_info_len_padded)
    struct.pack_into("<i", disk_hdr, 20, session_info_off)
    struct.pack_into("<i", disk_hdr, 24, num_vars)
    struct.pack_into("<i", disk_hdr, 28, var_hdr_off)
    struct.pack_into("<i", disk_hdr, 32, 1)      # num_buf
    struct.pack_into("<i", disk_hdr, 36, buf_len)

    # Build var headers
    def _make_var_header(
        name: str, var_type: int, offset: int, count: int = 1,
    ) -> bytes:
        hdr = bytearray(144)
        struct.pack_into("<i", hdr, 0, var_type)
        struct.pack_into("<i", hdr, 4, offset)
        struct.pack_into("<i", hdr, 8, count)
        name_bytes = name.encode("ascii")[:32]
        hdr[16 : 16 + len(name_bytes)] = name_bytes
        return bytes(hdr)

    var_hdrs = (
        _make_var_header("Lat", 5, lat_offset)
        + _make_var_header("Lon", 5, lon_offset)
    )

    # Pad between disk header (112 bytes) and var headers (at 144)
    padding = b"\x00" * (var_hdr_off - 112)

    # Data rows
    data_rows = bytearray()
    for lat, lon in zip(lat_values, lon_values):
        data_rows += struct.pack("<d", lat)
        data_rows += struct.pack("<d", lon)

    ibt_path = tmp_path / "test.ibt"
    ibt_path.write_bytes(
        bytes(disk_hdr) + padding + var_hdrs + session_info + bytes(data_rows)
    )
    return ibt_path


class TestIracingIbt:
    """Tests for iRacing .ibt extraction."""

    def test_extract_positions_synthetic(self, tmp_path):
        """Round-trip: write synthetic ibt, read back positions."""
        n = 100
        lats = [36.5 + i * 0.0001 for i in range(n)]
        lons = [-121.7 + i * 0.0001 for i in range(n)]
        ibt_path = _make_ibt_file(tmp_path, lats, lons)

        positions = extract_positions(ibt_path)
        assert positions is not None
        assert positions.shape == (n, 2)
        np.testing.assert_allclose(positions[0, 0], 36.5, atol=1e-6)
        np.testing.assert_allclose(positions[0, 1], -121.7, atol=1e-6)

    def test_extract_positions_drops_zeros(self, tmp_path):
        """Leading zero-position rows should be dropped."""
        lats = [0.0, 0.0, 36.5, 36.501, 36.502] + [36.5 + i * 0.001 for i in range(20)]
        lons = [0.0, 0.0, -121.7, -121.701, -121.702] + [-121.7 + i * 0.001 for i in range(20)]
        ibt_path = _make_ibt_file(tmp_path, lats, lons)

        positions = extract_positions(ibt_path)
        assert positions is not None
        # The 2 zero rows should be dropped
        assert positions.shape[0] == len(lats) - 2

    def test_extract_positions_missing_file(self, tmp_path):
        fake = tmp_path / "nonexistent.ibt"
        assert extract_positions(fake) is None

    def test_extract_channels_synthetic(self, tmp_path):
        """extract_telemetry_channels with Lat/Lon channels."""
        n = 50
        lats = [36.5 + i * 0.0001 for i in range(n)]
        lons = [-121.7 + i * 0.0001 for i in range(n)]
        ibt_path = _make_ibt_file(tmp_path, lats, lons)

        result = extract_telemetry_channels(ibt_path, ["Lat", "Lon"])
        assert result is not None
        assert "Lat" in result
        assert "Lon" in result
        assert len(result["Lat"]) == n

    def test_extract_channels_missing_channel(self, tmp_path):
        """Requesting a non-existent channel should omit it."""
        lats = [36.5 + i * 0.001 for i in range(30)]
        lons = [-121.7 + i * 0.001 for i in range(30)]
        ibt_path = _make_ibt_file(tmp_path, lats, lons)

        result = extract_telemetry_channels(ibt_path, ["Speed", "Lat"])
        assert result is not None
        assert "Lat" in result
        assert "Speed" not in result


# =========================================================================
# F1 ZIP extraction
# =========================================================================

class TestF1Zips:
    """Tests for F1 zip extraction."""

    def test_process_f1_zip_synthetic(self, tmp_path):
        """Create a minimal F1-format ZIP and extract."""
        zip_path = tmp_path / "2099-main.zip"
        n = 50
        tel_data = {
            "tel": {
                "time": [float(i) * 0.1 for i in range(n)],
                "speed": [float(200 + i) for i in range(n)],
                "throttle": [80.0] * n,
                "brake": [0] * n,
                "acc_x": [0.1] * n,
                "acc_y": [0.2] * n,
                "x": [float(i * 10) for i in range(n)],
                "y": [float(i * 5) for i in range(n)],
                "dataKey": "2099-Test GP-Race-HAM-1",
            }
        }
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr(
                "2099-main/Test GP/Race/HAM/1_tel.json",
                json.dumps(tel_data),
            )

        laps = process_f1_zip(zip_path)
        assert len(laps) == 1
        lap = laps[0]
        assert lap["gp_name"] == "Test GP"
        assert lap["driver"] == "HAM"
        assert lap["session"] == "Race"
        assert lap["lap_number"] == 1
        # Speed converted from km/h to m/s
        assert abs(lap["speed_mps"][0] - 200.0 / 3.6) < 0.01
        # Throttle converted from 0-100 to 0-1
        assert abs(lap["throttle"][0] - 0.8) < 0.01

    def test_process_f1_zip_max_laps(self, tmp_path):
        """max_laps parameter limits extraction."""
        zip_path = tmp_path / "limited.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            for i in range(10):
                tel = {
                    "tel": {
                        "time": list(range(20)),
                        "speed": [100.0] * 20,
                        "x": list(range(20)),
                        "y": list(range(20)),
                        "dataKey": f"test-{i}",
                    }
                }
                zf.writestr(
                    f"yr-main/GP/Race/DRV/{i}_tel.json",
                    json.dumps(tel),
                )
        laps = process_f1_zip(zip_path, max_laps=3)
        assert len(laps) == 3

    def test_process_f1_zip_missing(self, tmp_path):
        fake = tmp_path / "no_such.zip"
        assert process_f1_zip(fake) == []

    def test_parse_path_metadata(self):
        gp, session, driver, lap = _parse_path_metadata(
            "2022-main/Abu Dhabi Grand Prix/Practice 1/ALB/10_tel.json"
        )
        assert gp == "Abu Dhabi Grand Prix"
        assert session == "Practice 1"
        assert driver == "ALB"
        assert lap == 10


# =========================================================================
# ACC files
# =========================================================================

class TestAccFiles:
    """Tests for ACC setup extraction."""

    def test_parse_acc_setup_synthetic(self, tmp_path):
        """Parse a minimal ACC-format setup JSON."""
        setup_dir = tmp_path / "Setups" / "my_car" / "my_track"
        setup_dir.mkdir(parents=True)
        setup_data = {
            "basicSetup": {
                "tyres": {
                    "tyrePressure": [260, 255, 258, 253],
                },
            },
            "advancedSetup": {
                "mechanicalBalance": {"brakeBias": 58},
                "aeroBalance": {"rideHeight": [50, 60]},
            },
        }
        setup_path = setup_dir / "default.json"
        setup_path.write_text(json.dumps(setup_data))

        result = parse_acc_setup(setup_path)
        assert result is not None
        assert result["car_name"] == "my_car"
        assert result["track_name"] == "my_track"
        assert result["sim"] == "acc"
        assert result["tyre_pressures"] == [26.0, 25.5, 25.8, 25.3]
        assert result["brake_bias_raw"] == 58
        assert result["ride_height_front"] == 50
        assert result["ride_height_rear"] == 60

    def test_parse_acc_setup_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json {{{")
        assert parse_acc_setup(bad_file) is None

    def test_discover_acc_setups_does_not_crash(self):
        # May return empty if ACC not installed
        result = discover_acc_setups()
        assert isinstance(result, list)


# =========================================================================
# LMU files
# =========================================================================

class TestLmuFiles:
    """Tests for LMU .hdv extraction."""

    def test_parse_hdv_synthetic(self, tmp_path):
        hdv_text = """\
[GENERAL]
Mass=1200
Category=LMH

[ENGINE]
RPMTorque=(3000, 400, 0.9)

[FRONTWING]
FWSetting=5.0
"""
        hdv_path = tmp_path / "test_car.hdv"
        hdv_path.write_text(hdv_text)

        result = parse_lmu_hdv(hdv_path)
        assert result is not None
        assert result["mass_kg"] == 1200.0
        assert result["car_name"] == "test_car"
        assert result["sim"] == "lmu"
        assert result["category"] == "LMH"

    def test_parse_hdv_no_mass(self, tmp_path):
        hdv_path = tmp_path / "no_mass.hdv"
        hdv_path.write_text("[ENGINE]\nRPMTorque=something\n")
        assert parse_lmu_hdv(hdv_path) is None

    def test_parse_hdv_missing_file(self, tmp_path):
        fake = tmp_path / "nope.hdv"
        assert parse_lmu_hdv(fake) is None

    def test_discover_lmu_vehicles_does_not_crash(self):
        result = discover_lmu_vehicles()
        assert isinstance(result, list)
