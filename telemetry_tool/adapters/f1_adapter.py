"""Codemasters F1 game CSV telemetry adapter.

Handles CSV telemetry exports from F1 2023, F1 2024, and F1 25 produced by
third-party tools (f1laps, f1-telemetry-app, SimHub, etc.).

Detection
---------
Reads the first header line and looks for F1 game-specific column names
(``m_worldPositionX``, ``m_speed``, ``m_throttle``, ``m_gForceLateral``,
``m_steer``, ``m_brake``, ``m_gear``, ``m_engineRPM``).  Requires at least
3 sentinels for high confidence (0.85).  Also detects alternate column
names without the ``m_`` prefix at 0.7 confidence.

Parsing
-------
Maps F1 game column names to canonical names defined in
``telemetry_tool.channel_registry``.  Applies unit conversions:

- Throttle/Brake: 0.0-1.0 fraction to 0-100 percentage
- G-forces: G to m/s^2 (multiply by 9.80665)
- Steering: -1..+1 normalized to approximate degrees (* 180)
- Position: Y-up convention (m_worldPositionY = altitude)
- Time: synthesised from row index at 60 Hz if no time column
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import numpy as np
import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_G_TO_MPS2: Final[float] = 9.80665
_DEFAULT_SAMPLE_RATE_HZ: Final[float] = 60.0

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

#: Header sentinels used for format detection (m_ prefixed variant).
_F1_SENTINELS: Final[frozenset[str]] = frozenset({
    "m_worldPositionX", "m_speed", "m_throttle", "m_gForceLateral",
    "m_steer", "m_brake", "m_gear", "m_engineRPM",
})

#: Alternate sentinels without the m_ prefix.
_F1_ALT_SENTINELS: Final[frozenset[str]] = frozenset({
    "worldPositionX", "speed", "throttle", "gForceLateral",
    "steer", "brake", "gear", "engineRPM",
})

# ---------------------------------------------------------------------------
# Column mapping: F1 game raw -> (canonical_name, conversion_func | None)
# ---------------------------------------------------------------------------

_NUMERIC = lambda s: pd.to_numeric(s, errors="coerce")  # noqa: E731
_SCALE_01_TO_PCT = lambda s: pd.to_numeric(s, errors="coerce") * 100.0  # noqa: E731
_G_TO_MPS2_FN = lambda s: pd.to_numeric(s, errors="coerce") * _G_TO_MPS2  # noqa: E731
_STEER_TO_DEG = lambda s: pd.to_numeric(s, errors="coerce") * 180.0  # noqa: E731

# (F1 column, canonical name, conversion or None)
# Listed with m_ prefix; the alternate (non-m_) prefix is handled in
# _rename_and_convert() via a prefix-stripping pass.
_COLUMN_MAP: Final[list[tuple[str, str, object]]] = [
    # Position (F1 Y-up: X=horizontal, Z=horizontal, Y=vertical)
    ("m_worldPositionX", "pos_x_m",             _NUMERIC),
    ("m_worldPositionZ", "pos_y_m",             _NUMERIC),
    ("m_worldPositionY", "altitude_m",          _NUMERIC),

    # Speed (already in m/s in F1 games)
    ("m_speed",          "speed_mps",            _NUMERIC),

    # Acceleration (G -> m/s^2)
    ("m_gForceLateral",       "accel_lat_mps2",  _G_TO_MPS2_FN),
    ("m_gForceLongitudinal",  "accel_long_mps2", _G_TO_MPS2_FN),
    ("m_gForceVertical",      "accel_vert_mps2", _G_TO_MPS2_FN),

    # Controls
    ("m_throttle",       "throttle_pct",         _SCALE_01_TO_PCT),
    ("m_brake",          "brake_pct",            _SCALE_01_TO_PCT),
    ("m_steer",          "steering_angle_deg",   _STEER_TO_DEG),

    # Engine
    ("m_gear",           "gear",                 _NUMERIC),
    ("m_engineRPM",      "rpm",                  _NUMERIC),

    # Distance and lap
    ("m_lapDistance",     "distance_m",           _NUMERIC),
    ("m_currentLapNum",  "lap_number",            _NUMERIC),
]

#: All raw column names from the mapping (for extended detection scoring).
_F1_RAW_NAMES: Final[frozenset[str]] = frozenset(
    raw for raw, _, _ in _COLUMN_MAP
)

#: Tire surface temperature columns.
_TIRE_TEMP_MAP: Final[list[tuple[str, str]]] = [
    ("m_tyresSurfaceTemperature_RL", "tire_temp_rl"),
    ("m_tyresSurfaceTemperature_RR", "tire_temp_rr"),
    ("m_tyresSurfaceTemperature_FL", "tire_temp_fl"),
    ("m_tyresSurfaceTemperature_FR", "tire_temp_fr"),
]

#: Tire inner temperature columns.
_TIRE_INNER_TEMP_MAP: Final[list[tuple[str, str]]] = [
    ("m_tyresInnerTemperature_RL", "tire_temp_rl_i"),
    ("m_tyresInnerTemperature_RR", "tire_temp_rr_i"),
    ("m_tyresInnerTemperature_FL", "tire_temp_fl_i"),
    ("m_tyresInnerTemperature_FR", "tire_temp_fr_i"),
]

#: Tire pressure columns.
_TIRE_PRESSURE_MAP: Final[list[tuple[str, str]]] = [
    ("m_tyresPressure_RL", "tire_pressure_rl"),
    ("m_tyresPressure_RR", "tire_pressure_rr"),
    ("m_tyresPressure_FL", "tire_pressure_fl"),
    ("m_tyresPressure_FR", "tire_pressure_fr"),
]

#: Tire wear columns.
_TIRE_WEAR_MAP: Final[list[tuple[str, str]]] = [
    ("m_tyresWear_RL", "tire_wear_rl"),
    ("m_tyresWear_RR", "tire_wear_rr"),
    ("m_tyresWear_FL", "tire_wear_fl"),
    ("m_tyresWear_FR", "tire_wear_fr"),
]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class F1Adapter(BaseAdapter):
    """Adapter for Codemasters F1 game CSV telemetry exports."""

    FORMAT_NAME: str = "f1_game"
    EXTENSIONS: list[str] = [".csv"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is an F1 game CSV.

        Reads only the first header line.  Requires at least 3 of the
        sentinel column names for high confidence (0.85).  Also detects
        alternate column names without the ``m_`` prefix at 0.7 confidence.

        Returns 0.0 on any I/O error or non-CSV file.
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return 0.0

            suffix = path.suffix.lower()
            if suffix not in (".csv", ".txt", ""):
                return 0.0

            header_line = _read_header_line(path)
            if not header_line:
                return 0.0

            return _score_header(header_line)
        except Exception:
            logger.debug(
                "F1Adapter.detect() failed for %s", file_path,
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
        """Parse *file_path* into a canonical DataFrame.

        Maps F1 game columns to canonical names, applies unit conversions
        (G-forces to m/s^2, 0-1 to percentage), and synthesises time_s
        if absent.
        """
        df = _read_f1_csv(file_path)

        # Normalize alternate column names (no m_ prefix) to m_ prefix.
        df = _normalize_column_prefix(df)

        # Store raw metadata before column renaming.
        self._metadata = _extract_metadata(df, file_path)

        # Apply column mapping and conversions.
        df = _rename_and_convert(df)

        # Synthesise time_s from row index if not already present.
        if "time_s" not in df.columns:
            df = _synthesise_time(df)

        # Store canonical channel list.
        from telemetry_tool.channel_registry import CHANNELS
        self._channels = [col for col in df.columns if col in CHANNELS]

        return df

    # ------------------------------------------------------------------
    # metadata
    # ------------------------------------------------------------------
    def metadata(self) -> dict:
        """Return session metadata extracted during parsing."""
        return dict(self._metadata)

    # ------------------------------------------------------------------
    # available_channels
    # ------------------------------------------------------------------
    def available_channels(self) -> list[str]:
        """Return canonical channel names present after parsing."""
        return list(self._channels)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_header_line(path: Path) -> str:
    """Read the first non-empty line from *path* with encoding fallback."""
    for enc in _ENCODINGS:
        try:
            with path.open(encoding=enc) as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped:
                        return stripped
            return ""
        except UnicodeDecodeError:
            continue
    return ""


def _score_header(header_line: str) -> float:
    """Score how likely *header_line* represents an F1 game CSV header.

    Returns a confidence between 0.0 and 1.0.
    """
    # Determine delimiter.
    delim = ";" if header_line.count(";") > header_line.count(",") else ","
    cells = {c.strip() for c in header_line.split(delim)}

    # Primary: m_ prefixed sentinels.
    sentinel_hits = len(cells & _F1_SENTINELS)

    if sentinel_hits >= 3:
        return 0.85
    elif sentinel_hits == 2:
        return 0.5
    elif sentinel_hits == 1:
        return 0.3

    # Fallback: check alternate (non-m_) sentinels.
    alt_hits = len(cells & _F1_ALT_SENTINELS)
    if alt_hits >= 3:
        return 0.7
    elif alt_hits == 2:
        return 0.4
    elif alt_hits == 1:
        return 0.2

    return 0.0


def _read_f1_csv(file_path: str) -> pd.DataFrame:
    """Read an F1 game CSV into a raw DataFrame.

    Tries multiple encodings.  Returns the DataFrame with original column
    names (no renaming).
    """
    path = Path(file_path)
    for enc in _ENCODINGS:
        try:
            df = pd.read_csv(path, encoding=enc)
            df.columns = [c.strip() for c in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(path, encoding="utf-8", errors="replace")
    df.columns = [c.strip() for c in df.columns]
    return df


def _normalize_column_prefix(df: pd.DataFrame) -> pd.DataFrame:
    """Add m_ prefix to columns that match alternate sentinel names.

    This allows the rest of the parsing pipeline to work with a single
    set of column names.
    """
    columns_set = set(df.columns)

    # Only normalize if we see alternate names and NOT the m_ prefixed ones.
    # This avoids double-prefixing.
    rename_map: dict[str, str] = {}

    # Build a map of alt_name -> m_name for all known columns.
    for m_name in _F1_RAW_NAMES:
        if m_name.startswith("m_"):
            alt_name = m_name[2:]  # strip m_ prefix
            if alt_name in columns_set and m_name not in columns_set:
                rename_map[alt_name] = m_name

    # Also handle specific alternate names for non-mapping columns.
    alt_extras = {
        "sessionTime": "m_sessionTime",
        "currentLapNum": "m_currentLapNum",
        "lapDistance": "m_lapDistance",
    }
    for alt_name, m_name in alt_extras.items():
        if alt_name in columns_set and m_name not in columns_set:
            rename_map[alt_name] = m_name

    if rename_map:
        df = df.rename(columns=rename_map)

    return df


def _extract_metadata(df: pd.DataFrame, file_path: str) -> dict:
    """Extract metadata from the raw DataFrame and file path."""
    meta: dict = {"source": "f1_game", "format": "f1_game"}

    path = Path(file_path)
    meta["file_name"] = path.name

    return meta


def _rename_and_convert(df: pd.DataFrame) -> pd.DataFrame:
    """Rename F1 columns to canonical names and apply conversions."""
    columns_set = set(df.columns)
    rename_map: dict[str, str] = {}
    conversions: dict[str, object] = {}
    claimed_canonical: set[str] = set()

    for raw_name, canonical, convert_fn in _COLUMN_MAP:
        if canonical in claimed_canonical:
            continue
        if raw_name in columns_set:
            rename_map[raw_name] = canonical
            claimed_canonical.add(canonical)
            if convert_fn is not None:
                conversions[canonical] = convert_fn

    # Handle time column: m_sessionTime -> time_s.
    if "m_sessionTime" in columns_set and "time_s" not in claimed_canonical:
        rename_map["m_sessionTime"] = "time_s"
        claimed_canonical.add("time_s")
        conversions["time_s"] = _NUMERIC

    # Rename columns.
    df = df.rename(columns=rename_map)

    # Apply conversions.
    for canonical, convert_fn in conversions.items():
        if canonical in df.columns:
            df[canonical] = convert_fn(df[canonical])

    # Map tire surface temperature columns.
    for raw_name, canonical in _TIRE_TEMP_MAP:
        if raw_name in columns_set and canonical not in claimed_canonical:
            df[canonical] = pd.to_numeric(df[raw_name], errors="coerce")
            claimed_canonical.add(canonical)

    # Map tire inner temperature columns.
    for raw_name, canonical in _TIRE_INNER_TEMP_MAP:
        if raw_name in columns_set and canonical not in claimed_canonical:
            df[canonical] = pd.to_numeric(df[raw_name], errors="coerce")
            claimed_canonical.add(canonical)

    # Map tire pressure columns.
    for raw_name, canonical in _TIRE_PRESSURE_MAP:
        if raw_name in columns_set and canonical not in claimed_canonical:
            df[canonical] = pd.to_numeric(df[raw_name], errors="coerce")
            claimed_canonical.add(canonical)

    # Map tire wear columns.
    for raw_name, canonical in _TIRE_WEAR_MAP:
        if raw_name in columns_set and canonical not in claimed_canonical:
            df[canonical] = pd.to_numeric(df[raw_name], errors="coerce")
            claimed_canonical.add(canonical)

    return df


def _synthesise_time(df: pd.DataFrame) -> pd.DataFrame:
    """Synthesise time_s from row index at the default sample rate."""
    period = 1.0 / _DEFAULT_SAMPLE_RATE_HZ
    df["time_s"] = np.arange(len(df), dtype=np.float64) * period
    return df
