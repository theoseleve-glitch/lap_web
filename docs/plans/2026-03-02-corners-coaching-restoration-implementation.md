# Corners & Coaching Restoration — Implementation Plan v2

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fresh rebuild of the Corners & Coaching tab with modular React components, fixed data contract (corners always returned, `available: false` when theoretical fails), and real charts for brake precision + corner mastery.

**Architecture:** Modify backend `/corners` endpoint to merge corner boundaries with coaching metrics and add `available` flag. Create 8 new React component files under `components/app/corners/`. Wire into session detail page replacing inline CornersTab + legacy shared CornerReplay. Each section fetches its own data independently with graceful degradation.

**Tech Stack:** Python (Flask), TypeScript (Next.js 14, React), Canvas API, Vitest, apiFetch/api client

---

### Task 1: Backend — Fix `/corners` data contract

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:541-568`
- Test: `telemetry_tool/tests/test_data_api_v2.py`

**Step 1: Write the failing test**

In `telemetry_tool/tests/test_data_api_v2.py`, add:

```python
def test_corners_returns_boundaries_when_theoretical_missing(seeded_db):
    """Corners endpoint should return corner boundaries with available=false
    when theoretical data is missing."""
    conn = seeded_db
    # Session 1 from seeded_db has corners but may not have theoretical
    resp_data = _call_get_corners(conn, session_id=1)
    # Should always have a 'corners' list
    assert isinstance(resp_data["corners"], list)
    # Each corner should have corner_id, s_start, s_end, direction, available
    for c in resp_data["corners"]:
        assert "corner_id" in c
        assert "s_start" in c
        assert "s_end" in c
        assert "available" in c


def test_corners_available_flag_true_when_coaching_exists(seeded_db):
    """When theoretical data includes corner_coaching, corners should have available=true
    with metric fields populated."""
    conn = seeded_db
    # Insert mock theoretical data with corner_coaching for session 1
    import json
    mock_coaching = [
        {
            "corner_id": 1, "s_start": 100, "s_end": 200, "s_apex": 150,
            "direction": "L",
            "entry_speed_actual": 18.2, "entry_speed_theory": 19.5,
            "apex_speed_actual": 14.1, "apex_speed_theory": 15.8,
            "exit_speed_actual": 17.6, "exit_speed_theory": 18.9,
            "time_loss_total_s": 0.42, "primary_cause": "low_apex_speed",
            "coaching_hint": "Carry more speed through apex.",
        }
    ]
    conn.execute(
        "INSERT INTO theoretical_data (session_id, corner_coaching_json) VALUES (?, ?)"
        " ON CONFLICT(session_id) DO UPDATE SET corner_coaching_json = excluded.corner_coaching_json",
        (1, json.dumps(mock_coaching)),
    )
    conn.commit()

    resp_data = _call_get_corners(conn, session_id=1)
    assert resp_data["corners"][0]["available"] is True
    assert resp_data["corners"][0]["coaching_hint"] == "Carry more speed through apex."
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "test_corners" -v`
Expected: FAIL — current endpoint doesn't return `available` flag or boundary-only corners.

**Step 3: Modify the `/corners` endpoint**

In `telemetry_tool/web/routes/data_v2.py`, replace lines 541-568 with:

```python
@bp.route("/sessions/<session_id>/corners", methods=["GET"])
@_safe_api
def get_corners(session_id: str):
    """Return corner boundaries with coaching metrics when available.

    Corner boundaries come from corner detection (step 06b) stored in
    the session summary. Coaching metrics come from theoretical_data
    (corner_coaching_json). When theoretical fails, boundaries are still
    returned with available=false and null metrics.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Get corner boundaries from session summary
    summary = models.get_session_summary(conn, session_id)
    boundaries = summary.get("corners", []) if summary else []

    # Get coaching metrics from theoretical data
    theo = models.get_theoretical_data(conn, session_id)
    coaching_list = theo.get("corner_coaching") if theo else None

    # Build coaching lookup by corner_id
    coaching_map = {}
    if coaching_list:
        for c in coaching_list:
            cid = c.get("corner_id")
            if cid is not None:
                coaching_map[cid] = c

    # Merge boundaries with coaching
    result_corners = []
    for b in boundaries:
        cid = b.get("corner_id")
        coaching = coaching_map.get(cid)
        corner = {
            "corner_id": cid,
            "s_start": b.get("s_start"),
            "s_end": b.get("s_end"),
            "s_apex": b.get("s_apex"),
            "direction": b.get("direction"),
        }
        if coaching:
            corner["available"] = True
            for key in (
                "entry_speed_actual", "entry_speed_theory",
                "apex_speed_actual", "apex_speed_theory",
                "exit_speed_actual", "exit_speed_theory",
                "time_loss_total_s", "grip_utilisation_pct",
                "primary_cause", "coaching_hint",
            ):
                corner[key] = coaching.get(key)
        else:
            corner["available"] = False
            corner["coaching_hint"] = "Theoretical data unavailable for this corner"
            for key in (
                "entry_speed_actual", "entry_speed_theory",
                "apex_speed_actual", "apex_speed_theory",
                "exit_speed_actual", "exit_speed_theory",
                "time_loss_total_s", "grip_utilisation_pct",
                "primary_cause",
            ):
                corner[key] = None

        result_corners.append(corner)

    # Fallback: if no boundaries but coaching exists, use coaching as source
    if not result_corners and coaching_list:
        for c in coaching_list:
            corner = dict(c)
            corner["available"] = True
            result_corners.append(corner)

    return api_response({
        "corners": result_corners,
        "available": len(result_corners) > 0 and any(c["available"] for c in result_corners),
    })
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -k "test_corners" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_data_api_v2.py
git commit -m "fix: corners endpoint returns boundaries with available flag when theoretical fails"
```

---

### Task 2: Frontend — Create `CornersTab` orchestrator

**Files:**
- Create: `lap-website/src/components/app/corners/CornersTab.tsx`
- Create: `lap-website/src/components/app/corners/index.ts`

**Step 1: Create the directory and index**

```typescript
// lap-website/src/components/app/corners/index.ts
export { CornersTab } from './CornersTab';
```

**Step 2: Write CornersTab**

```typescript
// lap-website/src/components/app/corners/CornersTab.tsx
'use client';

import { useState } from 'react';
import { CoachingTable } from './CoachingTable';
import { CornerSelection } from './CornerSelection';
import { CornerReplay } from './CornerReplay';
import { BrakePrecisionChart } from './BrakePrecisionChart';
import { CornerMasteryCard } from './CornerMasteryCard';
import { ThrottleOnsetMap } from './ThrottleOnsetMap';
import { ConsistencyHeatmap } from './ConsistencyHeatmap';

export interface CornerData {
  corner_id: number;
  s_start: number;
  s_end: number;
  s_apex?: number;
  direction?: 'L' | 'R';
  available: boolean;
  entry_speed_actual?: number | null;
  entry_speed_theory?: number | null;
  apex_speed_actual?: number | null;
  apex_speed_theory?: number | null;
  exit_speed_actual?: number | null;
  exit_speed_theory?: number | null;
  time_loss_total_s?: number | null;
  grip_utilisation_pct?: number | null;
  primary_cause?: string | null;
  coaching_hint?: string | null;
}

interface CornersTabProps {
  corners: CornerData[];
  sessionId: string;
}

export function CornersTab({ corners, sessionId }: CornersTabProps) {
  const [selectedCorners, setSelectedCorners] = useState<Set<number>>(
    () => new Set(corners.map((c) => c.corner_id)),
  );

  if (corners.length === 0) {
    return (
      <div className="flex items-center justify-center py-20 text-steel/60 text-sm">
        No corners detected for this session
      </div>
    );
  }

  const filtered = corners.filter((c) => selectedCorners.has(c.corner_id));

  return (
    <div className="space-y-6">
      {/* Corner Replay */}
      <CornerReplay sessionId={sessionId} corners={filtered} />

      {/* Coaching Table + Corner Selection */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_240px] gap-4">
        <CoachingTable corners={filtered} />
        <CornerSelection
          corners={corners}
          selected={selectedCorners}
          onChange={setSelectedCorners}
          sessionId={sessionId}
        />
      </div>

      {/* Analysis Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <BrakePrecisionChart sessionId={sessionId} />
        <CornerMasteryCard sessionId={sessionId} />
        <ThrottleOnsetMap />
        <ConsistencyHeatmap />
      </div>
    </div>
  );
}
```

**Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/
git commit -m "feat: add CornersTab orchestrator component"
```

---

### Task 3: Frontend — Create `CoachingTable` component

**Files:**
- Create: `lap-website/src/components/app/corners/CoachingTable.tsx`

**Step 1: Write CoachingTable**

```typescript
// lap-website/src/components/app/corners/CoachingTable.tsx
'use client';

import { useState } from 'react';
import type { CornerData } from './CornersTab';

type SortKey = 'corner_id' | 'time_loss_total_s' | 'grip_utilisation_pct';

function severityColor(timeLossS: number | null | undefined): string {
  if (timeLossS == null) return 'text-steel/40';
  const ms = timeLossS * 1000;
  if (ms < 100) return 'text-green-400';
  if (ms < 300) return 'text-yellow-400';
  return 'text-red-400';
}

function fmtSpeed(mps: number | null | undefined): string {
  if (mps == null) return '--';
  return (mps * 3.6).toFixed(1);  // m/s → km/h
}

function fmtLoss(s: number | null | undefined): string {
  if (s == null) return '--';
  return `${(s * 1000).toFixed(0)} ms`;
}

interface Props {
  corners: CornerData[];
}

export function CoachingTable({ corners }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('corner_id');
  const [sortAsc, setSortAsc] = useState(true);

  const sorted = [...corners].sort((a, b) => {
    const av = a[sortKey] ?? -Infinity;
    const bv = b[sortKey] ?? -Infinity;
    return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  }

  const th = 'px-3 py-2 text-left text-[10px] uppercase tracking-wider text-steel/50 cursor-pointer hover:text-chalk select-none';
  const td = 'px-3 py-2 text-xs';

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-steel/10">
            <th className={th} onClick={() => toggleSort('corner_id')}>Corner</th>
            <th className={th}>Entry</th>
            <th className={th}>Apex</th>
            <th className={th}>Exit</th>
            <th className={th}>Grip %</th>
            <th className={th} onClick={() => toggleSort('time_loss_total_s')}>Time Loss</th>
            <th className={th}>Coaching</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((c) => (
            <tr
              key={c.corner_id}
              className={`border-b border-steel/5 ${!c.available ? 'opacity-40' : ''}`}
            >
              <td className={td}>
                <span className="font-mono font-bold text-chalk">C{c.corner_id}</span>
                {c.direction && (
                  <span className="ml-1 text-[9px] text-steel/50">{c.direction}</span>
                )}
              </td>
              <td className={td}>
                <span className="text-chalk">{fmtSpeed(c.entry_speed_actual)}</span>
                {c.entry_speed_theory != null && (
                  <span className="text-steel/40 ml-1">/ {fmtSpeed(c.entry_speed_theory)}</span>
                )}
              </td>
              <td className={td}>
                <span className="text-chalk">{fmtSpeed(c.apex_speed_actual)}</span>
                {c.apex_speed_theory != null && (
                  <span className="text-steel/40 ml-1">/ {fmtSpeed(c.apex_speed_theory)}</span>
                )}
              </td>
              <td className={td}>
                <span className="text-chalk">{fmtSpeed(c.exit_speed_actual)}</span>
                {c.exit_speed_theory != null && (
                  <span className="text-steel/40 ml-1">/ {fmtSpeed(c.exit_speed_theory)}</span>
                )}
              </td>
              <td className={td}>
                {c.grip_utilisation_pct != null ? `${c.grip_utilisation_pct.toFixed(0)}%` : '--'}
              </td>
              <td className={`${td} ${severityColor(c.time_loss_total_s)} font-mono`}>
                {fmtLoss(c.time_loss_total_s)}
              </td>
              <td className={`${td} text-steel/70 max-w-[200px] truncate`}>
                {c.coaching_hint || '--'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add lap-website/src/components/app/corners/CoachingTable.tsx
git commit -m "feat: add CoachingTable component with sortable columns"
```

---

### Task 4: Frontend — Create `CornerSelection` component

**Files:**
- Create: `lap-website/src/components/app/corners/CornerSelection.tsx`

**Step 1: Write CornerSelection**

```typescript
// lap-website/src/components/app/corners/CornerSelection.tsx
'use client';

import { useEffect } from 'react';
import type { CornerData } from './CornersTab';

interface Props {
  corners: CornerData[];
  selected: Set<number>;
  onChange: (s: Set<number>) => void;
  sessionId: string;
}

const STORAGE_PREFIX = 'corner_sel_';

export function CornerSelection({ corners, selected, onChange, sessionId }: Props) {
  // Load saved selection on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + sessionId);
      if (raw) {
        const ids: number[] = JSON.parse(raw);
        onChange(new Set(ids));
      }
    } catch { /* ignore */ }
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
    localStorage.setItem(STORAGE_PREFIX + sessionId, JSON.stringify([...next]));
  }

  function selectAll() {
    const all = new Set(corners.map((c) => c.corner_id));
    onChange(all);
    localStorage.setItem(STORAGE_PREFIX + sessionId, JSON.stringify([...all]));
  }

  function clearAll() {
    onChange(new Set());
    localStorage.setItem(STORAGE_PREFIX + sessionId, JSON.stringify([]));
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] uppercase tracking-wider text-steel/50">Corners</span>
        <div className="flex gap-2">
          <button onClick={selectAll} className="text-[9px] text-amber-400 hover:underline">
            All
          </button>
          <button onClick={clearAll} className="text-[9px] text-steel/40 hover:underline">
            Clear
          </button>
        </div>
      </div>
      <div className="space-y-1.5">
        {corners.map((c) => (
          <label
            key={c.corner_id}
            className="flex items-center gap-2 cursor-pointer text-xs text-chalk"
          >
            <input
              type="checkbox"
              checked={selected.has(c.corner_id)}
              onChange={() => toggle(c.corner_id)}
              className="rounded border-steel/30 bg-transparent text-amber-400 focus:ring-amber-400/30"
            />
            <span className="font-mono">C{c.corner_id}</span>
            {c.direction && <span className="text-steel/40 text-[9px]">{c.direction}</span>}
          </label>
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add lap-website/src/components/app/corners/CornerSelection.tsx
git commit -m "feat: add CornerSelection with localStorage persistence"
```

---

### Task 5: Frontend — Create `CornerReplay` component

**Files:**
- Create: `lap-website/src/components/app/corners/CornerReplay.tsx`

**Step 1: Write CornerReplay**

This is the largest component. It fetches from `/corner-replay-data`, renders a canvas-based cockpit gauge, GPS map with corner trace, and playback controls. Uses `useRef` for canvas, `useReducer` for playback state, `requestAnimationFrame` for animation.

```typescript
// lap-website/src/components/app/corners/CornerReplay.tsx
'use client';

import { useState, useEffect, useRef, useReducer, useCallback } from 'react';
import { api } from '@/lib/api-client';
import type { CornerData } from './CornersTab';

// ── Types ─────────────────────────────────────────────────

interface TracePoint {
  lat: number; lon: number; speed_mps: number;
  accel_lat?: number; accel_long?: number; distance_m: number;
}

interface ReplayLap { lap_number: number; lap_time_s: number; traces: TracePoint[]; }

interface ReplayData {
  corner_positions: Array<{ corner_id: number; lat: number; lon: number; s_start: number; s_end: number }>;
  corner_metrics: Array<{ corner_id: number; lap_number: number; entry_speed_mps: number; apex_speed_mps: number; exit_speed_mps: number; time_loss_ms: number }>;
  laps: ReplayLap[];
  best_lap_number: number;
  has_pedal_data: boolean;
  has_steering_data: boolean;
}

type Mode = 'review' | 'split' | 'top3';
type Speed = 0.25 | 0.5 | 1 | 2;

interface State {
  mode: Mode; cornerIdx: number; lapA: number; lapB: number;
  frame: number; playing: boolean; speed: Speed;
}

type Action =
  | { type: 'SET_MODE'; mode: Mode }
  | { type: 'SET_CORNER'; idx: number }
  | { type: 'NEXT_CORNER'; max: number }
  | { type: 'PREV_CORNER'; max: number }
  | { type: 'SET_LAP_A'; lap: number }
  | { type: 'SET_LAP_B'; lap: number }
  | { type: 'SET_FRAME'; frame: number }
  | { type: 'TOGGLE_PLAY' }
  | { type: 'SET_SPEED'; speed: Speed }
  | { type: 'TICK'; maxFrame: number };

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'SET_MODE': return { ...s, mode: a.mode, frame: 0, playing: false };
    case 'SET_CORNER': return { ...s, cornerIdx: a.idx, frame: 0, playing: false };
    case 'NEXT_CORNER': return { ...s, cornerIdx: (s.cornerIdx + 1) % a.max, frame: 0, playing: false };
    case 'PREV_CORNER': return { ...s, cornerIdx: (s.cornerIdx - 1 + a.max) % a.max, frame: 0, playing: false };
    case 'SET_LAP_A': return { ...s, lapA: a.lap };
    case 'SET_LAP_B': return { ...s, lapB: a.lap };
    case 'SET_FRAME': return { ...s, frame: a.frame };
    case 'TOGGLE_PLAY': return { ...s, playing: !s.playing };
    case 'SET_SPEED': return { ...s, speed: a.speed };
    case 'TICK': {
      const next = s.frame + 1;
      return next >= a.maxFrame ? { ...s, frame: 0, playing: false } : { ...s, frame: next };
    }
    default: return s;
  }
}

// ── Component ─────────────────────────────────────────────

interface Props { sessionId: string; corners: CornerData[]; }

export function CornerReplay({ sessionId, corners }: Props) {
  const [data, setData] = useState<ReplayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mapRef = useRef<HTMLCanvasElement>(null);
  const gaugeRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);

  const [state, dispatch] = useReducer(reducer, {
    mode: 'review', cornerIdx: 0, lapA: 0, lapB: 1,
    frame: 0, playing: false, speed: 1,
  });

  // Fetch replay data
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get<ReplayData>(`/sessions/${sessionId}/corner-replay-data`)
      .then((d) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [sessionId]);

  // Get current corner's trace slice for the active lap
  const getSlice = useCallback((lapNum: number) => {
    if (!data || !corners[state.cornerIdx]) return [];
    const corner = corners[state.cornerIdx];
    const lap = data.laps.find((l) => l.lap_number === lapNum);
    if (!lap) return [];
    return lap.traces.filter((p) => p.distance_m >= corner.s_start && p.distance_m <= corner.s_end);
  }, [data, corners, state.cornerIdx]);

  // Animation loop
  useEffect(() => {
    if (!state.playing) return;
    const interval = Math.round(33 / state.speed); // ~30fps base, scaled by speed
    const id = setInterval(() => {
      const slice = getSlice(state.lapA || data?.best_lap_number || 1);
      dispatch({ type: 'TICK', maxFrame: slice.length });
    }, interval);
    return () => clearInterval(id);
  }, [state.playing, state.speed, state.lapA, data, getSlice]);

  // Draw map canvas
  useEffect(() => {
    const canvas = mapRef.current;
    if (!canvas || !data || corners.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const slice = getSlice(state.lapA || data.best_lap_number);
    if (slice.length === 0) return;

    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Compute bounds
    const lats = slice.map((p) => p.lat);
    const lons = slice.map((p) => p.lon);
    const minLat = Math.min(...lats), maxLat = Math.max(...lats);
    const minLon = Math.min(...lons), maxLon = Math.max(...lons);
    const pad = 0.15;
    const rangeX = (maxLon - minLon) || 0.0001;
    const rangeY = (maxLat - minLat) || 0.0001;

    function toX(lon: number) { return pad * w + ((lon - minLon) / rangeX) * w * (1 - 2 * pad); }
    function toY(lat: number) { return h - (pad * h + ((lat - minLat) / rangeY) * h * (1 - 2 * pad)); }

    // Draw trace
    ctx.beginPath();
    ctx.strokeStyle = '#c3a54b';
    ctx.lineWidth = 2;
    slice.forEach((p, i) => {
      const x = toX(p.lon), y = toY(p.lat);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Draw cursor dot
    if (state.frame < slice.length) {
      const p = slice[state.frame];
      ctx.beginPath();
      ctx.arc(toX(p.lon), toY(p.lat), 5, 0, Math.PI * 2);
      ctx.fillStyle = '#fff';
      ctx.fill();
    }

    // Corner markers
    const cp = data.corner_positions.find((cp) => cp.corner_id === corners[state.cornerIdx]?.corner_id);
    if (cp) {
      ctx.beginPath();
      ctx.arc(toX(cp.lon), toY(cp.lat), 8, 0, Math.PI * 2);
      ctx.strokeStyle = '#e55';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = '#e55';
      ctx.font = '10px monospace';
      ctx.fillText(`C${cp.corner_id}`, toX(cp.lon) + 10, toY(cp.lat) - 4);
    }
  }, [data, corners, state.cornerIdx, state.frame, state.lapA, getSlice]);

  // Draw cockpit gauge
  useEffect(() => {
    const canvas = gaugeRef.current;
    if (!canvas || !data || corners.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const slice = getSlice(state.lapA || data.best_lap_number);
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const point = slice[state.frame] || slice[0];
    if (!point) return;

    const speed_kmh = point.speed_mps * 3.6;
    const maxSpeed = 120;
    const cx = w / 2, cy = h * 0.6, r = Math.min(w, h) * 0.38;

    // Arc background
    const startAngle = Math.PI * 0.8, endAngle = Math.PI * 2.2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 6;
    ctx.stroke();

    // Speed arc
    const speedAngle = startAngle + (speed_kmh / maxSpeed) * (endAngle - startAngle);
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, Math.min(speedAngle, endAngle));
    ctx.strokeStyle = '#c3a54b';
    ctx.lineWidth = 6;
    ctx.stroke();

    // Speed text
    ctx.fillStyle = '#e0dcd0';
    ctx.font = 'bold 24px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`${speed_kmh.toFixed(0)}`, cx, cy);
    ctx.font = '10px monospace';
    ctx.fillStyle = '#666';
    ctx.fillText('km/h', cx, cy + 16);

    // G-force diamond
    if (point.accel_lat != null && point.accel_long != null) {
      const gx = cx, gy = cy + r + 30;
      const gScale = 15; // pixels per G (1G ≈ 9.81 m/s²)
      const latG = point.accel_lat / 9.81;
      const longG = point.accel_long / 9.81;
      // Background diamond
      ctx.strokeStyle = '#333';
      ctx.lineWidth = 1;
      ctx.strokeRect(gx - 30, gy - 30, 60, 60);
      // Dot
      ctx.beginPath();
      ctx.arc(gx + latG * gScale, gy - longG * gScale, 3, 0, Math.PI * 2);
      ctx.fillStyle = '#c3a54b';
      ctx.fill();
    }
  }, [data, corners, state.cornerIdx, state.frame, state.lapA, getSlice]);

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      switch (e.key) {
        case ' ': e.preventDefault(); dispatch({ type: 'TOGGLE_PLAY' }); break;
        case 'ArrowRight': dispatch({ type: 'SET_FRAME', frame: state.frame + 1 }); break;
        case 'ArrowLeft': dispatch({ type: 'SET_FRAME', frame: Math.max(0, state.frame - 1) }); break;
        case ']': dispatch({ type: 'NEXT_CORNER', max: corners.length }); break;
        case '[': dispatch({ type: 'PREV_CORNER', max: corners.length }); break;
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state.frame, corners.length]);

  if (loading) {
    return <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center text-steel/40 text-sm">Loading corner replay...</div>;
  }
  if (error) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center">
        <p className="text-red-400 text-sm mb-2">Failed to load replay data</p>
        <button onClick={() => window.location.reload()} className="text-xs text-amber-400 hover:underline">Retry</button>
      </div>
    );
  }
  if (!data || data.laps.length === 0) {
    return <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center text-steel/40 text-sm">No replay data available</div>;
  }

  const slice = getSlice(state.lapA || data.best_lap_number);
  const currentPoint = slice[state.frame];
  const cornerMetrics = data.corner_metrics.filter(
    (m) => m.corner_id === corners[state.cornerIdx]?.corner_id,
  );
  const speeds: Speed[] = [0.25, 0.5, 1, 2];

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 overflow-hidden">
      {/* Controls bar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-steel/10 text-xs">
        {/* Mode tabs */}
        {(['review', 'split', 'top3'] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => dispatch({ type: 'SET_MODE', mode: m })}
            className={`px-2 py-1 rounded ${state.mode === m ? 'bg-amber-400/20 text-amber-400' : 'text-steel/50 hover:text-chalk'}`}
          >
            {m === 'top3' ? 'Top 3' : m.charAt(0).toUpperCase() + m.slice(1)}
          </button>
        ))}
        <span className="w-px h-4 bg-steel/10" />
        {/* Corner pills */}
        <button onClick={() => dispatch({ type: 'PREV_CORNER', max: corners.length })} className="text-steel/40 hover:text-chalk">&lsaquo;</button>
        {corners.map((c, i) => (
          <button
            key={c.corner_id}
            onClick={() => dispatch({ type: 'SET_CORNER', idx: i })}
            className={`px-2 py-0.5 rounded font-mono ${state.cornerIdx === i ? 'bg-amber-400/20 text-amber-400' : 'text-steel/50 hover:text-chalk'}`}
          >
            C{c.corner_id}
          </button>
        ))}
        <button onClick={() => dispatch({ type: 'NEXT_CORNER', max: corners.length })} className="text-steel/40 hover:text-chalk">&rsaquo;</button>
        <span className="w-px h-4 bg-steel/10" />
        {/* Playback */}
        <button onClick={() => dispatch({ type: 'TOGGLE_PLAY' })} className="text-chalk hover:text-amber-400 font-mono">
          {state.playing ? '||' : '\u25B6'}
        </button>
        {speeds.map((sp) => (
          <button
            key={sp}
            onClick={() => dispatch({ type: 'SET_SPEED', speed: sp })}
            className={`font-mono ${state.speed === sp ? 'text-amber-400' : 'text-steel/40 hover:text-chalk'}`}
          >
            {sp}x
          </button>
        ))}
        {/* Scrubber */}
        <input
          type="range"
          min={0}
          max={Math.max(0, slice.length - 1)}
          value={state.frame}
          onChange={(e) => dispatch({ type: 'SET_FRAME', frame: parseInt(e.target.value) })}
          className="flex-1 h-1 accent-amber-400"
        />
      </div>

      {/* 3-pane body */}
      <div className="grid grid-cols-[180px_1fr_200px] h-[380px]">
        {/* Cockpit gauge */}
        <div className="border-r border-steel/10 flex items-center justify-center p-2">
          <canvas ref={gaugeRef} width={160} height={240} />
        </div>
        {/* GPS map */}
        <div className="p-2">
          <canvas ref={mapRef} width={600} height={360} className="w-full h-full" />
        </div>
        {/* Metrics sidebar */}
        <div className="border-l border-steel/10 p-3 text-xs space-y-3 overflow-y-auto">
          <div>
            <span className="text-steel/40 text-[9px] uppercase">Speed</span>
            <p className="text-chalk font-mono text-lg">
              {currentPoint ? (currentPoint.speed_mps * 3.6).toFixed(0) : '--'} <span className="text-[9px] text-steel/40">km/h</span>
            </p>
          </div>
          {corners[state.cornerIdx] && (
            <>
              <div className="grid grid-cols-3 gap-1 text-center">
                <div>
                  <span className="text-[8px] text-steel/40">ENTRY</span>
                  <p className="font-mono text-chalk">{fmtSpd(corners[state.cornerIdx].entry_speed_actual)}</p>
                </div>
                <div>
                  <span className="text-[8px] text-steel/40">APEX</span>
                  <p className="font-mono text-chalk">{fmtSpd(corners[state.cornerIdx].apex_speed_actual)}</p>
                </div>
                <div>
                  <span className="text-[8px] text-steel/40">EXIT</span>
                  <p className="font-mono text-chalk">{fmtSpd(corners[state.cornerIdx].exit_speed_actual)}</p>
                </div>
              </div>
              {corners[state.cornerIdx].time_loss_total_s != null && (
                <div>
                  <span className="text-[8px] text-steel/40">TIME LOSS</span>
                  <p className="font-mono text-red-400">{(corners[state.cornerIdx].time_loss_total_s! * 1000).toFixed(0)} ms</p>
                </div>
              )}
              {corners[state.cornerIdx].coaching_hint && (
                <div>
                  <span className="text-[8px] text-steel/40">COACHING</span>
                  <p className="text-steel/70 leading-relaxed">{corners[state.cornerIdx].coaching_hint}</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function fmtSpd(mps: number | null | undefined): string {
  if (mps == null) return '--';
  return `${(mps * 3.6).toFixed(0)}`;
}
```

**Step 2: Commit**

```bash
git add lap-website/src/components/app/corners/CornerReplay.tsx
git commit -m "feat: add CornerReplay with cockpit gauge, GPS map, and playback controls"
```

---

### Task 6: Frontend — Create `BrakePrecisionChart` component

**Files:**
- Create: `lap-website/src/components/app/corners/BrakePrecisionChart.tsx`

**Step 1: Write BrakePrecisionChart**

```typescript
// lap-website/src/components/app/corners/BrakePrecisionChart.tsx
'use client';

import { useState, useEffect, useRef } from 'react';
import { api } from '@/lib/api-client';

interface BrakeData {
  corner_id: number;
  braking_point_delta_m: number;
  direction?: string;
}

interface Props { sessionId: string; }

export function BrakePrecisionChart({ sessionId }: Props) {
  const [data, setData] = useState<BrakeData[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    api.get<{ brake_data: BrakeData[] }>(`/sessions/${sessionId}/brake-precision`)
      .then((d) => { if (!cancelled) setData(d.brake_data || []); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data || data.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const barH = 20;
    const gap = 8;
    const labelW = 40;
    const maxDelta = Math.max(10, ...data.map((d) => Math.abs(d.braking_point_delta_m)));
    const midX = labelW + (w - labelW) / 2;

    data.forEach((d, i) => {
      const y = 20 + i * (barH + gap);
      const barW = (d.braking_point_delta_m / maxDelta) * ((w - labelW) / 2 - 10);

      // Color by severity
      const abs = Math.abs(d.braking_point_delta_m);
      const color = abs < 2 ? '#4ade80' : abs < 5 ? '#facc15' : '#f87171';

      // Label
      ctx.fillStyle = '#e0dcd0';
      ctx.font = '10px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`C${d.corner_id}`, labelW - 6, y + barH / 2 + 4);

      // Bar
      ctx.fillStyle = color;
      if (barW >= 0) {
        ctx.fillRect(midX, y, barW, barH);
      } else {
        ctx.fillRect(midX + barW, y, -barW, barH);
      }

      // Value label
      ctx.fillStyle = '#999';
      ctx.textAlign = barW >= 0 ? 'left' : 'right';
      ctx.fillText(
        `${d.braking_point_delta_m > 0 ? '+' : ''}${d.braking_point_delta_m.toFixed(1)}m`,
        midX + barW + (barW >= 0 ? 4 : -4),
        y + barH / 2 + 4,
      );
    });

    // Center line
    ctx.strokeStyle = '#444';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(midX, 10);
    ctx.lineTo(midX, 20 + data.length * (barH + gap));
    ctx.stroke();

    // Axis labels
    ctx.fillStyle = '#555';
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Early', midX - (w - labelW) / 4, 14);
    ctx.fillText('Late', midX + (w - labelW) / 4, 14);
  }, [data]);

  if (error) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-xs uppercase tracking-wider text-steel/50 mb-2">Brake Precision</h3>
        <p className="text-red-400 text-xs">Failed to load data</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <h3 className="text-xs uppercase tracking-wider text-steel/50 mb-3">Brake Precision</h3>
      {data === null ? (
        <p className="text-steel/40 text-xs">Loading...</p>
      ) : data.length === 0 ? (
        <p className="text-steel/40 text-xs">No brake precision data</p>
      ) : (
        <canvas ref={canvasRef} width={400} height={20 + data.length * 28 + 10} className="w-full" />
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add lap-website/src/components/app/corners/BrakePrecisionChart.tsx
git commit -m "feat: add BrakePrecisionChart with real data from /brake-precision"
```

---

### Task 7: Frontend — Create `CornerMasteryCard` component

**Files:**
- Create: `lap-website/src/components/app/corners/CornerMasteryCard.tsx`

**Step 1: Write CornerMasteryCard**

```typescript
// lap-website/src/components/app/corners/CornerMasteryCard.tsx
'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';

interface MasteryCorner {
  corner_id: number;
  mastery_score: number;
  grade: string;
  dimensions?: {
    brake_precision?: number;
    apex_speed?: number;
    exit_utilisation?: number;
    consistency?: number;
    grip?: number;
  };
}

interface MasteryData {
  overall_score: number;
  overall_grade: string;
  corners: MasteryCorner[];
}

interface Props { sessionId: string; }

function gradeColor(grade: string): string {
  if (grade.startsWith('A')) return 'text-green-400';
  if (grade.startsWith('B')) return 'text-amber-400';
  if (grade.startsWith('C')) return 'text-yellow-400';
  return 'text-red-400';
}

export function CornerMasteryCard({ sessionId }: Props) {
  const [data, setData] = useState<MasteryData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.get<MasteryData>(`/sessions/${sessionId}/corner-mastery`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [sessionId]);

  if (error) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-xs uppercase tracking-wider text-steel/50 mb-2">Corner Mastery</h3>
        <p className="text-red-400 text-xs">Failed to load data</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h3 className="text-xs uppercase tracking-wider text-steel/50 mb-2">Corner Mastery</h3>
        <p className="text-steel/40 text-xs">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs uppercase tracking-wider text-steel/50">Corner Mastery</h3>
        <div className="text-right">
          <span className={`text-2xl font-mono font-bold ${gradeColor(data.overall_grade)}`}>
            {data.overall_grade}
          </span>
          <span className="text-steel/40 text-xs ml-1">{data.overall_score}/100</span>
        </div>
      </div>
      <div className="space-y-2">
        {data.corners.map((c) => (
          <div key={c.corner_id} className="flex items-center gap-2">
            <span className="font-mono text-xs text-chalk w-8">C{c.corner_id}</span>
            <div className="flex-1 h-2 bg-steel/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-400 rounded-full transition-all"
                style={{ width: `${c.mastery_score}%` }}
              />
            </div>
            <span className={`font-mono text-xs w-6 text-right ${gradeColor(c.grade)}`}>
              {c.grade}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add lap-website/src/components/app/corners/CornerMasteryCard.tsx
git commit -m "feat: add CornerMasteryCard with real data from /corner-mastery"
```

---

### Task 8: Frontend — Create placeholder components

**Files:**
- Create: `lap-website/src/components/app/corners/ThrottleOnsetMap.tsx`
- Create: `lap-website/src/components/app/corners/ConsistencyHeatmap.tsx`

**Step 1: Write both placeholders**

```typescript
// lap-website/src/components/app/corners/ThrottleOnsetMap.tsx
export function ThrottleOnsetMap() {
  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs uppercase tracking-wider text-steel/50">Throttle Onset Map</h3>
        <span className="text-[9px] px-2 py-0.5 rounded bg-steel/10 text-steel/40">Coming Soon</span>
      </div>
      <div className="h-[140px] flex items-center justify-center border border-dashed border-steel/10 rounded-lg">
        <p className="text-steel/30 text-xs">Throttle application point per corner</p>
      </div>
    </div>
  );
}
```

```typescript
// lap-website/src/components/app/corners/ConsistencyHeatmap.tsx
export function ConsistencyHeatmap() {
  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs uppercase tracking-wider text-steel/50">Consistency Heatmap</h3>
        <span className="text-[9px] px-2 py-0.5 rounded bg-steel/10 text-steel/40">Coming Soon</span>
      </div>
      <div className="h-[140px] flex items-center justify-center border border-dashed border-steel/10 rounded-lg">
        <p className="text-steel/30 text-xs">Lap-to-lap consistency across corners</p>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add lap-website/src/components/app/corners/ThrottleOnsetMap.tsx lap-website/src/components/app/corners/ConsistencyHeatmap.tsx
git commit -m "feat: add ThrottleOnsetMap and ConsistencyHeatmap placeholders"
```

---

### Task 9: Frontend — Wire CornersTab into session page

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx:8,65-74,335,663-758`
- Update: `lap-website/src/components/app/corners/index.ts`

**Step 1: Update the index barrel export**

```typescript
// lap-website/src/components/app/corners/index.ts
export { CornersTab } from './CornersTab';
export type { CornerData } from './CornersTab';
```

**Step 2: Modify session page**

In `lap-website/src/app/app/sessions/[id]/page.tsx`:

1. **Line 8** — Replace import:
```typescript
// BEFORE:
import { SectorPanel, CornerReplay } from '@/components/shared/charts';
// AFTER:
import { SectorPanel } from '@/components/shared/charts';
import { CornersTab, type CornerData } from '@/components/app/corners';
```

2. **Lines 65-74** — Remove the inline `CornerData` interface (it's now exported from `corners/CornersTab.tsx`). Keep the `Tab` type and everything else.

3. **Line 335** — Update the corners tab render:
```typescript
// BEFORE:
{activeTab === 'corners' && <CornersTab corners={corners} sessionId={sessionId} />}
// AFTER (same JSX, but CornersTab now resolves from the new module):
{activeTab === 'corners' && <CornersTab corners={corners} sessionId={sessionId} />}
```

4. **Lines 663-758** — Delete the entire inline `CornersTab` function. It's replaced by the modular version.

**Step 3: Run build to verify**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no type errors.

**Step 4: Commit**

```bash
git add lap-website/src/app/app/sessions/[id]/page.tsx lap-website/src/components/app/corners/index.ts
git commit -m "feat: wire modular CornersTab into session detail page"
```

---

### Task 10: Cleanup — Remove legacy CornerReplay

**Files:**
- Delete: `lap-website/src/components/shared/charts/CornerReplay.tsx`
- Modify: `lap-website/src/components/shared/charts/index.ts` (remove CornerReplay export)

**Step 1: Remove the legacy component**

Delete `lap-website/src/components/shared/charts/CornerReplay.tsx`.

Update `lap-website/src/components/shared/charts/index.ts` to remove the `CornerReplay` export line.

**Step 2: Search for any remaining imports**

Run: `grep -r "CornerReplay" lap-website/src/ --include="*.tsx" --include="*.ts"`
Expected: Only hits in `components/app/corners/` (the new module) and potentially `components/app/corner-replay/` (orphaned, separate cleanup).

**Step 3: Run build**

Run: `cd lap-website && npm run build`
Expected: PASS

**Step 4: Commit**

```bash
git add -u lap-website/src/components/shared/charts/
git commit -m "chore: remove legacy CornerReplay from shared/charts"
```

---

### Task 11: Backend tests — Run full test suite

**Step 1: Run backend tests**

Run: `pytest telemetry_tool/tests/ -v --tb=short`
Expected: All pass, including the new corner tests from Task 1.

**Step 2: Run frontend tests**

Run: `cd lap-website && npm test`
Expected: All pass.

**Step 3: Final commit if any fixes needed**

---
