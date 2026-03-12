# OCP Downstream Chain + Corner Re-selection Design

## Goal

When the CasADi/IPOPT OCP solver completes asynchronously, ALL downstream consumers (corner analysis, coaching text, scoring, corner progression) must reflect OCP results. Additionally, users must be able to re-select corners on completed sessions and have the full analysis chain (including OCP) re-run.

## Background

The OCP solver runs as a Celery task after the synchronous pipeline completes. Currently `_update_downstream()` in `tasks/ocp_tasks.py` only re-scores and updates corner speed targets via interpolation. It does NOT re-run:

- `run_corner_analysis()` — time losses, grip utilisation, speed deltas per corner
- `run_coaching_analyzers()` — trail braking, exit cascades, traction budget, symptoms
- `run_enhanced_coaching()` — coaching text generation
- `persist_coaching_v3()` — corner progression DB records

Corner re-selection is only possible during the initial pipeline flow (`awaiting_corner_selection` status). Once a job completes, users cannot change corners.

## Part A: Full OCP Downstream Chain

### Location

`telemetry_tool/tasks/ocp_tasks.py` — `_update_downstream()` function.

### Data Flow

```
OCP TheoreticalResult (from solve_ocp)
  |
  v
_ocp_result_to_dataframe()
  -> pd.DataFrame with columns: distance_m, speed_mps, time_s, a_long, a_lat
  |
  v
run_corner_analysis(corners, best_lap_df, theoretical_lap, friction_model, resampled_laps)
  -> list[dict] corner_perfs with time_loss_s, grip utilisation, speed deltas
  |
  v
run_coaching_analyzers(corner_perfs, best_lap_df, theoretical_result_dict, friction_model, resampled_laps, available_columns)
  -> dict with trail_brakes, exit_cascades, traction_budgets, symptoms, throttle_lifts, weight_transfers
  |
  v
score_session(observed_metrics, ocp_theoretical_metrics)
  -> dict with total_score, grade, sub_scores, strengths, weaknesses
  |
  v
run_enhanced_coaching(corner_perfs, coaching_v2, scores, lap_metrics, driving_style, analyzer_bundle, driver_history)
  -> dict coaching_v3 output
  |
  v
Persist to DB:
  - analysis_json: score_result, coaching_v3, corner_coaching, theoretical_metrics, simulation_method
  - score_details table (INSERT OR REPLACE)
  - sessions.total_score, sessions.grade columns
  - corner_progression table (via persist_coaching_v3, PG only)
```

### Reconstructing Dependencies from analysis_json

The OCP task runs outside the pipeline context, so it must reconstruct the data structures that downstream functions expect:

| Dependency | Source in analysis_json | Reconstruction |
|---|---|---|
| `best_lap_df` | `speed_trace_best` (list of dicts) | `pd.DataFrame(speed_trace_best)` with column rename |
| `corners` | `corners` (list of dicts) | Used directly |
| `friction_model` | `friction_model` (dict or None) | Used directly, defaults to `{"max_lateral_g": 1.2}` |
| `resampled_laps` | Not stored (too large) | Pass `{0: best_lap_df}` as single-lap dict — corner analysis primarily uses the best lap |
| `theoretical_result` (dict) | Built from OCP result | `{"speed_profile": [...], "track_length_m": max(distance_m)}` |
| `observed_metrics` | `lap_times`, `speed_trace_best`, existing `score_result` | Extract `best_s`, `n_laps`, `cv_pct`, speed/accel metrics |
| `coaching_v2` | `coaching` or `coaching_v2` | Used as fallback input to `run_enhanced_coaching` |
| `driving_style` | `driving_style` | Used directly |

### Graceful Degradation

Each step is wrapped in try/except. If any step fails:
- The raw OCP result in `analysis_json["theoretical_ocp"]` is always preserved (stored by `_store_ocp_result` before downstream runs)
- Scoring update is attempted independently of coaching update
- A warning is logged with the specific step that failed
- The session remains usable with whatever data was successfully stored

### Scoring: "ocp" as Physics Method

In `scoring/pace.py`, the `is_physics` check includes `"ocp"`:

```python
is_physics = simulation_method in (
    "physics", "hybrid", "ocp",
    "kart_envelope_qss", "kart_envelope_casadi",
)
```

This ensures OCP results use the tighter blended percentage+absolute gap scoring thresholds rather than the lenient envelope thresholds.

## Part B: Corner Re-selection on Completed Sessions

### Endpoint Change

`POST /jobs/<job_id>/resume` in `web/routes/jobs.py`.

**Current:** Accepts status `("paused", "awaiting_corner_selection")`.
**New:** Also accepts `"completed"`.

### PipelineContext Reconstruction

After completion, `ctx.cleanup()` deletes the Redis key and temp directory. When a completed job is resumed:

1. `_load_pipeline_context(redis, job_id)` returns `None`
2. New helper `_reconstruct_context_from_db(conn, job_id, redis_client)` is called:
   - Loads job row from `ingestion_jobs` to get `workspace_id`, `session_id`
   - Loads session row to get `source_path` (original CSV)
   - Checks CSV file exists on disk
   - Creates a fresh `PipelineContext` with those values
   - Returns it (or `None` if data is missing)

### Full Re-run Fallback

`_run_finalize_stages()` already handles missing intermediate state:

```python
if resampled_laps:
    # Resume path with intermediate state
    ...
else:
    # Fallback: full re-run from CSV
    result = run_full_analysis(csv_path=ctx.file_path, ...)
```

No changes needed in `pipeline_tasks.py`. The full pipeline re-run will:
- Re-detect corners (or use the custom/selected corners from the context)
- Re-run theoretical (QSS/hybrid)
- Re-run scoring + coaching
- Persist everything
- Queue OCP (which then runs the full downstream chain from Part A)

### Edge Cases

| Case | Handling |
|---|---|
| Redis context expired | Reconstruct from DB |
| CSV file deleted | Return 409: "Original session file no longer available. Please re-upload." |
| Job not found in DB | Return 404 |
| Job status not resumable | Return 409 (existing behavior) |
| OCP dependencies not installed | OCP queue silently skips (existing behavior via `_is_ocp_enabled()`) |

### Flow

```
User: POST /jobs/<id>/resume {corners: [{s_start, s_apex, s_end}, ...]}
  |
  v
Status check: "completed" now allowed
  |
  v
Load PipelineContext from Redis
  -> Found? Use it
  -> Missing? _reconstruct_context_from_db()
     -> CSV exists? Create fresh context
     -> CSV missing? 409 error
  |
  v
Set corners on context (custom_corners or selected_corner_ids)
Save context to Redis
Update job status -> "processing"
  |
  v
Dispatch pipeline_finalize Celery task
  -> _run_finalize_stages() detects missing intermediate state
  -> Falls back to full run_full_analysis() from CSV
  -> New corners applied (custom or filtered)
  -> All stages 8-14 re-run
  -> Results persisted to DB
  -> OCP queued
  |
  v
OCP Celery task runs
  -> solve_ocp()
  -> _store_ocp_result()
  -> _update_downstream() [Part A]
     -> Full corner analysis + coaching + scoring with OCP data
     -> All DB tables updated
```

## Files Modified

| File | Change |
|---|---|
| `tasks/ocp_tasks.py` | Replace partial `_update_downstream()` with full chain |
| `scoring/pace.py` | Add `"ocp"` to `is_physics` (already done) |
| `web/routes/jobs.py` | Add `"completed"` to resume status guard; add `_reconstruct_context_from_db()` |

## Testing Strategy

### Unit tests (new file: `tests/test_ocp_downstream.py`)

1. `_ocp_result_to_dataframe()` produces correct columns and cumulative time
2. `_extract_observed_metrics()` handles missing/partial analysis_json
3. `_update_downstream()` with mocked DB and mocked pipeline functions — verify all downstream functions are called with correct arguments
4. `_update_downstream()` graceful degradation — verify partial failure doesn't lose OCP data
5. `_reconstruct_context_from_db()` with valid data returns context
6. `_reconstruct_context_from_db()` with missing CSV returns None

### Integration test (extend existing `test_corner_picker_changes.py`)

7. Resume a completed job with new corners — verify pipeline_finalize is dispatched
8. Resume with missing CSV — verify 409 response

## Out of Scope

- Frontend changes to expose a "re-select corners" UI on completed sessions
- Re-selection of corners without re-running the full pipeline (lightweight path)
- OCP warm-starting from previous OCP result on re-analysis
