"""GPX (GPS Exchange Format) adapter.

Parses standard GPX 1.0/1.1 track files (``<trkpt>`` sequences) into a
canonical GPS DataFrame. Speed/distance/heading are derived from positions +
time when the file omits them (most GPX exports do).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import defusedxml.ElementTree as ET  # XXE / billion-laughs safe (untrusted GPX upload)
import pandas as pd

from telemetry_tool.adapters._gps_interchange import finalize_gps_frame
from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


def _localname(tag: str) -> str:
    """Strip an XML namespace: '{ns}trkpt' -> 'trkpt'."""
    return tag.rsplit("}", 1)[-1]


class GPXAdapter(BaseAdapter):
    """Adapter for GPX track files."""

    FORMAT_NAME: str = "gpx"
    EXTENSIONS: list[str] = [".gpx"]

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
                head = fh.read(2048)
            if "<gpx" in head and "topografix.com/GPX" in head:
                return 0.95
            if "<gpx" in head and "<trkpt" in head:
                return 0.9
            return 0.0
        except Exception:
            logger.debug("GPXAdapter.detect() failed for %s", file_path,
                         exc_info=True)
            return 0.0

    def parse(self, file_path: str,
              progress_cb: Optional[object] = None) -> pd.DataFrame:
        root = ET.parse(file_path).getroot()

        rows: list[dict] = []
        for elem in root.iter():
            if _localname(elem.tag) != "trkpt":
                continue
            lat = elem.get("lat")
            lon = elem.get("lon")
            if lat is None or lon is None:
                continue
            row: dict = {"lat_deg": float(lat), "lon_deg": float(lon)}
            for child in elem:
                name = _localname(child.tag)
                if name == "ele" and child.text:
                    row["altitude_m"] = float(child.text)
                elif name == "time" and child.text:
                    row["_iso_time"] = child.text.strip()
                elif name == "extensions":
                    for ext in child.iter():
                        if _localname(ext.tag) == "speed" and ext.text:
                            row["speed_mps"] = float(ext.text)
            rows.append(row)

        if not rows:
            raise ValueError("GPX file contains no <trkpt> track points")

        df = pd.DataFrame(rows)

        if "_iso_time" in df.columns and df["_iso_time"].notna().any():
            ts = pd.to_datetime(df["_iso_time"], utc=True, errors="coerce")
            t0 = ts[ts.first_valid_index()]
            df["time_s"] = (ts - t0).dt.total_seconds()
            df = df.drop(columns=["_iso_time"])
        else:
            df["time_s"] = [i * 0.1 for i in range(len(df))]
            if "_iso_time" in df.columns:
                df = df.drop(columns=["_iso_time"])

        df = finalize_gps_frame(df, source="gpx")

        self._channels = list(df.columns)
        self._metadata = {"format": "gpx", "source_file": str(file_path)}
        return df

    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)
