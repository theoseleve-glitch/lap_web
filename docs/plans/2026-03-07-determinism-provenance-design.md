# Determinism & Provenance Design

**Date**: 2026-03-07
**Status**: Approved
**Scope**: Both pipelines (`telemetry_tool` 14-stage, `kart_envelope` 18-step)

## Problem

Analysis outputs must be deterministic for identical inputs, and every persisted analysis must carry provenance fields for reproducibility and traceability.

## Audit Findings

Determinism is already ~90% solved:
- All sklearn models use `random_state=42` globally (`ml_engine.py`, `anomaly_detection.py`)
- Sorting uses stable algorithms throughout (`argsort(kind="stable")`, `sorted()`)
- No sklearn clustering used anywhere
- Percentile/median operations are deterministic

Remaining gaps:
- No `analysis_run_id`, `input_fingerprint`, `params_hash` on outputs
- No provenance endpoint for debugging
- Float serialization not canonicalized for snapshot comparison
- NaN/Inf handling inconsistent across JSON paths

## Approach: Full Provenance Layer (Approach 2)

### 1. Provenance Module (`telemetry_tool/provenance/`)

```
telemetry_tool/provenance/
├── __init__.py          # exports build_provenance(), ProvenanceRecord
├── fingerprint.py       # file_hash + data_fingerprint
├── run_context.py       # analysis_run_id, params_hash, versions, generated_at
└── canonical.py         # float normalization, canonical JSON, hash computation
```

**`fingerprint.py`**:
- `compute_file_hash(path) -> str` — SHA-256, reuses `ingest/checksum.py` when available
- `compute_data_fingerprint(df) -> str` — SHA-256 of sorted column names + shape + first 8 bytes per column as float64

**`run_context.py`**:
- `build_provenance(input_df, config, file_path=None) -> ProvenanceRecord`

```python
@dataclass
class ProvenanceRecord:
    analysis_run_id: str      # uuid4
    input_fingerprint: str    # from compute_data_fingerprint()
    file_hash: str | None     # from compute_file_hash() if path available
    params_hash: str          # SHA-256 of JSON-serialized config/params
    pipeline_version: str     # from pipeline_status.compute_pipeline_version_string()
    model_version: str        # from ml_engine or kart_envelope config
    solver_version: str | None
    method_used: str          # "telemetry_tool_v2" or "kart_envelope_v2.2"
    generated_at: str         # ISO 8601 UTC
    training_data_hash: str | None
```

**`canonical.py`**:
- `canonicalize(obj, float_precision=6) -> str` — Round floats, normalize NaN/Inf to sentinels, sort keys
- `canonical_hash(obj) -> str` — SHA-256 of canonicalize output

**Integration**: Call `build_provenance()` at top of `run_full_analysis()` and `analyze_session()`. Inject `summary["provenance"] = record.to_dict()`.

### 2. Database — Migration 017

```sql
CREATE TABLE analysis_provenance (
    id              SERIAL PRIMARY KEY,
    analysis_run_id UUID NOT NULL UNIQUE,
    session_id      INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    workspace_id    INTEGER,
    input_fingerprint TEXT NOT NULL,
    file_hash       TEXT,
    params_hash     TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    solver_version  TEXT,
    method_used     TEXT NOT NULL,
    training_data_hash TEXT,
    generated_at    TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_provenance_session ON analysis_provenance(session_id);
CREATE INDEX idx_provenance_fingerprint ON analysis_provenance(input_fingerprint);
CREATE INDEX idx_provenance_pipeline_ver ON analysis_provenance(pipeline_version);
```

RLS policy: `workspace_id = current_setting('app.workspace_id')::INTEGER`.

**Dual-write**: Summary dict is source of truth. Table is denormalized query index. PG-only write (SQLite/desktop skips table, provenance lives in `results_json`).

### 3. API Endpoint

`GET /api/v1/sessions/<session_id>/provenance` in `data_v2.py`.

Read path: query table first, fall back to extracting from `results_json` for pre-migration sessions. Protected by auth + `require_permission("session:read")` + RLS.

### 4. Determinism Hardening

- `canonical.py` normalizes floats to 6dp before JSON serialization
- NaN → `"__NaN__"`, Inf → `"__Inf__"` for hashing (API responses unchanged)
- Dict ordering made explicit via `sort_keys=True` in canonical form

No changes needed for: random seeds (fixed), sorting (stable), median/percentile (deterministic), clustering (not used).

### 5. Snapshot Regression Tests

**Shared harness**: `tests/snapshot_harness.py`
- `assert_snapshot_match(result, name, rtol=1e-6)` — Hash-first comparison, semantic diff fallback
- Snapshots stored in `tests/snapshots/{telemetry_tool,kart_envelope}/` as `.json` + `.hash`
- `pytest --update-snapshots` flag for intentional updates

**Test cases** (`test_determinism.py` in each package):

| Test | Asserts |
|------|---------|
| `test_full_analysis_deterministic` | Two runs on same input produce identical canonical hashes |
| `test_corners_snapshot` | Corner detection output matches stored baseline |
| `test_theoretical_snapshot` | Theoretical lap output matches stored baseline |
| `test_coaching_snapshot` (kart) | Coaching + corner_coaching matches baseline |
| `test_delta_map_snapshot` (kart) | Delta map matches baseline |
| `test_provenance_fields_present` | All provenance fields exist with correct types |
| `test_provenance_version_change` | Pipeline version change → pipeline_version field changes |
| `test_provenance_input_change` | Modified input → input_fingerprint changes, params_hash unchanged |
| `test_provenance_params_change` | Config change → params_hash changes, input_fingerprint unchanged |

**Fixtures**: Existing `seeded_db` + synthetic CSV (telemetry_tool), `synthetic_oval_laps` (kart_envelope).

## Input Fingerprint Strategy

Dual hash:
- `file_hash`: SHA-256 of raw CSV bytes (reuse `ingest/checksum.py`)
- `data_fingerprint`: SHA-256 of sorted column names + shape + first 8 bytes per column as float64

The file hash is cheap; the data fingerprint answers "same numeric data?" even with formatting differences.

## Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/provenance/__init__.py` | New — exports |
| `telemetry_tool/provenance/fingerprint.py` | New — hash computation |
| `telemetry_tool/provenance/run_context.py` | New — ProvenanceRecord + build_provenance() |
| `telemetry_tool/provenance/canonical.py` | New — canonicalization + hash |
| `telemetry_tool/pipeline.py` | Modified — call build_provenance(), inject into summary |
| `kart_envelope/pipeline.py` | Modified — call build_provenance(), inject into summary |
| `telemetry_tool/web/routes/data_v2.py` | Modified — add provenance endpoint |
| `alembic/versions/017_analysis_provenance.py` | New — migration |
| `tests/snapshot_harness.py` | New — shared test harness |
| `telemetry_tool/tests/test_determinism.py` | New — snapshot + determinism tests |
| `kart_envelope/tests/test_determinism.py` | New — snapshot + determinism tests |
| `tests/snapshots/` | New — stored baselines |
| `tests/conftest.py` | Modified — add `--update-snapshots` flag |
