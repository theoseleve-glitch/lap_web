"""AiM RaceStudio .xrk / .xrz adapter (backed by libxrk).

libxrk (MIT) is a from-scratch reader for AiM raw logs — no AiM Windows DLL.
Maps libxrk's channel columns to canonical names and reuses finalize_gps_frame.

Confirmed facts from the AiM official test fixture (m3rlin45/libxrk):
- merged table TIME column name: 'timecodes' (int64, milliseconds)
- GPS Speed unit: m/s (verified: range 0.04–33 m/s in a real racing session)
- GPS_InlineAcc: longitudinal acceleration (m/s^2)
- GPS_LateralAcc: lateral acceleration (m/s^2)
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

# libxrk channel name -> canonical.
# GPS Speed: verified m/s in AiM official sample, mapped directly.
_RENAME: Final[dict[str, str]] = {
    "GPS Latitude": "lat_deg",
    "GPS Longitude": "lon_deg",
    "GPS Altitude": "altitude_m",
    "GPS Speed": "speed_mps",       # confirmed m/s
    "GPS_InlineAcc": "accel_long_mps2",
    "GPS_LateralAcc": "accel_lat_mps2",
    "GPS_Yaw_Rate": "yaw_rate_dps",
    "Engine RPM": "rpm",
    "RPM": "rpm",
}

# Timecodes column is int64 milliseconds in merged table.
_TIMECODES_COL: Final[str] = "timecodes"
_MS_TO_S: Final[float] = 1e-3


class AiMAdapter(BaseAdapter):
    """Adapter for AiM RaceStudio .xrk / .xrz logs via libxrk."""

    FORMAT_NAME: str = "aim_xrk"
    EXTENSIONS: list[str] = [".xrk", ".xrz"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            return 0.9 if path.suffix.lower() in (".xrk", ".xrz") else 0.0
        except Exception:
            logger.debug("AiMAdapter.detect() failed for %s", file_path, exc_info=True)
            return 0.0

    def parse(self, file_path: str,
              progress_cb: Optional[object] = None) -> pd.DataFrame:
        import libxrk  # declared in requirements.txt

        try:
            log = libxrk.aim_xrk(str(file_path))
            raw = log.get_channels_as_table().to_pandas()

            if len(raw) == 0:
                raise ValueError("file produced an empty data table (corrupt or truncated?)")

            df = raw.rename(columns={k: v for k, v in _RENAME.items() if k in raw.columns})

            # If a file carries both "Engine RPM" and "RPM", rename would create two
            # "rpm" columns; keep the first to avoid a duplicate-column DataFrame.
            df = df.loc[:, ~df.columns.duplicated(keep="first")]

            # Convert timecodes (ms int64) to elapsed seconds float.
            if _TIMECODES_COL in df.columns:
                t = pd.to_numeric(df[_TIMECODES_COL], errors="coerce") * _MS_TO_S
                valid_t = t.dropna()
                if valid_t.empty:
                    raise ValueError("AiM .xrk: timecodes column has no valid values")
                df["time_s"] = t - valid_t.iloc[0]
            elif "time_s" not in df.columns:
                raise ValueError(
                    f"no timecodes column found (columns: {list(df.columns)[:20]})"
                )

            keep = [c for c in df.columns if c in CHANNELS]
            df = df[keep]
            df = finalize_gps_frame(df, source="aim_xrk")

        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"AiM .xrk parse failed for {file_path}: {exc}") from exc

        self._channels = list(df.columns)
        self._metadata = {"format": "aim_xrk", "source_file": str(file_path)}
        return df

    def metadata(self) -> dict:
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        return list(self._channels)
