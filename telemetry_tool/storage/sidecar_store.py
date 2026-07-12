"""Raw-channel Parquet sidecar storage (W9.T9.2).

Path layout: `{root}/{workspace_id}/{session_id}/raw.parquet`
Compression: snappy (matches `parquet_manager._PARQUET_COMPRESSION`).
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Final

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from telemetry_tool.web.schemas.contracts import SidecarRef, SourceLiteral

logger = logging.getLogger(__name__)

_COMPRESSION: Final[str] = "snappy"
_FILENAME: Final[str] = "raw.parquet"


class SidecarMissing(FileNotFoundError):
    """Sidecar referenced but not found on disk."""


class SidecarStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or os.environ.get("SIDECAR_ROOT", "/data/sidecars"))

    def _path(self, workspace_id: str, session_id: str) -> Path:
        return self.root / workspace_id / session_id / _FILENAME

    def save(
        self,
        *,
        session_id: str,
        workspace_id: str,
        source: SourceLiteral,
        df: pd.DataFrame,
    ) -> SidecarRef:
        target = self._path(workspace_id, session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, target, compression=_COMPRESSION)
        size_bytes = target.stat().st_size
        sha256 = _sha256_of_file(target)
        logger.info(
            "Sidecar saved: ws=%s session=%s bytes=%d sha=%s... source=%s",
            workspace_id, session_id, size_bytes, sha256[:8], source.value,
        )
        return SidecarRef(
            object_key=str(target.relative_to(self.root)).replace(os.sep, "/"),
            format="parquet",
            sha256=sha256,
            size_bytes=size_bytes,
        )

    def load(self, ref: SidecarRef) -> pd.DataFrame:
        path = self.root / ref.object_key
        if not path.exists():
            raise SidecarMissing(f"Sidecar not found at {path}")
        return pq.read_table(path).to_pandas()

    def delete(self, ref: SidecarRef) -> bool:
        path = self.root / ref.object_key
        if not path.exists():
            return False
        path.unlink()
        # Prune empty parents (session dir, then workspace dir).
        try:
            path.parent.rmdir()
            path.parent.parent.rmdir()
        except OSError:
            pass
        return True


def _sha256_of_file(path: Path, chunk_size: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            blk = f.read(chunk_size)
            if not blk:
                break
            h.update(blk)
    return h.hexdigest()
