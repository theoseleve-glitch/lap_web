# API Parity Design — Distance-Axis Aligned Payloads

**Date:** 2026-03-01
**Status:** Approved
**Goal:** Fix payload shape mismatches that break vanilla JS chart modules, add 5 new/modified endpoints, ensure all arrays are distance-axis aligned.

---

## Problem

The SaaS re-port has 27 API endpoints, but 3 critical ones return field names that don't match what the vanilla JS modules read — causing blank maps, "No data" messages, and missing corner markers. Additionally, 4 endpoints the green UI needs don't exist yet.

### Critical Payload Mismatches (charts broken today)

| Endpoint | Backend returns | JS expects | Visible bug |
|----------|----------------|------------|-------------|
| `gps-trace`, `best_lap_gps` | `lat`, `lon` | `latitudes`, `longitudes` | Blank Leaflet map + canvas track map |
| `gg-data` | `lat_g`, `lon_g` | `accel_lat`, `accel_long` | "No acceleration data" on GG diagram |
| `corner-positions` | `s_start`, `s_end`, `s_apex` (distances only) | `lat`, `lon`, `brake_point_m` | No corner markers on map or speed trace |

### Missing Endpoints

| Endpoint | Needed by |
|----------|-----------|
| `GET /sessions/{id}/track-map?lap=best\|all` | Bundled multi-lap GPS for track map (eliminates N+1) |
| `GET /sessions/{id}/sectors` | Frontend-expected alias for sector_times |
| `GET /sessions/{id}/compare?sessionKeyB=...` | Cross-session overlay with distance-aligned traces |
| `GET /sessions/{id}/speed-trace?ref=Y` | Reference lap overlay on speed trace |
| `GET /dev-plans`, `GET /dev-plans/{id}` | Development plans JSON API (replaces Jinja2 HTML) |

---

## Design

### Fix A: GPS Trace Field Names

**Files:** `data_v2.py` — endpoints `get_gps_trace`, `get_best_lap_gps`

Change response keys from `lat`/`lon` to `latitudes`/`longitudes`. Both endpoints currently:
```python
return api_response({
    "lat": trace.get("latitudes", []),
    "lon": trace.get("longitudes", []),
    ...
})
```

Change to:
```python
return api_response({
    "latitudes": trace.get("latitudes", []),
    "longitudes": trace.get("longitudes", []),
    ...
})
```

This matches both `gps_trace.js` (`data.latitudes`) and `track_map.js` (`d.latitudes`).

### Fix B: GG Data Field Names

**File:** `data_v2.py` — endpoint `get_gg_data`

Change `lat_g`/`lon_g` to `accel_lat`/`accel_long`:
```python
return api_response({
    "accel_lat": lat_g,
    "accel_long": lon_g,
    "lap_number": lap_num,
})
```

`gg_diagram.js` reads `data.accel_lat` / `data.accel_long`. Note: `focus_tools.js` line 453 defensively checks both (`data.accel_lat || data.lat_g`), so it handles either.

### Fix C: Corner Positions — Add GPS Coordinates

**File:** `data_v2.py` — endpoint `get_corner_positions`

After building corners from `theoretical_data.corner_coaching`, look up GPS coordinates by interpolating `s_apex` distance against the best lap's GPS trace:

```python
# Get best lap GPS for coordinate lookup
best_lap = _resolve_lap_number(conn, session_id)
best_gps = models.get_gps_trace(conn, session_id, best_lap) if best_lap else None

for corner in corners:
    if best_gps and corner.get("s_apex") is not None:
        # Binary search distances array for s_apex
        dists = best_gps["distances"]
        lats = best_gps["latitudes"]
        lons = best_gps["longitudes"]
        idx = _closest_index(dists, corner["s_apex"])
        corner["lat"] = lats[idx]
        corner["lon"] = lons[idx]
```

Also add `brake_point_m` from `corner_metrics` table when available (per `speed_trace_zoom.js` expectation).

### New Endpoint 1: Track Map Bundle

**Route:** `GET /api/v1/sessions/{id}/track-map?lap=best|all`

Returns bundled GPS data for track map rendering, eliminating N+1 per-lap fetches.

Response for `?lap=all`:
```json
{
  "laps": {
    "3": {"latitudes": [], "longitudes": [], "distances": [], "speeds": []},
    "5": {"latitudes": [], "longitudes": [], "distances": [], "speeds": []}
  },
  "best_lap": 3,
  "corners": [
    {"corner_id": 1, "lat": 45.001, "lon": 7.002, "label": "T1", "distance_m": 150.0}
  ]
}
```

`?lap=best` returns only the best lap. Corners always included. All arrays distance-aligned.

### New Endpoint 2: Sectors Alias

**Route:** `GET /api/v1/sessions/{id}/sectors`

Delegates to existing `sector_times` logic. Returns `SectorAnalysisResult.to_dict()`.

### New Endpoint 3: Cross-Session Compare

**Route:** `GET /api/v1/sessions/{id}/compare?sessionKeyB=...`

Interpolates best laps from both sessions to a common distance axis:

```json
{
  "distances": [],
  "speeds_a": [],
  "speeds_b": [],
  "delta_s": [],
  "session_a": {"session_id": "...", "best_time_s": 60.0, "lap_number": 3},
  "session_b": {"session_id": "...", "best_time_s": 58.5, "lap_number": 2},
  "gps_a": {"latitudes": [], "longitudes": []},
  "gps_b": {"latitudes": [], "longitudes": []}
}
```

Uses numpy interpolation to common distance axis (shorter lap's range, 500 points).

### Modified Endpoint: Speed Trace `?ref=Y`

**Route:** `GET /api/v1/sessions/{id}/speed-trace?lap=X&ref=Y`

When `ref` parameter is provided, response includes reference lap data interpolated to the same distance axis:

```json
{
  "distances": [],
  "speeds": [],
  "lap_number": 3,
  "ref_speeds": [],
  "ref_lap_number": 5
}
```

### New Endpoint 4: Dev Plans JSON API

**Routes:**
- `GET /api/v1/dev-plans` — list all plans with driver name
- `GET /api/v1/dev-plans/{id}` — full detail with parsed `weeks_json`, `progress_json`

---

## Distance-Axis Contract

All trace-data endpoints return parallel arrays indexed on `distances[]` (metres, monotonically increasing from 0). Speeds are in m/s (modules convert to km/h with `* 3.6`). Null values represent GPS signal dropouts. Arrays are NOT uniformly sampled — raw GPS intervals vary, but all arrays in a single response are the same length.

---

## Files Modified

| File | Changes |
|------|---------|
| `telemetry_tool/web/routes/data_v2.py` | Fix 3 payload shapes, add 4 new endpoints, modify speed-trace |
| `telemetry_tool/tests/test_data_api_v2.py` | Update existing tests for new field names, add tests for new endpoints |

---

## Test Plan

1. Existing `gps-trace` tests must be updated to expect `latitudes`/`longitudes`
2. Existing `gg-data` tests must be updated to expect `accel_lat`/`accel_long`
3. New tests for: track-map, sectors, compare, dev-plans, speed-trace ref param
4. Parametrized 404 tests for all new endpoints
5. Run full `test_data_api_v2.py` suite
