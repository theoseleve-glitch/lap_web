"""User configuration for desktop sync.

Reads/writes ``~/.lap/config.json``. Creates the file with defaults if missing.
Thread-safe (atomic write via tempfile + rename).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".lap"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

_DEFAULTS: dict[str, Any] = {
    "auto_upload": False,      # Racer default; World Class overrides to True
    "cloud_api_url": "",       # e.g. "https://api.lap-coach.racing"
    "max_upload_attempts": 5,
}


class UserConfig:
    """Thin wrapper around a JSON config file."""

    def __init__(self, path: Path | None = None):
        self._path = path or _CONFIG_FILE
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Config read failed at %s: %s — using defaults", self._path, exc)
        self._data = dict(_DEFAULTS)
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=str(self._path.parent),
            delete=False, encoding="utf-8",
        )
        try:
            json.dump(self._data, tmp_fd, indent=2)
            tmp_fd.close()
            os.replace(tmp_fd.name, self._path)
        except Exception:
            try:
                Path(tmp_fd.name).unlink()
            except FileNotFoundError:
                pass
            raise

    @property
    def auto_upload(self) -> bool:
        return bool(self._data.get("auto_upload", _DEFAULTS["auto_upload"]))

    @auto_upload.setter
    def auto_upload(self, value: bool) -> None:
        self._data["auto_upload"] = bool(value)
        self._save()

    @property
    def cloud_api_url(self) -> str:
        return str(self._data.get("cloud_api_url") or os.environ.get("NEXT_PUBLIC_API_URL") or "")

    @cloud_api_url.setter
    def cloud_api_url(self, value: str) -> None:
        self._data["cloud_api_url"] = value
        self._save()

    @property
    def max_upload_attempts(self) -> int:
        return int(self._data.get("max_upload_attempts", _DEFAULTS["max_upload_attempts"]))

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()
