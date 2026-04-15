"""iRacing .ibt telemetry file extractor.

Binary format (version 2):

    Disk sub-header    112 bytes
    Var headers        144 bytes each (at var_header_offset)
    Session info YAML  (at session_info_offset, session_info_len bytes)
    Data rows          (at session_info_offset + session_info_len)
                       Each row is buf_len bytes

Var header layout (144 bytes):
    0:  int32   var_type  (1=bool/char, 2=int, 3=bitfield, 4=float, 5=double)
    4:  int32   offset    (byte offset within each data row)
    8:  int32   count     (array element count, usually 1)
    16: char[32] name
    48: char[64] description
    112: char[32] unit

All public functions log warnings on failure and return ``None``.
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# iRacing var type codes -> struct format + byte size
_TYPE_MAP = {
    1: ("<?", 1),    # bool / char
    2: ("<i", 4),    # int32
    3: ("<I", 4),    # bitfield (uint32)
    4: ("<f", 4),    # float32
    5: ("<d", 8),    # float64 (double)
}


def _parse_header(data: bytes) -> Optional[dict]:
    """Parse the 112-byte disk sub-header.

    Returns a dict with keys: num_vars, var_header_offset, buf_len,
    data_start, tick_rate.
    """
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
            "num_vars": num_vars,
            "var_header_offset": var_header_offset,
            "buf_len": buf_len,
            "data_start": data_start,
            "tick_rate": tick_rate,
        }
    except struct.error as exc:
        logger.warning("Failed to parse ibt header: %s", exc)
        return None


def _parse_var_headers(
    data: bytes, hdr: dict,
) -> Dict[str, dict]:
    """Parse all variable headers into ``{name: {type, offset, count, ...}}``."""
    result: Dict[str, dict] = {}
    offset = hdr["var_header_offset"]
    for _ in range(hdr["num_vars"]):
        end = offset + 144
        if end > len(data):
            break
        var_type = struct.unpack_from("<i", data, offset)[0]
        var_offset = struct.unpack_from("<i", data, offset + 4)[0]
        var_count = struct.unpack_from("<i", data, offset + 8)[0]
        name_raw = data[offset + 16 : offset + 48]
        name = name_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        desc_raw = data[offset + 48 : offset + 112]
        desc = desc_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        unit_raw = data[offset + 112 : offset + 144]
        unit = unit_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        result[name] = {
            "type": var_type,
            "offset": var_offset,
            "count": var_count,
            "desc": desc,
            "unit": unit,
        }
        offset = end
    return result


def _read_channel(
    f,
    var_info: dict,
    data_start: int,
    buf_len: int,
    num_samples: int,
) -> Optional[np.ndarray]:
    """Read a single channel as a numpy array."""
    vtype = var_info["type"]
    if vtype not in _TYPE_MAP:
        logger.warning("Unsupported var type %d", vtype)
        return None

    fmt, size = _TYPE_MAP[vtype]
    var_offset = var_info["offset"]
    count = var_info.get("count", 1)

    if count > 1:
        # Array channel -- not handled for position extraction
        logger.debug("Skipping array channel (count=%d)", count)
        return None

    # Pre-allocate
    dtype = np.float64 if vtype == 5 else np.float32
    out = np.empty(num_samples, dtype=dtype)

    for i in range(num_samples):
        row_start = data_start + i * buf_len + var_offset
        f.seek(row_start)
        raw = f.read(size)
        if len(raw) < size:
            out = out[:i]
            break
        out[i] = struct.unpack(fmt, raw)[0]

    return out


def _extract_single_lap(
    positions: np.ndarray,
    lap_dist_pct: np.ndarray,
) -> tuple:
    """Extract positions for the first complete lap.

    Uses LapDistPct (0→1 per lap) to find where lap boundaries are
    (where pct drops from ~1 back to ~0).  Returns the longest
    complete lap's positions.
    """
    n = min(len(positions), len(lap_dist_pct))
    positions = positions[:n]
    pct = lap_dist_pct[:n]

    # Find lap boundaries: where pct drops significantly (>0.5 decrease)
    dpct = np.diff(pct)
    boundaries = np.where(dpct < -0.5)[0] + 1  # index AFTER the drop

    if len(boundaries) < 1:
        # No complete lap found — return everything (fallback)
        return positions, pct

    # Collect all complete laps
    starts = [0] + list(boundaries)
    ends = list(boundaries) + [n]
    best_start, best_end = 0, n
    best_len = 0

    for s, e in zip(starts, ends):
        seg_pct = pct[s:e]
        # A "complete" lap goes from ~0 to ~0.9+
        if len(seg_pct) > 100 and seg_pct[-1] > 0.8 and seg_pct[0] < 0.2:
            if e - s > best_len:
                best_len = e - s
                best_start, best_end = s, e

    if best_len > 100:
        return positions[best_start:best_end], pct[best_start:best_end]

    # Fallback: use first boundary pair
    if len(boundaries) >= 2:
        return positions[boundaries[0]:boundaries[1]], pct[boundaries[0]:boundaries[1]]

    return positions[:boundaries[0]], pct[:boundaries[0]]


def extract_positions(ibt_path: Path) -> Optional[np.ndarray]:
    """Extract GPS positions from an iRacing .ibt file.

    Parameters
    ----------
    ibt_path:
        Path to the ``.ibt`` file.

    Returns
    -------
    np.ndarray or None
        Shape ``(N, 2)`` array of ``[lat, lon]`` in decimal degrees.
        Rows where both lat and lon are zero are dropped.
        Returns ``None`` on any read/parse error.
    """
    try:
        file_size = ibt_path.stat().st_size
    except OSError as exc:
        logger.warning("Cannot stat %s: %s", ibt_path, exc)
        return None

    try:
        with open(str(ibt_path), "rb") as f:
            header_bytes = f.read(max(4096, 144 * 300 + 200))
            hdr = _parse_header(header_bytes)
            if hdr is None:
                return None

            vars_map = _parse_var_headers(header_bytes, hdr)

            if "Lat" not in vars_map or "Lon" not in vars_map:
                logger.warning("No Lat/Lon channels in %s", ibt_path.name)
                return None

            num_samples = (file_size - hdr["data_start"]) // hdr["buf_len"]
            if num_samples < 10:
                logger.warning(
                    "Too few samples (%d) in %s", num_samples, ibt_path.name
                )
                return None

            lat = _read_channel(
                f, vars_map["Lat"],
                hdr["data_start"], hdr["buf_len"], num_samples,
            )
            lon = _read_channel(
                f, vars_map["Lon"],
                hdr["data_start"], hdr["buf_len"], num_samples,
            )

            if lat is None or lon is None:
                return None

            n = min(len(lat), len(lon))
            positions = np.column_stack((lat[:n], lon[:n]))

            # Drop rows where both are zero (pre-session padding)
            mask = ~((np.abs(positions[:, 0]) < 1e-9) &
                     (np.abs(positions[:, 1]) < 1e-9))
            positions = positions[mask]

            # Extract single lap using LapDistPct (0→1 per lap)
            if "LapDistPct" in vars_map:
                pct = _read_channel(
                    f, vars_map["LapDistPct"],
                    hdr["data_start"], hdr["buf_len"], num_samples,
                )
                if pct is not None:
                    pct = pct[mask[:len(pct)] if len(mask) <= len(pct) else mask]
                    positions, pct = _extract_single_lap(positions, pct)

            if positions.shape[0] < 10:
                logger.warning(
                    "Only %d valid positions in %s",
                    positions.shape[0], ibt_path.name,
                )
                return None

            logger.info(
                "Extracted %d positions (single lap) from %s",
                positions.shape[0], ibt_path.name,
            )
            return positions

    except (OSError, struct.error) as exc:
        logger.warning("Error reading %s: %s", ibt_path, exc)
        return None


def extract_telemetry_channels(
    ibt_path: Path,
    channels: List[str],
) -> Optional[Dict[str, np.ndarray]]:
    """Extract arbitrary named channels from an iRacing .ibt file.

    Parameters
    ----------
    ibt_path:
        Path to the ``.ibt`` file.
    channels:
        List of channel names to extract (e.g.
        ``["Speed", "Throttle", "Brake", "LatAccel"]``).

    Returns
    -------
    dict or None
        ``{channel_name: np.ndarray}``, or ``None`` on error.
        Missing channels are silently omitted from the result.
    """
    try:
        file_size = ibt_path.stat().st_size
    except OSError as exc:
        logger.warning("Cannot stat %s: %s", ibt_path, exc)
        return None

    try:
        with open(str(ibt_path), "rb") as f:
            header_bytes = f.read(max(4096, 144 * 300 + 200))
            hdr = _parse_header(header_bytes)
            if hdr is None:
                return None

            vars_map = _parse_var_headers(header_bytes, hdr)
            num_samples = (file_size - hdr["data_start"]) // hdr["buf_len"]
            if num_samples < 1:
                return None

            result: Dict[str, np.ndarray] = {}
            for ch_name in channels:
                if ch_name not in vars_map:
                    logger.debug(
                        "Channel %r not found in %s", ch_name, ibt_path.name
                    )
                    continue
                arr = _read_channel(
                    f, vars_map[ch_name],
                    hdr["data_start"], hdr["buf_len"], num_samples,
                )
                if arr is not None:
                    result[ch_name] = arr

            if not result:
                return None
            return result

    except (OSError, struct.error) as exc:
        logger.warning("Error reading %s: %s", ibt_path, exc)
        return None
