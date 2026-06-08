"""TrackAddict / RaceRender CSV adapter.

Parses RaceRender-format CSV logs (as exported by HP Tuners TrackAddict) into a
canonical GPS DataFrame. The file starts with one or more '# RaceRender Data'
comment lines, then a quoted column header, then comma data rows.

Format reference: https://racerender.com/Developer/DataFormat.html
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters._gps_interchange import finalize_gps_frame
from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.channel_registry import CHANNELS

logger = logging.getLogger(__name__)

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")
_G_TO_MPS2: Final[float] = 9.80665

_RENAME: Final[dict[str, str]] = {
    "Lap": "lap_number",
    "Latitude": "lat_deg",
    "Longitude": "lon_deg",
    "Altitude (m)": "altitude_m",
    "Heading": "heading_deg",
}
_ACCEL: Final[dict[str, str]] = {
    "Accel X": "accel_lat_mps2",
    "Accel Y": "accel_long_mps2",
    "Accel Z": "accel_vert_mps2",
}


class TrackAddictAdapter(BaseAdapter):
    """Adapter for TrackAddict / RaceRender CSV logs."""

    FORMAT_NAME: str = "trackaddict"
    EXTENSIONS: list[str] = [".csv", ".txt"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() not in (".csv", ".txt"):
                return 0.0
            first = ""
            for enc in _ENCODINGS:
                try:
                    with path.open(encoding=enc) as fh:
                        first = fh.readline()
                    break
                except UnicodeDecodeError:
                    continue
            if not first.startswith("# RaceRender Data"):
                return 0.0
            return 0.95 if "TrackAddict" in first else 0.9
        except Exception:
            logger.debug("TrackAddictAdapter.detect() failed for %s",
                         file_path, exc_info=True)
            return 0.0

    def parse(self, file_path: str,
              progress_cb: Optional[object] = None) -> pd.DataFrame:
        path = Path(file_path)

        skip = 0
        enc_used = "utf-8"
        for enc in _ENCODINGS:
            try:
                with path.open(encoding=enc) as fh:
                    for line in fh:
                        if line.startswith("#"):
                            skip += 1
                        else:
                            break
                enc_used = enc
                break
            except UnicodeDecodeError:
                skip = 0
                continue

        df = pd.read_csv(path, skiprows=skip, encoding=enc_used)
        df.columns = df.columns.str.strip()

        df = df.rename(columns={k: v for k, v in _RENAME.items()
                                if k in df.columns})

        if "Time" in df.columns:
            df["time_s"] = pd.to_numeric(df["Time"], errors="coerce")

        if "Speed (Km/h)" in df.columns:
            df["speed_mps"] = pd.to_numeric(df["Speed (Km/h)"],
                                            errors="coerce") / 3.6

        for src, dst in _ACCEL.items():
            if src in df.columns:
                df[dst] = pd.to_numeric(df[src], errors="coerce") * _G_TO_MPS2

        keep = [c for c in df.columns if c in CHANNELS]
        df = df[keep]
        df = finalize_gps_frame(df, source="trackaddict")

        self._channels = list(df.columns)
        self._metadata = {"format": "trackaddict", "source_file": str(file_path)}
        return df

    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)
