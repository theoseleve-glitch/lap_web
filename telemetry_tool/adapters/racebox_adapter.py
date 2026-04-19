"""RaceBox CSV telemetry adapter.

Parses RaceBox GPS logger CSV exports with UTC timestamps and km/h speed.
Converts speed from km/h to m/s, UTC timestamps to relative seconds.

Detection
---------
Reads the first few lines and looks for RaceBox-specific headers:
``"UTC Time"``, ``"Speed(km/h)"``, or ``"Speed (km/h)"``.  Returns 0.0
if RaceChrono sentinel columns are found (``"Lap #"``, ``"Time (s)"``).

Parsing
-------
Reads CSV with encoding fallback, renames columns to canonical names, converts
``Speed(km/h)`` → ``speed_mps`` (÷ 3.6), and converts ISO 8601 UTC timestamps
to relative seconds from the first sample.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

# Column name variants RaceBox uses (some firmware versions add spaces)
_SPEED_COLS: Final[tuple[str, ...]] = ("Speed(km/h)", "Speed (km/h)")
_ALT_COLS: Final[tuple[str, ...]] = ("Altitude(m)", "Altitude (m)")

# RaceBox-specific header tokens (any of these indicates a RaceBox file)
_RACEBOX_SIGNALS: Final[frozenset[str]] = frozenset({
    "UTC Time", "Speed(km/h)", "Speed (km/h)",
})

# RaceChrono-specific tokens — if found the file is NOT a RaceBox CSV
_RACECHRONO_SIGNALS: Final[frozenset[str]] = frozenset({
    "Lap #", "Time (s)", "Speed (m/s)",
})

# Simple rename map for non-speed / non-alt / non-time columns
_RENAME_MAP: Final[dict[str, str]] = {
    "Latitude": "lat_deg",
    "Longitude": "lon_deg",
    "Heading": "heading_deg",
}


class RaceBoxCSVAdapter(BaseAdapter):
    """Adapter for RaceBox GPS logger CSV exports."""

    FORMAT_NAME: str = "racebox_csv"
    EXTENSIONS: list[str] = [".csv"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is a RaceBox CSV.

        Reads at most the first 10 lines.  Returns:
        - 0.0  for non-existent, non-.csv, empty, or RaceChrono files
        - 0.75 when a RaceBox-specific header token is found
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return 0.0
            if path.suffix.lower() != ".csv":
                return 0.0
            if path.stat().st_size == 0:
                return 0.0

            lines = _read_head(path, max_lines=10)
            if not lines:
                return 0.0

            # Look for RaceChrono signals — if found, this is NOT a RaceBox file
            for line in lines:
                cells = {c.strip() for c in line.split(",")}
                if cells & _RACECHRONO_SIGNALS:
                    return 0.0

            # Look for RaceBox-specific tokens in the header
            for line in lines:
                cells = {c.strip() for c in line.split(",")}
                if cells & _RACEBOX_SIGNALS:
                    return 0.75

            return 0.0
        except Exception:
            logger.debug(
                "RaceBoxCSVAdapter.detect() failed for %s", file_path, exc_info=True
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
        """Parse a RaceBox CSV into a canonical DataFrame.

        Applies:
        - Column rename to canonical names
        - Speed conversion: km/h → m/s (÷ 3.6)
        - UTC Time → time_s (seconds relative to first row)
        """
        df = _read_csv(file_path)

        # Rename simple columns
        rename = {k: v for k, v in _RENAME_MAP.items() if k in df.columns}
        df = df.rename(columns=rename)

        # Speed: km/h → m/s
        speed_col = next((c for c in _SPEED_COLS if c in df.columns), None)
        if speed_col is not None:
            df["speed_mps"] = pd.to_numeric(df[speed_col], errors="coerce") / 3.6
            if speed_col != "speed_mps":
                df = df.drop(columns=[speed_col])

        # Altitude normalise
        alt_col = next((c for c in _ALT_COLS if c in df.columns), None)
        if alt_col is not None and alt_col != "altitude_m":
            df = df.rename(columns={alt_col: "altitude_m"})

        # UTC Time → time_s (relative seconds from first valid sample)
        if "UTC Time" in df.columns:
            timestamps = pd.to_datetime(df["UTC Time"], utc=True, errors="coerce")
            valid_idx = timestamps.first_valid_index()
            if valid_idx is not None:
                t0 = timestamps[valid_idx]
                df["time_s"] = (timestamps - t0).dt.total_seconds()
            else:
                df["time_s"] = 0.0
            df = df.drop(columns=["UTC Time"])

        # Coerce remaining non-canonical string columns to numeric
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Record channels and basic metadata
        self._channels = list(df.columns)
        self._metadata = {"format": "racebox_csv", "source_file": str(file_path)}

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

def _read_head(path: Path, max_lines: int = 10) -> list[str]:
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
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return [line for i, line in enumerate(fh) if i < max_lines]
    except Exception:
        return []


def _read_csv(file_path: str) -> pd.DataFrame:
    """Read CSV with encoding fallback, returning a DataFrame."""
    path = Path(file_path)
    for enc in _ENCODINGS:
        try:
            df = pd.read_csv(path, encoding=enc)
            df.columns = df.columns.str.strip()
            return df
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(path, encoding="utf-8", errors="replace")
    df.columns = df.columns.str.strip()
    return df
