# Corner Replay Re-Implementation Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Re-implement the Key Corner Replay module in the new Next.js webapp with three replay modes (Review, Split Comparison, Top 3 Overlay), analysis-time corner selection, and a batch composite API endpoint.

**Architecture:** Single batch GET endpoint returns all lap traces, corners, metrics, and replay windows. Frontend orchestrator manages state via useReducer with a single rAF loop driving synchronized canvas map + cockpit gauges. Corner selection happens during the analysis flow (pipeline pauses after track detection for user input).

**Tech Stack:** Flask API (Python), Next.js 14 + TypeScript + Tailwind, Canvas 2D API, TanStack React Query 5, Vitest + Playwright

---

## Section 1: Architecture & Data Flow

### Pipeline Integration

Corner selection happens DURING the analysis flow, not in Corner Coaching:

```
Upload CSV → Configure → Start Analysis
  → Pipeline stages 1-5 (track detection)
  → Pipeline pauses: corners_ready = true
  → Frontend shows TrackCornerPicker overlay
  → User selects 3-8 corners on interactive track map
  → PUT /api/v1/tracks/{trackId}/key-corners
  → POST /analysis/{jobId}/submit-corners resumes pipeline
  → Pipeline continues with corner analysis on selected corners only
```

The existing `corner_callback` / `_on_corners_ready()` mechanism in `analysis.py` handles the pipeline pause. The frontend analysis wizard polls job status and shows `TrackCornerPicker` when `corners_ready === true`.

### Data Flow for Corner Coaching Tab

```
Session detail page → "Corners & Coaching" tab clicked
  → Lazy-load CornerReplayOrchestrator bundle
  → GET /api/v1/sessions/{id}/corner-replay (single batch call)
  → Response cached in React Query
  → All mode switches / corner changes / lap selections are client-side index operations
  → No additional API calls during replay
```

### Batch Response Shape

```typescript
{
  session_id: number;
  track_id: number;
  has_pedal_data: boolean;      // true only if brake/throttle arrays have variance > 0
  has_steering_data: boolean;   // true only if steering arrays have variance > 0
  corners: Array<{
    corner_id: string;
    label: string;
    lat: number;
    lon: number;
    dist_m: number;
  }>;
  laps: Array<{
    lap_number: number;
    lap_time_s: number;
  }>;
  traces: Record<string, {         // keyed by lap_number
    lat: number[];
    lon: number[];
    dist_m: number[];
    speed_mps: number[];
    accel_lat: number[];
    accel_lon: number[];
    brake?: number[];              // omitted when has_pedal_data === false
    throttle?: number[];           // omitted when has_pedal_data === false
    steering?: number[];           // omitted when has_steering_data === false
  }>;
  replay_windows: Record<string, Array<{  // keyed by corner_id
    lap_number: number;
    start_idx: number;
    end_idx: number;
    estimated_duration_s: number;
  }>>;
  corner_metrics: Record<string, Array<{  // keyed by corner_id
    lap_number: number;
    brake_point_m: number;
    entry_speed_mps: number;
    apex_speed_mps: number;
    exit_speed_mps: number;
    time_loss_ms: number;
    coaching_hint: string | null;
  }>>;
}
```

### Pedal/Steering Data Detection

Pedal and steering data is ONLY included when actual data exists:
- `has_pedal_data`: true if brake AND throttle arrays exist with variance > 0 (not all zeros)
- `has_steering_data`: true if steering array exists with variance > 0
- When false, the corresponding keys are omitted from trace objects entirely
- Cockpit layout adapts dynamically:
  - Both present: 2x2 grid (speedo, g-ball, pedals, steering)
  - Only pedals: 3-panel row
  - Only steering: 3-panel row
  - Neither: speedo + g-ball only (side by side, larger)

---

## Section 2: Backend API Contract

### `GET /api/v1/sessions/{id}/corner-replay`

Returns the complete batch response (shape above).

**Query building:**
1. Load session row, verify exists (404)
2. Load track's key corners, verify non-empty (409)
3. Load GPS traces for all laps, verify >= 2 laps (422)
4. Detect pedal/steering data availability
5. Compute replay windows per corner (+-120 index pad around brake point)
6. Load corner metrics from `corner_metrics` table
7. Compute delta arrays for Split mode (time-based at same distance)
8. Return batch response

**Replay window computation:**
- For each corner, find brake_point index in the lap trace
- `start_idx = max(0, brake_idx - 120)`
- `end_idx = min(len(trace) - 1, brake_idx + 120)`
- `estimated_duration_s = sum(delta_d / max(v, 0.5))` over the window

**Delta computation (time-based at same distance):**
```
For each distance d in lap_A's trace:
  time_A = cumulative_time_A at distance d
  time_B = interpolated cumulative_time_B at distance d
  delta_ms = (time_A - time_B) * 1000
```
Positive delta means lap A is slower. Standard motorsport convention.

### `GET /api/v1/tracks/{trackId}/key-corners`

Returns `{ corners: Array<{ corner_id, label, lat, lon, dist_m }> }`.

Empty array (not 404) if track exists but has no corners. 404 only if track doesn't exist.

### `PUT /api/v1/tracks/{trackId}/key-corners`

Request body: `{ corners: Array<{ corner_id, label, lat, lon, dist_m }> }`

Validation: 3-8 corners required (422 otherwise).

**Non-destructive upsert:** If a corner_id already exists, only `label` is updated. `lat`, `lon`, `dist_m` come from the request but are preserved if the corner already has them and the request omits them. New corner_ids are inserted.

---

## Section 3: Frontend Component Architecture

### Component Tree

```
CornerCoachingSection (lazy-loaded tab in session detail)
 └── CornerReplayOrchestrator
     ├── CornerReplayControls
     │   ├── Mode tabs (Review / Split / Top 3)
     │   ├── Corner pills (prev/next + click)
     │   ├── Lap A/B selectors (Split mode only)
     │   ├── Scrubber (pointer events for mouse+touch)
     │   └── Speed selector (0.25x / 0.5x / 1x / 2x)
     ├── CornerReplayMap (canvas)
     │   ├── Review: primary lap trace + reference corner dots
     │   ├── Split: lap A (green) + lap B (red) + delta badge
     │   └── Top 3: overlay of 3 fastest laps (gold/silver/bronze)
     ├── CornerReplayCockpit (canvas)
     │   ├── Speedometer (always)
     │   ├── G-ball (always)
     │   ├── Brake/Throttle bars (only if has_pedal_data)
     │   └── Steering arc (only if has_steering_data)
     └── CornerMetricsPanel
         ├── Corner stats (brake point, entry/apex/exit speed, time loss)
         └── Coaching hints (from theoretical engine best passages)
```

### Orchestrator State (useReducer)

```typescript
State: {
  mode: 'review' | 'split' | 'top3'
  cornerIndex: number
  lapA: number
  lapB: number
  frame: number
  playing: boolean
  speed: 0.25 | 0.5 | 1 | 2
}
```

Actions: `SET_MODE`, `SET_CORNER`, `NEXT_CORNER`, `PREV_CORNER`, `SET_LAP_A`, `SET_LAP_B`, `SET_FRAME`, `TOGGLE_PLAY`, `SET_SPEED`

Mode and corner transitions reset `frame` to 0 and `playing` to false.

### Animation Loop

Single `requestAnimationFrame` loop in the orchestrator. Each tick:
1. Advance `frame` based on `speed` and elapsed time
2. Clamp to replay window bounds
3. Pass current frame data to Map + Cockpit as props (no child-level rAF)

### Canvas Strategy

- **Map**: Full redraw each frame. `useInteractiveCanvas` hook for zoom/pan (wheel + drag). Double-click resets to fit-all. `ResizeObserver` triggers canvas resize.
- **Cockpit**: Full redraw each frame. Layout grid adapts based on data availability.

### Keyboard Shortcuts

Registered at orchestrator level, active only when mounted:

| Key | Action |
|-----|--------|
| Space | Toggle play/pause |
| Left Arrow | Previous corner |
| Right Arrow | Next corner |
| [ | Decrease speed |
| ] | Increase speed |

### TrackCornerPicker (Analysis Flow)

Separate component in the analysis wizard:
- Shown when job status has `corners_ready === true`
- Renders track GPS outline on canvas with auto-detected corner markers
- User clicks to toggle selection (3-8 range, min 3 enforced)
- User can drag markers to adjust position
- "Confirm Corners" calls PUT key-corners + POST submit-corners

### Lazy Loading

`CornerCoachingSection` wrapper:
- `React.lazy()` + `Suspense` for the orchestrator bundle
- React Query `enabled: isActive` — fetches only when tab clicked
- `AbortController` signal for unmount cancellation

---

## Section 4: Error Handling & Safety Guards

### Backend Error Responses

All errors use standard envelope `{ok: false, error: "...", meta: {request_id}}`:

| Scenario | HTTP | Error |
|----------|------|-------|
| Session not found | 404 | `"Session not found"` |
| No key corners for track | 409 | `"No key corners defined for this track"` |
| < 2 GPS laps | 422 | `"Insufficient GPS data: need at least 2 laps, found {n}"` |
| Track not found | 404 | `"Track not found"` |
| Invalid corner count | 422 | `"Must select between 3 and 8 corners"` |

No 500s escape — entire endpoint wrapped in try/except with logged traceback.

### Frontend Error States

- **409**: "No corners selected. Re-run analysis to select corners." + link to analysis page
- **422**: "This session has fewer than 2 GPS laps."
- **404**: "Session not found or has been deleted."
- **Network error**: "Failed to load corner replay data." + retry button

### Canvas Safety

- Radius clamping: `Math.max(0, radius)` on all `arc()` calls
- Empty container: skip draws if `canvas.width < 10 || canvas.height < 10`
- NaN/Infinity guards: `if (!Number.isFinite(val)) return`
- Division by zero: `Math.max(speed, 0.5)` for duration calculations
- Frame index clamping: `Math.min(frame, trace.length - 1)`

### Data Integrity

- Null-safe sorting: `dist_m ?? Infinity`
- Missing lap data: excluded from lap selector
- Partial pedal/steering: variance check (all-zeros = no data)
- Empty corners: "No corner data available" fallback

### Cleanup

- `AbortController` on unmount cancels in-flight fetch
- `cancelAnimationFrame` in useEffect cleanup
- `removeEventListener` for keyboard shortcuts

---

## Section 5: Testing Strategy

### Backend Unit Tests (`test_corner_replay_api.py`, ~20 tests)

**Batch endpoint:**
- 404 for non-existent session
- 409 when no key corners
- 422 when < 2 GPS laps
- Correct response structure
- `has_pedal_data` true only with variance > 0
- `has_steering_data` true only with variance > 0
- Trace keys omitted when `has_*` is false
- Replay window indices within trace bounds
- Delta computation correctness
- Corners sorted by dist_m (null-safe)
- Workspace RLS isolation

**Key corners endpoint:**
- GET returns corners / 404 for missing track
- PUT creates 3-8 corners / rejects invalid count
- PUT non-destructive upsert (label update preserves lat/lon)
- Workspace isolation

### Frontend Component Tests (Vitest + RTL, ~22 tests)

**Orchestrator:** loading/error states, mode/corner reset behavior, keyboard shortcuts
**Controls:** mode tabs, corner pills, lap selectors, speed selector, scrubber
**Cockpit:** conditional pedal/steering rendering
**Map:** mount safety, empty traces, ResizeObserver, zoom reset

### E2E Tests (Playwright, ~6 scenarios)

Using `page.route` API mocks (no real backend):
1. Tab loads and shows corner replay
2. Mode switching updates UI
3. Corner pill navigation
4. Play/pause toggle
5. Error state for 409
6. Scrubber interaction

### Test Fixtures

Shared `cornerReplayFixture.ts`:
- `mockCornerReplayResponse` — valid batch with 2 laps, 3 corners, pedal data
- `mockCornerReplayNoPedals` — same without brake/throttle/steering
- `mockKeyCorners` — array of 4 key corners
