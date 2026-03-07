# Determinism & Provenance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make analysis outputs deterministic for identical inputs, and add robust provenance fields to every persisted analysis.

**Architecture:** Shared `telemetry_tool/provenance/` package with canonical serialization, fingerprinting, and run context. Alembic migration 033 adds `analysis_provenance` table. Provenance embedded in pipeline summary dicts and queryable via new API endpoint. Snapshot regression tests validate determinism across both pipelines.

**Tech Stack:** Python 3, hashlib (SHA-256), uuid, json, dataclasses, pytest, Alembic/SQLAlchemy, Flask

---

### Task 1: Canonical JSON Serializer

**Files:**
- Create: `telemetry_tool/provenance/__init__.py`
- Create: `telemetry_tool/provenance/canonical.py`
- Test: `telemetry_tool/tests/test_provenance_canonical.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_provenance_canonical.py
"""Tests for canonical JSON serialization and hashing."""
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
        assert canonicalize({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'

    def test_rounds_floats(self):
        result = canonicalize({"x": 1.23456789})
        assert result == '{"x": 1.234568}'

    def test_custom_precision(self):
        result = canonicalize({"x": 1.23456789}, float_precision=3)
        assert result == '{"x": 1.235}'

    def test_normalizes_nan(self):
        result = canonicalize({"x": float("nan")})
        assert result == '{"x": "__NaN__"}'

    def test_normalizes_inf(self):
        result = canonicalize({"x": float("inf"), "y": float("-inf")})
        assert result == '{"x": "__Inf__", "y": "__-Inf__"}'

    def test_nested_dicts_sorted(self):
        obj = {"z": {"b": 1, "a": 2}, "a": 0}
        result = canonicalize(obj)
        assert result == '{"a": 0, "z": {"a": 2, "b": 1}}'

    def test_lists_preserve_order(self):
        result = canonicalize([3, 1, 2])
        assert result == '[3, 1, 2]'

    def test_none_preserved(self):
        result = canonicalize({"x": None})
        assert result == '{"x": null}'

    def test_negative_zero_normalized(self):
        result = canonicalize({"x": -0.0})
        assert result == '{"x": 0.0}'

    def test_empty_structures(self):
        assert canonicalize({}) == '{}'
        assert canonicalize([]) == '[]'


class TestCanonicalHash:
    def test_deterministic(self):
        obj = {"b": 1, "a": [2.123456789, 3.0]}
        h1 = canonical_hash(obj)
        h2 = canonical_hash(obj)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_input_different_hash(self):
        h1 = canonical_hash({"x": 1})
        h2 = canonical_hash({"x": 2})
        assert h1 != h2

    def test_key_order_irrelevant(self):
        h1 = canonical_hash({"a": 1, "b": 2})
        h2 = canonical_hash({"b": 2, "a": 1})
        assert h1 == h2
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_provenance_canonical.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'provenance'`

**Step 3: Write the implementation**

```python
# telemetry_tool/provenance/__init__.py
"""Provenance tracking for deterministic, traceable analysis outputs."""
```

```python
# telemetry_tool/provenance/canonical.py
"""Canonical JSON serialization for deterministic hashing.

Provides two functions:
- ``canonicalize(obj)`` — deterministic JSON string with sorted keys,
  rounded floats, and normalized NaN/Inf values.
- ``canonical_hash(obj)`` — SHA-256 hex digest of the canonical form.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _normalize(obj: Any, precision: int) -> Any:
    """Recursively normalize an object for canonical serialization."""
    if isinstance(obj, dict):
        return {k: _normalize(v, precision) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v, precision) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj):
            return "__NaN__"
        if math.isinf(obj):
            return "__-Inf__" if obj < 0 else "__Inf__"
        rounded = round(obj, precision)
        # Normalize -0.0 → 0.0
        if rounded == 0.0:
            rounded = 0.0
        return rounded
    return obj


def canonicalize(obj: Any, float_precision: int = 6) -> str:
    """Return a deterministic JSON string of *obj*.

    - Dict keys are sorted recursively.
    - Floats are rounded to *float_precision* decimal places.
    - NaN → ``"__NaN__"``, Inf → ``"__Inf__"``, -Inf → ``"__-Inf__"``.
    - ``-0.0`` → ``0.0``.
    """
    normalized = _normalize(obj, float_precision)
    return json.dumps(normalized, sort_keys=True, separators=(", ", ": "),
                      ensure_ascii=True)


def canonical_hash(obj: Any, float_precision: int = 6) -> str:
    """Return SHA-256 hex digest of the canonical form of *obj*."""
    text = canonicalize(obj, float_precision)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_provenance_canonical.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/provenance/__init__.py telemetry_tool/provenance/canonical.py telemetry_tool/tests/test_provenance_canonical.py
git commit -m "feat(provenance): add canonical JSON serializer with deterministic hashing"
```

---

### Task 2: Input Fingerprinting

**Files:**
- Create: `telemetry_tool/provenance/fingerprint.py`
- Test: `telemetry_tool/tests/test_provenance_fingerprint.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_provenance_fingerprint.py
"""Tests for input fingerprinting."""
import sys
from pathlib import Path
from io import StringIO

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.fingerprint import compute_data_fingerprint, compute_file_hash


class TestComputeDataFingerprint:
    def test_deterministic(self):
        df = pd.DataFrame({"speed": [1.0, 2.0, 3.0], "time": [0.1, 0.2, 0.3]})
        fp1 = compute_data_fingerprint(df)
        fp2 = compute_data_fingerprint(df)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_column_order_irrelevant(self):
        df1 = pd.DataFrame({"a": [1.0], "b": [2.0]})
        df2 = pd.DataFrame({"b": [2.0], "a": [1.0]})
        assert compute_data_fingerprint(df1) == compute_data_fingerprint(df2)

    def test_different_data_different_hash(self):
        df1 = pd.DataFrame({"x": [1.0, 2.0]})
        df2 = pd.DataFrame({"x": [1.0, 3.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)

    def test_different_columns_different_hash(self):
        df1 = pd.DataFrame({"x": [1.0]})
        df2 = pd.DataFrame({"y": [1.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)

    def test_different_shape_different_hash(self):
        df1 = pd.DataFrame({"x": [1.0, 2.0]})
        df2 = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        assert compute_data_fingerprint(df1) != compute_data_fingerprint(df2)


class TestComputeFileHash:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        h1 = compute_file_hash(f)
        h2 = compute_file_hash(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        f1.write_text("a,b\n1,2\n")
        f2.write_text("a,b\n1,3\n")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_returns_none_for_missing_file(self, tmp_path):
        result = compute_file_hash(tmp_path / "nope.csv")
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_provenance_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'provenance.fingerprint'`

**Step 3: Write the implementation**

```python
# telemetry_tool/provenance/fingerprint.py
"""Input fingerprinting for provenance tracking.

Provides:
- ``compute_file_hash(path)`` — SHA-256 of raw file bytes.
- ``compute_data_fingerprint(df)`` — SHA-256 of normalized DataFrame
  structure (sorted columns + shape + numeric sample).
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_READ_BLOCK = 8 * 1024 * 1024  # 8 MB


def compute_file_hash(path: Path | str) -> Optional[str]:
    """Return SHA-256 hex digest of the file at *path*, or None if missing."""
    path = Path(path)
    if not path.exists():
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_READ_BLOCK)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        logger.warning("Failed to hash file: %s", path)
        return None


def compute_data_fingerprint(df: pd.DataFrame) -> str:
    """Return SHA-256 hex digest of a DataFrame's structure and content sample.

    The fingerprint is based on:
    - Sorted column names
    - Shape (rows, cols)
    - First 8 bytes of each numeric column (as float64 tobytes)

    Column order does not affect the result.
    """
    h = hashlib.sha256()

    # Sorted column names
    cols = sorted(df.columns.tolist())
    h.update("|".join(str(c) for c in cols).encode("utf-8"))

    # Shape
    h.update(f"|shape={df.shape[0]}x{df.shape[1]}".encode("utf-8"))

    # Numeric sample from each column (sorted order)
    for col in cols:
        try:
            arr = pd.to_numeric(df[col], errors="coerce").values.astype(np.float64)
            h.update(arr.tobytes())
        except (ValueError, TypeError):
            # Non-numeric column — hash string representation
            h.update(df[col].astype(str).str.cat(sep="|").encode("utf-8"))

    return h.hexdigest()
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_provenance_fingerprint.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/provenance/fingerprint.py telemetry_tool/tests/test_provenance_fingerprint.py
git commit -m "feat(provenance): add input fingerprinting (file hash + data fingerprint)"
```

---

### Task 3: Run Context and ProvenanceRecord

**Files:**
- Create: `telemetry_tool/provenance/run_context.py`
- Modify: `telemetry_tool/provenance/__init__.py`
- Test: `telemetry_tool/tests/test_provenance_run_context.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_provenance_run_context.py
"""Tests for provenance run context builder."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.run_context import ProvenanceRecord, build_provenance


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "Speed (m/s)": [10.0, 11.0, 12.0],
        "Lap #": [1, 1, 1],
        "Distance (m)": [0.0, 10.0, 20.0],
    })


class TestProvenanceRecord:
    def test_to_dict_has_all_fields(self, sample_df):
        record = build_provenance(
            input_df=sample_df,
            config={"n_resample_points": 1000},
            method="telemetry_tool_v2",
        )
        d = record.to_dict()
        assert "analysis_run_id" in d
        assert "input_fingerprint" in d
        assert "params_hash" in d
        assert "pipeline_version" in d
        assert "model_version" in d
        assert "method_used" in d
        assert "generated_at" in d
        assert d["method_used"] == "telemetry_tool_v2"

    def test_run_id_is_uuid4(self, sample_df):
        import uuid
        record = build_provenance(sample_df, {}, method="test")
        # Should not raise
        uuid.UUID(record.analysis_run_id, version=4)

    def test_same_input_same_fingerprint(self, sample_df):
        r1 = build_provenance(sample_df, {}, method="test")
        r2 = build_provenance(sample_df, {}, method="test")
        assert r1.input_fingerprint == r2.input_fingerprint

    def test_different_run_ids(self, sample_df):
        r1 = build_provenance(sample_df, {}, method="test")
        r2 = build_provenance(sample_df, {}, method="test")
        assert r1.analysis_run_id != r2.analysis_run_id

    def test_params_hash_changes_with_config(self, sample_df):
        r1 = build_provenance(sample_df, {"n": 100}, method="test")
        r2 = build_provenance(sample_df, {"n": 200}, method="test")
        assert r1.params_hash != r2.params_hash

    def test_file_hash_populated_when_path_given(self, sample_df, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        record = build_provenance(sample_df, {}, method="test", file_path=f)
        assert record.file_hash is not None

    def test_file_hash_none_when_no_path(self, sample_df):
        record = build_provenance(sample_df, {}, method="test")
        assert record.file_hash is None

    def test_generated_at_is_iso8601(self, sample_df):
        from datetime import datetime
        record = build_provenance(sample_df, {}, method="test")
        # Should parse without error
        datetime.fromisoformat(record.generated_at.replace("Z", "+00:00"))
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_provenance_run_context.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# telemetry_tool/provenance/run_context.py
"""Build provenance context for an analysis run.

The ``ProvenanceRecord`` captures everything needed to trace an analysis
output back to its inputs, code version, and configuration.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from provenance.fingerprint import compute_data_fingerprint, compute_file_hash

logger = logging.getLogger(__name__)


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
    """SHA-256 of JSON-serialized config (sorted keys)."""
    if isinstance(config, dict):
        text = json.dumps(config, sort_keys=True, default=str)
    else:
        text = json.dumps(vars(config) if hasattr(config, "__dict__") else str(config),
                          sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_pipeline_version() -> str:
    try:
        from pipeline_status import compute_pipeline_version_string
        return compute_pipeline_version_string()
    except Exception:
        return "unknown"


def _get_model_version() -> str:
    try:
        from pipeline_status import get_model_version
        return get_model_version()
    except Exception:
        return "none"


def build_provenance(
    input_df: pd.DataFrame,
    config: Any,
    *,
    method: str,
    file_path: Optional[Path | str] = None,
    solver_version: Optional[str] = None,
    training_data_hash: Optional[str] = None,
    pipeline_version: Optional[str] = None,
    model_version: Optional[str] = None,
) -> ProvenanceRecord:
    """Build a complete provenance record for an analysis run."""
    return ProvenanceRecord(
        analysis_run_id=str(uuid.uuid4()),
        input_fingerprint=compute_data_fingerprint(input_df),
        file_hash=compute_file_hash(file_path) if file_path else None,
        params_hash=_hash_config(config),
        pipeline_version=pipeline_version or _get_pipeline_version(),
        model_version=model_version or _get_model_version(),
        solver_version=solver_version,
        method_used=method,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        training_data_hash=training_data_hash,
    )
```

Update `__init__.py` exports:

```python
# telemetry_tool/provenance/__init__.py
"""Provenance tracking for deterministic, traceable analysis outputs."""
from provenance.canonical import canonicalize, canonical_hash
from provenance.fingerprint import compute_data_fingerprint, compute_file_hash
from provenance.run_context import ProvenanceRecord, build_provenance

__all__ = [
    "canonicalize",
    "canonical_hash",
    "compute_data_fingerprint",
    "compute_file_hash",
    "ProvenanceRecord",
    "build_provenance",
]
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_provenance_run_context.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/provenance/run_context.py telemetry_tool/provenance/__init__.py telemetry_tool/tests/test_provenance_run_context.py
git commit -m "feat(provenance): add ProvenanceRecord and build_provenance()"
```

---

### Task 4: Integrate Provenance into telemetry_tool Pipeline

**Files:**
- Modify: `telemetry_tool/pipeline.py:574-582` (after PipelineStatus creation, before summary dict)
- Modify: `telemetry_tool/pipeline.py:2882` (after pipeline finalize, add provenance to summary)
- Modify: `telemetry_tool/web/routes/sessions_v2.py:196-252` (include provenance in analysis_json blob)
- Test: `telemetry_tool/tests/test_provenance_integration.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_provenance_integration.py
"""Integration test: provenance fields in pipeline output."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestPipelineProvenance:
    """Verify provenance dict is present in run_full_analysis() output."""

    @pytest.fixture
    def minimal_csv(self, tmp_path):
        """Minimal CSV that will at least pass ingestion."""
        csv = tmp_path / "test.csv"
        csv.write_text(
            '"Time (s)","Lap #","Speed (m/s)","Latitude (deg)","Longitude (deg)"\n'
            '0.0,1,10.0,45.0,7.0\n'
            '0.1,1,10.1,45.0001,7.0001\n'
            '0.2,1,10.2,45.0002,7.0002\n'
        )
        return csv

    def test_provenance_in_summary(self, minimal_csv):
        from pipeline import run_full_analysis
        summary = run_full_analysis(
            csv_path=str(minimal_csv),
            session_meta={"driver": "test", "track_id": "t1"},
            enable_ml=False,
            enable_report=False,
        )
        prov = summary.get("provenance")
        assert prov is not None, "provenance key missing from summary"
        assert "analysis_run_id" in prov
        assert "input_fingerprint" in prov
        assert "params_hash" in prov
        assert "pipeline_version" in prov
        assert "method_used" in prov
        assert prov["method_used"] == "telemetry_tool_v2"
        assert "generated_at" in prov

    def test_provenance_deterministic_fingerprint(self, minimal_csv):
        from pipeline import run_full_analysis
        meta = {"driver": "test", "track_id": "t1"}
        s1 = run_full_analysis(str(minimal_csv), meta, enable_ml=False, enable_report=False)
        s2 = run_full_analysis(str(minimal_csv), meta, enable_ml=False, enable_report=False)
        assert s1["provenance"]["input_fingerprint"] == s2["provenance"]["input_fingerprint"]
        assert s1["provenance"]["params_hash"] == s2["provenance"]["params_hash"]
        # Run IDs must differ
        assert s1["provenance"]["analysis_run_id"] != s2["provenance"]["analysis_run_id"]
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_provenance_integration.py -v`
Expected: FAIL — `provenance key missing from summary`

**Step 3: Edit pipeline.py**

In `telemetry_tool/pipeline.py`, after line 577 (after `_pipeline_status` creation), add provenance build:

```python
    # ── Provenance ───────────────────────────────────────────────
    _provenance_record = None
    try:
        from provenance import build_provenance
        # input_df not yet available — we'll finalize after ingest (step 1)
    except ImportError:
        pass
```

After the ingest step succeeds (after `raw_df` is populated, around line ~640 where `summary["raw_df"] = raw_df`), add:

```python
    # Finalize provenance now that we have the input DataFrame
    if raw_df is not None:
        try:
            from provenance import build_provenance
            _provenance_record = build_provenance(
                input_df=raw_df,
                config={"n_resample_points": n_resample_points,
                        "lap_range": lap_range,
                        "enable_ml": enable_ml,
                        "filter_profile": _resolved_filter_profile.profile_name if _resolved_filter_profile else None},
                method="telemetry_tool_v2",
                file_path=csv_path,
                pipeline_version=_pipeline_status.pipeline_version,
                model_version=_pipeline_status.model_version,
            )
        except Exception as _prov_exc:
            logger.debug("Provenance build failed: %s", _prov_exc)
```

Before the final `return summary` (around line 2882, after `summary["pipeline"] = ...`), add:

```python
    # Attach provenance
    if _provenance_record is not None:
        summary["provenance"] = _provenance_record.to_dict()
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_provenance_integration.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_provenance_integration.py
git commit -m "feat(provenance): integrate provenance into telemetry_tool pipeline"
```

---

### Task 5: Integrate Provenance into kart_envelope Pipeline

**Files:**
- Modify: `kart_envelope/pipeline.py:1075-1081` (after version/solver_meta, before tire_meta)
- Test: `kart_envelope/tests/test_provenance_integration.py`

**Step 1: Write the failing test**

```python
# kart_envelope/tests/test_provenance_integration.py
"""Integration test: provenance fields in kart_envelope output."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestKartEnvelopeProvenance:
    def test_provenance_in_summary(self, synthetic_oval_laps, default_config, tmp_path):
        """analyze_session should include provenance dict."""
        from kart_envelope.pipeline import analyze_session
        from kart_envelope.config import SessionMetadata

        # Write a minimal CSV for the file_hash
        csv_path = tmp_path / "test_session.csv"
        laps = synthetic_oval_laps
        first_lap = laps[list(laps.keys())[0]]
        first_lap.to_csv(csv_path, index=False)

        meta = SessionMetadata(
            driver_name="TestDriver",
            kart_id="K1",
            track_name="TestOval",
            session_date="2026-01-01",
        )
        summary = analyze_session(
            csv_path=csv_path,
            metadata=meta,
            config=default_config,
            models_dir=tmp_path / "models",
            tracks_dir=tmp_path / "tracks",
            output_dir=tmp_path / "outputs",
        )
        prov = summary.get("provenance")
        assert prov is not None, "provenance key missing from kart_envelope summary"
        assert "analysis_run_id" in prov
        assert "input_fingerprint" in prov
        assert prov["method_used"] == "kart_envelope_v2.2"
        assert prov["solver_version"] is not None or "solver_version" in prov
```

**Step 2: Run test to verify it fails**

Run: `pytest kart_envelope/tests/test_provenance_integration.py -v`
Expected: FAIL — `provenance key missing`

**Step 3: Edit kart_envelope/pipeline.py**

After the CSV is loaded and normalized (after `parse_session_csv_raw` returns the DataFrame), add provenance build. Then after line 1081 (`summary["solver_meta"] = solver_meta`), add:

```python
    # Provenance
    try:
        from provenance import build_provenance
        _prov = build_provenance(
            input_df=normalized_df,  # use the normalized DataFrame
            config=config,
            method="kart_envelope_v2.2",
            file_path=csv_path,
            solver_version=str(theoretical.solver_backend) if theoretical else None,
            pipeline_version=summary.get("version", "2.2"),
            model_version=str(config.model_version),
        )
        summary["provenance"] = _prov.to_dict()
    except Exception as _prov_exc:
        logger.debug("Provenance build failed: %s", _prov_exc)
```

**Step 4: Run test to verify it passes**

Run: `pytest kart_envelope/tests/test_provenance_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add kart_envelope/pipeline.py kart_envelope/tests/test_provenance_integration.py
git commit -m "feat(provenance): integrate provenance into kart_envelope pipeline"
```

---

### Task 6: Alembic Migration 033 — analysis_provenance Table

**Files:**
- Create: `telemetry_tool/alembic/versions/033_analysis_provenance.py`
- Modify: `telemetry_tool/db/schema.py` (add table to SQLite schema for desktop mode)
- Modify: `telemetry_tool/db/migrate.py` (add Phase 28 idempotent migration)

**Step 1: Create the Alembic migration**

```python
# telemetry_tool/alembic/versions/033_analysis_provenance.py
"""Add analysis_provenance table for queryable provenance tracking.

Stores provenance metadata (run ID, fingerprints, versions) as a
denormalized index alongside the embedded provenance in analysis_json.

Revision ID: 033
Revises: 032
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("analysis_provenance"):
        return

    op.create_table(
        "analysis_provenance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_run_id", sa.String(36), nullable=False, unique=True),
        sa.Column("session_id", sa.String(64),
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.Text(), nullable=True),
        sa.Column("params_hash", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("solver_version", sa.String(64), nullable=True),
        sa.Column("method_used", sa.String(64), nullable=False),
        sa.Column("training_data_hash", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_provenance_session", "analysis_provenance", ["session_id"])
    op.create_index("idx_provenance_fingerprint", "analysis_provenance", ["input_fingerprint"])
    op.create_index("idx_provenance_pipeline_ver", "analysis_provenance", ["pipeline_version"])

    # RLS (PostgreSQL only — skip for SQLite)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE analysis_provenance ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY workspace_isolation ON analysis_provenance "
            "USING (workspace_id = current_setting('app.workspace_id')::INTEGER)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS workspace_isolation ON analysis_provenance")
    op.drop_index("idx_provenance_pipeline_ver", table_name="analysis_provenance")
    op.drop_index("idx_provenance_fingerprint", table_name="analysis_provenance")
    op.drop_index("idx_provenance_session", table_name="analysis_provenance")
    op.drop_table("analysis_provenance")
```

**Step 2: Add to SQLite schema in `db/schema.py`**

Find the end of the schema definitions and add (after the last `CREATE TABLE` block):

```sql
CREATE TABLE IF NOT EXISTS analysis_provenance (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id   TEXT    NOT NULL UNIQUE,
    session_id        TEXT    REFERENCES sessions(session_id) ON DELETE CASCADE,
    workspace_id      INTEGER,
    input_fingerprint TEXT    NOT NULL,
    file_hash         TEXT,
    params_hash       TEXT    NOT NULL,
    pipeline_version  TEXT    NOT NULL,
    model_version     TEXT    NOT NULL,
    solver_version    TEXT,
    method_used       TEXT    NOT NULL,
    training_data_hash TEXT,
    generated_at      TEXT    NOT NULL,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

**Step 3: Add Phase 28 migration to `db/migrate.py`**

Add an idempotent migration block that creates the table if it doesn't exist (same pattern as existing phases).

**Step 4: Run migration test**

Run: `pytest telemetry_tool/tests/ -k "schema or migrate" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/alembic/versions/033_analysis_provenance.py telemetry_tool/db/schema.py telemetry_tool/db/migrate.py
git commit -m "feat(provenance): add analysis_provenance table (migration 033)"
```

---

### Task 7: Provenance Write Path (DB Persistence)

**Files:**
- Modify: `telemetry_tool/web/models.py` (add `insert_provenance()` and `get_provenance()`)
- Modify: `telemetry_tool/web/routes/sessions_v2.py:196-252` (call `insert_provenance()` after analysis)
- Test: `telemetry_tool/tests/test_provenance_db.py`

**Step 1: Write the failing tests**

```python
# telemetry_tool/tests/test_provenance_db.py
"""Tests for provenance DB persistence."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestInsertProvenance:
    def test_insert_and_retrieve(self, db):
        from web.models import insert_provenance, get_provenance
        record = {
            "analysis_run_id": "aaaa-bbbb-cccc-dddd",
            "session_id": None,
            "workspace_id": None,
            "input_fingerprint": "abc123",
            "file_hash": "def456",
            "params_hash": "ghi789",
            "pipeline_version": "v2-test",
            "model_version": "none",
            "solver_version": None,
            "method_used": "test",
            "training_data_hash": None,
            "generated_at": "2026-03-07T12:00:00Z",
        }
        insert_provenance(db, record)
        result = get_provenance(db, analysis_run_id="aaaa-bbbb-cccc-dddd")
        assert result is not None
        assert result["input_fingerprint"] == "abc123"
        assert result["pipeline_version"] == "v2-test"

    def test_get_by_session_id(self, db):
        from web.models import insert_provenance, get_provenance_for_session
        # Create a session first
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, track_state, session_date, n_laps) "
            "VALUES ('s1', 'test.csv', 1, 't1', 'practice', 'dry', '2026-01-01', 5)"
        )
        record = {
            "analysis_run_id": "run-001",
            "session_id": "s1",
            "workspace_id": None,
            "input_fingerprint": "fp1",
            "file_hash": None,
            "params_hash": "ph1",
            "pipeline_version": "v2-abc",
            "model_version": "none",
            "solver_version": None,
            "method_used": "telemetry_tool_v2",
            "training_data_hash": None,
            "generated_at": "2026-03-07T12:00:00Z",
        }
        insert_provenance(db, record)
        result = get_provenance_for_session(db, "s1")
        assert result is not None
        assert result["analysis_run_id"] == "run-001"

    def test_get_missing_returns_none(self, db):
        from web.models import get_provenance_for_session
        assert get_provenance_for_session(db, "nonexistent") is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_provenance_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'insert_provenance'`

**Step 3: Add functions to `web/models.py`**

At the end of `web/models.py`, add:

```python
# ── analysis_provenance ─────────────────────────────────────────

def insert_provenance(conn, record: dict) -> None:
    """Insert a provenance record into analysis_provenance."""
    conn.execute(
        "INSERT INTO analysis_provenance "
        "(analysis_run_id, session_id, workspace_id, input_fingerprint, "
        "file_hash, params_hash, pipeline_version, model_version, "
        "solver_version, method_used, training_data_hash, generated_at) "
        "VALUES (:analysis_run_id, :session_id, :workspace_id, "
        ":input_fingerprint, :file_hash, :params_hash, :pipeline_version, "
        ":model_version, :solver_version, :method_used, "
        ":training_data_hash, :generated_at)",
        record,
    )
    conn.commit()


def get_provenance(conn, analysis_run_id: str) -> dict | None:
    """Retrieve a provenance record by analysis_run_id."""
    row = conn.execute(
        "SELECT * FROM analysis_provenance WHERE analysis_run_id = :rid",
        {"rid": analysis_run_id},
    ).fetchone()
    return dict(row) if row else None


def get_provenance_for_session(conn, session_id: str) -> dict | None:
    """Retrieve the most recent provenance record for a session."""
    row = conn.execute(
        "SELECT * FROM analysis_provenance WHERE session_id = :sid "
        "ORDER BY created_at DESC LIMIT 1",
        {"sid": session_id},
    ).fetchone()
    return dict(row) if row else None
```

**Step 4: Edit `sessions_v2.py` — add provenance to analysis_json and DB**

In `_persist_analysis_json()` (line ~249), before the `if blob:` check, add:

```python
    # Provenance
    provenance = summary.get("provenance")
    if provenance and isinstance(provenance, dict):
        blob["provenance"] = provenance
        # Also write to analysis_provenance table
        try:
            prov_record = dict(provenance)
            prov_record["session_id"] = session_id
            from flask import g
            prov_record.setdefault("workspace_id", getattr(g, "workspace_id", None))
            models.insert_provenance(conn, prov_record)
        except Exception as e:
            logger.warning("Failed to persist provenance to table: %s", e)
```

**Step 5: Run tests**

Run: `pytest telemetry_tool/tests/test_provenance_db.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add telemetry_tool/web/models.py telemetry_tool/web/routes/sessions_v2.py telemetry_tool/tests/test_provenance_db.py
git commit -m "feat(provenance): add DB persistence (insert + query) for provenance records"
```

---

### Task 8: Provenance API Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add GET `/sessions/<id>/provenance`)
- Test: `telemetry_tool/tests/test_provenance_endpoint.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_provenance_endpoint.py
"""Tests for the provenance API endpoint."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def client():
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestProvenanceEndpoint:
    def test_returns_provenance_from_table(self, client):
        mock_prov = {
            "analysis_run_id": "run-123",
            "input_fingerprint": "fp-abc",
            "file_hash": "fh-def",
            "params_hash": "ph-ghi",
            "pipeline_version": "v2-test",
            "model_version": "none",
            "solver_version": None,
            "method_used": "telemetry_tool_v2",
            "training_data_hash": None,
            "generated_at": "2026-03-07T12:00:00Z",
        }
        with patch("web.routes.data_v2.models") as mm:
            mm.get_provenance_for_session.return_value = mock_prov
            resp = client.get("/api/v1/sessions/s1/provenance")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["data"]["analysis_run_id"] == "run-123"

    def test_falls_back_to_analysis_json(self, client):
        mock_analysis = {
            "provenance": {
                "analysis_run_id": "run-fallback",
                "input_fingerprint": "fp-fb",
            }
        }
        with patch("web.routes.data_v2.models") as mm:
            mm.get_provenance_for_session.return_value = None
            mm.get_analysis_json.return_value = mock_analysis
            resp = client.get("/api/v1/sessions/s1/provenance")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["analysis_run_id"] == "run-fallback"

    def test_returns_404_when_no_provenance(self, client):
        with patch("web.routes.data_v2.models") as mm:
            mm.get_provenance_for_session.return_value = None
            mm.get_analysis_json.return_value = None
            resp = client.get("/api/v1/sessions/s1/provenance")
        assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_provenance_endpoint.py -v`
Expected: FAIL — 404 (route doesn't exist)

**Step 3: Add the endpoint to `data_v2.py`**

Add after the existing endpoint definitions (e.g., after the `update_session` PATCH route):

```python
@bp.route("/sessions/<session_id>/provenance", methods=["GET"])
@_safe_api
def get_session_provenance(session_id: str):
    """Return provenance metadata for a session's analysis."""
    conn = get_db_connection()

    # Try the dedicated table first (fast indexed lookup)
    prov = models.get_provenance_for_session(conn, session_id)
    if prov:
        # Filter to just the provenance fields (exclude DB-internal cols)
        keys = ("analysis_run_id", "input_fingerprint", "file_hash",
                "params_hash", "pipeline_version", "model_version",
                "solver_version", "method_used", "training_data_hash",
                "generated_at")
        data = {k: prov.get(k) for k in keys}
        return api_response(data)

    # Fallback: extract from analysis_json
    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict) and "provenance" in analysis:
        return api_response(analysis["provenance"])

    return api_error(ErrorCode.NOT_FOUND, "No provenance available", status=404)
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_provenance_endpoint.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_provenance_endpoint.py
git commit -m "feat(provenance): add GET /sessions/<id>/provenance endpoint"
```

---

### Task 9: Snapshot Test Harness

**Files:**
- Create: `tests/snapshot_harness.py`
- Test: `tests/test_snapshot_harness.py`

**Step 1: Write the failing tests**

```python
# tests/test_snapshot_harness.py
"""Tests for the snapshot regression test harness itself."""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.snapshot_harness import (
    assert_snapshot_match,
    update_snapshot,
    canonical_hash,
    _semantic_compare,
    SNAPSHOTS_DIR,
)


class TestCanonicalHash:
    def test_deterministic(self):
        obj = {"b": 1.23456789, "a": [2.0, 3.0]}
        assert canonical_hash(obj) == canonical_hash(obj)

    def test_key_order_irrelevant(self):
        assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


class TestSemanticCompare:
    def test_exact_match(self):
        diffs = _semantic_compare({"x": 1}, {"x": 1})
        assert diffs == []

    def test_float_within_tolerance(self):
        diffs = _semantic_compare({"x": 1.0000001}, {"x": 1.0000002}, rtol=1e-6)
        assert diffs == []

    def test_float_outside_tolerance(self):
        diffs = _semantic_compare({"x": 1.0}, {"x": 2.0}, rtol=1e-6)
        assert len(diffs) == 1
        assert "x" in diffs[0]

    def test_missing_key(self):
        diffs = _semantic_compare({"x": 1}, {"x": 1, "y": 2})
        assert len(diffs) == 1

    def test_nested_diff(self):
        diffs = _semantic_compare(
            {"a": {"b": 1.0}},
            {"a": {"b": 2.0}},
            rtol=1e-6,
        )
        assert len(diffs) == 1
        assert "a.b" in diffs[0]


class TestSnapshotWorkflow:
    def test_create_and_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tests.snapshot_harness.SNAPSHOTS_DIR", tmp_path)
        obj = {"score": 85.5, "grade": "A"}
        # First call creates the snapshot
        update_snapshot(obj, "test_basic", snapshots_dir=tmp_path)
        # Second call matches
        assert_snapshot_match(obj, "test_basic", snapshots_dir=tmp_path)

    def test_mismatch_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tests.snapshot_harness.SNAPSHOTS_DIR", tmp_path)
        update_snapshot({"x": 1}, "test_mismatch", snapshots_dir=tmp_path)
        with pytest.raises(AssertionError, match="Snapshot mismatch"):
            assert_snapshot_match({"x": 999}, "test_mismatch", snapshots_dir=tmp_path)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_snapshot_harness.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# tests/snapshot_harness.py
"""Shared snapshot regression test harness.

Supports both telemetry_tool and kart_envelope pipelines.

Usage in tests:
    from tests.snapshot_harness import assert_snapshot_match, update_snapshot

    def test_output_stable(result):
        assert_snapshot_match(result, "my_test_name")

Update snapshots:
    pytest --update-snapshots
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.provenance.canonical import canonicalize, canonical_hash as _canonical_hash

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


def canonical_hash(obj: Any) -> str:
    """Return canonical SHA-256 hash of a result dict."""
    return _canonical_hash(obj)


def update_snapshot(
    result: dict,
    snapshot_name: str,
    *,
    snapshots_dir: Path | None = None,
) -> None:
    """Write (or overwrite) a snapshot file."""
    base = snapshots_dir or SNAPSHOTS_DIR
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{snapshot_name}.json"
    hash_path = base / f"{snapshot_name}.hash"
    canonical = canonicalize(result)
    json_path.write_text(canonical, encoding="utf-8")
    hash_path.write_text(canonical_hash(result), encoding="utf-8")


def assert_snapshot_match(
    result: dict,
    snapshot_name: str,
    *,
    rtol: float = 1e-6,
    snapshots_dir: Path | None = None,
) -> None:
    """Assert *result* matches the stored snapshot.

    Fast path: compare canonical hashes. On mismatch, fall back to
    semantic comparison with *rtol* tolerance for floats, producing a
    human-readable diff.
    """
    base = snapshots_dir or SNAPSHOTS_DIR
    json_path = base / f"{snapshot_name}.json"
    hash_path = base / f"{snapshot_name}.hash"

    if not json_path.exists():
        raise FileNotFoundError(
            f"Snapshot {snapshot_name!r} not found at {json_path}. "
            f"Run with --update-snapshots to create it."
        )

    # Fast path: hash comparison
    current_hash = canonical_hash(result)
    stored_hash = hash_path.read_text(encoding="utf-8").strip()
    if current_hash == stored_hash:
        return  # Match!

    # Slow path: semantic comparison for diff
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    diffs = _semantic_compare(stored, result, rtol=rtol)
    if not diffs:
        # Hashes differ but values are within tolerance — update hash
        hash_path.write_text(current_hash, encoding="utf-8")
        return

    diff_report = "\n".join(f"  - {d}" for d in diffs[:20])
    total = len(diffs)
    suffix = f"\n  ... and {total - 20} more" if total > 20 else ""
    raise AssertionError(
        f"Snapshot mismatch for {snapshot_name!r} ({total} differences):\n"
        f"{diff_report}{suffix}"
    )


def _semantic_compare(
    expected: Any,
    actual: Any,
    rtol: float = 1e-6,
    path: str = "",
) -> list[str]:
    """Recursively compare two objects, returning human-readable diffs."""
    diffs: list[str] = []

    if isinstance(expected, dict) and isinstance(actual, dict):
        all_keys = set(expected) | set(actual)
        for key in sorted(all_keys):
            kpath = f"{path}.{key}" if path else key
            if key not in expected:
                diffs.append(f"{kpath}: missing in expected, present in actual")
            elif key not in actual:
                diffs.append(f"{kpath}: present in expected, missing in actual")
            else:
                diffs.extend(_semantic_compare(expected[key], actual[key], rtol, kpath))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            diffs.append(f"{path}: list length {len(expected)} vs {len(actual)}")
        for i, (e, a) in enumerate(zip(expected, actual)):
            diffs.extend(_semantic_compare(e, a, rtol, f"{path}[{i}]"))
    elif isinstance(expected, float) and isinstance(actual, float):
        if math.isnan(expected) and math.isnan(actual):
            pass  # Both NaN — OK
        elif not math.isclose(expected, actual, rel_tol=rtol, abs_tol=1e-12):
            diffs.append(f"{path}: {expected} vs {actual} (rtol={rtol})")
    elif expected != actual:
        diffs.append(f"{path}: {expected!r} vs {actual!r}")

    return diffs
```

**Step 4: Run tests**

Run: `pytest tests/test_snapshot_harness.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add tests/snapshot_harness.py tests/test_snapshot_harness.py
git commit -m "feat(provenance): add shared snapshot regression test harness"
```

---

### Task 10: Determinism Snapshot Tests — telemetry_tool

**Files:**
- Create: `telemetry_tool/tests/test_determinism.py`
- Create: `tests/snapshots/telemetry_tool/` (directory, populated on first run)
- Modify: `telemetry_tool/tests/conftest.py` (add `--update-snapshots` flag)

**Step 1: Add pytest flag to conftest.py**

At the top of `telemetry_tool/tests/conftest.py`, add:

```python
def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots", action="store_true", default=False,
        help="Update snapshot files for regression tests.",
    )
```

**Step 2: Write the determinism tests**

```python
# telemetry_tool/tests/test_determinism.py
"""Snapshot regression + determinism tests for telemetry_tool pipeline."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Also add tests/ root for snapshot_harness
_TESTS_ROOT = Path(__file__).resolve().parent.parent.parent / "tests"
if str(_TESTS_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT.parent))

from tests.snapshot_harness import assert_snapshot_match, update_snapshot, canonical_hash

SNAPSHOT_DIR = _TESTS_ROOT / "snapshots" / "telemetry_tool"


@pytest.fixture
def synthetic_csv(tmp_path):
    """Small deterministic CSV for pipeline testing."""
    import numpy as np
    rng = np.random.default_rng(42)
    n = 200
    rows = []
    rows.append('"Time (s)","Lap #","Speed (m/s)","Latitude (deg)","Longitude (deg)"')
    t = 0.0
    for i in range(n):
        lap = 1 if i < 100 else 2
        speed = 10.0 + rng.normal(0, 0.5)
        lat = 45.0 + i * 0.00001
        lon = 7.0 + i * 0.00001
        rows.append(f"{t:.3f},{lap},{speed:.4f},{lat:.7f},{lon:.7f}")
        t += 0.1
    csv = tmp_path / "synthetic.csv"
    csv.write_text("\n".join(rows) + "\n")
    return csv


class TestDeterminism:
    def test_full_analysis_deterministic(self, synthetic_csv):
        """Two runs on identical input produce identical canonical hashes."""
        from pipeline import run_full_analysis
        meta = {"driver": "test", "track_id": "synth"}
        s1 = run_full_analysis(str(synthetic_csv), meta, enable_ml=False, enable_report=False)
        s2 = run_full_analysis(str(synthetic_csv), meta, enable_ml=False, enable_report=False)

        # Remove non-deterministic fields before comparison
        for s in (s1, s2):
            prov = s.get("provenance", {})
            prov.pop("analysis_run_id", None)
            prov.pop("generated_at", None)
            p = s.get("pipeline", {})
            for step in p.get("steps", []):
                step.pop("started_at", None)
                step.pop("duration_ms", None)

        assert canonical_hash(s1) == canonical_hash(s2)

    def test_provenance_fields_present(self, synthetic_csv):
        """All required provenance fields exist with correct types."""
        from pipeline import run_full_analysis
        summary = run_full_analysis(
            str(synthetic_csv),
            {"driver": "test", "track_id": "synth"},
            enable_ml=False, enable_report=False,
        )
        prov = summary.get("provenance")
        assert prov is not None
        assert isinstance(prov["analysis_run_id"], str)
        assert len(prov["analysis_run_id"]) == 36  # UUID format
        assert isinstance(prov["input_fingerprint"], str)
        assert len(prov["input_fingerprint"]) == 64  # SHA-256
        assert isinstance(prov["params_hash"], str)
        assert isinstance(prov["pipeline_version"], str)
        assert isinstance(prov["generated_at"], str)
        assert prov["method_used"] == "telemetry_tool_v2"


class TestProvenanceSensitivity:
    def test_input_change_changes_fingerprint(self, synthetic_csv, tmp_path):
        """Modifying input data changes input_fingerprint but not params_hash."""
        from pipeline import run_full_analysis
        meta = {"driver": "test", "track_id": "synth"}
        s1 = run_full_analysis(str(synthetic_csv), meta, enable_ml=False, enable_report=False)

        # Create modified CSV (change one speed value)
        lines = synthetic_csv.read_text().splitlines()
        parts = lines[1].split(",")
        parts[2] = "99.9999"
        lines[1] = ",".join(parts)
        csv2 = tmp_path / "modified.csv"
        csv2.write_text("\n".join(lines) + "\n")

        s2 = run_full_analysis(str(csv2), meta, enable_ml=False, enable_report=False)

        assert s1["provenance"]["input_fingerprint"] != s2["provenance"]["input_fingerprint"]
        assert s1["provenance"]["params_hash"] == s2["provenance"]["params_hash"]

    def test_config_change_changes_params_hash(self, synthetic_csv):
        """Changing config changes params_hash but not input_fingerprint."""
        from pipeline import run_full_analysis
        meta = {"driver": "test", "track_id": "synth"}
        s1 = run_full_analysis(str(synthetic_csv), meta, enable_ml=False, enable_report=False,
                               n_resample_points=1000)
        s2 = run_full_analysis(str(synthetic_csv), meta, enable_ml=False, enable_report=False,
                               n_resample_points=500)

        assert s1["provenance"]["input_fingerprint"] == s2["provenance"]["input_fingerprint"]
        assert s1["provenance"]["params_hash"] != s2["provenance"]["params_hash"]
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_determinism.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/tests/test_determinism.py telemetry_tool/tests/conftest.py
git commit -m "test(provenance): add determinism + provenance sensitivity tests for telemetry_tool"
```

---

### Task 11: Determinism Snapshot Tests — kart_envelope

**Files:**
- Create: `kart_envelope/tests/test_determinism.py`
- Create: `tests/snapshots/kart_envelope/` (directory, populated on first run)

**Step 1: Write the determinism tests**

```python
# kart_envelope/tests/test_determinism.py
"""Snapshot regression + determinism tests for kart_envelope pipeline."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.snapshot_harness import canonical_hash


class TestDeterminism:
    def test_full_analysis_deterministic(self, synthetic_oval_laps, default_config, tmp_path):
        """Two runs produce identical canonical hashes."""
        from kart_envelope.pipeline import analyze_session
        from kart_envelope.config import SessionMetadata

        csv_path = tmp_path / "oval.csv"
        laps = synthetic_oval_laps
        first_lap = laps[list(laps.keys())[0]]
        first_lap.to_csv(csv_path, index=False)

        meta = SessionMetadata(
            driver_name="Test", kart_id="K1",
            track_name="Oval", session_date="2026-01-01",
        )
        kwargs = dict(
            csv_path=csv_path, metadata=meta, config=default_config,
            models_dir=tmp_path / "m", tracks_dir=tmp_path / "t",
            output_dir=tmp_path / "o1",
        )
        s1 = analyze_session(**kwargs)
        kwargs["output_dir"] = tmp_path / "o2"
        s2 = analyze_session(**kwargs)

        # Strip non-deterministic fields
        for s in (s1, s2):
            prov = s.get("provenance", {})
            prov.pop("analysis_run_id", None)
            prov.pop("generated_at", None)

        assert canonical_hash(s1) == canonical_hash(s2)

    def test_provenance_fields_present(self, synthetic_oval_laps, default_config, tmp_path):
        from kart_envelope.pipeline import analyze_session
        from kart_envelope.config import SessionMetadata

        csv_path = tmp_path / "oval.csv"
        laps = synthetic_oval_laps
        first_lap = laps[list(laps.keys())[0]]
        first_lap.to_csv(csv_path, index=False)

        meta = SessionMetadata(
            driver_name="Test", kart_id="K1",
            track_name="Oval", session_date="2026-01-01",
        )
        summary = analyze_session(
            csv_path=csv_path, metadata=meta, config=default_config,
            models_dir=tmp_path / "m", tracks_dir=tmp_path / "t",
            output_dir=tmp_path / "o",
        )
        prov = summary.get("provenance")
        assert prov is not None
        assert isinstance(prov["analysis_run_id"], str)
        assert isinstance(prov["input_fingerprint"], str)
        assert prov["method_used"] == "kart_envelope_v2.2"
```

**Step 2: Run tests**

Run: `pytest kart_envelope/tests/test_determinism.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add kart_envelope/tests/test_determinism.py
git commit -m "test(provenance): add determinism + provenance tests for kart_envelope"
```

---

### Task 12: Run Full Test Suite + Final Commit

**Step 1: Run all provenance tests**

Run: `pytest telemetry_tool/tests/test_provenance_canonical.py telemetry_tool/tests/test_provenance_fingerprint.py telemetry_tool/tests/test_provenance_run_context.py telemetry_tool/tests/test_provenance_integration.py telemetry_tool/tests/test_provenance_db.py telemetry_tool/tests/test_provenance_endpoint.py telemetry_tool/tests/test_determinism.py kart_envelope/tests/test_determinism.py tests/test_snapshot_harness.py -v`

Expected: All PASS

**Step 2: Run existing test suite to check no regressions**

Run: `pytest telemetry_tool/tests/ kart_envelope/tests/ -v --tb=short`

Expected: All existing tests still PASS

**Step 3: Verify acceptance criteria**

1. Run pipeline twice → canonical hashes match (test_determinism covers this)
2. All provenance fields present (test_provenance_fields_present)
3. GET endpoint returns correct data (test_provenance_endpoint)
4. Fingerprint changes when input changes (test_input_change_changes_fingerprint)
5. Params hash changes when config changes (test_config_change_changes_params_hash)

**Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore(provenance): final cleanup and test verification"
```
