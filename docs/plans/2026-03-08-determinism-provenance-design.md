# Deterministic Outputs + Provenance Completeness — Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` pipeline determinism and output traceability

## Problem

1. **Non-determinism**: Identical CSV inputs can produce different analysis JSON due to UUIDs, timestamps, and unsorted dict iteration. This breaks reproducibility, diff-based testing, and caching.
2. **Provenance gaps**: The provenance system exists (`ProvenanceRecord`, `analysis_provenance` table, `/provenance` endpoint) but `training_data_hash` is always None, and lightweight provenance refs are missing from coaching and practice plan sub-outputs.

## Feature 1: Deterministic Analysis Outputs

### Non-Determinism Sources (Audit)

| # | Source | File:Line | Severity | Fix |
|---|--------|-----------|----------|-----|
| 1 | `uuid.uuid4()` in provenance | `provenance/run_context.py:75` | CRITICAL | Deterministic hash of `input_fingerprint + params_hash + pipeline_version` |
| 2 | `datetime.now()` in provenance | `provenance/run_context.py:77` | CRITICAL | Accept optional `generated_at` param; freeze in deterministic mode |
| 3 | `datetime.now()` in SessionContext | `session_context.py:264` | HIGH | Accept optional timestamp param |
| 4 | Unsorted `dict.values()` in pd.concat | `pipeline.py:714` | HIGH | Sort by key before concat (unconditional fix) |

### Deterministic Mode Flag

Add `deterministic: bool = False` parameter to `run_full_analysis()` in `pipeline.py`. When True:
- `build_provenance()` generates `analysis_run_id` as `sha256(input_fingerprint + params_hash + pipeline_version)[:16]` instead of UUID
- `generated_at` is set to `"2000-01-01T00:00:00+00:00"` (canonical frozen value)
- SessionContext uses frozen timestamp

Default is `False` — production behavior unchanged.

### Unconditional Fix

`pipeline.py:714` — Sort resampled_laps by key before concat:
```python
trimmed_df = pd.concat(
    [resampled_laps[k] for k in sorted(resampled_laps.keys())
     if resampled_laps[k] is not None and not resampled_laps[k].empty],
    ignore_index=True,
)
```

## Feature 2: Provenance Completeness

### Already Exists (No Work Needed)

- `ProvenanceRecord` dataclass: `analysis_run_id`, `input_fingerprint`, `file_hash`, `params_hash`, `pipeline_version`, `model_version`, `solver_version`, `method_used`, `training_data_hash`, `generated_at`
- `analysis_provenance` DB table with `insert_provenance()` + `get_provenance_by_session()`
- `GET /api/v1/sessions/<id>/provenance` endpoint
- `compute_file_hash()`, `compute_data_fingerprint()`, `_hash_config()`
- Pipeline writes `summary["provenance"]` at end

### Gaps to Fill

| Gap | Fix |
|-----|-----|
| `training_data_hash` always None | After `laps_for_theo` assembled, compute `compute_data_fingerprint(pd.concat(laps_for_theo))` and pass to `build_provenance()` |
| No provenance ref in coaching_v2 | Attach `{"analysis_run_id": ..., "pipeline_version": ...}` to `summary["coaching_v2"]` |
| No provenance ref in practice plan | Same lightweight ref in `summary["practice_plan"]` |

### Lightweight Provenance Reference

Rather than duplicating the full record, sub-outputs get:
```python
{
    "provenance_ref": {
        "analysis_run_id": "abc123...",
        "pipeline_version": "v2-a3f8b2c1"
    }
}
```

The full record lives in `summary["provenance"]` and the `analysis_provenance` table.

## Feature 3: Snapshot Regression Tests

### Strategy

Create a minimal synthetic CSV (50 rows, 3 laps, known GPS/speed/accel values) that exercises the full pipeline. Run twice with `deterministic=True`, compare JSON outputs.

### What to Snapshot

- `theoretical_metrics` (envelope speeds, lap time)
- `corner_performances` (corner IDs, time losses, events)
- `score_result` (total score, sub-scores)
- `delta_segments` (cause classifications)

### What to Exclude

- `provenance.generated_at` (only in non-deterministic mode)
- `pipeline.steps[*].duration_ms` (wall-clock timing)
- `output_dir` (filesystem path)

### Test Structure

```python
class TestDeterministicOutput:
    def test_identical_inputs_produce_identical_outputs(self):
        csv = _build_synthetic_csv()
        summary_1 = run_pipeline(csv, deterministic=True)
        summary_2 = run_pipeline(csv, deterministic=True)
        _strip_volatile_fields(summary_1)
        _strip_volatile_fields(summary_2)
        assert json.dumps(summary_1, sort_keys=True) == json.dumps(summary_2, sort_keys=True)

    def test_provenance_fields_present(self):
        csv = _build_synthetic_csv()
        summary = run_pipeline(csv)
        prov = summary["provenance"]
        for field in REQUIRED_PROVENANCE_FIELDS:
            assert prov.get(field), f"Missing: {field}"

    def test_training_data_hash_populated(self):
        csv = _build_synthetic_csv()  # must have >= 4 laps
        summary = run_pipeline(csv)
        prov = summary["provenance"]
        assert prov.get("training_data_hash") is not None
```

## Files Touched

| File | Changes |
|------|---------|
| `provenance/run_context.py` | Accept `deterministic` flag, generate deterministic run_id + frozen timestamp |
| `session_context.py` | Accept optional `created_at` timestamp |
| `pipeline.py` | Add `deterministic` param, fix sorted concat, pass `training_data_hash`, attach provenance refs to coaching/practice plan |
| `tests/test_deterministic_output.py` | 3 tests: self-consistency, provenance fields, training_data_hash |

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| `deterministic=False` (default) | No behavior change from current production |
| No laps_for_theo | `training_data_hash` remains None |
| coaching_v2 / practice_plan not computed | No provenance_ref attached (no crash) |
