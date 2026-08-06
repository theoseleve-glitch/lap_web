# Driving Events Phase 3 — Mistake Tape + Exploitation Map

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase 2's detected events visible — a mistake tape along the speed trace, and a g-g envelope that is measured against something other than itself.

**Architecture:** Frontend-only. Two new pure modules under `lap-website/src/lib/` (one for the API type + fetch, one for canvas drawing), consumed by two existing chart components. No backend change is needed: `GET /sessions/<id>/driving-events` and `/corner-consistency` already ship (Phase 2 Task 10), and `/sessions/<id>/corner-metrics` is a `SELECT *` so migration 085's four `grip_anchor_*` columns already come through.

**Tech Stack:** Next.js 15 / React 19 / TypeScript, canvas 2D, `vitest` for unit tests (`npm test` → `vitest run`), `@playwright/test` for e2e. HTTP via `src/lib/api-client.ts`'s `api.get<T>(path)`.

## Global Constraints

Every task's requirements implicitly include this section.

1. **Never render `late_throttle`'s magnitude as a standalone claim, and never as the cause of a time cost.** The API states this per-row so a renderer never has to infer it: `time_cost_attribution` (`"caused"` | `"context"` | `"no_cost"`) and `magnitude_is_standalone_quotable` (boolean). Read those fields. Do not hardcode a list of event types — a fifth detector must inherit the constraint automatically.
2. **"No events" and "could not measure" must never render identically.** The response carries `capability` (each detector → `"detected"` | `"not_triggered"` | `"insufficient"`) and `capability_available`. A clean session and a session whose grip anchor failed both return `events: []`; the UI must distinguish them.
3. **Never draw a diagnostic boundary derived from the data it is drawn over.** This is the specific defect Phase 3 exists to remove (`GGExplorer.tsx:105`, `frictionR = maxG * 0.95`). If the grip anchor refused, draw no envelope and say so — do not fall back to a self-referential circle.
4. **Tests must import the shipped code, not a copy of it.** `src/__tests__/chart-guards.test.ts` re-declares its guard helpers inline, so it passes no matter what the components do. Do not follow that pattern; import the real exported functions.
5. **Bite-check every test.** Break the code the test guards, run it, confirm it goes RED *for the stated reason*, restore. Paste the actual failure output in your report. Note `pytest`-style caching has a JS analogue: if a test behaves oddly after a mutate-and-restore, clear `node_modules/.vite`.
6. `magnitude_unit` is a closed vocabulary: `m`, `m/s`, `m/s2`, `pct`. `anchor_tier` is one of `session_envelope_ellipse_fitted`, `session_envelope_default_p2`, `driver_best_session`, `refused`.
7. Do not grow `SpeedTraceChart.tsx` (already 1198 lines against this repo's 500-line guidance). New logic goes in `src/lib/`.
8. **Do not reuse `ChartAnnotations.tsx`** (spec §5.8). It paints onto the canvas externally, so the chart's next `clearRect` erases whatever it drew — an overlay routed through it will appear to work and then vanish on the first resize or hover. Overlays must be parameters of the pure draw functions, drawn inside the same pass. This is why Task 2's functions take a `ctx` and are called from within `drawSpeedTrace`, not after it.
8. Run frontend commands from `lap-website/`. Stage explicit paths; `git add -u` is forbidden in this repo (antivirus quarantine causes spurious deletions).

---

## File Structure

| File | Responsibility |
|---|---|
| `lap-website/src/lib/driving-events.ts` (new) | The `DrivingEvent` type mirroring the API row, the `DrivingEventsResponse` envelope, `fetchDrivingEvents()`, and the two predicates that enforce Global Constraint 1. No React, no canvas. |
| `lap-website/src/lib/driving-events-draw.ts` (new) | Pure canvas drawing: the corner shade band and the per-event tape strip. Takes an explicit geometry object so it is testable against a recording stub with no DOM. |
| `lap-website/src/components/shared/charts/SpeedTraceChart.tsx` (modify) | New optional props, one fetch effect following the existing `showTheoretical` pattern, two new `DrawOptions` fields, two calls into the draw module. |
| `lap-website/src/components/shared/charts/GGExplorer.tsx` (modify) | Replace the self-referential friction circle with the anchored envelope; refuse to draw when the anchor refused. |
| `lap-website/src/__tests__/driving-events.test.ts` (new) | Unit tests for the lib modules, importing the real exports. |

---

### Task 1: The API type, fetch, and the two rendering constraints

**Files:**
- Create: `lap-website/src/lib/driving-events.ts`
- Test: `lap-website/src/__tests__/driving-events.test.ts`

**Interfaces:**
- Consumes: `api.get<T>(path)` from `src/lib/api-client.ts` (line 191 exports `api`).
- Produces:
  - `type DrivingEvent` — one row of `GET /sessions/<id>/driving-events`
  - `type DrivingEventsResponse = { events: DrivingEvent[]; available: boolean; capability: Record<string, CapabilityValue>; capability_available: boolean }`
  - `fetchDrivingEvents(sessionId: string, limit?: number): Promise<DrivingEventsResponse | null>`
  - `canQuoteMagnitude(e: DrivingEvent): boolean`
  - `canAttributeCost(e: DrivingEvent): boolean`
  - `describeCapability(r: DrivingEventsResponse | null): 'clean' | 'degraded' | 'unavailable' | 'has-events'`

- [ ] **Step 1: Write the failing tests**

Create `lap-website/src/__tests__/driving-events.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  canQuoteMagnitude,
  canAttributeCost,
  describeCapability,
  type DrivingEvent,
  type DrivingEventsResponse,
} from '@/lib/driving-events';

function ev(over: Partial<DrivingEvent> = {}): DrivingEvent {
  return {
    lap_number: 3,
    corner_id: 4,
    event_type: 'over_slowing',
    s_norm_start: 0.21,
    s_norm_end: 0.30,
    magnitude: 1.4,
    magnitude_unit: 'm/s',
    time_cost_s: 0.31,
    validity: 'measured',
    reason: null,
    n_samples_in_window: 40,
    anchor_tier: 'session_envelope_ellipse_fitted',
    anchor_reason: null,
    evidence: {},
    time_cost_attribution: 'caused',
    magnitude_is_standalone_quotable: true,
    also_fired: [],
    ...over,
  };
}

describe('rendering constraints come from the payload, not a hardcoded list', () => {
  it('lets a caused, quotable event be quoted and attributed', () => {
    const e = ev();
    expect(canQuoteMagnitude(e)).toBe(true);
    expect(canAttributeCost(e)).toBe(true);
  });

  it('refuses to quote or attribute a context event', () => {
    const e = ev({
      event_type: 'late_throttle',
      magnitude: 12.4,
      magnitude_unit: 'm',
      time_cost_attribution: 'context',
      magnitude_is_standalone_quotable: false,
    });
    expect(canQuoteMagnitude(e)).toBe(false);
    expect(canAttributeCost(e)).toBe(false);
  });

  it('treats the two axes as independent: no cost but a quotable magnitude', () => {
    const e = ev({
      event_type: 're_braking',
      magnitude: 9.8,
      magnitude_unit: 'm/s2',
      time_cost_s: null,
      time_cost_attribution: 'no_cost',
      magnitude_is_standalone_quotable: true,
    });
    expect(canQuoteMagnitude(e)).toBe(true);
    expect(canAttributeCost(e)).toBe(false);
  });

  it('refuses an unknown attribution rather than defaulting to permissive', () => {
    const e = ev({ time_cost_attribution: 'something_new' as never });
    expect(canAttributeCost(e)).toBe(false);
  });

  it('never quotes a non-finite magnitude even when the flag allows it', () => {
    expect(canQuoteMagnitude(ev({ magnitude: NaN }))).toBe(false);
    expect(canQuoteMagnitude(ev({ magnitude: null }))).toBe(false);
  });
});

describe('an empty event list is not one state', () => {
  function res(over: Partial<DrivingEventsResponse> = {}): DrivingEventsResponse {
    return {
      events: [], available: false,
      capability: {
        over_slowing: 'not_triggered', late_throttle: 'not_triggered',
        re_braking: 'not_triggered', envelope_under_use: 'not_triggered',
      },
      capability_available: true,
      ...over,
    };
  }

  it('calls a session with events has-events', () => {
    expect(describeCapability(res({ events: [ev()], available: true }))).toBe('has-events');
  });

  it('calls all-not_triggered clean', () => {
    expect(describeCapability(res())).toBe('clean');
  });

  it('calls any insufficient detector degraded, NOT clean', () => {
    const r = res();
    r.capability.over_slowing = 'insufficient';
    expect(describeCapability(r)).toBe('degraded');
  });

  it('calls a missing capability record unavailable, distinct from clean', () => {
    expect(describeCapability(res({ capability: {}, capability_available: false })))
      .toBe('unavailable');
  });

  it('calls a null response unavailable', () => {
    expect(describeCapability(null)).toBe('unavailable');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events.test.ts`
Expected: FAIL — cannot resolve `@/lib/driving-events`.

- [ ] **Step 3: Implement the module**

Create `lap-website/src/lib/driving-events.ts`:

```ts
/**
 * Phase 3 client for the driving-events API (Phase 2, Task 10).
 *
 * Two of these exports exist to enforce constraints the BACKEND states
 * per-row precisely so a renderer never has to infer them. Do not replace
 * them with a hardcoded list of event types: a fifth detector must inherit
 * the constraint automatically, and getting this wrong renders a number the
 * measurement does not support.
 */
import { api } from '@/lib/api-client';

export type CapabilityValue = 'detected' | 'not_triggered' | 'insufficient';

export interface AlsoFired {
  event_type: string;
  magnitude: number | null;
  magnitude_unit: string | null;
  validity: string | null;
  magnitude_is_standalone_quotable: boolean;
}

export interface DrivingEvent {
  lap_number: number;
  corner_id: number;
  event_type: string;
  s_norm_start: number | null;
  s_norm_end: number | null;
  magnitude: number | null;
  magnitude_unit: string | null;
  time_cost_s: number | null;
  validity: string | null;
  reason: string | null;
  n_samples_in_window: number | null;
  anchor_tier: string | null;
  anchor_reason: string | null;
  evidence: Record<string, unknown>;
  /** "caused" | "context" | "no_cost" — see driving_events.TIME_COST_ATTRIBUTION */
  time_cost_attribution: string;
  magnitude_is_standalone_quotable: boolean;
  also_fired?: AlsoFired[];
}

export interface DrivingEventsResponse {
  events: DrivingEvent[];
  available: boolean;
  capability: Record<string, CapabilityValue>;
  capability_available: boolean;
}

/** May this event's magnitude be shown on its own? */
export function canQuoteMagnitude(e: DrivingEvent): boolean {
  if (!e.magnitude_is_standalone_quotable) return false;
  return typeof e.magnitude === 'number' && Number.isFinite(e.magnitude);
}

/** May `time_cost_s` be presented as CAUSED by this event's own magnitude? */
export function canAttributeCost(e: DrivingEvent): boolean {
  // Allow-list, not deny-list: an attribution value this build does not know
  // must read as "not attributable", never as permissive.
  if (e.time_cost_attribution !== 'caused') return false;
  return typeof e.time_cost_s === 'number' && Number.isFinite(e.time_cost_s);
}

/**
 * Collapse the response into the four states a UI must tell apart.
 * `events: []` alone is ambiguous — it is both "nothing to fix" and
 * "three of four detectors could not look at anything".
 */
export function describeCapability(
  r: DrivingEventsResponse | null,
): 'clean' | 'degraded' | 'unavailable' | 'has-events' {
  if (!r) return 'unavailable';
  if (r.events.length > 0) return 'has-events';
  if (!r.capability_available || Object.keys(r.capability).length === 0) {
    return 'unavailable';
  }
  const values = Object.values(r.capability);
  if (values.some((v) => v === 'insufficient')) return 'degraded';
  return 'clean';
}

export async function fetchDrivingEvents(
  sessionId: string,
  limit = 10,
): Promise<DrivingEventsResponse | null> {
  try {
    return await api.get<DrivingEventsResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/driving-events?limit=${limit}`,
    );
  } catch {
    // Optional overlay — a 404 or a pre-086 session must not break the chart.
    return null;
  }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events.test.ts`
Expected: PASS, 10 tests.

- [ ] **Step 5: Bite-check**

Change `canAttributeCost`'s allow-list to a deny-list (`if (e.time_cost_attribution === 'no_cost') return false;`). Re-run.
Expected: `refuses an unknown attribution rather than defaulting to permissive` and `refuses to quote or attribute a context event` go RED. Restore.

Then change `describeCapability` to return `'clean'` when values contain `insufficient`. Re-run.
Expected: `calls any insufficient detector degraded, NOT clean` goes RED. Restore.

Paste both outputs into the report.

- [ ] **Step 6: Commit**

```bash
cd lap-website && npx tsc --noEmit
git add lap-website/src/lib/driving-events.ts lap-website/src/__tests__/driving-events.test.ts
git commit -m "feat(events-ui): client type and the two rendering constraints"
```

---

### Task 2: Pure canvas draw — corner shade and mistake tape

**Files:**
- Create: `lap-website/src/lib/driving-events-draw.ts`
- Test: `lap-website/src/__tests__/driving-events.test.ts` (append)

**Interfaces:**
- Consumes: `DrivingEvent`, `canQuoteMagnitude` from Task 1.
- Produces:
  - `interface TapeGeometry { xToPixel: (m: number) => number; plotX: number; plotY: number; plotW: number; plotH: number; lapLengthM: number }`
  - `drawMistakeTape(ctx, events: DrivingEvent[], geo: TapeGeometry): void`
  - `drawCornerShade(ctx, events: DrivingEvent[], geo: TapeGeometry): void`
  - `eventColor(e: DrivingEvent): string`
  - `eventLabel(e: DrivingEvent): string` — gates the magnitude through `canQuoteMagnitude`
  - `TAPE_HEIGHT_PX = 8`

**Why pure and geometry-injected:** `SpeedTraceChart`'s existing bottom strip (`crossRefDeltaS`, around line 519) already proves this shape works on this canvas. Taking `xToPixel` as a parameter means these can be tested against a recording stub with no DOM and no canvas mock library.

**Why `s_norm` × `lapLengthM`:** events carry `s_norm_start`/`s_norm_end` (0..1 per lap), because Phase 2 moved everything to `distance_norm` after absolute metres proved to be a per-lap coordinate artifact. The chart's x-axis is metres, so convert at the boundary — never store metres in the event.

- [ ] **Step 1: Write the failing tests**

Append to `lap-website/src/__tests__/driving-events.test.ts`:

```ts
import {
  drawMistakeTape, drawCornerShade, eventColor, TAPE_HEIGHT_PX,
  type TapeGeometry,
} from '@/lib/driving-events-draw';

/** Records every call instead of painting. No DOM, no canvas mock. */
function recorder() {
  const calls: Array<{ op: string; args: unknown[] }> = [];
  const ctx = new Proxy({} as CanvasRenderingContext2D, {
    get(_t, prop: string) {
      if (prop === 'canvas') return undefined;
      return (...args: unknown[]) => { calls.push({ op: prop, args }); };
    },
    set(_t, prop: string, value) { calls.push({ op: `set:${prop}`, args: [value] }); return true; },
  });
  return { ctx, calls, rects: () => calls.filter((c) => c.op === 'fillRect') };
}

const GEO: TapeGeometry = {
  xToPixel: (m) => 100 + m,     // 1 px per metre, origin at 100
  plotX: 100, plotY: 20, plotW: 1000, plotH: 300, lapLengthM: 1000,
};

describe('drawMistakeTape', () => {
  it('places a segment at the event span converted from s_norm', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })], GEO);
    const rects = r.rects();
    expect(rects.length).toBe(1);
    const [x, , w, h] = rects[0]!.args as number[];
    expect(x).toBeCloseTo(300, 5);   // 100 + 0.2*1000
    expect(w).toBeCloseTo(100, 5);   // (0.3-0.2)*1000
    expect(h).toBe(TAPE_HEIGHT_PX);
  });

  it('draws nothing for an event with no span', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: null, s_norm_end: null })], GEO);
    expect(r.rects().length).toBe(0);
  });

  it('draws nothing for a non-finite or inverted span', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [
      ev({ s_norm_start: NaN, s_norm_end: 0.3 }),
      ev({ s_norm_start: 0.5, s_norm_end: 0.4 }),
    ], GEO);
    expect(r.rects().length).toBe(0);
  });

  it('clips a segment to the plot area instead of painting outside it', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: -0.5, s_norm_end: 1.5 })], GEO);
    const [x, , w] = r.rects()[0]!.args as number[];
    expect(x).toBeGreaterThanOrEqual(GEO.plotX);
    expect(x + w).toBeLessThanOrEqual(GEO.plotX + GEO.plotW);
  });

  it('gives a zero-width span a minimum visible width', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.4, s_norm_end: 0.4 })], GEO);
    const [, , w] = r.rects()[0]!.args as number[];
    expect(w).toBeGreaterThanOrEqual(1);
  });

  it('draws one segment per event', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [
      ev({ s_norm_start: 0.1, s_norm_end: 0.2 }),
      ev({ s_norm_start: 0.5, s_norm_end: 0.6 }),
    ], GEO);
    expect(r.rects().length).toBe(2);
  });
});

describe('eventColor', () => {
  it('distinguishes a costed event from a context one', () => {
    const caused = ev();
    const context = ev({ event_type: 'late_throttle', time_cost_attribution: 'context',
                         magnitude_is_standalone_quotable: false });
    expect(eventColor(caused)).not.toBe(eventColor(context));
  });

  it('returns a parseable rgba string for every event type', () => {
    for (const t of ['over_slowing', 'late_throttle', 're_braking', 'envelope_under_use', 'unknown']) {
      expect(eventColor(ev({ event_type: t }))).toMatch(/^rgba?\(/);
    }
  });
});

describe('drawCornerShade', () => {
  it('shades the full plot height over the event span', () => {
    const r = recorder();
    drawCornerShade(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })], GEO);
    const [, y, , h] = r.rects()[0]!.args as number[];
    expect(y).toBe(GEO.plotY);
    expect(h).toBe(GEO.plotH);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events.test.ts`
Expected: FAIL — cannot resolve `@/lib/driving-events-draw`.

- [ ] **Step 3: Implement the draw module**

Create `lap-website/src/lib/driving-events-draw.ts`:

```ts
/**
 * Pure canvas drawing for the Phase 3 mistake tape.
 *
 * Geometry is INJECTED rather than computed here so these functions can be
 * unit-tested against a recording stub with no DOM. They mirror the shape of
 * the existing cross-session delta bar in SpeedTraceChart (a per-segment
 * strip along the bottom of the plot area), which is already proven on this
 * canvas.
 *
 * Events carry `s_norm_*` (0..1 per lap), not metres. Phase 2 moved to
 * `distance_norm` because absolute metres differenced across laps is a
 * coordinate artifact -- lap spans on real data vary by ~19 m, which is
 * larger than several detectors' firing thresholds. Convert at the drawing
 * boundary; never persist metres back onto an event.
 */
import { canQuoteMagnitude, type DrivingEvent } from '@/lib/driving-events';

export const TAPE_HEIGHT_PX = 8;

export interface TapeGeometry {
  xToPixel: (metres: number) => number;
  plotX: number;
  plotY: number;
  plotW: number;
  plotH: number;
  lapLengthM: number;
}

const COLORS: Record<string, string> = {
  over_slowing: 'rgba(255, 42, 42, 0.55)',
  late_throttle: 'rgba(250, 204, 21, 0.35)',
  re_braking: 'rgba(249, 115, 22, 0.55)',
  envelope_under_use: 'rgba(59, 130, 246, 0.45)',
};
const COLOR_UNKNOWN = 'rgba(148, 163, 184, 0.40)';

export function eventColor(e: DrivingEvent): string {
  return COLORS[e.event_type] ?? COLOR_UNKNOWN;
}

/** Pixel span of an event, or null when it has none. Clipped to the plot. */
function spanPx(e: DrivingEvent, geo: TapeGeometry): { x: number; w: number } | null {
  const a = e.s_norm_start;
  const b = e.s_norm_end;
  if (typeof a !== 'number' || typeof b !== 'number') return null;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (b < a) return null;  // inverted span is a producer bug, not something to guess at

  const rawL = geo.xToPixel(a * geo.lapLengthM);
  const rawR = geo.xToPixel(b * geo.lapLengthM);
  if (!Number.isFinite(rawL) || !Number.isFinite(rawR)) return null;

  const right = geo.plotX + geo.plotW;
  const l = Math.max(geo.plotX, Math.min(rawL, right));
  const r = Math.max(geo.plotX, Math.min(rawR, right));
  if (r < geo.plotX || l > right) return null;
  return { x: l, w: Math.max(1, r - l) };  // a zero-width span must stay visible
}

/** The tape: one coloured segment per event along the bottom of the plot. */
export function drawMistakeTape(
  ctx: CanvasRenderingContext2D,
  events: DrivingEvent[],
  geo: TapeGeometry,
): void {
  if (!events?.length) return;
  ctx.save();
  const y = geo.plotY + geo.plotH - TAPE_HEIGHT_PX;
  for (const e of events) {
    const s = spanPx(e, geo);
    if (!s) continue;
    ctx.fillStyle = eventColor(e);
    ctx.fillRect(s.x, y, s.w, TAPE_HEIGHT_PX);
  }
  ctx.restore();
}

/** Full-height wash over each event's corner window. */
export function drawCornerShade(
  ctx: CanvasRenderingContext2D,
  events: DrivingEvent[],
  geo: TapeGeometry,
): void {
  if (!events?.length) return;
  ctx.save();
  for (const e of events) {
    const s = spanPx(e, geo);
    if (!s) continue;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.035)';
    ctx.fillRect(s.x, geo.plotY, s.w, geo.plotH);
  }
  ctx.restore();
}

/**
 * Label for one event. Obeys Global Constraint 1 by reading the payload's own
 * flags -- a magnitude that is not standalone-quotable is never shown as a
 * number, and a cost that is not attributable is never joined to it with
 * causal wording.
 */
export function eventLabel(e: DrivingEvent): string {
  const where = `C${e.corner_id} L${e.lap_number}`;
  if (canQuoteMagnitude(e)) {
    return `${where} · ${e.event_type} ${e.magnitude!.toFixed(1)}${e.magnitude_unit ?? ''}`;
  }
  return `${where} · ${e.event_type}`;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events.test.ts`
Expected: PASS, all Task 1 + Task 2 tests.

- [ ] **Step 5: Bite-check**

Remove the `Math.max(1, ...)` from `spanPx`'s return. Re-run.
Expected: `gives a zero-width span a minimum visible width` goes RED. Restore.

Remove the clipping (`return { x: rawL, w: rawR - rawL }`). Re-run.
Expected: `clips a segment to the plot area instead of painting outside it` goes RED. Restore.

Paste both outputs.

- [ ] **Step 6: Commit**

```bash
cd lap-website && npx tsc --noEmit
git add lap-website/src/lib/driving-events-draw.ts lap-website/src/__tests__/driving-events.test.ts
git commit -m "feat(events-ui): pure canvas draw for the mistake tape"
```

---

### Task 3: Wire the tape into SpeedTraceChart

**Files:**
- Modify: `lap-website/src/components/shared/charts/SpeedTraceChart.tsx`
- Test: `lap-website/src/__tests__/driving-events.test.ts` (append)

**Interfaces:**
- Consumes: `fetchDrivingEvents`, `DrivingEventsResponse` (Task 1); `drawMistakeTape`, `drawCornerShade`, `TapeGeometry` (Task 2).
- Produces: `SpeedTraceChartProps.showDrivingEvents?: boolean`.

**Where things are** (verify before editing — this file changes often):
- `SpeedTraceChartProps` is the interface at line 29; `showTheoretical` at line 50 is the prop pattern to copy.
- `DrawOptions` is the interface at line 108.
- `drawSpeedTrace` starts at line 131 and RETURNS `{ xMin, xMax, yMin, yMax, plotX, plotY, plotW, plotH }` — that return already gives you everything `TapeGeometry` needs except `xToPixel`.
- The `showTheoretical` fetch effect begins at line 857. Copy its shape exactly: a `cancelled` flag, `api.get`, and a silent `catch` that clears state.
- The existing cross-session delta bar (around line 519) is the visual precedent for a bottom strip.

- [ ] **Step 1: Add the prop and the fetch effect**

In `SpeedTraceChartProps` (after line 52), add:

```ts
  /** When true, fetches Phase 2 driving events and overlays the mistake tape */
  showDrivingEvents?: boolean;
```

Destructure `showDrivingEvents` alongside `showTheoretical` in the component signature at line 751.

Add state beside the other chart state:

```ts
  const [drivingEvents, setDrivingEvents] = useState<DrivingEventsResponse | null>(null);
```

Add the effect, modelled on the `showTheoretical` effect at line 857:

```ts
  // ── Fetch driving events ─────────────────────────────────────
  useEffect(() => {
    if (!showDrivingEvents || !sessionId) {
      setDrivingEvents(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const res = await fetchDrivingEvents(sessionId);
      if (!cancelled) setDrivingEvents(res);
    })();
    return () => { cancelled = true; };
  }, [showDrivingEvents, sessionId]);
```

Import at the top of the file:

```ts
import { fetchDrivingEvents, type DrivingEventsResponse } from '@/lib/driving-events';
import { drawMistakeTape, drawCornerShade } from '@/lib/driving-events-draw';
```

- [ ] **Step 2: Thread it through DrawOptions**

Add to `DrawOptions` (interface at line 108):

```ts
  /** Phase 2 driving events to overlay as a tape. Null = not requested or unavailable. */
  drivingEvents?: DrivingEvent[] | null;
```

Import `type DrivingEvent` in the same import statement as `fetchDrivingEvents`.

Pass `drivingEvents: drivingEvents?.events ?? null` where the other `opts` fields are assembled for `drawSpeedTrace`.

- [ ] **Step 3: Draw it**

Inside `drawSpeedTrace`, immediately BEFORE the `// ── Drag selection overlay ──` block (so a drag highlight still paints on top), add:

```ts
  // ── Driving-event tape ────────────────────────────────────
  if (opts.drivingEvents && opts.drivingEvents.length > 0) {
    const lapLengthM = xMax - xMin;
    if (lapLengthM > 0) {
      const geo = {
        xToPixel: (m: number) => xToPixel(xMin + m),
        plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH,
        lapLengthM,
      };
      drawCornerShade(ctx, opts.drivingEvents, geo);
      drawMistakeTape(ctx, opts.drivingEvents, geo);
    }
  }
```

Note `xToPixel(xMin + m)`: `s_norm` is a fraction of the LAP, but the chart's x-axis may be cropped by `distRange`, so the fraction is measured from `xMin`, not from zero.

- [ ] **Step 4: Write the geometry test**

Append to `lap-website/src/__tests__/driving-events.test.ts`:

```ts
describe('the tape geometry respects a cropped x-axis', () => {
  it('anchors s_norm to xMin, not to zero, when the chart is zoomed', () => {
    // A chart cropped to 400..900 m. An event at s_norm 0.2 of that window
    // must land at 400 + 0.2*500 = 500 m, NOT at 0.2 * 900.
    const xMin = 400, xMax = 900;
    const lapLengthM = xMax - xMin;
    const xToPixel = (m: number) => (m - xMin) * 2;   // 2 px per metre
    const geo: TapeGeometry = {
      xToPixel: (m: number) => xToPixel(xMin + m),
      plotX: 0, plotY: 0, plotW: 1000, plotH: 300, lapLengthM,
    };
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.4 })], geo);
    const [x, , w] = r.rects()[0]!.args as number[];
    expect(x).toBeCloseTo(200, 5);   // (400+100 - 400) * 2
    expect(w).toBeCloseTo(200, 5);   // 0.2 * 500 * 2
  });
});
```

- [ ] **Step 5: Run and typecheck**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events.test.ts && npx tsc --noEmit`
Expected: all PASS, no type errors.

- [ ] **Step 6: Bite-check**

In the geometry test, that assertion is the guard. Change the component's `xToPixel: (m: number) => xToPixel(xMin + m)` to `xToPixel: (m: number) => xToPixel(m)` in `SpeedTraceChart.tsx`, then re-run the test with the same substitution applied to the test's `geo`. Confirm the expected pixel changes and the assertion fails. Restore both.

Paste the output.

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/components/shared/charts/SpeedTraceChart.tsx lap-website/src/__tests__/driving-events.test.ts
git commit -m "feat(events-ui): overlay the mistake tape on the speed trace"
```

---

### Task 4: An exploitation envelope that is not drawn from its own data

**Files:**
- Modify: `lap-website/src/components/shared/charts/GGExplorer.tsx:105,141,209`
- Test: `lap-website/src/__tests__/driving-events.test.ts` (append)

**Interfaces:**
- Produces: `resolveEnvelope(anchor: AnchorSummary | null, maxObservedG: number): EnvelopeDecision` — exported from `src/lib/driving-events-draw.ts`.

**The defect being removed.** `GGExplorer.tsx:105` is `const frictionR = maxG * 0.95;` where `maxG` is the largest magnitude among the very points being plotted (computed at lines 96-102). It is then drawn as a boundary at line 141 and LABELLED with a G figure at line 209. A boundary derived from the data it is drawn over cannot diagnose that data — it moves whenever the data moves, so the driver can never be outside it and can never learn anything from it. Migration 085 gives the honest alternative: a per-corner `grip_anchor_baseline_g` with a `grip_anchor_tier` naming what it was measured against.

**Tiers**, from `telemetry_tool/grip_anchor.py`, in descending strength: `session_envelope_ellipse_fitted`, `session_envelope_default_p2`, `driver_best_session`, `refused`.

- [ ] **Step 1: Write the failing tests**

Append to `lap-website/src/__tests__/driving-events.test.ts`:

```ts
import { resolveEnvelope } from '@/lib/driving-events-draw';

describe('resolveEnvelope — never a boundary drawn from its own data', () => {
  it('uses the anchored baseline and names the tier', () => {
    const d = resolveEnvelope(
      { baseline_g: 1.02, tier: 'session_envelope_ellipse_fitted', reason: null }, 1.30);
    expect(d.draw).toBe(true);
    expect(d.radiusG).toBeCloseTo(1.02, 6);
    expect(d.label).toContain('1.02');
    expect(d.label.toLowerCase()).toContain('fitted');
  });

  it('still draws on the weaker driver-best tier, but says so', () => {
    const d = resolveEnvelope(
      { baseline_g: 0.94, tier: 'driver_best_session', reason: null }, 1.10);
    expect(d.draw).toBe(true);
    expect(d.label.toLowerCase()).toContain('your best');
  });

  it('DRAWS NOTHING when the anchor refused, and never falls back to maxG', () => {
    const d = resolveEnvelope(
      { baseline_g: null, tier: 'refused', reason: 'channel_untrusted' }, 1.30);
    expect(d.draw).toBe(false);
    expect(d.radiusG).toBeNull();
    expect(d.label.toLowerCase()).toContain('not measured');
    // The old defect: 1.30 * 0.95 = 1.235. It must appear nowhere.
    expect(d.label).not.toContain('1.23');
  });

  it('draws nothing when there is no anchor at all (pre-085 session)', () => {
    const d = resolveEnvelope(null, 1.30);
    expect(d.draw).toBe(false);
    expect(d.radiusG).toBeNull();
  });

  it('draws nothing for a non-finite or non-positive baseline', () => {
    for (const g of [NaN, Infinity, 0, -1]) {
      const d = resolveEnvelope(
        { baseline_g: g, tier: 'session_envelope_default_p2', reason: null }, 1.3);
      expect(d.draw).toBe(false);
    }
  });

  it('carries the refusal reason so the UI can explain itself', () => {
    const d = resolveEnvelope(
      { baseline_g: null, tier: 'refused', reason: 'channel_untrusted' }, 1.0);
    expect(d.reason).toBe('channel_untrusted');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events.test.ts`
Expected: FAIL — `resolveEnvelope` is not exported.

- [ ] **Step 3: Implement `resolveEnvelope`**

Append to `lap-website/src/lib/driving-events-draw.ts`:

```ts
export interface AnchorSummary {
  baseline_g: number | null;
  tier: string | null;
  reason: string | null;
}

export interface EnvelopeDecision {
  draw: boolean;
  radiusG: number | null;
  label: string;
  reason: string | null;
}

const TIER_LABEL: Record<string, string> = {
  session_envelope_ellipse_fitted: 'session envelope (fitted)',
  session_envelope_default_p2: 'session envelope (default p=2)',
  driver_best_session: 'your best this session',
};

/**
 * Decide what boundary, if any, the g-g diagram may draw.
 *
 * This replaces `frictionR = maxG * 0.95` -- a circle computed from the very
 * points it was drawn over, so it moved whenever the data moved and could
 * never place the driver outside it. `maxObservedG` is accepted ONLY so this
 * function can be given the whole picture; it is deliberately never used to
 * size the boundary. If the anchor refused, we draw nothing and say so.
 */
export function resolveEnvelope(
  anchor: AnchorSummary | null,
  _maxObservedG: number,
): EnvelopeDecision {
  if (!anchor || anchor.tier === 'refused' || anchor.tier == null) {
    return {
      draw: false, radiusG: null, reason: anchor?.reason ?? null,
      label: 'Grip limit not measured for this session',
    };
  }
  const g = anchor.baseline_g;
  if (typeof g !== 'number' || !Number.isFinite(g) || g <= 0) {
    return {
      draw: false, radiusG: null, reason: anchor.reason ?? null,
      label: 'Grip limit not measured for this session',
    };
  }
  const tier = TIER_LABEL[anchor.tier] ?? anchor.tier;
  return {
    draw: true, radiusG: g, reason: anchor.reason ?? null,
    label: `${g.toFixed(2)}G — ${tier}`,
  };
}
```

- [ ] **Step 4: Use it in GGExplorer**

Replace line 105 (`const frictionR = maxG * 0.95;`) with a decision derived from an `anchor` prop, and guard both use sites:

```ts
  const envelope = resolveEnvelope(opts.anchor ?? null, maxG);
```

At line 141, guard the radius computation and the arc:

```ts
  if (envelope.draw && envelope.radiusG != null) {
    const rPx = (envelope.radiusG / axisMax) * (pW / 2);
    // ... existing arc drawing, unchanged ...
  }
```

At line 209, replace the label with `envelope.label` — and when `envelope.draw` is false, still render `envelope.label` as plain text in the corner so the absence is stated rather than silent.

Add `anchor?: AnchorSummary | null` to `GGExplorerProps` and to its draw-options interface, fetched from `GET /sessions/<id>/corner-metrics` (which is a `SELECT *`, so `grip_anchor_tier`, `grip_anchor_reason` and `grip_anchor_baseline_g` are already in the response). Take the anchor of the modal tier across corners; if any corner refused, prefer `refused` — degrading loudly is the point.

- [ ] **Step 5: Run and typecheck**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events.test.ts && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Bite-check**

Change `resolveEnvelope`'s refusal branch to `return { draw: true, radiusG: _maxObservedG * 0.95, ... }` — i.e. reinstate the exact defect. Re-run.
Expected: `DRAWS NOTHING when the anchor refused` goes RED on `expect(d.draw).toBe(false)`. Restore.

Then `grep -n "0.95" lap-website/src/components/shared/charts/GGExplorer.tsx` and confirm it returns nothing. Paste both.

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/lib/driving-events-draw.ts lap-website/src/components/shared/charts/GGExplorer.tsx lap-website/src/__tests__/driving-events.test.ts
git commit -m "feat(events-ui): draw the g-g envelope from the grip anchor, not from itself"
```

---

### Task 5: "Nothing to fix" must not look like "could not measure"

**Files:**
- Create: `lap-website/src/components/app/DrivingEventsPanel.tsx`
- Test: `lap-website/src/__tests__/driving-events-panel.test.tsx`

**Interfaces:**
- Consumes: `fetchDrivingEvents`, `describeCapability`, `canQuoteMagnitude`, `canAttributeCost` (Task 1); `eventLabel`, `eventColor` (Task 2).
- Produces: `<DrivingEventsPanel sessionId={string} />` — the ranked "what should I fix next" list.

This is the surface that makes Global Constraints 1 and 2 visible rather than merely encoded.

- [ ] **Step 1: Write the failing tests**

Create `lap-website/src/__tests__/driving-events-panel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import DrivingEventsPanel from '@/components/app/DrivingEventsPanel';

vi.mock('@/lib/driving-events', async (orig) => {
  const actual = await orig<typeof import('@/lib/driving-events')>();
  return { ...actual, fetchDrivingEvents: vi.fn() };
});
import { fetchDrivingEvents } from '@/lib/driving-events';

const CLEAN_CAP = {
  over_slowing: 'not_triggered', late_throttle: 'not_triggered',
  re_braking: 'not_triggered', envelope_under_use: 'not_triggered',
} as const;

beforeEach(() => vi.mocked(fetchDrivingEvents).mockReset());

describe('DrivingEventsPanel distinguishes the empty states', () => {
  it('says nothing to fix when every detector looked and found nothing', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [], available: false, capability: { ...CLEAN_CAP }, capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('events-empty-clean')).toBeTruthy());
    expect(screen.queryByTestId('events-empty-degraded')).toBeNull();
  });

  it('says it could not measure when a detector reported insufficient', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [], available: false,
      capability: { ...CLEAN_CAP, over_slowing: 'insufficient' }, capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('events-empty-degraded')).toBeTruthy());
    expect(screen.queryByTestId('events-empty-clean')).toBeNull();
  });

  it('names which detectors could not look', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [], available: false,
      capability: { ...CLEAN_CAP, re_braking: 'insufficient' }, capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() =>
      expect(screen.getByTestId('events-empty-degraded').textContent).toContain('re_braking'));
  });
});

describe('DrivingEventsPanel obeys the attribution constraint', () => {
  const base = {
    lap_number: 3, corner_id: 4, s_norm_start: 0.2, s_norm_end: 0.3,
    validity: 'measured', reason: null, n_samples_in_window: 40,
    anchor_tier: 'session_envelope_ellipse_fitted', anchor_reason: null,
    evidence: {}, also_fired: [],
  };

  it('shows the cost as attributable for a caused event', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [{ ...base, event_type: 'over_slowing', magnitude: 1.4, magnitude_unit: 'm/s',
                 time_cost_s: 0.31, time_cost_attribution: 'caused',
                 magnitude_is_standalone_quotable: true }],
      available: true, capability: { ...CLEAN_CAP, over_slowing: 'detected' },
      capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('event-row-0')).toBeTruthy());
    expect(screen.getByTestId('event-cost-0').textContent).toContain('0.31');
    expect(screen.queryByTestId('event-cost-context-0')).toBeNull();
  });

  it('never prints a context event magnitude as a number', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [{ ...base, event_type: 'late_throttle', magnitude: 12.4, magnitude_unit: 'm',
                 time_cost_s: 0.31, time_cost_attribution: 'context',
                 magnitude_is_standalone_quotable: false }],
      available: true, capability: { ...CLEAN_CAP, late_throttle: 'detected' },
      capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('event-row-0')).toBeTruthy());
    expect(screen.getByTestId('event-row-0').textContent).not.toContain('12.4');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events-panel.test.tsx`
Expected: FAIL — cannot resolve the component.

- [ ] **Step 3: Implement the panel**

Create `lap-website/src/components/app/DrivingEventsPanel.tsx`:

```tsx
'use client';

/**
 * "What should I fix next" — the ranked driving-event list.
 *
 * Two things here are load-bearing, not styling:
 *
 * 1. FOUR empty states, not one. `events: []` is returned both by a clean
 *    session with nothing to fix and by a session whose grip anchor failed
 *    and left three of four detectors unable to look at anything. Rendering
 *    those identically tells the driver "you were perfect" when the truth is
 *    "we could not measure you".
 * 2. The cost is only ever presented as CAUSED by an event when the payload
 *    says it may be. `late_throttle` reports the identical corner-time gap
 *    `over_slowing` reports for the same corner-lap, and its added
 *    information beyond apex speed is not distinguishable from zero — so
 *    attributing that cost to its metres would count one measurement twice.
 */
import { useEffect, useState } from 'react';
import {
  fetchDrivingEvents, describeCapability, canAttributeCost,
  type DrivingEventsResponse,
} from '@/lib/driving-events';
import { eventLabel, eventColor } from '@/lib/driving-events-draw';

export default function DrivingEventsPanel({ sessionId }: { sessionId: string }) {
  const [res, setRes] = useState<DrivingEventsResponse | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    (async () => {
      const r = await fetchDrivingEvents(sessionId);
      if (cancelled) return;
      setRes(r);
      setLoaded(true);
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  if (!loaded) return <div data-testid="events-loading">Loading…</div>;

  const state = describeCapability(res);

  if (state === 'clean') {
    return (
      <div data-testid="events-empty-clean">
        Every detector ran and found nothing to flag on this session.
      </div>
    );
  }

  if (state === 'degraded') {
    const blind = Object.entries(res!.capability)
      .filter(([, v]) => v === 'insufficient')
      .map(([name]) => name);
    return (
      <div data-testid="events-empty-degraded">
        No events — but this is not a clean session. These detectors could not
        measure anything here: {blind.join(', ')}.
      </div>
    );
  }

  if (state === 'unavailable') {
    return (
      <div data-testid="events-empty-unavailable">
        Driving events were not computed for this session.
      </div>
    );
  }

  return (
    <ol data-testid="events-list">
      {res!.events.map((e, i) => (
        <li key={`${e.lap_number}-${e.corner_id}-${e.event_type}`}
            data-testid={`event-row-${i}`}>
          <span style={{ background: eventColor(e) }} aria-hidden />
          <span>{eventLabel(e)}</span>
          {canAttributeCost(e) ? (
            <span data-testid={`event-cost-${i}`}>
              costs {e.time_cost_s!.toFixed(2)}s
            </span>
          ) : typeof e.time_cost_s === 'number' && Number.isFinite(e.time_cost_s) ? (
            // Deliberately non-causal wording: the corner costs this much,
            // and this event happened in it. It did not necessarily cause it.
            <span data-testid={`event-cost-context-${i}`}>
              in a corner losing {e.time_cost_s.toFixed(2)}s
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd lap-website && npx vitest run src/__tests__/driving-events-panel.test.tsx && npx tsc --noEmit`
Expected: PASS, 5 tests.

- [ ] **Step 5: Bite-check**

Make the panel render `describeCapability` results `'clean'` and `'degraded'` through the same branch. Re-run.
Expected: `says it could not measure when a detector reported insufficient` goes RED. Restore.

Then make `eventLabel` print the magnitude unconditionally (drop the `canQuoteMagnitude` gate). Re-run.
Expected: `never prints a context event magnitude as a number` goes RED. Restore.

Paste both.

- [ ] **Step 6: Commit**

```bash
git add lap-website/src/components/app/DrivingEventsPanel.tsx lap-website/src/__tests__/driving-events-panel.test.tsx
git commit -m "feat(events-ui): ranked panel that tells clean apart from unmeasurable"
```

---

### Task 6: Real-render verification

**Files:**
- Test: `lap-website/src/__tests__/driving-events.test.ts` (append)

This is the gate. Everything above is unit-tested against stubs; this task proves the modules survive contact with a real payload shape and a real canvas context.

- [ ] **Step 1: Add a real-payload round trip**

Append to `lap-website/src/__tests__/driving-events.test.ts`:

```ts
describe('a full realistic payload survives the whole render path', () => {
  // Keys mirror Task 1's DrivingEvent exactly. If the API adds a field, this
  // fixture is the first place that should be updated -- and if it is NOT
  // updated, the type will still compile, which is why Step 2's check against
  // a live session is part of this task and not optional.
  const RESPONSE: DrivingEventsResponse = {
    available: true,
    capability_available: true,
    capability: {
      over_slowing: 'detected', late_throttle: 'detected',
      re_braking: 'detected', envelope_under_use: 'detected',
    },
    events: [
      ev({ event_type: 'over_slowing', corner_id: 1, lap_number: 4,
           s_norm_start: 0.04, s_norm_end: 0.11, magnitude: 1.62,
           magnitude_unit: 'm/s', time_cost_s: 0.885,
           time_cost_attribution: 'caused', magnitude_is_standalone_quotable: true,
           also_fired: [{ event_type: 'late_throttle', magnitude: 12.4,
                          magnitude_unit: 'm', validity: 'measured',
                          magnitude_is_standalone_quotable: false }] }),
      ev({ event_type: 'late_throttle', corner_id: 3, lap_number: 7,
           s_norm_start: 0.31, s_norm_end: 0.39, magnitude: 9.7,
           magnitude_unit: 'm', time_cost_s: 0.176,
           time_cost_attribution: 'context', magnitude_is_standalone_quotable: false }),
      ev({ event_type: 're_braking', corner_id: 6, lap_number: 2,
           s_norm_start: 0.55, s_norm_end: 0.61, magnitude: 9.80665,
           magnitude_unit: 'm/s2', time_cost_s: null,
           time_cost_attribution: 'no_cost', magnitude_is_standalone_quotable: true }),
      ev({ event_type: 'envelope_under_use', corner_id: 8, lap_number: 5,
           s_norm_start: 0.82, s_norm_end: 0.90, magnitude: 78.4,
           magnitude_unit: 'pct', time_cost_s: null,
           anchor_tier: 'driver_best_session',
           time_cost_attribution: 'no_cost', magnitude_is_standalone_quotable: true }),
      // An honest refusal: reached the payload, carries no magnitude.
      ev({ event_type: 'envelope_under_use', corner_id: 7, lap_number: 5,
           validity: 'not_measurable', reason: 'anchor_bound_self_referential',
           magnitude: null, magnitude_unit: null, time_cost_s: null,
           anchor_tier: 'driver_best_session',
           time_cost_attribution: 'no_cost', magnitude_is_standalone_quotable: true }),
      // No span at all -- must be skipped by the tape, not crash it.
      ev({ event_type: 'over_slowing', corner_id: 2, lap_number: 9,
           s_norm_start: null, s_norm_end: null }),
    ],
  };

  it('reports has-events and never throws through the whole path', () => {
    expect(describeCapability(RESPONSE)).toBe('has-events');
    const r = recorder();
    expect(() => {
      for (const e of RESPONSE.events) {
        canQuoteMagnitude(e); canAttributeCost(e); eventLabel(e); eventColor(e);
      }
      drawCornerShade(r.ctx, RESPONSE.events, GEO);
      drawMistakeTape(r.ctx, RESPONSE.events, GEO);
    }).not.toThrow();
  });

  it('draws a segment for every event that has a span, and none for those without', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, RESPONSE.events, GEO);
    const withSpan = RESPONSE.events.filter(
      (e) => typeof e.s_norm_start === 'number' && typeof e.s_norm_end === 'number').length;
    expect(r.rects().length).toBe(withSpan);
  });

  it('never renders a magnitude for the refusal or for the context event', () => {
    const refusal = RESPONSE.events.find((e) => e.validity === 'not_measurable')!;
    const context = RESPONSE.events.find((e) => e.time_cost_attribution === 'context')!;
    expect(canQuoteMagnitude(refusal)).toBe(false);       // magnitude is null
    expect(eventLabel(context)).not.toContain('9.7');
    expect(canAttributeCost(context)).toBe(false);
  });

  it('lets exactly one event in this payload claim its cost', () => {
    expect(RESPONSE.events.filter(canAttributeCost).length).toBe(1);
  });
});
```

- [ ] **Step 2: Verify against the running backend**

Start the webapp per `infra_webapp_local_run` conventions (`next dev`, not `next start` — this project is `output:standalone`) and confirm against a real session that:
1. the tape appears on the speed trace when `showDrivingEvents` is set;
2. the g-g diagram shows a tier-labelled envelope, or the explicit "not measured" text;
3. `grep -rn "0\.95" lap-website/src/components/shared/charts/GGExplorer.tsx` returns nothing.

Record what you saw. **If you cannot reach a real session, say so plainly and report which of the three you could not verify** — do not claim a visual check you did not perform.

- [ ] **Step 3: Full suite**

Run: `cd lap-website && npm test && npx tsc --noEmit`
Expected: PASS. Note any pre-existing failures separately and prove they are pre-existing by checking out `87a1330` in a throwaway worktree.

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/__tests__/driving-events.test.ts
git commit -m "test(events-ui): real-payload round trip through the render path"
```

---

## Known not covered by Phase 3

- **Per-lap phase segmentation.** Spec §6 assigns it to Phase 2 and it was never built — `_EnvelopeUnderUse`'s docstring says "a per-phase slice" but the number is whole-corner. So §5.8's `/gg-data` extension can deliver per-sample `corner_id` but not `phase`. Deferred deliberately rather than half-built.
- **`/gg-data` per-sample `corner_id`.** Needs a backend change; the exploitation map's honest envelope (Task 4) is the high-value half and needs none.
- **Driving signature / habits.** Spec §6 Phase 5 — gated on cross-session corner identity, which does not exist.
- **Cross-session anything.** `corner_id` is positional per-session.
- **`corner-consistency` rendering.** The endpoint ships; a "where am I unreliable" view is a follow-on once the ranked list is proven.
