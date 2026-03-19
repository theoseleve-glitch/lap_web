"""AiM RaceStudio stub adapter.

AiM .xrk/.xrz files require the proprietary AiM SDK (AIMXRK.dll, Windows-only).
This stub directs users to export to CSV from AiM RaceStudio.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.errors import MissingDependency


class AiMAdapter(BaseAdapter):
    FORMAT_NAME = "aim_xrk"
    EXTENSIONS: list[str] = [".xrk", ".xrz", ".drk"]

    def __init__(self):
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() in (".xrk", ".xrz", ".drk"):
                return 0.3
            return 0.0
        except Exception:
            return 0.0

    def parse(self, file_path: str, progress_cb: Optional[object] = None) -> pd.DataFrame:
        raise MissingDependency(
            "AiM SDK (AIMXRK.dll) required for .xrk/.xrz files. "
            "Please export to CSV from AiM RaceStudio.",
            format_name=self.FORMAT_NAME,
            file_path=file_path,
            package="AiM SDK",
            install_hint="Export to CSV from AiM RaceStudio instead",
        )

    def metadata(self) -> dict:
        return {}

    def available_channels(self) -> list[str]:
        return []
