"""MoTeC i2 CSV export adapter.

Handles CSV files exported from MoTeC i2 data analysis software.  MoTeC
exports have variable column names depending on sensor setup, but follow
common naming conventions.

Detection
---------
Reads the first 20 lines and looks for the ``Beacon`` column (present in
virtually all MoTeC exports) or the combination of ``Engine RPM`` with at
least two of ``Throttle``, ``Brake``, ``Ground Speed``.

Parsing
-------
Reads the full CSV via ``pd.read_csv``.  Detects and skips a units row
(second row after header) if present.  Renames columns to canonical names
using pattern matching and applies unit conversions.

MoTeC CSV peculiarity: the first row after the column header may contain
unit strings (e.g. "s", "rpm", "%", "deg").  This is detected by checking
whether the second data row is non-numeric.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final, Optional

import numpy as np
import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")
_G: Final[float] = 9.80665  # standard gravity, m/s^2

# ---------------------------------------------------------------------------
# Column mapping rules: (regex_pattern, canonical_name, unit_hint, conversion)
#
# conversion values:
#   "none"        - no conversion
#   "g_to_mps2"   - multiply by 9.80665
#   "kmh_to_ms"   - divide by 3.6
#   "mph_to_ms"   - multiply by 0.44704
#   "check_speed" - detect unit from values or column name
# ---------------------------------------------------------------------------
_COLUMN_RULES: Final[list[tuple[str, str, str]]] = [
    # Time
    (r"^Time$",                                 "time_s",               "none"),

    # Engine
    (r"(?i)^(?:Engine\s+)?RPM$",                "rpm",                  "none"),

    # Controls
    (r"(?i)^Throttle\s*(?:Pos(?:ition)?|%)?$",  "throttle_pct",         "none"),
    (r"(?i)^TPS$",                              "throttle_pct",         "none"),
    (r"(?i)^Brake\s*(?:Press(?:ure)?|%)?$",     "brake_pct",            "none"),
    (r"(?i)^BPS$",                              "brake_pct",            "none"),
    (r"(?i)^Steer(?:ing)?\s*Angle$",            "steering_angle_deg",   "none"),

    # Speed — needs unit detection
    (r"(?i)^(?:Ground|GPS|Gnd)\s+Speed$",       "speed_mps",            "check_speed"),

    # GPS
    (r"(?i)^GPS\s+Lat(?:itude)?$",              "lat_deg",              "none"),
    (r"(?i)^GPS\s+Lon(?:gitude|g)?$",           "lon_deg",              "none"),
    (r"(?i)^GPS\s+Alt(?:itude)?$",              "altitude_m",           "none"),

    # Accelerations — may be in G
    (r"(?i)^Lat(?:eral)?\s+(?:Accel|G)$",       "accel_lat_mps2",      "g_to_mps2"),
    (r"(?i)^Lateral\s+G$",                      "accel_lat_mps2",      "g_to_mps2"),
    (r"(?i)^Long(?:itudinal)?\s+(?:Accel|G)$",  "accel_long_mps2",     "g_to_mps2"),
    (r"(?i)^Longitudinal\s+G$",                 "accel_long_mps2",     "g_to_mps2"),

    # Yaw
    (r"(?i)^Yaw\s+Rate$",                       "yaw_rate_dps",        "none"),

    # Wheel speed (4-corner)
    (r"(?i)^Wheel\s+Speed\s+FL$",               "wheel_speed_fl",      "check_speed"),
    (r"(?i)^Wheel\s+Speed\s+FR$",               "wheel_speed_fr",      "check_speed"),
    (r"(?i)^Wheel\s+Speed\s+RL$",               "wheel_speed_rl",      "check_speed"),
    (r"(?i)^Wheel\s+Speed\s+RR$",               "wheel_speed_rr",      "check_speed"),

    # Damper position (4-corner)
    (r"(?i)^(?:Damper|Susp\s+Pos)\s+FL$",       "damper_pos_fl",       "none"),
    (r"(?i)^(?:Damper|Susp\s+Pos)\s+FR$",       "damper_pos_fr",       "none"),
    (r"(?i)^(?:Damper|Susp\s+Pos)\s+RL$",       "damper_pos_rl",       "none"),
    (r"(?i)^(?:Damper|Susp\s+Pos)\s+RR$",       "damper_pos_rr",       "none"),

    # Tire temp (4-corner)
    (r"(?i)^Tyre\s+Temp\s+FL$",                 "tire_temp_fl",        "none"),
    (r"(?i)^Tyre\s+Temp\s+FR$",                 "tire_temp_fr",        "none"),
    (r"(?i)^Tyre\s+Temp\s+RL$",                 "tire_temp_rl",        "none"),
    (r"(?i)^Tyre\s+Temp\s+RR$",                 "tire_temp_rr",        "none"),

    # Engine temps
    (r"(?i)^Oil\s+Temp$",                       "oil_temp",            "none"),
    (r"(?i)^Water\s+Temp$",                     "water_temp",          "none"),

    # Fuel
    (r"(?i)^Fuel(?:\s+Level)?$",                "fuel_kg",             "none"),

    # Lap
    (r"(?i)^(?:Lap[_\s]?Number|Lap)$",          "lap_number",          "none"),
]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class MoTeCAdapter(BaseAdapter):
    """Adapter for MoTeC i2 CSV exports."""

    FORMAT_NAME: str = "motec"
    EXTENSIONS: list[str] = [".csv"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is a MoTeC CSV.

        Looks for ``Beacon`` or ``Engine RPM`` with supporting columns.
        Returns 0.0 on any I/O error.
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return 0.0

            header_cells = _read_header_cells(path)
            if not header_cells:
                return 0.0

            return _score_header(header_cells)
        except Exception:
            logger.debug(
                "MoTeCAdapter.detect() failed for %s", file_path,
                exc_info=True,
            )
            return 0.0

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------
    def parse(
        self,
        file_path: str,
        progress_cb: Optional[object] = None,
    ) -> pd.DataFrame:
        """Parse *file_path* into a canonical DataFrame."""
        df = _read_csv_with_fallback(file_path)

        # Detect and skip units row.
        df = _skip_units_row(df)

        self._metadata = _extract_metadata(df)

        df = _rename_and_convert(df)

        from telemetry_tool.channel_registry import CHANNELS
        self._channels = [col for col in df.columns if col in CHANNELS]

        return df

    # ------------------------------------------------------------------
    # metadata / available_channels
    # ------------------------------------------------------------------
    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_head_lines(path: Path, max_lines: int = 100) -> list[str]:
    """Read first *max_lines* with encoding fallback."""
    for enc in _ENCODINGS:
        try:
            with path.open(encoding=enc) as fh:
                lines: list[str] = []
                for i, line in enumerate(fh):
                    if i >= max_lines:
                        break
                    lines.append(line)
                return lines
        except UnicodeDecodeError:
            continue
    return []


def _read_header_cells(path: Path) -> list[str]:
    """Return the header cells from the first non-empty line."""
    lines = _read_head_lines(path, max_lines=20)
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        delim = ";" if stripped.count(";") > stripped.count(",") else ","
        cells = [c.strip().strip('"').strip("'") for c in stripped.split(delim)]
        non_empty = [c for c in cells if c]
        if len(non_empty) >= 2:
            return cells
    return []


def _score_header(header_cells: list[str]) -> float:
    """Score how likely the header belongs to a MoTeC CSV."""
    cells_set = frozenset(c.strip() for c in header_cells)

    has_beacon = "Beacon" in cells_set

    # Check for Engine RPM (exact or with space).
    has_engine_rpm = "Engine RPM" in cells_set or "RPM" in cells_set

    if not has_beacon and not has_engine_rpm:
        return 0.0

    # If we have Beacon, that is very MoTeC-specific.
    if has_beacon:
        confidence = 0.85
        # Count additional known MoTeC columns.
        motec_keywords = [
            "Engine RPM", "RPM", "Throttle Pos", "Throttle Position",
            "TPS", "Brake Press", "Brake Pressure", "BPS",
            "Ground Speed", "GPS Speed", "Gnd Speed",
            "GPS Lat", "GPS Long", "Steer Angle", "Steering Angle",
            "Lat Accel", "Lateral G", "Long Accel", "Longitudinal G",
            "Yaw Rate", "Oil Temp", "Water Temp", "Fuel",
        ]
        extra = sum(1 for kw in motec_keywords if kw in cells_set)
        confidence = min(0.95, confidence + extra * 0.02)
        return confidence

    # Engine RPM without Beacon: need supporting columns.
    supporting_keywords = ["Throttle", "Brake", "Ground Speed",
                           "GPS Speed", "Gnd Speed"]
    support_count = 0
    for kw in supporting_keywords:
        if any(kw.lower() in c.lower() for c in cells_set):
            support_count += 1

    if support_count >= 2:
        return min(0.85, 0.65 + support_count * 0.05)

    return 0.0


def _read_csv_with_fallback(file_path: str) -> pd.DataFrame:
    """Read CSV with encoding fallback."""
    for enc in _ENCODINGS:
        try:
            return pd.read_csv(file_path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(file_path, encoding="utf-8", errors="replace")


def _skip_units_row(df: pd.DataFrame) -> pd.DataFrame:
    """If the first data row is non-numeric (unit strings), drop it."""
    if len(df) < 2:
        return df

    first_row = df.iloc[0]
    numeric_count = 0
    non_numeric_count = 0

    for val in first_row:
        if isinstance(val, (int, float)):
            if not np.isnan(val):
                numeric_count += 1
            continue
        s = str(val).strip()
        if not s:
            continue
        try:
            float(s)
            numeric_count += 1
        except (ValueError, TypeError):
            non_numeric_count += 1

    # If majority of cells are non-numeric strings, treat as units row.
    if non_numeric_count > numeric_count and non_numeric_count >= 2:
        logger.debug("Detected MoTeC units row; skipping first data row.")
        df = df.iloc[1:].reset_index(drop=True)

    return df


def _extract_metadata(df: pd.DataFrame) -> dict:
    """Extract basic metadata."""
    meta: dict = {"format": "motec", "sample_count": len(df)}
    return meta


def _rename_and_convert(df: pd.DataFrame) -> pd.DataFrame:
    """Rename MoTeC columns to canonical names and apply conversions."""
    rename_map: dict[str, str] = {}
    conversions: dict[str, str] = {}
    claimed: set[str] = set()

    for col in df.columns:
        col_stripped = col.strip()
        for pattern, canonical, conv in _COLUMN_RULES:
            if canonical in claimed:
                continue
            if re.match(pattern, col_stripped):
                rename_map[col] = canonical
                conversions[canonical] = conv
                claimed.add(canonical)
                break

    # Skip the Beacon column entirely (lap marker, not telemetry data).
    beacon_cols = [c for c in df.columns if c.strip() == "Beacon"]
    if beacon_cols:
        df = df.drop(columns=beacon_cols, errors="ignore")

    df = df.rename(columns=rename_map)

    # Apply conversions.
    for canonical, conv in conversions.items():
        if canonical not in df.columns:
            continue
        series = pd.to_numeric(df[canonical], errors="coerce")
        if conv == "g_to_mps2":
            df[canonical] = series * _G
        elif conv == "kmh_to_ms":
            df[canonical] = series / 3.6
        elif conv == "mph_to_ms":
            df[canonical] = series * 0.44704
        elif conv == "check_speed":
            df[canonical] = _convert_speed(series)
        else:
            df[canonical] = series

    return df


def _convert_speed(series: pd.Series) -> pd.Series:
    """Auto-detect speed unit and convert to m/s.

    Heuristic: if max > 300 -> likely mph; if max > 200 -> likely km/h;
    else assume m/s.
    """
    max_val = series.max()
    if pd.isna(max_val):
        return series
    if max_val > 300:
        return series * 0.44704
    if max_val > 120:
        return series / 3.6
    return series
