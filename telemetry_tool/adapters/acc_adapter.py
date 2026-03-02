"""Assetto Corsa Competizione (ACC) telemetry adapter.

Handles CSV exports from ACC shared memory dumps and MoTeC exports
originating from ACC.  Maps ACC-specific column names to the canonical
channel registry.

Detection
---------
Reads the first 100 lines and checks for ACC-specific header names:
``speedKmh``, ``gas``, ``brake``, ``steerAngle``, ``rpms``, etc.

Parsing
-------
Reads the full CSV via ``pd.read_csv``, renames columns to canonical
names, and applies unit conversions (km/h -> m/s, 0-1 -> 0-100%,
gear offset -1).  ACC shared memory corner order is 0=FL, 1=FR, 2=RL,
3=RR.

Time synthesis
--------------
If no explicit time column is found (``iCurrentTime``, ``sessionTimeLeft``,
etc.), time_s is synthesized from row index at a default sample period
of 1/30 s (30 Hz shared memory poll rate).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

#: Default sample period for ACC shared memory dumps (30 Hz).
_DEFAULT_SAMPLE_PERIOD_S: Final[float] = 1.0 / 30.0

#: ACC corner order: index -> canonical suffix.
_ACC_CORNERS: Final[tuple[str, ...]] = ("fl", "fr", "rl", "rr")

# ---------------------------------------------------------------------------
# ACC-specific header names used for detection.
# ---------------------------------------------------------------------------
_ACC_CORE_COLUMNS: Final[frozenset[str]] = frozenset({
    "speedKmh", "gas", "brake", "steerAngle", "rpms", "gear",
})

_ACC_EXTENDED_COLUMNS: Final[frozenset[str]] = frozenset({
    "iCurrentTime", "sessionTimeLeft", "currentLap", "Lap",
    "tyreTempI0", "tyreTempI1", "tyreTempI2", "tyreTempI3",
    "tyreTempM0", "tyreTempM1", "tyreTempM2", "tyreTempM3",
    "tyreTempO0", "tyreTempO1", "tyreTempO2", "tyreTempO3",
    "tyrePressure0", "tyrePressure1", "tyrePressure2", "tyrePressure3",
    "brakeTemp0", "brakeTemp1", "brakeTemp2", "brakeTemp3",
    "wheelSlip0", "wheelSlip1", "wheelSlip2", "wheelSlip3",
    "LapTimeMS", "lapTime",
})

# ---------------------------------------------------------------------------
# Column mapping: ACC raw -> (canonical_name, converter_key)
#
# converter_key values:
#   "none"      - no conversion
#   "kmh_to_ms" - divide by 3.6
#   "01_to_pct" - multiply by 100
#   "gear_sub1" - subtract 1 (ACC: 0=R, 1=N, 2=1st -> canonical: -1=R, 0=N, 1=1st)
# ---------------------------------------------------------------------------
_SCALAR_MAP: Final[list[tuple[str, str, str]]] = [
    # Motion
    ("speedKmh",        "speed_mps",            "kmh_to_ms"),
    # Controls
    ("gas",             "throttle_pct",         "01_to_pct"),
    ("brake",           "brake_pct",            "01_to_pct"),
    ("steerAngle",      "steering_angle_deg",   "none"),
    # Engine
    ("rpms",            "rpm",                  "none"),
    ("gear",            "gear",                 "gear_sub1"),
    # Lap
    ("Lap",             "lap_number",           "none"),
    ("currentLap",      "lap_number",           "none"),
]

# Time column candidates (first found wins).
_TIME_CANDIDATES: Final[list[str]] = [
    "iCurrentTime",
    "sessionTimeLeft",
    "timeStamp",
    "time",
    "Time",
]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class ACCAdapter(BaseAdapter):
    """Adapter for Assetto Corsa Competizione CSV exports."""

    FORMAT_NAME: str = "acc"

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is an ACC CSV.

        Looks for ``speedKmh`` or the combination of ``gas`` + ``brake``
        + ``steerAngle`` in the header row.  Returns 0.0 on any I/O
        error.
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
                "ACCAdapter.detect() failed for %s", file_path,
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

        self._metadata = _extract_metadata(df)

        df = _rename_and_convert(df)

        # Synthesize time column if missing.
        if "time_s" not in df.columns:
            df["time_s"] = df.index * _DEFAULT_SAMPLE_PERIOD_S

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
    """Read the first *max_lines* from *path* with encoding fallback."""
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
    """Return the header cells from the first non-empty line of a CSV."""
    lines = _read_head_lines(path, max_lines=20)
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        delim = ";" if stripped.count(";") > stripped.count(",") else ","
        cells = [c.strip().strip('"').strip("'") for c in stripped.split(delim)]
        # A valid header should have at least 2 non-empty cells.
        non_empty = [c for c in cells if c]
        if len(non_empty) >= 2:
            return cells
    return []


def _score_header(header_cells: list[str]) -> float:
    """Score how likely the header belongs to an ACC CSV."""
    cells_set = frozenset(header_cells)

    # Primary detection: speedKmh present.
    has_speed_kmh = "speedKmh" in cells_set

    # Secondary detection: gas + brake + steerAngle all present.
    has_core_trio = {"gas", "brake", "steerAngle"} <= cells_set

    if not has_speed_kmh and not has_core_trio:
        return 0.0

    # Base confidence.
    confidence = 0.7 if has_speed_kmh else 0.6

    # Boost for additional ACC-specific columns.
    all_known = _ACC_CORE_COLUMNS | _ACC_EXTENDED_COLUMNS
    hits = sum(1 for c in header_cells if c in all_known)
    # Subtract the ones already counted in the base check.
    extra = max(0, hits - (1 if has_speed_kmh else 3))
    confidence = min(0.95, confidence + extra * 0.03)

    return confidence


def _read_csv_with_fallback(file_path: str) -> pd.DataFrame:
    """Read a CSV with encoding fallback."""
    for enc in _ENCODINGS:
        try:
            return pd.read_csv(file_path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(file_path, encoding="utf-8", errors="replace")


def _extract_metadata(df: pd.DataFrame) -> dict:
    """Extract basic metadata from column presence."""
    meta: dict = {}
    if "Lap" in df.columns or "currentLap" in df.columns:
        col = "Lap" if "Lap" in df.columns else "currentLap"
        num_col = pd.to_numeric(df[col], errors="coerce")
        meta["total_laps"] = int(num_col.max()) if not num_col.isna().all() else 0
    meta["format"] = "acc"
    meta["sample_count"] = len(df)
    return meta


def _apply_conversion(series: pd.Series, conv: str) -> pd.Series:
    """Apply a unit conversion to a pandas Series."""
    numeric = pd.to_numeric(series, errors="coerce")
    if conv == "kmh_to_ms":
        return numeric / 3.6
    if conv == "01_to_pct":
        return numeric * 100.0
    if conv == "gear_sub1":
        return numeric - 1
    return numeric


def _rename_and_convert(df: pd.DataFrame) -> pd.DataFrame:
    """Rename ACC columns to canonical names and apply conversions."""
    columns_set = set(df.columns)
    claimed: set[str] = set()
    drop_cols: list[str] = []

    for raw_name, canonical, conv in _SCALAR_MAP:
        if canonical in claimed:
            if raw_name in columns_set:
                drop_cols.append(raw_name)
            continue
        if raw_name in columns_set:
            df[canonical] = _apply_conversion(df[raw_name], conv)
            claimed.add(canonical)
            if raw_name != canonical:
                drop_cols.append(raw_name)

    # Time column.
    for time_col in _TIME_CANDIDATES:
        if time_col in columns_set and "time_s" not in claimed:
            numeric = pd.to_numeric(df[time_col], errors="coerce")
            # iCurrentTime and LapTimeMS are in milliseconds.
            if time_col in ("iCurrentTime", "LapTimeMS"):
                df["time_s"] = numeric / 1000.0
            else:
                df["time_s"] = numeric
            claimed.add("time_s")
            drop_cols.append(time_col)
            break

    # 4-corner tire temperature (inner / middle / outer).
    for idx, corner in enumerate(_ACC_CORNERS):
        for zone_letter, zone_suffix in [("I", "i"), ("M", "m"), ("O", "o")]:
            raw = f"tyreTemp{zone_letter}{idx}"
            canonical = f"tire_temp_{corner}_{zone_suffix}"
            if raw in columns_set:
                df[canonical] = pd.to_numeric(df[raw], errors="coerce")
                claimed.add(canonical)
                drop_cols.append(raw)

    # 4-corner tire pressure.
    for idx, corner in enumerate(_ACC_CORNERS):
        raw = f"tyrePressure{idx}"
        canonical = f"tire_pressure_{corner}"
        if raw in columns_set:
            df[canonical] = pd.to_numeric(df[raw], errors="coerce")
            claimed.add(canonical)
            drop_cols.append(raw)

    # 4-corner brake temperature.
    for idx, corner in enumerate(_ACC_CORNERS):
        raw = f"brakeTemp{idx}"
        canonical = f"brake_temp_{corner}"
        if raw in columns_set:
            df[canonical] = pd.to_numeric(df[raw], errors="coerce")
            claimed.add(canonical)
            drop_cols.append(raw)

    # 4-corner wheel slip (-> slip_ratio).
    for idx, corner in enumerate(_ACC_CORNERS):
        raw = f"wheelSlip{idx}"
        canonical = f"slip_ratio_{corner}"
        if raw in columns_set:
            df[canonical] = pd.to_numeric(df[raw], errors="coerce")
            claimed.add(canonical)
            drop_cols.append(raw)

    # Drop original columns that were converted.
    existing_drop = [c for c in drop_cols if c in df.columns]
    if existing_drop:
        df = df.drop(columns=existing_drop, errors="ignore")

    return df
