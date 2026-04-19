"""ImmutableBundleStore — content-addressed raw archive storage.

Layout::

    <base_dir>/
    ├── 7d/
    │   └── 7d9f3b4c...e8.zip     mode 0440
    └── 4b/
        └── 4b9d1f8c...b6.zip     mode 0440

After promote() the file is read-only. Two-level sharding on the first two
hex chars keeps directory sizes bounded.
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

_READ_ONLY_MODE = 0o440


class ImmutableBundleStore:
    def __init__(self, base_dir: Path | str):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _shard(self, checksum: str) -> Path:
        return self._base / checksum[:2]

    def path_for(self, checksum: str) -> Path:
        """Return the canonical absolute path for this checksum (may not exist)."""
        return self._shard(checksum) / f"{checksum}.zip"

    def exists(self, checksum: str) -> bool:
        return self.path_for(checksum).is_file()

    def promote(self, temp_path: Path, checksum: str) -> Path:
        """Move ``temp_path`` to the canonical location, chmod read-only.

        Idempotent: if the destination already exists with the same checksum,
        the temp file is deleted and the existing path is returned.
        """
        temp_path = Path(temp_path)
        dest = self.path_for(checksum)

        if dest.is_file():
            # Another upload promoted the same content first. Drop our temp.
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            return dest

        self._shard(checksum).mkdir(parents=True, exist_ok=True)

        # Atomic-ish move: prefer rename, fall back to copy+unlink across
        # filesystem boundaries (e.g. tmpfs → mounted volume).
        try:
            os.replace(temp_path, dest)
        except OSError:
            shutil.copyfile(temp_path, dest)
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

        self._make_readonly(dest)
        return dest

    @staticmethod
    def _make_readonly(path: Path) -> None:
        try:
            os.chmod(path, _READ_ONLY_MODE)
        except OSError as exc:
            # Windows / unusual filesystems may not honor this; log and move on.
            logger.debug("chmod readonly failed on %s: %s", path, exc)

    def is_readonly(self, path: Path) -> bool:
        st = path.stat().st_mode
        return not bool(st & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
