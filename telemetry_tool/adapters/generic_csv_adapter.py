"""Generic CSV adapter (catch-all).

Attempts to match any CSV with recognizable telemetry column names using
fuzzy keyword matching.  This adapter intentionally keeps its confidence
below 0.8 so that format-specific adapters always win when they match.

Fuzzy matching rules (applied in order, first match wins per channel):
1. Exact match against canonical name (e.g. column named ``speed_mps``).
2. Case-insensitive keyword match with common patterns.
3. Unit-based disambiguation when multiple candidates exist.

Unit guessing:
- Speed > 200 -> likely km/h -> divide by 3.6
- Speed > 300 -> likely mph -> multiply by 0.44704
- Throttle/brake max ~1.0 -> multiply by 100

This adapter handles F1 game CSV exports, AiM CSV exports, OBD-II logger
exports (Torque Pro, OBD Fusion), VBOX CSV, and any other reasonably-named
CSV with at least 2 recognizable channels.
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

# ---------------------------------------------------------------------------
# Fuzzy matching rules: (test_func, canonical_name)
#
# Each test_func takes a lowercase column name and returns True if it
# matches.  Rules are evaluated in order; the first match for each
# canonical name wins.
# ---------------------------------------------------------------------------

def _match_time(col: str) -> bool:
    """Match time columns: time_s, time (s), time_sec, timestamp, elapsed."""
    return col == "time_s" or ("time" in col and ("_s" in col or "sec" in col))


def _match_speed(col: str) -> bool:
    """Match speed columns: speed, velocity, m_speed, etc."""
    return "speed" in col or "velocity" in col


def _match_throttle(col: str) -> bool:
    return "throttle" in col or col == "tps"


def _match_brake(col: str) -> bool:
    return "brake" in col and "temp" not in col


def _match_steering(col: str) -> bool:
    return "steer" in col


def _match_rpm(col: str) -> bool:
    return "rpm" in col


def _match_gear(col: str) -> bool:
    return "gear" in col


def _match_lat(col: str) -> bool:
    """Match latitude: lat, latitude, lat_deg, gps lat."""
    return col in ("lat", "lat_deg", "latitude", "gps lat", "gps_lat") or "latitude" in col


def _match_lon(col: str) -> bool:
    """Match longitude: lon, longitude, lon_deg, gps long."""
    return col in ("lon", "lon_deg", "longitude", "gps lon", "gps_lon", "gps long") or "longitude" in col


def _match_distance(col: str) -> bool:
    return "distance" in col or col in ("dist", "dist_m")


def _match_lap(col: str) -> bool:
    return "lap" in col and "overlap" not in col


def _match_altitude(col: str) -> bool:
    return "altitude" in col or "elevation" in col or col in ("alt", "alt_m")


def _match_yaw(col: str) -> bool:
    return "yaw" in col


def _match_accel_lat(col: str) -> bool:
    return ("lateral" in col) and ("accel" in col or "_g" in col or " g" in col)


def _match_accel_long(col: str) -> bool:
    return ("longitudinal" in col or ("long" in col and "longitude" not in col)) and ("accel" in col or "_g" in col or " g" in col)


# Ordered list of (matcher, canonical_name).
_FUZZY_RULES: Final[list[tuple[object, str]]] = [
    (_match_time,       "time_s"),
    (_match_speed,      "speed_mps"),
    (_match_throttle,   "throttle_pct"),
    (_match_brake,      "brake_pct"),
    (_match_steering,   "steering_angle_deg"),
    (_match_rpm,        "rpm"),
    (_match_gear,       "gear"),
    (_match_lat,        "lat_deg"),
    (_match_lon,        "lon_deg"),
    (_match_distance,   "distance_m"),
    (_match_lap,        "lap_number"),
    (_match_altitude,   "altitude_m"),
    (_match_yaw,        "yaw_rate_dps"),
    (_match_accel_lat,  "accel_lat_mps2"),
    (_match_accel_long, "accel_long_mps2"),
]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class GenericCSVAdapter(BaseAdapter):
    """Catch-all adapter for any CSV with recognizable telemetry columns."""

    FORMAT_NAME: str = "generic_csv"

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-0.7 based on fuzzy column matching.

        Confidence = min(0.7, 0.1 x matched_channels).  Returns 0.0 if
        fewer than 2 channels match.
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return 0.0

            header_cells = _read_header_cells(path)
            if not header_cells:
                return 0.0

            matched = _count_fuzzy_matches(header_cells)
            if matched < 2:
                return 0.0

            return min(0.7, 0.1 * matched)
        except Exception:
            logger.debug(
                "GenericCSVAdapter.detect() failed for %s", file_path,
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
        """Parse *file_path* into a canonical DataFrame via fuzzy matching."""
        df = _read_csv_with_fallback(file_path)

        self._metadata = {"format": "generic_csv", "sample_count": len(df)}

        df = _fuzzy_rename(df)

        # Unit guessing for speed.
        if "speed_mps" in df.columns:
            df["speed_mps"] = _guess_speed_unit(df["speed_mps"])

        # Unit guessing for throttle/brake (0-1 -> 0-100).
        for col in ("throttle_pct", "brake_pct"):
            if col in df.columns:
                df[col] = _guess_pct_unit(df[col])

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
    """Return header cells from the first non-empty line."""
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


def _count_fuzzy_matches(header_cells: list[str]) -> int:
    """Count how many canonical channels can be matched from header cells."""
    claimed: set[str] = set()
    count = 0

    for cell in header_cells:
        col_lower = cell.strip().lower()
        if not col_lower:
            continue

        # Check exact canonical match first.
        from telemetry_tool.channel_registry import CHANNELS
        if col_lower in CHANNELS:
            if col_lower not in claimed:
                claimed.add(col_lower)
                count += 1
            continue

        # Fuzzy rules.
        for matcher, canonical in _FUZZY_RULES:
            if canonical in claimed:
                continue
            if matcher(col_lower):
                claimed.add(canonical)
                count += 1
                break

    return count


def _read_csv_with_fallback(file_path: str) -> pd.DataFrame:
    """Read CSV with encoding fallback."""
    for enc in _ENCODINGS:
        try:
            return pd.read_csv(file_path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(file_path, encoding="utf-8", errors="replace")


def _fuzzy_rename(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns using fuzzy matching rules."""
    from telemetry_tool.channel_registry import CHANNELS

    rename_map: dict[str, str] = {}
    claimed: set[str] = set()

    for col in df.columns:
        col_lower = col.strip().lower()

        # 1. Exact canonical match.
        if col_lower in CHANNELS and col_lower not in claimed:
            if col != col_lower:
                rename_map[col] = col_lower
            claimed.add(col_lower)
            continue

        # 2. Fuzzy rules.
        for matcher, canonical in _FUZZY_RULES:
            if canonical in claimed:
                continue
            if matcher(col_lower):
                rename_map[col] = canonical
                claimed.add(canonical)
                break

    df = df.rename(columns=rename_map)

    # Coerce all matched canonical columns to numeric.
    for canonical in claimed:
        if canonical in df.columns:
            df[canonical] = pd.to_numeric(df[canonical], errors="coerce")

    return df


def _guess_speed_unit(series: pd.Series) -> pd.Series:
    """Auto-detect speed unit and convert to m/s."""
    max_val = series.max()
    if pd.isna(max_val):
        return series
    if max_val > 300:
        # Likely mph.
        return series * 0.44704
    if max_val > 120:
        # Likely km/h.
        return series / 3.6
    # Likely already m/s.
    return series


def _guess_pct_unit(series: pd.Series) -> pd.Series:
    """If max is around 1.0, scale to 0-100."""
    max_val = series.max()
    if pd.isna(max_val):
        return series
    if max_val <= 1.5:
        return series * 100.0
    return series
