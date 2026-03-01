"""
cache.py
--------
Disk-based Parquet cache with manifest for resumable ingestion.

Each ingestion run creates a cache directory keyed by a partial file hash::

    .ingest_cache/
    └── <sha256_partial[:12]>/
        ├── manifest.json
        ├── chunk_0000.parquet
        ├── chunk_0001.parquet
        └── ...

The manifest tracks progress so a crashed/interrupted ingestion can resume
from the last completed chunk instead of re-reading the entire file.

Public API
~~~~~~~~~~
- ``IngestCache.create(path, config)`` — start a new ingestion cache
- ``IngestCache.load(cache_id, cache_root)`` — reload from manifest
- ``IngestCache.resume_or_create(path, config)`` — smart constructor
- ``cache.flush_chunk(chunk_idx, df)`` — write one chunk to Parquet
- ``cache.merge_chunks()`` — concatenate all chunks into final DataFrame
- ``cache.verify()`` — integrity check (row counts, checksum)
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from telemetry_tool.ingest.checksum import sha256_partial
from telemetry_tool.ingest.config import IngestionConfig
from telemetry_tool.ingest.progress import IngestionProgress, ProgressCallback, null_progress

logger = logging.getLogger(__name__)

_PARQUET_COMPRESSION = "snappy"

# Integer types that pandas may upcast to float64 when NaN values appear.
_INT_TYPES = {pa.int8(), pa.int16(), pa.int32(), pa.int64(),
              pa.uint8(), pa.uint16(), pa.uint32(), pa.uint64()}


def _promote_schema(schema: pa.Schema) -> pa.Schema:
    """Promote integer fields to float64 to handle cross-chunk type drift.

    Pandas upcasts int columns to float64 when any chunk contains NaN,
    which causes PyArrow schema mismatches when merging chunks.  By
    promoting all int fields upfront, all chunks share a compatible schema.
    """
    fields = []
    for f in schema:
        if f.type in _INT_TYPES:
            fields.append(pa.field(f.name, pa.float64(), nullable=True, metadata=f.metadata))
        else:
            fields.append(f)
    return pa.schema(fields, metadata=schema.metadata)


# ---------------------------------------------------------------------------
# Disk space safety
# ---------------------------------------------------------------------------

class InsufficientDiskSpace(OSError):
    """Raised when there is not enough free disk space for cache operations."""


def check_disk_space(
    target_dir: Path,
    required_bytes: int,
    *,
    safety_factor: float = 1.5,
    label: str = "",
) -> None:
    """Raise :class:`InsufficientDiskSpace` if free space is too low.

    Parameters
    ----------
    target_dir : Path
        Directory (or parent) to check.  Created if it does not exist.
    required_bytes : int
        Expected bytes to be written.
    safety_factor : float
        Multiplier applied to *required_bytes* (accounts for Parquet
        overhead + temporary merge file).
    label : str
        Human-readable context for the error message.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(str(target_dir)).free
    needed = int(required_bytes * safety_factor)
    if free < needed:
        raise InsufficientDiskSpace(
            f"Insufficient disk space{' for ' + label if label else ''}: "
            f"{free / (1024**3):.1f} GB free, need {needed / (1024**3):.1f} GB "
            f"({required_bytes / (1024**3):.1f} GB data x {safety_factor} safety)"
        )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class IngestionManifest:
    """JSON-serialisable state of an ingestion run."""

    cache_id: str                          # sha256_partial[:12]
    file_path: str
    file_size: int
    sha256_partial: str                    # First 1 MB hash
    sha256_full: Optional[str] = None      # Entire file hash (filled async)
    encoding: str = "utf-8"
    delimiter: str = ","
    header_idx: int = 0
    column_names: list[str] = field(default_factory=list)
    n_chunks_expected: int = 0
    n_chunks_completed: int = 0
    n_rows_total: int = 0                  # Sum of rows across completed chunks
    chunk_row_counts: list[int] = field(default_factory=list)  # per-chunk
    status: str = "pending"                # pending | reading | merging | complete | failed
    error: Optional[str] = None
    started_at: str = ""
    updated_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "IngestionManifest":
        data = json.loads(text)
        return cls(**data)

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "IngestionManifest":
        return cls.from_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Cache manager
# ---------------------------------------------------------------------------

class IngestCache:
    """Manages the on-disk Parquet chunk cache for a single ingestion."""

    def __init__(self, cache_dir: Path, manifest: IngestionManifest) -> None:
        self._cache_dir = cache_dir
        self._manifest = manifest

    @property
    def manifest(self) -> IngestionManifest:
        return self._manifest

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def is_complete(self) -> bool:
        return self._manifest.status == "complete"

    @property
    def n_chunks_completed(self) -> int:
        return self._manifest.n_chunks_completed

    # -- Construction ---------------------------------------------------

    @classmethod
    def create(
        cls,
        source_path: Path,
        header_idx: int,
        encoding: str,
        delimiter: str,
        config: IngestionConfig,
    ) -> "IngestCache":
        """Create a fresh cache directory and manifest."""
        partial_hash = sha256_partial(source_path)
        file_size = source_path.stat().st_size
        cache_id = f"{partial_hash[:12]}_{file_size}"
        cache_root = config.cache_dir
        cache_dir = cache_root / cache_id

        # Disk space pre-check: need ~1.5x file size for chunks + merge output
        check_disk_space(cache_root, file_size, label="ingest cache creation")

        cache_dir.mkdir(parents=True, exist_ok=True)

        est_rows_per_chunk = config.chunk_size
        est_row_bytes = 150  # conservative estimate
        est_total_rows = file_size // est_row_bytes
        est_chunks = max(1, est_total_rows // est_rows_per_chunk)

        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        manifest = IngestionManifest(
            cache_id=cache_id,
            file_path=str(source_path),
            file_size=file_size,
            sha256_partial=partial_hash,
            encoding=encoding,
            delimiter=delimiter,
            header_idx=header_idx,
            n_chunks_expected=est_chunks,
            status="reading",
            started_at=now,
            updated_at=now,
        )
        manifest.save(cache_dir / "manifest.json")
        logger.info("Created ingest cache: %s (%d est. chunks)", cache_dir, est_chunks)
        return cls(cache_dir, manifest)

    @classmethod
    def load_existing(cls, cache_dir: Path) -> "IngestCache":
        """Load an existing cache from its manifest."""
        manifest_path = cache_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No manifest at {manifest_path}")
        manifest = IngestionManifest.load(manifest_path)
        return cls(cache_dir, manifest)

    @classmethod
    def resume_or_create(
        cls,
        source_path: Path,
        header_idx: int,
        encoding: str,
        delimiter: str,
        config: IngestionConfig,
    ) -> "IngestCache":
        """Resume from cache if valid, otherwise create fresh."""
        partial_hash = sha256_partial(source_path)
        file_size = source_path.stat().st_size
        cache_id = f"{partial_hash[:12]}_{file_size}"
        cache_dir = config.cache_dir / cache_id

        if cache_dir.exists() and (cache_dir / "manifest.json").exists():
            try:
                cache = cls.load_existing(cache_dir)
                # Verify the file hasn't changed
                if cache.manifest.sha256_partial == partial_hash:
                    if cache.manifest.status == "complete":
                        logger.info("Cache hit (complete): %s", cache_dir)
                        return cache
                    if cache.manifest.status in ("reading", "merging"):
                        logger.info(
                            "Resuming from chunk %d: %s",
                            cache.manifest.n_chunks_completed, cache_dir,
                        )
                        return cache
                    if cache.manifest.status == "failed":
                        logger.warning("Previous ingestion failed; clearing cache.")
                        cls._clear(cache_dir)
                else:
                    logger.warning(
                        "File changed since last ingest (hash mismatch); clearing cache."
                    )
                    cls._clear(cache_dir)
            except Exception as exc:
                logger.warning("Failed to load cache %s: %s; recreating.", cache_dir, exc)
                cls._clear(cache_dir)

        return cls.create(source_path, header_idx, encoding, delimiter, config)

    @staticmethod
    def _clear(cache_dir: Path) -> None:
        """Remove a cache directory and all its contents."""
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
            logger.debug("Cleared cache: %s", cache_dir)

    # -- Chunk operations -----------------------------------------------

    def _chunk_path(self, idx: int) -> Path:
        return self._cache_dir / f"chunk_{idx:04d}.parquet"

    def flush_chunk(self, chunk_idx: int, df: pd.DataFrame) -> None:
        """Write a single chunk to a Parquet file on disk.

        Updates the manifest with the new chunk's row count.
        """
        dest = self._chunk_path(chunk_idx)
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, dest, compression=_PARQUET_COMPRESSION)

        # Update manifest — idempotent for resume (index-based, not append)
        while len(self._manifest.chunk_row_counts) <= chunk_idx:
            self._manifest.chunk_row_counts.append(0)
        self._manifest.chunk_row_counts[chunk_idx] = len(df)
        self._manifest.n_chunks_completed = max(
            self._manifest.n_chunks_completed, chunk_idx + 1
        )
        self._manifest.n_rows_total = sum(self._manifest.chunk_row_counts)
        if not self._manifest.column_names and len(df.columns) > 0:
            self._manifest.column_names = list(df.columns)
        self._manifest.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._manifest.save(self._cache_dir / "manifest.json")

        logger.debug(
            "Flushed chunk %d: %d rows -> %s (%.1f KB)",
            chunk_idx, len(df), dest.name, dest.stat().st_size / 1024,
        )

    def has_chunk(self, chunk_idx: int) -> bool:
        """Check whether a specific chunk file exists on disk."""
        return self._chunk_path(chunk_idx).exists()

    def load_chunk(self, chunk_idx: int) -> pd.DataFrame:
        """Read a single chunk back from Parquet."""
        path = self._chunk_path(chunk_idx)
        return pq.read_table(path).to_pandas()

    # -- Merge ----------------------------------------------------------

    def merge_chunks_to_parquet(
        self,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> Path:
        """Streaming merge: write all chunks to a single Parquet file.

        Reads one chunk at a time via PyArrow, writes it as a row group to
        the output file, then frees the chunk.  Peak memory is O(1 chunk)
        regardless of total file size.

        Returns the path to the merged Parquet file (NOT loaded into memory).
        After merging, the manifest is updated to ``status="complete"``.
        """
        if progress_cb is None:
            progress_cb = null_progress

        self._manifest.status = "merging"
        self._manifest.save(self._cache_dir / "manifest.json")

        n_chunks = self._manifest.n_chunks_completed
        if n_chunks == 0:
            raise ValueError("No chunks to merge.")

        output_path = self._cache_dir / "_merged.parquet"
        writer: pq.ParquetWriter | None = None
        rows_merged = 0

        progress_cb(IngestionProgress(
            phase="merging",
            chunks_flushed=n_chunks,
            rows_read=0,
            rows_total_est=self._manifest.n_rows_total,
            pct=90,
        ))

        try:
            unified_schema: pa.Schema | None = None
            for idx in range(n_chunks):
                table = pq.read_table(self._chunk_path(idx))
                if writer is None:
                    # Build a unified schema: promote int→float for columns
                    # that may have NaN in later chunks (pandas upcast).
                    unified_schema = _promote_schema(table.schema)
                    writer = pq.ParquetWriter(
                        output_path, unified_schema, compression=_PARQUET_COMPRESSION,
                    )
                # Cast table to the unified schema so all chunks match.
                if table.schema != unified_schema:
                    table = table.cast(unified_schema)
                writer.write_table(table)
                rows_merged += table.num_rows
                del table  # Free chunk memory immediately

                pct = 90 + int(10 * (idx + 1) / n_chunks)
                progress_cb(IngestionProgress(
                    phase="merging",
                    chunk_idx=idx,
                    chunks_flushed=idx + 1,
                    rows_read=rows_merged,
                    rows_total_est=self._manifest.n_rows_total,
                    pct=min(pct, 99),
                ))
        except Exception:
            self._manifest.status = "failed"
            self._manifest.error = "merge failed"
            self._manifest.save(self._cache_dir / "manifest.json")
            raise
        finally:
            if writer is not None:
                writer.close()

        # Verify row count
        expected = sum(self._manifest.chunk_row_counts)
        if rows_merged != expected:
            logger.warning(
                "Row count mismatch after merge: got %d, expected %d",
                rows_merged, expected,
            )

        self._manifest.status = "complete"
        self._manifest.n_rows_total = rows_merged
        self._manifest.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._manifest.save(self._cache_dir / "manifest.json")

        logger.info(
            "Streamed %d chunks -> %d rows into %s",
            n_chunks, rows_merged, output_path.name,
        )
        return output_path

    def merge_chunks(
        self,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> pd.DataFrame:
        """Read all chunk files, merge via streaming ParquetWriter, and
        return a single DataFrame.

        Uses :meth:`merge_chunks_to_parquet` internally so peak memory
        during the merge phase is O(1 chunk), not O(all chunks).
        The final ``read_parquet`` is a single allocation.

        After merging, the manifest is updated to ``status="complete"``.
        Chunk files are NOT deleted — the caller or a cleanup job handles that.

        Note: time-column sorting is the caller's responsibility
        (``read_racechrono_csv_streamed`` handles this) to avoid a
        redundant double-sort that doubles peak memory.
        """
        if progress_cb is None:
            progress_cb = null_progress
        output_path = self.merge_chunks_to_parquet(progress_cb=progress_cb)

        # Single-allocation read of the merged file.
        # Time-column sorting is handled by the caller
        # (read_racechrono_csv_streamed) to avoid a redundant double-sort
        # that would spike memory to ~2x DataFrame size.
        df = pq.read_table(output_path).to_pandas()

        progress_cb(IngestionProgress(
            phase="complete",
            rows_read=len(df),
            rows_total_est=len(df),
            pct=100,
        ))

        logger.info(
            "Merged %d chunks -> %d rows from cache %s",
            self._manifest.n_chunks_completed, len(df), self._cache_dir.name,
        )
        return df

    # -- Verification ---------------------------------------------------

    def verify(self, source_path: Path) -> bool:
        """Check that the cache is consistent with the source file.

        Returns True if the cache appears valid.
        """
        if not (self._cache_dir / "manifest.json").exists():
            return False

        # Check partial hash matches
        current_hash = sha256_partial(source_path)
        if current_hash != self._manifest.sha256_partial:
            logger.warning("Partial hash mismatch — file has changed.")
            return False

        # Check all expected chunk files exist
        for idx in range(self._manifest.n_chunks_completed):
            if not self.has_chunk(idx):
                logger.warning("Missing chunk file: chunk_%04d.parquet", idx)
                return False

        return True

    # -- Cleanup --------------------------------------------------------

    def cleanup(self) -> None:
        """Remove the entire cache directory."""
        self._clear(self._cache_dir)
