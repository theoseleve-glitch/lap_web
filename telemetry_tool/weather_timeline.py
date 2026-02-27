"""
weather_timeline.py
-------------------
Per-lap weather interpolation for telemetry sessions.

Takes hourly weather data (from Open-Meteo via ``meteo_service.fetch_historical_weather``),
a list of lap timestamps (cumulative seconds from session start), and a session start
datetime.  Linearly interpolates continuous weather fields to each lap's time, assigns
categorical ``weather_code`` by nearest hour, and computes per-lap track conditions
(grip_score, track_state, track_temp_est_c) via ``estimate_track_conditions``.

Public API
~~~~~~~~~~
``parse_session_datetime(csv_path)``
    Extract session date/time from CSV metadata headers.

``build_weather_timeline(hourly_weather, lap_timestamps, session_start)``
    Returns a DataFrame with one row per lap.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Fields that are linearly interpolated between hours
_CONTINUOUS_FIELDS = [
    "air_temp_c",
    "humidity_pct",
    "wind_speed_mps",
    "wind_dir_deg",
    "rain_mm",
    "cloud_cover_pct",
]

# All columns in the output DataFrame
REQUIRED_COLUMNS = [
    "lap_number",
    "timestamp",
    "air_temp_c",
    "humidity_pct",
    "wind_speed_mps",
    "wind_dir_deg",
    "rain_mm",
    "cloud_cover_pct",
    "weather_code",
    "grip_score",
    "track_state",
    "track_temp_est_c",
]


# Regex for ISO-8601 timestamp in comment lines (e.g. "# Session: 2026-02-20T09:30:00Z")
_ISO_TIMESTAMP_RE = re.compile(
    r"#\s*\w+:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z?"
)

_MAX_HEADER_LINES = 30


def parse_session_datetime(csv_path: Path) -> Optional[datetime]:
    """
    Extract session date/time from CSV metadata headers.

    RaceChrono CSVs have comment lines starting with ``#`` that may contain
    date/time info.  This function reads the first 30 lines looking for:

    1. RaceChrono ``# Date:`` / ``# Time:`` headers (highest priority)
    2. ISO-8601 timestamp in a comment line, e.g. ``# Session: 2026-02-20T09:30:00Z``
    3. Returns ``None`` if nothing found (caller must prompt user)

    Parameters
    ----------
    csv_path : Path
        Path to the CSV file.

    Returns
    -------
    Optional[datetime]
        Parsed session datetime, or None if no date metadata found.
    """
    csv_path = Path(csv_path)

    date_str: Optional[str] = None
    time_str: Optional[str] = None
    iso_match: Optional[str] = None

    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= _MAX_HEADER_LINES:
                    break

                stripped = line.strip()
                if not stripped.startswith("#"):
                    continue

                # Priority 1: RaceChrono "# Date:" / "# Time:" headers
                lower = stripped.lower()
                if lower.startswith("# date:"):
                    date_str = stripped.split(":", 1)[1].strip()
                elif lower.startswith("# time:"):
                    time_str = stripped.split(":", 1)[1].strip()

                # Priority 2: ISO-8601 timestamp in comment line
                if iso_match is None:
                    m = _ISO_TIMESTAMP_RE.match(stripped)
                    if m:
                        iso_match = m.group(1)

    except OSError:
        logger.warning("Could not read CSV header from %s", csv_path)
        return None

    # Priority 1: explicit Date/Time headers
    if date_str is not None:
        try:
            date_part = datetime.strptime(date_str, "%Y-%m-%d")
            if time_str is not None:
                time_part = datetime.strptime(time_str, "%H:%M:%S")
                return date_part.replace(
                    hour=time_part.hour,
                    minute=time_part.minute,
                    second=time_part.second,
                )
            return date_part  # midnight
        except ValueError:
            logger.warning("Could not parse date/time: date=%r time=%r", date_str, time_str)

    # Priority 2: ISO-8601 from comment line
    if iso_match is not None:
        try:
            return datetime.fromisoformat(iso_match)
        except ValueError:
            logger.warning("Could not parse ISO timestamp: %r", iso_match)

    return None


def _empty_dataframe() -> pd.DataFrame:
    """Return an empty DataFrame with all required columns."""
    return pd.DataFrame(columns=REQUIRED_COLUMNS)


def _parse_hour_time(time_str: str) -> Optional[datetime]:
    """Parse an ISO time string like '2026-02-15T14:00' into a datetime."""
    try:
        return datetime.fromisoformat(time_str)
    except (ValueError, TypeError):
        return None


def _interpolate_field(
    t: float,
    t0: float,
    t1: float,
    v0: Optional[float],
    v1: Optional[float],
) -> Optional[float]:
    """
    Linearly interpolate a single field value between two time points.

    If either value is None, return the non-None value (or None if both are None).
    If t0 == t1 (zero-width interval), return v0.
    """
    if v0 is None and v1 is None:
        return None
    if v0 is None:
        return v1
    if v1 is None:
        return v0
    if t1 == t0:
        return v0
    frac = (t - t0) / (t1 - t0)
    frac = max(0.0, min(1.0, frac))
    return v0 + frac * (v1 - v0)


def _nearest_value(
    t: float,
    t0: float,
    t1: float,
    v0: Any,
    v1: Any,
) -> Any:
    """Return the value from the nearest time point."""
    if abs(t - t0) <= abs(t - t1):
        return v0
    return v1


def build_weather_timeline(
    hourly_weather: Optional[dict[str, Any]],
    lap_timestamps: Optional[List[float]],
    session_start: Optional[datetime],
) -> pd.DataFrame:
    """
    Build a per-lap weather timeline by interpolating hourly weather data.

    Parameters
    ----------
    hourly_weather : dict
        Output of ``meteo_service.fetch_historical_weather()``.
        Must contain ``"hours"`` list with hourly weather entries.
    lap_timestamps : list[float]
        Cumulative seconds from session start for each lap.
    session_start : datetime
        Session start datetime (used to map lap times to absolute time).

    Returns
    -------
    pd.DataFrame
        One row per lap with columns: lap_number, timestamp, air_temp_c,
        humidity_pct, wind_speed_mps, wind_dir_deg, rain_mm, cloud_cover_pct,
        weather_code, grip_score, track_state, track_temp_est_c.
    """
    # --- Graceful handling of None / empty inputs ---
    if not lap_timestamps:
        return _empty_dataframe()

    if hourly_weather is None or session_start is None:
        return _empty_dataframe()

    hours = hourly_weather.get("hours")
    if not hours:
        return _empty_dataframe()

    # --- Parse hourly timestamps into (epoch_seconds, hour_data) pairs ---
    hour_points: list[tuple[float, dict]] = []
    for h in hours:
        dt = _parse_hour_time(h.get("time", ""))
        if dt is None:
            continue
        epoch = dt.timestamp()
        hour_points.append((epoch, h))

    if not hour_points:
        return _empty_dataframe()

    # Sort by time
    hour_points.sort(key=lambda x: x[0])

    session_start_epoch = session_start.timestamp()

    # --- Import estimate_track_conditions ---
    try:
        from meteo_service import estimate_track_conditions
    except ImportError:
        logger.warning("meteo_service not available; track conditions will be empty")
        estimate_track_conditions = None  # type: ignore[assignment]

    # --- Interpolate for each lap ---
    rows: list[dict[str, Any]] = []

    for lap_idx, lap_time_s in enumerate(lap_timestamps):
        lap_epoch = session_start_epoch + lap_time_s
        lap_dt = session_start + timedelta(seconds=lap_time_s)

        row: dict[str, Any] = {
            "lap_number": lap_idx + 1,
            "timestamp": lap_dt.isoformat(),
        }

        # Find the bounding hour pair for interpolation
        if len(hour_points) == 1:
            # Single hour: all laps get the same values
            h_data = hour_points[0][1]
            for field in _CONTINUOUS_FIELDS:
                row[field] = h_data.get(field)
            row["weather_code"] = h_data.get("weather_code")
        else:
            # Find bracketing hours
            t_before, h_before = hour_points[0]
            t_after, h_after = hour_points[-1]

            for i in range(len(hour_points) - 1):
                t0, h0 = hour_points[i]
                t1, h1 = hour_points[i + 1]
                if t0 <= lap_epoch <= t1:
                    t_before, h_before = t0, h0
                    t_after, h_after = t1, h1
                    break
            else:
                # Lap is outside the hour range: clamp to nearest edge
                if lap_epoch < hour_points[0][0]:
                    t_before, h_before = hour_points[0]
                    t_after, h_after = hour_points[0]
                else:
                    t_before, h_before = hour_points[-1]
                    t_after, h_after = hour_points[-1]

            # Interpolate continuous fields
            for field in _CONTINUOUS_FIELDS:
                v0 = h_before.get(field)
                v1 = h_after.get(field)
                row[field] = _interpolate_field(
                    lap_epoch, t_before, t_after, v0, v1
                )

            # Nearest-hour for weather_code (categorical)
            row["weather_code"] = _nearest_value(
                lap_epoch,
                t_before, t_after,
                h_before.get("weather_code"),
                h_after.get("weather_code"),
            )

        # --- Compute track conditions via estimate_track_conditions ---
        if estimate_track_conditions is not None:
            weather_input = {
                "air_temp_c": row.get("air_temp_c"),
                "humidity_pct": row.get("humidity_pct"),
                "rain_mm": row.get("rain_mm"),
                "wind_speed_mps": row.get("wind_speed_mps"),
                "cloud_cover_pct": row.get("cloud_cover_pct"),
            }
            try:
                conditions = estimate_track_conditions(weather_input)
                row["grip_score"] = conditions.get("grip_score")
                row["track_state"] = conditions.get("track_state")
                row["track_temp_est_c"] = conditions.get("track_temp_est_c")
            except Exception as exc:
                logger.warning("estimate_track_conditions failed for lap %d: %s",
                               lap_idx + 1, exc)
                row["grip_score"] = None
                row["track_state"] = None
                row["track_temp_est_c"] = None
        else:
            row["grip_score"] = None
            row["track_state"] = None
            row["track_temp_est_c"] = None

        rows.append(row)

    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    return df
