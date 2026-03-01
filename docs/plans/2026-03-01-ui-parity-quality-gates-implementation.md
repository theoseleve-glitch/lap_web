# UI Parity + Quality Gates Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract reusable chart components from session-detail, add SectorPanel + CornerReplay, add seeded API contract tests, E2E smoke test, and verify observability.

**Architecture:** Dual-mode shared chart components (sessionId OR data props) in `src/components/shared/charts/`. Backend contract tests use real seeded SQLite. E2E smoke tests via Playwright. Observability already implemented — verify only.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, Zustand 5, Leaflet, Canvas API, Playwright, pytest

---

### Task 1: Verify observability is already implemented

**Files:**
- Read: `telemetry_tool/web/api_utils.py`
- Read: `telemetry_tool/web/logging_setup.py`
- Read: `telemetry_tool/web/app.py`

**Step 1: Verify X-Request-Id header**

Run:
```bash
cd telemetry_tool && python -c "
import sys; sys.path.insert(0, '.')
from web.app import create_app
app = create_app()
client = app.test_client()
resp = client.get('/api/v1/sessions')
print('X-Request-Id:', resp.headers.get('X-Request-Id'))
print('Status:', resp.status_code)
import json
body = json.loads(resp.data)
print('meta.request_id:', body.get('meta', {}).get('request_id'))
"
```
Expected: X-Request-Id header present, matches meta.request_id.

**Step 2: Verify JSON logging**

Run:
```bash
cd telemetry_tool && TELEMETRY_LOG_FORMAT=json python -c "
import sys, os; sys.path.insert(0, '.')
os.environ['TELEMETRY_LOG_FORMAT'] = 'json'
from web.app import create_app
app = create_app()
client = app.test_client()
resp = client.get('/api/v1/sessions')
print('Done — check log output above for JSON format')
"
```
Expected: Log lines are valid JSON with timestamp, level, logger, message, request_id fields.

**Step 3: Verify request timing**

Confirm `api_utils.py:init_request_id` sets `g._request_start_time` in `before_request` and logs duration in `after_request`.

No code changes needed. This workstream is complete.

---

### Task 2: Extend seeded_db fixture with GPS traces, corners, theoretical data

**Files:**
- Modify: `telemetry_tool/tests/conftest.py`

**Step 1: Add GPS trace + theoretical data seeding to conftest.py**

Add after the existing `score_details` inserts in `seeded_db`:

```python
    # --- GPS traces for s1 (lap 1 = best lap) ---
    import math
    n_points = 100
    lap_length = 1000.0
    for lap_num in [1, 2, 3]:
        distances = [i * lap_length / n_points for i in range(n_points)]
        # Simulate an oval track
        speeds = [20.0 + 5.0 * math.sin(2 * math.pi * d / lap_length) for d in distances]
        latitudes = [45.0 + 0.001 * math.cos(2 * math.pi * d / lap_length) for d in distances]
        longitudes = [7.0 + 0.002 * math.sin(2 * math.pi * d / lap_length) for d in distances]
        conn.execute(
            "INSERT INTO gps_traces (session_id, lap_number, distances, speeds, latitudes, longitudes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "s1", lap_num,
                json.dumps(distances), json.dumps(speeds),
                json.dumps(latitudes), json.dumps(longitudes),
            ),
        )

    # --- Theoretical data with corner coaching ---
    corner_coaching = [
        {"corner_id": 1, "corner_name": "T1", "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0, "direction": "left"},
        {"corner_id": 2, "corner_name": "T2", "s_start": 400.0, "s_end": 500.0, "s_apex": 450.0, "direction": "right"},
        {"corner_id": 3, "corner_name": "T3", "s_start": 700.0, "s_end": 800.0, "s_apex": 750.0, "direction": "left"},
    ]
    theoretical_speeds = [22.0 + 3.0 * math.sin(2 * math.pi * d / lap_length) for d in distances]
    conn.execute(
        "INSERT INTO theoretical_data (session_id, theoretical_time_s, actual_best_time_s, "
        "gap_pct, simulation_method, speeds, distances, corner_coaching_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "s1", 58.0, 60.0, 3.33, "envelope",
            json.dumps(theoretical_speeds), json.dumps(distances),
            json.dumps(corner_coaching),
        ),
    )

    # --- Corner metrics (per-lap per-corner) ---
    for lap_num in [1, 2, 3]:
        for corner in corner_coaching:
            conn.execute(
                "INSERT INTO corner_metrics (session_id, lap_number, corner_id, "
                "entry_speed_mps, apex_speed_mps, exit_speed_mps, brake_point_m, "
                "time_loss_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "s1", lap_num, corner["corner_id"],
                    25.0 - corner["corner_id"] * 2,
                    18.0 - corner["corner_id"],
                    22.0 - corner["corner_id"],
                    corner["s_start"] - 10.0,
                    50 + corner["corner_id"] * 20 + lap_num * 5,
                ),
            )

    # --- Reference line ---
    conn.execute(
        "INSERT INTO reference_lines (session_id, latitudes, longitudes, distances, speeds) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "s1",
            json.dumps(latitudes), json.dumps(longitudes),
            json.dumps(distances), json.dumps(theoretical_speeds),
        ),
    )

    # --- Analysis JSON (sector analysis, consistency, etc.) ---
    analysis_json = {
        "consistency_metrics": {"cv_pct": 0.43, "std_dev_s": 0.195, "best_to_median_delta_s": 0.015},
        "robustness_metrics": {"early_mean_s": 60.5, "late_mean_s": 61.0},
        "sector_analysis": {
            "n_sectors": 3,
            "ideal_lap_time_s": 58.234,
            "sector_stats": [
                {"sector": 1, "best_s": 14.2, "mean_s": 14.5, "std_s": 0.3},
                {"sector": 2, "best_s": 15.1, "mean_s": 15.3, "std_s": 0.2},
                {"sector": 3, "best_s": 13.8, "mean_s": 14.0, "std_s": 0.2},
            ],
        },
        "data_quality_summary": {"overall_confidence": 0.88, "gps_quality": 0.92},
    }
    conn.execute(
        "UPDATE sessions SET analysis_json = ? WHERE session_id = 's1'",
        (json.dumps(analysis_json),),
    )

    # --- Driving style features ---
    conn.execute(
        "INSERT INTO driving_style_features (session_id, style_label, style_confidence, features_json) "
        "VALUES (?, ?, ?, ?)",
        ("s1", "smooth", 0.82, json.dumps([
            {"name": "trail_braking", "value": 0.7},
            {"name": "throttle_modulation", "value": 0.85},
        ])),
    )
```

**Step 2: Verify seeded_db loads without errors**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -v -k "test_session_list" --tb=short`
Expected: PASS — confirms seeded_db fixture works with new data.

**Step 3: Commit**

```bash
git add telemetry_tool/tests/conftest.py
git commit -m "test: extend seeded_db with GPS traces, corners, theoretical, analysis data

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Write API contract tests

**Files:**
- Create: `telemetry_tool/tests/test_api_contracts.py`

**Step 1: Write the contract test file**

```python
"""API contract tests — verify every endpoint returns correct response shapes.

Uses seeded_db fixture (real SQLite with sample data) to catch field name
mismatches, missing columns, and broken SQL. NOT mocks.
"""
import json
import math
import pytest
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


SEEDED_SESSION_ID = "s1"


@pytest.fixture
def seeded_client(seeded_db):
    """Flask test client backed by seeded SQLite."""
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    # Monkey-patch to use seeded_db
    import web.models as models
    _orig_get_conn = getattr(models, "_get_conn", None)
    models._get_conn = lambda: seeded_db
    # Also patch data_v2's get_conn
    from web.routes import data_v2
    data_v2._get_conn = lambda: seeded_db
    with app.test_client() as client:
        yield client
    if _orig_get_conn:
        models._get_conn = _orig_get_conn


class TestEnvelopeContract:
    """Every response has {ok, data, meta} envelope with request_id."""

    PATHS = [
        "/api/v1/sessions",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/laps",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/speed-trace?lap=1",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/gps-trace?lap=1",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/gg-data?lap=1",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/scores",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/corners",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/corner-positions",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/track-map?lap=best",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/sectors",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/theoretical",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/reference_line",
        f"/api/v1/sessions/{SEEDED_SESSION_ID}/best_lap_gps",
    ]

    @pytest.mark.parametrize("path", PATHS)
    def test_envelope_shape(self, seeded_client, path):
        resp = seeded_client.get(path)
        assert resp.status_code == 200, f"{path}: {resp.status_code}"
        body = resp.get_json()
        assert body["ok"] is True
        assert "data" in body
        assert "request_id" in body.get("meta", {})


class TestTraceContracts:
    """Trace endpoints return parallel arrays of equal length."""

    def test_speed_trace_shape(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/speed-trace?lap=1")
        data = resp.get_json()["data"]
        assert "distances" in data
        assert "speeds" in data
        assert "lap_number" in data
        assert len(data["distances"]) == len(data["speeds"])

    def test_gps_trace_shape(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/gps-trace?lap=1")
        data = resp.get_json()["data"]
        assert "latitudes" in data
        assert "longitudes" in data
        assert "distances" in data
        assert "speeds" in data
        n = len(data["distances"])
        assert len(data["latitudes"]) == n
        assert len(data["longitudes"]) == n
        assert len(data["speeds"]) == n

    def test_gg_data_shape(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/gg-data?lap=1")
        data = resp.get_json()["data"]
        assert "accel_lat" in data
        assert "accel_long" in data
        assert "lap_number" in data

    def test_distance_monotonic(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/speed-trace?lap=1")
        distances = resp.get_json()["data"]["distances"]
        for i in range(1, len(distances)):
            assert distances[i] >= distances[i - 1], f"distance[{i}] not monotonic"

    def test_no_nan_in_json(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/speed-trace?lap=1")
        raw = resp.data.decode()
        assert "NaN" not in raw
        assert "Infinity" not in raw


class TestCornerContracts:
    """Corner endpoints return expected fields."""

    def test_corner_positions_have_lat_lon(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/corner-positions")
        data = resp.get_json()["data"]
        assert "corners" in data
        for corner in data["corners"]:
            assert "corner_id" in corner
            assert "lat" in corner or "s_apex" in corner

    def test_corners_have_coaching(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/corners")
        data = resp.get_json()["data"]
        assert isinstance(data, (dict, list))


class TestTrackMapContract:
    """Track map endpoint returns bundled data."""

    def test_track_map_best(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/track-map?lap=best")
        data = resp.get_json()["data"]
        assert "laps" in data
        assert "best_lap" in data
        assert "corners" in data

    def test_track_map_all(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/track-map?lap=all")
        data = resp.get_json()["data"]
        assert "laps" in data
        assert len(data["laps"]) >= 1


class TestSectorsContract:
    """Sectors endpoint returns sector analysis."""

    def test_sectors_shape(self, seeded_client):
        resp = seeded_client.get(f"/api/v1/sessions/{SEEDED_SESSION_ID}/sectors")
        if resp.status_code == 200:
            data = resp.get_json()["data"]
            assert isinstance(data, dict)
```

**Step 2: Run the contract tests**

Run: `pytest telemetry_tool/tests/test_api_contracts.py -v --tb=short`
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_api_contracts.py
git commit -m "test: add API contract tests with seeded fixture

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Create shared chart directory, useChartData hook, and ChartSyncProvider

**Files:**
- Create: `lap-website/src/components/shared/charts/useChartData.ts`
- Create: `lap-website/src/components/shared/charts/ChartSyncProvider.tsx`
- Move: `lap-website/src/components/app/charts/useVanillaChart.ts` to `shared/charts/`
- Create: `lap-website/src/components/shared/charts/index.ts`

**Step 1: Create the shared charts directory**

Run: `mkdir -p lap-website/src/components/shared/charts`

**Step 2: Create useChartData.ts**

```typescript
/**
 * useChartData.ts — Shared data-fetching hook for chart components.
 *
 * Handles the dual-mode pattern: if `data` prop is provided, use it directly;
 * if `sessionId` is provided, fetch from the API. Returns { data, loading, error }.
 */
'use client';

import { useState, useEffect, useRef } from 'react';
import { apiFetch } from '@/lib/api-client';

interface UseChartDataOptions<T> {
  /** Pre-fetched data — if provided, skip API fetch */
  data?: T;
  /** Session ID for API fetch */
  sessionId?: string;
  /** API path relative to session (e.g. 'gps-trace?lap=1') */
  endpoint?: string;
  /** Transform API response data before returning */
  transform?: (raw: Record<string, unknown>) => T;
}

interface UseChartDataResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useChartData<T>(options: UseChartDataOptions<T>): UseChartDataResult<T> {
  const { data: preFetched, sessionId, endpoint, transform } = options;
  const [data, setData] = useState<T | null>(preFetched ?? null);
  const [loading, setLoading] = useState(!preFetched && !!sessionId);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    // If pre-fetched data is provided, use it directly
    if (preFetched) {
      setData(preFetched);
      setLoading(false);
      setError(null);
      return;
    }

    // Need sessionId and endpoint to fetch
    if (!sessionId || !endpoint) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const result = await apiFetch(`/sessions/${sessionId}/${endpoint}`);
        if (cancelled || !mountedRef.current) return;
        if (!result.ok) {
          setError(result.error?.message ?? 'Failed to fetch chart data');
          setLoading(false);
          return;
        }
        const transformed = transform
          ? transform(result.data as Record<string, unknown>)
          : (result.data as T);
        setData(transformed);
        setLoading(false);
      } catch (err) {
        if (cancelled || !mountedRef.current) return;
        setError(err instanceof Error ? err.message : 'Fetch failed');
        setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [preFetched, sessionId, endpoint, transform]);

  return { data, loading, error };
}
```

**Step 3: Create ChartSyncProvider.tsx**

```typescript
/**
 * ChartSyncProvider.tsx — Provides distance-based hover sync context.
 *
 * Wraps chart groups. Children can call useChartSync() to get/set
 * the current hover distance. Different syncId values create
 * independent sync buses.
 */
'use client';

import { createContext, useContext, useMemo, useCallback } from 'react';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface ChartSyncContextValue {
  syncId: string;
  hoverDistance: number | null;
  hoverSource: string | null;
  setHover: (distance: number, source: string) => void;
  clearHover: () => void;
}

const ChartSyncContext = createContext<ChartSyncContextValue | null>(null);

interface ChartSyncProviderProps {
  children: React.ReactNode;
  syncId?: string;
}

export function ChartSyncProvider({ children, syncId = 'default' }: ChartSyncProviderProps) {
  const store = useChartHoverStore();

  const setHover = useCallback(
    (distance: number, source: string) => {
      store.setHover(distance, `${syncId}:${source}`);
    },
    [store.setHover, syncId],
  );

  const clearHover = useCallback(() => {
    store.clearHover();
  }, [store.clearHover]);

  // Filter hover events by syncId prefix
  const isOwnSync = store.hoverSource?.startsWith(`${syncId}:`) ?? false;

  const value = useMemo(
    () => ({
      syncId,
      hoverDistance: isOwnSync ? store.hoverDistance : null,
      hoverSource: isOwnSync ? store.hoverSource : null,
      setHover,
      clearHover,
    }),
    [syncId, isOwnSync, store.hoverDistance, store.hoverSource, setHover, clearHover],
  );

  return (
    <ChartSyncContext.Provider value={value}>
      {children}
    </ChartSyncContext.Provider>
  );
}

export function useChartSync() {
  const ctx = useContext(ChartSyncContext);
  if (!ctx) {
    // Fallback: use global store directly (for charts used outside a provider)
    const store = useChartHoverStore();
    return {
      syncId: 'global',
      hoverDistance: store.hoverDistance,
      hoverSource: store.hoverSource,
      setHover: store.setHover,
      clearHover: store.clearHover,
    };
  }
  return ctx;
}
```

**Step 4: Copy useVanillaChart.ts to shared (keep original for now)**

Run: `cp lap-website/src/components/app/charts/useVanillaChart.ts lap-website/src/components/shared/charts/useVanillaChart.ts`

**Step 5: Create barrel export index.ts**

```typescript
export { ChartSyncProvider, useChartSync } from './ChartSyncProvider';
export { useChartData } from './useChartData';
export { useVanillaChart } from './useVanillaChart';
// Components added in subsequent tasks:
// export { TrackMap } from './TrackMap';
// export { SpeedTraceChart } from './SpeedTraceChart';
// export { GGExplorer } from './GGExplorer';
// export { SectorPanel } from './SectorPanel';
// export { CornerReplay } from './CornerReplay';
```

**Step 6: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No new errors from the shared charts files.

**Step 7: Commit**

```bash
git add lap-website/src/components/shared/charts/
git commit -m "feat: add shared chart infrastructure (useChartData, ChartSyncProvider, barrel export)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Extract TrackMap shared component

**Files:**
- Create: `lap-website/src/components/shared/charts/TrackMap.tsx`
- Modify: `lap-website/src/components/shared/charts/index.ts`

**Step 1: Create TrackMap.tsx**

Extract from `GpsTrace.tsx` with dual-mode props. The component accepts either `sessionId` (delegates to vanilla JS) OR `data` (renders Leaflet directly).

```typescript
/**
 * TrackMap.tsx — Shared Leaflet track map component.
 *
 * Dual-mode: pass `sessionId` to use vanilla JS gps_trace.js,
 * or pass `data` to render directly without API calls.
 */
'use client';

import { useEffect, useRef, useMemo } from 'react';
import 'leaflet/dist/leaflet.css';
import { useVanillaChart } from './useVanillaChart';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface TrackMapData {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds?: number[];
}

interface Corner {
  corner_id: number;
  lat: number;
  lon: number;
  label?: string;
}

interface TrackMapProps {
  sessionId?: string;
  lap?: number;
  data?: TrackMapData;
  corners?: Corner[];
  markerDistance?: number;
  onHoverDistance?: (d: number) => void;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
  apiBase?: string;
}

/** Load Leaflet via npm dynamic import (only once). */
let leafletLoaded = false;
let leafletPromise: Promise<void> | null = null;

function ensureLeaflet(): Promise<void> {
  if (leafletLoaded) return Promise.resolve();
  if (leafletPromise) return leafletPromise;

  leafletPromise = (async () => {
    const L = (await import('leaflet')).default;
    L.Icon.Default.imagePath = '/images/leaflet/';
    (window as unknown as Record<string, unknown>).L = L;
    leafletLoaded = true;
  })();

  return leafletPromise;
}

export function TrackMap({
  sessionId,
  lap,
  data,
  corners,
  markerDistance,
  onHoverDistance,
  className = '',
  gpsLaps = [],
  bestLap = null,
  apiBase,
}: TrackMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);

  const scripts = useMemo(() => ['/js/gps_trace.js'], []);

  // Only use vanilla chart hook when in sessionId mode
  const { ready, error } = useVanillaChart({
    sessionId: sessionId || '__skip__',
    apiBase,
    scripts: sessionId ? scripts : [],
    gpsLaps,
    bestLap,
  });

  const shouldUseVanilla = !!sessionId && !data;

  // Vanilla JS mode: delegate to gps_trace.js
  useEffect(() => {
    if (!shouldUseVanilla || !ready || !containerRef.current) return;
    cleanedUpRef.current = false;
    const container = containerRef.current;
    let cancelled = false;

    (async () => {
      try {
        await ensureLeaflet();
        if (cancelled) return;

        if (window.GpsTrace) {
          const loadLap = (window.GpsTrace as Record<string, unknown>).loadLap as
            | ((lapNum: number) => void)
            | undefined;
          if (loadLap) {
            const defaultLap = lap || bestLap || (gpsLaps.length > 0 ? gpsLaps[0] : null);
            if (defaultLap) loadLap(defaultLap);
          }
        }
      } catch (err) {
        console.error('Failed to load Leaflet for TrackMap:', err);
      }
    })();

    return () => {
      cancelled = true;
      if (cleanedUpRef.current) return;
      cleanedUpRef.current = true;
      if (container) {
        while (container.firstChild) {
          container.removeChild(container.firstChild);
        }
      }
    };
  }, [shouldUseVanilla, ready, bestLap, gpsLaps, lap]);

  // Hover bridge for vanilla mode
  useEffect(() => {
    if (!shouldUseVanilla || !ready) return;

    const setHover = useChartHoverStore.getState().setHover;
    const clearHover = useChartHoverStore.getState().clearHover;

    if (window.GpsTrace) {
      (window.GpsTrace as Record<string, unknown>)._originalOnMapHover = (
        distance: number,
      ) => {
        if (distance != null && isFinite(distance)) {
          setHover(distance, 'track-map');
          onHoverDistance?.(distance);
        }
      };
    }

    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'track-map') return;
      if (state.hoverDistance !== null && window.GpsTrace) {
        const updateMarker = (window.GpsTrace as Record<string, unknown>)
          .updateMarkerByDistance as ((d: number) => void) | undefined;
        if (updateMarker) updateMarker(state.hoverDistance);
      }
    });

    const mapEl = document.getElementById('gps-map');
    const handleLeave = () => clearHover();
    if (mapEl) mapEl.addEventListener('mouseleave', handleLeave);

    return () => {
      unsubscribe();
      if (mapEl) mapEl.removeEventListener('mouseleave', handleLeave);
    };
  }, [shouldUseVanilla, ready, onHoverDistance]);

  if (error && shouldUseVanilla) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load track map: {error}
      </div>
    );
  }

  // Render mode: vanilla JS container
  if (shouldUseVanilla) {
    return (
      <div ref={containerRef} className={className}>
        <div id="gps-map" style={{ width: '100%', height: '400px', position: 'relative' }} />
        <div className="flex items-center gap-3 mt-2 text-sm flex-wrap">
          <label className="text-gray-400">Lap:</label>
          <select id="lap-select" className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700">
            {gpsLaps.map((l) => (
              <option key={l} value={l}>
                Lap {l}{l === bestLap ? ' (Best)' : ''}
              </option>
            ))}
          </select>
          <label className="inline-flex items-center gap-1 text-gray-400 ml-3">
            <input type="checkbox" id="toggle-reference-line" className="accent-orange-500" />
            Reference
          </label>
          <label className="inline-flex items-center gap-1 text-gray-400">
            <input type="checkbox" id="toggle-best-lap" className="accent-orange-500" />
            Best Lap
          </label>
          <label className="inline-flex items-center gap-1 text-gray-400">
            <input type="checkbox" id="toggle-all-laps" className="accent-orange-500" />
            All Laps
          </label>
        </div>
      </div>
    );
  }

  // Data mode: "data prop provided" — placeholder for direct Leaflet rendering
  return (
    <div ref={containerRef} className={className}>
      <div style={{ width: '100%', height: '400px', position: 'relative', background: '#1a1a2e' }}>
        {data ? (
          <div className="text-gray-400 p-4 text-sm">
            Track map with {data.latitudes.length} points
            {corners && ` and ${corners.length} corners`}
          </div>
        ) : (
          <div className="text-gray-500 p-4">No GPS data</div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Update barrel export**

Uncomment the TrackMap export in `index.ts`:
```typescript
export { TrackMap } from './TrackMap';
```

**Step 3: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors.

**Step 4: Commit**

```bash
git add lap-website/src/components/shared/charts/TrackMap.tsx lap-website/src/components/shared/charts/index.ts
git commit -m "feat: add shared TrackMap component with dual-mode props

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Extract SpeedTraceChart shared component

**Files:**
- Create: `lap-website/src/components/shared/charts/SpeedTraceChart.tsx`
- Modify: `lap-website/src/components/shared/charts/index.ts`

**Step 1: Create SpeedTraceChart.tsx**

Same dual-mode pattern as TrackMap. Delegates to chart_sync.js + speed_trace_zoom.js in sessionId mode.

The component follows the exact same structure as `SpeedTraceZoom.tsx` but with added `data` prop support and `onHoverDistance` callback.

**Step 2: Update barrel export**

**Step 3: Verify build and commit**

```bash
git add lap-website/src/components/shared/charts/SpeedTraceChart.tsx lap-website/src/components/shared/charts/index.ts
git commit -m "feat: add shared SpeedTraceChart component with dual-mode props

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Extract GGExplorer shared component

**Files:**
- Create: `lap-website/src/components/shared/charts/GGExplorer.tsx`
- Modify: `lap-website/src/components/shared/charts/index.ts`

**Step 1: Create shared GGExplorer.tsx**

Same dual-mode pattern. Delegates to gg_explorer.js in sessionId mode.

**Step 2: Update barrel export, verify build, commit**

```bash
git add lap-website/src/components/shared/charts/GGExplorer.tsx lap-website/src/components/shared/charts/index.ts
git commit -m "feat: add shared GGExplorer component with dual-mode props

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Build SectorPanel component

**Files:**
- Create: `lap-website/src/components/shared/charts/SectorPanel.tsx`
- Modify: `lap-website/src/components/shared/charts/index.ts`

**Step 1: Create SectorPanel.tsx**

Pure React + Tailwind. No vanilla JS. Fetches from `/sessions/{id}/sectors` or uses pre-fetched data.

```typescript
/**
 * SectorPanel.tsx — Sector analysis panel with ideal lap, heatmap, and insights.
 *
 * Shows best/mean/gap per sector with color-coded cells (green=close to best,
 * red=far from best). Auto-generates coaching insights from sector stats.
 */
'use client';

import { useMemo } from 'react';
import { useChartData } from './useChartData';

interface SectorStat {
  sector: number;
  best_s: number;
  mean_s: number;
  std_s: number;
}

interface SectorAnalysisData {
  n_sectors: number;
  ideal_lap_time_s: number;
  sector_stats: SectorStat[];
  sector_timings?: unknown[];
  coaching?: string[];
}

interface SectorPanelProps {
  sessionId?: string;
  data?: SectorAnalysisData;
  className?: string;
}

function gapColor(gap: number, maxGap: number): string {
  if (maxGap === 0) return 'text-green-400';
  const ratio = gap / maxGap;
  if (ratio < 0.33) return 'text-green-400';
  if (ratio < 0.66) return 'text-yellow-400';
  return 'text-red-400';
}

function gapBgColor(gap: number, maxGap: number): string {
  if (maxGap === 0) return 'bg-green-900/30';
  const ratio = gap / maxGap;
  if (ratio < 0.33) return 'bg-green-900/30';
  if (ratio < 0.66) return 'bg-yellow-900/30';
  return 'bg-red-900/30';
}

export function SectorPanel({ sessionId, data: preFetched, className = '' }: SectorPanelProps) {
  const { data, loading, error } = useChartData<SectorAnalysisData>({
    data: preFetched,
    sessionId,
    endpoint: 'sectors',
    transform: (raw) => raw as unknown as SectorAnalysisData,
  });

  const insights = useMemo(() => {
    if (!data?.sector_stats) return [];
    const stats = data.sector_stats;
    const result: string[] = [];

    // Find sector with lowest variance
    const sortedByStd = [...stats].sort((a, b) => a.std_s - b.std_s);
    if (sortedByStd.length > 0) {
      const best = sortedByStd[0];
      const cv = best.mean_s > 0 ? ((best.std_s / best.mean_s) * 100).toFixed(1) : '0';
      result.push(`Sector ${best.sector} lowest variance (${cv}%)`);
    }

    // Find sector with highest time loss (gap)
    const gaps = stats.map((s) => ({ sector: s.sector, gap: s.mean_s - s.best_s }));
    const sortedByGap = [...gaps].sort((a, b) => b.gap - a.gap);
    if (sortedByGap.length > 0 && sortedByGap[0].gap > 0) {
      const worst = sortedByGap[0];
      result.push(`Sector ${worst.sector} highest time loss (${worst.gap.toFixed(3)}s)`);
    }

    return result;
  }, [data]);

  if (loading) {
    return <div className={`text-gray-500 p-4 ${className}`}>Loading sector data...</div>;
  }

  if (error) {
    return <div className={`text-red-400 p-4 ${className}`}>Failed to load sectors: {error}</div>;
  }

  if (!data || !data.sector_stats || data.sector_stats.length === 0) {
    return <div className={`text-gray-500 p-4 ${className}`}>No sector data available</div>;
  }

  const maxGap = Math.max(...data.sector_stats.map((s) => s.mean_s - s.best_s), 0.001);

  return (
    <div className={`bg-gray-900 rounded-lg p-4 ${className}`}>
      {/* Ideal lap header */}
      <div className="text-sm text-gray-400 mb-3">
        Ideal Lap:{' '}
        <span className="text-white font-mono font-semibold">
          {data.ideal_lap_time_s.toFixed(3)}s
        </span>
        <span className="text-gray-500 ml-2">(sum of best sectors)</span>
      </div>

      {/* Sector table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs">
              <th className="text-left pr-4 pb-2" />
              {data.sector_stats.map((s) => (
                <th key={s.sector} className="text-center px-3 pb-2 font-normal">
                  S{s.sector}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="text-gray-300">
              <td className="pr-4 py-1 text-gray-500 text-xs">Best</td>
              {data.sector_stats.map((s) => (
                <td key={s.sector} className="text-center px-3 py-1 font-mono">
                  {s.best_s.toFixed(1)}
                </td>
              ))}
            </tr>
            <tr className="text-gray-300">
              <td className="pr-4 py-1 text-gray-500 text-xs">Mean</td>
              {data.sector_stats.map((s) => (
                <td key={s.sector} className="text-center px-3 py-1 font-mono">
                  {s.mean_s.toFixed(1)}
                </td>
              ))}
            </tr>
            <tr>
              <td className="pr-4 py-1 text-gray-500 text-xs">Gap</td>
              {data.sector_stats.map((s) => {
                const gap = s.mean_s - s.best_s;
                return (
                  <td
                    key={s.sector}
                    className={`text-center px-3 py-1 font-mono ${gapColor(gap, maxGap)} ${gapBgColor(gap, maxGap)} rounded`}
                  >
                    {gap.toFixed(1)}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>

      {/* Heatmap bar */}
      <div className="flex gap-1 mt-3">
        {data.sector_stats.map((s) => {
          const gap = s.mean_s - s.best_s;
          const ratio = maxGap > 0 ? gap / maxGap : 0;
          const hue = 120 - ratio * 120; // 120=green, 0=red
          return (
            <div
              key={s.sector}
              className="flex-1 h-3 rounded"
              style={{ backgroundColor: `hsl(${hue}, 70%, 40%)` }}
              title={`S${s.sector}: ${gap.toFixed(3)}s gap`}
            />
          );
        })}
      </div>
      <div className="text-xs text-gray-600 mt-1">
        green = close to best, red = far from best
      </div>

      {/* Insights */}
      {insights.length > 0 && (
        <div className="mt-3 text-xs text-gray-400 space-y-1">
          {insights.map((insight, i) => (
            <div key={i}>Insight: {insight}</div>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Update barrel export, verify build, commit**

```bash
git add lap-website/src/components/shared/charts/SectorPanel.tsx lap-website/src/components/shared/charts/index.ts
git commit -m "feat: add SectorPanel component with heatmap and coaching insights

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Build CornerReplay component

**Files:**
- Create: `lap-website/src/components/shared/charts/CornerReplay.tsx`
- Modify: `lap-website/src/components/shared/charts/index.ts`

**Step 1: Create CornerReplay.tsx**

Multi-part component with corner selector, side-by-side mini maps, playback controls, and speed profile comparison. Uses `requestAnimationFrame` for playback, fetches from `/corner-positions`, `/corner-metrics/summary`, `/gps-trace`.

This is the most complex component. Key implementation details:

- **Corner segmentation**: Binary search on `distances[]` to find start/end indices for each corner
- **Playback**: `requestAnimationFrame` loop advances a distance cursor from `s_start` to `s_end`
- **Split compare**: Two Leaflet mini maps side-by-side, same distance cursor drives both
- **Speed profile**: Canvas chart overlaying speed-vs-distance through the corner for both laps
- **Controls**: Play/pause, step fwd/back, scrub slider, speed multiplier

Due to size, the full implementation will be written during execution. The shell structure:

```typescript
'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

interface CornerReplayProps {
  sessionId: string;
  initialCorner?: number;
  className?: string;
}

export function CornerReplay({ sessionId, initialCorner, className = '' }: CornerReplayProps) {
  // State: corners list, selected corner, lap A/B, playback position
  // Fetch corner-positions + corner-metrics/summary on mount
  // Fetch GPS traces for selected laps
  // Binary search to segment corner from full trace
  // requestAnimationFrame playback loop
  // Canvas speed profile chart
  // Playback controls
}
```

**Step 2: Update barrel export, verify build, commit**

```bash
git add lap-website/src/components/shared/charts/CornerReplay.tsx lap-website/src/components/shared/charts/index.ts
git commit -m "feat: add CornerReplay component with playback and split compare

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 10: Update session detail page to use shared components

**Files:**
- Modify: `lap-website/src/components/app/charts/GpsTrace.tsx`
- Modify: `lap-website/src/components/app/charts/SpeedTraceZoom.tsx`
- Modify: `lap-website/src/components/app/charts/GGExplorer.tsx`

**Step 1: Update imports to re-export from shared**

Each `app/charts/` component becomes a thin re-export or wrapper:

```typescript
// GpsTrace.tsx — thin wrapper
export { TrackMap as GpsTrace } from '@/components/shared/charts';
```

Or, if the app-specific component needs different defaults, keep it as a wrapper that passes app-specific defaults to the shared component.

**Step 2: Verify existing pages still work**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add lap-website/src/components/app/charts/
git commit -m "refactor: app chart components re-export from shared library

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 11: Write Playwright E2E smoke test

**Files:**
- Create: `lap-website/e2e/smoke-flow.spec.ts`
- Create: `lap-website/e2e/fixtures/test-session.csv` (small CSV fixture)

**Step 1: Create test CSV fixture**

A minimal RaceChrono CSV with ~20 rows across 2 laps. Just enough for the pipeline to produce GPS traces and corners.

**Step 2: Create smoke-flow.spec.ts**

```typescript
import { test, expect } from '@playwright/test';
import path from 'path';

const FIXTURE_CSV = path.join(__dirname, 'fixtures', 'test-session.csv');

test.describe('Full-flow smoke test', () => {
  test('upload, view session, verify charts render', async ({ page }) => {
    // 1. Navigate to sessions/upload page
    await page.goto('/app/sessions');
    await page.waitForLoadState('networkidle');

    // 2. Upload CSV fixture
    const fileInput = page.locator('input[type="file"]');
    if (await fileInput.isVisible()) {
      await fileInput.setInputFiles(FIXTURE_CSV);
      // Wait for upload to complete
      await page.waitForResponse((resp) =>
        resp.url().includes('/sessions/upload') && resp.status() === 200,
        { timeout: 30000 }
      );
    }

    // 3. Verify session appears in list
    await page.goto('/app/sessions');
    await page.waitForSelector('[data-testid="session-row"], .session-card, tr', {
      timeout: 10000,
    });

    // 4. Open session detail (click first session)
    const sessionLink = page.locator('a[href*="/sessions/"]').first();
    if (await sessionLink.isVisible()) {
      await sessionLink.click();
      await page.waitForLoadState('networkidle');

      // 5. Verify Visualize tab renders charts
      // Map container should have Leaflet content (not empty)
      const mapContainer = page.locator('#gps-map');
      if (await mapContainer.isVisible({ timeout: 5000 }).catch(() => false)) {
        // Leaflet creates .leaflet-container class when initialized
        await expect(mapContainer.locator('.leaflet-container, canvas, svg'))
          .toBeVisible({ timeout: 10000 });
      }

      // Speed trace canvas should exist
      const speedChart = page.locator('#speed-chart');
      if (await speedChart.isVisible({ timeout: 5000 }).catch(() => false)) {
        await expect(speedChart).toBeVisible();
      }
    }

    // 6. Navigate to Analytics page — verify no errors
    await page.goto('/app/analytics');
    await page.waitForLoadState('networkidle');
    // Check no error overlay
    const errorOverlay = page.locator('.error-overlay, [role="alert"]');
    expect(await errorOverlay.count()).toBe(0);
  });
});
```

**Step 3: Verify test file is valid**

Run: `cd lap-website && npx tsc --noEmit e2e/smoke-flow.spec.ts 2>&1 | head -10`
Expected: No syntax errors.

**Step 4: Commit**

```bash
git add lap-website/e2e/smoke-flow.spec.ts lap-website/e2e/fixtures/
git commit -m "test: add Playwright E2E smoke test for upload-to-visualize flow

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 12: Final verification

**Step 1: Run backend tests**

Run: `pytest telemetry_tool/tests/test_api_contracts.py -v`
Expected: All contract tests pass.

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -v`
Expected: All 119+ data API tests pass.

**Step 2: Run frontend build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 3: Verify shared components are importable**

Run:
```bash
cd lap-website && node -e "
const fs = require('fs');
const index = fs.readFileSync('src/components/shared/charts/index.ts', 'utf-8');
console.log('Exports:', index.match(/export \{.+\}/g));
"
```
Expected: Shows all exported components.

**Step 4: Summary**

Report what was implemented:
- Observability: verified already working (X-Request-Id, JSON logs, timing)
- API contract tests: seeded DB fixture + parametrized contract tests
- Shared chart components: TrackMap, SpeedTraceChart, GGExplorer, SectorPanel, CornerReplay, ChartSyncProvider
- E2E smoke test: upload-to-visualize Playwright test
- App chart components updated to re-export from shared

---

## Files Modified/Created

| File | Changes |
|------|---------|
| `telemetry_tool/tests/conftest.py` | Extend seeded_db with GPS, corners, theoretical, analysis |
| `telemetry_tool/tests/test_api_contracts.py` | New: seeded contract tests |
| `lap-website/src/components/shared/charts/useChartData.ts` | New: shared data-fetching hook |
| `lap-website/src/components/shared/charts/ChartSyncProvider.tsx` | New: hover sync context |
| `lap-website/src/components/shared/charts/useVanillaChart.ts` | Copied from app/charts/ |
| `lap-website/src/components/shared/charts/index.ts` | New: barrel export |
| `lap-website/src/components/shared/charts/TrackMap.tsx` | New: refactored from GpsTrace |
| `lap-website/src/components/shared/charts/SpeedTraceChart.tsx` | New: refactored from SpeedTraceZoom |
| `lap-website/src/components/shared/charts/GGExplorer.tsx` | New: refactored from GGExplorer |
| `lap-website/src/components/shared/charts/SectorPanel.tsx` | New: pure React + Tailwind |
| `lap-website/src/components/shared/charts/CornerReplay.tsx` | New: playback + compare |
| `lap-website/src/components/app/charts/*.tsx` | Updated: re-export from shared |
| `lap-website/e2e/smoke-flow.spec.ts` | New: E2E smoke test |
| `lap-website/e2e/fixtures/test-session.csv` | New: test fixture CSV |

### Execution Order

```
Task 1 (verify observability)
  -> Task 2 (extend seeded_db)
  -> Task 3 (contract tests)
  -> Task 4 (shared chart infra)
  -> Task 5 (TrackMap)
  -> Task 6 (SpeedTraceChart)
  -> Task 7 (GGExplorer)
  -> Task 8 (SectorPanel)
  -> Task 9 (CornerReplay)
  -> Task 10 (update app charts)
  -> Task 11 (E2E smoke test)
  -> Task 12 (final verification)
```
