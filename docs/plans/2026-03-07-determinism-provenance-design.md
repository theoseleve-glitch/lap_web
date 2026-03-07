# Determinism & Provenance Design

**Date**: 2026-03-07
**Status**: Approved
**Scope**: Both pipelines (`telemetry_tool` 14-stage + `kart_envelope` 18-step)

## Problem

Analysis outputs must be deterministic for identical inputs, and every persisted analysis must carry robust provenance fields for reproducibility and traceability.

## Audit Findings

Determinism is already ~90% solved:
- All sklearn models use `random_state=42` globally (`ml_engine.py`, `anomaly_detection.py`)
- Sorting uses stable algorithms (`argsort(kind="stable")`) throughout
- No sklearn clustering used anywhere
- Percentile/median operations are deterministic

Remaining gaps:
- No provenance fields (`analysis_run_id`, `input_fingerprint`, `params_hash`)
- Float serialization not normalized for snapshot comparison
- No regression tests proving determinism

## Approach: Full Provenance Layer (Approach 2)

Shared `telemetry_tool/provenance/` package, Alembic migration 017, provenance API endpoint, shared snapshot test harness.

## Section 1: Provenance Module

### Package Structure

```
telemetry_tool/provenance/
    __init__.py          # exports build_provenance(), ProvenanceRecord
    fingerprint.py       # file_hash (SHA-256) + data_fingerprint (canonical channel hash)
    run_context.py       # analysis_run_id, params_hash, version fields, generated_at
    canonical.py         # float normalization, canonical JSON serializer, hash computation
```

### fingerprint.py

- `compute_file_hash(path) -> str` — Reuses `ingest/checksum.py` SHA-256. Desktop mode computes fresh.
- `compute_data_fingerprint(df) -> str` — SHA-256 of: sorted column names + shape tuple + first 8 bytes of each column cast to float64. Fast even for 10GB files.

### run_context.py

`build_provenance(input_df, config, file_path=None) -> ProvenanceRecord`:

```python
@dataclass
class ProvenanceRecord:
    analysis_run_id: str        # uuid4
    input_fingerprint: str      # from compute_data_fingerprint()
    file_hash: str | None       # from compute_file_hash() if path available
    params_hash: str            # SHA-256 of JSON-serialized config/params
    pipeline_version: str       # from pipeline_status.compute_pipeline_version_string()
    model_version: str          # from ml_engine or kart_envelope config
    solver_version: str | None  # kart_envelope solver backend, None for telemetry_tool
    method_used: str            # "telemetry_tool_v2" or "kart_envelope_v2.2"
    generated_at: str           # ISO 8601 UTC timestamp
    training_data_hash: str | None  # hash of ML model training set, if applicable
```

### canonical.py

- `canonicalize(obj, float_precision=6) -> str` — Recursively walks dicts/lists, rounds floats to N decimals, normalizes NaN to `"__NaN__"`, Inf to `"__Inf__"`, sorts dict keys, returns deterministic JSON string.
- `canonical_hash(obj) -> str` — SHA-256 of canonicalize output.

### Integration

- `telemetry_tool/pipeline.py`: Call `build_provenance()` at top of `run_full_analysis()` (after CSV read, before stage 1). Inject `summary["provenance"] = record.to_dict()`.
- `kart_envelope/pipeline.py`: Same pattern at top of `analyze_session()`.

## Section 2: Database — Migration 017

### Table: `analysis_provenance`

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

### RLS

```sql
ALTER TABLE analysis_provenance ENABLE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON analysis_provenance
    USING (workspace_id = current_setting('app.workspace_id')::INTEGER);
```

### Write Path

- PG mode: `insert_provenance(conn, record)` writes to table + summary JSON.
- SQLite/desktop: Table write skipped. Provenance lives only in `results_json`.

### Consistency

Summary dict is source of truth. Table is denormalized query index. Provenance endpoint reads table first, falls back to extracting from `results_json`.

## Section 3: API Endpoint + Determinism Hardening

### Endpoint

`GET /api/v1/sessions/<session_id>/provenance` in `data_v2.py`.

Response envelope:
```json
{
  "ok": true,
  "data": {
    "analysis_run_id": "550e8400-e29b-41d4-a716-446655440000",
    "input_fingerprint": "a3f8b2c1e9...",
    "file_hash": "7f83b1657ff1fc53...",
    "params_hash": "d4e5f6a7b8...",
    "pipeline_version": "v2-a3f8b2c1",
    "model_version": "2024-06-15_v3.1",
    "solver_version": null,
    "method_used": "telemetry_tool_v2",
    "training_data_hash": null,
    "generated_at": "2026-03-07T14:30:00Z"
  }
}
```

Read path: table lookup by session_id, fallback to `results_json` extraction. Protected by auth + RBAC (`session:read`).

### Determinism Hardening

1. **Float serialization**: `canonical.py` normalizes floats to 6dp for hashing/snapshots.
2. **Dict ordering**: `sort_keys=True` in canonical serialization.
3. **NaN/Inf**: Normalized to string sentinels for hashing. API responses keep numeric NaN.

No changes needed for random seeds, sorting, median, or clustering (already deterministic).

## Section 4: Snapshot Regression Test Harness

### Harness: `tests/snapshot_harness.py`

```python
def assert_snapshot_match(result: dict, snapshot_name: str, rtol: float = 1e-6) -> None
def update_snapshot(result: dict, snapshot_name: str) -> None
def canonical_hash(result: dict) -> str
```

Workflow:
1. Canonical hash for fast pass/fail.
2. First run stores snapshot JSON + hash in `tests/snapshots/`.
3. Subsequent runs compare hash. On mismatch, semantic deep comparison with `rtol=1e-6` produces human-readable diff.
4. `pytest --update-snapshots` to regenerate after intentional changes.

### Snapshot Storage

```
tests/snapshots/
    telemetry_tool/
        full_analysis_oval.json + .hash
        corners_oval.json + .hash
        theoretical_oval.json + .hash
    kart_envelope/
        full_analysis_synthetic.json + .hash
        coaching_synthetic.json + .hash
        delta_map_synthetic.json + .hash
```

### Test Cases

**telemetry_tool/tests/test_determinism.py:**
- `test_full_analysis_deterministic` — Run twice, assert canonical hashes match
- `test_corners_snapshot` — Corners output against stored baseline
- `test_theoretical_snapshot` — Theoretical lap + metrics
- `test_provenance_fields_present` — All fields exist with correct types

**kart_envelope/tests/test_determinism.py:**
- `test_full_analysis_deterministic` — Run twice on `synthetic_oval_laps`, assert match
- `test_coaching_snapshot` — Coaching + corner coaching
- `test_delta_map_snapshot` — Delta map output
- `test_provenance_fields_present` — Field validation

### Provenance-Specific Tests

- `test_provenance_version_change` — Monkey-patch `PIPELINE_VERSION`, assert field changed
- `test_provenance_input_change` — Modify input cell, assert `input_fingerprint` changed, `params_hash` unchanged
- `test_provenance_params_change` — Change config param, assert `params_hash` changed, `input_fingerprint` unchanged

### Fixtures

- telemetry_tool: `seeded_db` + synthetic CSV (reuse `test_streaming_ingest.py` pattern)
- kart_envelope: `synthetic_oval_laps` from conftest (seeded `np.random.seed(42)`)

## Files Changed

| File | Change |
|------|--------|
| `telemetry_tool/provenance/__init__.py` | New — exports |
| `telemetry_tool/provenance/fingerprint.py` | New — hash functions |
| `telemetry_tool/provenance/run_context.py` | New — ProvenanceRecord + build_provenance() |
| `telemetry_tool/provenance/canonical.py` | New — canonicalization + hashing |
| `telemetry_tool/pipeline.py` | Edit — call build_provenance(), inject into summary |
| `kart_envelope/pipeline.py` | Edit — call build_provenance(), inject into summary |
| `alembic/versions/017_analysis_provenance.py` | New — migration |
| `telemetry_tool/web/routes/data_v2.py` | Edit — add provenance endpoint |
| `tests/snapshot_harness.py` | New — shared test harness |
| `telemetry_tool/tests/test_determinism.py` | New — snapshot + determinism tests |
| `kart_envelope/tests/test_determinism.py` | New — snapshot + determinism tests |
| `tests/snapshots/` | New — snapshot JSON + hash files |
| `telemetry_tool/tests/conftest.py` | Edit — add `--update-snapshots` flag |

## Acceptance Criteria

1. Running analysis twice on identical input yields identical canonical hashes.
2. All provenance fields present in both pipeline outputs.
3. `GET /api/v1/sessions/<id>/provenance` returns correct data.
4. Snapshot tests pass for corners, theoretical, deltas, coaching.
5. Provenance fields change only when expected (version/input/params change tests).
