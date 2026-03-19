"""RaceChrono RCZ stub adapter.

RaceChrono .rcz files are a proprietary binary format used by the RaceChrono
mobile app.  This stub directs users to export to CSV from the RaceChrono app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.errors import MissingDependency


class RaceChronoRCZAdapter(BaseAdapter):
    FORMAT_NAME = "racechrono_rcz"
    EXTENSIONS: list[str] = [".rcz"]

    def __init__(self):
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() == ".rcz":
                return 0.3
            return 0.0
        except Exception:
            return 0.0

    def parse(self, file_path: str, progress_cb: Optional[object] = None) -> pd.DataFrame:
        raise MissingDependency(
            "RaceChrono .rcz binary format is not directly readable. "
            "Please export to CSV from the RaceChrono app.",
            format_name=self.FORMAT_NAME,
            file_path=file_path,
            package="RaceChrono app",
            install_hint="Export to CSV from the RaceChrono app instead",
        )

    def metadata(self) -> dict:
        return {}

    def available_channels(self) -> list[str]:
        return []
