# Compare Flows, Secondary Pages & Exports — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix Compare regressions (session compare panels, driver compare, widget bug), restore broken secondary pages (Weekends, Leaderboard, Dev Plans), flag analytics as Coming Soon, and build the Exports backend + wiring.

**Architecture:** Side-by-side panel layout for session compare with chart selector rail. Celery async for exports. All new frontend pages follow existing patterns (useQuery + api client + DataTable). New backend endpoints in existing route files. One Alembic migration (026) for exports table.

**Tech Stack:** Next.js 14 / TypeScript / Tailwind / Zustand / TanStack Query (frontend); Flask / PostgreSQL / Celery / Redis (backend); Canvas 2D for charts; pyarrow for Parquet exports.

**Design doc:** `docs/plans/2026-03-02-compare-secondary-exports-design.md`

---

## Phase 1: Bug Fixes (Quick Wins)

### Task 1: Fix SessionComparison.tsx field name mismatch

The `SessionComparison` widget in the Analytics tab is broken — it uses wrong field names for the backend response from `GET /api/v1/sessions/{id}/compare`.

**Files:**
- Modify: `lap-website/src/components/app/analytics/SessionComparison.tsx`

**Step 1: Fix the CompareData interface (lines 15-22)**

Replace:
```typescript
interface CompareData {
  distances: number[];
  speed_a: number[];
  speed_b: number[];
  time_delta_cumulative: number[];
  best_a_s: number;
  best_b_s: number;
}
```

With:
```typescript
interface CompareData {
  distances: number[];
  speeds_a: number[];
  speeds_b: number[];
  delta_s: number[];
  session_a: { session_id: string; best_time_s: number | null; lap_number: number };
  session_b: { session_id: string; best_time_s: number | null; lap_number: number };
}
```

**Step 2: Fix the speed canvas drawing (lines 108-133)**

Replace destructuring at line 108:
```typescript
const { distances, speed_a, speed_b } = compareData;
```
With:
```typescript
const { distances, speeds_a, speeds_b } = compareData;
```

Update all references: `speed_a` → `speeds_a`, `speed_b` → `speeds_b` through lines 112-133.

**Step 3: Fix the delta canvas drawing (lines 180-221)**

Replace all `time_delta_cumulative` references with `delta_s`:
- Line 180: `const { distances, time_delta_cumulative } = compareData;` → `const { distances, delta_s } = compareData;`
- Line 181: `if (!distances?.length || !time_delta_cumulative?.length)` → `if (!distances?.length || !delta_s?.length)`
- Lines 184, 188, 204, 210-211, 217-221: all `time_delta_cumulative` → `delta_s`

**Step 4: Fix the summary cards (lines 275-287)**

Replace:
```typescript
compareData.best_a_s
compareData.best_b_s
```
With:
```typescript
compareData.session_a?.best_time_s
compareData.session_b?.best_time_s
```

**Step 5: Fix the sessions list fetch (line 54)**

The component does `apiFetch<SessionSummary[]>('/sessions')` expecting a bare array, but the envelope unwrapper returns `{ sessions: [...] }`. Fix:

Replace:
```typescript
const data = await apiFetch<SessionSummary[]>('/sessions');
// ...
setSessions(data || []);
```
With:
```typescript
const data = await apiFetch<{ sessions: SessionSummary[] }>('/sessions');
// ...
setSessions(data?.sessions || []);
```

**Step 6: Verify**

Run: `cd lap-website && npm run build`
Expected: No TypeScript errors.

**Step 7: Commit**

```
feat: fix SessionComparison widget field name mismatch with backend
```

---

### Task 2: Fix Weekends detail page

The detail page calls a nonexistent `/weekends/{id}/sessions` endpoint and uses wrong field names.

**Files:**
- Modify: `lap-website/src/app/app/weekends/[id]/page.tsx`

**Step 1: Remove the separate sessions fetch (lines 62-65)**

The backend returns sessions inline in the weekend detail response. Remove the second `useQuery` call:

```typescript
// DELETE THIS:
const { data: sessionsData, ... } = useQuery({
  queryKey: ['weekend-sessions', id],
  queryFn: () => api.get<{ sessions: SessionRow[] }>(`/weekends/${id}/sessions`),
  enabled: !!weekend,
});
const sessions = sessionsData?.sessions ?? [];
```

Replace with:
```typescript
const sessions: SessionRow[] = (weekend as any)?.sessions ?? [];
```

**Step 2: Update the WeekendDetail interface (lines 9-12)**

The backend returns `session_count` (no `s`), and does not return `best_time` or `avg_score`. Add `sessions` to the interface and fix field names:

```typescript
interface WeekendDetail {
  id: number;
  name: string;
  track_name: string;
  track_id: number;
  start_date: string;
  end_date: string;
  notes: string | null;
  session_count: number;       // was sessions_count
  sessions: SessionRow[];      // inline from backend
  created_at: string;
}
```

**Step 3: Fix stat cards to use correct field names (lines ~115-119)**

- `weekend.sessions_count` → `weekend.session_count`
- `weekend.best_time` → compute from `sessions`: `sessions.length ? Math.min(...sessions.map(s => s.best_time).filter(Boolean)) : null`, format with `formatLapTime()`
- `weekend.avg_score` → compute from `sessions`: `sessions.length ? (sessions.reduce((a, s) => a + (s.score ?? 0), 0) / sessions.length).toFixed(1) : '—'`

**Step 4: Extract sessions from weekend data**

```typescript
const sessions: SessionRow[] = weekend?.sessions ?? [];
const bestTime = sessions.length
  ? Math.min(...sessions.filter(s => s.best_time).map(s => s.best_time))
  : null;
const avgScore = sessions.length
  ? (sessions.reduce((sum, s) => sum + (s.score ?? 0), 0) / sessions.length).toFixed(1)
  : null;
```

**Step 5: Verify**

Run: `cd lap-website && npm run build`
Expected: No TypeScript errors.

**Step 6: Commit**

```
fix: weekend detail reads sessions inline, fix field name mismatches
```

---

## Phase 2: Compare Enhancements

### Task 3: Add sector/corner compare backend endpoint

New endpoint that derives sector and corner timing deltas from the speed traces of two sessions' best laps.

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add endpoint after line ~1963)
- Test: `telemetry_tool/tests/test_data_api_v2.py`

**Step 1: Write the test**

```python
def test_compare_sectors(client, seeded_db):
    """Sector compare returns corner-by-corner timing data."""
    sessions = client.get("/api/v1/sessions?limit=2").get_json()
    sids = [s["session_id"] for s in sessions["data"]["sessions"][:2]]
    if len(sids) < 2:
        pytest.skip("need 2 sessions")
    resp = client.get(f"/api/v1/sessions/{sids[0]}/compare/sectors?sessionKeyB={sids[1]}")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert "sectors" in body
    assert "corners" in body
    assert isinstance(body["sectors"], list)
    assert isinstance(body["corners"], list)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py::test_compare_sectors -v`
Expected: FAIL (404 — route does not exist)

**Step 3: Implement the endpoint**

Add to `data_v2.py` after the `get_session_compare_overlay` function:

```python
@bp.route("/sessions/<session_id>/compare/sectors", methods=["GET"])
@_safe_api
def get_session_compare_sectors(session_id: str):
    """Sector and corner timing deltas between two sessions' best laps."""
    session_b_id = request.args.get("sessionKeyB")
    if not session_b_id:
        return api_response(error="sessionKeyB required", status=400)

    conn = _get_conn()

    # Get corners for both sessions
    corners_a = models.get_corners(conn, session_id) or []
    corners_b = models.get_corners(conn, session_b_id) or []

    # Get speed overlay data for timing
    # Reuse the overlay computation
    overlay_resp = _compute_overlay(conn, session_id, session_b_id)
    if overlay_resp is None:
        return api_response(error="Could not compute overlay", status=404)

    distances = overlay_resp["distances"]
    speeds_a = overlay_resp["speeds_a"]
    speeds_b = overlay_resp["speeds_b"]

    # Build corner comparison (aligned by corner index)
    corner_pairs = []
    n_corners = min(len(corners_a), len(corners_b))
    for i in range(n_corners):
        ca, cb = corners_a[i], corners_b[i]
        corner_pairs.append({
            "corner_id": i + 1,
            "name": ca.get("name") or f"Corner {i + 1}",
            "time_a": ca.get("time_s"),
            "time_b": cb.get("time_s"),
            "delta": round((cb.get("time_s", 0) or 0) - (ca.get("time_s", 0) or 0), 4),
            "min_speed_a": ca.get("min_speed_mps"),
            "min_speed_b": cb.get("min_speed_mps"),
            "entry_speed_a": ca.get("entry_speed_mps"),
            "entry_speed_b": cb.get("entry_speed_mps"),
            "exit_speed_a": ca.get("exit_speed_mps"),
            "exit_speed_b": cb.get("exit_speed_mps"),
        })

    # Build sectors from corner boundaries
    sectors = []
    if n_corners > 1:
        for i in range(n_corners - 1):
            sector_name = f"Sector {i + 1}"
            # Time through sector = sum of corner times in that range
            time_a = corners_a[i].get("time_s") or 0
            time_b = corners_b[i].get("time_s") or 0
            sectors.append({
                "sector_id": i + 1,
                "name": sector_name,
                "time_a": round(time_a, 4),
                "time_b": round(time_b, 4),
                "delta": round(time_b - time_a, 4),
            })

    return api_response(data={"sectors": sectors, "corners": corner_pairs})
```

Note: extract the overlay computation from `get_session_compare_overlay` into a shared `_compute_overlay()` helper to avoid code duplication.

**Step 4: Run test**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py::test_compare_sectors -v`
Expected: PASS

**Step 5: Commit**

```
feat: add sector/corner compare endpoint GET /sessions/{id}/compare/sectors
```

---

### Task 4: Add driver compare backend endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add after compare_sessions endpoint, ~line 759)
- Test: `telemetry_tool/tests/test_data_api_v2.py`

**Step 1: Write the test**

```python
def test_compare_drivers(client, seeded_db):
    """Driver compare returns aggregated scores and trends."""
    drivers = client.get("/api/v1/drivers").get_json()["data"]
    if len(drivers) < 2:
        pytest.skip("need 2 drivers")
    dids = [d["id"] for d in drivers[:2]]
    resp = client.get(f"/api/v1/compare/drivers?a={dids[0]}&b={dids[1]}")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert "driver_a" in body and "driver_b" in body
    for key in ("driver", "avg_scores", "trend", "stats"):
        assert key in body["driver_a"]
        assert key in body["driver_b"]
```

**Step 2: Run test — expected FAIL (404)**

**Step 3: Implement**

```python
@bp.route("/compare/drivers", methods=["GET"])
@_safe_api
def compare_drivers():
    """Compare two drivers' aggregated scores and trends."""
    driver_a_id = request.args.get("a")
    driver_b_id = request.args.get("b")
    if not driver_a_id or not driver_b_id:
        return api_response(error="Both 'a' and 'b' driver IDs required", status=400)

    conn = _get_conn()

    def _driver_data(driver_id):
        driver = models.get_driver_by_id(conn, driver_id)
        if not driver:
            return None

        # Get all sessions for this driver with scores
        sessions = models.get_sessions_for_driver(conn, driver_id)
        scores_list = []
        trend = []
        for s in (sessions or []):
            sd = models.get_score_details(conn, s["session_id"])
            if sd:
                scores_list.append(sd)
                trend.append({
                    "session_date": s.get("session_date"),
                    "total_score": sd.get("total_score"),
                })

        # Average scores
        avg = {"pace": 0, "consistency": 0, "execution": 0, "robustness": 0}
        if scores_list:
            avg["pace"] = round(sum(s.get("pace_score", 0) or 0 for s in scores_list) / len(scores_list), 1)
            avg["consistency"] = round(sum(s.get("consistency_score", 0) or 0 for s in scores_list) / len(scores_list), 1)
            avg["execution"] = round(sum(s.get("execution_score", 0) or 0 for s in scores_list) / len(scores_list), 1)
            avg["robustness"] = round(sum(s.get("robustness_score", 0) or 0 for s in scores_list) / len(scores_list), 1)

        totals = [s.get("total_score", 0) or 0 for s in scores_list]
        tracks = set(s.get("track_name") for s in (sessions or []) if s.get("track_name"))

        return {
            "driver": driver,
            "avg_scores": avg,
            "trend": sorted(trend, key=lambda t: t.get("session_date") or ""),
            "stats": {
                "sessions": len(sessions or []),
                "avg_score": round(sum(totals) / len(totals), 1) if totals else 0,
                "best_score": max(totals) if totals else 0,
                "tracks": len(tracks),
            },
        }

    da = _driver_data(driver_a_id)
    db = _driver_data(driver_b_id)
    if not da or not db:
        return api_response(error="One or both drivers not found", status=404)

    return api_response(data={"driver_a": da, "driver_b": db})
```

**Step 4: Run test — expected PASS**

**Step 5: Commit**

```
feat: add driver compare endpoint GET /compare/drivers
```

---

### Task 5: Refactor compare sessions page — side-by-side panel layout

Replace the inline speed overlay with a panel layout that has a chart selector rail.

**Files:**
- Modify: `lap-website/src/app/app/compare/sessions/page.tsx`
- Create: `lap-website/src/components/app/compare/CompareChartPanel.tsx`
- Create: `lap-website/src/components/app/compare/SpeedOverlayPanel.tsx`
- Create: `lap-website/src/components/app/compare/GpsOverlayPanel.tsx`
- Create: `lap-website/src/components/app/compare/SectorDeltaPanel.tsx`
- Create: `lap-website/src/components/app/compare/CornerComparePanel.tsx`

**Step 1: Create the CompareChartPanel container**

This is the selector rail + two-panel layout:

```typescript
'use client';
import { useState } from 'react';

type ChartMode = 'speed' | 'gps' | 'sectors' | 'corners';

interface CompareChartPanelProps {
  sessionAId: string;
  sessionBId: string;
}

const MODES: { key: ChartMode; label: string; icon: string }[] = [
  { key: 'speed',   label: 'Speed Overlay', icon: '~' },
  { key: 'gps',     label: 'GPS Overlay',   icon: '◎' },
  { key: 'sectors', label: 'Sector Delta',  icon: '▦' },
  { key: 'corners', label: 'Corner Detail', icon: '↗' },
];

export default function CompareChartPanel({ sessionAId, sessionBId }: CompareChartPanelProps) {
  const [mode, setMode] = useState<ChartMode>('speed');

  return (
    <div className="flex gap-4">
      {/* Selector rail */}
      <div className="flex flex-col gap-1 w-40 shrink-0">
        {MODES.map(m => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            className={`text-left px-3 py-2 rounded text-sm transition-colors ${
              mode === m.key
                ? 'bg-zinc-700 text-zinc-100 border-l-2 border-[#3ddc84]'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
            }`}
          >
            <span className="mr-2">{m.icon}</span>{m.label}
          </button>
        ))}
      </div>

      {/* Chart panels */}
      <div className="flex-1 min-w-0">
        {mode === 'speed'   && <SpeedOverlayPanel sessionAId={sessionAId} sessionBId={sessionBId} />}
        {mode === 'gps'     && <GpsOverlayPanel sessionAId={sessionAId} sessionBId={sessionBId} />}
        {mode === 'sectors' && <SectorDeltaPanel sessionAId={sessionAId} sessionBId={sessionBId} />}
        {mode === 'corners' && <CornerComparePanel sessionAId={sessionAId} sessionBId={sessionBId} />}
      </div>
    </div>
  );
}
```

**Step 2: Extract SpeedOverlayPanel**

Move the existing `SpeedOverlayChart` (lines 736-845), `drawSpeedCanvas` (848-940), and `drawDeltaCanvas` (943-1016) from `page.tsx` into `SpeedOverlayPanel.tsx`. The component stays identical — just relocated. It takes `sessionAId` and `sessionBId` props and fetches the overlay data itself (as it already does).

Add hover sync integration:
```typescript
import { useChartHoverStore } from '@/lib/chart-hover-store';
// In the mousemove handler on the speed canvas:
const { setHover, clearHover } = useChartHoverStore();
// On mousemove: setHover(distanceAtMouse, 'speed-overlay');
// On mouseleave: clearHover();
```

**Step 3: Create GpsOverlayPanel**

```typescript
'use client';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface GpsOverlayProps {
  sessionAId: string;
  sessionBId: string;
}

interface OverlayData {
  distances: number[];
  speeds_a: number[];
  speeds_b: number[];
  gps_a: { latitudes: number[]; longitudes: number[] };
  gps_b: { latitudes: number[]; longitudes: number[] };
}

export default function GpsOverlayPanel({ sessionAId, sessionBId }: GpsOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [data, setData] = useState<OverlayData | null>(null);
  const [loading, setLoading] = useState(true);
  const { hoverDistance, hoverSource } = useChartHoverStore();

  useEffect(() => {
    setLoading(true);
    api.get<OverlayData>(`/sessions/${sessionAId}/compare?sessionKeyB=${sessionBId}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [sessionAId, sessionBId]);

  useEffect(() => {
    if (!data || !canvasRef.current) return;
    drawGpsCanvas(canvasRef.current, data, hoverDistance);
  }, [data, hoverDistance]);

  if (loading) return <div className="h-[400px] flex items-center justify-center text-zinc-500">Loading GPS...</div>;
  if (!data?.gps_a?.latitudes?.length) return <div className="h-[400px] flex items-center justify-center text-zinc-500">No GPS data available</div>;

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h3 className="text-sm font-medium text-zinc-300 mb-3">GPS Track Overlay</h3>
      <canvas ref={canvasRef} width={700} height={400} className="w-full" />
      <div className="flex gap-4 mt-2 text-xs text-zinc-500">
        <span><span className="inline-block w-3 h-0.5 bg-[#3ddc84] mr-1" />Session A</span>
        <span><span className="inline-block w-3 h-0.5 bg-[#ff8c00] mr-1" />Session B</span>
      </div>
    </div>
  );
}

function drawGpsCanvas(canvas: HTMLCanvasElement, data: OverlayData, hoverDistance: number | null) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const { gps_a, gps_b, distances } = data;
  const allLat = [...gps_a.latitudes, ...gps_b.latitudes];
  const allLon = [...gps_a.longitudes, ...gps_b.longitudes];
  const minLat = Math.min(...allLat), maxLat = Math.max(...allLat);
  const minLon = Math.min(...allLon), maxLon = Math.max(...allLon);
  const pad = 30;

  const toX = (lon: number) => pad + ((lon - minLon) / (maxLon - minLon || 1)) * (W - 2 * pad);
  const toY = (lat: number) => H - pad - ((lat - minLat) / (maxLat - minLat || 1)) * (H - 2 * pad);

  // Draw trace A
  ctx.beginPath();
  ctx.strokeStyle = '#3ddc84';
  ctx.lineWidth = 2;
  gps_a.latitudes.forEach((lat, i) => {
    const x = toX(gps_a.longitudes[i]), y = toY(lat);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Draw trace B
  ctx.beginPath();
  ctx.strokeStyle = '#ff8c00';
  ctx.lineWidth = 2;
  gps_b.latitudes.forEach((lat, i) => {
    const x = toX(gps_b.longitudes[i]), y = toY(lat);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Hover marker
  if (hoverDistance !== null && distances.length) {
    // Find closest index to hoverDistance
    let idx = 0;
    let minDiff = Math.abs(distances[0] - hoverDistance);
    for (let i = 1; i < distances.length; i++) {
      const diff = Math.abs(distances[i] - hoverDistance);
      if (diff < minDiff) { minDiff = diff; idx = i; }
    }
    // Draw dots on both traces
    if (idx < gps_a.latitudes.length) {
      ctx.beginPath();
      ctx.arc(toX(gps_a.longitudes[idx]), toY(gps_a.latitudes[idx]), 5, 0, Math.PI * 2);
      ctx.fillStyle = '#3ddc84';
      ctx.fill();
    }
    if (idx < gps_b.latitudes.length) {
      ctx.beginPath();
      ctx.arc(toX(gps_b.longitudes[idx]), toY(gps_b.latitudes[idx]), 5, 0, Math.PI * 2);
      ctx.fillStyle = '#ff8c00';
      ctx.fill();
    }
  }
}
```

**Step 4: Create SectorDeltaPanel**

```typescript
'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

interface SectorData {
  sectors: { sector_id: number; name: string; time_a: number; time_b: number; delta: number }[];
  corners: any[];
}

export default function SectorDeltaPanel({ sessionAId, sessionBId }: { sessionAId: string; sessionBId: string }) {
  const [data, setData] = useState<SectorData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get<SectorData>(`/sessions/${sessionAId}/compare/sectors?sessionKeyB=${sessionBId}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [sessionAId, sessionBId]);

  if (loading) return <div className="h-[300px] flex items-center justify-center text-zinc-500">Loading sectors...</div>;
  if (!data?.sectors?.length) return <div className="h-[300px] flex items-center justify-center text-zinc-500">No sector data available</div>;

  const maxTime = Math.max(...data.sectors.flatMap(s => [s.time_a, s.time_b]));
  const totalDelta = data.sectors.reduce((sum, s) => sum + s.delta, 0);

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-zinc-300">Sector Time Delta</h3>
        <span className={`text-sm font-mono ${totalDelta > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
          {totalDelta > 0 ? '+' : ''}{totalDelta.toFixed(3)}s total
        </span>
      </div>
      <div className="space-y-3">
        {data.sectors.map(s => (
          <div key={s.sector_id}>
            <div className="flex items-center justify-between text-xs text-zinc-400 mb-1">
              <span>{s.name}</span>
              <span className={`font-mono ${s.delta > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                {s.delta > 0 ? '+' : ''}{s.delta.toFixed(3)}s
              </span>
            </div>
            <div className="flex gap-1 h-5">
              <div className="bg-[#3ddc84]/30 rounded" style={{ width: `${(s.time_a / maxTime) * 100}%` }}>
                <div className="h-full bg-[#3ddc84] rounded" style={{ width: '100%' }} />
              </div>
              <div className="bg-[#ff8c00]/30 rounded" style={{ width: `${(s.time_b / maxTime) * 100}%` }}>
                <div className="h-full bg-[#ff8c00] rounded" style={{ width: '100%' }} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 5: Create CornerComparePanel**

```typescript
'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

interface SectorData {
  sectors: any[];
  corners: {
    corner_id: number; name: string;
    time_a: number; time_b: number; delta: number;
    min_speed_a: number | null; min_speed_b: number | null;
    entry_speed_a: number | null; entry_speed_b: number | null;
    exit_speed_a: number | null; exit_speed_b: number | null;
  }[];
}

export default function CornerComparePanel({ sessionAId, sessionBId }: { sessionAId: string; sessionBId: string }) {
  const [data, setData] = useState<SectorData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get<SectorData>(`/sessions/${sessionAId}/compare/sectors?sessionKeyB=${sessionBId}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [sessionAId, sessionBId]);

  if (loading) return <div className="h-[300px] flex items-center justify-center text-zinc-500">Loading corners...</div>;
  if (!data?.corners?.length) return <div className="h-[300px] flex items-center justify-center text-zinc-500">No corner data available</div>;

  const mpsToKmh = (v: number | null) => v != null ? (v * 3.6).toFixed(1) : '—';

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h3 className="text-sm font-medium text-zinc-300 mb-3">Corner-by-Corner Comparison</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-2 pr-3">Corner</th>
              <th className="text-right py-2 px-2">Time A</th>
              <th className="text-right py-2 px-2">Time B</th>
              <th className="text-right py-2 px-2">Delta</th>
              <th className="text-right py-2 px-2">Min Spd A</th>
              <th className="text-right py-2 px-2">Min Spd B</th>
              <th className="text-right py-2 px-2">Entry A</th>
              <th className="text-right py-2 px-2">Entry B</th>
              <th className="text-right py-2 px-2">Exit A</th>
              <th className="text-right py-2 pl-2">Exit B</th>
            </tr>
          </thead>
          <tbody>
            {data.corners.map(c => (
              <tr key={c.corner_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                <td className="py-2 pr-3 text-zinc-300">{c.name}</td>
                <td className="text-right py-2 px-2 text-[#3ddc84] font-mono">{c.time_a?.toFixed(3) ?? '—'}</td>
                <td className="text-right py-2 px-2 text-[#ff8c00] font-mono">{c.time_b?.toFixed(3) ?? '—'}</td>
                <td className={`text-right py-2 px-2 font-mono ${(c.delta ?? 0) > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {c.delta != null ? `${c.delta > 0 ? '+' : ''}${c.delta.toFixed(3)}` : '—'}
                </td>
                <td className="text-right py-2 px-2 text-zinc-400">{mpsToKmh(c.min_speed_a)}</td>
                <td className="text-right py-2 px-2 text-zinc-400">{mpsToKmh(c.min_speed_b)}</td>
                <td className="text-right py-2 px-2 text-zinc-400">{mpsToKmh(c.entry_speed_a)}</td>
                <td className="text-right py-2 px-2 text-zinc-400">{mpsToKmh(c.entry_speed_b)}</td>
                <td className="text-right py-2 px-2 text-zinc-400">{mpsToKmh(c.exit_speed_a)}</td>
                <td className="text-right py-2 pl-2 text-zinc-400">{mpsToKmh(c.exit_speed_b)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

**Step 6: Update page.tsx to use CompareChartPanel**

In `page.tsx`, replace the `SpeedOverlayChart` usage (lines 520-525) with:
```tsx
<CompareChartPanel sessionAId={sessionAId} sessionBId={sessionBId} />
```

Remove the inline `SpeedOverlayChart`, `drawSpeedCanvas`, `drawDeltaCanvas` definitions (lines 736-1016) since they're now in `SpeedOverlayPanel.tsx`.

**Step 7: Verify**

Run: `cd lap-website && npm run build`

**Step 8: Commit**

```
feat: add side-by-side compare panels (GPS, sector delta, corner detail)
```

---

### Task 6: Build driver compare page

**Files:**
- Rewrite: `lap-website/src/app/app/compare/drivers/page.tsx`

**Step 1: Implement the full page**

Replace the placeholder with a full implementation:

```typescript
'use client';
import { useEffect, useState, useRef } from 'react';
import { api } from '@/lib/api-client';

interface Driver { id: number; name: string; }

interface DriverCompareData {
  driver_a: {
    driver: Driver;
    avg_scores: { pace: number; consistency: number; execution: number; robustness: number };
    trend: { session_date: string; total_score: number }[];
    stats: { sessions: number; avg_score: number; best_score: number; tracks: number };
  };
  driver_b: typeof DriverCompareData.prototype.driver_a;
}

// ... full implementation with:
// - Two driver dropdowns from GET /api/v1/drivers
// - Fetch comparison on selection from GET /api/v1/compare/drivers?a=...&b=...
// - Radar chart (Canvas 2D) for 4 score dimensions
// - Trend line chart (Canvas 2D) for score over time
// - Summary stats table (sessions, avg score, best score, tracks)
```

The radar chart draws a 4-axis polygon for each driver (acid-green and pit-orange). The trend chart draws score lines over session dates. Both use raw Canvas 2D (consistent with the speed overlay pattern).

**Step 2: Verify**

Run: `cd lap-website && npm run build`

**Step 3: Commit**

```
feat: implement driver compare page with radar chart and trend lines
```

---

### Task 7: Update compare hub with inline quick-start

**Files:**
- Modify: `lap-website/src/app/app/compare/page.tsx`

**Step 1: Add inline session/driver dropdowns to the hub cards**

Each card gets a mini selector that, on selection, navigates to the sub-page with pre-selected values via URL search params:

```
/app/compare/sessions?a={id}&b={id}
/app/compare/drivers?a={id}&b={id}
```

The sub-pages read these from `useSearchParams()` to pre-populate their dropdowns.

**Step 2: Verify + Commit**

```
feat: add quick-start dropdowns to compare hub
```

---

## Phase 3: Secondary Pages

### Task 8: Build leaderboard page

**Files:**
- Rewrite: `lap-website/src/app/app/leaderboard/page.tsx`

**Step 1: Implement full leaderboard**

```typescript
'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader } from '@/components/shared/PageHeader';

interface LeaderboardRow {
  session_id: string;
  session_date: string;
  best_lap_time_s: number;
  total_score: number;
  track_state: string;
  n_laps: number;
  driver_name: string;
  track_name: string;
  track_id: number;
}

interface Track { id: number; name: string; }
interface Driver { id: number; name: string; }

export default function LeaderboardPage() {
  const [trackId, setTrackId] = useState('');
  const [driverId, setDriverId] = useState('');

  const { data: tracks } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<Track[]>('/tracks'),
  });

  const { data: drivers } = useQuery({
    queryKey: ['drivers'],
    queryFn: () => api.get<Driver[]>('/drivers'),
  });

  const params = new URLSearchParams();
  if (trackId) params.set('track_id', trackId);
  if (driverId) params.set('driver_id', driverId);
  params.set('limit', '50');

  const { data: rows, isLoading } = useQuery({
    queryKey: ['leaderboard', trackId, driverId],
    queryFn: () => api.get<LeaderboardRow[]>(`/leaderboard?${params}`),
  });

  // Render: PageHeader, filter dropdowns (track + driver), sortable DataTable
  // Columns: Rank (#), Driver, Track, Best Lap (formatted mm:ss.sss), Laps, Score, Grade badge, Date
  // Sort: best_lap_time_s ASC by default
  // ...
}
```

Note: check the exact response shape — the backend may wrap in an envelope. The `api.get` client unwraps `{ok, data}` so `rows` should be the array directly.

**Step 2: Verify**

Run: `cd lap-website && npm run build`

**Step 3: Commit**

```
feat: implement leaderboard page with filters and sortable table
```

---

### Task 9: Build development plans pages

**Files:**
- Create: `lap-website/src/app/app/development/page.tsx`
- Create: `lap-website/src/app/app/development/[id]/page.tsx`
- Modify: `lap-website/src/app/app/layout.tsx` (add nav link)

**Step 1: Add nav link to sidebar**

In `layout.tsx`, add to the STRATEGIST group (after Leaderboard):
```typescript
{ href: '/app/development', label: 'Dev Plans', icon: '◧' },
```

**Step 2: Build list page**

```typescript
// GET /api/v1/dev-plans?driver_id=... → list
// Driver selector dropdown
// Grid of plan cards: name, driver, status, progress bar (from progress_json), created_at
// "New Plan" button → modal with name input + driver selector
// POST /api/v1/dev-plans { driver_id, plan_name }
```

**Step 3: Build detail page**

```typescript
// GET /api/v1/dev-plans/{id} → detail
// Plan name, driver, status, created/updated dates
// Progress tracking: parse progress_json as checklist items
// Edit progress: PATCH /api/v1/dev-plans/{id} { progress_json: {...} }
// Delete button: DELETE /api/v1/dev-plans/{id} → redirect to list
```

**Step 4: Verify + Commit**

```
feat: implement development plans list and detail pages
```

---

### Task 10: Analytics Coming Soon treatment

**Files:**
- Create: `lap-website/src/components/shared/ComingSoon.tsx`
- Modify: `lap-website/src/app/app/analytics/page.tsx`
- Modify: `lap-website/src/app/app/analytics/weather/page.tsx`
- Modify: `lap-website/src/app/app/analytics/trends/page.tsx`
- Modify: `lap-website/src/app/app/analytics/meteo/page.tsx`
- Modify: `lap-website/src/app/app/analytics/pace-predictor/page.tsx`
- Modify: `lap-website/src/app/app/analytics/weight-simulator/page.tsx`

**Step 1: Create ComingSoon component**

```typescript
import Link from 'next/link';

export function ComingSoon({ title, description, backHref }: { title: string; description?: string; backHref: string }) {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md">
        <div className="inline-block px-3 py-1 bg-amber-500/10 text-amber-400 text-xs font-medium rounded-full mb-4">
          Coming Soon
        </div>
        <h1 className="text-2xl font-bold text-zinc-100 mb-2">{title}</h1>
        {description && <p className="text-zinc-400 mb-6">{description}</p>}
        <Link href={backHref} className="text-sm text-[#3ddc84] hover:underline">
          Back to Analytics Hub
        </Link>
      </div>
    </div>
  );
}
```

**Step 2: Update all 5 sub-page stubs** to use `<ComingSoon>`

**Step 3: Update hub page** — add "Coming Soon" badge overlay to each card, make them non-navigable (render `<div>` instead of `<Link>`)

**Step 4: Verify + Commit**

```
feat: analytics sub-pages show Coming Soon with styled badges
```

---

## Phase 4: Exports

### Task 11: Alembic migration for exports table

**Files:**
- Create: `telemetry_tool/alembic/versions/026_exports.py`

**Step 1: Create migration**

```python
"""exports table for async export jobs"""
revision = "026"
down_revision = "025"

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

def upgrade():
    op.create_table(
        "exports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("file_path", sa.Text),
        sa.Column("file_size", sa.BigInteger),
        sa.Column("filters", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    # RLS policy
    op.execute("""
        ALTER TABLE exports ENABLE ROW LEVEL SECURITY;
        CREATE POLICY exports_workspace_isolation ON exports
            USING (workspace_id = current_setting('app.workspace_id')::uuid);
    """)
    op.create_index("ix_exports_workspace_user", "exports", ["workspace_id", "user_id"])

def downgrade():
    op.execute("DROP POLICY IF EXISTS exports_workspace_isolation ON exports")
    op.drop_table("exports")
```

**Step 2: Verify**

Run: `cd telemetry_tool && alembic upgrade head` (or dry-run with `--sql`)

**Step 3: Commit**

```
feat: add Alembic migration 026 for exports table with RLS
```

---

### Task 12: Celery export task

**Files:**
- Create: `telemetry_tool/tasks/export_tasks.py`

**Step 1: Implement the task**

```python
"""Async export generation tasks."""
import csv
import io
import json
import os
import logging
from datetime import datetime

from telemetry_tool.tasks.celery_app import celery
from telemetry_tool.web.db_pg import get_pg_conn

logger = logging.getLogger(__name__)

EXPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "exports")

@celery.task(queue="default", bind=True, max_retries=2)
def generate_export(self, export_id: str):
    """Generate an export file for the given export record."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    conn = get_pg_conn()
    try:
        # Fetch export record
        cur = conn.cursor()
        cur.execute("SELECT * FROM exports WHERE id = %s", (export_id,))
        row = cur.fetchone()
        if not row:
            logger.error("Export %s not found", export_id)
            return

        export = dict(row)
        data_type = export["data_type"]
        fmt = export["format"]
        workspace_id = str(export["workspace_id"])

        # Update status
        cur.execute("UPDATE exports SET status = 'generating' WHERE id = %s", (export_id,))
        conn.commit()

        # Set RLS context
        cur.execute("SET LOCAL app.workspace_id = %s", (workspace_id,))

        # Query data
        rows = _query_data(cur, data_type)

        # Generate file
        file_name = f"{export_id}.{fmt}"
        file_path = os.path.join(EXPORT_DIR, file_name)

        if fmt == "csv":
            _write_csv(rows, file_path)
        elif fmt == "json":
            _write_json(rows, file_path)
        elif fmt == "parquet":
            _write_parquet(rows, file_path)
        elif fmt == "pdf":
            _write_pdf(rows, file_path, data_type)

        file_size = os.path.getsize(file_path)
        cur.execute(
            "UPDATE exports SET status = 'ready', file_path = %s, file_size = %s, completed_at = NOW() WHERE id = %s",
            (file_path, file_size, export_id),
        )
        conn.commit()

    except Exception as e:
        logger.exception("Export %s failed", export_id)
        conn.rollback()
        cur = conn.cursor()
        cur.execute(
            "UPDATE exports SET status = 'failed', error = %s WHERE id = %s",
            (str(e)[:500], export_id),
        )
        conn.commit()
    finally:
        conn.close()


def _query_data(cur, data_type: str) -> list[dict]:
    """Query data for the given type, respecting RLS."""
    queries = {
        "sessions": "SELECT session_id, csv_filename, driver_name, track_name, session_date, n_laps, best_lap_time_s, total_score, grade FROM sessions ORDER BY session_date DESC",
        "laps": "SELECT l.session_id, l.lap_number, l.lap_time_s, l.speed_mean_mps, l.speed_max_mps, l.is_valid FROM laps l ORDER BY l.session_id, l.lap_number",
        "drivers": "SELECT id, driver_name, created_at FROM drivers ORDER BY driver_name",
        "tracks": "SELECT id, track_name, lap_length_m, created_at FROM tracks ORDER BY track_name",
        "scores": "SELECT session_id, total_score, grade, pace_score, consistency_score, execution_score, robustness_score FROM score_details ORDER BY session_id",
    }
    sql = queries.get(data_type)
    if not sql:
        raise ValueError(f"Unknown data_type: {data_type}")
    cur.execute(sql)
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _write_csv(rows: list[dict], path: str):
    if not rows:
        open(path, "w").close()
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _write_json(rows: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)


def _write_parquet(rows: list[dict], path: str):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if not rows:
        table = pa.table({})
    else:
        table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _write_pdf(rows: list[dict], path: str, data_type: str):
    """Simple PDF table using reportlab if available, otherwise JSON fallback."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        from reportlab.lib import colors

        doc = SimpleDocTemplate(path, pagesize=A4)
        if not rows:
            doc.build([])
            return
        headers = list(rows[0].keys())
        table_data = [headers] + [[str(r.get(h, "")) for h in headers] for r in rows[:500]]
        t = Table(table_data)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        doc.build([t])
    except ImportError:
        # Fallback: write JSON with .pdf extension
        _write_json(rows, path)
```

**Step 2: Commit**

```
feat: add Celery export task with CSV/JSON/Parquet/PDF generation
```

---

### Task 13: Export API endpoints

**Files:**
- Create: `telemetry_tool/web/routes/exports.py`
- Modify: `telemetry_tool/web/app.py` (register blueprint)

**Step 1: Create the exports blueprint**

```python
"""Export API endpoints."""
from flask import Blueprint, request, send_file, g
from telemetry_tool.web.api_utils import api_response

bp = Blueprint("exports", __name__, url_prefix="/api/v1")

VALID_TYPES = {"sessions", "laps", "drivers", "tracks", "scores"}
VALID_FORMATS = {"csv", "json", "pdf", "parquet"}

@bp.route("/exports/generate", methods=["POST"])
def generate_export():
    body = request.get_json(silent=True) or {}
    data_type = body.get("type") or body.get("data_type")
    fmt = body.get("format")

    if data_type not in VALID_TYPES:
        return api_response(error=f"Invalid data_type. Must be one of: {VALID_TYPES}", status=400)
    if fmt not in VALID_FORMATS:
        return api_response(error=f"Invalid format. Must be one of: {VALID_FORMATS}", status=400)

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO exports (workspace_id, user_id, data_type, format, filters) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (str(g.workspace_id), str(g.user_id), data_type, fmt, json.dumps(body.get("filters"))),
    )
    export_id = str(cur.fetchone()[0])
    conn.commit()

    from telemetry_tool.tasks.export_tasks import generate_export as gen_task
    gen_task.delay(export_id)

    return api_response(data={"id": export_id, "status": "pending"}, status=201)


@bp.route("/exports", methods=["GET"])
def list_exports():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, data_type, format, status, file_size, created_at, completed_at, error FROM exports WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
        (str(g.user_id),),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return api_response(data={"exports": rows})


@bp.route("/exports/<export_id>/download", methods=["GET"])
def download_export(export_id: str):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT file_path, format, status FROM exports WHERE id = %s AND user_id = %s", (export_id, str(g.user_id)))
    row = cur.fetchone()
    if not row:
        return api_response(error="Export not found", status=404)
    if row[2] != "ready":
        return api_response(error="Export not ready", status=400)

    import os
    if not os.path.exists(row[0]):
        return api_response(error="Export file missing", status=404)

    mime_map = {"csv": "text/csv", "json": "application/json", "pdf": "application/pdf", "parquet": "application/octet-stream"}
    return send_file(row[0], mimetype=mime_map.get(row[1], "application/octet-stream"), as_attachment=True, download_name=f"export.{row[1]}")
```

**Step 2: Register blueprint in app.py**

Add to the blueprint registration section in `telemetry_tool/web/app.py`:
```python
from telemetry_tool.web.routes.exports import bp as exports_bp
app.register_blueprint(exports_bp)
```

**Step 3: Commit**

```
feat: add export API endpoints (generate, list, download)
```

---

### Task 14: Wire exports frontend

**Files:**
- Modify: `lap-website/src/app/app/exports/page.tsx`

**Step 1: Verify API path alignment**

The existing frontend calls:
- `api.get<{ exports: ExportRow[] }>('/exports')` → matches `GET /api/v1/exports`
- `api.post('/exports/generate', { type: exportType, format: selectedFormat })` → matches `POST /api/v1/exports/generate`

Check that the `ExportRow` interface matches the backend response. Fix any mismatches:
- Backend returns `id` as UUID string → frontend expects `id: number` → fix to `string`
- Backend returns `data_type` + `format` but no `name` → frontend expects `name` → derive: `${data_type} export` or use `data_type` directly
- Backend returns no `download_url` → frontend expects it → compute: `/exports/${id}/download` for `status === 'ready'`

**Step 2: Add polling for in-progress exports**

```typescript
const { data, refetch } = useQuery({
  queryKey: ['exports'],
  queryFn: () => api.get<{ exports: ExportRow[] }>('/exports'),
  refetchInterval: (data) => {
    // Poll every 5s while any export is generating
    const hasActive = data?.exports?.some(e => e.status === 'generating' || e.status === 'pending');
    return hasActive ? 5000 : false;
  },
});
```

**Step 3: Wire download button**

```typescript
const handleDownload = (id: string) => {
  window.open(`${BACKEND_URL}/api/v1/exports/${id}/download`, '_blank');
};
```

**Step 4: Verify**

Run: `cd lap-website && npm run build`

**Step 5: Commit**

```
feat: wire exports frontend to real backend endpoints with polling
```

---

## Verification Checklist

After all tasks are complete:

1. **Compare Sessions**: Select two sessions → see metadata, scores, speed overlay, GPS overlay, sector delta, corner comparison in side-by-side panels
2. **Compare Drivers**: Select two drivers → see radar chart, trend lines, summary stats
3. **Compare Hub**: Inline dropdowns navigate to sub-pages with pre-selected values
4. **SessionComparison Widget**: In session detail Analytics tab, compare widget shows canvases and summary cards correctly
5. **Weekends Detail**: Sessions load from inline data, stats compute correctly
6. **Leaderboard**: Full table with track/driver filters, sorted by best lap time
7. **Dev Plans**: Nav link visible, list page with driver filter, create/detail/edit/delete working
8. **Analytics**: Hub shows Coming Soon badges, sub-pages show Coming Soon component
9. **Exports**: Generate export → shows pending → polls → shows ready → download works
10. **Chart Sync**: Hovering on speed overlay highlights position on GPS overlay

Run full frontend build: `cd lap-website && npm run build`
Run backend tests: `pytest telemetry_tool/tests/ -v`
