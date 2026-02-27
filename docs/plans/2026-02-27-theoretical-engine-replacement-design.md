# Theoretical Engine Replacement — Design

**Date**: 2026-02-27
**Status**: Approved
**Approach**: Adapter Pattern (A)

## Context

The existing theoretical lap computation in `telemetry_tool/` uses two engines:
1. `lap_simulation.py` — Point-mass forward-backward solver (physics)
2. `theoretical_engine.py` — Percentile envelope (statistical, 98th pct speed / 99th pct accel)

A new, more advanced engine has been developed in `kart_envelope/` featuring:
- Capability envelope with speed-dependent grip/power/brake models
- QSS + CasADi minimum-time solvers
- Per-corner coaching with time-loss attribution
- Delta maps (distance-aligned actual vs theoretical)
- Session scalars (grip/power/brake condition multipliers)
- Offline training/distillation pipeline
- Bundle v2 fast inference

## Decisions

| Decision | Choice |
|----------|--------|
| Scope | Full replacement + integration (kart_envelope package + pipeline Step 10 + scoring + API) |
| Scoring | Enhance to leverage corner coaching, delta maps, session scalars |
| Tiering | Skip — default `b2c` (full features), don't touch billing |
| API surface | Enrich existing `GET /sessions/<id>/theoretical` endpoint |
| Fallback | Keep old engines (`theoretical_engine.py`, `lap_simulation.py`) as cascade fallback |

## Architecture

### Adapter Pattern

```
pipeline.py Step 10
    ↓
theoretical_adapter.py  (NEW — thin bridge layer)
    ├── Builds TrackGeometry from curvature_profile
    ├── Trains CapabilityEnvelope from resampled_laps
    ├── Infers SessionScalars
    ├── Calls compute_theoretical_lap() → TheoreticalResult
    ├── Runs compute_delta_map() + analyze_corner_performance()
    └── Returns: DataFrame + enriched metrics + coaching + delta + scalars
        ↓
    Falls back to lap_simulation → theoretical_engine on failure
```

### Pipeline Cascade (Step 10)

```
Priority 1: NEW — kart_envelope solver via theoretical_adapter
Priority 2: OLD — lap_simulation.simulate_with_fallback()
Priority 3: OLD — theoretical_engine.build_theoretical_lap()
Priority 4: ImportError (all methods unavailable)
```

## Component Design

### 1. Package Replacement (`kart_envelope/`)

Replace `V2_claude_ai/kart_envelope/` entirely with `New_folder/kart_envelope/`.

New modules over existing:
- `tiering.py` — Product tier gating (default `b2c`)
- `offline/` — Teacher/student distillation (9 modules)
- `optimizer/` — Corner optimization (grid search + ML)
- `control/` — Vehicle control models
- `bundle_validate.py`, `run_batch_optimal.py`, `train_offline.py`
- `monthly_retrain.py`, `retrain_schedule.py`

Cross-reference from telemetry_tool: `pipeline.py:1246` imports `kart_envelope.processing.joker_detection` — must verify still works.

### 2. Adapter Layer (`telemetry_tool/theoretical_adapter.py`)

```python
def compute_theoretical_via_envelope(
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: pd.DataFrame | None,
    vehicle_params: Any | None,
    data_quality_rpt: Any | None,
    *,
    best_driver_time_s: float | None = None,
    config: KartEnvelopeConfig | None = None,
) -> AdapterResult:
    """
    Bridge between telemetry_tool pipeline and kart_envelope solver.

    Returns AdapterResult with:
      .theoretical_df   — DataFrame(distance_m, v_env_mps, accel_max_mps2, brake_max_mps2)
      .theoretical_result — TheoreticalResult from solver
      .corner_coaching  — list[CornerPerformance] (or None)
      .delta_map        — pd.DataFrame (or None)
      .session_scalars  — SessionScalars (or None)
      .method           — str ("kart_envelope_qss" | "kart_envelope_casadi")
    """
```

Steps:
1. Convert resampled_laps to kart_envelope column names (`_map_columns()`)
2. Build `TrackGeometry` from curvature_profile (distance, curvature, heading, xy)
3. Train `CapabilityEnvelope` from lap acceleration data
4. Infer `SessionScalars` (μ, P, B)
5. Call `compute_theoretical_lap(geometry, envelope, scalars)` → `TheoreticalResult`
6. Convert `TheoreticalResult` to pipeline DataFrame format
7. Run `compute_delta_map()` for best lap vs theoretical
8. Run `analyze_corner_performance()` for per-corner coaching
9. Bundle all into `AdapterResult`

### 3. Pipeline Step 10 Changes (`telemetry_tool/pipeline.py`)

The `_theoretical()` function (lines 1543-1672) changes cascade order:

```python
def _theoretical() -> pd.DataFrame:
    nonlocal _sim_method, _sim_result, _corner_coaching, _delta_map, _session_scalars

    # Priority 1: NEW kart_envelope solver
    try:
        from theoretical_adapter import compute_theoretical_via_envelope
        adapter_result = compute_theoretical_via_envelope(
            resampled_laps, curvature_profile, vehicle_params, data_quality_rpt,
            best_driver_time_s=best_driver_time,
        )
        _sim_method = adapter_result.method
        _sim_result = adapter_result.theoretical_result
        _corner_coaching = adapter_result.corner_coaching
        _delta_map = adapter_result.delta_map
        _session_scalars = adapter_result.session_scalars
        return adapter_result.theoretical_df
    except Exception as exc:
        logger.warning("kart_envelope solver failed: %s — falling back", exc)

    # Priority 2: OLD physics simulation (existing code)
    ...
    # Priority 3: OLD percentile envelope (existing code)
    ...
```

New summary keys populated:
- `summary["corner_coaching"]` — list of CornerPerformance dicts
- `summary["delta_map"]` — DataFrame
- `summary["session_scalars"]` — dict {mu, p, b, confidence, condition_label}

### 4. Scoring Enhancement (`telemetry_tool/scoring.py`)

#### Pace (`_score_pace`)
- Recognize `"kart_envelope_qss"` and `"kart_envelope_casadi"` as physics methods
- Uses tighter physics thresholds (achievable ideal, not statistical composite)

#### Execution (`_score_execution`)
- When `corner_coaching` data is available in theoretical_metrics:
  - Call `compute_granular_execution(corner_performances=...)` (already exists)
  - Blend granular score (70%) with existing speed/accel/brake efficiency (30%)
- Fallback: existing behavior when no corner data

#### `score_session()` signature
- Add optional `corner_coaching: list[dict] | None = None` parameter
- When present, pass to execution scorer
- Use `session_scalars.confidence` as additional confidence signal

### 5. DB Schema Extension

**Alembic migration #017** (`017_theoretical_engine_v2`):

SQLite (schema.py):
```sql
ALTER TABLE theoretical_data ADD COLUMN corner_coaching_json TEXT;
ALTER TABLE theoretical_data ADD COLUMN delta_map_json TEXT;
ALTER TABLE theoretical_data ADD COLUMN session_scalars_json TEXT;
```

PostgreSQL (Alembic):
```sql
ALTER TABLE theoretical_data ADD COLUMN corner_coaching_json JSONB;
ALTER TABLE theoretical_data ADD COLUMN delta_map_json JSONB;
ALTER TABLE theoretical_data ADD COLUMN session_scalars_json JSONB;
```

### 6. API Enrichment

**`GET /sessions/<id>/theoretical`** response gains:

```json
{
  "theoretical_time_s": 45.2,
  "actual_best_time_s": 46.1,
  "gap_pct": 1.99,
  "simulation_method": "kart_envelope_qss",
  "speeds": [...],
  "distances": [...],
  "metrics": {
    "best_s": 45.2,
    "speed_mean_mps": 18.3,
    "accel_max_mps2": 12.1,
    "braking_max_mps2": 14.5,
    "simulation_method": "kart_envelope_qss",
    "cornering_limited_fraction": 0.42,
    "confidence": 0.87
  },
  "corner_coaching": [
    {
      "corner_id": 1,
      "s_start": 42.3, "s_end": 58.7, "s_apex": 50.5,
      "entry_speed_actual": 12.4, "entry_speed_theory": 12.8,
      "apex_speed_actual": 9.1, "apex_speed_theory": 9.3,
      "exit_speed_actual": 14.2, "exit_speed_theory": 14.9,
      "time_loss_entry_s": 0.014, "time_loss_apex_s": 0.006, "time_loss_exit_s": 0.022,
      "primary_cause": "exit_speed",
      "coaching_hint": "Accelerate harder exiting Turn 1"
    }
  ],
  "session_scalars": {
    "mu": 0.95, "p": 1.02, "b": 0.98,
    "confidence": 0.87, "condition": "dry"
  }
}
```

### 7. Data Access Layer (`web/models.py`)

- `insert_theoretical_data()` — Store new JSON columns
- `get_theoretical_data()` — Parse new JSON columns for API

### 8. Queries (`db/queries.py`)

Update `INSERT_THEORETICAL_DATA` and `SELECT_THEORETICAL_DATA` to include new columns.

## Files Changed

| File | Change |
|------|--------|
| `kart_envelope/` (entire package) | Replace with New_folder version |
| `telemetry_tool/theoretical_adapter.py` | NEW — adapter layer |
| `telemetry_tool/pipeline.py` | Step 10 cascade + new summary keys |
| `telemetry_tool/scoring.py` | Enhanced execution + pace for new engine |
| `telemetry_tool/db/schema.py` | 3 new columns on theoretical_data |
| `telemetry_tool/db/queries.py` | Updated INSERT/SELECT |
| `telemetry_tool/web/models.py` | Store/retrieve new columns |
| `telemetry_tool/web/routes/api_v1_data.py` | Enrich theoretical response |
| `telemetry_tool/web/routes/api_data.py` | Enrich theoretical response |
| `alembic/versions/017_*.py` | New migration |

## Files NOT Changed

| File | Reason |
|------|--------|
| `telemetry_tool/theoretical_engine.py` | Kept as fallback (Priority 3) |
| `telemetry_tool/lap_simulation.py` | Kept as fallback (Priority 2) |
| Billing / tiering routes | Out of scope |
| Frontend (Next.js) | Out of scope (can consume new fields when ready) |

## Risks

1. **kart_envelope imports**: The new package may import modules not in `requirements.txt` (e.g., `casadi`, `joblib`). These are optional — QSS solver has no extra deps.
2. **Column name mismatch**: The adapter must correctly map RaceChrono column names to kart_envelope canonical names. Existing `_map_to_internal_names()` in pipeline.py is a reference.
3. **`joker_detection` import**: `pipeline.py:1246` imports from `kart_envelope.processing.joker_detection` — must verify this module exists in the new package.
4. **CasADi availability**: CasADi is optional and may not be installed. QSS is the default fallback.
