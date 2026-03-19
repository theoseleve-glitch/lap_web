"""MoTeC .ld/.ldx binary telemetry adapter.

Reads MoTeC i2 binary files using the ``ldparser`` library.
If ``ldparser`` is not installed, raises MissingDependency with install hint.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final, Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.errors import MissingDependency

logger = logging.getLogger(__name__)

# MoTeC channel name → canonical name (regex-based matching like motec_adapter.py)
_CHANNEL_RULES: Final[list[tuple[str, str]]] = [
    (r"(?i)^engine.*rpm$|^rpm$", "rpm"),
    (r"(?i)^ground.*speed|^speed$", "speed_mps"),
    (r"(?i)^throttle", "throttle_pct"),
    (r"(?i)^brake.*pos|^brake$", "brake_pct"),
    (r"(?i)^steer", "steering_angle_deg"),
    (r"(?i)^gear", "gear"),
    (r"(?i)^gps.*lat|^latitude", "lat_deg"),
    (r"(?i)^gps.*lon|^longitude", "lon_deg"),
    (r"(?i)^gps.*alt|^altitude", "altitude_m"),
    (r"(?i)^beacon", "lap_number"),
    (r"(?i)^g.*force.*lat|^lat.*g$", "accel_lat_mps2"),
    (r"(?i)^g.*force.*lon|^long.*g$", "accel_long_mps2"),
    (r"(?i)^yaw", "yaw_rate_dps"),
]


class MoTeCBinaryAdapter(BaseAdapter):
    """Adapter for MoTeC native .ld/.ldx binary telemetry files."""

    FORMAT_NAME: str = "motec_ld"
    EXTENSIONS: list[str] = [".ld", ".ldx"]

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that *file_path* is a MoTeC .ld/.ldx file.

        Checks file extension and reads a small header portion if the file
        exists.  Returns 0.0 on any I/O error or wrong extension.
        """
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() not in (".ld", ".ldx"):
                return 0.0
            # MoTeC .ld files have a specific header structure
            with open(file_path, "rb") as f:
                header = f.read(8)
            if len(header) >= 4:
                return 0.90
            return 0.0
        except Exception:
            logger.debug(
                "MoTeCBinaryAdapter.detect() failed for %s", file_path,
                exc_info=True,
            )
            return 0.0

    def parse(
        self,
        file_path: str,
        progress_cb: Optional[object] = None,
    ) -> pd.DataFrame:
        """Parse a MoTeC .ld/.ldx file into a canonical DataFrame.

        Requires the ``ldparser`` library (``pip install ldparser``).  Raises
        ``MissingDependency`` if the library is not installed.

        Maps MoTeC channel names to canonical names via regex rules and applies
        unit conversions:

        - Throttle/Brake: 0.0-1.0 fraction to 0-100 percentage (when max <= 1.5)
        """
        try:
            import ldparser
        except ImportError:
            raise MissingDependency(
                "ldparser library required for MoTeC .ld/.ldx files",
                format_name=self.FORMAT_NAME,
                file_path=file_path,
                package="ldparser",
                install_hint="pip install ldparser",
            )

        ld = ldparser.ldData(file_path)

        data: dict[str, object] = {}
        time_added = False

        for channel in ld.channels:
            ch_name = channel.name
            canonical = _match_channel(ch_name)

            if canonical:
                data[canonical] = channel.data
            else:
                data[f"raw_{ch_name.lower().replace(' ', '_')}"] = channel.data

            # Generate time from first channel's frequency
            if not time_added and hasattr(channel, "freq") and channel.freq > 0:
                n = len(channel.data)
                dt = 1.0 / channel.freq
                data["time_s"] = [i * dt for i in range(n)]
                time_added = True

        df = pd.DataFrame(data)

        # Unit adjustments (throttle/brake 0-1 → 0-100)
        for col in ("throttle_pct", "brake_pct"):
            if col in df.columns:
                max_val = df[col].max()
                if pd.notna(max_val) and max_val <= 1.5:
                    df[col] = df[col] * 100.0

        self._metadata = {
            "format": "motec_ld",
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


def _match_channel(name: str) -> str | None:
    """Return canonical channel name for *name*, or None if no rule matches."""
    for pattern, canonical in _CHANNEL_RULES:
        if re.match(pattern, name):
            return canonical
    return None
