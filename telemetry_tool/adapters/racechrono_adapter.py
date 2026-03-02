"""RaceChrono CSV adapter.

Wraps the existing ``telemetry_tool.io_racechrono.read_racechrono_csv()``
reader and maps RaceChrono column names to canonical names defined in
``telemetry_tool.channel_registry``.

Detection
---------
Reads the first 100 lines and looks for header sentinels (``"Time (s)"``,
``"Time"``, ``"UTC Time"``, ``"Timestamp"``) as the first cell of a row,
plus RaceChrono-specific column names (``"Speed (m/s)"``, ``"Lap #"``, etc.)
in the same header row.

Parsing
-------
Delegates to ``read_racechrono_csv()`` for the heavy lifting (encoding
fallback, header detection, numeric coercion, monotonicity check).  Then
renames columns to canonical names with unit conversion (G -> m/s^2).

Column mapping mirrors ``kart_envelope/ingest/columns.py``'s ``_RAW_MAP``
with ``*calc`` preference: when both ``"Speed (m/s)"`` and
``"Speed (m/s) *calc"`` exist, the ``*calc`` variant wins.
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

_G: Final[float] = 9.80665  # standard gravity, m/s^2

#: Header sentinels that identify a RaceChrono data header row.
_HEADER_SENTINELS: Final[frozenset[str]] = frozenset({
    "Time (s)", "Time", "UTC Time", "Timestamp", "time_s",
})

#: Encoding fallback chain (mirrors io_racechrono.py).
_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

# ---------------------------------------------------------------------------
# Column mapping: RaceChrono raw -> (canonical_name, needs_G_conversion)
#
# *calc variants are listed BEFORE their non-*calc counterparts so the first
# match wins when both columns are present.
# ---------------------------------------------------------------------------
_COLUMN_MAP: Final[list[tuple[str, str, bool]]] = [
    # Tier 1 — Essential
    ("Time (s)",                              "time_s",               False),
    ("Speed (m/s) *calc",                     "speed_mps",            False),
    ("Speed (m/s)",                           "speed_mps",            False),
    ("Distance (m)",                          "distance_m",           False),
    ("Lap #",                                 "lap_number",           False),
    ("Latitude (deg)",                        "lat_deg",              False),
    ("Longitude (deg)",                       "lon_deg",              False),
    ("Altitude (m)",                          "altitude_m",           False),
    ("GPS Altitude (m)",                      "altitude_m",           False),

    # Tier 2 — Standard (IMU / derived)
    ("Longitudinal acceleration (G) *calc",   "accel_long_mps2",      True),
    ("Longitudinal acceleration (G)",         "accel_long_mps2",      True),
    ("Lateral acceleration (G) *calc",        "accel_lat_mps2",       True),
    ("Lateral acceleration (G)",              "accel_lat_mps2",       True),
    ("Yaw rate (deg/s)",                      "yaw_rate_dps",         False),
    ("Bearing (deg)",                         "heading_deg",          False),
    ("Combined acceleration (G) *calc",       "combined_g",           False),

    # Tier 2 — GPS quality
    ("Satellites (sats)",                     "satellites",            False),
    ("Satellites",                            "satellites",            False),
    ("Accuracy (m)",                          "accuracy_m",           False),

    # Tier 3 — Controls
    ("Throttle position (%)",                 "throttle_pct",         False),
    ("Throttle (%)",                          "throttle_pct",         False),
    ("Brake pressure (%)",                    "brake_pct",            False),
    ("Brake (%)",                             "brake_pct",            False),
    ("Steering angle (deg)",                  "steering_angle_deg",   False),
    ("Steering Angle (deg)",                  "steering_angle_deg",   False),
    ("Steering angle",                        "steering_angle_deg",   False),
    ("Steering (deg)",                        "steering_angle_deg",   False),

    # Position
    ("X-position (m)",                        "x_m",                  False),
    ("X (m)",                                 "x_m",                  False),
    ("Y-position (m)",                        "y_m",                  False),
    ("Y (m)",                                 "y_m",                  False),
]

# Pre-computed sets for fast look-up during detection.
_RACECHRONO_HEADER_NAMES: Final[frozenset[str]] = frozenset(
    raw for raw, _, _ in _COLUMN_MAP
)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class RaceChronoAdapter(BaseAdapter):
    """Adapter for RaceChrono CSV exports."""

    FORMAT_NAME: str = "racechrono"

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is a RaceChrono CSV.

        Reads at most 100 lines.  Looks for:
        1. A header sentinel (``"Time (s)"``, etc.) as the first cell.
        2. Additional RaceChrono-specific column names in that header row.

        Returns 0.0 on any I/O error.
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return 0.0

            # Read first 100 lines with encoding fallback.
            lines = _read_head(path, max_lines=100)
            if not lines:
                return 0.0

            return _score_lines(lines)
        except Exception:
            logger.debug(
                "RaceChronoAdapter.detect() failed for %s", file_path,
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
        """Parse *file_path* via ``read_racechrono_csv()``, then rename to
        canonical column names and apply unit conversions.
        """
        from telemetry_tool.io_racechrono import read_racechrono_csv

        df = read_racechrono_csv(file_path)

        # Extract metadata that io_racechrono attaches to df.attrs.
        self._metadata = dict(df.attrs.get("racechrono_metadata", {}))

        # Rename columns to canonical names with *calc preference.
        df = _rename_to_canonical(df)

        # Store the list of canonical channel names that are present.
        from telemetry_tool.channel_registry import CHANNELS
        self._channels = [
            col for col in df.columns if col in CHANNELS
        ]

        return df

    # ------------------------------------------------------------------
    # metadata
    # ------------------------------------------------------------------
    def metadata(self) -> dict:
        """Return session metadata parsed from the CSV pre-header rows."""
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

def _read_head(path: Path, max_lines: int = 100) -> list[str]:
    """Read the first *max_lines* lines from *path* with encoding fallback."""
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
    # Last resort
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return [next(fh) for _ in range(max_lines)]
    except StopIteration:
        pass
    return []


def _normalise_cell(value: str) -> str:
    """Collapse internal whitespace and strip."""
    import re
    return re.sub(r"\s+", " ", value).strip()


def _score_lines(lines: list[str]) -> float:
    """Score how likely *lines* represent a RaceChrono CSV.

    Returns a confidence between 0.0 and 1.0.
    """
    header_row_idx: int | None = None
    header_cells: list[str] = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Determine delimiter for this line.
        if ";" in stripped:
            first_cell = _normalise_cell(stripped.split(";")[0])
        else:
            first_cell = _normalise_cell(stripped.split(",")[0])

        if first_cell in _HEADER_SENTINELS:
            header_row_idx = idx
            # Parse all cells from this header line.
            delim = ";" if stripped.count(";") > stripped.count(",") else ","
            header_cells = [_normalise_cell(c) for c in stripped.split(delim)]
            break

    if header_row_idx is None:
        return 0.0

    # Base confidence: found the sentinel.
    confidence = 0.6

    # Boost for additional known RaceChrono column names.
    known_hits = sum(
        1 for cell in header_cells if cell in _RACECHRONO_HEADER_NAMES
    )
    # Subtract 1 for the sentinel itself (already counted).
    extra = max(0, known_hits - 1)

    # Each extra known column adds 0.05 confidence, capped at 0.95.
    confidence = min(0.95, confidence + extra * 0.05)

    return confidence


def _rename_to_canonical(df: pd.DataFrame) -> pd.DataFrame:
    """Rename RaceChrono columns to canonical names and convert G -> m/s^2.

    Follows ``*calc`` preference: the first entry in ``_COLUMN_MAP`` for each
    canonical target that exists in *df* wins.  If a ``*calc`` column and its
    plain counterpart both exist, the ``*calc`` value is used and the plain
    column is dropped.
    """
    rename_map: dict[str, str] = {}
    g_convert: list[str] = []
    claimed_canonical: set[str] = set()
    drop_cols: list[str] = []

    columns_set = set(df.columns)

    for raw_name, canonical, is_g in _COLUMN_MAP:
        if canonical in claimed_canonical:
            # This canonical target already claimed by a higher-priority
            # (e.g. *calc) variant.  Drop the duplicate raw column.
            if raw_name in columns_set:
                drop_cols.append(raw_name)
            continue
        if raw_name in columns_set:
            rename_map[raw_name] = canonical
            claimed_canonical.add(canonical)
            if is_g:
                g_convert.append(canonical)

    # Drop duplicate raw columns.
    if drop_cols:
        df = df.drop(columns=drop_cols, errors="ignore")

    # Rename.
    df = df.rename(columns=rename_map)

    # Convert G-force columns to m/s^2.
    for col in g_convert:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce") * _G

    return df
