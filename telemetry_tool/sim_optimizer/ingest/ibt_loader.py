"""Load an iRacing .ibt file into a DataFrame with ``irsdk__`` prefixed columns.

This is the bridge between raw .ibt binary files (from replay capture or live
telemetry) and the sim optimizer pipeline which expects a DataFrame whose
columns are named ``irsdk__<VarName>`` (e.g. ``irsdk__Speed``,
``irsdk__Throttle``).

The loader reads the binary format directly (no external ``ibt`` library
required) and uses vectorized numpy reads for speed.

Usage
-----
::

    from telemetry_tool.sim_optimizer.ingest.ibt_loader import load_ibt
    df = load_ibt("session.ibt")
    # df.columns → ["irsdk__Speed", "irsdk__Throttle", ...]

    from telemetry_tool.sim_optimizer.pipeline import optimize_session
    result = optimize_session(df)
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# iRacing var type codes -> (struct format, numpy dtype, byte size)
_TYPE_MAP = {
    1: ("<b", np.int8, 1),       # bool / char
    2: ("<i", np.int32, 4),      # int32
    3: ("<I", np.uint32, 4),     # bitfield (uint32)
    4: ("<f", np.float32, 4),    # float32
    5: ("<d", np.float64, 8),    # float64 (double)
}

# Minimum samples to consider a valid telemetry file
_MIN_SAMPLES = 10


def _parse_header(data: bytes) -> Optional[dict]:
    """Parse the 112-byte disk sub-header."""
    if len(data) < 112:
        return None
    try:
        version = struct.unpack_from("<i", data, 0)[0]
        if version not in (1, 2):
            logger.warning("Unknown ibt version %d", version)
            return None
        tick_rate = struct.unpack_from("<i", data, 8)[0]
        session_info_len = struct.unpack_from("<i", data, 16)[0]
        session_info_offset = struct.unpack_from("<i", data, 20)[0]
        num_vars = struct.unpack_from("<i", data, 24)[0]
        var_header_offset = struct.unpack_from("<i", data, 28)[0]
        buf_len = struct.unpack_from("<i", data, 36)[0]
        data_start = session_info_offset + session_info_len
        return {
            "version": version,
            "tick_rate": tick_rate,
            "num_vars": num_vars,
            "var_header_offset": var_header_offset,
            "buf_len": buf_len,
            "data_start": data_start,
            "session_info_offset": session_info_offset,
            "session_info_len": session_info_len,
        }
    except struct.error as exc:
        logger.warning("Failed to parse ibt header: %s", exc)
        return None


def _parse_var_headers(data: bytes, hdr: dict) -> list[dict]:
    """Parse variable headers into a list of var descriptors."""
    result = []
    offset = hdr["var_header_offset"]
    for _ in range(hdr["num_vars"]):
        end = offset + 144
        if end > len(data):
            break
        var_type = struct.unpack_from("<i", data, offset)[0]
        var_offset = struct.unpack_from("<i", data, offset + 4)[0]
        var_count = struct.unpack_from("<i", data, offset + 8)[0]
        name_raw = data[offset + 16: offset + 48]
        name = name_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        desc_raw = data[offset + 48: offset + 112]
        desc = desc_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        unit_raw = data[offset + 112: offset + 144]
        unit = unit_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        result.append({
            "name": name,
            "type": var_type,
            "offset": var_offset,
            "count": var_count,
            "desc": desc,
            "unit": unit,
        })
        offset = end
    return result


def _parse_session_info(data: bytes, hdr: dict) -> str:
    """Extract the session info YAML string."""
    start = hdr["session_info_offset"]
    end = start + hdr["session_info_len"]
    if end > len(data):
        return ""
    raw = data[start:end]
    return raw.split(b"\x00")[0].decode("utf-8", errors="replace")


def load_ibt(
    ibt_path: str | Path,
    *,
    channels: list[str] | None = None,
) -> Optional[pd.DataFrame]:
    """Load an iRacing .ibt file into a DataFrame with ``irsdk__`` columns.

    Parameters
    ----------
    ibt_path:
        Path to the ``.ibt`` binary telemetry file.
    channels:
        Optional list of channel names to load. If ``None``, loads all
        scalar channels. Array channels (count > 1) are expanded as
        ``Name__0``, ``Name__1``, etc.

    Returns
    -------
    pd.DataFrame or None
        DataFrame with ``irsdk__<VarName>`` columns, or ``None`` on error.
    """
    ibt_path = Path(ibt_path)
    if not ibt_path.exists():
        logger.warning("IBT file not found: %s", ibt_path)
        return None

    try:
        file_size = ibt_path.stat().st_size
    except OSError as exc:
        logger.warning("Cannot stat %s: %s", ibt_path, exc)
        return None

    try:
        with open(str(ibt_path), "rb") as f:
            # Read enough for headers (generous: 144 bytes * 500 vars + 4KB)
            header_read_size = min(file_size, 144 * 500 + 4096)
            header_bytes = f.read(header_read_size)

            hdr = _parse_header(header_bytes)
            if hdr is None:
                logger.warning("Invalid header in %s", ibt_path.name)
                return None

            var_headers = _parse_var_headers(header_bytes, hdr)
            if not var_headers:
                logger.warning("No variable headers in %s", ibt_path.name)
                return None

            buf_len = hdr["buf_len"]
            data_start = hdr["data_start"]
            num_samples = (file_size - data_start) // buf_len

            if num_samples < _MIN_SAMPLES:
                logger.warning(
                    "Only %d samples in %s (min %d)",
                    num_samples, ibt_path.name, _MIN_SAMPLES,
                )
                return None

            # Filter channels if requested
            if channels is not None:
                channels_set = set(channels)
                var_headers = [v for v in var_headers if v["name"] in channels_set]

            # Read all data rows at once
            f.seek(data_start)
            raw_data = f.read(num_samples * buf_len)

        if len(raw_data) < num_samples * buf_len:
            num_samples = len(raw_data) // buf_len

        # Build DataFrame column by column using vectorized reads
        columns: dict[str, np.ndarray] = {}

        for vh in var_headers:
            vtype = vh["type"]
            if vtype not in _TYPE_MAP:
                logger.debug("Skipping unsupported type %d for %s", vtype, vh["name"])
                continue

            _, np_dtype, byte_size = _TYPE_MAP[vtype]
            var_offset = vh["offset"]
            count = vh["count"]

            if count == 1:
                # Scalar channel — vectorized extraction
                col_name = f"irsdk__{vh['name']}"
                arr = np.empty(num_samples, dtype=np_dtype)
                for i in range(num_samples):
                    row_start = i * buf_len + var_offset
                    arr[i] = np.frombuffer(
                        raw_data, dtype=np_dtype, count=1, offset=row_start,
                    )[0]
                columns[col_name] = arr.astype(np.float64)
            else:
                # Array channel — expand to Name__0, Name__1, ...
                for elem in range(count):
                    col_name = f"irsdk__{vh['name']}__{elem}"
                    elem_offset = var_offset + elem * byte_size
                    arr = np.empty(num_samples, dtype=np_dtype)
                    for i in range(num_samples):
                        row_start = i * buf_len + elem_offset
                        arr[i] = np.frombuffer(
                            raw_data, dtype=np_dtype, count=1, offset=row_start,
                        )[0]
                    columns[col_name] = arr.astype(np.float64)

        if not columns:
            logger.warning("No channels extracted from %s", ibt_path.name)
            return None

        df = pd.DataFrame(columns)
        logger.info(
            "Loaded %s: %d samples, %d channels (%.1f MB)",
            ibt_path.name,
            num_samples,
            len(df.columns),
            file_size / 1e6,
        )
        return df

    except (OSError, struct.error) as exc:
        logger.warning("Error reading %s: %s", ibt_path, exc)
        return None


def load_ibt_with_metadata(
    ibt_path: str | Path,
) -> Optional[tuple[pd.DataFrame, dict]]:
    """Load .ibt file and return both DataFrame and session metadata.

    Returns
    -------
    (DataFrame, metadata_dict) or None
        metadata_dict contains: tick_rate, version, session_info (YAML str),
        n_samples, n_channels, file_name, file_size_mb.
    """
    ibt_path = Path(ibt_path)
    df = load_ibt(ibt_path)
    if df is None:
        return None

    # Re-read header for metadata (cheap — already validated)
    try:
        with open(str(ibt_path), "rb") as f:
            file_size = ibt_path.stat().st_size
            header_read_size = min(file_size, 144 * 500 + 4096)
            header_bytes = f.read(header_read_size)
            hdr = _parse_header(header_bytes)
            session_info = _parse_session_info(header_bytes, hdr) if hdr else ""
    except Exception:
        hdr = {}
        session_info = ""

    metadata = {
        "file_name": ibt_path.name,
        "file_size_mb": round(ibt_path.stat().st_size / 1e6, 2),
        "tick_rate": hdr.get("tick_rate", 60) if hdr else 60,
        "version": hdr.get("version", 0) if hdr else 0,
        "n_samples": len(df),
        "n_channels": len(df.columns),
        "session_info_yaml": session_info,
    }
    return df, metadata
