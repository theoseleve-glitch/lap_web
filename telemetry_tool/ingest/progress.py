"""
progress.py
-----------
Ingestion progress event contract and callback protocol.

Design
~~~~~~
- ``IngestionProgress`` is a plain dataclass — no framework dependency.
- ``ProgressCallback`` is a ``Protocol`` so any ``Callable[[IngestionProgress], None]``
  satisfies the type checker.
- The dataclass is JSON-serialisable via ``.to_dict()`` for SSE / polling
  endpoints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Progress event
# ---------------------------------------------------------------------------

@dataclass
class IngestionProgress:
    """Snapshot of ingestion pipeline state at a point in time.

    All fields are intentionally simple types so the object can be
    serialised to JSON without custom encoders.
    """

    #: Human-readable pipeline phase.
    phase: str  # "detecting_header" | "reading" | "normalizing" |
                # "flushing" | "merging" | "complete" | "failed"

    #: Zero-based index of the current chunk being processed.
    chunk_idx: int = 0

    #: Total rows ingested so far (across all chunks).
    rows_read: int = 0

    #: Estimated total rows in the file (``file_size / avg_row_bytes``).
    #: Updated as more chunks are read and the estimate improves.
    rows_total_est: int = 0

    #: Bytes consumed from the source file so far.
    bytes_read: int = 0

    #: Total file size in bytes.
    bytes_total: int = 0

    #: Integer percentage (0–100).
    pct: int = 0

    #: Wall-clock seconds since ingestion started.
    elapsed_s: float = 0.0

    #: Estimated seconds remaining (``None`` if not yet calculable).
    eta_s: Optional[float] = None

    #: Current resident memory of the process (MB).  ``-1`` when
    #: measurement is unavailable (psutil not installed).
    memory_mb: float = -1.0

    #: Throughput in megabytes per second.
    rate_mb_s: float = 0.0

    #: Number of Parquet chunk files flushed to the cache directory.
    chunks_flushed: int = 0

    #: Number of malformed CSV rows skipped so far.
    rows_skipped: int = 0

    #: Error message when ``phase == "failed"``, else ``None``.
    error: Optional[str] = None

    # -- Helpers -----------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain ``dict`` suitable for ``json.dumps``."""
        return {
            "phase": self.phase,
            "chunk_idx": self.chunk_idx,
            "rows_read": self.rows_read,
            "rows_total_est": self.rows_total_est,
            "bytes_read": self.bytes_read,
            "bytes_total": self.bytes_total,
            "pct": self.pct,
            "elapsed_s": round(self.elapsed_s, 2),
            "eta_s": round(self.eta_s, 1) if self.eta_s is not None else None,
            "memory_mb": round(self.memory_mb, 1),
            "rate_mb_s": round(self.rate_mb_s, 1),
            "chunks_flushed": self.chunks_flushed,
            "rows_skipped": self.rows_skipped,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Callback protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ProgressCallback(Protocol):
    """Any callable accepting an ``IngestionProgress`` satisfies this."""

    def __call__(self, progress: IngestionProgress) -> None: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Convenience: CLI progress printer
# ---------------------------------------------------------------------------

def cli_progress_printer(p: IngestionProgress) -> None:
    """Print a single-line progress bar to stdout (carriage-return overwrite)."""
    bar_len = 30
    filled = int(bar_len * p.pct / 100)
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
    eta = f"ETA {p.eta_s:.0f}s" if p.eta_s is not None else "ETA --"
    print(
        f"\r[{bar}] {p.pct:3d}% | {p.rows_read:>10,} rows | "
        f"{p.rate_mb_s:5.1f} MB/s | {eta}  ",
        end="",
        flush=True,
    )
    if p.phase in ("complete", "failed"):
        print()  # newline after final update


# ---------------------------------------------------------------------------
# Convenience: null callback (for testing / silence)
# ---------------------------------------------------------------------------

def null_progress(_: IngestionProgress) -> None:
    """No-op callback."""
