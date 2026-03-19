"""Qstarz binary stub adapter.

Qstarz .rcnx/.rcn files are proprietary binary formats used by Qstarz GPS
loggers.  This stub directs users to export to CSV from QRacing software.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.errors import MissingDependency


class QstarzBinaryStub(BaseAdapter):
    FORMAT_NAME = "qstarz_binary"
    EXTENSIONS: list[str] = [".rcnx", ".rcn"]

    def __init__(self):
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                return 0.0
            if path.suffix.lower() in (".rcnx", ".rcn"):
                return 0.3
            return 0.0
        except Exception:
            return 0.0

    def parse(self, file_path: str, progress_cb: Optional[object] = None) -> pd.DataFrame:
        raise MissingDependency(
            "Qstarz binary format (.rcnx/.rcn) is not directly readable. "
            "Please export to CSV from QRacing software.",
            format_name=self.FORMAT_NAME,
            file_path=file_path,
            package="QRacing",
            install_hint="Export to CSV from QRacing software instead",
        )

    def metadata(self) -> dict:
        return {}

    def available_channels(self) -> list[str]:
        return []
