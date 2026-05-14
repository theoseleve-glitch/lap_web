"""Day-10 RC7 — streaming-ingest schema reconciliation across chunks.

OK_R2.csv reproduced this error from the V2 mesh pipeline:

    pyarrow.lib.ArrowNotImplementedError: Unsupported cast from string to null
    using function cast_null

Root cause: ``IngestCache.merge_chunks_to_parquet`` built the unified Parquet
schema from chunk 0 only, then cast every subsequent chunk to that schema.
When chunk 0 had a sparse column whose values were all empty/NaN, pyarrow
inferred that column as type ``null``. A later chunk with actual string
values in the same column could not be cast back down to ``null``, so the
merge raised.

The fix scans every chunk's schema at merge time and reconciles types
column-by-column (int → float64 to absorb pandas' NaN-upcast; null →
first non-null type seen across chunks; mixed → string as a defensive
fallback). All chunks then cast cleanly into the unified schema.

These regression tests exercise the cache layer directly so they don't
depend on a multi-megabyte CSV fixture.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from telemetry_tool.ingest.cache import IngestCache, IngestionManifest  # noqa: E402


def _bare_cache(tmp_path: Path) -> IngestCache:
    """Construct an IngestCache without going through ``create`` (which
    requires a real source file). The manifest is a stub good enough for
    the merge codepath."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    manifest = IngestionManifest(
        cache_id="test",
        file_path="(test)",
        file_size=0,
        sha256_partial="0" * 64,
        n_chunks_expected=2,
        status="reading",
    )
    manifest.save(cache_dir / "manifest.json")
    return IngestCache(cache_dir, manifest)


def test_merge_null_chunk0_string_chunk1_does_not_raise():
    """Chunk 0 all-null + chunk 1 has strings → merge must succeed.

    This is the OK_R2.csv failure mode. Pre-fix, this raises
    ArrowNotImplementedError at ``table.cast(unified_schema)``.
    """
    with tempfile.TemporaryDirectory() as td:
        cache = _bare_cache(Path(td))
        chunk0 = pd.DataFrame({
            "Time (s)": np.linspace(0.0, 10.0, 100),
            "Lap Comment": [None] * 100,
        })
        chunk1 = pd.DataFrame({
            "Time (s)": np.linspace(10.0, 20.0, 100),
            "Lap Comment": ["fast lap"] * 50 + ["slow lap"] * 50,
        })
        cache.flush_chunk(0, chunk0)
        cache.flush_chunk(1, chunk1)
        out_path = cache.merge_chunks_to_parquet()
        merged = pq.read_table(out_path).to_pandas()
        assert len(merged) == 200
        # String values from chunk 1 are preserved
        assert merged["Lap Comment"].iloc[150] == "slow lap"
        assert merged["Lap Comment"].iloc[100] == "fast lap"
        # Chunk 0's nulls round-trip as missing values
        assert pd.isna(merged["Lap Comment"].iloc[50])


def test_merge_int_chunk0_float_with_nan_chunk1_promotes_to_float():
    """Existing behavior preserved: int column + later NaN → float64.

    Pandas upcasts int → float when NaN appears. The cache's schema
    reconciliation must handle this without regression after the
    null-promotion fix lands.
    """
    with tempfile.TemporaryDirectory() as td:
        cache = _bare_cache(Path(td))
        chunk0 = pd.DataFrame({
            "Lap": [1, 2, 3],
            "Time (s)": [0.1, 0.2, 0.3],
        })
        chunk1 = pd.DataFrame({
            "Lap": [4.0, np.nan, 5.0],
            "Time (s)": [0.4, 0.5, 0.6],
        })
        cache.flush_chunk(0, chunk0)
        cache.flush_chunk(1, chunk1)
        out_path = cache.merge_chunks_to_parquet()
        merged = pq.read_table(out_path).to_pandas()
        assert len(merged) == 6
        assert merged["Lap"].dtype.kind == "f"
        assert merged["Lap"].iloc[3] == 4.0
        assert pd.isna(merged["Lap"].iloc[4])


def test_merge_all_null_column_across_all_chunks():
    """If a column is null in every chunk, merge still completes — the
    unified schema keeps the column as null (it carries no data anyway)."""
    with tempfile.TemporaryDirectory() as td:
        cache = _bare_cache(Path(td))
        chunk0 = pd.DataFrame({
            "Time (s)": [0.0, 1.0],
            "Always Empty": [None, None],
        })
        chunk1 = pd.DataFrame({
            "Time (s)": [2.0, 3.0],
            "Always Empty": [None, None],
        })
        cache.flush_chunk(0, chunk0)
        cache.flush_chunk(1, chunk1)
        out_path = cache.merge_chunks_to_parquet()
        merged = pq.read_table(out_path).to_pandas()
        assert len(merged) == 4
        # Column survives, all NaN
        assert merged["Always Empty"].isna().all()
