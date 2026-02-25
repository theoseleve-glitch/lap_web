"""
bench_ingest.py
---------------
Benchmark script for the streaming ingestion pipeline.

Generates synthetic RaceChrono CSV files at configurable sizes (up to 10 GB)
and measures wall-clock time, peak RSS, disk usage, and throughput for both
the legacy and streaming paths.

Usage
~~~~~
::

    # Quick smoke test (100 MB)
    python benchmarks/bench_ingest.py --size-mb 100

    # Full benchmark suite
    python benchmarks/bench_ingest.py --size-mb 100 500 1000 5000 10000

    # Compare legacy vs streaming
    python benchmarks/bench_ingest.py --size-mb 500 --compare

    # Custom chunk size
    python benchmarks/bench_ingest.py --size-mb 1000 --chunk-size 100000

Environment
~~~~~~~~~~~
Requires ``TELEMETRY_INGEST_V2=1`` for streaming path (set automatically).
"""

from __future__ import annotations

import argparse
import csv
import gc
import io
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd


# ---------------------------------------------------------------------------
# Synthetic CSV generator
# ---------------------------------------------------------------------------

_COLUMNS = [
    "Time (s)",
    "Speed (m/s)",
    "Latitude (deg)",
    "Longitude (deg)",
    "Acceleration X (m/s2)",
    "Acceleration Y (m/s2)",
    "Acceleration Z (m/s2)",
    "Gyroscope X (rad/s)",
    "Gyroscope Y (rad/s)",
    "Gyroscope Z (rad/s)",
    "OBD RPM (rpm)",
    "OBD Coolant temp (C)",
    "Lap #",
    "Speed (m/s) *calc",
]

_N_METADATA_LINES = 5


def generate_csv(path: Path, target_bytes: int, *, delimiter: str = ",") -> int:
    """Write a synthetic RaceChrono CSV of approximately *target_bytes*.

    Returns the actual file size in bytes.
    """
    # Metadata preamble
    metadata = [
        "# RaceChrono Pro Export",
        "# Session: Benchmark synthetic data",
        "# Date: 2026-02-24",
        f"# Target size: {target_bytes / (1024**2):.0f} MB",
        "",
    ]

    # Estimate rows needed.  Each row is ~140 bytes with 14 columns.
    header_bytes = len(delimiter.join(_COLUMNS)) + 1
    meta_bytes = sum(len(l) + 1 for l in metadata)
    overhead = meta_bytes + header_bytes
    row_bytes_est = 140  # empirical
    n_rows = max(100, (target_bytes - overhead) // row_bytes_est)

    print(f"  Generating {n_rows:,} rows ({target_bytes / (1024**2):.0f} MB target)...")

    import random
    rng = random.Random(42)

    with open(path, "w", newline="", encoding="utf-8") as f:
        # Metadata
        for line in metadata:
            f.write(line + "\n")

        # Header
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(_COLUMNS)

        # Data rows
        t = 0.0
        batch_size = 50_000
        rows_written = 0
        while rows_written < n_rows:
            batch = min(batch_size, n_rows - rows_written)
            rows = []
            for _ in range(batch):
                t += 0.01 + rng.random() * 0.005
                row = [
                    f"{t:.4f}",
                    f"{rng.uniform(0, 50):.3f}",
                    f"{rng.uniform(43.0, 44.0):.8f}",
                    f"{rng.uniform(-79.0, -78.0):.8f}",
                    f"{rng.uniform(-3, 3):.4f}",
                    f"{rng.uniform(-3, 3):.4f}",
                    f"{rng.uniform(9, 11):.4f}",
                    f"{rng.uniform(-1, 1):.4f}",
                    f"{rng.uniform(-1, 1):.4f}",
                    f"{rng.uniform(-1, 1):.4f}",
                    f"{rng.randint(1000, 8000)}",
                    f"{rng.uniform(80, 105):.1f}",
                    str(rng.randint(1, 30)),
                    f"{rng.uniform(0, 50):.3f}",
                ]
                rows.append(row)
            writer.writerows(rows)
            rows_written += batch

    actual_size = path.stat().st_size
    print(f"  Generated: {path.name} ({actual_size / (1024**2):.1f} MB, {rows_written:,} rows)")
    return actual_size


# ---------------------------------------------------------------------------
# Memory measurement
# ---------------------------------------------------------------------------

def get_peak_rss_mb() -> float:
    """Return peak RSS in MB (platform-dependent)."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        pass

    if platform.system() == "Windows":
        try:
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            psapi = ctypes.windll.psapi
            handle = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return pmc.PeakWorkingSetSize / (1024 * 1024)
        except Exception:
            pass

    return -1.0


def sample_rss_mb() -> float:
    """Return current RSS in MB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return -1.0


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------

def bench_streaming(csv_path: Path, chunk_size: int) -> dict:
    """Run the streaming pipeline and collect metrics."""
    os.environ["TELEMETRY_INGEST_V2"] = "1"

    from telemetry_tool.ingest.config import IngestionConfig, refresh_flag
    from telemetry_tool.ingest.streaming import (
        read_racechrono_csv_streamed,
        stream_detect_header,
        stream_read_chunks,
    )
    from telemetry_tool.ingest.cache import IngestCache
    from telemetry_tool.ingest.pool import WriteQueue
    from telemetry_tool.ingest.progress import IngestionProgress

    refresh_flag()

    config = IngestionConfig(chunk_size=chunk_size)

    # Track peak memory by sampling periodically
    gc.collect()
    rss_before = sample_rss_mb()
    peak_rss = rss_before

    progress_snapshots: list[dict] = []

    def _progress(p: IngestionProgress) -> None:
        nonlocal peak_rss
        current = sample_rss_mb()
        if current > peak_rss:
            peak_rss = current
        progress_snapshots.append(p.to_dict())
        # Print inline progress
        if p.pct % 10 == 0 or p.phase in ("complete", "failed"):
            print(f"    [{p.phase}] {p.pct}% | {p.rows_read:,} rows | "
                  f"{p.rate_mb_s:.1f} MB/s | RSS {current:.0f} MB")

    t0 = time.monotonic()

    # Phase 1: header detection
    header_idx, encoding, delimiter, metadata = stream_detect_header(csv_path)

    # Phase 2: chunked read with disk cache + write queue
    cache_dir = Path(tempfile.mkdtemp(prefix="bench_cache_"))
    config_with_cache = IngestionConfig(
        chunk_size=chunk_size,
        cache_dir=cache_dir,
    )

    cache = IngestCache.create(
        csv_path, header_idx, encoding, delimiter, config_with_cache
    )
    wq = WriteQueue(cache, max_depth=2, progress_cb=_progress)

    chunk_count = 0
    rows_total = 0
    for chunk_idx, chunk_df in enumerate(stream_read_chunks(
        csv_path, header_idx, encoding, delimiter,
        config=config_with_cache, progress_cb=_progress,
    )):
        # Skip already-cached chunks (resume scenario)
        if cache.has_chunk(chunk_idx):
            continue
        wq.put(chunk_idx, chunk_df)
        chunk_count += 1
        rows_total += len(chunk_df)
        del chunk_df  # Release chunk memory

    flushed = wq.drain()
    wq.close()

    # Phase 3: merge
    df = cache.merge_chunks(progress_cb=_progress)

    elapsed = time.monotonic() - t0
    file_size = csv_path.stat().st_size
    peak_rss_final = max(peak_rss, sample_rss_mb())

    # Cache disk usage
    cache_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())

    # Cleanup
    del df
    gc.collect()
    shutil.rmtree(cache_dir, ignore_errors=True)

    return {
        "method": "streaming",
        "file_size_mb": round(file_size / (1024**2), 1),
        "rows": rows_total,
        "chunks": chunk_count,
        "chunks_flushed": flushed,
        "elapsed_s": round(elapsed, 2),
        "throughput_mb_s": round((file_size / (1024**2)) / max(elapsed, 0.01), 1),
        "rss_before_mb": round(rss_before, 0),
        "peak_rss_mb": round(peak_rss_final, 0),
        "rss_delta_mb": round(peak_rss_final - rss_before, 0),
        "cache_disk_mb": round(cache_size / (1024**2), 1),
        "chunk_size": chunk_size,
    }


def bench_legacy(csv_path: Path) -> dict:
    """Run the legacy read_racechrono_csv path and collect metrics."""
    # Ensure flag is OFF
    os.environ.pop("TELEMETRY_INGEST_V2", None)

    from telemetry_tool.ingest.config import refresh_flag
    refresh_flag()

    gc.collect()
    rss_before = sample_rss_mb()

    t0 = time.monotonic()

    from telemetry_tool.io_racechrono import read_racechrono_csv
    df = read_racechrono_csv(csv_path)

    elapsed = time.monotonic() - t0
    file_size = csv_path.stat().st_size
    peak_rss = max(sample_rss_mb(), rss_before)

    n_rows = len(df)
    del df
    gc.collect()

    return {
        "method": "legacy",
        "file_size_mb": round(file_size / (1024**2), 1),
        "rows": n_rows,
        "chunks": 1,
        "chunks_flushed": 0,
        "elapsed_s": round(elapsed, 2),
        "throughput_mb_s": round((file_size / (1024**2)) / max(elapsed, 0.01), 1),
        "rss_before_mb": round(rss_before, 0),
        "peak_rss_mb": round(peak_rss, 0),
        "rss_delta_mb": round(peak_rss - rss_before, 0),
        "cache_disk_mb": 0,
        "chunk_size": 0,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(results: list[dict]) -> None:
    """Pretty-print benchmark results as a table."""
    print("\n" + "=" * 90)
    print("BENCHMARK RESULTS")
    print("=" * 90)

    headers = [
        "Method", "Size(MB)", "Rows", "Chunks", "Time(s)",
        "MB/s", "RSS Before", "Peak RSS", "RSS Delta", "Cache(MB)",
    ]
    col_widths = [12, 10, 12, 8, 8, 8, 12, 10, 10, 10]

    # Header row
    header_line = " | ".join(
        h.ljust(w) for h, w in zip(headers, col_widths)
    )
    print(header_line)
    print("-" * len(header_line))

    for r in results:
        values = [
            r["method"],
            str(r["file_size_mb"]),
            f"{r['rows']:,}",
            str(r["chunks"]),
            str(r["elapsed_s"]),
            str(r["throughput_mb_s"]),
            f"{r['rss_before_mb']:.0f} MB",
            f"{r['peak_rss_mb']:.0f} MB",
            f"+{r['rss_delta_mb']:.0f} MB",
            str(r["cache_disk_mb"]),
        ]
        row_line = " | ".join(v.ljust(w) for v, w in zip(values, col_widths))
        print(row_line)

    print("=" * 90)

    # Memory budget check
    for r in results:
        if r["method"] == "streaming" and r["rss_delta_mb"] > 512:
            print(f"WARNING: Streaming path exceeded 512 MB budget "
                  f"(delta={r['rss_delta_mb']:.0f} MB) for {r['file_size_mb']} MB file")
        elif r["method"] == "streaming":
            print(f"PASS: Streaming path stayed within 512 MB budget "
                  f"(delta={r['rss_delta_mb']:.0f} MB) for {r['file_size_mb']} MB file")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark the streaming ingestion pipeline"
    )
    parser.add_argument(
        "--size-mb",
        type=int,
        nargs="+",
        default=[100],
        help="File sizes to benchmark (MB). Default: 100",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Also run the legacy path for comparison",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=50_000,
        help="Rows per chunk. Default: 50000",
    )
    parser.add_argument(
        "--keep-csv",
        action="store_true",
        help="Don't delete generated CSV files after benchmarking",
    )
    args = parser.parse_args()

    print(f"Platform: {platform.platform()}")
    print(f"Python: {sys.version}")
    print(f"Chunk size: {args.chunk_size:,} rows")
    print()

    results: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="bench_ingest_"))

    try:
        for size_mb in args.size_mb:
            target_bytes = size_mb * 1024 * 1024
            csv_path = tmpdir / f"bench_{size_mb}mb.csv"

            print(f"\n--- {size_mb} MB ---")
            generate_csv(csv_path, target_bytes)

            # Streaming benchmark
            print(f"  Running streaming pipeline...")
            try:
                result = bench_streaming(csv_path, args.chunk_size)
                results.append(result)
            except Exception as exc:
                print(f"  ERROR (streaming): {exc}")
                import traceback
                traceback.print_exc()

            # Legacy comparison
            if args.compare:
                if size_mb > 2000:
                    print(f"  Skipping legacy for {size_mb} MB (too large for in-memory)")
                else:
                    print(f"  Running legacy pipeline...")
                    try:
                        result = bench_legacy(csv_path)
                        results.append(result)
                    except Exception as exc:
                        print(f"  ERROR (legacy): {exc}")

            if not args.keep_csv:
                csv_path.unlink(missing_ok=True)

    finally:
        if not args.keep_csv:
            shutil.rmtree(tmpdir, ignore_errors=True)

    if results:
        print_report(results)


if __name__ == "__main__":
    main()
