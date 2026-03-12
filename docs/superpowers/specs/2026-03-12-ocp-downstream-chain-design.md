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

Two distinct data shapes are built from the OCP result:

- **`theo_df`** (DataFrame) — columns `distance_m`, `speed_mps`, `time_s`, `a_long`, `a_lat`. Used by `run_corner_analysis()` as the `theoretical_lap` parameter.
- **`theoretical_result_dict`** (dict) — shape `{"speed_profile": [{"distance_m": ..., "speed_mps": ...}, ...], "track_length_m": float}`. Used by `run_coaching_analyzers()` for exit cascade analysis.

```
OCP TheoreticalResult (from solve_ocp)
  |
  +---> _ocp_result_to_dataframe() -> theo_df (pd.DataFrame)
  |
  +---> _build_theoretical_result_dict() -> theoretical_result_dict (dict)
  |
  v
run_corner_analysis(
    corners,            # list[dict] from analysis_json["corners"]
    best_lap_df,        # pd.DataFrame from analysis_json["speed_trace_best"]
    theo_df,            # DataFrame (NOT dict)
    friction_model,     # dict from analysis_json, default {"max_lateral_g": 1.2}
    resampled_laps,     # {0: best_lap_df} — see Known Limitations
    excluded_laps=frozenset(),  # not available in OCP context, defaults to empty
)
  -> list[dict] corner_perfs with time_loss_s, grip utilisation, speed deltas
  |
  v
run_coaching_analyzers(
    corner_perfs,
    best_lap_df,
    theoretical_result_dict,    # dict with speed_profile + track_length_m
    friction_model,
    resampled_laps,
    available_columns,          # set from best_lap_df.columns
)
  -> dict with trail_brakes, exit_cascades, traction_budgets, symptoms, throttle_lifts, weight_transfers
  |
  v
score_session(observed_metrics, ocp_theoretical_metrics)
  -> dict with total_score, grade, sub_scores, strengths, weaknesses
  |
  v
run_enhanced_coaching(
    corner_perfs, coaching_v2, scores, lap_metrics, driving_style,
    analyzer_bundle, driver_history,
    vehicle_class=analysis_json.get("vehicle_class", "car"),
)
  -> dict coaching_v3 output
  |
  v
Persist to DB:
  - analysis_json: score_result, coaching_v3, corner_coaching, theoretical_metrics, simulation_method
  - score_details table (INSERT OR REPLACE)
  - sessions.total_score, sessions.grade columns
  - corner_progression table (via persist_coaching_v3, PG only)
```

### RLS / Workspace Context

The OCP task gets its connection from `_load_session_data()` -> `get_db_connection()`. When `USE_PG=1`, `SET LOCAL` for RLS context must be set before any writes. The `_update_downstream()` function must call `set_workspace_context(conn, workspace_id)` before the persist phase. The `workspace_id` is passed through from the original task dispatch.

Multiple `conn.commit()` calls reset `SET LOCAL`. To avoid this, the persist phase should batch all writes into a single transaction:

```python
# Set RLS context once
if workspace_id and os.environ.get("USE_PG", "0") not in ("0", "false", "no"):
    from auth.workspace import set_workspace_context
    set_workspace_context(conn, workspace_id)

# All writes in one commit
_persist_updated_analysis(conn, session_id, analysis_json)
_update_score_details_table(conn, session_id, new_scores)
_update_session_score_columns(conn, session_id, new_scores)
conn.commit()  # single commit preserves SET LOCAL
```

### Reconstructing Dependencies from analysis_json

The OCP task runs outside the pipeline context, so it must reconstruct the data structures that downstream functions expect:

| Dependency | Source in analysis_json | Reconstruction |
|---|---|---|
| `best_lap_df` | `speed_trace_best` (list of dicts) | `pd.DataFrame(speed_trace_best)` with column rename |
| `corners` | `corners` (list of dicts) | Used directly |
| `friction_model` | `friction_model` (dict or None) | Used directly, defaults to `{"max_lateral_g": 1.2}` |
| `resampled_laps` | Not stored (too large) | Pass `{0: best_lap_df}` as single-lap dict (see Known Limitations) |
| `theo_df` (DataFrame) | Built from OCP result | `_ocp_result_to_dataframe(result)` with distance_m, speed_mps, time_s |
| `theoretical_result_dict` (dict) | Built from OCP result | `{"speed_profile": [{"distance_m": d, "speed_mps": v}, ...], "track_length_m": max(dist)}` |
| `observed_metrics` | `lap_times`, `speed_trace_best`, existing `score_result` | Extract `best_s`, `n_laps`, `cv_pct`, speed/accel metrics |
| `coaching_v2` | `coaching` or `coaching_v2` | Used as fallback input to `run_enhanced_coaching` |
| `driving_style` | `driving_style` | Used directly |
| `vehicle_class` | `vehicle_params.vehicle_class` or `"car"` | Passed to `run_enhanced_coaching` |
| `available_columns` | `best_lap_df.columns` | `set(best_lap_df.columns)` |

### Known Limitations

**Single-lap resampled_laps:** Since full resampled lap data is not stored in `analysis_json`, the OCP downstream passes `{0: best_lap_df}` as a substitute. This means:
- Per-lap corner metrics and multi-lap stability analysis in downstream functions (e.g. `run_advanced_corner_intelligence`, `_compute_risk_scores`) will be degraded to single-lap quality.
- This is acceptable because the OCP update primarily improves corner speed targets and coaching text. The multi-lap data was already computed by the synchronous pipeline and is preserved in `analysis_json`.

### Graceful Degradation

Each step is wrapped in try/except. If any step fails:
- The raw OCP result in `analysis_json["theoretical_ocp"]` is always preserved (stored by `_store_ocp_result` before downstream runs)
- Scoring update is attempted independently of coaching update
- A warning is logged with the specific step that failed
- The session remains usable with whatever data was successfully stored

### Scoring: "ocp" as Physics Method

Both `scoring/pace.py` and `scoring/execution.py` have `is_physics` checks. Both must include `"ocp"`:

```python
is_physics = simulation_method in (
    "physics", "hybrid", "ocp",
    "kart_envelope_qss", "kart_envelope_casadi",
)
```

This ensures OCP results use the tighter blended percentage+absolute gap scoring thresholds rather than the lenient envelope thresholds. Both files have already been updated.

## Part B: Corner Re-selection on Completed Sessions

### Endpoint Change

`POST /jobs/<job_id>/resume` in `web/routes/jobs.py`.

**Current:** Accepts status `("paused", "awaiting_corner_selection")`.
**New:** Also accepts `"completed"`.

### PipelineContext Reconstruction

After completion, `ctx.cleanup()` deletes the Redis key and temp directory. When a completed job is resumed:

1. `_load_pipeline_context(redis, job_id)` returns `None`
2. New helper `_reconstruct_context_from_db(conn, job_id, redis_client)` is called:
   - Loads job row from `ingestion_jobs` to get `workspace_id` and `file_path`
   - Uses `job_id` as `session_id` (convention: `session_id == job_id` in this codebase, confirmed by `_sanitize_job` at jobs.py:79)
   - CSV path comes from `ingestion_jobs.file_path` (NOT `sessions.source_path`, since the former is the original upload path used by PipelineContext)
   - Checks CSV file exists on disk
   - Creates a fresh `PipelineContext` with those values
   - Returns it (or `None` if data is missing)

### Full Re-run Fallback

`_run_finalize_stages()` already handles missing intermediate state:

```python
if resampled_laps:
    # Resume path with intermediate state — custom corners applied here
    ...
else:
    # Fallback: full re-run from CSV
    result = run_full_analysis(csv_path=ctx.file_path, ...)
```

**Important limitation:** In the fallback path (no intermediate state), `run_full_analysis()` is called WITHOUT `preloaded_corners`. Custom corners from `ctx.custom_corners` are only applied in the `if resampled_laps:` branch. This means:

- If Redis intermediate state has fully expired AND the layout key is gone, the fallback path will **auto-detect corners** instead of using the user's selection.
- **Fix required in `pipeline_tasks.py`:** Pass `ctx.custom_corners` (or `ctx.selected_corner_ids` with the auto-detected corners filtered) to `run_full_analysis()` via a new `override_corners` parameter, OR inject them into `session_meta` so the pipeline picks them up.

The full pipeline re-run will:
- Apply the user's corner selection (via the fix above)
- Re-run theoretical (QSS/hybrid)
- Re-run scoring + coaching
- Persist everything
- Queue OCP (which then runs the full downstream chain from Part A)

### Concurrency: OCP Task vs Resume Race

If a user resumes a completed session while an OCP task from the original pipeline is still running:
- The OCP task's `_update_downstream` and the re-run's `_persist_session_data` will race on the `analysis_json` column.
- **Mitigation:** Before dispatching `pipeline_finalize` on the resume path, check for an in-flight OCP Celery task (via `analysis_json.get("ocp_task_id")`) and revoke it if found. The re-run will queue a fresh OCP task with the new corners.

### Edge Cases

| Case | Handling |
|---|---|
| Redis context expired | Reconstruct from DB via `_reconstruct_context_from_db()` |
| CSV file deleted | Return 409: "Original session file no longer available. Please re-upload." |
| CSV path is Docker temp path (container restarted) | Same as "CSV deleted" — 409 with re-upload message |
| Job not found in DB | Return 404 |
| Job status not resumable | Return 409 (existing behavior) |
| OCP dependencies not installed | OCP queue silently skips (existing behavior via `_is_ocp_enabled()`) |
| In-flight OCP task from previous run | Revoke before dispatching new finalize |
| Custom corners in fallback path (no intermediate state) | Requires `pipeline_tasks.py` change to pass corners through |

### Flow

```
User: POST /jobs/<id>/resume {corners: [{s_start, s_apex, s_end}, ...]}
  |
  v
Status check: "completed" now allowed
  |
  v
Check for in-flight OCP task -> revoke if found
  |
  v
Load PipelineContext from Redis
  -> Found? Use it
  -> Missing? _reconstruct_context_from_db()
     -> Load job row (workspace_id, file_path)
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
  -> _run_finalize_stages()
     -> Has intermediate state? Resume path (corners applied)
     -> No intermediate state? Full re-run (corners passed via fix)
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
| `tasks/ocp_tasks.py` | Replace partial `_update_downstream()` with full chain; batch commits for RLS; add `_build_theoretical_result_dict()` |
| `scoring/pace.py` | Add `"ocp"` to `is_physics` (already done) |
| `scoring/execution.py` | Add `"ocp"` to `is_physics` (already done) |
| `web/routes/jobs.py` | Add `"completed"` to resume status guard; add `_reconstruct_context_from_db()`; revoke in-flight OCP on resume |
| `tasks/pipeline_tasks.py` | Pass custom corners through to `run_full_analysis()` in fallback path |

## Testing Strategy

### Unit tests (new file: `tests/test_ocp_downstream.py`)

1. `_ocp_result_to_dataframe()` produces correct columns and cumulative time
2. `_extract_observed_metrics()` handles missing/partial analysis_json
3. `_build_theoretical_result_dict()` produces correct shape for coaching analyzers
4. `_update_downstream()` with mocked DB and mocked pipeline functions — verify all downstream functions are called with correct arguments and correct data shapes (DataFrame vs dict)
5. `_update_downstream()` graceful degradation — verify partial failure doesn't lose OCP data
6. `_reconstruct_context_from_db()` with valid data returns context
7. `_reconstruct_context_from_db()` with missing CSV returns None
8. RLS context: verify `set_workspace_context` is called before writes when `USE_PG=1`
9. Batch commit: verify only one `conn.commit()` in persist phase

### Integration test (extend existing `test_corner_picker_changes.py`)

10. Resume a completed job with new corners — verify pipeline_finalize is dispatched
11. Resume with missing CSV — verify 409 response
12. Resume with in-flight OCP — verify old task is revoked

## Out of Scope

- Frontend changes to expose a "re-select corners" UI on completed sessions
- Re-selection of corners without re-running the full pipeline (lightweight path)
- OCP warm-starting from previous OCP result on re-analysis
