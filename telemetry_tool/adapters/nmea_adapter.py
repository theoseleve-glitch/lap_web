"""NMEA 0183 GPS log adapter.

Parses raw NMEA sentence logs into a canonical GPS DataFrame. RMC supplies
position, speed (knots) and course; GGA supplies altitude. Detection is
content-based ($GxRMC/$GxGGA), so the shared ``.txt``/``.log`` extensions do
not collide with the CSV adapters.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters._gps_interchange import finalize_gps_frame
from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_KNOTS_TO_MPS: Final[float] = 0.514444


def _nmea_to_deg(value: str, hemi: str) -> float | None:
    """Convert NMEA ddmm.mmmm + hemisphere to signed decimal degrees."""
    if not value or "." not in value:
        return None
    dot = value.index(".")
    deg_len = dot - 2  # last 2 digits before the dot are minutes
    if deg_len < 1:
        return None
    try:
        degrees = float(value[:deg_len])
        minutes = float(value[deg_len:])
    except ValueError:
        return None
    dec = degrees + minutes / 60.0
    return -dec if hemi in ("S", "W") else dec


def _hhmmss_to_seconds(value: str) -> float | None:
    """Convert NMEA hhmmss.ss UTC time-of-day to seconds since midnight."""
    if not value or len(value) < 6:
        return None
    try:
        return int(value[0:2]) * 3600 + int(value[2:4]) * 60 + float(value[4:])
    except ValueError:
        return None


class NMEAAdapter(BaseAdapter):
    """Adapter for raw NMEA 0183 GPS logs."""

    FORMAT_NAME: str = "nmea"
    EXTENSIONS: list[str] = [".nmea", ".log", ".txt"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            with path.open(encoding="utf-8", errors="replace") as fh:
                head = "".join(fh.readline() for _ in range(20))
            if any(tok in head for tok in
                   ("$GPRMC", "$GNRMC", "$GPGGA", "$GNGGA")):
                return 0.85
            return 0.0
        except Exception:
            logger.debug("NMEAAdapter.detect() failed for %s", file_path,
                         exc_info=True)
            return 0.0

    def parse(self, file_path: str,
              progress_cb: Optional[object] = None) -> pd.DataFrame:
        rows: list[dict] = []
        alt_by_time: dict[float, float] = {}

        with Path(file_path).open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line.startswith("$") or "," not in line:
                    continue
                body = line[1:].split("*", 1)[0]
                f = body.split(",")
                stype = f[0][2:] if len(f[0]) >= 5 else f[0]

                if stype == "RMC" and len(f) >= 9 and f[2] == "A":
                    t = _hhmmss_to_seconds(f[1])
                    lat = _nmea_to_deg(f[3], f[4])
                    lon = _nmea_to_deg(f[5], f[6])
                    if t is None or lat is None or lon is None:
                        continue
                    row: dict = {"time_s": t, "lat_deg": lat, "lon_deg": lon}
                    try:
                        if f[7]:
                            row["speed_mps"] = float(f[7]) * _KNOTS_TO_MPS
                        if len(f) > 8 and f[8]:
                            row["heading_deg"] = float(f[8])
                    except ValueError:
                        pass  # malformed speed/course — finalize_gps_frame derives both
                    rows.append(row)

                elif stype == "GGA" and len(f) >= 10:
                    t = _hhmmss_to_seconds(f[1])
                    if t is not None and f[9]:
                        try:
                            alt_by_time[t] = float(f[9])
                        except ValueError:
                            pass

        if not rows:
            raise ValueError("NMEA log contains no valid RMC fixes")

        df = pd.DataFrame(rows)
        if alt_by_time:
            # Exact-float match is safe: RMC and GGA share the same hhmmss.ss per 1 Hz burst.
            df["altitude_m"] = df["time_s"].map(alt_by_time)

        # Time-of-day -> relative seconds from first fix (handle midnight wrap).
        t = df["time_s"].to_numpy(dtype=float)
        t = t - t[0]
        t[t < 0] += 86400.0
        df["time_s"] = t

        df = finalize_gps_frame(df, source="nmea")

        self._channels = list(df.columns)
        self._metadata = {"format": "nmea", "source_file": str(file_path)}
        return df

    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)
