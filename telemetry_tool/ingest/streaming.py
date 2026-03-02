"""
streaming.py
------------
Streaming header detection and chunked CSV reader for large telemetry files.

Replaces the memory-intensive ``_open_with_fallback()`` (reads entire file
into ``list[str]``) and monolithic ``pd.read_csv()`` (loads full DataFrame)
with O(1)-memory alternatives.

Public API
~~~~~~~~~~
- ``stream_detect_header(path)`` — scan first N lines for a header sentinel.
- ``stream_read_chunks(path, …)`` — yield cleaned DataFrame chunks.
- ``read_racechrono_csv_streamed(path, …)`` — full streaming pipeline returning
  a single merged DataFrame (or a path to the merged Parquet cache).
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Final, Iterator, Optional

import pandas as pd

from telemetry_tool.ingest.config import IngestionConfig, IngestionLimits
from telemetry_tool.ingest.progress import IngestionProgress, ProgressCallback, null_progress

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (mirrored from io_racechrono for consistency; sentinels shared)
# ---------------------------------------------------------------------------

_HEADER_SENTINELS: Final[frozenset[str]] = frozenset({
    "Time (s)", "Time", "UTC Time", "Timestamp", "time_s",
})
_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_NON_NUMERIC_RAW: Final[frozenset[str]] = frozenset({"Lap #", "lap_number"})
_LIMITS: Final[IngestionLimits] = IngestionLimits()


def _normalise_cell(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


# ---------------------------------------------------------------------------
# Streaming header detection
# ---------------------------------------------------------------------------

class StreamingParseError(ValueError):
    """Raised when the streaming parser cannot locate the header row."""


def stream_detect_header(
    path: Path,
    *,
    max_lines: int = _LIMITS.max_header_search_lines,
) -> tuple[int, str, str, dict[str, str]]:
    """Scan the first *max_lines* lines of *path* for a header sentinel.

    Returns
    -------
    (header_row_idx, encoding, delimiter, metadata)
        - header_row_idx: zero-based line index of the data header
        - encoding: the first encoding that succeeded
        - delimiter: ``","`` or ``";"``
        - metadata: key-value pairs parsed from rows above the header

    Memory
    ------
    O(max_lines) — buffers at most 100 lines (~50 KB typical).

    Raises
    ------
    StreamingParseError
        If the sentinel is not found within *max_lines* lines.
    FileNotFoundError
        If *path* does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    for enc in _ENCODINGS:
        try:
            header_idx, delim, meta_lines = _scan_for_header(path, enc, max_lines)
            metadata = _parse_metadata_lines(meta_lines)
            logger.debug(
                "Header found at row %d (encoding=%r, delimiter=%r) in %s",
                header_idx, enc, delim, path.name,
            )
            return header_idx, enc, delim, metadata
        except UnicodeDecodeError:
            logger.debug("Encoding %r failed for %s — trying next.", enc, path.name)
            continue
        except StreamingParseError:
            # Header not found with this encoding — try next in case encoding
            # mangled the sentinel string.
            continue

    # Last resort: utf-8 with replacement chars
    try:
        header_idx, delim, meta_lines = _scan_for_header(
            path, "utf-8", max_lines, errors="replace"
        )
        metadata = _parse_metadata_lines(meta_lines)
        logger.warning(
            "All clean encodings failed for %s; found header with replacement chars.",
            path.name,
        )
        return header_idx, "utf-8", delim, metadata
    except StreamingParseError:
        pass

    raise StreamingParseError(
        f"Could not locate header row (sentinels: {_HEADER_SENTINELS}) in the first "
        f"{max_lines} lines of {path}."
    )


def _scan_for_header(
    path: Path,
    encoding: str,
    max_lines: int,
    *,
    errors: str = "strict",
) -> tuple[int, str, list[str]]:
    """Line-by-line scan.  Returns (header_idx, delimiter, metadata_lines)."""
    meta_lines: list[str] = []
    with open(path, "r", encoding=encoding, errors=errors) as f:
        for idx, line in enumerate(f):
            if idx >= max_lines:
                break
            stripped = line.strip()
            if not stripped:
                meta_lines.append("")
                continue
            if ";" in stripped:
                first_cell = _normalise_cell(stripped.split(";")[0])
            else:
                first_cell = _normalise_cell(stripped.split(",")[0])

            if first_cell in _HEADER_SENTINELS:
                delim = ";" if stripped.count(";") > stripped.count(",") else ","
                return idx, delim, meta_lines

            meta_lines.append(stripped)

    raise StreamingParseError(
        f"Header sentinel (one of {_HEADER_SENTINELS}) not found in first "
        f"{max_lines} lines (encoding={encoding})."
    )


def _parse_metadata_lines(lines: list[str]) -> dict[str, str]:
    """Parse metadata from pre-header lines (identical logic to io_racechrono)."""
    metadata: dict[str, str] = {}
    comment_idx = 0
    for raw in lines:
        if not raw or raw in (",", ";", ",,", ";;"):
            continue
        clean = raw.lstrip("#").strip()
        if not clean:
            continue
        if ":" in clean:
            key, _, value = clean.partition(":")
            key = key.strip()
            value = value.strip()
            if key:
                metadata[key.lower()] = value
                continue
        metadata[f"comment_{comment_idx}"] = clean
        comment_idx += 1
    return metadata


# ---------------------------------------------------------------------------
# In-place numeric coercion (avoids DataFrame.copy())
# ---------------------------------------------------------------------------

def _coerce_numeric_inplace(df: pd.DataFrame) -> pd.DataFrame:
    """Cast parseable columns to float64 **in-place** — no copy.

    This is the memory-efficient replacement for ``_coerce_numeric()``
    in ``io_racechrono.py`` which calls ``df.copy()`` first.
    """
    for col in df.columns:
        if col in _NON_NUMERIC_RAW:
            continue
        coerced = pd.to_numeric(df[col], errors="coerce")
        non_null_before = df[col].notna().sum()
        non_null_after = coerced.notna().sum()
        if non_null_after > 0 or non_null_before == 0:
            df[col] = coerced
    return df


def _strip_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names (whitespace collapse + strip)."""
    rename_map = {col: _normalise_cell(str(col)) for col in df.columns}
    return df.rename(columns=rename_map)


def _drop_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove rows where every value is NaN or empty string."""
    mask = df.replace("", pd.NA).isna().all(axis=1)
    if mask.any():
        return df[~mask].reset_index(drop=True)
    return df


def _read_header_columns(
    path: Path,
    header_idx: int,
    encoding: str,
    delimiter: str,
) -> list[str]:
    """Read just the header line and return normalised column names.

    Memory: O(1) — reads a single line at the header offset.
    """
    with open(path, "r", encoding=encoding, errors="replace") as f:
        for idx, line in enumerate(f):
            if idx == header_idx:
                raw_cols = line.strip().split(delimiter)
                return [_normalise_cell(c) for c in raw_cols if _normalise_cell(c)]
    return []


# ---------------------------------------------------------------------------
# Memory measurement helper
# ---------------------------------------------------------------------------

def _get_memory_mb() -> float:
    """Return current process RSS in MB, or -1 if unavailable."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except (ImportError, OSError):
        return -1.0


# ---------------------------------------------------------------------------
# Chunked CSV reader
# ---------------------------------------------------------------------------

def stream_read_chunks(
    path: Path,
    header_idx: int,
    encoding: str,
    delimiter: str,
    *,
    config: IngestionConfig | None = None,
    progress_cb: ProgressCallback | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield cleaned DataFrame chunks from a RaceChrono CSV.

    Each chunk has:
    - Whitespace-normalised column names
    - Numeric columns coerced to float64 (in-place, no copy)
    - Empty trailing rows removed

    Memory
    ------
    Peak ≈ ``chunk_size × n_columns × 8 bytes × 2`` (one chunk being
    processed + one chunk being yielded to the caller).

    Parameters
    ----------
    path : Path
        Source CSV file.
    header_idx : int
        Zero-based line index of the data header row.
    encoding : str
        File encoding (from ``stream_detect_header``).
    delimiter : str
        Field separator (``","`` or ``";"``)
    config : IngestionConfig, optional
        Tuning knobs.  Defaults to ``IngestionConfig()``.
    progress_cb : ProgressCallback, optional
        Called after each chunk with an ``IngestionProgress`` snapshot.

    Yields
    ------
    pd.DataFrame
        One chunk at a time, cleaned and ready for normalisation/caching.
    """
    if config is None:
        config = IngestionConfig()
    if progress_cb is None:
        progress_cb = null_progress

    decimal = "," if delimiter == ";" else "."
    file_size = path.stat().st_size
    t0 = time.monotonic()

    reader = pd.read_csv(
        path,
        sep=delimiter,
        decimal=decimal,
        skiprows=header_idx,
        encoding=encoding,
        encoding_errors="replace",
        on_bad_lines="skip",
        chunksize=config.chunk_size,
        dtype=str,                # Read as strings — coerce later for safety
    )

    rows_read = 0
    chunk_idx = 0
    avg_row_bytes: float = 150.0  # initial heuristic, refined after first chunk

    for raw_chunk in reader:
        chunk = _strip_headers(raw_chunk)
        chunk = _coerce_numeric_inplace(chunk)
        chunk = _drop_empty_rows(chunk)

        rows_in_chunk = len(chunk)
        rows_read += rows_in_chunk
        chunk_idx += 1

        # Refine bytes-per-row estimate after first real chunk
        if chunk_idx == 1 and rows_in_chunk > 0:
            avg_row_bytes = file_size / max(1, rows_read)

        bytes_read_est = min(int(rows_read * avg_row_bytes), file_size)
        est_total_rows = max(rows_read, int(file_size / max(1, avg_row_bytes)))
        elapsed = time.monotonic() - t0
        rate = (bytes_read_est / 1e6) / max(elapsed, 0.01)
        pct = min(99, int(100 * bytes_read_est / max(file_size, 1)))

        remaining_bytes = max(0, file_size - bytes_read_est)
        eta = (remaining_bytes / max(bytes_read_est / max(elapsed, 0.01), 1)
               if rows_read > 100 else None)

        progress_cb(IngestionProgress(
            phase="reading",
            chunk_idx=chunk_idx,
            rows_read=rows_read,
            rows_total_est=est_total_rows,
            bytes_read=bytes_read_est,
            bytes_total=file_size,
            pct=pct,
            elapsed_s=elapsed,
            eta_s=eta,
            memory_mb=_get_memory_mb(),
            rate_mb_s=rate,
            chunks_flushed=0,  # Updated by caller (cache layer)
        ))

        yield chunk

    # Final progress
    elapsed = time.monotonic() - t0
    progress_cb(IngestionProgress(
        phase="reading",
        chunk_idx=chunk_idx,
        rows_read=rows_read,
        rows_total_est=rows_read,  # Now exact
        bytes_read=file_size,
        bytes_total=file_size,
        pct=100,
        elapsed_s=elapsed,
        eta_s=0.0,
        memory_mb=_get_memory_mb(),
        rate_mb_s=(file_size / 1e6) / max(elapsed, 0.01),
        chunks_flushed=0,
    ))


# ---------------------------------------------------------------------------
# Convenience: full streaming read (returns merged DataFrame)
# ---------------------------------------------------------------------------

def read_racechrono_csv_streamed(
    path: Path,
    *,
    config: IngestionConfig | None = None,
    progress_cb: ProgressCallback | None = None,
) -> pd.DataFrame:
    """Stream-read a RaceChrono CSV and return a single merged DataFrame.

    This is the streaming replacement for ``read_racechrono_csv()``.
    For files that fit in memory the result is identical; for large files
    it uses bounded memory via chunked reading.

    The returned DataFrame has:
    - Normalised column names (whitespace stripped)
    - Numeric columns coerced to float64
    - Empty rows dropped
    - Time column sorted (monotonicity enforced)
    - RaceChrono metadata attached in ``df.attrs["racechrono_metadata"]``

    This function does **not** apply canonical column renaming (that's the
    job of ``normalize_columns`` in ``kart_envelope.ingest.columns``).
    """
    if config is None:
        config = IngestionConfig()
    if progress_cb is None:
        progress_cb = null_progress

    path = Path(path)
    file_size = path.stat().st_size
    logger.info("Streaming read: %s (%s)", path.name, _human_size(file_size))

    # Phase 1: detect header (O(1) memory)
    progress_cb(IngestionProgress(phase="detecting_header", bytes_total=file_size))
    header_idx, encoding, delimiter, metadata = stream_detect_header(path)

    # Phase 1b: adaptive chunk sizing — read column count from header line
    columns = _read_header_columns(path, header_idx, encoding, delimiter)
    effective_chunk_size = config.compute_chunk_size(len(columns))
    if effective_chunk_size != config.chunk_size:
        logger.info(
            "Adaptive chunk sizing: %d cols -> %d rows/chunk (target %d MB)",
            len(columns), effective_chunk_size, config.target_chunk_memory_mb,
        )
    # Override config's chunk_size for this invocation.  IngestionConfig is
    # frozen, so we create a shallow replacement only for the chunk_size field.
    if config.adaptive_chunks and len(columns) > 0:
        config = IngestionConfig(
            chunk_size=effective_chunk_size,
            max_memory_mb=config.max_memory_mb,
            cache_dir=config.cache_dir,
            max_inflight_chunks=config.max_inflight_chunks,
            verify_full_checksum=config.verify_full_checksum,
            adaptive_chunks=False,  # prevent re-computation downstream
            target_chunk_memory_mb=config.target_chunk_memory_mb,
        )

    # Route: small files accumulate in memory; large files use disk cache
    from telemetry_tool.ingest.config import STREAMING_THRESHOLD_BYTES

    if file_size > STREAMING_THRESHOLD_BYTES:
        # Large file path: flush chunks to Parquet cache, merge from disk
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.pool import WriteQueue

        cache = IngestCache.resume_or_create(
            path, header_idx, encoding, delimiter, config,
        )
        wq = WriteQueue(cache, max_depth=config.max_inflight_chunks, progress_cb=progress_cb)

        try:
            for chunk_idx, chunk in enumerate(stream_read_chunks(
                path, header_idx, encoding, delimiter,
                config=config, progress_cb=progress_cb,
            )):
                if cache.has_chunk(chunk_idx):
                    continue  # Resume: skip already-cached chunks
                wq.put(chunk_idx, chunk)
                del chunk

            wq.drain()
        finally:
            wq.close()

        if cache.n_chunks_completed == 0:
            raise StreamingParseError(f"No data found in {path} after header row.")

        df = cache.merge_chunks(progress_cb=progress_cb)
    else:
        # Small file path: accumulate in memory (same as before)
        chunks: list[pd.DataFrame] = []
        for chunk in stream_read_chunks(
            path, header_idx, encoding, delimiter,
            config=config, progress_cb=progress_cb,
        ):
            chunks.append(chunk)

        if not chunks:
            raise StreamingParseError(f"No data found in {path} after header row.")

        progress_cb(IngestionProgress(phase="merging", bytes_total=file_size, pct=95))
        df = pd.concat(chunks, ignore_index=True)
        del chunks

    # Time monotonicity (deferred from chunk level — needs global sort).
    # Use inplace operations to avoid allocating a full copy of the
    # DataFrame (~7+ GB for a 10 GB CSV).
    time_col = "Time (s)"
    if time_col in df.columns and not df[time_col].is_monotonic_increasing:
        n_violations = int((df[time_col].diff().dropna() < 0).sum())
        logger.warning(
            "Time column has %d backward jump(s) across chunk boundaries; sorting.",
            n_violations,
        )
        df.sort_values(time_col, inplace=True)
        df.reset_index(drop=True, inplace=True)

    df.attrs["racechrono_metadata"] = metadata

    progress_cb(IngestionProgress(
        phase="complete",
        rows_read=len(df),
        rows_total_est=len(df),
        bytes_total=file_size,
        bytes_read=file_size,
        pct=100,
        memory_mb=_get_memory_mb(),
    ))

    logger.info(
        "Streamed %s -> %d rows x %d cols (header at row %d, encoding=%s).",
        path.name, len(df), len(df.columns), header_idx, encoding,
    )
    return df


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"
