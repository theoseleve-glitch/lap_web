#!/usr/bin/env python3
"""Parse iRacing .ibt telemetry files into CSV/Parquet.

The .ibt format is the same binary layout as IRSDK shared memory:
  - Header (112 bytes): version, tick_rate, var count, offsets
  - Var headers (144 bytes each): name, desc, unit, type, count, offset
  - Session info (YAML string)
  - Data buffers (one per tick at 60Hz)

Usage:
    # Single file
    python scripts/parse_ibt.py path/to/file.ibt [output_dir]

    # Batch: all .ibt files in a directory
    python scripts/parse_ibt.py path/to/ibt_folder/ [output_dir]
"""
from __future__ import annotations

import csv
import json
import logging
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ibt_parser")

# IRSDK var types
_TYPE_CHAR = 0
_TYPE_BOOL = 1
_TYPE_INT = 2
_TYPE_BITFIELD = 3
_TYPE_FLOAT = 4
_TYPE_DOUBLE = 5

_TYPE_NAMES = {0: "char", 1: "bool", 2: "int", 3: "bitfield", 4: "float", 5: "double"}
_TYPE_STRUCT = {0: "c", 1: "?", 2: "<i", 3: "<I", 4: "<f", 5: "<d"}
_TYPE_SIZE = {0: 1, 1: 1, 2: 4, 3: 4, 4: 4, 5: 8}


@dataclass
class VarHeader:
    name: str
    desc: str
    unit: str
    var_type: int
    count: int
    offset: int  # byte offset within the data buffer

    @property
    def type_name(self) -> str:
        return _TYPE_NAMES.get(self.var_type, "unknown")

    @property
    def byte_size(self) -> int:
        return _TYPE_SIZE.get(self.var_type, 4) * self.count


@dataclass
class IBTHeader:
    version: int
    status: int
    tick_rate: int
    session_info_update: int
    session_info_len: int
    session_info_offset: int
    num_vars: int
    var_header_offset: int
    num_buf: int
    buf_len: int
    buf_offset: int  # start of first data buffer


def parse_header(data: bytes) -> IBTHeader:
    """Parse the 112-byte .ibt header."""
    ver = struct.unpack_from("<i", data, 0)[0]
    status = struct.unpack_from("<i", data, 4)[0]
    tick_rate = struct.unpack_from("<i", data, 8)[0]
    si_update = struct.unpack_from("<i", data, 0xC)[0]
    si_len = struct.unpack_from("<i", data, 0x10)[0]
    si_offset = struct.unpack_from("<i", data, 0x14)[0]
    num_vars = struct.unpack_from("<i", data, 0x18)[0]
    vh_offset = struct.unpack_from("<i", data, 0x1C)[0]
    num_buf = struct.unpack_from("<i", data, 0x20)[0]
    buf_len = struct.unpack_from("<i", data, 0x24)[0]

    # Buffer offset: after var headers + session info
    # The first buffer record starts after the disk sub-header (at offset 0x70 = 112)
    # Actually, each buffer has: ticks(4) + buf_offset(4) = 8 bytes
    # The actual data starts at the buf_offset stored in the first buffer record
    buf_offset_val = struct.unpack_from("<i", data, 0x30)[0]  # disk sub-header: buf[0].tick_count
    buf_data_offset = struct.unpack_from("<i", data, 0x34)[0]  # disk sub-header: buf[0].buf_offset

    return IBTHeader(
        version=ver, status=status, tick_rate=tick_rate,
        session_info_update=si_update, session_info_len=si_len,
        session_info_offset=si_offset, num_vars=num_vars,
        var_header_offset=vh_offset, num_buf=num_buf,
        buf_len=buf_len, buf_offset=buf_data_offset,
    )


def parse_var_headers(data: bytes, header: IBTHeader) -> list[VarHeader]:
    """Parse variable headers (144 bytes each)."""
    headers = []
    offset = header.var_header_offset

    for _ in range(header.num_vars):
        var_type = struct.unpack_from("<i", data, offset)[0]
        var_offset = struct.unpack_from("<i", data, offset + 4)[0]
        var_count = struct.unpack_from("<i", data, offset + 8)[0]
        # offset+12: countAsTime (4 bytes, padding)
        name = data[offset + 16: offset + 48].split(b"\x00")[0].decode("ascii", errors="replace")
        desc = data[offset + 48: offset + 112].split(b"\x00")[0].decode("ascii", errors="replace")
        unit = data[offset + 112: offset + 144].split(b"\x00")[0].decode("ascii", errors="replace")

        headers.append(VarHeader(
            name=name, desc=desc, unit=unit,
            var_type=var_type, count=var_count, offset=var_offset,
        ))
        offset += 144

    return headers


def parse_session_info(data: bytes, header: IBTHeader) -> str:
    """Extract the session info YAML string."""
    start = header.session_info_offset
    end = start + header.session_info_len
    raw = data[start:end]
    # Strip trailing nulls
    null_idx = raw.find(b"\x00")
    if null_idx >= 0:
        raw = raw[:null_idx]
    return raw.decode("utf-8", errors="replace")


def parse_data_rows(data: bytes, header: IBTHeader,
                    var_headers: list[VarHeader]) -> list[dict[str, Any]]:
    """Parse all data ticks into a list of dicts."""
    buf_len = header.buf_len
    data_start = header.buf_offset
    total_data = len(data) - data_start
    num_ticks = total_data // buf_len if buf_len > 0 else 0

    log.info("Parsing %d ticks (%d bytes each, %.1f seconds at %dHz)",
             num_ticks, buf_len, num_ticks / max(header.tick_rate, 1), header.tick_rate)

    # Build column names (flatten arrays)
    columns: list[tuple[str, VarHeader, int]] = []  # (col_name, var_header, array_index)
    for vh in var_headers:
        if vh.count == 1:
            columns.append((f"irsdk__{vh.name}", vh, 0))
        else:
            for i in range(vh.count):
                columns.append((f"irsdk__{vh.name}__{i}", vh, i))

    rows = []
    for tick in range(num_ticks):
        buf_start = data_start + tick * buf_len
        if buf_start + buf_len > len(data):
            break

        row: dict[str, Any] = {}
        for col_name, vh, arr_idx in columns:
            elem_size = _TYPE_SIZE.get(vh.var_type, 4)
            val_offset = buf_start + vh.offset + arr_idx * elem_size
            if val_offset + elem_size > len(data):
                row[col_name] = None
                continue

            fmt = _TYPE_STRUCT.get(vh.var_type, "<f")
            try:
                val = struct.unpack_from(fmt, data, val_offset)[0]
                if vh.var_type == _TYPE_CHAR:
                    val = val.decode("ascii", errors="replace") if isinstance(val, bytes) else val
                elif vh.var_type in (_TYPE_FLOAT, _TYPE_DOUBLE):
                    if val != val:  # NaN
                        val = None
                row[col_name] = val
            except Exception:
                row[col_name] = None

        rows.append(row)

    return rows


def extract_metadata(session_info_yaml: str, var_headers: list[VarHeader],
                     header: IBTHeader) -> dict[str, Any]:
    """Extract key metadata from session info YAML."""
    meta: dict[str, Any] = {
        "tick_rate_hz": header.tick_rate,
        "num_vars": header.num_vars,
        "version": header.version,
    }

    # Simple YAML key extraction (avoid requiring pyyaml)
    for line in session_info_yaml.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key == "TrackDisplayName" and val:
                meta["track_name"] = val
            elif key == "TrackName" and "track_name" not in meta and val:
                meta["track_name"] = val
            elif key == "TrackLength" and val:
                meta["track_length"] = val
            elif key == "CarScreenName" and val:
                meta["car_name"] = val
            elif key == "UserName" and val:
                meta["driver_name"] = val
            elif key == "DriverCarFuelMaxLtr" and val:
                meta["fuel_capacity_l"] = val
            elif key == "SessionType" and val:
                meta["session_type"] = val

    # Corner weights from setup
    corner_weights = {}
    for line in session_info_yaml.split("\n"):
        if "CornerWeight" in line and ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().split()[0] if val.strip() else ""
            try:
                corner_weights[key] = float(val)
            except (ValueError, TypeError):
                pass
    if corner_weights:
        meta["corner_weights"] = corner_weights
        total = sum(corner_weights.values())
        if total > 0:
            meta["total_weight_n"] = total
            meta["estimated_mass_kg"] = round(total / 9.80665, 1)

    return meta


def parse_ibt(ibt_path: Path) -> tuple[list[dict], dict[str, Any], list[VarHeader]]:
    """Parse an .ibt file. Returns (rows, metadata, var_headers)."""
    log.info("Reading %s (%.1f MB)", ibt_path.name, ibt_path.stat().st_size / 1e6)
    t0 = time.monotonic()

    with open(ibt_path, "rb") as f:
        data = f.read()

    header = parse_header(data)
    log.info("Header: v%d, %dHz, %d vars, buf_len=%d, data@0x%X",
             header.version, header.tick_rate, header.num_vars,
             header.buf_len, header.buf_offset)

    var_headers = parse_var_headers(data, header)
    session_info = parse_session_info(data, header)
    metadata = extract_metadata(session_info, var_headers, header)

    log.info("Track: %s, Car: %s, Driver: %s",
             metadata.get("track_name", "?"), metadata.get("car_name", "?"),
             metadata.get("driver_name", "?"))

    rows = parse_data_rows(data, header, var_headers)

    elapsed = time.monotonic() - t0
    log.info("Parsed %d rows in %.1fs (%.0f rows/s)", len(rows), elapsed,
             len(rows) / max(elapsed, 0.001))

    metadata["sample_count"] = len(rows)
    metadata["column_count"] = len(rows[0]) if rows else 0
    metadata["session_info_yaml"] = session_info

    return rows, metadata, var_headers


def save_csv(rows: list[dict], output_path: Path) -> None:
    """Save rows as CSV."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log.info("Saved CSV: %s (%d rows, %d cols)", output_path, len(rows), len(fieldnames))


def save_metadata(metadata: dict, output_path: Path) -> None:
    """Save metadata as JSON (excluding the full YAML)."""
    meta_out = {k: v for k, v in metadata.items() if k != "session_info_yaml"}
    with open(output_path, "w") as f:
        json.dump(meta_out, f, indent=2)


def process_ibt(ibt_path: Path, output_dir: Path) -> bool:
    """Process one .ibt file: parse → save CSV + metadata."""
    try:
        rows, metadata, var_headers = parse_ibt(ibt_path)
        if not rows:
            log.warning("No data rows in %s", ibt_path.name)
            return False

        # Create output folder
        stem = ibt_path.stem
        track = metadata.get("track_name", "unknown").replace(" ", "_").replace("/", "_")
        car = metadata.get("car_name", "unknown").replace(" ", "_").replace("/", "_")
        folder_name = f"{stem}__{track}__{car}"
        out_path = output_dir / folder_name
        out_path.mkdir(parents=True, exist_ok=True)

        save_csv(rows, out_path / "telemetry_raw.csv")
        save_metadata(metadata, out_path / "capture_meta.json")

        # Save session info YAML
        yaml_str = metadata.get("session_info_yaml", "")
        if yaml_str:
            (out_path / "session_info.yaml").write_text(yaml_str, encoding="utf-8")

        return True
    except Exception as exc:
        log.error("Failed to parse %s: %s", ibt_path.name, exc, exc_info=True)
        return False


def batch_process(input_path: Path, output_dir: Path, skip_existing: bool = True) -> None:
    """Process all .ibt files in a directory."""
    if input_path.is_file():
        ibt_files = [input_path]
    else:
        ibt_files = sorted(input_path.glob("*.ibt"))

    if not ibt_files:
        log.error("No .ibt files found in %s", input_path)
        return

    log.info("Found %d .ibt files", len(ibt_files))
    output_dir.mkdir(parents=True, exist_ok=True)

    success, skipped, failed = 0, 0, 0

    for i, ibt_path in enumerate(ibt_files, 1):
        log.info("[%d/%d] %s (%.1f MB)", i, len(ibt_files),
                 ibt_path.name, ibt_path.stat().st_size / 1e6)

        if skip_existing:
            existing = list(output_dir.glob(f"{ibt_path.stem}__*"))
            if existing:
                log.info("  Already parsed — skipping")
                skipped += 1
                continue

        if process_ibt(ibt_path, output_dir):
            success += 1
        else:
            failed += 1

    log.info("")
    log.info("=" * 50)
    log.info("BATCH COMPLETE: %d success, %d skipped, %d failed", success, skipped, failed)
    log.info("=" * 50)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_ibt.py <file.ibt | ibt_folder> [output_dir]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("ibt_parsed")

    batch_process(input_path, output_dir)
