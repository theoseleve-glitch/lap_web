# Corner Replay Re-Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the stubbed `/api/v1/sessions/{id}/corner-replay` endpoint with a batch composite response and rewrite the frontend corner replay components to support three modes (Review, Split Comparison, Top 3 Overlay) with synchronized canvas map + cockpit gauges.

**Architecture:** Single batch GET endpoint returns all lap traces, corners, metrics, and replay windows. Frontend orchestrator manages state via `useReducer` with one `requestAnimationFrame` loop driving map + cockpit in sync. Corner selection happens during the analysis flow via a `TrackCornerPicker` overlay. Pedal/steering data is conditionally included based on variance detection.

**Tech Stack:** Python Flask (backend), PostgreSQL/SQLite (DB), Next.js 14 + TypeScript + Tailwind (frontend), Canvas 2D API, TanStack React Query 5, Vitest + Playwright (tests)

---

## Context You Need

### Key File Locations

| File | Purpose |
|------|---------|
| `telemetry_tool/web/routes/api_v1_data.py` | V1 data API — stubbed endpoint at lines 3728-3736 |
| `telemetry_tool/web/models.py` | `get_gps_trace()` at line 670, `get_laps_for_session()` etc. |
| `telemetry_tool/web/api_utils.py` | `api_response()`, `api_error()`, `ErrorCode` |
| `telemetry_tool/db/schema.py` | Tables: `gps_traces` (line 99), `corner_metrics` (line 390), `track_key_corners` (line 428) |
| `telemetry_tool/web/routes/api_data.py` | Legacy GET/POST key-corners at lines 1135-1178 |
| `telemetry_tool/web/routes/analysis.py` | `submit_corners_api()` at line 596, `_persist_key_corners()` at line 633 |
| `lap-website/src/components/app/corner-replay/` | Existing components (5 files, will be rewritten) |
| `lap-website/src/app/app/sessions/[id]/page.tsx` | Corners & Coaching tab at lines 1076-1214 |
| `lap-website/src/lib/api-client.ts` | `api.get/post/put` wrappers at lines 105-114 |
| `lap-website/src/hooks/useInteractiveCanvas.ts` | Canvas + hover/tooltip hook used by map |

### Endpoint Pattern (Reference)

All V1 endpoints follow this pattern in `api_v1_data.py`:

```python
@bp.route("/sessions/<session_id>/speed-trace", methods=["GET"])
@rate_limit(tier="read")
def v1_speed_trace(session_id: str):
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    # ... query + transform ...
    return api_response({"distances": [...], "speeds": [...]})
```

### Database Tables

**`gps_traces`** — Per-lap GPS data as JSON arrays:
- `session_id`, `lap_number`, `latitudes_json`, `longitudes_json`, `distances_json`, `speeds_json`, `accel_lat_json`, `accel_long_json`

**`corner_metrics`** — Per-lap per-corner analysis:
- `session_id`, `lap_number`, `corner_id`, `brake_point_m`, `entry_speed_mps`, `apex_speed_mps`, `exit_speed_mps`, `time_loss_ms`, `coaching_hint`

**`track_key_corners`** — User-defined corners per track:
- `track_id`, `corner_id`, `label`, `lat`, `lon`, `dist_m`

### Frontend API Client Pattern

```typescript
import { api } from '@/lib/api-client';

// Returns unwrapped data (envelope already parsed)
const data = await api.get<CornerReplayData>(`/sessions/${id}/corner-replay`);
```

### Existing Models Function

```python
# telemetry_tool/web/models.py:670
def get_gps_trace(conn, session_id, lap_number) -> Optional[dict]:
    # Returns: {"latitudes": [...], "longitudes": [...], "distances": [...],
    #           "speeds": [...], "accel_lat"?: [...], "accel_long"?: [...]}
```

---

## Task 1: Backend — Batch Corner Replay Endpoint (Tests)

**Files:**
- Create: `telemetry_tool/tests/test_corner_replay_api.py`

**Step 1: Write the test file with batch endpoint tests**

Create `telemetry_tool/tests/test_corner_replay_api.py`:

```python
"""Tests for the corner replay batch API endpoint.

Validates:
- 404 for non-existent session
- 409 when track has no key corners
- 422 when session has < 2 GPS laps
- Correct response structure
- has_pedal_data / has_steering_data detection
- Trace keys omitted when has_* is false
- Replay window bounds
- Corners sorted by dist_m (null-safe)
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures — in-memory DB with required tables
# ---------------------------------------------------------------------------

def _make_conn():
    """Create a minimal mock connection with pre-loaded data."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            track_id TEXT,
            file_name TEXT DEFAULT 'test.csv'
        )
    """)
    conn.execute("""
        CREATE TABLE laps (
            session_id TEXT,
            lap_number INTEGER,
            lap_time_s REAL,
            is_best INTEGER DEFAULT 0,
            UNIQUE(session_id, lap_number)
        )
    """)
    conn.execute("""
        CREATE TABLE gps_traces (
            session_id TEXT,
            lap_number INTEGER,
            latitudes_json TEXT,
            longitudes_json TEXT,
            distances_json TEXT,
            speeds_json TEXT,
            accel_lat_json TEXT,
            accel_long_json TEXT,
            UNIQUE(session_id, lap_number)
        )
    """)
    conn.execute("""
        CREATE TABLE track_key_corners (
            track_id TEXT,
            corner_id INTEGER,
            label TEXT,
            lat REAL,
            lon REAL,
            dist_m REAL,
            UNIQUE(track_id, corner_id)
        )
    """)
    conn.execute("""
        CREATE TABLE corner_metrics (
            session_id TEXT,
            lap_number INTEGER,
            corner_id INTEGER,
            brake_point_m REAL,
            brake_intensity REAL,
            entry_speed_mps REAL,
            apex_speed_mps REAL,
            exit_speed_mps REAL,
            throttle_onset_m REAL,
            exit_accel_mps2 REAL,
            grip_utilization REAL,
            time_loss_ms REAL,
            coaching_hint TEXT,
            UNIQUE(session_id, lap_number, corner_id)
        )
    """)
    conn.commit()
    return conn


def _seed_full_session(conn, session_id="sess-001", track_id="track-001"):
    """Seed a complete session with 3 laps, 2 key corners, corner metrics."""
    import json as _json

    conn.execute(
        "INSERT INTO sessions (session_id, track_id) VALUES (?, ?)",
        (session_id, track_id),
    )

    # 3 laps
    for lap in range(1, 4):
        lap_time = 60.0 + lap
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_best) VALUES (?, ?, ?, ?)",
            (session_id, lap, lap_time, 1 if lap == 1 else 0),
        )

    # GPS traces — 200 points per lap, with speed data
    for lap in range(1, 4):
        n = 200
        lats = [45.0 + i * 0.0001 for i in range(n)]
        lons = [9.0 + i * 0.0001 for i in range(n)]
        dists = [i * 5.0 for i in range(n)]  # 0m to 995m
        speeds = [15.0 + (i % 20) * 0.5 for i in range(n)]  # 15-25 m/s
        accel_lat = [0.1 * (i % 10 - 5) for i in range(n)]
        accel_lon = [0.05 * (i % 8 - 4) for i in range(n)]

        conn.execute(
            """INSERT INTO gps_traces
               (session_id, lap_number, latitudes_json, longitudes_json,
                distances_json, speeds_json, accel_lat_json, accel_long_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, lap,
             _json.dumps(lats), _json.dumps(lons),
             _json.dumps(dists), _json.dumps(speeds),
             _json.dumps(accel_lat), _json.dumps(accel_lon)),
        )

    # 2 key corners
    conn.execute(
        "INSERT INTO track_key_corners (track_id, corner_id, label, lat, lon, dist_m) VALUES (?, ?, ?, ?, ?, ?)",
        (track_id, 1, "Turn 1", 45.005, 9.005, 100.0),
    )
    conn.execute(
        "INSERT INTO track_key_corners (track_id, corner_id, label, lat, lon, dist_m) VALUES (?, ?, ?, ?, ?, ?)",
        (track_id, 2, "Hairpin", 45.010, 9.010, 500.0),
    )

    # Corner metrics for each lap + corner
    for lap in range(1, 4):
        for cid, brake_m in [(1, 90.0), (2, 490.0)]:
            conn.execute(
                """INSERT INTO corner_metrics
                   (session_id, lap_number, corner_id, brake_point_m,
                    entry_speed_mps, apex_speed_mps, exit_speed_mps,
                    time_loss_ms, coaching_hint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, lap, cid, brake_m,
                 20.0 + lap, 15.0 + lap, 18.0 + lap,
                 50.0 * lap, f"Brake later into C{cid}" if lap > 1 else None),
            )

    conn.commit()


# ---------------------------------------------------------------------------
# Tests — batch endpoint logic
# ---------------------------------------------------------------------------


class TestBuildCornerReplayResponse:
    """Tests for the _build_corner_replay_response helper."""

    def test_returns_none_for_missing_session(self):
        """Non-existent session returns None."""
        conn = _make_conn()
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "nonexistent")
        assert result is None

    def test_returns_409_signal_when_no_key_corners(self):
        """Session with track but no key corners returns 409 signal."""
        conn = _make_conn()
        conn.execute("INSERT INTO sessions (session_id, track_id) VALUES ('s1', 't1')")
        conn.execute("INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 1, 60.0)")
        conn.execute("INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 2, 61.0)")
        n = 100
        import json as _json
        conn.execute(
            """INSERT INTO gps_traces (session_id, lap_number, latitudes_json,
               longitudes_json, distances_json, speeds_json)
               VALUES ('s1', 1, ?, ?, ?, ?)""",
            (_json.dumps([0]*n), _json.dumps([0]*n), _json.dumps([0]*n), _json.dumps([0]*n)),
        )
        conn.execute(
            """INSERT INTO gps_traces (session_id, lap_number, latitudes_json,
               longitudes_json, distances_json, speeds_json)
               VALUES ('s1', 2, ?, ?, ?, ?)""",
            (_json.dumps([0]*n), _json.dumps([0]*n), _json.dumps([0]*n), _json.dumps([0]*n)),
        )
        conn.commit()
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "s1")
        assert result == "NO_KEY_CORNERS"

    def test_returns_422_signal_when_fewer_than_2_laps(self):
        """Session with only 1 GPS lap returns 422 signal."""
        conn = _make_conn()
        conn.execute("INSERT INTO sessions (session_id, track_id) VALUES ('s1', 't1')")
        conn.execute("INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 1, 60.0)")
        conn.execute(
            "INSERT INTO track_key_corners (track_id, corner_id, label, lat, lon, dist_m) VALUES ('t1', 1, 'C1', 0, 0, 100)",
        )
        import json as _json
        n = 100
        conn.execute(
            """INSERT INTO gps_traces (session_id, lap_number, latitudes_json,
               longitudes_json, distances_json, speeds_json)
               VALUES ('s1', 1, ?, ?, ?, ?)""",
            (_json.dumps([0]*n), _json.dumps([0]*n), _json.dumps([0]*n), _json.dumps([0]*n)),
        )
        conn.commit()
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "s1")
        assert result == "INSUFFICIENT_LAPS"

    def test_full_response_structure(self):
        """Complete session returns all expected keys."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "sess-001")
        assert isinstance(result, dict)
        assert result["session_id"] == "sess-001"
        assert result["track_id"] == "track-001"
        assert "corners" in result
        assert "laps" in result
        assert "traces" in result
        assert "replay_windows" in result
        assert "corner_metrics" in result
        assert "has_pedal_data" in result
        assert "has_steering_data" in result

    def test_corners_sorted_by_dist_m(self):
        """Corners array is sorted by dist_m ascending."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "sess-001")
        dists = [c["dist_m"] for c in result["corners"]]
        assert dists == sorted(dists)

    def test_has_pedal_data_false_when_no_brake_throttle(self):
        """has_pedal_data is False when no brake/throttle columns exist."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        # Our seeded data has no brake/throttle columns in gps_traces
        result = _build_corner_replay_response(conn, "sess-001")
        assert result["has_pedal_data"] is False

    def test_has_steering_data_false_when_no_steering(self):
        """has_steering_data is False when no steering column exists."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "sess-001")
        assert result["has_steering_data"] is False

    def test_trace_keys_omit_pedal_when_not_available(self):
        """Trace dicts don't contain brake/throttle when has_pedal_data is False."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "sess-001")
        for _lap_num, trace in result["traces"].items():
            assert "brake" not in trace
            assert "throttle" not in trace

    def test_replay_window_indices_within_bounds(self):
        """start_idx and end_idx are within [0, trace_length-1]."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "sess-001")
        for _corner_id, windows in result["replay_windows"].items():
            for w in windows:
                lap_key = str(w["lap_number"])
                trace_len = len(result["traces"][lap_key]["lat"])
                assert w["start_idx"] >= 0
                assert w["end_idx"] < trace_len
                assert w["start_idx"] <= w["end_idx"]

    def test_laps_have_correct_structure(self):
        """Each lap entry has lap_number and lap_time_s."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "sess-001")
        assert len(result["laps"]) == 3
        for lap in result["laps"]:
            assert "lap_number" in lap
            assert "lap_time_s" in lap

    def test_corner_metrics_keyed_by_corner_id(self):
        """corner_metrics dict is keyed by corner_id string."""
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _build_corner_replay_response
        result = _build_corner_replay_response(conn, "sess-001")
        assert "1" in result["corner_metrics"]
        assert "2" in result["corner_metrics"]
        # Each corner has entries for each lap
        assert len(result["corner_metrics"]["1"]) == 3
```

**Step 2: Run tests to verify they fail**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_corner_replay_api.py -v --tb=short 2>&1 | head -40`
Expected: FAIL — `ImportError: cannot import name '_build_corner_replay_response'`

**Step 3: Commit test file**

```bash
git add telemetry_tool/tests/test_corner_replay_api.py
git commit -m "test: add failing tests for corner replay batch endpoint"
```

---

## Task 2: Backend — Implement `_build_corner_replay_response` Helper

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:3724-3736`

**Step 1: Add the `_build_corner_replay_response` helper function**

Replace the stubbed endpoint (lines 3724-3736) in `telemetry_tool/web/routes/api_v1_data.py` with the helper + real endpoint. Insert BEFORE the stub:

```python
# ---------------------------------------------------------------------------
# Corner Replay helpers
# ---------------------------------------------------------------------------

def _has_variance(arr: list) -> bool:
    """Return True if the array has at least one non-zero value with variance."""
    if not arr or len(arr) < 2:
        return False
    first = arr[0]
    return any(abs(v - first) > 1e-9 for v in arr[:50])  # check first 50


def _build_corner_replay_response(conn, session_id: str):
    """Build the complete corner replay batch response.

    Returns:
        dict — full response payload
        None — session not found
        "NO_KEY_CORNERS" — track has no key corners
        "INSUFFICIENT_LAPS" — fewer than 2 GPS laps
    """
    # 1. Load session
    session = get_session_by_id(conn, session_id)
    if session is None:
        return None

    track_id = session.get("track_id")

    # 2. Load key corners
    try:
        kc_rows = conn.execute(
            "SELECT corner_id, label, lat, lon, dist_m "
            "FROM track_key_corners WHERE track_id = :tid ORDER BY dist_m",
            {"tid": track_id},
        ).fetchall()
    except Exception:
        kc_rows = []

    if not kc_rows:
        return "NO_KEY_CORNERS"

    corners = []
    for r in kc_rows:
        row = dict(r) if not isinstance(r, dict) else r
        corners.append({
            "corner_id": str(row["corner_id"]),
            "label": row.get("label") or f"C{row['corner_id']}",
            "lat": float(row["lat"]) if row.get("lat") else 0.0,
            "lon": float(row["lon"]) if row.get("lon") else 0.0,
            "dist_m": float(row["dist_m"]) if row.get("dist_m") is not None else float("inf"),
        })
    # Sort null-safe by dist_m
    corners.sort(key=lambda c: c["dist_m"] if c["dist_m"] != float("inf") else 1e12)

    # 3. Load laps
    laps_raw = get_laps_for_session(conn, session_id)
    laps = []
    for lap in laps_raw:
        laps.append({
            "lap_number": lap["lap_number"],
            "lap_time_s": lap.get("lap_time_s"),
        })

    # 4. Load GPS traces for all laps
    lap_numbers = get_gps_lap_numbers(conn, session_id)
    if len(lap_numbers) < 2:
        return "INSUFFICIENT_LAPS"

    traces = {}
    has_pedal = False
    has_steering = False

    for ln in lap_numbers:
        gps = get_gps_trace(conn, session_id, ln)
        if gps is None:
            continue

        trace = {
            "lat": gps.get("latitudes", []),
            "lon": gps.get("longitudes", []),
            "dist_m": gps.get("distances", []),
            "speed_mps": gps.get("speeds", []),
            "accel_lat": gps.get("accel_lat", []),
            "accel_lon": gps.get("accel_long", []),
        }

        # Check for pedal data (brake/throttle stored as separate columns if available)
        brake = gps.get("brake", [])
        throttle = gps.get("throttle", [])
        steering = gps.get("steering", [])

        if brake and throttle and _has_variance(brake):
            has_pedal = True
            trace["brake"] = brake
            trace["throttle"] = throttle

        if steering and _has_variance(steering):
            has_steering = True
            trace["steering"] = steering

        traces[str(ln)] = trace

    if len(traces) < 2:
        return "INSUFFICIENT_LAPS"

    # 5. Compute replay windows per corner
    replay_windows = {}
    for corner in corners:
        cid = corner["corner_id"]
        windows = []
        for lap_key, trace in traces.items():
            ln = int(lap_key)
            dists = trace["dist_m"]
            if not dists:
                continue

            # Find brake point from corner_metrics
            try:
                cm_row = conn.execute(
                    "SELECT brake_point_m FROM corner_metrics "
                    "WHERE session_id = :sid AND lap_number = :ln AND corner_id = :cid",
                    {"sid": session_id, "ln": ln, "cid": int(cid)},
                ).fetchone()
            except Exception:
                cm_row = None

            if cm_row:
                brake_m = float(dict(cm_row) if not isinstance(cm_row, dict) else cm_row).get("brake_point_m", corner["dist_m"])
            else:
                brake_m = corner["dist_m"]

            # Find index of brake point in distances
            brake_idx = 0
            for i, d in enumerate(dists):
                if d >= brake_m:
                    brake_idx = i
                    break

            pad = 120
            start_idx = max(0, brake_idx - pad)
            end_idx = min(len(dists) - 1, brake_idx + pad)

            # Estimate duration
            speeds = trace["speed_mps"]
            duration = 0.0
            for i in range(start_idx, end_idx):
                if i + 1 < len(dists):
                    dd = abs(dists[i + 1] - dists[i])
                    v = max(speeds[i] if i < len(speeds) else 1.0, 0.5)
                    duration += dd / v

            windows.append({
                "lap_number": ln,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "estimated_duration_s": round(duration, 3),
            })

        replay_windows[cid] = windows

    # 6. Load corner metrics
    corner_metrics_out = {}
    for corner in corners:
        cid = corner["corner_id"]
        try:
            cm_rows = conn.execute(
                """SELECT lap_number, brake_point_m, entry_speed_mps,
                          apex_speed_mps, exit_speed_mps, time_loss_ms, coaching_hint
                   FROM corner_metrics
                   WHERE session_id = :sid AND corner_id = :cid
                   ORDER BY lap_number""",
                {"sid": session_id, "cid": int(cid)},
            ).fetchall()
        except Exception:
            cm_rows = []

        metrics_list = []
        for r in cm_rows:
            row = dict(r) if not isinstance(r, dict) else r
            metrics_list.append({
                "lap_number": row["lap_number"],
                "brake_point_m": row.get("brake_point_m"),
                "entry_speed_mps": row.get("entry_speed_mps"),
                "apex_speed_mps": row.get("apex_speed_mps"),
                "exit_speed_mps": row.get("exit_speed_mps"),
                "time_loss_ms": row.get("time_loss_ms"),
                "coaching_hint": row.get("coaching_hint"),
            })
        corner_metrics_out[cid] = metrics_list

    return {
        "session_id": session_id,
        "track_id": track_id,
        "has_pedal_data": has_pedal,
        "has_steering_data": has_steering,
        "corners": corners,
        "laps": laps,
        "traces": traces,
        "replay_windows": replay_windows,
        "corner_metrics": corner_metrics_out,
    }
```

Then replace the stub route handler (lines 3728-3736):

```python
@bp.route("/sessions/<session_id>/corner-replay", methods=["GET"])
@rate_limit(tier="read")
def v1_corner_replay(session_id: str):
    """Return batch corner replay data for all laps and corners.

    Returns:
        200 with full replay payload
        404 if session not found
        409 if no key corners defined
        422 if fewer than 2 GPS laps
    """
    conn = get_db_connection()
    result = _build_corner_replay_response(conn, session_id)

    if result is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    if result == "NO_KEY_CORNERS":
        return api_error(
            ErrorCode.CONFLICT,
            "No key corners defined for this track. Run analysis with corner selection first.",
            status=409,
        )
    if result == "INSUFFICIENT_LAPS":
        return api_error(
            ErrorCode.VALIDATION,
            "Insufficient GPS data: need at least 2 laps",
            status=422,
        )

    return api_response(result)
```

**Step 2: Verify `ErrorCode.CONFLICT` exists**

Check `telemetry_tool/web/api_utils.py` for existing ErrorCode values. If `CONFLICT` is missing, add it to the enum.

**Step 3: Run tests to verify they pass**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_corner_replay_api.py -v --tb=short`
Expected: All 11 tests PASS

**Step 4: Run full backend test suite to check for regressions**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/ -v --tb=short 2>&1 | tail -20`
Expected: All existing tests still pass

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_data.py telemetry_tool/web/api_utils.py
git commit -m "feat(api): implement batch corner replay endpoint with replay windows and metrics"
```

---

## Task 3: Backend — Key Corners CRUD Endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py` (add after corner-replay endpoint)
- Modify: `telemetry_tool/tests/test_corner_replay_api.py` (add tests)

**Step 1: Write failing tests for key corners endpoints**

Add to `test_corner_replay_api.py`:

```python
class TestKeyCornersCRUD:
    """Tests for GET/PUT /api/v1/tracks/{trackId}/key-corners."""

    def test_get_returns_corners_for_track(self):
        conn = _make_conn()
        _seed_full_session(conn)
        from web.routes.api_v1_data import _get_key_corners
        result = _get_key_corners(conn, "track-001")
        assert len(result) == 2
        assert result[0]["corner_id"] == 1
        assert result[0]["label"] == "Turn 1"

    def test_get_returns_empty_for_track_without_corners(self):
        conn = _make_conn()
        conn.execute("INSERT INTO sessions (session_id, track_id) VALUES ('s1', 't1')")
        conn.commit()
        from web.routes.api_v1_data import _get_key_corners
        result = _get_key_corners(conn, "t1")
        assert result == []

    def test_put_creates_corners(self):
        conn = _make_conn()
        corners = [
            {"corner_id": 1, "label": "T1", "lat": 45.0, "lon": 9.0, "dist_m": 100},
            {"corner_id": 2, "label": "T2", "lat": 45.1, "lon": 9.1, "dist_m": 200},
            {"corner_id": 3, "label": "T3", "lat": 45.2, "lon": 9.2, "dist_m": 300},
        ]
        from web.routes.api_v1_data import _upsert_key_corners
        _upsert_key_corners(conn, "track-001", corners)
        rows = conn.execute(
            "SELECT * FROM track_key_corners WHERE track_id = 'track-001' ORDER BY corner_id"
        ).fetchall()
        assert len(rows) == 3

    def test_put_rejects_fewer_than_3_corners(self):
        corners = [
            {"corner_id": 1, "label": "T1", "lat": 45.0, "lon": 9.0, "dist_m": 100},
            {"corner_id": 2, "label": "T2", "lat": 45.1, "lon": 9.1, "dist_m": 200},
        ]
        from web.routes.api_v1_data import _validate_key_corners
        valid, error = _validate_key_corners(corners)
        assert not valid
        assert "3 and 8" in error

    def test_put_rejects_more_than_8_corners(self):
        corners = [
            {"corner_id": i, "label": f"T{i}", "lat": 45.0, "lon": 9.0, "dist_m": i * 100}
            for i in range(1, 10)
        ]
        from web.routes.api_v1_data import _validate_key_corners
        valid, error = _validate_key_corners(corners)
        assert not valid
        assert "3 and 8" in error

    def test_put_non_destructive_upsert(self):
        """Label-only update preserves existing lat/lon/dist_m."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO track_key_corners (track_id, corner_id, label, lat, lon, dist_m) "
            "VALUES ('t1', 1, 'Old Label', 45.123, 9.456, 100.0)"
        )
        conn.commit()

        from web.routes.api_v1_data import _upsert_key_corners
        # Update label only, keeping same corner_id
        corners = [
            {"corner_id": 1, "label": "New Label", "lat": 45.123, "lon": 9.456, "dist_m": 100.0},
            {"corner_id": 2, "label": "T2", "lat": 45.2, "lon": 9.2, "dist_m": 200.0},
            {"corner_id": 3, "label": "T3", "lat": 45.3, "lon": 9.3, "dist_m": 300.0},
        ]
        _upsert_key_corners(conn, "t1", corners)

        row = conn.execute(
            "SELECT * FROM track_key_corners WHERE track_id = 't1' AND corner_id = 1"
        ).fetchone()
        row = dict(row)
        assert row["label"] == "New Label"
        assert abs(row["lat"] - 45.123) < 0.001
```

**Step 2: Run tests to verify they fail**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_corner_replay_api.py::TestKeyCornersCRUD -v --tb=short`
Expected: FAIL — cannot import helpers

**Step 3: Implement helpers + endpoints**

Add to `api_v1_data.py` after the corner replay endpoint:

```python
def _get_key_corners(conn, track_id: str) -> list:
    """Fetch key corners for a track, sorted by dist_m."""
    try:
        rows = conn.execute(
            "SELECT corner_id, label, lat, lon, dist_m "
            "FROM track_key_corners WHERE track_id = :tid ORDER BY dist_m",
            {"tid": track_id},
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "corner_id": (dict(r) if not isinstance(r, dict) else r)["corner_id"],
            "label": (dict(r) if not isinstance(r, dict) else r).get("label"),
            "lat": (dict(r) if not isinstance(r, dict) else r).get("lat"),
            "lon": (dict(r) if not isinstance(r, dict) else r).get("lon"),
            "dist_m": (dict(r) if not isinstance(r, dict) else r).get("dist_m"),
        }
        for r in rows
    ]


def _validate_key_corners(corners: list) -> tuple:
    """Validate corner count. Returns (valid: bool, error: str | None)."""
    if len(corners) < 3 or len(corners) > 8:
        return False, "Must select between 3 and 8 corners"
    return True, None


def _upsert_key_corners(conn, track_id: str, corners: list) -> None:
    """Non-destructive upsert: insert or replace corners for a track."""
    for c in corners:
        conn.execute(
            """INSERT OR REPLACE INTO track_key_corners
               (track_id, corner_id, label, lat, lon, dist_m)
               VALUES (:tid, :cid, :label, :lat, :lon, :dist_m)""",
            {
                "tid": track_id,
                "cid": c["corner_id"],
                "label": c.get("label", f"C{c['corner_id']}"),
                "lat": c.get("lat"),
                "lon": c.get("lon"),
                "dist_m": c.get("dist_m"),
            },
        )
    conn.commit()


@bp.route("/tracks/<track_id>/key-corners", methods=["GET"])
@rate_limit(tier="read")
def v1_get_key_corners(track_id: str):
    """Return key corners for a track."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    corners = _get_key_corners(conn, track_id)
    return api_response({"corners": corners})


@bp.route("/tracks/<track_id>/key-corners", methods=["PUT"])
@rate_limit(tier="write")
def v1_put_key_corners(track_id: str):
    """Create or update key corners for a track (3-8 corners)."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)

    data = request.get_json(silent=True)
    if not data or "corners" not in data:
        return api_error(ErrorCode.VALIDATION, "Missing corners array", status=422)

    corners = data["corners"]
    valid, error = _validate_key_corners(corners)
    if not valid:
        return api_error(ErrorCode.VALIDATION, error, status=422)

    _upsert_key_corners(conn, track_id, corners)
    return api_response({"corners": _get_key_corners(conn, track_id)})
```

**Step 4: Run tests**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_corner_replay_api.py -v --tb=short`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_data.py telemetry_tool/tests/test_corner_replay_api.py
git commit -m "feat(api): add key corners GET/PUT endpoints with validation"
```

---

## Task 4: Frontend — TypeScript Types and API Client Methods

**Files:**
- Create: `lap-website/src/types/corner-replay.ts`
- Modify: `lap-website/src/lib/api-client.ts` (no changes needed — uses `api.get<T>()`)

**Step 1: Create the TypeScript types file**

Create `lap-website/src/types/corner-replay.ts`:

```typescript
/* Corner Replay — batch response types */

export interface CornerReplayCorner {
  corner_id: string;
  label: string;
  lat: number;
  lon: number;
  dist_m: number;
}

export interface CornerReplayLap {
  lap_number: number;
  lap_time_s: number | null;
}

export interface CornerReplayTrace {
  lat: number[];
  lon: number[];
  dist_m: number[];
  speed_mps: number[];
  accel_lat: number[];
  accel_lon: number[];
  brake?: number[];
  throttle?: number[];
  steering?: number[];
}

export interface ReplayWindow {
  lap_number: number;
  start_idx: number;
  end_idx: number;
  estimated_duration_s: number;
}

export interface CornerMetric {
  lap_number: number;
  brake_point_m: number | null;
  entry_speed_mps: number | null;
  apex_speed_mps: number | null;
  exit_speed_mps: number | null;
  time_loss_ms: number | null;
  coaching_hint: string | null;
}

export interface CornerReplayData {
  session_id: string;
  track_id: string;
  has_pedal_data: boolean;
  has_steering_data: boolean;
  corners: CornerReplayCorner[];
  laps: CornerReplayLap[];
  traces: Record<string, CornerReplayTrace>;
  replay_windows: Record<string, ReplayWindow[]>;
  corner_metrics: Record<string, CornerMetric[]>;
}

/* Orchestrator state */

export type ReplayMode = 'review' | 'split' | 'top3';
export type PlaybackSpeed = 0.25 | 0.5 | 1 | 2;

export interface ReplayState {
  mode: ReplayMode;
  cornerIndex: number;
  lapA: number;
  lapB: number;
  frame: number;
  playing: boolean;
  speed: PlaybackSpeed;
}

export type ReplayAction =
  | { type: 'SET_MODE'; mode: ReplayMode }
  | { type: 'SET_CORNER'; index: number }
  | { type: 'NEXT_CORNER'; total: number }
  | { type: 'PREV_CORNER'; total: number }
  | { type: 'SET_LAP_A'; lap: number }
  | { type: 'SET_LAP_B'; lap: number }
  | { type: 'SET_FRAME'; frame: number }
  | { type: 'TOGGLE_PLAY' }
  | { type: 'SET_SPEED'; speed: PlaybackSpeed };
```

**Step 2: Verify no TypeScript errors**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty src/types/corner-replay.ts 2>&1 | head -20`
Expected: No errors

**Step 3: Commit**

```bash
cd lap-website
git add src/types/corner-replay.ts
git commit -m "feat: add TypeScript types for corner replay batch response"
```

---

## Task 5: Frontend — Replay State Reducer

**Files:**
- Create: `lap-website/src/components/app/corner-replay/replayReducer.ts`

**Step 1: Create the reducer**

```typescript
import type { ReplayState, ReplayAction, PlaybackSpeed } from '@/types/corner-replay';

const SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2];

export const initialReplayState: ReplayState = {
  mode: 'review',
  cornerIndex: 0,
  lapA: 1,
  lapB: 2,
  frame: 0,
  playing: false,
  speed: 1,
};

export function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  switch (action.type) {
    case 'SET_MODE':
      return { ...state, mode: action.mode, frame: 0, playing: false };
    case 'SET_CORNER':
      return { ...state, cornerIndex: action.index, frame: 0, playing: false };
    case 'NEXT_CORNER':
      return {
        ...state,
        cornerIndex: (state.cornerIndex + 1) % action.total,
        frame: 0,
        playing: false,
      };
    case 'PREV_CORNER':
      return {
        ...state,
        cornerIndex: (state.cornerIndex - 1 + action.total) % action.total,
        frame: 0,
        playing: false,
      };
    case 'SET_LAP_A':
      return { ...state, lapA: action.lap, frame: 0, playing: false };
    case 'SET_LAP_B':
      return { ...state, lapB: action.lap, frame: 0, playing: false };
    case 'SET_FRAME':
      return { ...state, frame: action.frame };
    case 'TOGGLE_PLAY':
      return { ...state, playing: !state.playing };
    case 'SET_SPEED':
      return { ...state, speed: action.speed };
    default:
      return state;
  }
}
```

**Step 2: Verify no TypeScript errors**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty src/components/app/corner-replay/replayReducer.ts 2>&1`
Expected: No errors

**Step 3: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/replayReducer.ts
git commit -m "feat: add replay state reducer with mode/corner/frame management"
```

---

## Task 6: Frontend — Rewrite CornerReplayControls

**Files:**
- Modify: `lap-website/src/components/app/corner-replay/CornerReplayControls.tsx`

**Step 1: Rewrite the controls component**

Replace the entire file with:

```typescript
'use client';

import type { ReplayMode, PlaybackSpeed, CornerReplayCorner } from '@/types/corner-replay';

interface CornerReplayControlsProps {
  mode: ReplayMode;
  corners: CornerReplayCorner[];
  cornerIndex: number;
  laps: Array<{ lap_number: number; lap_time_s: number | null }>;
  lapA: number;
  lapB: number;
  frame: number;
  totalFrames: number;
  playing: boolean;
  speed: PlaybackSpeed;
  onModeChange: (mode: ReplayMode) => void;
  onCornerChange: (index: number) => void;
  onPrevCorner: () => void;
  onNextCorner: () => void;
  onLapAChange: (lap: number) => void;
  onLapBChange: (lap: number) => void;
  onScrub: (frame: number) => void;
  onTogglePlay: () => void;
  onSpeedChange: (speed: PlaybackSpeed) => void;
}

const MODES: { value: ReplayMode; label: string }[] = [
  { value: 'review', label: 'Review' },
  { value: 'split', label: 'Split' },
  { value: 'top3', label: 'Top 3' },
];

const SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2];

export function CornerReplayControls({
  mode,
  corners,
  cornerIndex,
  laps,
  lapA,
  lapB,
  frame,
  totalFrames,
  playing,
  speed,
  onModeChange,
  onCornerChange,
  onPrevCorner,
  onNextCorner,
  onLapAChange,
  onLapBChange,
  onScrub,
  onTogglePlay,
  onSpeedChange,
}: CornerReplayControlsProps) {
  const progress = totalFrames > 1 ? frame / (totalFrames - 1) : 0;

  return (
    <div className="space-y-3">
      {/* Mode tabs */}
      <div className="flex items-center gap-1">
        {MODES.map((m) => (
          <button
            key={m.value}
            onClick={() => onModeChange(m.value)}
            className={`px-3 py-1.5 rounded text-xs font-telemetry transition-colors ${
              mode === m.value
                ? 'bg-acid-green/20 text-acid-green'
                : 'text-steel hover:text-chalk hover:bg-white/5'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Corner pills + navigation */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={onPrevCorner}
          className="w-7 h-7 flex items-center justify-center rounded bg-steel/10 text-steel hover:text-chalk transition-colors text-sm"
          aria-label="Previous corner"
        >
          &larr;
        </button>
        <div className="flex gap-1 flex-wrap">
          {corners.map((c, i) => (
            <button
              key={c.corner_id}
              onClick={() => onCornerChange(i)}
              className={`min-w-[28px] h-7 px-1.5 rounded text-xs font-telemetry transition-colors ${
                cornerIndex === i
                  ? 'bg-acid-green text-carbon font-bold'
                  : 'bg-steel/10 text-steel hover:text-chalk'
              }`}
              title={c.label}
            >
              {c.label || `C${c.corner_id}`}
            </button>
          ))}
        </div>
        <button
          onClick={onNextCorner}
          className="w-7 h-7 flex items-center justify-center rounded bg-steel/10 text-steel hover:text-chalk transition-colors text-sm"
          aria-label="Next corner"
        >
          &rarr;
        </button>
      </div>

      {/* Lap selectors (Split mode) */}
      {mode === 'split' && (
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-xs">
            <span className="text-acid-green font-telemetry">Lap A</span>
            <select
              value={lapA}
              onChange={(e) => onLapAChange(Number(e.target.value))}
              className="rounded border border-steel/20 bg-asphalt px-2 py-1 text-xs text-chalk font-telemetry"
            >
              {laps.map((l) => (
                <option key={l.lap_number} value={l.lap_number}>
                  Lap {l.lap_number}{l.lap_time_s ? ` (${l.lap_time_s.toFixed(2)}s)` : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs">
            <span className="text-safety-red font-telemetry">Lap B</span>
            <select
              value={lapB}
              onChange={(e) => onLapBChange(Number(e.target.value))}
              className="rounded border border-steel/20 bg-asphalt px-2 py-1 text-xs text-chalk font-telemetry"
            >
              {laps.map((l) => (
                <option key={l.lap_number} value={l.lap_number}>
                  Lap {l.lap_number}{l.lap_time_s ? ` (${l.lap_time_s.toFixed(2)}s)` : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {/* Scrubber + play controls */}
      <div className="bg-concrete rounded-lg border border-steel/20 px-4 py-3">
        {/* Progress bar */}
        <div className="mb-3">
          <div className="relative h-1.5 bg-asphalt rounded-full overflow-hidden cursor-pointer group">
            <div
              className="absolute inset-y-0 left-0 bg-acid-green rounded-full transition-[width] duration-75"
              style={{ width: `${progress * 100}%` }}
            />
            <input
              type="range"
              min={0}
              max={Math.max(totalFrames - 1, 0)}
              value={frame}
              onChange={(e) => onScrub(parseInt(e.target.value, 10))}
              className="absolute inset-0 w-full opacity-0 cursor-pointer"
              aria-label="Replay scrubber"
            />
            <div
              className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-acid-green rounded-full border-2 border-concrete opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
              style={{ left: `calc(${progress * 100}% - 6px)` }}
            />
          </div>
        </div>

        {/* Controls row */}
        <div className="flex items-center justify-between gap-4">
          {/* Play/pause */}
          <button
            onClick={onTogglePlay}
            className="w-8 h-8 flex items-center justify-center rounded-md bg-asphalt hover:bg-steel/20 transition-colors text-chalk"
            aria-label={playing ? 'Pause' : 'Play'}
          >
            {playing ? (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <rect x="2" y="1" width="3.5" height="12" rx="0.5" />
                <rect x="8.5" y="1" width="3.5" height="12" rx="0.5" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <path d="M3 1.5v11l9-5.5z" />
              </svg>
            )}
          </button>

          <span className="font-telemetry text-[10px] text-steel/60 tabular-nums">
            F{frame + 1}/{totalFrames}
          </span>

          {/* Speed selector */}
          <div className="flex items-center gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => onSpeedChange(s)}
                className={`px-2 py-1 rounded text-xs font-telemetry transition-colors ${
                  speed === s
                    ? 'bg-acid-green/20 text-acid-green'
                    : 'text-steel hover:text-chalk'
                }`}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify no TypeScript errors**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | grep -i "CornerReplayControls" | head -5`
Expected: No errors (or only from files importing old interface — those will be fixed in Task 8)

**Step 3: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/CornerReplayControls.tsx
git commit -m "feat: rewrite CornerReplayControls with mode tabs, corner pills, lap selectors"
```

---

## Task 7: Frontend — Extend CornerReplayCockpit for Conditional Rendering

**Files:**
- Modify: `lap-website/src/components/app/corner-replay/CornerReplayCockpit.tsx`

**Step 1: Update the CockpitFrame interface and draw function**

Read the current file first. Then modify:

1. Update the `CockpitFrame` interface to add optional fields:

```typescript
export interface CockpitFrame {
  speed: number;       // km/h
  gLat: number;        // lateral g
  gLon: number;        // longitudinal g
  throttle?: number;   // 0-1, optional
  brake?: number;      // 0-1, optional
  steeringAngle?: number; // degrees, optional
}
```

2. Add `hasPedalData` and `hasSteeringData` props:

```typescript
interface CornerReplayCockpitProps {
  frame: CockpitFrame;
  hasPedalData: boolean;
  hasSteeringData: boolean;
}
```

3. In the draw function, wrap the throttle/brake bars rendering (lines ~211-250) in:

```typescript
if (hasPedalData) {
  // ... existing throttle + brake bar code ...
}
```

4. Wrap the steering arc rendering (lines ~252-294) in:

```typescript
if (hasSteeringData) {
  // ... existing steering arc code ...
}
```

5. Adjust layout proportions when sections are hidden (the speedometer and G-ball take more space).

**Step 2: Verify no TypeScript errors**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | grep "Cockpit" | head -5`

**Step 3: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/CornerReplayCockpit.tsx
git commit -m "feat: conditional pedal/steering rendering in cockpit based on data availability"
```

---

## Task 8: Frontend — Rewrite CornerReplayMap for Multi-Lap + Zoom/Pan

**Files:**
- Modify: `lap-website/src/components/app/corner-replay/CornerReplayMap.tsx`

**Step 1: Rewrite the map component**

Replace the entire file. The new version must support:

1. **Three render modes** based on `mode` prop:
   - `review`: single lap trace (acid-green) + corner marker dots + current position dot
   - `split`: lap A (acid-green) + lap B (safety-red) + delta time badge
   - `top3`: 3 fastest laps (gold #FFD700, silver #C0C0C0, bronze #CD7F32)

2. **Zoom/pan** via `useInteractiveCanvas` hook (already has drag support):
   - Add `wheel` event for zoom
   - `onDoubleClick` resets to fit-all view
   - Store `zoomLevel` and `panOffset` in local state

3. **Canvas safety**:
   - `Math.max(0, radius)` on all `arc()` calls
   - Skip draw if `canvas.width < 10`
   - `Number.isFinite()` guards before drawing

4. **Props interface**:

```typescript
interface CornerReplayMapProps {
  mode: ReplayMode;
  traces: Record<string, CornerReplayTrace>;
  corners: CornerReplayCorner[];
  cornerIndex: number;
  lapA: number;
  lapB: number;
  frame: number;
  replayWindow: ReplayWindow | null;
}
```

5. **ResizeObserver**: Already handled by `useInteractiveCanvas`

**Step 2: Verify no TypeScript errors**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | grep "Map" | head -5`

**Step 3: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/CornerReplayMap.tsx
git commit -m "feat: rewrite CornerReplayMap with zoom/pan, multi-lap, 3 render modes"
```

---

## Task 9: Frontend — Corner Metrics Panel

**Files:**
- Create: `lap-website/src/components/app/corner-replay/CornerMetricsPanel.tsx`

**Step 1: Create the panel component**

```typescript
'use client';

import type { CornerMetric, CornerReplayCorner } from '@/types/corner-replay';

interface CornerMetricsPanelProps {
  corner: CornerReplayCorner;
  metrics: CornerMetric[];
  selectedLap: number;
}

function mpsToKph(mps: number | null): string {
  if (mps == null) return '--';
  return `${(mps * 3.6).toFixed(1)} km/h`;
}

export function CornerMetricsPanel({ corner, metrics, selectedLap }: CornerMetricsPanelProps) {
  const lapMetric = metrics.find((m) => m.lap_number === selectedLap);

  return (
    <div className="rounded-lg border border-steel/20 bg-concrete p-4">
      <h3 className="font-telemetry text-xs font-bold text-chalk mb-3">
        {corner.label || `Corner ${corner.corner_id}`}
      </h3>

      {!lapMetric ? (
        <p className="text-steel text-xs font-telemetry">No metrics for this lap</p>
      ) : (
        <div className="space-y-3">
          {/* Speed metrics */}
          <div className="grid grid-cols-3 gap-2">
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Entry</p>
              <p className="text-chalk font-telemetry text-sm">{mpsToKph(lapMetric.entry_speed_mps)}</p>
            </div>
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Apex</p>
              <p className="text-chalk font-telemetry text-sm">{mpsToKph(lapMetric.apex_speed_mps)}</p>
            </div>
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Exit</p>
              <p className="text-chalk font-telemetry text-sm">{mpsToKph(lapMetric.exit_speed_mps)}</p>
            </div>
          </div>

          {/* Brake point + time loss */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Brake</p>
              <p className="text-chalk font-telemetry text-sm">
                {lapMetric.brake_point_m != null ? `${lapMetric.brake_point_m.toFixed(0)}m` : '--'}
              </p>
            </div>
            <div>
              <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Time Loss</p>
              <p className={`font-telemetry text-sm ${
                (lapMetric.time_loss_ms ?? 0) > 100 ? 'text-safety-red' :
                (lapMetric.time_loss_ms ?? 0) > 50 ? 'text-amber-400' : 'text-acid-green'
              }`}>
                {lapMetric.time_loss_ms != null ? `+${lapMetric.time_loss_ms.toFixed(0)}ms` : '--'}
              </p>
            </div>
          </div>

          {/* Coaching hint */}
          {lapMetric.coaching_hint && (
            <div className="mt-2 rounded bg-acid-green/5 border border-acid-green/20 px-3 py-2">
              <p className="text-acid-green font-telemetry text-xs">{lapMetric.coaching_hint}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify no TypeScript errors**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | grep "MetricsPanel" | head -5`

**Step 3: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/CornerMetricsPanel.tsx
git commit -m "feat: add CornerMetricsPanel with speed metrics, time loss, coaching hints"
```

---

## Task 10: Frontend — Rewrite CornerReplayOrchestrator

**Files:**
- Modify: `lap-website/src/components/app/corner-replay/CornerReplay.tsx`

**Step 1: Rewrite as orchestrator**

Replace the entire file. This is the main component that:

1. **Fetches batch data** via `useQuery`:
```typescript
const { data, error, isLoading } = useQuery({
  queryKey: ['corner-replay', sessionId],
  queryFn: () => api.get<CornerReplayData>(`/sessions/${sessionId}/corner-replay`),
  enabled: !!sessionId,
});
```

2. **Manages state** via `useReducer(replayReducer, initialReplayState)`

3. **Runs single rAF loop** that advances frame based on speed:
```typescript
const animate = useCallback((timestamp: number) => {
  if (!state.playing) return;
  // Advance frame based on elapsed time and speed
  // Clamp to replay window bounds
  dispatch({ type: 'SET_FRAME', frame: nextFrame });
  rafRef.current = requestAnimationFrame(animate);
}, [state.playing, state.speed, /* window bounds */]);
```

4. **Registers keyboard shortcuts** via `useEffect` on `keydown`:
   - Space → TOGGLE_PLAY
   - ArrowLeft → PREV_CORNER
   - ArrowRight → NEXT_CORNER
   - `[` → decrease speed
   - `]` → increase speed

5. **Derives current frame data** from state + cached batch data and passes to children

6. **Renders error states** for 409/422/404/network errors

7. **Props**: `sessionId: string` (that's all — everything else is internal)

8. **Layout**: Map + Cockpit side by side, Controls below, MetricsPanel to the right

**Step 2: Update the barrel export**

Update `lap-website/src/components/app/corner-replay/index.ts`:

```typescript
export { CornerReplay } from './CornerReplay';
export { CornerReplayMap } from './CornerReplayMap';
export { CornerReplayCockpit } from './CornerReplayCockpit';
export { CornerReplayControls } from './CornerReplayControls';
export { CornerMetricsPanel } from './CornerMetricsPanel';
```

**Step 3: Verify no TypeScript errors**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | grep "corner-replay" | head -10`

**Step 4: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/
git commit -m "feat: rewrite CornerReplay as orchestrator with useReducer, rAF loop, keyboard shortcuts"
```

---

## Task 11: Frontend — Update Sessions Page Integration

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx:1076-1214`

**Step 1: Simplify the Corners & Coaching tab**

Replace the Corner Replay section (lines ~1128-1169) with:

```tsx
{/* Corner Replay (full width) */}
<section>
  <h3 className="font-body text-chalk text-lg font-semibold mb-4 mt-2">Corner Replay</h3>
  <div className="bg-concrete rounded-lg border border-steel/10 p-4 min-h-[400px]">
    <CornerReplay sessionId={id} />
  </div>
</section>
```

Remove the old corner pill navigation + prev/next buttons from the session page (the orchestrator now owns all that UI).

Remove the old `selectedCorner` state and `cornerId` prop. The new `CornerReplay` only takes `sessionId`.

Update the import at the top of the file to use the new export.

**Step 2: Verify the page builds**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | grep "sessions" | head -10`

**Step 3: Commit**

```bash
cd lap-website
git add src/app/app/sessions/[id]/page.tsx
git commit -m "feat: integrate new CornerReplay orchestrator in session detail page"
```

---

## Task 12: Frontend — Test Fixtures

**Files:**
- Create: `lap-website/src/components/app/corner-replay/__tests__/fixtures.ts`

**Step 1: Create shared test fixtures**

```typescript
import type { CornerReplayData } from '@/types/corner-replay';

function generateTrace(n: number, withPedals: boolean) {
  const lat = Array.from({ length: n }, (_, i) => 45.0 + i * 0.0001);
  const lon = Array.from({ length: n }, (_, i) => 9.0 + i * 0.0001);
  const dist_m = Array.from({ length: n }, (_, i) => i * 5);
  const speed_mps = Array.from({ length: n }, (_, i) => 15 + (i % 20) * 0.5);
  const accel_lat = Array.from({ length: n }, (_, i) => 0.1 * (i % 10 - 5));
  const accel_lon = Array.from({ length: n }, (_, i) => 0.05 * (i % 8 - 4));

  const trace: Record<string, number[]> = {
    lat, lon, dist_m, speed_mps, accel_lat, accel_lon,
  };

  if (withPedals) {
    trace.brake = Array.from({ length: n }, (_, i) => (i % 30 < 10 ? 0.8 : 0));
    trace.throttle = Array.from({ length: n }, (_, i) => (i % 30 >= 15 ? 0.9 : 0.1));
    trace.steering = Array.from({ length: n }, (_, i) => Math.sin(i / 10) * 45);
  }

  return trace;
}

export const mockCornerReplayResponse: CornerReplayData = {
  session_id: 'sess-001',
  track_id: 'track-001',
  has_pedal_data: true,
  has_steering_data: true,
  corners: [
    { corner_id: '1', label: 'Turn 1', lat: 45.005, lon: 9.005, dist_m: 100 },
    { corner_id: '2', label: 'Hairpin', lat: 45.010, lon: 9.010, dist_m: 500 },
    { corner_id: '3', label: 'Chicane', lat: 45.015, lon: 9.015, dist_m: 800 },
  ],
  laps: [
    { lap_number: 1, lap_time_s: 61.0 },
    { lap_number: 2, lap_time_s: 60.5 },
  ],
  traces: {
    '1': generateTrace(200, true) as any,
    '2': generateTrace(200, true) as any,
  },
  replay_windows: {
    '1': [
      { lap_number: 1, start_idx: 0, end_idx: 60, estimated_duration_s: 4.5 },
      { lap_number: 2, start_idx: 0, end_idx: 60, estimated_duration_s: 4.3 },
    ],
    '2': [
      { lap_number: 1, start_idx: 80, end_idx: 140, estimated_duration_s: 5.2 },
      { lap_number: 2, start_idx: 80, end_idx: 140, estimated_duration_s: 5.0 },
    ],
    '3': [
      { lap_number: 1, start_idx: 140, end_idx: 199, estimated_duration_s: 4.8 },
      { lap_number: 2, start_idx: 140, end_idx: 199, estimated_duration_s: 4.6 },
    ],
  },
  corner_metrics: {
    '1': [
      { lap_number: 1, brake_point_m: 90, entry_speed_mps: 20, apex_speed_mps: 15, exit_speed_mps: 18, time_loss_ms: 50, coaching_hint: null },
      { lap_number: 2, brake_point_m: 92, entry_speed_mps: 21, apex_speed_mps: 16, exit_speed_mps: 19, time_loss_ms: 30, coaching_hint: 'Brake later into Turn 1' },
    ],
    '2': [
      { lap_number: 1, brake_point_m: 490, entry_speed_mps: 22, apex_speed_mps: 12, exit_speed_mps: 16, time_loss_ms: 80, coaching_hint: null },
      { lap_number: 2, brake_point_m: 492, entry_speed_mps: 23, apex_speed_mps: 13, exit_speed_mps: 17, time_loss_ms: 60, coaching_hint: 'Carry more speed through Hairpin' },
    ],
    '3': [
      { lap_number: 1, brake_point_m: 790, entry_speed_mps: 18, apex_speed_mps: 14, exit_speed_mps: 17, time_loss_ms: 40, coaching_hint: null },
      { lap_number: 2, brake_point_m: 792, entry_speed_mps: 19, apex_speed_mps: 15, exit_speed_mps: 18, time_loss_ms: 25, coaching_hint: null },
    ],
  },
};

export const mockCornerReplayNoPedals: CornerReplayData = {
  ...mockCornerReplayResponse,
  has_pedal_data: false,
  has_steering_data: false,
  traces: {
    '1': generateTrace(200, false) as any,
    '2': generateTrace(200, false) as any,
  },
};

export const mockKeyCorners = [
  { corner_id: 1, label: 'Turn 1', lat: 45.005, lon: 9.005, dist_m: 100 },
  { corner_id: 2, label: 'Hairpin', lat: 45.010, lon: 9.010, dist_m: 500 },
  { corner_id: 3, label: 'Chicane', lat: 45.015, lon: 9.015, dist_m: 800 },
  { corner_id: 4, label: 'Final', lat: 45.018, lon: 9.018, dist_m: 950 },
];
```

**Step 2: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/__tests__/fixtures.ts
git commit -m "test: add shared test fixtures for corner replay components"
```

---

## Task 13: Frontend — Component Tests (Vitest)

**Files:**
- Create: `lap-website/src/components/app/corner-replay/__tests__/CornerReplayControls.test.tsx`
- Create: `lap-website/src/components/app/corner-replay/__tests__/replayReducer.test.ts`

**Step 1: Write reducer tests**

```typescript
import { describe, it, expect } from 'vitest';
import { replayReducer, initialReplayState } from '../replayReducer';

describe('replayReducer', () => {
  it('SET_MODE resets frame and stops playing', () => {
    const state = { ...initialReplayState, frame: 50, playing: true };
    const next = replayReducer(state, { type: 'SET_MODE', mode: 'split' });
    expect(next.mode).toBe('split');
    expect(next.frame).toBe(0);
    expect(next.playing).toBe(false);
  });

  it('SET_CORNER resets frame and stops playing', () => {
    const state = { ...initialReplayState, frame: 50, playing: true };
    const next = replayReducer(state, { type: 'SET_CORNER', index: 2 });
    expect(next.cornerIndex).toBe(2);
    expect(next.frame).toBe(0);
    expect(next.playing).toBe(false);
  });

  it('NEXT_CORNER wraps around', () => {
    const state = { ...initialReplayState, cornerIndex: 2 };
    const next = replayReducer(state, { type: 'NEXT_CORNER', total: 3 });
    expect(next.cornerIndex).toBe(0);
  });

  it('PREV_CORNER wraps around', () => {
    const state = { ...initialReplayState, cornerIndex: 0 };
    const next = replayReducer(state, { type: 'PREV_CORNER', total: 3 });
    expect(next.cornerIndex).toBe(2);
  });

  it('TOGGLE_PLAY toggles playing', () => {
    const next = replayReducer(initialReplayState, { type: 'TOGGLE_PLAY' });
    expect(next.playing).toBe(true);
    const next2 = replayReducer(next, { type: 'TOGGLE_PLAY' });
    expect(next2.playing).toBe(false);
  });

  it('SET_SPEED changes speed', () => {
    const next = replayReducer(initialReplayState, { type: 'SET_SPEED', speed: 2 });
    expect(next.speed).toBe(2);
  });

  it('SET_FRAME sets frame', () => {
    const next = replayReducer(initialReplayState, { type: 'SET_FRAME', frame: 42 });
    expect(next.frame).toBe(42);
  });

  it('SET_LAP_A resets frame', () => {
    const state = { ...initialReplayState, frame: 50 };
    const next = replayReducer(state, { type: 'SET_LAP_A', lap: 3 });
    expect(next.lapA).toBe(3);
    expect(next.frame).toBe(0);
  });
});
```

**Step 2: Write controls component tests**

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CornerReplayControls } from '../CornerReplayControls';
import { mockCornerReplayResponse } from './fixtures';

const defaultProps = {
  mode: 'review' as const,
  corners: mockCornerReplayResponse.corners,
  cornerIndex: 0,
  laps: mockCornerReplayResponse.laps,
  lapA: 1,
  lapB: 2,
  frame: 0,
  totalFrames: 60,
  playing: false,
  speed: 1 as const,
  onModeChange: vi.fn(),
  onCornerChange: vi.fn(),
  onPrevCorner: vi.fn(),
  onNextCorner: vi.fn(),
  onLapAChange: vi.fn(),
  onLapBChange: vi.fn(),
  onScrub: vi.fn(),
  onTogglePlay: vi.fn(),
  onSpeedChange: vi.fn(),
};

describe('CornerReplayControls', () => {
  it('renders mode tabs', () => {
    render(<CornerReplayControls {...defaultProps} />);
    expect(screen.getByText('Review')).toBeDefined();
    expect(screen.getByText('Split')).toBeDefined();
    expect(screen.getByText('Top 3')).toBeDefined();
  });

  it('renders corner pills', () => {
    render(<CornerReplayControls {...defaultProps} />);
    expect(screen.getByText('Turn 1')).toBeDefined();
    expect(screen.getByText('Hairpin')).toBeDefined();
    expect(screen.getByText('Chicane')).toBeDefined();
  });

  it('hides lap selectors in review mode', () => {
    render(<CornerReplayControls {...defaultProps} mode="review" />);
    expect(screen.queryByText('Lap A')).toBeNull();
  });

  it('shows lap selectors in split mode', () => {
    render(<CornerReplayControls {...defaultProps} mode="split" />);
    expect(screen.getByText('Lap A')).toBeDefined();
    expect(screen.getByText('Lap B')).toBeDefined();
  });

  it('calls onModeChange when mode tab clicked', () => {
    const fn = vi.fn();
    render(<CornerReplayControls {...defaultProps} onModeChange={fn} />);
    fireEvent.click(screen.getByText('Split'));
    expect(fn).toHaveBeenCalledWith('split');
  });

  it('renders speed buttons', () => {
    render(<CornerReplayControls {...defaultProps} />);
    expect(screen.getByText('0.25x')).toBeDefined();
    expect(screen.getByText('1x')).toBeDefined();
    expect(screen.getByText('2x')).toBeDefined();
  });
});
```

**Step 3: Run the tests**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/components/app/corner-replay/__tests__/ --reporter=verbose 2>&1 | tail -30`
Expected: All tests PASS

**Step 4: Commit**

```bash
cd lap-website
git add src/components/app/corner-replay/__tests__/
git commit -m "test: add reducer and controls component tests for corner replay"
```

---

## Task 14: E2E — Corner Replay Playwright Tests

**Files:**
- Create: `lap-website/e2e/corner-replay.spec.ts`

**Step 1: Write E2E tests with mocked API**

```typescript
import { test, expect } from '@playwright/test';

const MOCK_CORNER_REPLAY = {
  session_id: 'sess-001',
  track_id: 'track-001',
  has_pedal_data: false,
  has_steering_data: false,
  corners: [
    { corner_id: '1', label: 'Turn 1', lat: 45.005, lon: 9.005, dist_m: 100 },
    { corner_id: '2', label: 'Hairpin', lat: 45.010, lon: 9.010, dist_m: 500 },
    { corner_id: '3', label: 'Chicane', lat: 45.015, lon: 9.015, dist_m: 800 },
  ],
  laps: [
    { lap_number: 1, lap_time_s: 61.0 },
    { lap_number: 2, lap_time_s: 60.5 },
  ],
  traces: {
    '1': {
      lat: Array.from({ length: 50 }, (_, i) => 45.0 + i * 0.0001),
      lon: Array.from({ length: 50 }, (_, i) => 9.0 + i * 0.0001),
      dist_m: Array.from({ length: 50 }, (_, i) => i * 20),
      speed_mps: Array.from({ length: 50 }, () => 18),
      accel_lat: Array.from({ length: 50 }, () => 0),
      accel_lon: Array.from({ length: 50 }, () => 0),
    },
    '2': {
      lat: Array.from({ length: 50 }, (_, i) => 45.0 + i * 0.0001),
      lon: Array.from({ length: 50 }, (_, i) => 9.0 + i * 0.0001),
      dist_m: Array.from({ length: 50 }, (_, i) => i * 20),
      speed_mps: Array.from({ length: 50 }, () => 19),
      accel_lat: Array.from({ length: 50 }, () => 0),
      accel_lon: Array.from({ length: 50 }, () => 0),
    },
  },
  replay_windows: {
    '1': [
      { lap_number: 1, start_idx: 0, end_idx: 30, estimated_duration_s: 4.0 },
      { lap_number: 2, start_idx: 0, end_idx: 30, estimated_duration_s: 3.8 },
    ],
    '2': [
      { lap_number: 1, start_idx: 20, end_idx: 49, estimated_duration_s: 5.0 },
      { lap_number: 2, start_idx: 20, end_idx: 49, estimated_duration_s: 4.8 },
    ],
    '3': [
      { lap_number: 1, start_idx: 35, end_idx: 49, estimated_duration_s: 3.0 },
      { lap_number: 2, start_idx: 35, end_idx: 49, estimated_duration_s: 2.9 },
    ],
  },
  corner_metrics: {
    '1': [
      { lap_number: 1, brake_point_m: 90, entry_speed_mps: 20, apex_speed_mps: 15, exit_speed_mps: 18, time_loss_ms: 50, coaching_hint: null },
    ],
    '2': [
      { lap_number: 1, brake_point_m: 490, entry_speed_mps: 22, apex_speed_mps: 12, exit_speed_mps: 16, time_loss_ms: 80, coaching_hint: 'Brake later' },
    ],
    '3': [
      { lap_number: 1, brake_point_m: 790, entry_speed_mps: 18, apex_speed_mps: 14, exit_speed_mps: 17, time_loss_ms: 40, coaching_hint: null },
    ],
  },
};

test.describe('Corner Replay', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    // Mock session details
    await page.route('**/api/v1/sessions/sess-001/details', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'sess-001', track_name: 'Test Track', driver_name: 'Test' }),
      });
    });

    // Mock corner replay batch
    await page.route('**/api/v1/sessions/sess-001/corner-replay', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_CORNER_REPLAY),
      });
    });

    // Mock other session endpoints
    await page.route('**/api/v1/sessions/sess-001/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: {} }),
      });
    });
  });

  test('corner replay tab loads and shows controls', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    // Click Corners & Coaching tab
    await page.getByRole('button', { name: 'Corners & Coaching' }).click();
    // Should show corner pills
    await expect(page.getByText('Turn 1')).toBeVisible();
    await expect(page.getByText('Hairpin')).toBeVisible();
  });

  test('mode switching updates UI', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: 'Corners & Coaching' }).click();
    // Switch to Split mode
    await page.getByText('Split').click();
    // Lap selectors should appear
    await expect(page.getByText('Lap A')).toBeVisible();
    await expect(page.getByText('Lap B')).toBeVisible();
  });

  test('corner pill navigation changes active corner', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: 'Corners & Coaching' }).click();
    // Click Hairpin
    await page.getByText('Hairpin').click();
    // Hairpin pill should be highlighted (has bg-acid-green class)
    const hairpinBtn = page.getByText('Hairpin');
    await expect(hairpinBtn).toHaveClass(/bg-acid-green/);
  });

  test('play/pause button toggles', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: 'Corners & Coaching' }).click();
    const playBtn = page.getByRole('button', { name: 'Play' });
    await expect(playBtn).toBeVisible();
    await playBtn.click();
    // Should now be Pause
    await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible();
  });

  test('shows error for 409 response', async ({ page }) => {
    // Override to return 409
    await page.route('**/api/v1/sessions/sess-001/corner-replay', async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, error: 'No key corners defined for this track' }),
      });
    });
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: 'Corners & Coaching' }).click();
    await expect(page.getByText(/No corners selected/i)).toBeVisible();
  });
});
```

**Step 2: Run E2E tests (dev server must be running)**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx playwright test e2e/corner-replay.spec.ts --reporter=list 2>&1 | tail -20`

**Step 3: Commit**

```bash
cd lap-website
git add e2e/corner-replay.spec.ts
git commit -m "test(e2e): add Playwright tests for corner replay with mocked API"
```

---

## Task 15: Build Verification & Final Cleanup

**Files:**
- No new files — verification only

**Step 1: Run full backend test suite**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests pass (including new corner replay tests)

**Step 2: Run frontend type check**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx tsc --noEmit --pretty 2>&1 | tail -20`
Expected: No errors in new files

**Step 3: Run frontend build**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build 2>&1 | tail -20`
Expected: Build succeeds with no chunk failures

**Step 4: Run Vitest**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run --reporter=verbose 2>&1 | tail -30`
Expected: All component tests pass

**Step 5: If any failures, fix and re-run. Then commit any fixes.**

```bash
git add -A
git commit -m "fix: resolve build/test issues from corner replay integration"
```
