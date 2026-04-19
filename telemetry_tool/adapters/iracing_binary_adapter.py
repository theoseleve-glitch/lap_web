"""iRacing .ibt binary telemetry adapter.

Reads native iRacing telemetry files using the ``ibt`` library.
If ``ibt`` is not installed, raises MissingDependency with install hint.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.errors import MissingDependency

logger = logging.getLogger(__name__)

# iRacing .ibt magic bytes: first 2 bytes identify the format
_IBT_MAGIC = b"\x03\x00"  # Common ibt header prefix

# Channel mapping: iRacing channel name -> canonical name
_CHANNEL_MAP: dict[str, str] = {
    "SessionTime": "time_s",
    "Speed": "speed_mps",
    "Throttle": "throttle_pct",
    "Brake": "brake_pct",
    "SteeringWheelAngle": "steering_angle_deg",
    "RPM": "rpm",
    "Gear": "gear",
    "Lat": "lat_deg",
    "Lon": "lon_deg",
    "Alt": "altitude_m",
    "LapCurrentLapTime": "raw_lap_time",
    "Lap": "lap_number",
    "LapDist": "distance_m",
    "YawRate": "yaw_rate_dps",
    "LatAccel": "accel_lat_mps2",
    "LongAccel": "accel_long_mps2",
}

_RAD_TO_DEG = 180.0 / math.pi


class IRacingBinaryAdapter(BaseAdapter):
    """Adapter for iRacing native .ibt telemetry files."""

    FORMAT_NAME: str = "iracing_ibt"
    EXTENSIONS: list[str] = [".ibt"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is an iRacing .ibt file.

        Checks file extension and reads magic bytes if the file exists.
        Returns 0.0 on any I/O error or wrong extension.
        """
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() != ".ibt":
                return 0.0
            # Read magic bytes
            with open(file_path, "rb") as f:
                header = f.read(4)
            if len(header) >= 2 and header[:2] == _IBT_MAGIC:
                return 0.95
            # Extension match alone still gives moderate confidence
            return 0.7
        except Exception:
            logger.debug(
                "IRacingBinaryAdapter.detect() failed for %s", file_path,
                exc_info=True,
            )
            return 0.0

    def parse(
        self,
        file_path: str,
        progress_cb: Optional[object] = None,
    ) -> pd.DataFrame:
        """Parse an iRacing .ibt file into a canonical DataFrame.

        Requires the ``ibt`` library (``pip install ibt``).  Raises
        ``MissingDependency`` if the library is not installed.

        Maps iRacing channel names to canonical names and applies unit
        conversions:

        - Throttle/Brake: 0.0-1.0 fraction to 0-100 percentage
        - SteeringWheelAngle: radians to degrees
        """
        try:
            import ibt as ibt_lib
        except ImportError:
            raise MissingDependency(
                "ibt library required for .ibt files",
                format_name=self.FORMAT_NAME,
                file_path=file_path,
                package="ibt",
                install_hint="pip install ibt",
            )

        telemetry = ibt_lib.IBT(file_path)

        # Build DataFrame from available mapped channels
        data: dict[str, object] = {}
        for ibt_name, canonical in _CHANNEL_MAP.items():
            try:
                values = telemetry.get_channel(ibt_name)
                if values is not None:
                    data[canonical] = values
            except (KeyError, AttributeError):
                continue

        # Add any unmapped channels as raw_<name>
        try:
            all_channels = telemetry.channels
        except AttributeError:
            all_channels = []

        for ch_name in all_channels:
            if ch_name not in _CHANNEL_MAP:
                try:
                    values = telemetry.get_channel(ch_name)
                    if values is not None:
                        data[f"raw_{ch_name.lower()}"] = values
                except (KeyError, AttributeError):
                    continue

        df = pd.DataFrame(data)

        # Unit adjustments
        if "throttle_pct" in df.columns:
            df["throttle_pct"] = pd.to_numeric(
                df["throttle_pct"], errors="coerce"
            ) * 100.0  # 0-1 -> 0-100
        if "brake_pct" in df.columns:
            df["brake_pct"] = pd.to_numeric(
                df["brake_pct"], errors="coerce"
            ) * 100.0
        if "steering_angle_deg" in df.columns:
            df["steering_angle_deg"] = pd.to_numeric(
                df["steering_angle_deg"], errors="coerce"
            ) * _RAD_TO_DEG  # rad -> deg

        self._metadata = {
            "format": "iracing_ibt",
            "source": "iracing_ibt",
            "file_name": Path(file_path).name,
            "channel_count": len(df.columns),
            "sample_count": len(df),
        }
        self._channels = [c for c in df.columns if not c.startswith("raw_")]
        return df

    def metadata(self) -> dict:
        """Return session metadata extracted during parsing."""
        return dict(self._metadata)

    def available_channels(self) -> list[str]:
        """Return canonical channel names present after parsing."""
        return list(self._channels)
