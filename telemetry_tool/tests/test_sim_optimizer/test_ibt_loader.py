"""Tests for the ibt_loader module — .ibt binary → irsdk__ DataFrame.

Uses synthetic .ibt binary files to test header parsing, channel extraction,
and error handling without needing real iRacing telemetry files.
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.sim_optimizer.ingest.ibt_loader import (
    _parse_header,
    _parse_var_headers,
    load_ibt,
    load_ibt_with_metadata,
)


# ---------------------------------------------------------------------------
# Helpers: synthetic .ibt file builder
# ---------------------------------------------------------------------------

def _build_var_header(
    name: str,
    var_type: int,
    offset: int,
    count: int = 1,
    desc: str = "",
    unit: str = "",
) -> bytes:
    """Build a 144-byte variable header."""
    buf = bytearray(144)
    struct.pack_into("<i", buf, 0, var_type)      # type
    struct.pack_into("<i", buf, 4, offset)         # offset within row
    struct.pack_into("<i", buf, 8, count)          # count
    name_bytes = name.encode("ascii")[:31]
    buf[16:16 + len(name_bytes)] = name_bytes
    desc_bytes = desc.encode("ascii")[:63]
    buf[48:48 + len(desc_bytes)] = desc_bytes
    unit_bytes = unit.encode("ascii")[:31]
    buf[112:112 + len(unit_bytes)] = unit_bytes
    return bytes(buf)


def _build_ibt_file(
    vars_spec: list[tuple[str, int, int]],  # (name, type_code, count)
    n_samples: int = 100,
    tick_rate: int = 60,
    session_info: str = "---\nDriverInfo:\n  Drivers:\n",
) -> bytes:
    """Build a minimal .ibt binary file.

    vars_spec: list of (name, type_code, count) tuples.
    Returns the complete file as bytes.
    """
    type_sizes = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}

    # Compute row layout
    offsets = []
    current_offset = 0
    for name, vtype, count in vars_spec:
        offsets.append(current_offset)
        current_offset += type_sizes[vtype] * count
    buf_len = current_offset

    # Header (112 bytes)
    num_vars = len(vars_spec)
    var_header_offset = 112
    session_info_bytes = session_info.encode("utf-8") + b"\x00"
    session_info_offset = var_header_offset + 144 * num_vars
    session_info_len = len(session_info_bytes)
    data_start = session_info_offset + session_info_len

    header = bytearray(112)
    struct.pack_into("<i", header, 0, 2)                      # version
    struct.pack_into("<i", header, 4, 0)                      # status
    struct.pack_into("<i", header, 8, tick_rate)               # tick_rate
    struct.pack_into("<i", header, 12, 0)                      # session_info_update
    struct.pack_into("<i", header, 16, session_info_len)       # session_info_len
    struct.pack_into("<i", header, 20, session_info_offset)    # session_info_offset
    struct.pack_into("<i", header, 24, num_vars)               # num_vars
    struct.pack_into("<i", header, 28, var_header_offset)      # var_header_offset
    struct.pack_into("<i", header, 32, 1)                      # num_bufs
    struct.pack_into("<i", header, 36, buf_len)                # buf_len

    # Var headers
    var_headers = b""
    for i, (name, vtype, count) in enumerate(vars_spec):
        var_headers += _build_var_header(
            name, vtype, offsets[i], count,
            desc=f"Test {name}", unit="",
        )

    # Session info
    # Data rows
    rng = np.random.default_rng(42)
    data_rows = bytearray()
    for row_idx in range(n_samples):
        row = bytearray(buf_len)
        for i, (name, vtype, count) in enumerate(vars_spec):
            off = offsets[i]
            for elem in range(count):
                if vtype == 4:  # float32
                    val = float(row_idx * 0.1 + elem + rng.normal(0, 0.01))
                    struct.pack_into("<f", row, off + elem * 4, val)
                elif vtype == 5:  # float64
                    val = float(row_idx * 0.1 + elem + rng.normal(0, 0.01))
                    struct.pack_into("<d", row, off + elem * 8, val)
                elif vtype == 2:  # int32
                    val = int(row_idx + elem)
                    struct.pack_into("<i", row, off + elem * 4, val)
                elif vtype == 3:  # uint32 / bitfield
                    struct.pack_into("<I", row, off + elem * 4, row_idx)
                elif vtype == 1:  # bool/char
                    row[off + elem] = row_idx % 2
        data_rows.extend(row)

    return bytes(header) + var_headers + session_info_bytes + bytes(data_rows)


@pytest.fixture
def simple_ibt(tmp_path: Path) -> Path:
    """Create a simple .ibt file with Speed, Throttle, Brake, Gear, Lat, Lon."""
    vars_spec = [
        ("Speed", 4, 1),
        ("Throttle", 4, 1),
        ("Brake", 4, 1),
        ("Gear", 2, 1),
        ("Lat", 5, 1),
        ("Lon", 5, 1),
        ("LapDist", 4, 1),
        ("Lap", 2, 1),
        ("SessionTime", 5, 1),
        ("LatAccel", 4, 1),
        ("LongAccel", 4, 1),
        ("SteeringWheelAngle", 4, 1),
        ("RPM", 4, 1),
    ]
    data = _build_ibt_file(vars_spec, n_samples=200, tick_rate=60)
    path = tmp_path / "test_session.ibt"
    path.write_bytes(data)
    return path


@pytest.fixture
def array_channel_ibt(tmp_path: Path) -> Path:
    """Create an .ibt file with an array channel (count > 1)."""
    vars_spec = [
        ("Speed", 4, 1),
        ("LatAccel_ST", 4, 6),  # 360 Hz sub-samples
        ("Throttle", 4, 1),
    ]
    data = _build_ibt_file(vars_spec, n_samples=50)
    path = tmp_path / "array_session.ibt"
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseHeader:
    def test_valid_header(self, simple_ibt):
        data = simple_ibt.read_bytes()
        hdr = _parse_header(data[:112])
        assert hdr is not None
        assert hdr["version"] == 2
        assert hdr["tick_rate"] == 60
        assert hdr["num_vars"] == 13

    def test_too_short(self):
        assert _parse_header(b"\x00" * 50) is None

    def test_wrong_version(self):
        data = bytearray(112)
        struct.pack_into("<i", data, 0, 99)
        assert _parse_header(bytes(data)) is None


class TestParseVarHeaders:
    def test_reads_all_vars(self, simple_ibt):
        data = simple_ibt.read_bytes()
        hdr = _parse_header(data[:112])
        var_headers = _parse_var_headers(data, hdr)
        assert len(var_headers) == 13
        names = {vh["name"] for vh in var_headers}
        assert "Speed" in names
        assert "Throttle" in names
        assert "Lat" in names


class TestLoadIbt:
    def test_loads_all_channels(self, simple_ibt):
        df = load_ibt(simple_ibt)
        assert df is not None
        assert len(df) == 200
        assert "irsdk__Speed" in df.columns
        assert "irsdk__Throttle" in df.columns
        assert "irsdk__Brake" in df.columns
        assert "irsdk__Lat" in df.columns
        assert "irsdk__Lon" in df.columns

    def test_columns_have_irsdk_prefix(self, simple_ibt):
        df = load_ibt(simple_ibt)
        for col in df.columns:
            assert col.startswith("irsdk__"), f"Column {col} missing irsdk__ prefix"

    def test_channel_filter(self, simple_ibt):
        df = load_ibt(simple_ibt, channels=["Speed", "Brake"])
        assert df is not None
        assert "irsdk__Speed" in df.columns
        assert "irsdk__Brake" in df.columns
        assert "irsdk__Throttle" not in df.columns

    def test_array_channels_expanded(self, array_channel_ibt):
        df = load_ibt(array_channel_ibt)
        assert df is not None
        # LatAccel_ST has count=6, so should expand to __0 through __5
        for i in range(6):
            assert f"irsdk__LatAccel_ST__{i}" in df.columns

    def test_nonexistent_file(self, tmp_path):
        df = load_ibt(tmp_path / "nonexistent.ibt")
        assert df is None

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.ibt"
        path.write_bytes(b"")
        df = load_ibt(path)
        assert df is None

    def test_too_few_samples(self, tmp_path):
        vars_spec = [("Speed", 4, 1)]
        data = _build_ibt_file(vars_spec, n_samples=5)
        path = tmp_path / "tiny.ibt"
        path.write_bytes(data)
        df = load_ibt(path)
        assert df is None  # Below _MIN_SAMPLES threshold

    def test_values_are_float64(self, simple_ibt):
        df = load_ibt(simple_ibt)
        for col in df.columns:
            assert df[col].dtype == np.float64

    def test_values_increase_monotonically_for_session_time(self, simple_ibt):
        df = load_ibt(simple_ibt)
        st = df["irsdk__SessionTime"].values
        # SessionTime should generally increase (synthetic data: row_idx * 0.1)
        diffs = np.diff(st)
        assert np.sum(diffs > 0) > len(diffs) * 0.9  # Allow some noise


class TestLoadIbtWithMetadata:
    def test_returns_tuple(self, simple_ibt):
        result = load_ibt_with_metadata(simple_ibt)
        assert result is not None
        df, meta = result
        assert isinstance(df, pd.DataFrame)
        assert isinstance(meta, dict)

    def test_metadata_fields(self, simple_ibt):
        _, meta = load_ibt_with_metadata(simple_ibt)
        assert meta["tick_rate"] == 60
        assert meta["version"] == 2
        assert meta["n_samples"] == 200
        assert meta["n_channels"] == 13
        assert meta["file_name"] == "test_session.ibt"
        assert meta["file_size_mb"] > 0
        assert "session_info_yaml" in meta

    def test_nonexistent_returns_none(self, tmp_path):
        result = load_ibt_with_metadata(tmp_path / "nope.ibt")
        assert result is None


class TestCompatibilityWithRawChannels:
    """Verify that ibt_loader output feeds into raw_channels.extract_raw_channels."""

    def test_extract_raw_channels_accepts_ibt_loader_output(self, simple_ibt, sim_config):
        from telemetry_tool.sim_optimizer.ingest.raw_channels import extract_raw_channels

        df = load_ibt(simple_ibt)
        assert df is not None

        channels = extract_raw_channels(df, config=sim_config)
        assert channels.n_samples == 200
        assert channels.speed_mps is not None
        assert channels.throttle is not None
        assert channels.brake is not None

    def test_feeds_into_optimizer_pipeline(self, simple_ibt):
        """Smoke test: ibt_loader → optimize_session doesn't crash."""
        from telemetry_tool.sim_optimizer.pipeline import optimize_session

        df = load_ibt(simple_ibt)
        assert df is not None

        result = optimize_session(df)
        # May not produce a full theoretical (synthetic data is simple)
        # but should not crash
        assert result is not None
        assert isinstance(result.errors, list)
