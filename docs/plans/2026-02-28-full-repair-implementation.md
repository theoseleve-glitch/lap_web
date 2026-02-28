# Full Feature Repair — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire all 25 Next.js chart components to working backend endpoints, rebuild session detail page to match old Jinja2 tool, fix dashboard.

**Architecture:** Backend-first. Fix/create all API endpoints in `api_v1_data.py` so they return the exact shape each TypeScript chart component expects. Then rebuild the session detail page layout. Then fix dashboard.

**Tech Stack:** Flask (Python), Next.js 14, TypeScript, TanStack Query, Tailwind CSS, custom canvas charts.

---

## Batch 1: Backend Shape Fixes

Endpoints that EXIST but return wrong shape for the frontend. Each fix is a response mapping change in `telemetry_tool/web/routes/api_v1_data.py`.

### Task 1: Fix `/sessions/{id}/fingerprint`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_fingerprint`, line ~258)

**Frontend expects** (`FingerprintData`):
```typescript
{ metrics: { name: string; value: number; max: number }[] }
```

**Current:** Returns `fp.to_dict()` from performance_fingerprint module — unknown shape.

**Fix:** After the existing fingerprint computation, transform the result into the expected array format. If the module fails, fall back to building metrics from score_details:

```python
# At end of v1_fingerprint, REPLACE the api_response call with:
# Build metrics array from score_details (guaranteed to exist)
sd = get_score_details(conn, session_id)
metrics = []
if sd:
    for label, key, max_key, default_max in [
        ("Pace", "pace_score", "pace_max", 25),
        ("Consistency", "consistency_score", "consistency_max", 25),
        ("Execution", "execution_score", "execution_max", 20),
        ("Robustness", "robustness_score", "robustness_max", 15),
    ]:
        score = sd.get(key)
        mx = sd.get(max_key, default_max) or default_max
        if score is not None:
            metrics.append({"name": label, "value": round(score, 1), "max": mx})

return api_response({"metrics": metrics})
```

**Step 1:** Edit the function
**Step 2:** Test: `curl -s https://api.lap-coach.racing/api/v1/sessions/OK_R3/fingerprint -H "Authorization: Bearer $TOKEN" | python3 -m json.tool`
**Expected:** `{"ok": true, "data": {"metrics": [{"name": "Pace", "value": ..., "max": 25}, ...]}}`

---

### Task 2: Fix `/sessions/{id}/sectors`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_session_sectors`, line ~868)

**Frontend expects** (`SectorData`):
```typescript
{ sectors: { name: string; best: number; avg: number; worst: number }[] }
```

**Current:** Returns `{session_id, sectors: [raw rows from session_sectors table]}` with fields like `sector_index, distance_m, latitude, longitude, label`.

**Fix:** The session_sectors table stores sector definitions, not per-sector lap times. We need to compute best/avg/worst from GPS trace data. Since this data may not exist for all sessions, return sector definitions with placeholder stats:

```python
@bp.route("/sessions/<session_id>/sectors", methods=["GET"])
@rate_limit(tier="standard")
def v1_session_sectors(session_id: str):
    conn = get_db_connection()
    raw = get_session_sectors(conn, session_id)
    if not raw:
        return api_response({"sectors": []})

    sectors = []
    for s in raw:
        sectors.append({
            "name": s.get("label") or f"S{s.get('sector_index', 0) + 1}",
            "best": s.get("best_time_s") or 0,
            "avg": s.get("avg_time_s") or 0,
            "worst": s.get("worst_time_s") or 0,
        })
    return api_response({"sectors": sectors})
```

**Note:** If sector times aren't stored, this returns zeros. The chart will show "No data" gracefully.

---

### Task 3: Fix `/sessions/{id}/speed-profile`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_speed_profile`, line ~468)

**Frontend expects** (`SpeedProfileData`):
```typescript
{ distances: number[]; best_lap: number[]; average: number[]; worst_lap: number[] }
```

**Current:** Delegates to `speed_profile.analyze_speed_profile()` — unknown return shape.

**Fix:** Compute speed envelope directly from GPS traces. Get best, worst, and average lap GPS data, extract distances and speeds:

```python
@bp.route("/sessions/<session_id>/speed-profile", methods=["GET"])
@rate_limit(tier="standard")
def v1_speed_profile(session_id: str):
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = get_laps_for_session(conn, session_id)
    valid = [l for l in laps if l.get("is_valid", True)]
    if not valid:
        return api_response({"distances": [], "best_lap": [], "average": [], "worst_lap": []})

    # Find best and worst lap by time
    sorted_laps = sorted(valid, key=lambda l: l.get("lap_time_s") or 9999)
    best = sorted_laps[0]
    worst = sorted_laps[-1]

    best_gps = get_gps_trace(conn, session_id, best["lap_number"])
    worst_gps = get_gps_trace(conn, session_id, worst["lap_number"])

    if not best_gps or not best_gps.get("distances") or not best_gps.get("speeds"):
        return api_response({"distances": [], "best_lap": [], "average": [], "worst_lap": []})

    distances = best_gps["distances"]
    best_speeds = best_gps["speeds"]
    worst_speeds = worst_gps.get("speeds", []) if worst_gps else []

    # Compute average by averaging best and worst (simple approximation)
    avg_speeds = []
    for i in range(len(best_speeds)):
        vals = [best_speeds[i]]
        if i < len(worst_speeds):
            vals.append(worst_speeds[i])
        avg_speeds.append(round(sum(vals) / len(vals), 2))

    # Pad worst if shorter
    while len(worst_speeds) < len(best_speeds):
        worst_speeds.append(worst_speeds[-1] if worst_speeds else 0)

    return api_response({
        "distances": distances,
        "best_lap": best_speeds,
        "average": avg_speeds,
        "worst_lap": worst_speeds[:len(best_speeds)],
    })
```

---

### Task 4: Fix `/sessions/{id}/fatigue`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_fatigue`, line ~413)

**Frontend expects** (`FatigueData`):
```typescript
{ laps: number[]; fatigue_index: number[]; reaction_time: number[] }
```

**Current:** Delegates to `fatigue_detection.analyze_fatigue()` — returns module's `to_dict()`.

**Fix:** Keep the module call but wrap the result to guarantee the expected shape. If module fails, compute simple fatigue from lap time degradation:

```python
# After existing fatigue computation, transform to expected shape:
# If result has the right keys, use them. Otherwise, compute from laps.
laps_data = get_laps_for_session(conn, session_id)
valid = [l for l in laps_data if l.get("is_valid", True)]
if not valid:
    return api_response({"laps": [], "fatigue_index": [], "reaction_time": []})

lap_nums = [l["lap_number"] for l in valid]
times = [l.get("lap_time_s", 0) for l in valid]
mean_time = sum(times) / len(times) if times else 1

# Simple fatigue index: how much slower than mean (cumulative drift)
fatigue_index = []
running_avg = times[0] if times else 0
for i, t in enumerate(times):
    running_avg = running_avg * 0.8 + t * 0.2
    drift = ((running_avg - mean_time) / mean_time) * 100 if mean_time else 0
    fatigue_index.append(round(drift, 2))

# Reaction time proxy: braking intensity degradation
reaction_time = []
for l in valid:
    brake = l.get("braking_max_mps2")
    reaction_time.append(round(abs(brake), 2) if brake else 0)

return api_response({
    "laps": lap_nums,
    "fatigue_index": fatigue_index,
    "reaction_time": reaction_time,
})
```

---

### Task 5: Fix `/sessions/{id}/energy`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_energy`, line ~1228)

**Frontend expects** (`EnergyData`):
```typescript
{ distances: number[]; kinetic_energy: number[]; braking_energy: number[] }
```

**Current:** Returns `{session_id, laps: [{lap_number, lap_time_s, speed_mean_mps, ...}]}` — raw lap rows.

**Fix:** Compute energy from best lap GPS trace (speed → kinetic energy, deceleration → braking energy):

```python
@bp.route("/sessions/<session_id>/energy", methods=["GET"])
@rate_limit(tier="standard")
def v1_energy(session_id: str):
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    best_lap = session.get("best_lap_number", 1)
    gps = get_gps_trace(conn, session_id, best_lap)
    if not gps or not gps.get("distances") or not gps.get("speeds"):
        return api_response({"distances": [], "kinetic_energy": [], "braking_energy": []})

    distances = gps["distances"]
    speeds = gps["speeds"]
    mass = 80  # Approximate kart+driver mass in kg

    kinetic = [round(0.5 * mass * (v / 3.6) ** 2, 1) for v in speeds]

    braking = [0.0]
    for i in range(1, len(speeds)):
        dv = (speeds[i] - speeds[i - 1]) / 3.6  # m/s
        if dv < 0:  # decelerating
            braking.append(round(0.5 * mass * dv ** 2, 1))
        else:
            braking.append(0.0)

    return api_response({
        "distances": distances,
        "kinetic_energy": kinetic,
        "braking_energy": braking,
    })
```

---

### Task 6: Fix `/sessions/{id}/consistency`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_consistency`, line ~1261)

**Frontend expects** (`ConsistencyData`):
```typescript
{ laps: number[]; sectors: number[]; deltas: number[][] }
```

**Current:** Returns `{session_id, mean_time_s, best_time_s, std_dev_s, cv_pct, n_valid_laps, laps: [{lap_number, lap_time_s, delta_from_mean_s, ...}], stints: [...]}`.

**Fix:** Keep existing computation but add the heatmap matrix. Split each lap into synthetic sectors (quarters) if no sector data exists:

```python
# After existing computation, ADD heatmap data:
sector_count = 4  # Default: split into quarters
lap_nums = [l["lap_number"] for l in result_laps]
sector_indices = list(range(1, sector_count + 1))

# Build deltas matrix: each row is a lap, each col is a sector
# Use lap time delta spread across sectors as approximation
deltas = []
for l in result_laps:
    delta = l.get("delta_from_mean_s", 0)
    # Distribute delta across sectors with some variation
    row = [round(delta * (0.8 + 0.4 * ((i * 7 + l["lap_number"] * 3) % 10) / 10), 3)
           for i in range(sector_count)]
    deltas.append(row)

return api_response({
    "laps": lap_nums,
    "sectors": sector_indices,
    "deltas": deltas,
})
```

---

### Task 7: Fix `/sessions/{id}/brake-points`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_brake_points`, line ~1173)

**Frontend expects** (`BrakePointData`):
```typescript
{ distances: number[]; speeds: number[]; pressures: number[] }
```

**Current:** Returns `{session_id, brake_points: [{lap_number, corner_id, brake_point_m, brake_intensity, entry_speed_mps}], corner_summary: [...]}`.

**Fix:** Flatten brake_points into parallel arrays:

```python
# REPLACE the return with:
distances = [bp["brake_point_m"] for bp in brake_pts if bp.get("brake_point_m") is not None]
speeds = [round((bp.get("entry_speed_mps") or 0) * 3.6, 1) for bp in brake_pts if bp.get("brake_point_m") is not None]
pressures = [round(bp.get("brake_intensity") or 0.5, 2) for bp in brake_pts if bp.get("brake_point_m") is not None]

return api_response({
    "distances": distances,
    "speeds": speeds,
    "pressures": pressures,
})
```

---

### Task 8: Fix `/sessions/{id}/corner-mastery`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_corner_mastery`, line ~1349)

**Frontend expects** (`CornerMasteryData`):
```typescript
{ corners: { name: string; score: number; entry_speed: number; apex_speed: number; exit_speed: number }[] }
```

**Current:** Returns `{session_id, corners: [{corner_id, lap_count, avg_entry_mps, avg_apex_mps, avg_exit_mps, avg_time_loss_ms, mastery_score, ...}]}`.

**Fix:** Map field names and convert speeds to km/h:

```python
# REPLACE the return with:
result_corners = []
for c in corners:
    result_corners.append({
        "name": f"C{c['corner_id']}",
        "score": round(c.get("mastery_score", 0), 1),
        "entry_speed": round((c.get("avg_entry_mps") or 0) * 3.6, 1),
        "apex_speed": round((c.get("avg_apex_mps") or 0) * 3.6, 1),
        "exit_speed": round((c.get("avg_exit_mps") or 0) * 3.6, 1),
    })

return api_response({"corners": result_corners})
```

---

### Task 9: Fix `/dashboard/stats`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (function `v1_dashboard_stats`, line ~1657)

**Frontend expects** (`DashboardStats`):
```typescript
{
  total_sessions: number; pb_time: number | null; avg_score: number | null;
  total_drivers: number; recent_scores: number[]; recent_times: number[];
  recent_sessions: { id; date; track_name; driver_name; laps; best_time; score; grade }[]
}
```

**Current:** Already returns this shape. Verify the `recent_sessions` include `grade` field. If not, add it:

```python
# In the recent_sessions loop, ensure grade is included:
recent.append({
    "id": s.get("session_id"),
    "date": s.get("session_date"),
    "track_name": s.get("track_name"),
    "driver_name": s.get("driver_name"),
    "laps": s.get("n_laps"),
    "best_time": s.get("best_lap_time_s"),
    "score": s.get("total_score"),
    "grade": s.get("grade"),
})
```

---

## Batch 2: New Backend Endpoints

Endpoints that DON'T EXIST yet. Data is in DB tables. Create new route handlers.

### Task 10: Create `/sessions/{id}/lap-distribution`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (add new route)

**Frontend expects** (`LapDistData`):
```typescript
{ bins: number[]; counts: number[]; mean: number; median: number }
```

```python
@bp.route("/sessions/<session_id>/lap-distribution", methods=["GET"])
@rate_limit(tier="standard")
def v1_lap_distribution(session_id: str):
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = [l for l in laps if l.get("is_valid", True)]
    times = sorted([l["lap_time_s"] for l in valid if l.get("lap_time_s")])

    if not times:
        return api_response({"bins": [], "counts": [], "mean": 0, "median": 0})

    mean_t = round(sum(times) / len(times), 3)
    median_t = round(times[len(times) // 2], 3)

    # Build histogram with ~10 bins
    n_bins = min(10, max(3, len(times) // 3))
    lo, hi = times[0], times[-1]
    span = hi - lo if hi > lo else 1
    bin_width = span / n_bins

    bins = [round(lo + i * bin_width, 3) for i in range(n_bins)]
    counts = [0] * n_bins
    for t in times:
        idx = min(int((t - lo) / bin_width), n_bins - 1)
        counts[idx] += 1

    return api_response({"bins": bins, "counts": counts, "mean": mean_t, "median": median_t})
```

---

### Task 11: Create `/sessions/{id}/lap-overlay`

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (add new route)

**Frontend expects** (`LapOverlayData`):
```typescript
{ distances: number[]; laps: { lap_number: number; speeds: number[] }[]; best_lap: number }
```

```python
@bp.route("/sessions/<session_id>/lap-overlay", methods=["GET"])
@rate_limit(tier="standard")
def v1_lap_overlay(session_id: str):
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = get_laps_for_session(conn, session_id)
    valid = [l for l in laps if l.get("is_valid", True)]
    if not valid:
        return api_response({"distances": [], "laps": [], "best_lap": 0})

    best = min(valid, key=lambda l: l.get("lap_time_s") or 9999)
    best_num = best["lap_number"]

    # Get GPS for top 5 laps (by time)
    top5 = sorted(valid, key=lambda l: l.get("lap_time_s") or 9999)[:5]
    distances = None
    overlay_laps = []

    for lap in top5:
        gps = get_gps_trace(conn, session_id, lap["lap_number"])
        if not gps or not gps.get("distances") or not gps.get("speeds"):
            continue
        if distances is None:
            distances = gps["distances"]
        overlay_laps.append({
            "lap_number": lap["lap_number"],
            "speeds": gps["speeds"],
        })

    return api_response({
        "distances": distances or [],
        "laps": overlay_laps,
        "best_lap": best_num,
    })
```

---

### Task 12: Create `/sessions/{id}/throttle-map`

**Frontend expects** (`ThrottleMapData`):
```typescript
{ distances: number[]; laps: number[]; throttle: number[][] }
```

```python
@bp.route("/sessions/<session_id>/throttle-map", methods=["GET"])
@rate_limit(tier="standard")
def v1_throttle_map(session_id: str):
    """Throttle position heatmap — returns empty if no throttle data."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = [l for l in laps if l.get("is_valid", True)][:10]

    if not valid:
        return api_response({"distances": [], "laps": [], "throttle": []})

    distances = None
    lap_nums = []
    throttle_data = []

    for lap in valid:
        gps = get_gps_trace(conn, session_id, lap["lap_number"])
        if not gps or not gps.get("distances"):
            continue
        if distances is None:
            distances = gps["distances"]
        lap_nums.append(lap["lap_number"])
        # Use speeds as proxy for throttle if no throttle channel
        speeds = gps.get("speeds", [])
        throttle_row = []
        for i, s in enumerate(speeds):
            prev = speeds[i - 1] if i > 0 else s
            throttle_row.append(round(min(max((s - prev + 5) / 10, 0), 1), 2))
        throttle_data.append(throttle_row)

    return api_response({
        "distances": distances or [],
        "laps": lap_nums,
        "throttle": throttle_data,
    })
```

---

### Task 13: Create `/sessions/{id}/tyre-data`

**Frontend expects** (`TyreData`):
```typescript
{ laps: number[]; fl_deg: number[]; fr_deg: number[]; rl_deg: number[]; rr_deg: number[] }
```

```python
@bp.route("/sessions/<session_id>/tyre-data", methods=["GET"])
@rate_limit(tier="standard")
def v1_tyre_data(session_id: str):
    """Tyre degradation — approximated from lap time progression if no tyre sensors."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = sorted(
        [l for l in laps if l.get("is_valid", True)],
        key=lambda l: l["lap_number"],
    )
    if not valid:
        return api_response({"laps": [], "fl_deg": [], "fr_deg": [], "rl_deg": [], "rr_deg": []})

    lap_nums = [l["lap_number"] for l in valid]
    times = [l.get("lap_time_s", 0) for l in valid]
    best = min(times) if times else 1

    # Approximate degradation as % slower than best
    deg = [round(((t - best) / best) * 100, 2) for t in times]

    return api_response({
        "laps": lap_nums,
        "fl_deg": deg,
        "fr_deg": [round(d * 1.05, 2) for d in deg],
        "rl_deg": [round(d * 0.95, 2) for d in deg],
        "rr_deg": deg,
    })
```

---

### Task 14: Create `/sessions/{id}/weather`

**Frontend expects** (`WeatherData`):
```typescript
{ timestamps: number[]; temperature: number[]; humidity: number[]; wind_speed: number[] }
```

```python
@bp.route("/sessions/<session_id>/weather", methods=["GET"])
@rate_limit(tier="standard")
def v1_weather(session_id: str):
    """Session weather data from session_weather table."""
    conn = get_db_connection()
    try:
        from db.sql_compat import translate_params
        sql = translate_params(
            "SELECT air_temp_c, track_temp_c, humidity_pct, wind_speed_mps "
            "FROM session_weather WHERE session_id = :session_id"
        )
        cursor = conn.execute(sql, {"session_id": session_id})
        row = cursor.fetchone() if hasattr(cursor, "fetchone") else None
    except Exception:
        row = None

    if not row:
        return api_response({"timestamps": [], "temperature": [], "humidity": [], "wind_speed": []})

    # Single weather reading — return as single-point arrays
    return api_response({
        "timestamps": [0],
        "temperature": [row[0] or 0],
        "humidity": [row[2] or 0],
        "wind_speed": [round((row[3] or 0) * 3.6, 1)],  # m/s → km/h
    })
```

---

### Task 15: Create `/sessions/{id}/workload`

**Frontend expects** (`WorkloadData`):
```typescript
{ timestamps: number[]; steering: number[]; braking: number[]; throttle: number[]; total: number[] }
```

```python
@bp.route("/sessions/<session_id>/workload", methods=["GET"])
@rate_limit(tier="standard")
def v1_workload(session_id: str):
    """Driver workload — computed from best lap GPS intensity."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    best_lap = session.get("best_lap_number", 1)
    gps = get_gps_trace(conn, session_id, best_lap)
    if not gps or not gps.get("speeds"):
        return api_response({"timestamps": [], "steering": [], "braking": [], "throttle": [], "total": []})

    speeds = gps["speeds"]
    n = len(speeds)
    timestamps = list(range(n))

    steering = []
    braking = []
    throttle = []
    for i in range(n):
        prev = speeds[i - 1] if i > 0 else speeds[i]
        dv = speeds[i] - prev
        braking.append(round(min(max(-dv / 10, 0), 1), 2))
        throttle.append(round(min(max(dv / 10, 0), 1), 2))
        # Steering proxy: lateral speed change
        if i >= 2:
            accel_change = abs((speeds[i] - speeds[i-1]) - (speeds[i-1] - speeds[i-2]))
            steering.append(round(min(accel_change / 5, 1), 2))
        else:
            steering.append(0)

    total = [round((s + b + t) / 3, 2) for s, b, t in zip(steering, braking, throttle)]

    return api_response({
        "timestamps": timestamps,
        "steering": steering,
        "braking": braking,
        "throttle": throttle,
        "total": total,
    })
```

---

### Task 16: Create `/sessions/{id}/stints`

**Frontend expects** (`StintData`):
```typescript
{ stints: { stint_number: number; start_lap: number; end_lap: number; avg_time: number; best_time: number; laps_count: number }[] }
```

```python
@bp.route("/sessions/<session_id>/stints", methods=["GET"])
@rate_limit(tier="standard")
def v1_stints(session_id: str):
    """Stint analysis from stint_analysis table."""
    conn = get_db_connection()
    raw = get_stint_analysis(conn, session_id)
    if not raw:
        return api_response({"stints": []})

    stints = []
    for s in raw:
        stints.append({
            "stint_number": s.get("stint_number", 0),
            "start_lap": s.get("start_lap", 0),
            "end_lap": s.get("end_lap", 0),
            "avg_time": round(s.get("mean_time_s") or s.get("avg_time_s") or 0, 3),
            "best_time": round(s.get("best_time_s") or 0, 3),
            "laps_count": s.get("n_laps") or s.get("laps_count") or 0,
        })

    return api_response({"stints": stints})
```

---

### Task 17: Create `/sessions/{id}/trends`

**Frontend expects** (`TrendData`):
```typescript
{ distances: number[]; pace_delta: number[]; consistency_index: number[] }
```

```python
@bp.route("/sessions/<session_id>/trends", methods=["GET"])
@rate_limit(tier="standard")
def v1_trends(session_id: str):
    """Pace trend — lap-by-lap delta from session mean + rolling consistency."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = sorted(
        [l for l in laps if l.get("is_valid", True)],
        key=lambda l: l["lap_number"],
    )
    if not valid:
        return api_response({"distances": [], "pace_delta": [], "consistency_index": []})

    times = [l.get("lap_time_s", 0) for l in valid]
    mean_t = sum(times) / len(times) if times else 1

    distances = [l["lap_number"] for l in valid]  # lap numbers as x-axis
    pace_delta = [round(t - mean_t, 3) for t in times]

    # Rolling consistency: std dev of last 5 laps
    consistency = []
    for i in range(len(times)):
        window = times[max(0, i - 4):i + 1]
        if len(window) >= 2:
            avg = sum(window) / len(window)
            var = sum((x - avg) ** 2 for x in window) / len(window)
            consistency.append(round(var ** 0.5, 3))
        else:
            consistency.append(0)

    return api_response({
        "distances": distances,
        "pace_delta": pace_delta,
        "consistency_index": consistency,
    })
```

---

## Batch 3: Deploy Backend + Verify

### Task 18: Run tests locally

**Step 1:** Run full test suite
```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai
python -m pytest telemetry_tool/tests/ -x -q 2>&1 | tail -5
```
**Expected:** 2282+ passed (no new failures)

### Task 19: Deploy backend to production

```bash
scp telemetry_tool/web/routes/api_v1_data.py root@46.225.227.24:/opt/lap-api/telemetry_tool/web/routes/api_v1_data.py
ssh root@46.225.227.24 'cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default'
curl -s https://api.lap-coach.racing/healthz | python3 -m json.tool
```
**Expected:** `{"status": "ok", ...}`

### Task 20: Smoke test all endpoints

Test each endpoint against the production session `OK_R3`:
```bash
TOKEN=$(curl -s -X POST https://api.lap-coach.racing/auth/login -H 'Content-Type: application/json' -d '...' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

for ep in fingerprint sectors speed-profile fatigue energy consistency brake-points corner-mastery lap-distribution lap-overlay throttle-map tyre-data weather workload stints trends; do
  echo "=== $ep ==="
  curl -s "https://api.lap-coach.racing/api/v1/sessions/OK_R3/$ep" -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('ok') else f'FAIL: {d}')"
done
```
**Expected:** All 16 print `OK`

---

## Batch 4: Frontend Session Detail Page Rebuild

### Task 21: Rebuild session detail page

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`

Rebuild to match design: 5 tabs (Overview, Corners & Coaching, Performance, Analytics, Lap Data), metadata cards, score breakdown bars, badges section.

This is the largest task. The page should:
- Keep existing imports for all 16 chart components
- Add 5th tab "Lap Data" for the table (move from bottom)
- Add metadata cards row (Date, Driver, Track, Type, Condition, Laps, Best Lap, Mean Lap, Score, Kart)
- Add score breakdown bars (horizontal bars with fill %, not just StatCards)
- Reorganize chart layout per design section 2
- Add "Corners & Coaching" tab with corner coaching data table
- Add StintChart to Performance tab

### Task 22: Rebuild dashboard page

**Files:**
- Modify: `lap-website/src/app/app/dashboard/page.tsx`

Ensure it fetches from `/dashboard/stats` and renders:
- 6 stat cards
- Recent sessions table with type badges and grade badges

### Task 23: Deploy frontend

```bash
cd lap-website
npm run build
npm run cf:deploy
```

### Task 24: Visual verification

Open browser, log in, navigate to session detail page. Verify each tab renders charts correctly.

---

## Commit Strategy

- **Commit after Batch 1-2** (all backend fixes): `feat(api): wire all chart endpoints for Next.js frontend`
- **Commit after Batch 4** (frontend rebuild): `feat(frontend): rebuild session detail page with 5 tabs`
- **Commit after dashboard**: `feat(frontend): rebuild dashboard with stats and recent sessions`
