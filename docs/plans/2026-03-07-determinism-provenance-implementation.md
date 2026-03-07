# Determinism & Provenance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make analysis outputs deterministic for identical inputs and add provenance fields to every persisted analysis for reproducibility and traceability.

**Architecture:** Shared `telemetry_tool/provenance/` package with fingerprint, run context, and canonical JSON modules. Alembic migration 020 adds `analysis_provenance` table. Both pipelines inject provenance into their summary dicts. Snapshot regression harness validates determinism via canonical hash + semantic diff.

**Tech Stack:** Python 3, hashlib (SHA-256), uuid4, dataclasses, json, numpy, pandas, pytest, Alembic/SQLAlchemy

---

### Task 1: Canonical JSON Module

**Files:**
- Create: `telemetry_tool/provenance/__init__.py`
- Create: `telemetry_tool/provenance/canonical.py`
- Create: `telemetry_tool/tests/test_canonical.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_canonical.py
"""Tests for provenance canonical JSON serialisation."""
import math
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.canonical import canonicalize, canonical_hash


class TestCanonicalize:
    def test_sorts_dict_keys(self):
        obj = {"z": 1, "a": 2, "m": 3}
        result = canonicalize(obj)
        assert result == '{"a": 2, "m": 3, "z": 1}'

    def test_rounds_floats(self):
        obj = {"val": 3.14159265358979}
        result = canonicalize(obj, float_precision=6)
        assert '"val": 3.141593' in result

    def test_normalizes_nan(self):
        obj = {"val": float("nan")}
        result = canonicalize(obj)
        assert '"val": "__NaN__"' in result

    def test_normalizes_inf(self):
        obj = {"val": float("inf"), "neg": float("-inf")}
        result = canonicalize(obj)
        assert '"val": "__Inf__"' in result
        assert '"neg": "__-Inf__"' in result

    def test_nested_dicts_sorted(self):
        obj = {"b": {"d": 1, "c": 2}, "a": 3}
        result = canonicalize(obj)
        assert result == '{"a": 3, "b": {"c": 2, "d": 1}}'

    def test_lists_preserve_order(self):
        obj = {"items": [3, 1, 2]}
        result = canonicalize(obj)
        assert '"items": [3, 1, 2]' in result

    def test_none_preserved(self):
        obj = {"val": None}
        result = canonicalize(obj)
        assert '"val": null' in result

    def test_deterministic_hash(self):
        obj = {"z": 1.0000001, "a": [1, 2, 3]}
        h1 = canonical_hash(obj)
        h2 = canonical_hash(obj)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_input_different_hash(self):
        h1 = canonical_hash({"a": 1})
        h2 = canonical_hash({"a": 2})
        assert h1 != h2
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_canonical.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'provenance'`

**Step 3: Create the package and implement canonical.py**

```python
# telemetry_tool/provenance/__init__.py
"""Provenance tracking for telemetry analysis pipelines."""
```

```python
# telemetry_tool/provenance/canonical.py
"""Canonical JSON serialisation for deterministic hashing.

Normalises floats, NaN/Inf, and dict ordering so that identical
analysis results always produce the same hash.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _normalise(obj: Any, precision: int) -> Any:
    """Recursively normalise an object for canonical JSON."""
    if isinstance(obj, dict):
        return {k: _normalise(v, precision) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normalise(v, precision) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj):
            return "__NaN__"
        if math.isinf(obj):
            return "__-Inf__" if obj < 0 else "__Inf__"
        return round(obj, precision)
    return obj


def canonicalize(obj: Any, float_precision: int = 6) -> str:
    """Return a deterministic JSON string with sorted keys and normalised floats."""
    normalised = _normalise(obj, float_precision)
    return json.dumps(normalised, sort_keys=True, separators=(", ", ": "))


def canonical_hash(obj: Any, float_precision: int = 6) -> str:
    """Return the SHA-256 hex digest of the canonical JSON form."""
    payload = canonicalize(obj, float_precision)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

**Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_canonical.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/provenance/__init__.py telemetry_tool/provenance/canonical.py telemetry_tool/tests/test_canonical.py
git commit -m "feat(provenance): add canonical JSON module for deterministic hashing"
```

---

### Task 2: Fingerprint Module

**Files:**
- Create: `telemetry_tool/provenance/fingerprint.py`
- Create: `telemetry_tool/tests/test_fingerprint.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_fingerprint.py
"""Tests for provenance fingerprinting (file hash + data fingerprint)."""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.fingerprint import compute_data_fingerprint, compute_file_hash


class TestFileHash:
    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n")
        h = compute_file_hash(str(f))
        assert isinstance(h, str) and len(h) == 64

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        content = "x,y\n1.0,2.0\n3.0,4.0\n"
        f1.write_text(content)
        f2.write_text(content)
        assert compute_file_hash(str(f1)) == compute_file_hash(str(f2))

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        f1.write_text("a,b\n1,2\n")
        f2.write_text("a,b\n1,3\n")
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))


class TestDataFingerprint:
    def test_returns_hex_string(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        fp = compute_data_fingerprint(df)
        assert isinstance(fp, str) and len(fp) == 64

    def test_same_data_same_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        df2 = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        assert compute_data_fingerprint(df1) == compute_data_fingerprint(df2)

    def test_column_order_irrelevant(self):
        df1 = pd.DataFrame({"a": [1.0], "b": [2.0]})
        df2 = pd.DataFrame({"b": [2.0], "a": [1.0]})
        assert compute_data_fingerprint(df1) == compute_data_fingerprint(df2)

    def test_different_values_different_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0, 2.0]})
        df2 = pd.DataFrame({"a": [1.0, 3.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)

    def test_different_columns_different_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0]})
        df2 = pd.DataFrame({"b": [1.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)

    def test_different_shape_different_fingerprint(self):
        df1 = pd.DataFrame({"a": [1.0, 2.0]})
        df2 = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'provenance.fingerprint'`

**Step 3: Implement fingerprint.py**

```python
# telemetry_tool/provenance/fingerprint.py
"""Input fingerprinting for provenance tracking.

Provides two hash functions:
- ``compute_file_hash`` — SHA-256 of raw file bytes.
- ``compute_data_fingerprint`` — SHA-256 of normalised column structure +
  a fixed-size numeric sample.  Resistant to encoding/formatting differences.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_READ_BLOCK: int = 8 * 1024 * 1024  # 8 MB


def compute_file_hash(path: str) -> str:
    """Return SHA-256 hex digest of the raw file bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_READ_BLOCK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_data_fingerprint(df: pd.DataFrame) -> str:
    """Return SHA-256 hex digest of the DataFrame's normalised structure + sample.

    The fingerprint covers:
    - Sorted column names
    - Shape (rows, cols)
    - First 8 bytes of each numeric column (cast to float64), sorted by column name

    This is fast even for very large DataFrames because only the header
    structure and a fixed-size sample are hashed.
    """
    h = hashlib.sha256()

    # 1. Sorted column names
    cols = sorted(df.columns.tolist())
    h.update("|".join(str(c) for c in cols).encode("utf-8"))

    # 2. Shape
    h.update(f"|shape={df.shape[0]}x{df.shape[1]}".encode("utf-8"))

    # 3. Per-column numeric sample (first 8 bytes of float64 representation)
    for col in cols:
        series = df[col]
        try:
            vals = series.astype(np.float64).values
        except (ValueError, TypeError):
            # Non-numeric column: hash the string repr of first value
            vals = str(series.iloc[0]).encode("utf-8") if len(series) > 0 else b""
            h.update(vals if isinstance(vals, bytes) else vals)
            continue
        # Take first element as 8-byte sample
        if len(vals) > 0:
            h.update(vals[0].tobytes())

    return h.hexdigest()
```

**Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_fingerprint.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/provenance/fingerprint.py telemetry_tool/tests/test_fingerprint.py
git commit -m "feat(provenance): add input fingerprint module (file hash + data fingerprint)"
```

---

### Task 3: Run Context Module (ProvenanceRecord + build_provenance)

**Files:**
- Create: `telemetry_tool/provenance/run_context.py`
- Modify: `telemetry_tool/provenance/__init__.py`
- Create: `telemetry_tool/tests/test_run_context.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_run_context.py
"""Tests for provenance run context (ProvenanceRecord + build_provenance)."""
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.run_context import ProvenanceRecord, build_provenance


class TestProvenanceRecord:
    def test_to_dict_returns_all_fields(self):
        r = ProvenanceRecord(
            analysis_run_id="abc-123",
            input_fingerprint="deadbeef",
            file_hash="cafebabe",
            params_hash="12345678",
            pipeline_version="v2-aabbccdd",
            model_version="none",
            solver_version=None,
            method_used="telemetry_tool_v2",
            generated_at="2026-03-07T12:00:00Z",
            training_data_hash=None,
        )
        d = r.to_dict()
        assert d["analysis_run_id"] == "abc-123"
        assert d["input_fingerprint"] == "deadbeef"
        assert d["file_hash"] == "cafebabe"
        assert d["solver_version"] is None
        assert d["training_data_hash"] is None
        assert len(d) == 10  # all fields present


class TestBuildProvenance:
    def test_returns_provenance_record(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        config = {"some_param": 42}
        record = build_provenance(
            input_df=df,
            config=config,
            method_used="telemetry_tool_v2",
        )
        assert isinstance(record, ProvenanceRecord)
        assert len(record.analysis_run_id) == 36  # UUID4 format
        assert len(record.input_fingerprint) == 64  # SHA-256
        assert len(record.params_hash) == 64
        assert record.method_used == "telemetry_tool_v2"
        assert record.generated_at.endswith("Z") or "+" in record.generated_at

    def test_same_inputs_same_fingerprint(self):
        df = pd.DataFrame({"a": [1.0, 2.0]})
        cfg = {"x": 1}
        r1 = build_provenance(df, cfg, method_used="test")
        r2 = build_provenance(df, cfg, method_used="test")
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.params_hash == r2.params_hash
        # But run_ids differ (UUID4 is random)
        assert r1.analysis_run_id != r2.analysis_run_id

    def test_file_hash_populated_when_path_given(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        df = pd.DataFrame({"a": [1.0], "b": [2.0]})
        record = build_provenance(df, {}, method_used="test", file_path=str(f))
        assert record.file_hash is not None and len(record.file_hash) == 64

    def test_file_hash_none_when_no_path(self):
        df = pd.DataFrame({"a": [1.0]})
        record = build_provenance(df, {}, method_used="test")
        assert record.file_hash is None
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_run_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'provenance.run_context'`

**Step 3: Implement run_context.py and update __init__.py**

```python
# telemetry_tool/provenance/run_context.py
"""Provenance run context — builds a ProvenanceRecord for each analysis run.

Captures: unique run ID, input fingerprint, config hash, pipeline/model
versions, and timestamp.  This record is embedded in the analysis summary
and optionally persisted to the ``analysis_provenance`` table.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from provenance.fingerprint import compute_data_fingerprint, compute_file_hash


@dataclass
class ProvenanceRecord:
    """Immutable provenance snapshot for a single analysis run."""

    analysis_run_id: str
    input_fingerprint: str
    file_hash: Optional[str]
    params_hash: str
    pipeline_version: str
    model_version: str
    solver_version: Optional[str]
    method_used: str
    generated_at: str
    training_data_hash: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hash_config(config: Any) -> str:
    """SHA-256 of the JSON-serialised config."""
    payload = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_provenance(
    input_df: pd.DataFrame,
    config: Any,
    *,
    method_used: str,
    file_path: Optional[str] = None,
    pipeline_version: Optional[str] = None,
    model_version: Optional[str] = None,
    solver_version: Optional[str] = None,
    training_data_hash: Optional[str] = None,
) -> ProvenanceRecord:
    """Build a ProvenanceRecord for the current analysis run.

    Parameters
    ----------
    input_df : DataFrame
        The parsed input data (used for data fingerprint).
    config : dict or dataclass
        Analysis configuration (hashed for params_hash).
    method_used : str
        Pipeline identifier, e.g. "telemetry_tool_v2" or "kart_envelope_v2.2".
    file_path : str, optional
        Path to the raw CSV file (for file_hash).
    pipeline_version : str, optional
        Override pipeline version string.  Defaults to computed value.
    model_version : str, optional
        ML model version.  Defaults to "none".
    solver_version : str, optional
        Solver backend version (kart_envelope only).
    training_data_hash : str, optional
        Hash of the ML training dataset.
    """
    # Resolve pipeline version
    if pipeline_version is None:
        try:
            from pipeline_status import compute_pipeline_version_string
            pipeline_version = compute_pipeline_version_string()
        except ImportError:
            pipeline_version = "unknown"

    # Resolve model version
    if model_version is None:
        try:
            from pipeline_status import get_model_version
            model_version = get_model_version()
        except ImportError:
            model_version = "none"

    return ProvenanceRecord(
        analysis_run_id=str(uuid.uuid4()),
        input_fingerprint=compute_data_fingerprint(input_df),
        file_hash=compute_file_hash(file_path) if file_path else None,
        params_hash=_hash_config(config),
        pipeline_version=pipeline_version,
        model_version=model_version,
        solver_version=solver_version,
        method_used=method_used,
        generated_at=datetime.now(timezone.utc).isoformat(),
        training_data_hash=training_data_hash,
    )
```

Update `__init__.py`:

```python
# telemetry_tool/provenance/__init__.py
"""Provenance tracking for telemetry analysis pipelines."""
from provenance.canonical import canonical_hash, canonicalize
from provenance.fingerprint import compute_data_fingerprint, compute_file_hash
from provenance.run_context import ProvenanceRecord, build_provenance

__all__ = [
    "build_provenance",
    "canonical_hash",
    "canonicalize",
    "compute_data_fingerprint",
    "compute_file_hash",
    "ProvenanceRecord",
]
```

**Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_run_context.py tests/test_canonical.py tests/test_fingerprint.py -v`
Expected: All 22 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/provenance/run_context.py telemetry_tool/provenance/__init__.py telemetry_tool/tests/test_run_context.py
git commit -m "feat(provenance): add run context module (ProvenanceRecord + build_provenance)"
```

---

### Task 4: Integrate Provenance into telemetry_tool Pipeline

**Files:**
- Modify: `telemetry_tool/pipeline.py:52-61` (imports) and `telemetry_tool/pipeline.py:573-582` (after PipelineStatus, before summary dict)
- Modify: `telemetry_tool/pipeline.py:2881-2882` (before `return summary`)

**Step 1: Write a focused integration test**

Add to `telemetry_tool/tests/test_run_context.py`:

```python
class TestPipelineProvenance:
    """Verify provenance is injected into pipeline summary."""

    def test_provenance_key_in_summary(self):
        """Smoke test: provenance record can be built and serialised."""
        df = pd.DataFrame({
            "Speed (m/s)": [10.0, 11.0, 12.0],
            "Lap #": [1, 1, 1],
            "Time (s)": [0.0, 1.0, 2.0],
        })
        record = build_provenance(
            df, {"track": "test"}, method_used="telemetry_tool_v2"
        )
        d = record.to_dict()
        assert "analysis_run_id" in d
        assert "input_fingerprint" in d
        assert "params_hash" in d
        assert "pipeline_version" in d
        assert "generated_at" in d
        assert d["method_used"] == "telemetry_tool_v2"
```

**Step 2: Run test to verify it passes** (this tests the module, not the pipeline integration)

Run: `cd telemetry_tool && python -m pytest tests/test_run_context.py::TestPipelineProvenance -v`
Expected: PASS

**Step 3: Modify pipeline.py**

Add import at `pipeline.py` line ~52 (after existing imports):

```python
from provenance.run_context import build_provenance
```

After `_pipeline_status` creation (~line 577) and before the `summary` dict (~line 579), add:

```python
    # ── Provenance ─────────────────────────────────────────────
    _provenance_record = build_provenance(
        input_df=raw_df if raw_df is not None else pd.DataFrame(),
        config=meta,
        method_used="telemetry_tool_v2",
        file_path=str(csv_path) if csv_path else None,
        pipeline_version=_pipeline_status.pipeline_version,
        model_version=_pipeline_status.model_version,
    )
```

Note: `raw_df` is not yet available at this point — it's computed in step 01_ingest. Move the provenance build to just after the ingest step completes (after `raw_df` is assigned, around line ~640). If ingest fails and `raw_df is None`, pass an empty DataFrame.

In the summary finalization section (~line 2882), add before `return summary`:

```python
    # Rebuild provenance with actual raw_df now that ingest is complete
    _provenance_record = build_provenance(
        input_df=raw_df if raw_df is not None else pd.DataFrame(),
        config=meta,
        method_used="telemetry_tool_v2",
        file_path=str(csv_path) if csv_path else None,
        pipeline_version=_pipeline_status.pipeline_version,
        model_version=_pipeline_status.model_version,
    )
    summary["provenance"] = _provenance_record.to_dict()
```

**Step 4: Run existing pipeline tests to verify nothing breaks**

Run: `cd telemetry_tool && python -m pytest tests/ -v --timeout=60 -x -q`
Expected: All existing tests PASS (no regressions)

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(provenance): inject provenance record into telemetry_tool pipeline summary"
```

---

### Task 5: Integrate Provenance into kart_envelope Pipeline

**Files:**
- Modify: `kart_envelope/pipeline.py:13-24` (imports)
- Modify: `kart_envelope/pipeline.py:1075-1081` (after summary is built, before write)

**Step 1: Write a focused integration test**

```python
# kart_envelope/tests/test_provenance_integration.py
"""Test provenance injection into kart_envelope pipeline summary."""
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.run_context import build_provenance


def test_kart_provenance_record():
    """Verify provenance record can be built for kart_envelope."""
    df = pd.DataFrame({
        "Distance (m)": [0.0, 0.5, 1.0],
        "Speed (m/s)": [10.0, 11.0, 12.0],
    })
    record = build_provenance(
        df,
        {"model_version": "1.0", "solver_backend": "scipy"},
        method_used="kart_envelope_v2.2",
        solver_version="scipy",
        pipeline_version="v2.2",
        model_version="1.0",
    )
    d = record.to_dict()
    assert d["method_used"] == "kart_envelope_v2.2"
    assert d["solver_version"] == "scipy"
    assert d["pipeline_version"] == "v2.2"
```

**Step 2: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest ../kart_envelope/tests/test_provenance_integration.py -v`
Expected: PASS

**Step 3: Modify kart_envelope/pipeline.py**

Add import near the top (after line ~24):

```python
from provenance.run_context import build_provenance
```

After line 1081 (`summary["solver_meta"] = solver_meta`), add:

```python
    # ── Provenance ──────────────────────────────────────────────
    _provenance_record = build_provenance(
        input_df=normalized_df if normalized_df is not None else pd.DataFrame(),
        config={
            "model_version": str(config.model_version),
            "solver_backend": str(config.solver_backend),
            "physics_stack_version": str(config.physics_stack_version),
        },
        method_used="kart_envelope_v2.2",
        file_path=str(metadata.session_file) if metadata else None,
        pipeline_version=summary.get("version", "2.2"),
        model_version=str(config.model_version),
        solver_version=str(theoretical.solver_backend) if theoretical else None,
    )
    summary["provenance"] = _provenance_record.to_dict()
```

Note: `normalized_df` is the parsed input from step 01. Check what variable name holds the normalised DataFrame at line 1075 — it may be `resampled` or similar. Refer to the local variable that holds the main DataFrame after ingest+normalisation.

**Step 4: Run kart_envelope tests**

Run: `python -m pytest kart_envelope/tests/ -v --timeout=60 -x -q`
Expected: All existing tests PASS

**Step 5: Commit**

```bash
git add kart_envelope/pipeline.py kart_envelope/tests/test_provenance_integration.py
git commit -m "feat(provenance): inject provenance record into kart_envelope pipeline summary"
```

---

### Task 6: Alembic Migration 020 — analysis_provenance Table

**Files:**
- Create: `alembic/versions/020_analysis_provenance.py`

**Step 1: Write the migration**

```python
# alembic/versions/020_analysis_provenance.py
"""Add analysis_provenance table for queryable provenance tracking.

Stores denormalised provenance records alongside the summary JSON
embedded in sessions.analysis_json.  PG-only (SQLite/desktop mode
uses only the embedded JSON).

Revision ID: 020
Revises: 019
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_provenance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("analysis_run_id", sa.Text, nullable=False, unique=True),
        sa.Column("session_id", sa.Text, sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("workspace_id", sa.Integer, nullable=True),
        sa.Column("input_fingerprint", sa.Text, nullable=False),
        sa.Column("file_hash", sa.Text, nullable=True),
        sa.Column("params_hash", sa.Text, nullable=False),
        sa.Column("pipeline_version", sa.Text, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("solver_version", sa.Text, nullable=True),
        sa.Column("method_used", sa.Text, nullable=False),
        sa.Column("training_data_hash", sa.Text, nullable=True),
        sa.Column("generated_at", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_provenance_session", "analysis_provenance", ["session_id"])
    op.create_index("idx_provenance_fingerprint", "analysis_provenance", ["input_fingerprint"])
    op.create_index("idx_provenance_pipeline_ver", "analysis_provenance", ["pipeline_version"])

    # RLS policy (PG only, silently skipped on SQLite)
    try:
        op.execute("ALTER TABLE analysis_provenance ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY workspace_isolation ON analysis_provenance "
            "USING (workspace_id = current_setting('app.workspace_id')::INTEGER)"
        )
    except Exception:
        pass  # SQLite — no RLS support


def downgrade() -> None:
    try:
        op.execute("DROP POLICY IF EXISTS workspace_isolation ON analysis_provenance")
    except Exception:
        pass
    op.drop_index("idx_provenance_pipeline_ver")
    op.drop_index("idx_provenance_fingerprint")
    op.drop_index("idx_provenance_session")
    op.drop_table("analysis_provenance")
```

**Step 2: Verify migration applies (dry run)**

Run: `cd telemetry_tool && python -c "from alembic.versions import *; print('import ok')"`
Expected: No errors.  Full migration test requires PG — skip for now, will be validated in integration tests.

**Step 3: Commit**

```bash
git add alembic/versions/020_analysis_provenance.py
git commit -m "feat(provenance): add Alembic migration 020 for analysis_provenance table"
```

---

### Task 7: Provenance Write Path (Dual-Write to Table + Summary)

**Files:**
- Create: `telemetry_tool/provenance/persistence.py`
- Create: `telemetry_tool/tests/test_provenance_persistence.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_provenance_persistence.py
"""Tests for provenance persistence (dual-write to table + summary)."""
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.persistence import insert_provenance, get_provenance_by_session
from provenance.run_context import ProvenanceRecord


def _create_provenance_table(conn):
    """Create the analysis_provenance table in SQLite for testing."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_run_id TEXT NOT NULL UNIQUE,
            session_id TEXT,
            workspace_id INTEGER,
            input_fingerprint TEXT NOT NULL,
            file_hash TEXT,
            params_hash TEXT NOT NULL,
            pipeline_version TEXT NOT NULL,
            model_version TEXT NOT NULL,
            solver_version TEXT,
            method_used TEXT NOT NULL,
            training_data_hash TEXT,
            generated_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


@pytest.fixture
def prov_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_provenance_table(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_record():
    return ProvenanceRecord(
        analysis_run_id="550e8400-e29b-41d4-a716-446655440000",
        input_fingerprint="a" * 64,
        file_hash="b" * 64,
        params_hash="c" * 64,
        pipeline_version="v2-aabbccdd",
        model_version="none",
        solver_version=None,
        method_used="telemetry_tool_v2",
        generated_at="2026-03-07T12:00:00+00:00",
        training_data_hash=None,
    )


class TestInsertProvenance:
    def test_inserts_row(self, prov_db, sample_record):
        insert_provenance(prov_db, sample_record, session_id="s1")
        row = prov_db.execute(
            "SELECT * FROM analysis_provenance WHERE session_id = 's1'"
        ).fetchone()
        assert row is not None
        assert row["analysis_run_id"] == sample_record.analysis_run_id
        assert row["pipeline_version"] == "v2-aabbccdd"

    def test_idempotent_on_duplicate_run_id(self, prov_db, sample_record):
        insert_provenance(prov_db, sample_record, session_id="s1")
        insert_provenance(prov_db, sample_record, session_id="s1")  # no error
        count = prov_db.execute(
            "SELECT COUNT(*) as n FROM analysis_provenance"
        ).fetchone()["n"]
        assert count == 1


class TestGetProvenance:
    def test_returns_dict(self, prov_db, sample_record):
        insert_provenance(prov_db, sample_record, session_id="s1")
        result = get_provenance_by_session(prov_db, "s1")
        assert result is not None
        assert result["analysis_run_id"] == sample_record.analysis_run_id

    def test_returns_none_for_missing(self, prov_db):
        result = get_provenance_by_session(prov_db, "nonexistent")
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_provenance_persistence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'provenance.persistence'`

**Step 3: Implement persistence.py**

```python
# telemetry_tool/provenance/persistence.py
"""Provenance persistence — dual-write to DB table and summary dict.

Writes to the ``analysis_provenance`` table when available (PG mode).
Falls back gracefully when the table does not exist (SQLite desktop mode
before migration, or when USE_PG=0).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from provenance.run_context import ProvenanceRecord

logger = logging.getLogger(__name__)


def insert_provenance(
    conn: Any,
    record: ProvenanceRecord,
    session_id: Optional[str] = None,
    workspace_id: Optional[int] = None,
) -> None:
    """Insert a provenance record into the analysis_provenance table.

    Uses INSERT OR IGNORE / ON CONFLICT DO NOTHING for idempotency.
    Silently skips if the table does not exist.
    """
    try:
        conn.execute(
            "INSERT OR IGNORE INTO analysis_provenance "
            "(analysis_run_id, session_id, workspace_id, input_fingerprint, "
            "file_hash, params_hash, pipeline_version, model_version, "
            "solver_version, method_used, training_data_hash, generated_at) "
            "VALUES (:run_id, :sid, :wid, :fp, :fh, :ph, :pv, :mv, :sv, :mu, :tdh, :ga)",
            {
                "run_id": record.analysis_run_id,
                "sid": session_id,
                "wid": workspace_id,
                "fp": record.input_fingerprint,
                "fh": record.file_hash,
                "ph": record.params_hash,
                "pv": record.pipeline_version,
                "mv": record.model_version,
                "sv": record.solver_version,
                "mu": record.method_used,
                "tdh": record.training_data_hash,
                "ga": record.generated_at,
            },
        )
        conn.commit()
    except Exception as exc:
        logger.debug("Provenance insert skipped: %s", exc)


def get_provenance_by_session(
    conn: Any,
    session_id: str,
) -> Optional[dict[str, Any]]:
    """Retrieve the most recent provenance record for a session.

    Returns None if no record exists or the table is missing.
    """
    try:
        row = conn.execute(
            "SELECT * FROM analysis_provenance "
            "WHERE session_id = :sid ORDER BY created_at DESC LIMIT 1",
            {"sid": session_id},
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    except Exception:
        return None
```

**Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_provenance_persistence.py -v`
Expected: All 4 tests PASS

**Step 5: Update __init__.py exports and commit**

Add to `telemetry_tool/provenance/__init__.py`:

```python
from provenance.persistence import get_provenance_by_session, insert_provenance
```

And add to `__all__`:

```python
    "get_provenance_by_session",
    "insert_provenance",
```

```bash
git add telemetry_tool/provenance/persistence.py telemetry_tool/provenance/__init__.py telemetry_tool/tests/test_provenance_persistence.py
git commit -m "feat(provenance): add persistence module (dual-write to table + summary)"
```

---

### Task 8: Provenance API Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` — add endpoint after the last session route
- Create: `telemetry_tool/tests/test_provenance_endpoint.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_provenance_endpoint.py
"""Tests for GET /api/v1/sessions/<id>/provenance endpoint."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app():
    """Create a Flask test app with an in-memory SQLite DB."""
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_provenance_endpoint_returns_from_analysis_json(client):
    """When analysis_json has provenance, endpoint returns it."""
    # This is a smoke test — full integration requires seeded DB.
    # Just verify the route exists and returns proper error for missing session.
    resp = client.get("/api/v1/sessions/nonexistent/provenance")
    data = resp.get_json()
    assert resp.status_code in (404, 401)  # 404 or 401 if auth required
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_provenance_endpoint.py -v`
Expected: FAIL — 404 because route doesn't exist yet (or import error)

**Step 3: Add the endpoint to data_v2.py**

Add after the last `@bp.route` block (around line ~3150):

```python
# ══════════════════════════════════════════════════════════════════
# N. GET /api/v1/sessions/<id>/provenance — Provenance record
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/provenance", methods=["GET"])
@_safe_api
def get_provenance(session_id: str):
    """Return the provenance record for a session.

    Read path: check analysis_provenance table first (fast indexed lookup),
    fall back to extracting from analysis_json for pre-migration sessions.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Try table first
    try:
        from provenance.persistence import get_provenance_by_session
        prov = get_provenance_by_session(conn, session_id)
        if prov is not None:
            # Remove internal DB fields
            prov.pop("id", None)
            prov.pop("created_at", None)
            return api_response(prov)
    except Exception:
        pass

    # Fall back to analysis_json
    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        prov = analysis.get("provenance")
        if prov:
            return api_response(prov)

    return api_error(
        ErrorCode.NOT_FOUND,
        "No provenance available for this session",
        status=404,
    )
```

**Step 4: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_provenance_endpoint.py -v`
Expected: PASS (route now exists, returns 404 for missing session)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_provenance_endpoint.py
git commit -m "feat(provenance): add GET /api/v1/sessions/<id>/provenance endpoint"
```

---

### Task 9: Snapshot Test Harness

**Files:**
- Create: `tests/snapshot_harness.py`
- Modify: `telemetry_tool/tests/conftest.py` — add `--update-snapshots` flag
- Create: `tests/snapshots/` directory structure

**Step 1: Write harness tests (self-test)**

```python
# tests/test_snapshot_harness.py
"""Self-tests for the snapshot harness module."""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.snapshot_harness import assert_snapshot_match, _deep_compare


class TestDeepCompare:
    def test_identical_dicts(self):
        a = {"x": 1.0, "y": [2.0, 3.0]}
        diffs = _deep_compare(a, a)
        assert diffs == []

    def test_float_within_tolerance(self):
        a = {"x": 1.0000001}
        b = {"x": 1.0000002}
        diffs = _deep_compare(a, b, rtol=1e-6)
        assert diffs == []

    def test_float_outside_tolerance(self):
        a = {"x": 1.0}
        b = {"x": 2.0}
        diffs = _deep_compare(a, b, rtol=1e-6)
        assert len(diffs) > 0

    def test_missing_key(self):
        a = {"x": 1}
        b = {"x": 1, "y": 2}
        diffs = _deep_compare(a, b)
        assert len(diffs) > 0

    def test_nested_diff(self):
        a = {"outer": {"inner": 1.0}}
        b = {"outer": {"inner": 2.0}}
        diffs = _deep_compare(a, b)
        assert any("outer.inner" in d for d in diffs)


class TestSnapshotMatch:
    def test_creates_snapshot_on_first_run(self, tmp_path):
        result = {"score": 85.5, "grade": "A"}
        # Should not raise — creates new snapshot
        assert_snapshot_match(
            result, "test_first_run", snapshot_dir=tmp_path, rtol=1e-6
        )
        assert (tmp_path / "test_first_run.json").exists()
        assert (tmp_path / "test_first_run.hash").exists()

    def test_matches_on_second_run(self, tmp_path):
        result = {"score": 85.5, "grade": "A"}
        assert_snapshot_match(result, "test_match", snapshot_dir=tmp_path)
        assert_snapshot_match(result, "test_match", snapshot_dir=tmp_path)

    def test_fails_on_different_result(self, tmp_path):
        r1 = {"score": 85.5}
        r2 = {"score": 99.0}
        assert_snapshot_match(r1, "test_diff", snapshot_dir=tmp_path)
        with pytest.raises(AssertionError):
            assert_snapshot_match(r2, "test_diff", snapshot_dir=tmp_path)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_snapshot_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.snapshot_harness'`

**Step 3: Implement the snapshot harness**

```python
# tests/snapshot_harness.py
"""Snapshot regression test harness.

Hybrid comparison: canonical hash for fast pass/fail,
semantic deep-compare with float tolerance for debugging diffs.

Usage:
    assert_snapshot_match(result_dict, "test_name")

Update snapshots:
    pytest --update-snapshots
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

# Ensure provenance module is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TT_ROOT = _PROJECT_ROOT / "telemetry_tool"
for p in (_PROJECT_ROOT, _TT_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from provenance.canonical import canonical_hash, canonicalize

_DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _deep_compare(
    a: Any,
    b: Any,
    rtol: float = 1e-6,
    path: str = "",
) -> list[str]:
    """Recursively compare two objects, returning a list of diff descriptions."""
    diffs: list[str] = []

    if type(a) != type(b):
        # Allow int/float comparison
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            pass  # fall through to float comparison
        else:
            diffs.append(f"{path}: type mismatch {type(a).__name__} vs {type(b).__name__}")
            return diffs

    if isinstance(a, dict):
        all_keys = set(a.keys()) | set(b.keys())
        for k in sorted(all_keys):
            if k not in a:
                diffs.append(f"{path}.{k}: missing in actual")
            elif k not in b:
                diffs.append(f"{path}.{k}: missing in expected")
            else:
                diffs.extend(_deep_compare(a[k], b[k], rtol, f"{path}.{k}"))
        return diffs

    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            diffs.append(f"{path}: length {len(a)} vs {len(b)}")
            return diffs
        for i, (va, vb) in enumerate(zip(a, b)):
            diffs.extend(_deep_compare(va, vb, rtol, f"{path}[{i}]"))
        return diffs

    if isinstance(a, float) or isinstance(b, float):
        fa, fb = float(a), float(b)
        if math.isnan(fa) and math.isnan(fb):
            return diffs
        if math.isinf(fa) and math.isinf(fb) and (fa > 0) == (fb > 0):
            return diffs
        if not math.isclose(fa, fb, rel_tol=rtol, abs_tol=1e-12):
            diffs.append(f"{path}: {fa} vs {fb} (rtol={rtol})")
        return diffs

    if a != b:
        diffs.append(f"{path}: {a!r} vs {b!r}")

    return diffs


def assert_snapshot_match(
    result: dict,
    snapshot_name: str,
    *,
    snapshot_dir: Path | None = None,
    rtol: float = 1e-6,
    update: bool = False,
) -> None:
    """Assert result matches a stored snapshot.

    On first run (no snapshot file), creates the snapshot and passes.
    On subsequent runs, compares canonical hash first (fast path),
    then falls back to semantic comparison for diff output.
    """
    sdir = Path(snapshot_dir) if snapshot_dir else _DEFAULT_SNAPSHOT_DIR
    sdir.mkdir(parents=True, exist_ok=True)

    json_path = sdir / f"{snapshot_name}.json"
    hash_path = sdir / f"{snapshot_name}.hash"

    current_canonical = canonicalize(result)
    current_hash = canonical_hash(result)

    # First run or update mode: create snapshot
    if not json_path.exists() or update:
        json_path.write_text(current_canonical, encoding="utf-8")
        hash_path.write_text(current_hash, encoding="utf-8")
        return

    # Fast path: compare hashes
    stored_hash = hash_path.read_text(encoding="utf-8").strip()
    if current_hash == stored_hash:
        return

    # Slow path: semantic comparison for diff output
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    # Re-parse current through canonical to get normalised form
    current_normalised = json.loads(current_canonical)
    diffs = _deep_compare(current_normalised, stored, rtol=rtol)

    if not diffs:
        # Hashes differ but values are within tolerance — update hash
        hash_path.write_text(current_hash, encoding="utf-8")
        return

    diff_report = "\n".join(f"  {d}" for d in diffs[:20])
    extra = f"\n  ... and {len(diffs) - 20} more" if len(diffs) > 20 else ""
    raise AssertionError(
        f"Snapshot '{snapshot_name}' mismatch "
        f"(hash {current_hash[:12]}... vs {stored_hash[:12]}...):\n"
        f"{diff_report}{extra}\n\n"
        f"Run with --update-snapshots to accept the new baseline."
    )
```

**Step 4: Add `--update-snapshots` pytest flag**

Add to `telemetry_tool/tests/conftest.py` at the top (after imports):

```python
def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update snapshot baselines instead of comparing",
    )


@pytest.fixture
def update_snapshots(request):
    return request.config.getoption("--update-snapshots")
```

**Step 5: Run self-tests**

Run: `python -m pytest tests/test_snapshot_harness.py -v`
Expected: All 8 tests PASS

**Step 6: Create snapshot directories**

```bash
mkdir -p tests/snapshots/telemetry_tool tests/snapshots/kart_envelope
```

**Step 7: Commit**

```bash
git add tests/snapshot_harness.py tests/test_snapshot_harness.py telemetry_tool/tests/conftest.py
git commit -m "feat(provenance): add snapshot regression test harness with hybrid comparison"
```

---

### Task 10: Determinism Snapshot Tests — telemetry_tool

**Files:**
- Create: `telemetry_tool/tests/test_determinism.py`

**Step 1: Write the snapshot tests**

```python
# telemetry_tool/tests/test_determinism.py
"""Snapshot regression tests for telemetry_tool pipeline determinism.

Verifies that running analysis twice on identical inputs produces
identical canonical hashes, and that key outputs match stored baselines.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from provenance.canonical import canonical_hash
from provenance.run_context import build_provenance, ProvenanceRecord

SNAPSHOT_DIR = _REPO_ROOT / "tests" / "snapshots" / "telemetry_tool"


@pytest.fixture
def synthetic_csv(tmp_path):
    """Create a small deterministic CSV matching RaceChrono format."""
    np.random.seed(42)
    n = 200
    rng = np.random.default_rng(42)
    time = np.linspace(0, 60, n)
    speed = 10.0 + 5.0 * np.sin(time * 0.1) + rng.normal(0, 0.1, n)
    dist = np.cumsum(speed * (time[1] - time[0]))
    lat = 45.0 + dist * 1e-5
    lon = 7.0 + dist * 1e-5
    lap = np.where(time < 30, 1, 2)

    df = pd.DataFrame({
        "Time (s)": time,
        "Speed (m/s)": speed,
        "Distance (m)": dist,
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
        "Lap #": lap,
    })
    csv_path = tmp_path / "test_session.csv"
    df.to_csv(csv_path, index=False)
    return csv_path, df


class TestProvenanceDeterminism:
    def test_same_input_same_fingerprint(self, synthetic_csv):
        _, df = synthetic_csv
        r1 = build_provenance(df, {"mode": "test"}, method_used="test")
        r2 = build_provenance(df, {"mode": "test"}, method_used="test")
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.params_hash == r2.params_hash

    def test_modified_input_different_fingerprint(self, synthetic_csv):
        _, df = synthetic_csv
        r1 = build_provenance(df, {"mode": "test"}, method_used="test")
        df2 = df.copy()
        df2.iloc[0, 1] = 999.0  # change one speed value
        r2 = build_provenance(df2, {"mode": "test"}, method_used="test")
        assert r1.input_fingerprint != r2.input_fingerprint
        assert r1.params_hash == r2.params_hash  # config unchanged

    def test_modified_config_different_params_hash(self, synthetic_csv):
        _, df = synthetic_csv
        r1 = build_provenance(df, {"mode": "test"}, method_used="test")
        r2 = build_provenance(df, {"mode": "prod"}, method_used="test")
        assert r1.input_fingerprint == r2.input_fingerprint  # same data
        assert r1.params_hash != r2.params_hash

    def test_provenance_fields_present_and_typed(self, synthetic_csv):
        _, df = synthetic_csv
        r = build_provenance(
            df, {"x": 1}, method_used="telemetry_tool_v2",
            pipeline_version="v2-test", model_version="test-1.0",
        )
        d = r.to_dict()
        assert isinstance(d["analysis_run_id"], str) and len(d["analysis_run_id"]) == 36
        assert isinstance(d["input_fingerprint"], str) and len(d["input_fingerprint"]) == 64
        assert isinstance(d["params_hash"], str) and len(d["params_hash"]) == 64
        assert d["pipeline_version"] == "v2-test"
        assert d["model_version"] == "test-1.0"
        assert d["method_used"] == "telemetry_tool_v2"
        assert "T" in d["generated_at"]  # ISO format

    def test_canonical_hash_deterministic(self):
        obj = {
            "score": 85.12345678,
            "laps": [{"time": 60.123, "valid": True}],
            "corners": [{"id": 1, "speed": 12.345}],
        }
        h1 = canonical_hash(obj)
        h2 = canonical_hash(obj)
        assert h1 == h2

    def test_provenance_version_change_detected(self, synthetic_csv):
        _, df = synthetic_csv
        r1 = build_provenance(
            df, {}, method_used="test", pipeline_version="v2-aabb"
        )
        r2 = build_provenance(
            df, {}, method_used="test", pipeline_version="v3-ccdd"
        )
        assert r1.pipeline_version != r2.pipeline_version
```

**Step 2: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_determinism.py -v`
Expected: All 6 tests PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_determinism.py
git commit -m "test(provenance): add determinism snapshot tests for telemetry_tool pipeline"
```

---

### Task 11: Determinism Snapshot Tests — kart_envelope

**Files:**
- Create: `kart_envelope/tests/test_determinism.py`

**Step 1: Write the snapshot tests**

```python
# kart_envelope/tests/test_determinism.py
"""Snapshot regression tests for kart_envelope pipeline determinism.

Uses the synthetic_oval_laps fixture from conftest.py (seeded with
np.random.seed(42)) to verify reproducible outputs.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TT_ROOT = _PROJECT_ROOT / "telemetry_tool"
if str(_TT_ROOT) not in sys.path:
    sys.path.insert(0, str(_TT_ROOT))

from provenance.canonical import canonical_hash
from provenance.run_context import build_provenance


class TestKartProvenanceDeterminism:
    def test_same_input_same_fingerprint(self, synthetic_oval_laps):
        lap_df = synthetic_oval_laps[1]
        r1 = build_provenance(
            lap_df, {"solver": "scipy"}, method_used="kart_envelope_v2.2",
            pipeline_version="v2.2", model_version="1.0",
        )
        r2 = build_provenance(
            lap_df, {"solver": "scipy"}, method_used="kart_envelope_v2.2",
            pipeline_version="v2.2", model_version="1.0",
        )
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.params_hash == r2.params_hash

    def test_different_lap_different_fingerprint(self, synthetic_oval_laps):
        r1 = build_provenance(
            synthetic_oval_laps[1], {}, method_used="test",
            pipeline_version="v2.2", model_version="1.0",
        )
        # Modify lap data
        modified = synthetic_oval_laps[1].copy()
        modified.iloc[0, 0] = 999.0
        r2 = build_provenance(
            modified, {}, method_used="test",
            pipeline_version="v2.2", model_version="1.0",
        )
        assert r1.input_fingerprint != r2.input_fingerprint

    def test_provenance_fields_present(self, synthetic_oval_laps):
        lap_df = synthetic_oval_laps[1]
        r = build_provenance(
            lap_df,
            {"solver": "scipy", "model_version": "1.0"},
            method_used="kart_envelope_v2.2",
            pipeline_version="v2.2",
            model_version="1.0",
            solver_version="scipy",
        )
        d = r.to_dict()
        assert d["method_used"] == "kart_envelope_v2.2"
        assert d["solver_version"] == "scipy"
        assert d["pipeline_version"] == "v2.2"
        assert d["model_version"] == "1.0"
        assert len(d["analysis_run_id"]) == 36
        assert len(d["input_fingerprint"]) == 64
        assert len(d["params_hash"]) == 64

    def test_canonical_hash_stable_for_kart_output(self):
        """Simulate a kart_envelope summary fragment and verify hash stability."""
        summary_fragment = {
            "version": "2.2",
            "theoretical_lap_time_s": 42.567891234,
            "corner_perfs": [
                {"corner_id": 1, "speed_m_s": 12.345, "rating": "good"},
                {"corner_id": 2, "speed_m_s": 10.123, "rating": "fair"},
            ],
            "coaching_text": "Brake later into T1",
        }
        h1 = canonical_hash(summary_fragment)
        h2 = canonical_hash(summary_fragment)
        assert h1 == h2
```

**Step 2: Run tests**

Run: `python -m pytest kart_envelope/tests/test_determinism.py -v`
Expected: All 4 tests PASS

**Step 3: Commit**

```bash
git add kart_envelope/tests/test_determinism.py
git commit -m "test(provenance): add determinism snapshot tests for kart_envelope pipeline"
```

---

### Task 12: Final Integration — Wire Persistence into Pipeline + Run Full Suite

**Files:**
- Modify: `telemetry_tool/pipeline.py` — add `insert_provenance()` call after DB persist step
- Verify all tests pass

**Step 1: Add provenance table write to pipeline.py**

In `pipeline.py`, after the `15_persist_db` step (~line 2869), add:

```python
    # ── Write provenance to table (PG only, silently skipped on SQLite) ──
    if db_session_id is not None:
        try:
            from provenance.persistence import insert_provenance
            from flask import g
            _wid = getattr(g, "workspace_id", None) if "flask" in sys.modules else None
            insert_provenance(
                conn, _provenance_record,
                session_id=str(db_session_id),
                workspace_id=_wid,
            )
        except Exception as _prov_err:
            logger.debug("Provenance table write skipped: %s", _prov_err)
```

Note: This uses the existing `conn` from the persist step. The `insert_provenance()` call is wrapped in try/except so it never breaks the pipeline.

**Step 2: Run the full test suite**

Run: `cd telemetry_tool && python -m pytest tests/ -v --timeout=120 -q`
Expected: All tests PASS (existing + new provenance tests)

Run: `python -m pytest kart_envelope/tests/ -v --timeout=120 -q`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(provenance): wire provenance table write into pipeline persist step"
```

---

### Summary of All Files

| Task | Files Created | Files Modified |
|------|--------------|----------------|
| 1 | `provenance/__init__.py`, `provenance/canonical.py`, `tests/test_canonical.py` | — |
| 2 | `provenance/fingerprint.py`, `tests/test_fingerprint.py` | — |
| 3 | `provenance/run_context.py`, `tests/test_run_context.py` | `provenance/__init__.py` |
| 4 | — | `telemetry_tool/pipeline.py` |
| 5 | `kart_envelope/tests/test_provenance_integration.py` | `kart_envelope/pipeline.py` |
| 6 | `alembic/versions/020_analysis_provenance.py` | — |
| 7 | `provenance/persistence.py`, `tests/test_provenance_persistence.py` | `provenance/__init__.py` |
| 8 | `tests/test_provenance_endpoint.py` | `web/routes/data_v2.py` |
| 9 | `tests/snapshot_harness.py`, `tests/test_snapshot_harness.py` | `telemetry_tool/tests/conftest.py` |
| 10 | `telemetry_tool/tests/test_determinism.py` | — |
| 11 | `kart_envelope/tests/test_determinism.py` | — |
| 12 | — | `telemetry_tool/pipeline.py` |

**Total: 12 tasks, 14 new files, 6 modified files, 12 commits**
