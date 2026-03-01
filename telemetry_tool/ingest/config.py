"""
config.py
---------
Feature flag, configuration, and safety limits for the streaming ingest
pipeline.

The ``INGEST_V2`` flag is read from the environment variable
``TELEMETRY_INGEST_V2``.  The flag defaults to **ON** (streaming path).
Set ``TELEMETRY_INGEST_V2=0`` (or ``"false"``/``"no"``/``"off"``) to
force fallback to the legacy ``io_racechrono`` reader.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

_FLAG_ENV: Final[str] = "TELEMETRY_INGEST_V2"
_FALSY: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})


def _read_flag() -> bool:
    """Default **ON**.  Set ``TELEMETRY_INGEST_V2=0`` to force legacy path."""
    raw = os.environ.get(_FLAG_ENV, "1")
    return raw.strip().lower() not in _FALSY


INGEST_V2: bool = _read_flag()
"""``True`` when the streaming ingest pipeline is enabled (default)."""


def refresh_flag() -> bool:
    """Re-read the environment variable (useful for tests)."""
    global INGEST_V2  # noqa: PLW0603
    INGEST_V2 = _read_flag()
    return INGEST_V2


# ---------------------------------------------------------------------------
# Streaming threshold
# ---------------------------------------------------------------------------

#: Files larger than this are routed to the streaming path (when flag is ON).
STREAMING_THRESHOLD_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_TARGET_CHUNK_MEMORY_MB: Final[int] = 64  # target per-chunk memory budget


@dataclass(frozen=True)
class IngestionConfig:
    """Tuning knobs for the streaming ingest pipeline."""

    #: Rows per chunk fed to ``pd.read_csv(chunksize=…)``.
    #: When ``adaptive_chunks`` is True (default), this is overridden by
    #: :meth:`compute_chunk_size` based on column count.
    chunk_size: int = 50_000

    #: Hard ceiling on peak resident memory (MB).  The chunked reader will
    #: try to stay below this by adjusting in-flight chunk count.
    max_memory_mb: int = 512

    #: Directory for Parquet chunk files and the ingestion manifest.
    #: Uses INGEST_CACHE_DIR env var if set, otherwise falls back to
    #: a temp directory (avoids PermissionError in read-only containers).
    cache_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("INGEST_CACHE_DIR", "")
    ) if os.environ.get("INGEST_CACHE_DIR") else Path(tempfile.gettempdir()) / "ingest_cache")

    #: Maximum number of chunks held in memory before flushing to disk.
    max_inflight_chunks: int = 3

    #: Whether to compute a full SHA-256 checksum of the source file
    #: (runs in a background thread).  Disable for faster dev cycles.
    verify_full_checksum: bool = True

    #: Enable adaptive chunk sizing based on column count and memory budget.
    adaptive_chunks: bool = True

    #: Target memory per chunk (MB) when adaptive sizing is enabled.
    target_chunk_memory_mb: int = _TARGET_CHUNK_MEMORY_MB

    def compute_chunk_size(self, n_cols: int) -> int:
        """Compute rows-per-chunk to keep each chunk near the memory target.

        Formula: ``rows = target_bytes / (n_cols * 8_bytes * 2_overhead)``

        - ``8`` bytes per float64 cell
        - ``×2`` accounts for pandas overhead (index, type buffers)

        Returns the fixed ``chunk_size`` when ``adaptive_chunks`` is False.
        """
        if not self.adaptive_chunks or n_cols <= 0:
            return self.chunk_size
        bytes_per_row = n_cols * 8 * 2
        target_bytes = self.target_chunk_memory_mb * 1024 * 1024
        computed = int(target_bytes / max(bytes_per_row, 1))
        limits = IngestionLimits()
        return max(limits.min_chunk_size, min(limits.max_chunk_size, computed))


# ---------------------------------------------------------------------------
# Safety limits (hard ceilings — not user-configurable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IngestionLimits:
    """Absolute ceilings enforced regardless of user configuration."""

    max_file_size_bytes: int = 15 * 1024**3      # 15 GB
    max_rows: int = 100_000_000                    # 100 M rows
    max_columns: int = 200
    max_memory_mb: int = 1024                      # 1 GB absolute ceiling
    max_cache_disk_mb: int = 15_000                # 15 GB temp disk
    max_chunk_size: int = 200_000                  # rows per chunk
    min_chunk_size: int = 5_000                    # floor for adaptive sizing
    max_concurrent_ingestions: int = 2
    max_header_search_lines: int = 100             # lines to scan for header
