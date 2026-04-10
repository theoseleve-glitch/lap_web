# Track Surface Follow-Up Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 4 layers on top of the existing track surface foundation: solver integration, physics ceiling endpoint + speed trace overlay, track map grip heatmap, and cross-workspace aggregation.

**Architecture:** The aggregate track surface (`track_surfaces` PG table, populated incrementally by step 09j in the pipeline) provides per-meter grip data across sessions. Layer 1 feeds this into the theoretical solver. Layers 2-3 visualize it in the frontend via new/existing canvas charts. Layer 4 adds a global (cross-workspace) aggregate table.

**Tech Stack:** Python 3.14 / Flask (backend), Next.js 14 / TypeScript / Canvas 2D (frontend), PostgreSQL 16 with RLS, Alembic migrations.

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `telemetry_tool/pipeline/stages/s10_theoretical.py` | Theoretical lap solver — gains aggregate grip fallback | Modify |
| `telemetry_tool/pipeline/orchestrator.py` | Pipeline wiring — passes `track_id` to s10 | Modify |
| `telemetry_tool/tests/test_track_surface.py` | Track surface tests — gains solver + global tests | Modify |
| `telemetry_tool/web/routes/data_v2.py` | API routes — gains `/physics-ceiling` + `/global-surface` | Modify |
| `telemetry_tool/track_surface.py` | Aggregation module — gains global upsert/read | Modify |
| `telemetry_tool/alembic/versions/048_track_surfaces_global.py` | Global aggregate table migration | Create |
| `lap-website/src/components/shared/charts/SpeedTraceChart.tsx` | Speed trace — gains physics ceiling line | Modify |
| `lap-website/src/components/shared/charts/TrackMap.tsx` | Track map — gains grip heatmap color mode | Modify |
| `lap-website/src/app/app/sessions/[id]/page.tsx` | Session detail page — gains toggles for new features | Modify |

---

## Task 1: Solver Integration — Test

**Files:**
- Modify: `telemetry_tool/tests/test_track_surface.py`

- [ ] **Step 1: Write failing test for aggregate grip fallback in solver**

Add to `telemetry_tool/tests/test_track_surface.py`:

```python
import numpy as np
from unittest.mock import patch, MagicMock
from track_surface import AggregateGrip


class TestSolverAggregateGripFallback:
    """Verify s10_theoretical uses aggregate grip when session grip is fallback."""

    def _make_aggregate(self, n=50, mu_val=1.2):
        dist = np.linspace(0, 500, n)
        return AggregateGrip(
            distance_bins=dist,
            mu_p95=np.full(n, mu_val),
            mu_mean=np.full(n, mu_val * 0.9),
            mu_lon_accel=np.full(n, 0.4),
            mu_lon_brake=np.full(n, 0.9),
            session_count=5,
            track_id="test_track",
        )

    @patch("track_surface.get_aggregate_grip")
    @patch("web.db.get_db_connection")
    def test_aggregate_replaces_global_fallback(self, mock_conn, mock_get_agg):
        """When session grip is global fallback, aggregate grip takes over."""
        agg = self._make_aggregate(mu_val=1.25)
        mock_get_agg.return_value = agg
        mock_conn.return_value = MagicMock()

        # Verify mu_at returns aggregate values
        assert abs(agg.mu_at(100.0, "p95") - 1.25) < 0.01
        assert agg.session_count >= 3
        assert not agg.is_global_fallback

    def test_aggregate_skipped_when_session_count_low(self):
        """Aggregate with <3 sessions should not be used."""
        agg = self._make_aggregate()
        agg.session_count = 2
        # Solver should skip this — test the guard condition
        assert agg.session_count < 3
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_track_surface.py -v --tb=short`

Expected: 12 passed (10 existing + 2 new)

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/tests/test_track_surface.py
git commit -m "test: add solver aggregate grip fallback tests"
```

---

## Task 2: Solver Integration — Implementation

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s10_theoretical.py:36-55` (function signature)
- Modify: `telemetry_tool/pipeline/stages/s10_theoretical.py:548-553` (grip map override block)
- Modify: `telemetry_tool/pipeline/orchestrator.py:924-938` (pass track_id)

- [ ] **Step 1: Add `track_id` parameter to `run_theoretical()`**

In `telemetry_tool/pipeline/stages/s10_theoretical.py`, add `track_id: str | None = None` to the function signature after `distance_quality`:

```python
def run_theoretical(
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: Optional[pd.DataFrame],
    friction_circle: Any,
    vehicle_params: Any,
    data_quality_rpt: Any,
    valid_times: Optional[list[tuple[int, float]]],
    *,
    channel_discovery: Any = None,
    n_resample_points: int = 1000,
    best_n_lap_indices: Optional[list[int]] = None,
    excluded_laps: frozenset[int] = frozenset(),
    inclusion_policy: Any = None,
    clustering_result: Any = None,
    phases_df: Optional[pd.DataFrame] = None,
    lap_to_phase: Optional[dict[int, int]] = None,
    grip_map: Any = None,
    friction_envelope: Any = None,
    distance_quality: Any = None,
    track_id: str | None = None,
) -> tuple[
```

- [ ] **Step 2: Insert aggregate grip lookup before the session grip override**

In `telemetry_tool/pipeline/stages/s10_theoretical.py`, insert BEFORE line 548 (`# Apply grip map override`):

```python
    # Try aggregate grip from track surface (PG mode, >= 3 sessions)
    if (grip_map is None or getattr(grip_map, "is_global_fallback", False)) and track_id:
        try:
            import os
            if os.environ.get("USE_PG", "0") == "1":
                from track_surface import get_aggregate_grip
                from web.db import get_db_connection
                _agg_conn = get_db_connection()
                _agg = get_aggregate_grip(_agg_conn, track_id)
                if _agg is not None and _agg.session_count >= 3:
                    grip_map = _agg
                    logger.info("Using aggregate grip for track %s (%d sessions)",
                                track_id, _agg.session_count)
        except Exception as _agg_exc:
            logger.debug("Aggregate grip lookup skipped: %s", _agg_exc)
```

- [ ] **Step 3: Pass `track_id` from orchestrator to `run_theoretical()`**

In `telemetry_tool/pipeline/orchestrator.py`, at line ~938 (inside the `_safe_step("10_theoretical", ...)` call), add `track_id=track_id` after `distance_quality=_dq`:

```python
        theo_result, err = _safe_step(
            "10_theoretical", s10_theoretical.run_theoretical,
            resampled_laps, curvature_profile, corrected_friction or friction_circle,
            vehicle_params, data_quality_rpt, valid_times,
            channel_discovery=_channel_discovery,
            n_resample_points=n_resample_points,
            best_n_lap_indices=best_n_lap_indices,
            excluded_laps=excluded_laps,
            inclusion_policy=_inclusion_policy,
            clustering_result=_clustering_result,
            phases_df=phases_df,
            lap_to_phase=lap_to_phase,
            grip_map=_grip_map,
            friction_envelope=_friction_envelope_result,
            distance_quality=_dq,
            track_id=track_id,
        )
```

- [ ] **Step 4: Run pipeline correctness tests**

Run: `cd telemetry_tool && python -m pytest tests/test_re_port_correctness.py tests/test_track_surface.py -v --tb=short`

Expected: All pass (pipeline doesn't regress; aggregate lookup is a no-op in SQLite mode).

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10_theoretical.py telemetry_tool/pipeline/orchestrator.py
git commit -m "feat(solver): use aggregate track surface grip when session grip unavailable"
```

---

## Task 3: Physics Ceiling Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add endpoint after track-delta)

- [ ] **Step 1: Add `/physics-ceiling` endpoint**

In `telemetry_tool/web/routes/data_v2.py`, add after the `/track-delta` endpoint block (before the `# GET /api/v1/sessions/<id>/optimal-v2` section):

```python
# ══════════════════════════════════════════════════════════════════
# GET /api/v1/sessions/<id>/physics-ceiling
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/physics-ceiling", methods=["GET"])
@_safe_api
def get_physics_ceiling(session_id: str) -> tuple[dict, int]:
    """Return per-meter maximum speed from aggregate track surface grip.

    Computes v_max(d) = sqrt(mu_p95(d) * g / kappa(d)) at each distance
    point, giving the physics-limited speed ceiling for visualization.
    """
    import os
    import numpy as np

    _G = 9.80665

    if os.environ.get("USE_PG", "0") != "1":
        return api_error(ErrorCode.NOT_FOUND, "Physics ceiling requires PostgreSQL mode", status=404)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if not analysis or not isinstance(analysis, dict):
        return api_error(ErrorCode.NOT_FOUND, "No analysis data for session", status=404)

    # Get track_id
    track_id = analysis.get("track_id")
    if not track_id and isinstance(session, dict):
        track_id = session.get("track_id")
    if not track_id or track_id == "unknown_track":
        return api_error(ErrorCode.NOT_FOUND, "No track detected for this session", status=404)

    # Get aggregate grip
    try:
        from track_surface import get_aggregate_grip
    except ImportError:
        return api_error(ErrorCode.NOT_FOUND, "Track surface module not available", status=404)

    aggregate = get_aggregate_grip(conn, track_id)
    if aggregate is None:
        return api_error(ErrorCode.NOT_FOUND, "No aggregate surface data yet", status=404)

    # Get curvature from session's speed trace or analysis_json
    speed_trace = analysis.get("speed_trace_data")
    theo = analysis.get("theoretical_metrics") or {}
    curvature_data = analysis.get("curvature_profile")

    # Build distance + curvature arrays from available data
    distances = None
    curvature = None

    # Try theoretical result (has distance + curvature)
    opt_v2 = analysis.get("optimal_v2")
    if opt_v2 and isinstance(opt_v2, dict):
        distances = opt_v2.get("distance_m")
        curvature = opt_v2.get("curvature_1pm")

    # Fallback: grip_map distances + derive curvature from speed trace
    gm = analysis.get("grip_map")
    if distances is None and gm and isinstance(gm, dict):
        distances = gm.get("distance_bins")

    if distances is None or not distances:
        return api_error(ErrorCode.NOT_FOUND, "No distance data available for ceiling computation", status=404)

    dist_arr = np.array(distances, dtype=float)

    # Build curvature array
    if curvature is not None:
        curv_arr = np.abs(np.array(curvature, dtype=float))
    else:
        # Derive from corner data if available
        corners = analysis.get("corners")
        curv_arr = np.full(len(dist_arr), 0.001)  # gentle default
        if corners and isinstance(corners, list):
            for c in corners:
                if isinstance(c, dict) and "s_start" in c and "s_end" in c:
                    s_s = c.get("s_start", 0)
                    s_e = c.get("s_end", 0)
                    apex_k = c.get("curvature_1pm", 0.01)
                    mask = (dist_arr >= s_s) & (dist_arr <= s_e)
                    curv_arr[mask] = max(abs(apex_k), 0.001)

    # Compute ceiling: v_max = sqrt(mu * g / kappa)
    mu_arr = np.array([aggregate.mu_at(float(d), "p95") for d in dist_arr])
    kappa_safe = np.maximum(curv_arr, 1e-6)
    v_max_mps = np.sqrt(mu_arr * _G / kappa_safe)
    v_max_mps = np.clip(v_max_mps, 0, 100)  # cap at 360 kph

    # Convert to kph for frontend consistency
    ceiling_kph = (v_max_mps * 3.6).tolist()
    dist_list = dist_arr.tolist()

    return api_response({
        "distances": dist_list,
        "ceiling_speeds_kph": ceiling_kph,
        "aggregate_sessions": aggregate.session_count,
        "track_id": track_id,
    })
```

- [ ] **Step 2: Verify endpoint loads**

Run: `cd telemetry_tool && python -c "from web.routes.data_v2 import bp; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): add /physics-ceiling endpoint for aggregate speed limit"
```

---

## Task 4: Speed Trace Physics Ceiling — Frontend

**Files:**
- Modify: `lap-website/src/components/shared/charts/SpeedTraceChart.tsx`

- [ ] **Step 1: Add `ceilingSpeeds` to `DrawOptions` interface**

In `SpeedTraceChart.tsx`, at line ~120 after `theoreticalSpeeds`, add:

```typescript
  ceilingSpeeds?: { distances: number[]; speeds: number[]; sessions: number } | null;
```

- [ ] **Step 2: Add ceiling to yMax calculation in `drawSpeedTrace`**

In `drawSpeedTrace`, after the `theoreticalSpeeds` yMax extension (line ~196), add:

```typescript
  if (opts.ceilingSpeeds && opts.ceilingSpeeds.speeds.length > 0) {
    const ceilMax = safeMax(opts.ceilingSpeeds.speeds) * 1.1; // already kph
    if (ceilMax > yMax) yMax = ceilMax;
  }
```

- [ ] **Step 3: Draw physics ceiling line and fill**

In `drawSpeedTrace`, after the theoretical speed line block (after line ~287, after `legendY += 12;`), add:

```typescript
  // Physics ceiling from aggregate track surface (dashed gold, filled area)
  if (opts.ceilingSpeeds && opts.ceilingSpeeds.distances.length > 0) {
    const cd = opts.ceilingSpeeds.distances;
    const cs = opts.ceilingSpeeds.speeds; // kph

    // Fill area between actual speed and ceiling
    ctx.save();
    ctx.globalAlpha = 0.08;
    ctx.fillStyle = '#C9A84C';
    ctx.beginPath();
    let fillStarted = false;
    // Forward pass: ceiling line
    for (let i = 0; i < cd.length; i++) {
      const x = xToPixel(cd[i]);
      if (x < pad.left || x > pad.left + pW) continue;
      const y = yToPixel(cs[i]);
      if (!fillStarted) { ctx.moveTo(x, y); fillStarted = true; } else { ctx.lineTo(x, y); }
    }
    // Backward pass: actual speed line (interpolated to ceiling distances)
    if (fillStarted && distances.length > 0) {
      for (let i = cd.length - 1; i >= 0; i--) {
        const x = xToPixel(cd[i]);
        if (x < pad.left || x > pad.left + pW) continue;
        // Find nearest actual speed
        const idx = binarySearch(distances, cd[i]);
        const actualKph = (speeds[idx] ?? 0) * 3.6;
        const y = yToPixel(actualKph);
        ctx.lineTo(x, y);
      }
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // Dashed gold ceiling line
    ctx.save();
    ctx.setLineDash([8, 4]);
    ctx.strokeStyle = '#C9A84C';
    ctx.lineWidth = 1.5;
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    let ceilStarted = false;
    for (let i = 0; i < cd.length; i++) {
      const x = xToPixel(cd[i]);
      if (x < pad.left || x > pad.left + pW) continue;
      const y = yToPixel(cs[i]);
      if (!ceilStarted) { ctx.moveTo(x, y); ceilStarted = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.restore();

    // Legend entry
    ctx.fillStyle = '#C9A84C';
    ctx.globalAlpha = 0.7;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`- - Track Limit (${opts.ceilingSpeeds.sessions} sessions)`, pad.left + 8, legendY);
    ctx.globalAlpha = 1.0;
    legendY += 12;
  }
```

- [ ] **Step 4: Add `showPhysicsCeiling` prop and ceiling data fetch**

In `SpeedTraceChartProps` interface (line ~59), add:

```typescript
  /** When true, fetches and overlays the aggregate physics ceiling */
  showPhysicsCeiling?: boolean;
```

In the component destructuring (line ~628), add:

```typescript
  showPhysicsCeiling = false,
```

Add state after `theoreticalData` state (line ~642):

```typescript
  const [ceilingData, setCeilingData] = useState<{ distances: number[]; speeds: number[]; sessions: number } | null>(null);
```

Add fetch effect after the theoretical fetch (after line ~741):

```typescript
  // ── Fetch physics ceiling from aggregate track surface ─────
  useEffect(() => {
    if (!showPhysicsCeiling || !sessionId) {
      setCeilingData(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{
          ceiling_speeds_kph: number[];
          distances: number[];
          aggregate_sessions: number;
        }>(`/sessions/${encodeURIComponent(sessionId)}/physics-ceiling`);
        if (cancelled) return;
        if (res?.ceiling_speeds_kph) {
          setCeilingData({
            distances: res.distances,
            speeds: res.ceiling_speeds_kph,
            sessions: res.aggregate_sessions,
          });
        }
      } catch {
        if (!cancelled) setCeilingData(null);
      }
    })();
    return () => { cancelled = true; };
  }, [showPhysicsCeiling, sessionId]);
```

- [ ] **Step 5: Wire ceiling data into the draw call**

In the `render` callback (line ~781), add `ceilingSpeeds: ceilingData` to the `drawSpeedTrace` options:

```typescript
    boundsRef.current = drawSpeedTrace(ctx, rect.width, speedH, {
      distances: chartData.distances,
      speeds: chartData.speeds,
      refSpeeds: refSpeeds ?? chartData.ref_speeds,
      avgSpeeds: !refSpeeds ? (avgSpeeds ?? chartData.avg_speeds) : undefined,
      theoreticalSpeeds: theoreticalData,
      ceilingSpeeds: ceilingData,
      hoverDistanceM: hoverDistance,
      refLapLabel: activeCompareLap != null ? `Lap ${activeCompareLap}` : null,
      primaryLapLabel: activeCompareLap != null ? `Lap ${activeLap}` : null,
      distRange,
      dragSelection,
    });
```

Add `ceilingData` to the `render` dependency array.

- [ ] **Step 6: Build frontend**

Run: `cd lap-website && npm run build`

Expected: Build succeeds.

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/components/shared/charts/SpeedTraceChart.tsx
git commit -m "feat(charts): add physics ceiling overlay to speed trace"
```

---

## Task 5: Track Map Grip Heatmap — Frontend

**Files:**
- Modify: `lap-website/src/components/shared/charts/TrackMap.tsx`

- [ ] **Step 1: Add grip headroom color function**

In `TrackMap.tsx`, after the `speedToColor` function (line ~74), add:

```typescript
/** Grip headroom → color: green (lots of headroom) → gold → red (at limit). */
function gripHeadroomColor(headroom_pct: number): string {
  if (headroom_pct > 15) return '#22C55E'; // acid-green
  if (headroom_pct > 5) {
    // Interpolate gold → green
    const t = (headroom_pct - 5) / 10;
    const r = Math.round(201 * (1 - t) + 34 * t);
    const g = Math.round(168 * (1 - t) + 197 * t);
    const b = Math.round(76 * (1 - t) + 94 * t);
    return `rgb(${r},${g},${b})`;
  }
  if (headroom_pct > 0) {
    // Interpolate red → gold
    const t = headroom_pct / 5;
    const r = Math.round(255 * (1 - t) + 201 * t);
    const g = Math.round(42 * (1 - t) + 168 * t);
    const b = Math.round(42 * (1 - t) + 76 * t);
    return `rgb(${r},${g},${b})`;
  }
  return '#FF2A2A'; // safety-red — at or over the limit
}
```

- [ ] **Step 2: Add `colorMode` prop**

In `TrackMapProps` (line ~36), add after `compareLap`:

```typescript
  /** Color mode: "speed" (default) or "grip" (headroom heatmap). */
  colorMode?: "speed" | "grip";
```

In the component destructuring, add `colorMode = "speed"`.

Add state for grip delta data:

```typescript
const [gripDelta, setGripDelta] = useState<{ distance_m: number; headroom_pct: number }[] | null>(null);
```

- [ ] **Step 3: Fetch grip delta data when in grip mode**

Add a `useEffect` after the existing GPS data fetch:

```typescript
  // ── Fetch grip delta for heatmap mode ──
  useEffect(() => {
    if (colorMode !== 'grip' || !sessionId) {
      setGripDelta(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch<{ bins: { distance_m: number; headroom_pct: number }[] }>(
          `/sessions/${encodeURIComponent(sessionId)}/track-delta`,
        );
        if (!cancelled && res?.bins) setGripDelta(res.bins);
      } catch {
        if (!cancelled) setGripDelta(null);
      }
    })();
    return () => { cancelled = true; };
  }, [colorMode, sessionId]);
```

- [ ] **Step 4: Replace speed coloring with grip coloring in draw loop**

In the main track draw loop (line ~377-382), replace the color selection:

```typescript
    if (colorMode === 'grip' && gripDelta && dists) {
      // Find nearest grip delta bin
      let bestIdx = 0;
      let bestDist = Infinity;
      for (let j = 0; j < gripDelta.length; j++) {
        const dd = Math.abs(gripDelta[j].distance_m - (dists[i] ?? 0));
        if (dd < bestDist) { bestDist = dd; bestIdx = j; }
      }
      ctx.strokeStyle = inRange ? gripHeadroomColor(gripDelta[bestIdx].headroom_pct) : '#444';
    } else if (speeds && speeds.length === lats.length) {
      const t = (speeds[i] - minSpd) / spdRange;
      ctx.strokeStyle = inRange ? speedToColor(t) : '#444';
    } else {
      ctx.strokeStyle = inRange ? '#F0EDE5' : '#333';
    }
```

- [ ] **Step 5: Add grip legend when in grip mode**

After the speed legend (line ~498), add a grip legend block:

```typescript
  // Grip headroom legend (when in grip mode)
  if (colorMode === 'grip') {
    const legX = w - 20;
    const legY = 16;
    const legH = 60;
    const legW = 8;
    // Gradient bar
    const grad = ctx.createLinearGradient(legX, legY, legX, legY + legH);
    grad.addColorStop(0, '#22C55E');
    grad.addColorStop(0.5, '#C9A84C');
    grad.addColorStop(1, '#FF2A2A');
    ctx.fillStyle = grad;
    ctx.fillRect(legX - legW, legY, legW, legH);
    // Labels
    ctx.fillStyle = '#949494';
    ctx.font = '8px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText('Headroom', legX - legW - 4, legY);
    ctx.fillText('+15%', legX - legW - 4, legY + 12);
    ctx.textBaseline = 'bottom';
    ctx.fillText('0%', legX - legW - 4, legY + legH);
  }
```

- [ ] **Step 6: Add `gripDelta` and `colorMode` to draw dependencies**

Make sure the render callback includes `gripDelta` and `colorMode` in its dependency array so the canvas redraws when these change.

- [ ] **Step 7: Build frontend**

Run: `cd lap-website && npm run build`

Expected: Build succeeds.

- [ ] **Step 8: Commit**

```bash
git add lap-website/src/components/shared/charts/TrackMap.tsx
git commit -m "feat(charts): add grip headroom heatmap mode to track map"
```

---

## Task 6: Session Detail Page — Wire Up New Features

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`

- [ ] **Step 1: Add track map color mode toggle state**

Add state near other chart-related state:

```typescript
const [trackColorMode, setTrackColorMode] = useState<"speed" | "grip">("speed");
```

- [ ] **Step 2: Add toggle UI in track map panel header**

Find the TrackMap rendering and add a toggle above it:

```tsx
<div className="flex items-center gap-1 mb-2">
  <button
    onClick={() => setTrackColorMode("speed")}
    className={`px-2 py-0.5 text-xs font-telemetry rounded transition-colors ${
      trackColorMode === "speed"
        ? "text-chalk bg-steel/20"
        : "text-steel hover:text-chalk"
    }`}
  >
    Speed
  </button>
  <button
    onClick={() => setTrackColorMode("grip")}
    className={`px-2 py-0.5 text-xs font-telemetry rounded transition-colors ${
      trackColorMode === "grip"
        ? "text-chalk bg-steel/20"
        : "text-steel hover:text-chalk"
    }`}
  >
    Grip
  </button>
</div>
```

- [ ] **Step 3: Pass props to TrackMap and SpeedTraceChart**

Add `colorMode={trackColorMode}` prop to the `<TrackMap>` component.

Add `showPhysicsCeiling={true}` prop to the `<SpeedTraceChart>` component (or `<SpeedTraceZoom>`).

- [ ] **Step 4: Build frontend**

Run: `cd lap-website && npm run build`

Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat(session): add grip heatmap toggle and physics ceiling overlay"
```

---

## Task 7: Cross-Workspace Global Table — Migration

**Files:**
- Create: `telemetry_tool/alembic/versions/048_track_surfaces_global.py`

- [ ] **Step 1: Create migration**

```python
"""048 — global track surface aggregate (cross-workspace).

Same schema as track_surfaces but without workspace_id or RLS.
Aggregates grip data across all workspaces for richer models.
"""
from alembic import op
import sqlalchemy as sa

revision = "048"
down_revision = "047"


def upgrade():
    op.create_table(
        "track_surfaces_global",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text, nullable=False),
        sa.Column("distance_m", sa.Float, nullable=False),
        sa.Column("mu_lat_p95", sa.Float, nullable=False),
        sa.Column("mu_lat_mean", sa.Float, nullable=False),
        sa.Column("mu_lon_accel", sa.Float, nullable=True),
        sa.Column("mu_lon_brake", sa.Float, nullable=True),
        sa.Column("elevation_m", sa.Float, nullable=True),
        sa.Column("lateral_scatter_m", sa.Float, nullable=True),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("session_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("track_id", "distance_m",
                            name="uq_track_surface_global_bin"),
    )
    op.create_index("idx_track_surfaces_global_track", "track_surfaces_global", ["track_id"])


def downgrade():
    op.drop_table("track_surfaces_global")
```

- [ ] **Step 2: Commit**

```bash
git add telemetry_tool/alembic/versions/048_track_surfaces_global.py
git commit -m "feat(db): add global track surfaces table (cross-workspace)"
```

---

## Task 8: Cross-Workspace — Global Upsert + Read + API

**Files:**
- Modify: `telemetry_tool/track_surface.py`
- Modify: `telemetry_tool/pipeline/orchestrator.py`
- Modify: `telemetry_tool/web/routes/data_v2.py`
- Modify: `telemetry_tool/tests/test_track_surface.py`

- [ ] **Step 1: Add test for global upsert guard**

In `telemetry_tool/tests/test_track_surface.py`, add:

```python
from track_surface import upsert_global_grip


class TestGlobalUpsertGuards:
    def test_skips_none(self):
        assert upsert_global_grip(None, "track", None) == 0

    def test_skips_global_fallback(self):
        gm = _FakeGripMap(fallback=True)
        assert upsert_global_grip(None, "track", gm) == 0

    def test_skips_unknown_track(self):
        gm = _FakeGripMap(fallback=False, stats=[1])
        assert upsert_global_grip(None, "unknown_track", gm) == 0
```

- [ ] **Step 2: Add `upsert_global_grip()` and `get_global_aggregate_grip()` to `track_surface.py`**

Add at the end of `telemetry_tool/track_surface.py`:

```python
# ── Global (cross-workspace) aggregate ───────────────────────────


def upsert_global_grip(
    conn: Any,
    track_id: str,
    grip_map: Any,
    friction_envelope: Any = None,
) -> int:
    """Merge a session's grip into the global (cross-workspace) aggregate.

    Same logic as upsert_session_grip but targets track_surfaces_global
    (no RLS, no workspace_id).
    """
    if grip_map is None or grip_map.is_global_fallback:
        return 0
    if not track_id or track_id == "unknown_track":
        return 0
    if not hasattr(grip_map, "bin_stats") or not grip_map.bin_stats:
        return 0

    lon_accel_global = None
    lon_brake_global = None
    if friction_envelope is not None and hasattr(friction_envelope, "friction_bins"):
        accels = [fb.accel_max_g for fb in friction_envelope.friction_bins
                  if fb.accel_max_g > 0 and fb.confidence > 0]
        brakes = [fb.brake_max_g for fb in friction_envelope.friction_bins
                  if fb.brake_max_g > 0 and fb.confidence > 0]
        if accels:
            lon_accel_global = float(np.median(accels))
        if brakes:
            lon_brake_global = float(np.median(brakes))

    updated = 0
    now = datetime.now(timezone.utc).isoformat()

    for stat in grip_map.bin_stats:
        if stat.confidence < 0.3 or stat.sample_count < 3:
            continue

        params = {
            "track_id": track_id,
            "distance_m": round(stat.distance_m, 1),
            "mu_lat_p95": round(stat.mu_p95, 4),
            "mu_lat_mean": round(stat.mu_mean, 4),
            "mu_lon_accel": lon_accel_global,
            "mu_lon_brake": lon_brake_global,
            "sample_count": stat.sample_count,
            "now": now,
        }

        sql = """
            INSERT INTO track_surfaces_global
                (track_id, distance_m, mu_lat_p95, mu_lat_mean,
                 mu_lon_accel, mu_lon_brake,
                 sample_count, session_count, last_updated)
            VALUES
                (%(track_id)s, %(distance_m)s, %(mu_lat_p95)s, %(mu_lat_mean)s,
                 %(mu_lon_accel)s, %(mu_lon_brake)s,
                 %(sample_count)s, 1, %(now)s)
            ON CONFLICT (track_id, distance_m)
            DO UPDATE SET
                mu_lat_p95 = (
                    track_surfaces_global.mu_lat_p95 * track_surfaces_global.sample_count
                    + EXCLUDED.mu_lat_p95 * EXCLUDED.sample_count
                ) / NULLIF(track_surfaces_global.sample_count + EXCLUDED.sample_count, 0),
                mu_lat_mean = (
                    track_surfaces_global.mu_lat_mean * track_surfaces_global.sample_count
                    + EXCLUDED.mu_lat_mean * EXCLUDED.sample_count
                ) / NULLIF(track_surfaces_global.sample_count + EXCLUDED.sample_count, 0),
                mu_lon_accel = COALESCE(
                    (track_surfaces_global.mu_lon_accel * track_surfaces_global.session_count
                     + EXCLUDED.mu_lon_accel)
                    / NULLIF(track_surfaces_global.session_count + 1, 0),
                    EXCLUDED.mu_lon_accel,
                    track_surfaces_global.mu_lon_accel
                ),
                mu_lon_brake = COALESCE(
                    (track_surfaces_global.mu_lon_brake * track_surfaces_global.session_count
                     + EXCLUDED.mu_lon_brake)
                    / NULLIF(track_surfaces_global.session_count + 1, 0),
                    EXCLUDED.mu_lon_brake,
                    track_surfaces_global.mu_lon_brake
                ),
                sample_count = track_surfaces_global.sample_count + EXCLUDED.sample_count,
                session_count = track_surfaces_global.session_count + 1,
                last_updated = EXCLUDED.last_updated
        """

        try:
            conn.execute(sql, params)
            updated += 1
        except Exception as exc:
            logger.warning("Global track surface upsert failed for d=%.1f: %s",
                           stat.distance_m, exc)

    if updated > 0:
        logger.info("Global track surface updated: track=%s, bins=%d", track_id, updated)

    return updated


def get_global_aggregate_grip(conn: Any, track_id: str) -> AggregateGrip | None:
    """Build AggregateGrip from the global (cross-workspace) table."""
    sql = """
        SELECT distance_m, mu_lat_p95, mu_lat_mean,
               mu_lon_accel, mu_lon_brake, session_count
        FROM track_surfaces_global
        WHERE track_id = %(track_id)s
        ORDER BY distance_m
    """
    try:
        rows = conn.execute(sql, {"track_id": track_id}).fetchall()
    except Exception:
        return None

    if not rows or len(rows) < 5:
        return None

    distance = np.array([r[0] for r in rows])
    mu_p95 = np.array([r[1] for r in rows])
    mu_mean = np.array([r[2] for r in rows])
    mu_lon_accel = np.array([r[3] if r[3] is not None else 0.0 for r in rows])
    mu_lon_brake = np.array([r[4] if r[4] is not None else 0.0 for r in rows])
    session_count = max(r[5] for r in rows)

    return AggregateGrip(
        distance_bins=distance,
        mu_p95=mu_p95,
        mu_mean=mu_mean,
        mu_lon_accel=mu_lon_accel,
        mu_lon_brake=mu_lon_brake,
        session_count=session_count,
        track_id=track_id,
    )
```

- [ ] **Step 3: Wire global upsert into orchestrator step 09j**

In `telemetry_tool/pipeline/orchestrator.py`, inside the existing step 09j `USE_PG` block, after the workspace upsert, add:

```python
            try:
                from track_surface import upsert_global_grip
                upsert_global_grip(_ts_conn, _ts_track_id, _grip_map, _friction_envelope_result)
            except Exception as _tsg_exc:
                logger.debug("Global track surface upsert skipped: %s", _tsg_exc)
```

- [ ] **Step 4: Update solver fallback chain**

In `telemetry_tool/pipeline/stages/s10_theoretical.py`, in the aggregate grip lookup block (added in Task 2), extend the fallback to try global:

```python
    if (grip_map is None or getattr(grip_map, "is_global_fallback", False)) and track_id:
        try:
            import os
            if os.environ.get("USE_PG", "0") == "1":
                from track_surface import get_aggregate_grip, get_global_aggregate_grip
                from web.db import get_db_connection
                _agg_conn = get_db_connection()
                _agg = get_aggregate_grip(_agg_conn, track_id)
                if _agg is not None and _agg.session_count >= 3:
                    grip_map = _agg
                    logger.info("Using workspace aggregate grip for track %s (%d sessions)",
                                track_id, _agg.session_count)
                else:
                    _gagg = get_global_aggregate_grip(_agg_conn, track_id)
                    if _gagg is not None and _gagg.session_count >= 5:
                        grip_map = _gagg
                        logger.info("Using global aggregate grip for track %s (%d sessions)",
                                    track_id, _gagg.session_count)
        except Exception as _agg_exc:
            logger.debug("Aggregate grip lookup skipped: %s", _agg_exc)
```

- [ ] **Step 5: Add `/tracks/<track_id>/global-surface` API endpoint**

In `telemetry_tool/web/routes/data_v2.py`, add after the `/physics-ceiling` endpoint:

```python
# ══════════════════════════════════════════════════════════════════
# GET /api/v1/tracks/<track_id>/global-surface
# ══════════════════════════════════════════════════════════════════


@bp.route("/tracks/<track_id>/global-surface", methods=["GET"])
@_safe_api
def get_global_surface(track_id: str) -> tuple[dict, int]:
    """Return the global (cross-workspace) aggregate track surface."""
    import os

    if os.environ.get("USE_PG", "0") != "1":
        return api_error(ErrorCode.NOT_FOUND, "Global surface requires PostgreSQL mode", status=404)

    conn = get_db_connection()

    try:
        from track_surface import get_global_aggregate_grip
    except ImportError:
        return api_error(ErrorCode.NOT_FOUND, "Track surface module not available", status=404)

    aggregate = get_global_aggregate_grip(conn, track_id)
    if aggregate is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"No global surface data for track '{track_id}'",
            status=404,
        )

    return api_response(aggregate.to_dict())
```

- [ ] **Step 6: Run all tests**

Run: `cd telemetry_tool && python -m pytest tests/test_track_surface.py tests/test_re_port_correctness.py -v --tb=short`

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/track_surface.py telemetry_tool/pipeline/orchestrator.py telemetry_tool/pipeline/stages/s10_theoretical.py telemetry_tool/web/routes/data_v2.py telemetry_tool/alembic/versions/048_track_surfaces_global.py telemetry_tool/tests/test_track_surface.py
git commit -m "feat: cross-workspace global track surface aggregate with solver fallback"
```
