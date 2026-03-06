# API Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 3 payload shape mismatches that break vanilla JS chart modules, add 5 new/modified endpoints with distance-axis aligned payloads.

**Architecture:** All changes are in `data_v2.py` (Flask route handlers) — no model layer or schema changes needed. Payload fixes are simple field renames. New endpoints follow existing `@bp.route` + `@_safe_api` + session check pattern.

**Tech Stack:** Flask, SQLite, numpy (for interpolation), existing `models.py` data layer.

**Design doc:** `docs/plans/2026-03-01-api-parity-design.md`

---

### Task 1: Fix GPS Trace Field Names (`latitudes`/`longitudes`)

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:310-316` (gps-trace response)
- Modify: `telemetry_tool/web/routes/data_v2.py:718-724` (best_lap_gps response)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (update assertions)

**Step 1: Update existing tests to expect new field names**

In `test_data_api_v2.py`, find the `TestGpsTrace` assertions (around line 379) and contract tests (around line 1052). Change all `"lat"` → `"latitudes"` and `"lon"` → `"longitudes"`:

```python
# In TestGpsTrace (line ~379):
assert body["data"]["latitudes"] == [45.0, 45.001, 45.002]
assert body["data"]["longitudes"] == [7.0, 7.001, 7.002]

# In TestGpsTraceContract (line ~1052):
assert "latitudes" in data, "Contract: must have latitudes"
assert "longitudes" in data, "Contract: must have longitudes"
assert isinstance(data["latitudes"], list)
assert isinstance(data["longitudes"], list)
assert len(data["latitudes"]) == len(data["longitudes"]) == len(data["distances"]) == len(data["speeds"])
expected_keys = {"lap_number", "latitudes", "longitudes", "distances", "speeds"}
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "gps_trace" -v`
Expected: FAIL — tests now expect `latitudes` but endpoint returns `lat`.

**Step 3: Fix the `gps-trace` endpoint**

In `data_v2.py`, find `get_gps_trace` return statement (line ~310):

```python
# BEFORE:
return api_response({
    "lat": trace.get("latitudes", []),
    "lon": trace.get("longitudes", []),
    "distances": trace.get("distances", []),
    "speeds": trace.get("speeds", []),
    "lap_number": lap_num,
})

# AFTER:
return api_response({
    "latitudes": trace.get("latitudes", []),
    "longitudes": trace.get("longitudes", []),
    "distances": trace.get("distances", []),
    "speeds": trace.get("speeds", []),
    "lap_number": lap_num,
})
```

**Step 4: Fix the `best_lap_gps` endpoint**

In `data_v2.py`, find `get_best_lap_gps` return statement (line ~718):

```python
# BEFORE:
return api_response({
    "lat": trace.get("latitudes", []),
    "lon": trace.get("longitudes", []),
    "distances": trace.get("distances", []),
    "speeds": trace.get("speeds", []),
    "lap_number": lap_num,
})

# AFTER:
return api_response({
    "latitudes": trace.get("latitudes", []),
    "longitudes": trace.get("longitudes", []),
    "distances": trace.get("distances", []),
    "speeds": trace.get("speeds", []),
    "lap_number": lap_num,
})
```

**Step 5: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "gps" -v`
Expected: All PASS.

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "fix: return latitudes/longitudes in GPS endpoints (was lat/lon)"
```

---

### Task 2: Fix GG Data Field Names (`accel_lat`/`accel_long`)

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:358-362` (gg-data response)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (update assertions)

**Step 1: Update existing tests to expect new field names**

In `test_data_api_v2.py`, find `TestGGData` assertions (around line 406-420) and contract tests (around line 1076-1112). Change all `"lat_g"` → `"accel_lat"` and `"lon_g"` → `"accel_long"`:

```python
# In TestGGData (line ~419):
assert body["data"]["accel_lat"] == [0.1, -0.2, 0.05]
assert body["data"]["accel_long"] == [0.5, 0.3, -0.4]

# In TestGGDataContract (line ~1099):
assert "accel_lat" in data, "Contract: must have accel_lat"
assert "accel_long" in data, "Contract: must have accel_long"
assert isinstance(data["accel_lat"], list)
assert isinstance(data["accel_long"], list)
assert len(data["accel_lat"]) == len(data["accel_long"])
expected_keys = {"lap_number", "accel_lat", "accel_long"}
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "gg" -v`
Expected: FAIL — tests expect `accel_lat` but endpoint returns `lat_g`.

**Step 3: Fix the `gg-data` endpoint**

In `data_v2.py`, find `get_gg_data` return statement (line ~358):

```python
# BEFORE:
return api_response({
    "lat_g": lat_g,
    "lon_g": lon_g,
    "lap_number": lap_num,
})

# AFTER:
return api_response({
    "accel_lat": lat_g,
    "accel_long": lon_g,
    "lap_number": lap_num,
})
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "gg" -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "fix: return accel_lat/accel_long in GG endpoint (was lat_g/lon_g)"
```

---

### Task 3: Fix Corner Positions — Add GPS Coordinates

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:730-775` (corner-positions endpoint)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (update + add tests)

**Step 1: Write tests for corner positions with GPS coords**

Add/update tests in `test_data_api_v2.py`:

```python
class TestCornerPositionsWithGPS:

    def test_corners_have_lat_lon(self, client):
        """Corner positions should include lat/lon interpolated from GPS trace."""
        theo = _sample_theoretical_data()
        # Add distance fields to coaching entries
        theo["corner_coaching"] = [
            {"corner_id": 1, "advice": "Brake later", "s_apex": 50.0,
             "s_start": 30.0, "s_end": 70.0, "direction": "left"},
            {"corner_id": 2, "advice": "Earlier throttle", "s_apex": 100.0,
             "s_start": 80.0, "s_end": 120.0, "direction": "right"},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = theo
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_corner_metrics_summary.return_value = []
            mm.get_corner_metrics_for_session.return_value = []

            resp = client.get("/api/v1/sessions/s1/corner-positions")

        assert resp.status_code == 200
        body = resp.get_json()
        corners = body["data"]["corners"]
        assert len(corners) == 2
        # Each corner should have lat/lon from GPS interpolation
        for c in corners:
            assert "lat" in c
            assert "lon" in c
            assert c["lat"] is not None
            assert c["lon"] is not None

    def test_corners_have_brake_point_m(self, client):
        """Corner positions include brake_point_m from corner_metrics."""
        theo = _sample_theoretical_data()
        theo["corner_coaching"] = [
            {"corner_id": 1, "s_apex": 50.0},
        ]
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_theoretical_data.return_value = theo
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_corner_metrics_summary.return_value = [
                {"corner_id": 1, "avg_brake_point_m": 45.5,
                 "min_brake_point_m": 44.0, "max_brake_point_m": 47.0,
                 "n_laps": 3, "avg_entry_speed": 20.0,
                 "avg_apex_speed": 15.0, "avg_exit_speed": 18.0,
                 "avg_grip": 0.9, "avg_time_loss_ms": 50.0,
                 "total_time_loss_ms": 150.0},
            ]
            mm.get_corner_metrics_for_session.return_value = []

            resp = client.get("/api/v1/sessions/s1/corner-positions")

        body = resp.get_json()
        c1 = body["data"]["corners"][0]
        assert c1["brake_point_m"] == 45.5
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "CornerPositionsWithGPS" -v`
Expected: FAIL — no `lat`/`lon` or `brake_point_m` in response.

**Step 3: Rewrite the `corner-positions` endpoint**

Replace the entire `get_corner_positions` function body in `data_v2.py`. The key changes:
1. After building corners from `theoretical_data`, get the best lap GPS trace
2. For each corner with `s_apex`, binary-search the GPS `distances[]` to find closest index, read `latitudes[idx]`/`longitudes[idx]`
3. Merge `brake_point_m` from `corner_metrics_summary` (avg brake point)

Helper function to add before the endpoint:

```python
def _closest_index(distances, target):
    """Binary search for closest distance index."""
    if not distances:
        return 0
    lo, hi = 0, len(distances) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if distances[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo
```

Endpoint rewrite:

```python
@bp.route("/sessions/<session_id>/corner-positions", methods=["GET"])
@_safe_api
def get_corner_positions(session_id: str):
    """Return corner GPS positions with brake point data."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Build corners from theoretical data
    theo = models.get_theoretical_data(conn, session_id)
    corners = []
    if theo and theo.get("corner_coaching"):
        seen = set()
        for cc in theo["corner_coaching"]:
            cid = cc.get("corner_id") or cc.get("corner_index")
            if cid is not None and cid not in seen:
                seen.add(cid)
                corners.append({
                    "corner_id": cid,
                    "s_start": cc.get("s_start") or cc.get("distance_start"),
                    "s_end": cc.get("s_end") or cc.get("distance_end"),
                    "s_apex": cc.get("s_apex") or cc.get("distance_apex"),
                    "direction": cc.get("direction"),
                    "label": cc.get("label") or cc.get("name"),
                    "lat": cc.get("lat"),
                    "lon": cc.get("lon"),
                    "brake_point_m": None,
                })

    if not corners:
        # Fall back to corner_metrics summary (unique corner_ids)
        summary = models.get_corner_metrics_summary(conn, session_id)
        for row in summary:
            corners.append({
                "corner_id": row["corner_id"],
                "s_start": None, "s_end": None, "s_apex": None,
                "direction": None, "label": None,
                "lat": None, "lon": None,
                "brake_point_m": row.get("avg_brake_point_m"),
            })

    if not corners:
        return api_error(ErrorCode.NOT_FOUND,
                         "No corner position data for this session", status=404)

    # Enrich with GPS coordinates from best lap trace
    best_lap = _resolve_lap_number(conn, session_id)
    best_gps = models.get_gps_trace(conn, session_id, best_lap) if best_lap else None

    if best_gps:
        dists = best_gps.get("distances", [])
        lats = best_gps.get("latitudes", [])
        lons = best_gps.get("longitudes", [])
        if dists and lats and lons:
            for corner in corners:
                apex_d = corner.get("s_apex")
                if apex_d is not None and corner.get("lat") is None:
                    idx = _closest_index(dists, apex_d)
                    if idx < len(lats):
                        corner["lat"] = lats[idx]
                        corner["lon"] = lons[idx]

    # Merge brake_point_m from corner_metrics summary
    cm_summary = models.get_corner_metrics_summary(conn, session_id)
    bp_map = {row["corner_id"]: row.get("avg_brake_point_m") for row in cm_summary}
    for corner in corners:
        if corner.get("brake_point_m") is None:
            corner["brake_point_m"] = bp_map.get(corner["corner_id"])

    return api_response({"corners": corners})
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "corner" -v`
Expected: All PASS (including old corner-positions tests and new GPS tests).

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "fix: add GPS coords and brake_point_m to corner-positions endpoint"
```

---

### Task 4: Add Track Map Bundle Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add endpoint at end)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (add tests)

**Step 1: Write tests**

```python
class TestTrackMapEndpoint:

    def test_track_map_best_lap(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_gps_lap_numbers.return_value = [1, 2, 3]
            mm.get_theoretical_data.return_value = None
            mm.get_corner_metrics_summary.return_value = []
            mm.get_corner_metrics_for_session.return_value = []

            resp = client.get("/api/v1/sessions/s1/track-map?lap=best")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "laps" in body["data"]
        assert "best_lap" in body["data"]
        assert "corners" in body["data"]
        assert str(body["data"]["best_lap"]) in body["data"]["laps"]

    def test_track_map_all_laps(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()
            mm.get_gps_lap_numbers.return_value = [1, 2, 3]
            mm.get_theoretical_data.return_value = None
            mm.get_corner_metrics_summary.return_value = []
            mm.get_corner_metrics_for_session.return_value = []

            resp = client.get("/api/v1/sessions/s1/track-map?lap=all")

        assert resp.status_code == 200
        body = resp.get_json()
        # Should have all 3 laps
        assert len(body["data"]["laps"]) == 3

    def test_track_map_404(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/FAKE/track-map")

        assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "TrackMap" -v`
Expected: FAIL — 404 route not found (endpoint doesn't exist yet).

**Step 3: Implement the endpoint**

Add to `data_v2.py`:

```python
@bp.route("/sessions/<session_id>/track-map", methods=["GET"])
@_safe_api
def get_track_map(session_id: str):
    """Return bundled GPS data for track map rendering.

    Query params:
        lap: "best" (default) or "all"
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_mode = request.args.get("lap", "best")
    best_lap = _resolve_lap_number(conn, session_id)

    if best_lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps available", status=404)

    # Determine which laps to include
    if lap_mode == "all":
        lap_numbers = models.get_gps_lap_numbers(conn, session_id)
    else:
        lap_numbers = [best_lap]

    # Fetch GPS data for each lap
    laps_data = {}
    for ln in lap_numbers:
        trace = models.get_gps_trace(conn, session_id, ln)
        if trace:
            laps_data[str(ln)] = {
                "latitudes": trace.get("latitudes", []),
                "longitudes": trace.get("longitudes", []),
                "distances": trace.get("distances", []),
                "speeds": trace.get("speeds", []),
            }

    if not laps_data:
        return api_error(ErrorCode.NOT_FOUND, "No GPS data available", status=404)

    # Build corners with GPS coords (reuse corner-positions logic)
    corners = []
    theo = models.get_theoretical_data(conn, session_id)
    if theo and theo.get("corner_coaching"):
        best_gps = models.get_gps_trace(conn, session_id, best_lap)
        dists = best_gps.get("distances", []) if best_gps else []
        lats = best_gps.get("latitudes", []) if best_gps else []
        lons = best_gps.get("longitudes", []) if best_gps else []

        seen = set()
        for cc in theo["corner_coaching"]:
            cid = cc.get("corner_id") or cc.get("corner_index")
            if cid is not None and cid not in seen:
                seen.add(cid)
                apex_d = cc.get("s_apex") or cc.get("distance_apex")
                lat = cc.get("lat")
                lon = cc.get("lon")
                if lat is None and apex_d is not None and dists:
                    idx = _closest_index(dists, apex_d)
                    if idx < len(lats):
                        lat = lats[idx]
                        lon = lons[idx]
                corners.append({
                    "corner_id": cid,
                    "lat": lat,
                    "lon": lon,
                    "label": cc.get("label") or cc.get("name"),
                    "distance_m": apex_d,
                })

    return api_response({
        "laps": laps_data,
        "best_lap": best_lap,
        "corners": corners,
    })
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "TrackMap" -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "feat: add track-map endpoint with bundled multi-lap GPS data"
```

---

### Task 5: Add Speed Trace `?ref=Y` Parameter

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:248-277` (speed-trace endpoint)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (add tests)

**Step 1: Write tests**

```python
class TestSpeedTraceRef:

    def test_speed_trace_with_ref(self, client):
        """Speed trace with ?ref=Y returns ref_speeds interpolated."""
        trace_a = _sample_gps_trace()
        trace_b = {**_sample_gps_trace(), "speeds": [12.0, 17.0, 14.0]}
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.side_effect = [trace_a, trace_b]

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1&ref=2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "ref_speeds" in body["data"]
        assert body["data"]["ref_lap_number"] == 2
        assert len(body["data"]["ref_speeds"]) == len(body["data"]["distances"])

    def test_speed_trace_without_ref(self, client):
        """Speed trace without ref still works normally."""
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()

            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert "ref_speeds" not in body["data"]
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "SpeedTraceRef" -v`
Expected: FAIL for `test_speed_trace_with_ref` — no `ref_speeds` in response.

**Step 3: Modify the speed-trace endpoint**

```python
@bp.route("/sessions/<session_id>/speed-trace", methods=["GET"])
@_safe_api
def get_speed_trace(session_id: str):
    """Return speed vs distance arrays for a lap.

    Query params:
        lap (int, optional) — lap number; defaults to best lap
        ref (int, optional) — reference lap for overlay; interpolated to same distance axis
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_num = _get_lap_param(conn, session_id)
    if lap_num is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps available", status=404)

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"No trace data for lap {lap_num}",
            status=404,
        )

    result = {
        "distances": trace.get("distances", []),
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
    }

    # Optional reference lap overlay
    ref_raw = request.args.get("ref")
    if ref_raw is not None:
        try:
            ref_lap = int(ref_raw)
        except (ValueError, TypeError):
            ref_lap = None
        if ref_lap is not None:
            ref_trace = models.get_gps_trace(conn, session_id, ref_lap)
            if ref_trace:
                import numpy as np
                ref_dists = ref_trace.get("distances", [])
                ref_speeds = ref_trace.get("speeds", [])
                if ref_dists and ref_speeds:
                    # Interpolate ref speeds onto primary distance axis
                    primary_dists = trace.get("distances", [])
                    interp = np.interp(primary_dists, ref_dists, ref_speeds)
                    result["ref_speeds"] = interp.tolist()
                    result["ref_lap_number"] = ref_lap

    return api_response(result)
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "speed_trace or SpeedTrace" -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "feat: add ref lap overlay to speed-trace endpoint"
```

---

### Task 6: Add Sectors Alias Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add endpoint)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (add test)

**Step 1: Write test**

```python
class TestSectorsEndpoint:

    def test_sectors_returns_sector_analysis(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()
            mm.get_analysis_json.return_value = _sample_analysis_json()

            resp = client.get("/api/v1/sessions/s1/sectors")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "n_sectors" in body["data"]

    def test_sectors_404(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = None

            resp = client.get("/api/v1/sessions/FAKE/sectors")

        assert resp.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "Sectors" -v`

**Step 3: Implement — delegate to sector_times logic**

```python
@bp.route("/sessions/<session_id>/sectors", methods=["GET"])
@_safe_api
def get_sectors(session_id: str):
    """Alias for sector_times — returns sector analysis."""
    return get_sector_times(session_id)
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "Sectors or sector" -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "feat: add /sectors alias endpoint for sector analysis"
```

---

### Task 7: Add Cross-Session Compare Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add endpoint)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (add tests)

**Step 1: Write tests**

```python
class TestSessionCompareOverlay:

    def test_compare_returns_overlay(self, client):
        sessions = _sample_sessions()
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.side_effect = [sessions[0], sessions[1]]
            mm.get_laps_for_session.return_value = _sample_laps()
            mm.get_gps_trace.return_value = _sample_gps_trace()

            resp = client.get("/api/v1/sessions/s1/compare?sessionKeyB=s2")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "distances" in body["data"]
        assert "speeds_a" in body["data"]
        assert "speeds_b" in body["data"]
        assert "delta_s" in body["data"]
        assert "gps_a" in body["data"]
        assert "gps_b" in body["data"]

    def test_compare_missing_session_b(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.return_value = _sample_session()

            resp = client.get("/api/v1/sessions/s1/compare")

        assert resp.status_code == 400

    def test_compare_session_b_not_found(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
             patch("web.routes.data_v2.models") as mm:
            mock_db.return_value = MagicMock()
            mm.get_session_by_id.side_effect = [_sample_session(), None]

            resp = client.get("/api/v1/sessions/s1/compare?sessionKeyB=FAKE")

        assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "SessionCompareOverlay" -v`

**Step 3: Implement the endpoint**

```python
@bp.route("/sessions/<session_id>/compare", methods=["GET"])
@_safe_api
def get_session_compare_overlay(session_id: str):
    """Cross-session overlay with distance-aligned speed traces."""
    conn = get_db_connection()
    session_a = models.get_session_by_id(conn, session_id)
    if session_a is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    session_b_id = request.args.get("sessionKeyB")
    if not session_b_id:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "sessionKeyB parameter is required", status=400)

    session_b = models.get_session_by_id(conn, session_b_id)
    if session_b is None:
        return api_error(ErrorCode.NOT_FOUND,
                         f"Session {session_b_id} not found", status=404)

    # Get best lap traces for both sessions
    best_a = _resolve_lap_number(conn, session_id)
    best_b = _resolve_lap_number(conn, session_b_id)

    if best_a is None or best_b is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps in one or both sessions",
                         status=404)

    trace_a = models.get_gps_trace(conn, session_id, best_a)
    trace_b = models.get_gps_trace(conn, session_b_id, best_b)

    if trace_a is None or trace_b is None:
        return api_error(ErrorCode.NOT_FOUND,
                         "No GPS trace for one or both sessions", status=404)

    import numpy as np

    dist_a = trace_a.get("distances", [])
    spd_a = trace_a.get("speeds", [])
    dist_b = trace_b.get("distances", [])
    spd_b = trace_b.get("speeds", [])

    if not dist_a or not spd_a or not dist_b or not spd_b:
        return api_error(ErrorCode.NOT_FOUND,
                         "Insufficient trace data for comparison", status=404)

    # Common distance axis (shorter lap's range, 500 points)
    max_dist = min(dist_a[-1], dist_b[-1])
    if max_dist <= 0:
        return api_error(ErrorCode.NOT_FOUND,
                         "No valid distance range for comparison", status=404)

    common_dist = np.linspace(0, max_dist, min(500, min(len(dist_a), len(dist_b))))
    interp_a = np.interp(common_dist, dist_a, spd_a)
    interp_b = np.interp(common_dist, dist_b, spd_b)

    # Cumulative time delta
    def _cum_time(dists, speeds):
        t = [0.0]
        for i in range(1, len(dists)):
            ds = dists[i] - dists[i - 1]
            v = speeds[i] if speeds[i] > 0 else speeds[i - 1]
            t.append(t[-1] + (ds / v if v > 0 else 0))
        return t

    time_a = _cum_time(common_dist.tolist(), interp_a.tolist())
    time_b = _cum_time(common_dist.tolist(), interp_b.tolist())
    delta = [round(b - a, 4) for a, b in zip(time_a, time_b)]

    return api_response({
        "distances": common_dist.tolist(),
        "speeds_a": interp_a.tolist(),
        "speeds_b": interp_b.tolist(),
        "delta_s": delta,
        "session_a": {
            "session_id": session_id,
            "best_time_s": session_a.get("best_lap_time_s"),
            "lap_number": best_a,
        },
        "session_b": {
            "session_id": session_b_id,
            "best_time_s": session_b.get("best_lap_time_s"),
            "lap_number": best_b,
        },
        "gps_a": {
            "latitudes": trace_a.get("latitudes", []),
            "longitudes": trace_a.get("longitudes", []),
        },
        "gps_b": {
            "latitudes": trace_b.get("latitudes", []),
            "longitudes": trace_b.get("longitudes", []),
        },
    })
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "SessionCompareOverlay" -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "feat: add cross-session compare endpoint with distance-aligned overlay"
```

---

### Task 8: Add Dev Plans JSON API

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add 2 endpoints)
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (add tests)

**Step 1: Write tests**

```python
class TestDevPlansEndpoint:

    def test_list_dev_plans(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db:
            conn = MagicMock()
            mock_db.return_value = conn
            conn.execute.return_value.fetchall.return_value = [
                {"id": 1, "driver_id": 1, "plan_name": "Beginner Plan",
                 "level": "beginner", "status": "active",
                 "weeks_json": "[]", "progress_json": "{}",
                 "created_at": "2026-01-01", "updated_at": "2026-01-01"},
            ]

            resp = client.get("/api/v1/dev-plans")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["plans"]) == 1
        assert body["data"]["plans"][0]["plan_name"] == "Beginner Plan"

    def test_get_dev_plan_detail(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db:
            conn = MagicMock()
            mock_db.return_value = conn
            conn.execute.return_value.fetchone.return_value = {
                "id": 1, "driver_id": 1, "plan_name": "Beginner Plan",
                "level": "beginner", "status": "active",
                "weeks_json": '[{"week": 1, "drills": []}]',
                "progress_json": '{"completed_drills": 0}',
                "created_at": "2026-01-01", "updated_at": "2026-01-01",
            }

            resp = client.get("/api/v1/dev-plans/1")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["plan_name"] == "Beginner Plan"
        assert isinstance(body["data"]["weeks"], list)  # parsed JSON
        assert isinstance(body["data"]["progress"], dict)  # parsed JSON

    def test_get_dev_plan_not_found(self, client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db:
            conn = MagicMock()
            mock_db.return_value = conn
            conn.execute.return_value.fetchone.return_value = None

            resp = client.get("/api/v1/dev-plans/999")

        assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "DevPlans" -v`

**Step 3: Implement the endpoints**

```python
@bp.route("/dev-plans", methods=["GET"])
@_safe_api
def list_dev_plans():
    """List all development plans."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT dp.*, d.driver_name "
        "FROM development_plans dp "
        "LEFT JOIN drivers d ON dp.driver_id = d.driver_id "
        "ORDER BY dp.created_at DESC"
    ).fetchall()
    plans = []
    for r in rows:
        d = dict(r)
        d.pop("weeks_json", None)
        d.pop("progress_json", None)
        plans.append(d)
    return api_response({"plans": plans})


@bp.route("/dev-plans/<int:plan_id>", methods=["GET"])
@_safe_api
def get_dev_plan(plan_id: int):
    """Return a development plan with parsed weeks and progress."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT dp.*, d.driver_name "
        "FROM development_plans dp "
        "LEFT JOIN drivers d ON dp.driver_id = d.driver_id "
        "WHERE dp.id = :id",
        {"id": plan_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)

    d = dict(row)
    d["weeks"] = json.loads(d.pop("weeks_json", "[]") or "[]")
    d["progress"] = json.loads(d.pop("progress_json", "{}") or "{}")
    return api_response(d)
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "DevPlans" -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "feat: add dev-plans JSON API endpoints"
```

---

### Task 9: Update 404 Parametrized Tests + Full Suite Verification

**Files:**
- Modify: `telemetry_tool/tests/test_data_api_v2.py` (extend parametrized list)

**Step 1: Add new endpoint paths to the parametrized 404 test**

Find `TestNewEndpoints404ForMissingSession.NEW_PATHS` and add the new endpoints:

```python
"/api/v1/sessions/FAKE/track-map",
"/api/v1/sessions/FAKE/sectors",
"/api/v1/sessions/FAKE/compare?sessionKeyB=OTHER",
```

**Step 2: Run the full test suite**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -v`
Expected: All tests pass.

Run: `pytest telemetry_tool/tests/test_upload_sync.py -v`
Expected: All 7 pass.

Run: `pytest telemetry_tool/tests/test_re_port_correctness.py -v`
Expected: All 7 pass.

**Step 3: Verify all routes are registered**

```bash
python -c "
import sys; sys.path.insert(0, 'telemetry_tool')
from web.app import create_app
app = create_app()
rules = sorted([r.rule for r in app.url_map.iter_rules() if 'sessions' in r.rule or 'dev-plans' in r.rule])
for r in rules: print(r)
"
```

Expected output should include: `/track-map`, `/sectors`, `/compare`, `/dev-plans`, `/dev-plans/<int:plan_id>`.

**Step 4: Commit**

```bash
git add telemetry_tool/tests/test_data_api_v2.py
git commit -m "test: extend parametrized 404 tests for new API parity endpoints"
```

---

## Execution Order

```
Task 1 (GPS field names)  →  Task 2 (GG field names)  →  Task 3 (corner GPS)
→  Task 4 (track-map)  →  Task 5 (speed-trace ref)  →  Task 6 (sectors alias)
→  Task 7 (compare overlay)  →  Task 8 (dev-plans)  →  Task 9 (final verification)
```

Tasks 1-3 are critical bug fixes. Tasks 4-8 are independent of each other (but depend on Tasks 1-3). Task 9 is final verification.
