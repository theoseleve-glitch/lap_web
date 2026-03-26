"""VBOX .vbo telemetry adapter.

Parses section-based text format with [header], [column names], [data].
Converts velocity from knots to m/s, lat/long from stored value / 60000 to degrees.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_KNOTS_TO_MPS: Final[float] = 0.514444
_LATLONG_DIVISOR: Final[float] = 60000.0
_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

# Canonical column mapping: vbox column name -> canonical_name
_COLUMN_ORDER: Final[list[tuple[str, str]]] = [
    ("sats", "satellites"),
    ("time", "time_s"),
    ("lat", "lat_deg"),
    ("long", "lon_deg"),
    ("velocity", "speed_mps"),
    ("heading", "heading_deg"),
    ("height", "altitude_m"),
    ("vertvel", "raw_vert_vel"),
]


class VboxAdapter(BaseAdapter):
    """Adapter for RaceLogic VBOX .vbo files."""

    FORMAT_NAME: str = "vbox"
    EXTENSIONS: list[str] = [".vbo"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() != ".vbo":
                return 0.0

            for enc in _ENCODINGS:
                try:
                    with path.open(encoding=enc) as fh:
                        for i, line in enumerate(fh):
                            if i > 50:
                                break
                            stripped = line.strip().lower()
                            if stripped in ("[header]", "[column names]"):
                                return 0.9
                    return 0.0
                except UnicodeDecodeError:
                    continue
            return 0.0
        except Exception:
            return 0.0

    def parse(self, file_path: str, progress_cb: Optional[object] = None) -> pd.DataFrame:
        path = Path(file_path)
        lines = _read_all_lines(path)
        header_info, col_names, data_lines = _parse_sections(lines)

        self._metadata = header_info

        df = _build_dataframe(col_names, data_lines)

        # Unit conversions
        if "speed_mps" in df.columns:
            df["speed_mps"] = pd.to_numeric(df["speed_mps"], errors="coerce") * _KNOTS_TO_MPS
        if "lat_deg" in df.columns:
            df["lat_deg"] = pd.to_numeric(df["lat_deg"], errors="coerce") / _LATLONG_DIVISOR
        if "lon_deg" in df.columns:
            df["lon_deg"] = pd.to_numeric(df["lon_deg"], errors="coerce") / _LATLONG_DIVISOR
        if "time_s" in df.columns:
            raw_time = pd.to_numeric(df["time_s"], errors="coerce")
            df["time_s"] = _vbox_time_to_seconds(raw_time)

        # Coerce remaining columns to numeric
        for col in df.columns:
            if col not in ("time_s", "speed_mps", "lat_deg", "lon_deg"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        self._channels = [c for c in df.columns if not c.startswith("raw_")]
        return df

    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)


def _read_all_lines(path: Path) -> list[str]:
    for enc in _ENCODINGS:
        try:
            return path.read_text(encoding=enc).splitlines()
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _parse_sections(lines: list[str]) -> tuple[dict, list[str], list[str]]:
    """Parse VBOX sections: [header], [column names], [data]."""
    section = None
    header_info: dict = {}
    col_names: list[str] = []
    data_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if lower.startswith("[") and lower.endswith("]"):
            section = lower[1:-1]
            continue

        if not stripped:
            continue

        if section == "header":
            header_info[stripped] = stripped
        elif section == "column names" or section == "satellites":
            if not col_names:
                col_names = stripped.split()
        elif section == "data":
            data_lines.append(stripped)

    return header_info, col_names, data_lines


def _build_dataframe(col_names: list[str], data_lines: list[str]) -> pd.DataFrame:
    """Build DataFrame from parsed VBOX data."""
    canonical_names = []
    for name in col_names:
        lower = name.lower()
        matched = False
        for vbox_name, canonical in _COLUMN_ORDER:
            if lower == vbox_name or lower.startswith(vbox_name):
                canonical_names.append(canonical)
                matched = True
                break
        if not matched:
            canonical_names.append(f"raw_{lower}")

    rows = []
    for line in data_lines:
        cells = line.split()
        if len(cells) >= len(canonical_names):
            rows.append(cells[:len(canonical_names)])
        elif cells:
            padded = cells + [None] * (len(canonical_names) - len(cells))
            rows.append(padded)

    if not rows:
        return pd.DataFrame(columns=canonical_names)

    return pd.DataFrame(rows, columns=canonical_names)


def _vbox_time_to_seconds(raw_time: pd.Series) -> pd.Series:
    """Convert VBOX time (HHMMSSCC format) to seconds from session start."""
    time_val = raw_time.values.copy()
    hours = (time_val // 10000).astype(float)
    remainder = time_val % 10000
    minutes = (remainder // 100).astype(float)
    seconds = (remainder % 100).astype(float)
    abs_seconds = hours * 3600 + minutes * 60 + seconds
    result = abs_seconds - abs_seconds[0] if len(abs_seconds) > 0 else abs_seconds
    return pd.Series(result)
