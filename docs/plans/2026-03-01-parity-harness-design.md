# Parity Harness Design

**Date**: 2026-03-01
**Status**: Approved

## Goal

A single `pytest` command that uploads a synthetic CSV through the Flask test client, queries every data-serving endpoint, and compares API responses against pipeline truth with hard tolerance rules. Failures break the build. JSON artifacts are dumped for diffing.

## Tolerance Contract

```python
TOLERANCES = {
    # Tier 1: Critical (exact or near-exact)
    "lap_time_s":       0.005,   # +/-5 ms
    "best_lap_index":   0,       # exact match (integer)
    "total_score":      0.1,     # +/-0.1 out of 100
    "pillar_score":     0.1,     # +/-0.1 per pillar
    "grade":            0,       # exact string match

    # Tier 2: Geometric
    "sector_time_s":    0.001,   # +/-1 ms
    "corner_s_start":   1.0,     # +/-1 meter
    "corner_s_end":     1.0,     # +/-1 meter
    "corner_s_apex":    1.0,     # +/-1 meter

    # Tier 3: Traces (per-sample)
    "speed_mps":        0.01,    # +/-0.01 m/s
    "gps_lat_lon":      1e-6,    # ~0.1 m at equator
    "accel_g":          0.01,    # +/-0.01 g
}
```

These tolerances are the contract. They live at the top of the test file. Any violation fails the build.

## File Structure

```
telemetry_tool/tests/test_parity_harness.py
  TOLERANCES dict
  ARTIFACTS_DIR
  fixtures:
    synthetic_csv()          - deterministic 5-lap CSV (seed=42)
    app_client()             - Flask test client, in-memory SQLite
    uploaded_session()       - uploads CSV, returns (session_id, pipeline_result)
  helpers:
    assert_close()           - numeric tolerance with clear label
    assert_exact()           - exact match with clear label
    dump_artifact()          - write JSON to artifacts/
  tests:
    test_scores_parity()
    test_laps_parity()
    test_speed_trace_parity()
    test_gps_trace_parity()
    test_corners_parity()
    test_sectors_parity()
    test_gg_data_parity()
    test_missing_data_contract()
```

## Synthetic CSV Fixture

- 5 laps x ~200 points per lap = ~1000 rows
- Columns: Time (s), Lap #, Distance (m), Speed (m/s), Latitude, Longitude, Acceleration Lateral (m/s^2), Acceleration Longitudinal (m/s^2)
- numpy.random.seed(42) for determinism
- Simulated oval with sinusoidal lat/lon, speed dips at fixed distance intervals (corners)
- 5 laps gives margin if pipeline excludes outlap/incomplete

## Data Flow

1. `synthetic_csv()` generates CSV to tmp file
2. `uploaded_session()` POSTs to `/api/v1/sessions/upload` via Flask test client
3. `run_full_analysis()` is patched with `wraps=` to capture the full pipeline result dict while allowing normal execution and DB persistence
4. Each test GETs its endpoint and compares API response data against captured pipeline result
5. Both sides dumped to `artifacts/{endpoint}_pipeline.json` and `artifacts/{endpoint}_api.json` before assertions

## Pipeline Truth Capture

The upload route calls `run_full_analysis()` internally. We use `unittest.mock.patch(wraps=...)` to intercept the return value without altering behavior. The full 43-key pipeline result dict becomes the "truth" for all comparisons.

## Parity Tests

### test_scores_parity
- Pipeline: `score_result.total_score`, `score_result.grade`, `score_result.sub_scores.{pace,consistency,execution,robustness}.score`
- API: `GET /api/v1/sessions/{id}/scores` -> `data.pace_score`, `data.consistency_score`, etc.
- Tolerances: `total_score` +/-0.1, each pillar +/-0.1, grade exact

### test_laps_parity
- Pipeline: `lap_metrics[].{lap_number, lap_time_s, speed_mean_mps, is_valid, is_best}`
- API: `GET /api/v1/sessions/{id}/laps` -> `data.laps[]`
- Tolerances: `lap_time_s` +/-5ms, best_lap_index exact, speed_mean_mps +/-0.01
- Assert same number of laps, same ordering

### test_speed_trace_parity
- Pipeline: `gps_traces` for best lap (distances, speeds arrays)
- API: `GET /api/v1/sessions/{id}/speed-trace`
- Tolerances: each speed sample +/-0.01 m/s, distance samples +/-0.01 m
- Assert same array length

### test_gps_trace_parity
- Pipeline: best lap GPS from `resampled_laps[best_lap_key]` lat/lon/distance
- API: `GET /api/v1/sessions/{id}/gps-trace`
- Tolerances: lat/lon +/-1e-6, distances +/-0.01 m

### test_corners_parity
- Pipeline: `corners[]` from theoretical_data (s_start, s_end, s_apex per corner)
- API: `GET /api/v1/sessions/{id}/corners` -> `data.corners[]`
- Tolerances: s_start/s_end/s_apex +/-1 m each

### test_sectors_parity
- Pipeline: sector analysis from `analysis_json`
- API: `GET /api/v1/sessions/{id}/sector_times`
- Tolerances: sector times +/-1 ms

### test_gg_data_parity
- Pipeline: lateral/longitudinal acceleration arrays for best lap
- API: `GET /api/v1/sessions/{id}/gg-data`
- Tolerances: each sample +/-0.01 g
- Assert `available: true`

### test_missing_data_contract
- Upload a *second* minimal CSV intentionally lacking acceleration columns
- Assert GG endpoint returns `{available: false, reason_code: "NO_GG_DATA", message: "..."}`
- Assert corners endpoint returns `{available: false, reason_code: "NO_CORNER_DATA"}` if corner detection has nothing to detect
- Never empty arrays, never silent 200 with no explanation

## Missing Data Contract

Endpoints modified to return structured unavailability:

```json
{
  "ok": true,
  "data": {
    "available": false,
    "reason_code": "NO_GG_DATA",
    "message": "No accelerometer columns found in source data"
  }
}
```

Reason codes:
- `NO_SCORE_DATA` - scoring step failed/skipped
- `NO_GPS_DATA` - GPS trace not stored
- `NO_GG_DATA` - no accelerometer columns
- `NO_CORNER_DATA` - corner detection failed
- `NO_SECTOR_DATA` - sector analysis unavailable
- `NO_SPEED_TRACE` - speed trace not stored

## Decisions

- **Fixture**: Synthetic CSV only (deterministic, fast, no binary fixture management)
- **Harness type**: pytest test suite (integrates with existing CI, uses conftest fixtures)
- **Test depth**: Flask test client (full round-trip: pipeline -> DB write -> HTTP read -> JSON parse)
- **Missing data**: Fix endpoints + assert in harness (complete contract)
