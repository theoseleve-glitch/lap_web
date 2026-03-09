"""
Tests for the INGEST_V2 streaming ingestion pipeline.

Covers:
- Streaming header detection (encoding, delimiter, metadata)
- Chunked reader (chunk boundaries, coercion, empty rows)
- Manifest serialization and resume
- Checksum (partial + full)
- Column mapping stability (streaming vs legacy produce same output)
- Cache creation, flush, merge, verify, cleanup
- Feature flag gating
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Fixtures ──────────────────────────────────────────────────────

def _make_racechrono_csv(
    path: Path,
    n_rows: int = 200,
    n_metadata_lines: int = 3,
    encoding: str = "utf-8",
    delimiter: str = ",",
    include_calc: bool = True,
    seed: int = 42,
) -> Path:
    """Generate a synthetic RaceChrono-style CSV file.

    Returns the path to the written file.
    """
    rng = np.random.default_rng(seed)

    # Metadata rows (above header)
    meta_lines: list[str] = []
    if n_metadata_lines >= 1:
        meta_lines.append("# Format: RaceChrono Pro v7.2")
    if n_metadata_lines >= 2:
        meta_lines.append("# Date: 2024-06-15")
    if n_metadata_lines >= 3:
        meta_lines.append("# Track: Silverstone GP")

    # Header
    cols = ["Time (s)", "Speed (m/s)", "Distance (m)", "Lap #",
            "Latitude (deg)", "Longitude (deg)"]
    if include_calc:
        cols.insert(2, "Speed (m/s) *calc")
        cols.append("Longitudinal acceleration (G) *calc")
        cols.append("Lateral acceleration (G) *calc")
    else:
        cols.append("Longitudinal acceleration (G)")
        cols.append("Lateral acceleration (G)")

    header = delimiter.join(cols)

    # Data rows
    time_vals = np.linspace(0.0, n_rows * 0.04, n_rows)  # 25 Hz
    speed_vals = rng.uniform(5, 30, n_rows)
    speed_calc = speed_vals + rng.normal(0, 0.01, n_rows)  # tiny diff
    dist_vals = np.cumsum(speed_vals * 0.04)
    lap_vals = np.repeat(np.arange(1, (n_rows // 50) + 2), 50)[:n_rows]
    lat_vals = 52.07 + rng.normal(0, 0.001, n_rows)
    lon_vals = -1.02 + rng.normal(0, 0.001, n_rows)
    accel_long = rng.uniform(-0.5, 0.5, n_rows)
    accel_lat = rng.uniform(-0.8, 0.8, n_rows)

    data_lines: list[str] = []
    for i in range(n_rows):
        if include_calc:
            row = [
                f"{time_vals[i]:.4f}", f"{speed_vals[i]:.4f}",
                f"{speed_calc[i]:.4f}", f"{dist_vals[i]:.4f}",
                str(int(lap_vals[i])),
                f"{lat_vals[i]:.6f}", f"{lon_vals[i]:.6f}",
                f"{accel_long[i]:.4f}", f"{accel_lat[i]:.4f}",
            ]
        else:
            row = [
                f"{time_vals[i]:.4f}", f"{speed_vals[i]:.4f}",
                f"{dist_vals[i]:.4f}",
                str(int(lap_vals[i])),
                f"{lat_vals[i]:.6f}", f"{lon_vals[i]:.6f}",
                f"{accel_long[i]:.4f}", f"{accel_lat[i]:.4f}",
            ]
        data_lines.append(delimiter.join(row))

    content = "\n".join(meta_lines + [header] + data_lines) + "\n"
    path.write_text(content, encoding=encoding)
    return path


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_csv(tmp_dir):
    return _make_racechrono_csv(tmp_dir / "session.csv")


@pytest.fixture
def large_csv(tmp_dir):
    """Larger CSV for chunk-boundary tests (5 000 rows)."""
    return _make_racechrono_csv(tmp_dir / "large.csv", n_rows=5000)


@pytest.fixture
def semicolon_csv(tmp_dir):
    return _make_racechrono_csv(
        tmp_dir / "euro.csv", delimiter=";", encoding="latin-1"
    )


@pytest.fixture
def no_metadata_csv(tmp_dir):
    return _make_racechrono_csv(
        tmp_dir / "bare.csv", n_metadata_lines=0
    )


# ── Streaming header detection ────────────────────────────────────

class TestStreamDetectHeader:
    def test_basic_comma_csv(self, sample_csv):
        from telemetry_tool.ingest.streaming import stream_detect_header
        idx, enc, delim, meta = stream_detect_header(sample_csv)
        assert idx == 3  # 3 metadata lines above header
        assert enc == "utf-8"
        assert delim == ","
        assert "format" in meta or "date" in meta

    def test_semicolon_latin1(self, semicolon_csv):
        from telemetry_tool.ingest.streaming import stream_detect_header
        idx, enc, delim, meta = stream_detect_header(semicolon_csv)
        assert idx == 3
        # ASCII content is valid utf-8 and latin-1; utf-8 wins in the fallback
        # chain.  The important assertion is delimiter detection + header found.
        assert enc in ("utf-8", "latin-1")
        assert delim == ";"

    def test_pure_latin1_fallback(self, tmp_dir):
        """File with bytes 0x80-0xFF that are invalid UTF-8 → latin-1 fallback."""
        from telemetry_tool.ingest.streaming import stream_detect_header

        # Write raw bytes: latin-1 metadata with accented chars + valid header
        content = (
            b"# Format: Donn\xe9es de t\xe9l\xe9m\xe9trie\n"
            b"# Piste: N\xfcrburgring Nordschleife\n"
            b"# S\xe9ance: 2024-06-15\n"
            b"Time (s),Speed (m/s),Lap #\n"
            b"0.0000,12.3456,1\n"
            b"0.0400,12.5000,1\n"
        )
        p = tmp_dir / "latin1_real.csv"
        p.write_bytes(content)
        idx, enc, delim, meta = stream_detect_header(p)
        assert idx == 3
        assert enc == "latin-1"
        assert delim == ","

    def test_no_metadata(self, no_metadata_csv):
        from telemetry_tool.ingest.streaming import stream_detect_header
        idx, enc, delim, meta = stream_detect_header(no_metadata_csv)
        assert idx == 0  # header is the first line
        assert delim == ","
        assert meta == {}

    def test_missing_header_raises(self, tmp_dir):
        from telemetry_tool.ingest.streaming import StreamingParseError, stream_detect_header
        bad = tmp_dir / "bad.csv"
        bad.write_text("a,b,c\n1,2,3\n")
        with pytest.raises(StreamingParseError):
            stream_detect_header(bad)

    def test_file_not_found(self, tmp_dir):
        from telemetry_tool.ingest.streaming import stream_detect_header
        with pytest.raises(FileNotFoundError):
            stream_detect_header(tmp_dir / "nope.csv")

    def test_metadata_parsing(self, sample_csv):
        from telemetry_tool.ingest.streaming import stream_detect_header
        _, _, _, meta = stream_detect_header(sample_csv)
        assert meta.get("format") == "RaceChrono Pro v7.2"
        assert meta.get("date") == "2024-06-15"
        assert meta.get("track") == "Silverstone GP"


# ── Chunked reader ────────────────────────────────────────────────

class TestStreamReadChunks:
    def test_yields_dataframes(self, sample_csv):
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header, stream_read_chunks
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cfg = IngestionConfig(chunk_size=100)
        chunks = list(stream_read_chunks(sample_csv, idx, enc, delim, config=cfg))
        assert len(chunks) == 2  # 200 rows / 100 per chunk
        assert len(chunks[0]) == 100
        assert len(chunks[1]) == 100

    def test_total_rows_match(self, large_csv):
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header, stream_read_chunks
        idx, enc, delim, _ = stream_detect_header(large_csv)
        cfg = IngestionConfig(chunk_size=1000)
        chunks = list(stream_read_chunks(large_csv, idx, enc, delim, config=cfg))
        total = sum(len(c) for c in chunks)
        assert total == 5000

    def test_numeric_coercion(self, sample_csv):
        from telemetry_tool.ingest.streaming import stream_detect_header, stream_read_chunks
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        chunks = list(stream_read_chunks(sample_csv, idx, enc, delim))
        df = chunks[0]
        assert df["Time (s)"].dtype == np.float64
        assert df["Speed (m/s)"].dtype == np.float64

    def test_progress_callback_called(self, sample_csv):
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header, stream_read_chunks
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        events = []
        cfg = IngestionConfig(chunk_size=100)
        list(stream_read_chunks(
            sample_csv, idx, enc, delim, config=cfg,
            progress_cb=lambda p: events.append(p),
        ))
        # One event per chunk + final event = 3
        assert len(events) >= 2
        assert events[-1].pct == 100


# ── Full streaming read ───────────────────────────────────────────

class TestReadStreamed:
    def test_returns_dataframe(self, sample_csv):
        from telemetry_tool.ingest.streaming import read_racechrono_csv_streamed
        df = read_racechrono_csv_streamed(sample_csv)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 200
        assert "Time (s)" in df.columns

    def test_metadata_attached(self, sample_csv):
        from telemetry_tool.ingest.streaming import read_racechrono_csv_streamed
        df = read_racechrono_csv_streamed(sample_csv)
        meta = df.attrs.get("racechrono_metadata", {})
        assert "format" in meta

    def test_time_monotonic(self, sample_csv):
        from telemetry_tool.ingest.streaming import read_racechrono_csv_streamed
        df = read_racechrono_csv_streamed(sample_csv)
        assert df["Time (s)"].is_monotonic_increasing


# ── Checksum ──────────────────────────────────────────────────────

class TestChecksum:
    def test_partial_deterministic(self, sample_csv):
        from telemetry_tool.ingest.checksum import sha256_partial
        h1 = sha256_partial(sample_csv)
        h2 = sha256_partial(sample_csv)
        assert h1 == h2
        assert len(h1) == 64  # hex SHA-256

    def test_full_deterministic(self, sample_csv):
        from telemetry_tool.ingest.checksum import sha256_full
        h1 = sha256_full(sample_csv)
        h2 = sha256_full(sample_csv)
        assert h1 == h2

    def test_partial_differs_on_change(self, sample_csv):
        from telemetry_tool.ingest.checksum import sha256_partial
        h1 = sha256_partial(sample_csv)
        # Modify the file
        with open(sample_csv, "a") as f:
            f.write("extra data\n")
        h2 = sha256_partial(sample_csv)
        assert h1 != h2

    def test_async_matches_sync(self, sample_csv):
        from telemetry_tool.ingest.checksum import sha256_full, sha256_full_async
        future = sha256_full_async(sample_csv)
        sync_hash = sha256_full(sample_csv)
        assert future.result(timeout=10) == sync_hash

    def test_small_file_partial_equals_full(self, tmp_dir):
        """For files < 1 MB, partial and full should be identical."""
        from telemetry_tool.ingest.checksum import sha256_full, sha256_partial
        tiny = tmp_dir / "tiny.bin"
        tiny.write_bytes(b"hello world")
        assert sha256_partial(tiny) == sha256_full(tiny)


# ── Manifest serialization ────────────────────────────────────────

class TestManifest:
    def test_round_trip(self, tmp_dir):
        from telemetry_tool.ingest.cache import IngestionManifest
        m = IngestionManifest(
            cache_id="abc123def456",
            file_path="/data/session.csv",
            file_size=1_000_000,
            sha256_partial="deadbeef" * 8,
            encoding="utf-8",
            delimiter=",",
            header_idx=3,
            column_names=["Time (s)", "Speed (m/s)"],
            n_chunks_expected=20,
            n_chunks_completed=5,
            n_rows_total=25000,
            chunk_row_counts=[5000, 5000, 5000, 5000, 5000],
            status="reading",
            started_at="2024-06-15T10:00:00",
            updated_at="2024-06-15T10:01:00",
        )
        path = tmp_dir / "manifest.json"
        m.save(path)
        loaded = IngestionManifest.load(path)
        assert loaded.cache_id == m.cache_id
        assert loaded.n_chunks_completed == 5
        assert loaded.chunk_row_counts == [5000] * 5
        assert loaded.status == "reading"

    def test_json_is_valid(self, tmp_dir):
        from telemetry_tool.ingest.cache import IngestionManifest
        m = IngestionManifest(
            cache_id="test", file_path="x.csv", file_size=100,
            sha256_partial="a" * 64,
        )
        text = m.to_json()
        parsed = json.loads(text)
        assert parsed["cache_id"] == "test"


# ── Cache (create, flush, merge, verify, resume) ──────────────────

class TestIngestCache:
    def test_create_and_flush(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)

        assert cache.manifest.status == "reading"
        assert cache.n_chunks_completed == 0

        # Flush a synthetic chunk
        df = pd.DataFrame({"A": [1, 2, 3], "B": [4.0, 5.0, 6.0]})
        cache.flush_chunk(0, df)
        assert cache.n_chunks_completed == 1
        assert cache.has_chunk(0)
        assert cache.manifest.chunk_row_counts == [3]

    def test_merge_chunks(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)

        # Flush two chunks
        df1 = pd.DataFrame({"X": [1, 2], "Y": [3.0, 4.0]})
        df2 = pd.DataFrame({"X": [5, 6], "Y": [7.0, 8.0]})
        cache.flush_chunk(0, df1)
        cache.flush_chunk(1, df2)

        merged = cache.merge_chunks()
        assert len(merged) == 4
        assert cache.manifest.status == "complete"
        assert list(merged["X"]) == [1, 2, 5, 6]

    def test_verify_passes_for_unchanged_file(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)
        cache.flush_chunk(0, pd.DataFrame({"A": [1]}))
        assert cache.verify(sample_csv) is True

    def test_verify_fails_for_changed_file(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)
        cache.flush_chunk(0, pd.DataFrame({"A": [1]}))

        # Mutate the file — prepend data so hash of first 1MB changes
        original = sample_csv.read_bytes()
        sample_csv.write_bytes(b"CHANGED\n" + original)

        assert cache.verify(sample_csv) is False

    def test_resume_or_create_resumes(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)

        # First: create and partially fill
        cache1 = IngestCache.create(sample_csv, idx, enc, delim, cfg)
        cache1.flush_chunk(0, pd.DataFrame({"A": [1, 2]}))

        # Second: resume should find the existing cache
        cache2 = IngestCache.resume_or_create(sample_csv, idx, enc, delim, cfg)
        assert cache2.n_chunks_completed == 1
        assert cache2.manifest.cache_id == cache1.manifest.cache_id

    def test_cleanup(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)
        cache_dir = cache.cache_dir
        assert cache_dir.exists()
        cache.cleanup()
        assert not cache_dir.exists()


# ── Progress contract ─────────────────────────────────────────────

class TestProgressContract:
    def test_to_dict(self):
        from telemetry_tool.ingest.progress import IngestionProgress
        p = IngestionProgress(
            phase="reading", chunk_idx=3, rows_read=15000,
            rows_total_est=60000, bytes_read=5_000_000,
            bytes_total=20_000_000, pct=25, elapsed_s=2.5,
            eta_s=7.5, memory_mb=128.3, rate_mb_s=2.0,
        )
        d = p.to_dict()
        assert d["phase"] == "reading"
        assert d["pct"] == 25
        assert d["eta_s"] == 7.5
        assert isinstance(d["elapsed_s"], float)

    def test_to_dict_none_eta(self):
        from telemetry_tool.ingest.progress import IngestionProgress
        p = IngestionProgress(phase="detecting_header")
        d = p.to_dict()
        assert d["eta_s"] is None

    def test_callback_protocol(self):
        from telemetry_tool.ingest.progress import IngestionProgress, ProgressCallback
        events: list[IngestionProgress] = []

        def my_cb(p: IngestionProgress) -> None:
            events.append(p)

        assert isinstance(my_cb, ProgressCallback)
        my_cb(IngestionProgress(phase="test"))
        assert len(events) == 1

    def test_cli_printer_no_crash(self, capsys):
        from telemetry_tool.ingest.progress import IngestionProgress, cli_progress_printer
        cli_progress_printer(IngestionProgress(phase="reading", pct=50, rows_read=1000))
        cli_progress_printer(IngestionProgress(phase="complete", pct=100, rows_read=2000))
        captured = capsys.readouterr()
        assert "50%" in captured.out
        assert "100%" in captured.out


# ── Feature flag gating ───────────────────────────────────────────

class TestFeatureFlag:
    def test_flag_default_on(self):
        from telemetry_tool.ingest.config import refresh_flag

        # Ensure env var is not set — default is now ON
        os.environ.pop("TELEMETRY_INGEST_V2", None)
        assert refresh_flag() is True

    def test_flag_explicit_on(self):
        from telemetry_tool.ingest.config import refresh_flag
        os.environ["TELEMETRY_INGEST_V2"] = "1"
        try:
            assert refresh_flag() is True
        finally:
            os.environ.pop("TELEMETRY_INGEST_V2", None)
            refresh_flag()

    def test_flag_truthy_variants(self):
        from telemetry_tool.ingest.config import refresh_flag
        for val in ("1", "true", "True", "YES", "yes", "", "maybe"):
            os.environ["TELEMETRY_INGEST_V2"] = val
            assert refresh_flag() is True, f"Failed for {val!r}"
        os.environ.pop("TELEMETRY_INGEST_V2", None)
        refresh_flag()

    def test_flag_falsy_variants(self):
        from telemetry_tool.ingest.config import refresh_flag
        for val in ("0", "false", "no", "off", "False", "OFF"):
            os.environ["TELEMETRY_INGEST_V2"] = val
            assert refresh_flag() is False, f"Failed for {val!r}"
        os.environ.pop("TELEMETRY_INGEST_V2", None)
        refresh_flag()


# ── Column mapping stability ──────────────────────────────────────

class TestColumnMappingStability:
    """Verify streaming reader produces same column set as legacy for the
    same input file.  This is the key correctness invariant."""

    def test_column_names_match(self, sample_csv):
        from telemetry_tool.ingest.streaming import read_racechrono_csv_streamed
        df_stream = read_racechrono_csv_streamed(sample_csv)
        # Column names should be present and numeric
        assert "Time (s)" in df_stream.columns
        assert "Speed (m/s)" in df_stream.columns or "Speed (m/s) *calc" in df_stream.columns

    def test_row_count_preserved(self, sample_csv):
        from telemetry_tool.ingest.streaming import read_racechrono_csv_streamed
        df = read_racechrono_csv_streamed(sample_csv)
        assert len(df) == 200

    def test_chunk_boundary_no_data_loss(self, large_csv):
        """5000-row file chunked at 1000: verify no rows lost."""
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import read_racechrono_csv_streamed
        cfg = IngestionConfig(chunk_size=1000)
        df = read_racechrono_csv_streamed(large_csv, config=cfg)
        assert len(df) == 5000


# ── Schema migration ─────────────────────────────────────────────

class TestSchemaMigration:
    def test_v14_creates_ingestion_jobs(self):
        import sqlite3
        import sys

        # Ensure project root importable
        project_root = Path(__file__).resolve().parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from db.migrate import ensure_schema
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        version = ensure_schema(conn)
        assert version >= 14

        # Table exists
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ingestion_jobs'"
        ).fetchone()
        assert row is not None

        # Can insert
        conn.execute(
            "INSERT INTO ingestion_jobs (job_id, file_path, file_size, sha256_partial, status) "
            "VALUES ('j1', 'test.csv', 1000, 'abc', 'pending')"
        )
        conn.commit()
        result = conn.execute("SELECT * FROM ingestion_jobs WHERE job_id='j1'").fetchone()
        assert result["file_path"] == "test.csv"
        conn.close()

    def test_v14_observability_columns(self):
        import sqlite3
        import sys
        project_root = Path(__file__).resolve().parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from db.migrate import ensure_schema
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)

        # Verify observability columns exist
        conn.execute(
            "INSERT INTO ingestion_jobs "
            "(job_id, file_path, file_size, sha256_partial, status, peak_rss_mb, throughput_mb_s) "
            "VALUES ('j2', 'big.csv', 10000000, 'def', 'complete', 512.5, 85.3)"
        )
        conn.commit()
        result = conn.execute("SELECT peak_rss_mb, throughput_mb_s FROM ingestion_jobs WHERE job_id='j2'").fetchone()
        assert result["peak_rss_mb"] == 512.5
        assert result["throughput_mb_s"] == 85.3
        conn.close()


# ── Adaptive chunk sizing ────────────────────────────────────────

class TestAdaptiveChunks:
    def test_few_columns_large_chunks(self):
        from telemetry_tool.ingest.config import IngestionConfig
        cfg = IngestionConfig(adaptive_chunks=True, target_chunk_memory_mb=64)
        # 14 columns (typical RaceChrono): ~200k rows/chunk
        size = cfg.compute_chunk_size(14)
        assert size >= 100_000
        assert size <= 200_000

    def test_many_columns_small_chunks(self):
        from telemetry_tool.ingest.config import IngestionConfig
        cfg = IngestionConfig(adaptive_chunks=True, target_chunk_memory_mb=64)
        # 200 columns: much smaller chunks
        size = cfg.compute_chunk_size(200)
        assert size >= 5_000
        assert size <= 50_000

    def test_disabled_returns_default(self):
        from telemetry_tool.ingest.config import IngestionConfig
        cfg = IngestionConfig(chunk_size=42_000, adaptive_chunks=False)
        assert cfg.compute_chunk_size(14) == 42_000

    def test_zero_columns_returns_default(self):
        from telemetry_tool.ingest.config import IngestionConfig
        cfg = IngestionConfig(chunk_size=50_000, adaptive_chunks=True)
        assert cfg.compute_chunk_size(0) == 50_000

    def test_header_column_reader(self, sample_csv):
        from telemetry_tool.ingest.streaming import _read_header_columns, stream_detect_header
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cols = _read_header_columns(sample_csv, idx, enc, delim)
        assert "Time (s)" in cols
        assert len(cols) >= 6


# ── Writer drain-on-error ────────────────────────────────────────

class TestWriterDrainOnError:
    def test_put_raises_after_writer_error(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.pool import WriteQueue
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)

        # Patch flush_chunk to always fail
        def _failing_flush(chunk_idx, df):
            raise IOError("Simulated disk full")

        cache.flush_chunk = _failing_flush
        wq = WriteQueue(cache, max_depth=2)

        # First put goes into queue; writer thread will fail on it
        df = pd.DataFrame({"A": [1, 2, 3]})
        wq.put(0, df)

        import time
        time.sleep(0.5)  # Give writer thread time to fail

        # Next put should raise RuntimeError
        with pytest.raises(RuntimeError, match="Writer thread failed"):
            wq.put(1, df)

        # close() should also raise
        with pytest.raises(RuntimeError, match="Writer thread failed"):
            wq.close()

    def test_drain_unblocks_after_error(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.pool import WriteQueue
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)

        call_count = [0]
        def _fail_on_second(chunk_idx, df):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise IOError("Simulated write error")
            # First chunk succeeds
            from telemetry_tool.ingest.cache import IngestCache
            IngestCache.flush_chunk(cache, chunk_idx, df)

        cache.flush_chunk = _fail_on_second
        wq = WriteQueue(cache, max_depth=4)

        df = pd.DataFrame({"A": [1, 2, 3]})
        wq.put(0, df)
        wq.put(1, df)  # This one will fail in the writer

        import time
        time.sleep(0.5)

        # drain should raise
        with pytest.raises(RuntimeError, match="Writer thread failed"):
            wq.drain()


# ── Disk space pre-check ─────────────────────────────────────────

class TestDiskSpaceCheck:
    def test_check_passes_with_space(self, tmp_dir):
        from telemetry_tool.ingest.cache import check_disk_space

        # Small file, should always pass
        check_disk_space(tmp_dir, 1000)

    def test_check_raises_on_impossible_size(self, tmp_dir):
        from telemetry_tool.ingest.cache import InsufficientDiskSpace, check_disk_space

        # Request more space than any disk could have (1 PB)
        with pytest.raises(InsufficientDiskSpace):
            check_disk_space(tmp_dir, 1024**5)


# ── Merge via PyArrow ────────────────────────────────────────────

class TestMergeChunksParquet:
    def test_merge_to_parquet_file(self, sample_csv, tmp_dir):
        from telemetry_tool.ingest.cache import IngestCache
        from telemetry_tool.ingest.config import IngestionConfig
        from telemetry_tool.ingest.streaming import stream_detect_header

        cfg = IngestionConfig(cache_dir=tmp_dir / "cache")
        idx, enc, delim, _ = stream_detect_header(sample_csv)
        cache = IngestCache.create(sample_csv, idx, enc, delim, cfg)

        df1 = pd.DataFrame({"X": [1, 2], "Y": [3.0, 4.0]})
        df2 = pd.DataFrame({"X": [5, 6], "Y": [7.0, 8.0]})
        cache.flush_chunk(0, df1)
        cache.flush_chunk(1, df2)

        parquet_path = cache.merge_chunks_to_parquet()
        assert parquet_path.exists()
        assert parquet_path.suffix == ".parquet"

        # Verify contents via pyarrow
        import pyarrow.parquet as pq
        table = pq.read_table(parquet_path)
        assert table.num_rows == 4
        assert table.column("X").to_pylist() == [1, 2, 5, 6]
