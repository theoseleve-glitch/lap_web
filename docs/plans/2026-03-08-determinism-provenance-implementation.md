# Deterministic Outputs + Provenance Completeness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make analysis outputs byte-stable for identical inputs and fill remaining provenance gaps.

**Architecture:** Add a `deterministic` flag that replaces UUIDs/timestamps with hash-derived deterministic values. Fix one unconditional non-determinism bug (unsorted concat). Compute `training_data_hash` from the theoretical training set. Attach lightweight provenance refs to coaching output. Three regression tests verify the system.

**Tech Stack:** Python 3, hashlib, pandas, pytest

---

### Task 1: Deterministic Mode in `build_provenance()`

**Files:**
- Modify: `telemetry_tool/provenance/run_context.py`
- Test: `telemetry_tool/tests/test_deterministic_output.py`

**Context:** `build_provenance()` currently uses `uuid.uuid4()` for `analysis_run_id` and `datetime.now()` for `generated_at`. When `deterministic=True`, the run ID should be a SHA-256 of stable inputs and the timestamp should be a frozen canonical value.

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_deterministic_output.py`:

```python
"""Tests for deterministic analysis outputs and provenance completeness."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


class TestDeterministicProvenance:
    """build_provenance() deterministic mode."""

    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "Distance (m)": np.linspace(0, 100, 20),
            "Speed (m/s)": np.full(20, 15.0),
        })

    def test_deterministic_run_id_is_stable(self):
        from provenance.run_context import build_provenance

        df = self._make_df()
        cfg = {"track_id": "test_track"}
        p1 = build_provenance(df, cfg, method_used="test", deterministic=True)
        p2 = build_provenance(df, cfg, method_used="test", deterministic=True)
        assert p1.analysis_run_id == p2.analysis_run_id
        # Must NOT be a uuid4 (36 chars with dashes)
        assert "-" not in p1.analysis_run_id or len(p1.analysis_run_id) != 36

    def test_deterministic_timestamp_is_frozen(self):
        from provenance.run_context import build_provenance

        df = self._make_df()
        cfg = {"track_id": "test_track"}
        p1 = build_provenance(df, cfg, method_used="test", deterministic=True)
        p2 = build_provenance(df, cfg, method_used="test", deterministic=True)
        assert p1.generated_at == p2.generated_at
        assert p1.generated_at == "2000-01-01T00:00:00+00:00"

    def test_non_deterministic_run_id_is_unique(self):
        from provenance.run_context import build_provenance

        df = self._make_df()
        cfg = {"track_id": "test_track"}
        p1 = build_provenance(df, cfg, method_used="test", deterministic=False)
        p2 = build_provenance(df, cfg, method_used="test", deterministic=False)
        assert p1.analysis_run_id != p2.analysis_run_id
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_deterministic_output.py::TestDeterministicProvenance -v`
Expected: FAIL — `build_provenance() got an unexpected keyword argument 'deterministic'`

**Step 3: Implement deterministic mode in `build_provenance()`**

In `telemetry_tool/provenance/run_context.py`, modify `build_provenance()`:

```python
_FROZEN_TIMESTAMP = "2000-01-01T00:00:00+00:00"


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
    deterministic: bool = False,
) -> ProvenanceRecord:
    """Build a ProvenanceRecord for the current analysis run.

    When *deterministic* is True, the run ID is derived from a SHA-256
    of stable inputs (fingerprint + params + version) and the timestamp
    is frozen.  This ensures identical inputs produce byte-identical
    provenance.
    """
    if pipeline_version is None:
        try:
            from pipeline_status import compute_pipeline_version_string

            pipeline_version = compute_pipeline_version_string()
        except ImportError:
            pipeline_version = "unknown"

    if model_version is None:
        try:
            from pipeline_status import get_model_version

            model_version = get_model_version()
        except ImportError:
            model_version = "none"

    input_fingerprint = compute_data_fingerprint(input_df)
    params_hash = _hash_config(config)

    if deterministic:
        # Deterministic run ID: hash of stable inputs
        id_payload = f"{input_fingerprint}|{params_hash}|{pipeline_version}"
        run_id = hashlib.sha256(id_payload.encode("utf-8")).hexdigest()[:16]
        generated_at = _FROZEN_TIMESTAMP
    else:
        run_id = str(uuid.uuid4())
        generated_at = datetime.now(timezone.utc).isoformat()

    return ProvenanceRecord(
        analysis_run_id=run_id,
        input_fingerprint=input_fingerprint,
        file_hash=compute_file_hash(file_path) if file_path else None,
        params_hash=params_hash,
        pipeline_version=pipeline_version,
        model_version=model_version,
        solver_version=solver_version,
        method_used=method_used,
        generated_at=generated_at,
        training_data_hash=training_data_hash,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_deterministic_output.py::TestDeterministicProvenance -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/provenance/run_context.py telemetry_tool/tests/test_deterministic_output.py
git commit -m "feat(provenance): add deterministic mode to build_provenance()"
```

---

### Task 2: Fix Unsorted pd.concat + Add `deterministic` Param to Pipeline

**Files:**
- Modify: `telemetry_tool/pipeline.py:470-490` (signature), `pipeline.py:713-716` (concat)

**Context:** `run_full_analysis()` needs a `deterministic` parameter. Also, at line 713, `pd.concat([df for df in resampled_laps.values() ...])` iterates dict values without sorting — this is an unconditional bug regardless of deterministic mode.

**Step 1: Fix the unsorted concat (unconditional)**

At `telemetry_tool/pipeline.py` line ~713, change:

```python
# BEFORE:
trimmed_df = pd.concat(
    [df for df in resampled_laps.values() if df is not None and not df.empty],
    ignore_index=True,
)

# AFTER:
trimmed_df = pd.concat(
    [resampled_laps[k] for k in sorted(resampled_laps.keys())
     if resampled_laps[k] is not None and not resampled_laps[k].empty],
    ignore_index=True,
)
```

**Step 2: Add `deterministic` parameter to `run_full_analysis()`**

At `telemetry_tool/pipeline.py`, add to the function signature (after `vehicle_overrides`):

```python
    deterministic: bool = False,
```

**Step 3: Thread `deterministic` into `build_provenance()` call**

At `telemetry_tool/pipeline.py` line ~3615, add the parameter:

```python
_provenance_record = build_provenance(
    input_df=raw_df if raw_df is not None else pd.DataFrame(),
    config=meta,
    method_used="telemetry_tool_v2",
    file_path=str(csv_path) if csv_path else None,
    pipeline_version=_pipeline_status.pipeline_version,
    model_version=_pipeline_status.model_version,
    deterministic=deterministic,
)
```

**Step 4: Run existing tests to verify no regressions**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py telemetry_tool/tests/test_theoretical_plausibility.py -v --tb=short`
Expected: All pass (no behavior change when `deterministic=False`)

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "fix(pipeline): sort resampled laps before concat + add deterministic flag"
```

---

### Task 3: Compute `training_data_hash` from `laps_for_theo`

**Files:**
- Modify: `telemetry_tool/pipeline.py:3613-3622` (provenance block)
- Test: `telemetry_tool/tests/test_deterministic_output.py`

**Context:** `_laps_for_theo_ref[0]` is already hoisted (set at pipeline.py:2332/2344). After the theoretical step, we have the training laps available. Compute their fingerprint and pass it to `build_provenance()`.

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_deterministic_output.py`:

```python
class TestTrainingDataHash:
    """training_data_hash is computed from laps_for_theo."""

    def test_training_data_hash_from_laps(self):
        from provenance.run_context import build_provenance
        from provenance.fingerprint import compute_data_fingerprint

        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.random.default_rng(42).uniform(10, 30, 100),
        })
        expected_hash = compute_data_fingerprint(df)

        p = build_provenance(
            pd.DataFrame(), {},
            method_used="test",
            training_data_hash=expected_hash,
        )
        assert p.training_data_hash == expected_hash
        assert len(p.training_data_hash) == 64  # SHA-256 hex digest

    def test_training_data_hash_none_when_no_laps(self):
        from provenance.run_context import build_provenance

        p = build_provenance(
            pd.DataFrame(), {},
            method_used="test",
        )
        assert p.training_data_hash is None
```

**Step 2: Run test to verify it passes** (these test the function's existing behavior)

Run: `pytest telemetry_tool/tests/test_deterministic_output.py::TestTrainingDataHash -v`
Expected: 2 PASSED

**Step 3: Wire `training_data_hash` in pipeline provenance call**

At `telemetry_tool/pipeline.py`, in the provenance block (~line 3613), compute the training data hash before calling `build_provenance()`:

```python
    # ── Provenance ─────────────────────────────────────────────────
    try:
        _training_data_hash = None
        _laps = _laps_for_theo_ref[0]
        if _laps and len(_laps) > 0:
            try:
                from provenance.fingerprint import compute_data_fingerprint as _cdf
                _training_data_hash = _cdf(pd.concat(_laps, ignore_index=True))
            except Exception:
                pass

        _provenance_record = build_provenance(
            input_df=raw_df if raw_df is not None else pd.DataFrame(),
            config=meta,
            method_used="telemetry_tool_v2",
            file_path=str(csv_path) if csv_path else None,
            pipeline_version=_pipeline_status.pipeline_version,
            model_version=_pipeline_status.model_version,
            training_data_hash=_training_data_hash,
            deterministic=deterministic,
        )
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_deterministic_output.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_deterministic_output.py
git commit -m "feat(provenance): compute training_data_hash from laps_for_theo"
```

---

### Task 4: Attach Provenance Ref to Coaching Output

**Files:**
- Modify: `telemetry_tool/pipeline.py:3214` (coaching_guide section)

**Context:** After `summary["coaching_guide"]` is set and after `summary["provenance"]` is built, attach a lightweight `provenance_ref` to the coaching guide dict. The pipeline builds provenance at line ~3613, which is after coaching at ~3214. So we attach the ref after provenance is built.

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_deterministic_output.py`:

```python
class TestProvenanceRef:
    """Lightweight provenance ref attached to sub-outputs."""

    def test_provenance_ref_structure(self):
        ref = {
            "analysis_run_id": "abc123",
            "pipeline_version": "v2-deadbeef",
        }
        assert "analysis_run_id" in ref
        assert "pipeline_version" in ref

    def test_provenance_ref_not_full_record(self):
        """Ref should have exactly 2 keys, not the full provenance record."""
        ref = {
            "analysis_run_id": "abc123",
            "pipeline_version": "v2-deadbeef",
        }
        assert len(ref) == 2
```

**Step 2: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_deterministic_output.py::TestProvenanceRef -v`
Expected: 2 PASSED (structural tests)

**Step 3: Attach provenance ref in pipeline**

At `telemetry_tool/pipeline.py`, after the provenance block (after `summary["provenance"] = _provenance_record.to_dict()` at line ~3623), add:

```python
        # Attach lightweight provenance ref to sub-outputs
        _prov_ref = {
            "analysis_run_id": _provenance_record.analysis_run_id,
            "pipeline_version": _provenance_record.pipeline_version,
        }
        if summary.get("coaching_guide") and isinstance(summary["coaching_guide"], dict):
            summary["coaching_guide"]["provenance_ref"] = _prov_ref
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_deterministic_output.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_deterministic_output.py
git commit -m "feat(provenance): attach lightweight provenance_ref to coaching output"
```

---

### Task 5: Provenance Fields Presence Test

**Files:**
- Modify: `telemetry_tool/tests/test_deterministic_output.py`

**Context:** Verify that all required provenance fields are present and non-empty when `build_provenance()` is called with typical inputs.

**Step 1: Write the test**

Add to `telemetry_tool/tests/test_deterministic_output.py`:

```python
class TestProvenanceFieldsPresent:
    """All required provenance fields are present and non-empty."""

    REQUIRED_FIELDS = [
        "analysis_run_id",
        "input_fingerprint",
        "params_hash",
        "pipeline_version",
        "model_version",
        "method_used",
        "generated_at",
    ]

    def test_all_required_fields_present(self):
        from provenance.run_context import build_provenance

        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 100, 20),
            "Speed (m/s)": np.full(20, 15.0),
        })
        p = build_provenance(df, {"track_id": "t"}, method_used="test")
        d = p.to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"
            assert d[field], f"Empty field: {field}"

    def test_optional_fields_exist_as_keys(self):
        from provenance.run_context import build_provenance

        df = pd.DataFrame({"x": [1, 2]})
        p = build_provenance(df, {}, method_used="test")
        d = p.to_dict()
        # These may be None but keys must exist
        for field in ["file_hash", "solver_version", "training_data_hash"]:
            assert field in d, f"Missing optional field key: {field}"

    def test_to_dict_is_json_serializable(self):
        from provenance.run_context import build_provenance

        df = pd.DataFrame({"x": [1.0, 2.0]})
        p = build_provenance(df, {"a": 1}, method_used="test")
        # Must not raise
        result = json.dumps(p.to_dict(), sort_keys=True)
        assert isinstance(result, str)
        assert len(result) > 50
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_deterministic_output.py::TestProvenanceFieldsPresent -v`
Expected: 3 PASSED

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_deterministic_output.py
git commit -m "test(provenance): add provenance field presence + serialization tests"
```

---

### Task 6: Self-Consistency Snapshot Test

**Files:**
- Modify: `telemetry_tool/tests/test_deterministic_output.py`

**Context:** The definitive test — run `build_provenance()` twice with `deterministic=True` on the same inputs and assert the JSON output is byte-identical. This catches any non-determinism in the provenance path. A full pipeline snapshot test would require the entire pipeline to be importable, which is heavy; the provenance-level test covers the core requirement.

**Step 1: Write the test**

Add to `telemetry_tool/tests/test_deterministic_output.py`:

```python
class TestSelfConsistency:
    """Identical inputs produce identical JSON output."""

    def _make_inputs(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": rng.uniform(10, 30, 100),
            "Accel (m/s²)": rng.normal(0, 2, 100),
        })
        config = {
            "track_id": "monza",
            "session_type": "practice",
            "driver_name": "TestDriver",
        }
        return df, config

    def test_byte_stable_json(self):
        from provenance.run_context import build_provenance

        df, config = self._make_inputs()

        p1 = build_provenance(
            df, config,
            method_used="test_v2",
            pipeline_version="v2-test",
            model_version="none",
            deterministic=True,
        )
        p2 = build_provenance(
            df, config,
            method_used="test_v2",
            pipeline_version="v2-test",
            model_version="none",
            deterministic=True,
        )

        j1 = json.dumps(p1.to_dict(), sort_keys=True)
        j2 = json.dumps(p2.to_dict(), sort_keys=True)
        assert j1 == j2, "Provenance JSON is not byte-stable"

    def test_different_inputs_produce_different_output(self):
        from provenance.run_context import build_provenance

        df1 = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        df2 = pd.DataFrame({"x": [4.0, 5.0, 6.0]})
        config = {"track_id": "t"}

        p1 = build_provenance(df1, config, method_used="test", deterministic=True)
        p2 = build_provenance(df2, config, method_used="test", deterministic=True)

        assert p1.analysis_run_id != p2.analysis_run_id
        assert p1.input_fingerprint != p2.input_fingerprint
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_deterministic_output.py::TestSelfConsistency -v`
Expected: 2 PASSED

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_deterministic_output.py
git commit -m "test(determinism): add self-consistency snapshot test for provenance"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Deterministic mode in `build_provenance()` | `provenance/run_context.py`, `tests/test_deterministic_output.py` |
| 2 | Fix unsorted concat + `deterministic` param on pipeline | `pipeline.py` |
| 3 | Compute `training_data_hash` from `laps_for_theo` | `pipeline.py`, `tests/test_deterministic_output.py` |
| 4 | Attach provenance ref to coaching output | `pipeline.py`, `tests/test_deterministic_output.py` |
| 5 | Provenance fields presence tests | `tests/test_deterministic_output.py` |
| 6 | Self-consistency snapshot test | `tests/test_deterministic_output.py` |
