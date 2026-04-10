# Track Surface System — Follow-Up Layers Design

**Date**: 2026-04-10
**Status**: Approved
**Branch**: feat/logger-download-sync

## Context

Migration 047 (`track_surfaces` table), `track_surface.py` (aggregation module), orchestrator wiring (step 09j), and two API endpoints (`/track-surface`, `/track-delta`) are already built. This spec covers the four follow-up layers that consume the aggregate track surface.

## Layer 1: Solver Integration

### Goal
The theoretical lap solver uses aggregate grip from the track surface table instead of single-session grip, producing a physics-grounded speed ceiling.

### Changes

**File: `telemetry_tool/pipeline/stages/s10_theoretical.py`**

Before the existing grip_map override block (~line 549), insert:

```python
# Try aggregate grip first (requires PG + >=3 sessions)
if grip_map is None or grip_map.is_global_fallback:
    try:
        from track_surface import get_aggregate_grip
        from web.db import get_db_connection
        conn = get_db_connection()
        agg = get_aggregate_grip(conn, track_id)
        if agg is not None and agg.session_count >= 3:
            grip_map = agg
    except Exception:
        pass
```

The existing code at line 549-553 then applies `grip_map.mu_at(d, "p95")` as before. No interface change needed because `AggregateGrip.mu_at()` matches `GripMap.mu_at()`.

**Fallback chain**: aggregate grip (>=3 sessions) → session grip_map → global mu constant.

The `run_theoretical()` function signature gains an optional `track_id: str | None = None` parameter. The orchestrator passes `meta["track_id"]` through.

### Test
- Unit test: mock `get_aggregate_grip` returning a known AggregateGrip, verify `caps.mu` array uses aggregate values.
- Integration test: process 4 sessions at the same track, verify the 4th session's theoretical uses aggregate from the first 3.

## Layer 2: Track Map Grip Heatmap

### Goal
The existing 2.5D isometric `TrackMap.tsx` gains a grip heatmap mode showing per-meter grip headroom.

### Changes

**File: `lap-website/src/components/shared/charts/TrackMap.tsx`**

New prop:
```typescript
colorMode?: "speed" | "grip";
```

When `colorMode="grip"`:
1. Fetch `GET /api/v1/sessions/{sessionId}/track-delta?lap={lap}`
2. Map `headroom_pct` at each distance to a green→yellow→red gradient:
   - `headroom_pct > 15%` → green (`#22C55E` / acid-green)
   - `headroom_pct 5-15%` → gold (`#C9A84C`)
   - `headroom_pct < 5%` → red (`#FF2A2A` / safety-red)
3. Render with the same 2.5D isometric projection, line width, shadow
4. Legend overlay in top-right: "Grip Headroom" with color scale

When `colorMode="speed"` (default): existing behavior unchanged.

**File: `lap-website/src/app/app/sessions/[id]/page.tsx`**

Add a toggle button in the track map panel header:
```
[Speed] [Grip]   ← ghost-style toggle, font-telemetry
```

Default: "Speed". Switches `colorMode` prop on `TrackMap`.

### Data flow
```
Toggle click → colorMode state → TrackMap prop
  → (if "grip") fetch /track-delta
  → map headroom_pct → color per GPS segment
```

### Fallback
If `/track-delta` returns 404 (no aggregate data yet), show a steel-colored info badge: "Upload more sessions at this track to unlock grip analysis".

## Layer 3: Speed Trace Physics Ceiling

### Goal
The speed trace chart shows a "physics ceiling" line — the maximum possible speed at each meter given the aggregate track surface.

### Changes

**Backend: New endpoint in `data_v2.py`**

```
GET /api/v1/sessions/{id}/physics-ceiling?lap=N
```

Logic:
1. Get session's track_id from analysis_json
2. Get aggregate grip via `get_aggregate_grip(conn, track_id)`
3. Get session's reference line + curvature from analysis_json
4. Run a lightweight QSS solve: for each distance point, compute `v_max = sqrt(mu_p95(d) * g / kappa(d))` clamped by longitudinal limits from friction envelope
5. Return `{ distances: number[], ceiling_speeds_mps: number[], aggregate_sessions: int }`

This is a simplified QSS (no full forward-backward integration needed for the ceiling — it's the per-point cornering limit from aggregate grip).

**Frontend: `SpeedTraceChart.tsx`**

New prop:
```typescript
showPhysicsCeiling?: boolean;
```

When true:
1. Fetch `/physics-ceiling?lap=N`
2. Draw a dashed gold line (`#C9A84C`, dash `[8, 4]`) above the speed trace
3. Fill the area between actual speed and ceiling with `rgba(201, 168, 76, 0.08)` (gold at 8% opacity)
4. Label in legend: "Track Limit (N sessions)"

Integrates with existing `showTheoretical` — both can be visible simultaneously:
- Solid cyan = theoretical optimal (from session grip)
- Dashed gold = physics ceiling (from aggregate grip)
- Colored line = actual speed

### Session detail page

Add `showPhysicsCeiling={true}` when aggregate data is available (check via `/track-surface` 200 vs 404).

## Layer 4: Cross-Workspace Aggregation

### Goal
A global (non-workspace-scoped) track surface that pools data from all workspaces for richer models.

### Changes

**Migration 048: `track_surfaces_global`**

Same columns as `track_surfaces` minus `workspace_id`. No RLS. Primary key on `(track_id, distance_m)`.

**File: `track_surface.py`**

New function:
```python
def upsert_global_grip(conn, track_id, grip_map, friction_envelope=None):
    """Same as upsert_session_grip but targets track_surfaces_global.
    
    Called with a non-RLS connection (e.g., service account or 
    SET LOCAL disabled).
    """
```

New function:
```python
def get_global_aggregate_grip(conn, track_id) -> AggregateGrip | None:
    """Read from track_surfaces_global."""
```

**Orchestrator wiring (step 09j enhancement)**

After the workspace upsert, also upsert to global:
```python
if _grip_map is not None:
    try:
        upsert_global_grip(_ts_conn, _ts_track_id, _grip_map, _friction_envelope_result)
    except Exception:
        pass
```

Note: The global upsert needs to bypass RLS. The `track_surfaces_global` table has no RLS policy, so any connection can write to it directly — no bypass needed. The workspace-scoped `track_surfaces` table keeps its RLS. Only the global table is policy-free.

**Solver fallback chain update**

```
workspace aggregate (>=3 sessions)
  → global aggregate (>=5 sessions)
    → session grip_map
      → global mu constant (1.0)
```

**New API endpoint**

```
GET /api/v1/tracks/{track_id}/global-surface
```

Returns the global aggregate. No workspace filtering. Available to all authenticated users.

**Privacy**: Only aggregate statistics (mean/p95 grip per distance bin) flow to global. No session identifiers, driver names, or per-session data.

## Implementation Order

1. **Layer 1** (solver integration) — backend only, no frontend changes, enables everything else
2. **Layer 3** (physics ceiling endpoint + SpeedTraceChart) — highest user-visible impact
3. **Layer 2** (TrackMap grip heatmap) — second visual feature
4. **Layer 4** (cross-workspace) — migration + backend, low risk

Layers 1-3 can ship independently. Layer 4 is additive.

## File Manifest

| Layer | File | Action |
|-------|------|--------|
| 1 | `telemetry_tool/pipeline/stages/s10_theoretical.py` | Edit: add aggregate grip lookup before session grip |
| 1 | `telemetry_tool/pipeline/orchestrator.py` | Edit: pass track_id to s10_theoretical |
| 1 | `telemetry_tool/tests/test_track_surface.py` | Edit: add solver integration tests |
| 2 | `lap-website/src/components/shared/charts/TrackMap.tsx` | Edit: add colorMode prop + grip heatmap rendering |
| 2 | `lap-website/src/app/app/sessions/[id]/page.tsx` | Edit: add speed/grip toggle |
| 3 | `telemetry_tool/web/routes/data_v2.py` | Edit: add /physics-ceiling endpoint |
| 3 | `lap-website/src/components/shared/charts/SpeedTraceChart.tsx` | Edit: add showPhysicsCeiling prop + ceiling line |
| 4 | `telemetry_tool/alembic/versions/048_track_surfaces_global.py` | Create: global table migration |
| 4 | `telemetry_tool/track_surface.py` | Edit: add global upsert + global read functions |
| 4 | `telemetry_tool/pipeline/orchestrator.py` | Edit: add global upsert call in step 09j |
| 4 | `telemetry_tool/web/routes/data_v2.py` | Edit: add /tracks/{id}/global-surface endpoint |
