"""Qstarz QRacing CSV export adapter.

Parses Qstarz CSV exports with INDEX/RCR/DATE/TIME columns.
Converts speed from km/h to m/s, parses N/S lat and E/W lon.

Detection
---------
Reads the first few lines and checks for the four Qstarz-specific header
tokens: ``INDEX``, ``RCR``, ``DATE``, ``TIME``.  Returns 0.8 when all four
are present, 0.6 when three are present, 0.0 otherwise.

Parsing
-------
Reads CSV with encoding fallback.  Lat (``LATITUDE N/S``) and lon
(``LONGITUDE E/W``) are parsed from their ``51.5074000N`` / ``000.1278000W``
string form.  Speed is converted from km/h to m/s.  DATE + TIME are combined
and converted to relative seconds from the first row.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

# Qstarz-specific header tokens for detection
_QSTARZ_SIGNALS: Final[frozenset[str]] = frozenset({"INDEX", "RCR", "DATE", "TIME"})


class QstarzCSVAdapter(BaseAdapter):
    """Adapter for Qstarz QRacing GPS logger CSV exports."""

    FORMAT_NAME: str = "qstarz_csv"
    EXTENSIONS: list[str] = [".csv"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is a Qstarz CSV.

        Reads at most the first 10 lines.  Returns:
        - 0.0  for non-existent, non-.csv, or empty files
        - 0.8  when all four Qstarz signals are found (INDEX, RCR, DATE, TIME)
        - 0.6  when three of the four signals are found
        - 0.0  otherwise
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

            for line in lines:
                cells = {c.strip() for c in line.split(",")}
                overlap = cells & _QSTARZ_SIGNALS
                if len(overlap) == 4:
                    return 0.8
                if len(overlap) == 3:
                    return 0.6

            return 0.0
        except Exception:
            logger.debug(
                "QstarzCSVAdapter.detect() failed for %s", file_path, exc_info=True
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
        """Parse a Qstarz CSV into a canonical DataFrame.

        Applies:
        - Lat/lon parsing from N/S, E/W string notation
        - Speed conversion: km/h → m/s (÷ 3.6)
        - DATE + TIME → time_s (relative seconds from first row)
        - HEIGHT → altitude_m
        - HEADING → heading_deg
        """
        df = _read_csv(file_path)

        # Lat/lon: "51.5074000N" → float, "000.1278000W" → -float
        lat_col = next((c for c in df.columns if c.upper().startswith("LATITUDE")), None)
        lon_col = next((c for c in df.columns if c.upper().startswith("LONGITUDE")), None)
        if lat_col is not None:
            df["lat_deg"] = _parse_lat_ns(df[lat_col])
            if lat_col != "lat_deg":
                df = df.drop(columns=[lat_col])
        if lon_col is not None:
            df["lon_deg"] = _parse_lon_ew(df[lon_col])
            if lon_col != "lon_deg":
                df = df.drop(columns=[lon_col])

        # Speed: km/h → m/s
        if "SPEED" in df.columns:
            df["speed_mps"] = pd.to_numeric(df["SPEED"], errors="coerce") / 3.6
            df = df.drop(columns=["SPEED"])

        # Height → altitude_m
        if "HEIGHT" in df.columns:
            df = df.rename(columns={"HEIGHT": "altitude_m"})

        # Heading → heading_deg
        if "HEADING" in df.columns:
            df = df.rename(columns={"HEADING": "heading_deg"})

        # TIME + DATE → time_s (relative seconds from first valid row)
        if "DATE" in df.columns and "TIME" in df.columns:
            datetime_str = df["DATE"].astype(str) + " " + df["TIME"].astype(str)
            # Qstarz format: "2026/03/19 10:00:00.000"
            timestamps = pd.to_datetime(datetime_str, format="%Y/%m/%d %H:%M:%S.%f", errors="coerce")
            valid_idx = timestamps.first_valid_index()
            if valid_idx is not None:
                t0 = timestamps[valid_idx]
                df["time_s"] = (timestamps - t0).dt.total_seconds()
            else:
                df["time_s"] = 0.0
            df = df.drop(columns=["DATE", "TIME"])

        # Coerce remaining object columns to numeric
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Record channels and metadata
        self._channels = list(df.columns)
        self._metadata = {"format": "qstarz_csv", "source_file": str(file_path)}

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
    """Read CSV with encoding fallback, stripping column whitespace."""
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


def _parse_lat_ns(series: pd.Series) -> pd.Series:
    """Parse '51.5074000N' → 51.5074, negate for S."""
    def _convert(val: object) -> float:
        s = str(val).strip()
        if not s:
            return float("nan")
        if s[-1] in ("N", "n"):
            return float(s[:-1])
        if s[-1] in ("S", "s"):
            return -float(s[:-1])
        return float(s)
    return series.apply(_convert)


def _parse_lon_ew(series: pd.Series) -> pd.Series:
    """Parse '000.1278000W' → -0.1278, negate for W."""
    def _convert(val: object) -> float:
        s = str(val).strip()
        if not s:
            return float("nan")
        if s[-1] in ("E", "e"):
            return float(s[:-1])
        if s[-1] in ("W", "w"):
            return -float(s[:-1])
        return float(s)
    return series.apply(_convert)
