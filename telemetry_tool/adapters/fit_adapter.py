"""Garmin / ANT+ FIT (.fit) adapter.

Parses FIT activity files into a canonical GPS DataFrame using the ``fitparse``
library (MIT). Reads 'record' messages: GPS position (semicircles -> degrees),
speed, altitude, and heart rate.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters._gps_interchange import finalize_gps_frame
from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_SEMICIRCLE_TO_DEG: Final[float] = 180.0 / (2 ** 31)


class FITAdapter(BaseAdapter):
    """Adapter for Garmin/ANT+ FIT activity files."""

    FORMAT_NAME: str = "fit"
    EXTENSIONS: list[str] = [".fit"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size < 12:
                return 0.0
            if path.suffix.lower() != ".fit":
                return 0.0
            with path.open("rb") as fh:
                header = fh.read(12)
            return 0.95 if header[8:12] == b".FIT" else 0.0
        except Exception:
            logger.debug("FITAdapter.detect() failed for %s", file_path,
                         exc_info=True)
            return 0.0

    def parse(self, file_path: str,
              progress_cb: Optional[object] = None) -> pd.DataFrame:
        import fitparse  # declared in requirements.txt

        rows: list[dict] = []
        try:
            fitfile = fitparse.FitFile(str(file_path))
            for record in fitfile.get_messages("record"):
                vals = {d.name: d.value for d in record}
                rec_ts = vals.get("timestamp")
                lat = vals.get("position_lat")
                lon = vals.get("position_long")
                if lat is None or lon is None or rec_ts is None:
                    continue
                row: dict = {
                    "lat_deg": lat * _SEMICIRCLE_TO_DEG,
                    "lon_deg": lon * _SEMICIRCLE_TO_DEG,
                    "_ts": rec_ts,
                }
                spd = vals.get("enhanced_speed")
                if spd is None:
                    spd = vals.get("speed")
                if spd is not None:
                    row["speed_mps"] = float(spd)
                alt = vals.get("enhanced_altitude")
                if alt is None:
                    alt = vals.get("altitude")
                if alt is not None:
                    row["altitude_m"] = float(alt)
                hr = vals.get("heart_rate")
                if hr is not None:
                    row["heart_rate_bpm"] = float(hr)
                rows.append(row)
        except fitparse.FitParseError as exc:
            raise ValueError(f"FIT file is corrupt or unreadable: {exc}") from exc

        if len(rows) < 2:
            raise ValueError(f"FIT file has fewer than 2 usable GPS records (got {len(rows)})")

        df = pd.DataFrame(rows)
        ts = pd.to_datetime(df["_ts"])
        df["time_s"] = (ts - ts.iloc[0]).dt.total_seconds()
        df = df.drop(columns=["_ts"])

        df = finalize_gps_frame(df, source="fit")

        self._channels = list(df.columns)
        self._metadata = {"format": "fit", "source_file": str(file_path)}
        return df

    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)
