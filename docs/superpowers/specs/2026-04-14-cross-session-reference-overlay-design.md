# Cross-Session Reference Lap Overlay

**Date:** 2026-04-14
**Status:** Approved
**Scope:** Backend API + frontend overlay on session detail page + compare page enhancement

## Problem

Users can only compare laps within the same session. There is no way to overlay a lap from a previous session onto the current session's charts for cross-session analysis (e.g., comparing today's best lap with last week's best on the same track).

## Solution

Add a reference lap overlay system that works across all three visualization charts (speed trace, track map, GG explorer) on both the session detail page and the compare page. A single composite API endpoint provides all reference data in one fetch. A React context provider distributes that data to all charts simultaneously.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where it lives | Session detail page (overlay) + compare page (enhanced) | Both surfaces serve different workflows — quick ad-hoc vs deep comparison |
| Data fetching | Single composite endpoint (Approach B) | Eliminates flicker between charts, one distance alignment pass, clean loading state |
| Reference color | Racing purple (#8B5CF6) dashed | Distinct from gold primary, uses existing design token |
| Picker UI | Floating action button + modal | Discoverable, doesn't clutter toolbar, provides room for session details |
| Hover sync | Dual markers (primary + reference) | Full comparison experience — see both positions at every distance |

## Backend API

### GET /api/v1/sessions/{id}/reference-candidates

Returns sessions on the same track as session `{id}`, for populating the reference picker dropdown. Ordered by date descending.

**Query params:** None required. Optional: `limit` (default 20).

**Response:**

```json
{
  "ok": true,
  "data": [
    {
      "session_id": "abc-123",
      "driver_name": "John",
      "session_date": "2026-04-10",
      "best_lap_time_s": 44.8,
      "n_laps": 12,
      "session_type": "practice"
    }
  ]
}
```

**Implementation:** Query the sessions table joined on `track_id` from the primary session. Exclude the current session. Reuses existing session-list query logic with a track filter added.

### GET /api/v1/sessions/{id}/reference-data

Returns speed, GPS, and GG data for both the primary and reference laps, interpolated onto a common distance axis.

**Query params:**
- `ref_session` (required) — session ID of the reference session
- `ref_lap` (required) — lap number in the reference session
- `primary_lap` (required) — lap number in the current session

**Response:**

```json
{
  "ok": true,
  "data": {
    "primary": {
      "session_id": "current-session-id",
      "lap_number": 3,
      "lap_time_s": 45.2
    },
    "reference": {
      "session_id": "ref-session-id",
      "lap_number": 5,
      "lap_time_s": 44.8,
      "driver_name": "John",
      "session_date": "2026-04-10"
    },
    "distances": [0.0, 1.2, 2.4, ...],
    "speed": {
      "primary": [12.1, 12.3, ...],
      "reference": [12.5, 12.6, ...],
      "delta_s": [0.0, -0.02, -0.05, ...]
    },
    "gps": {
      "primary": { "latitudes": [...], "longitudes": [...] },
      "reference": { "latitudes": [...], "longitudes": [...] }
    },
    "gg": {
      "primary": { "accel_lat": [...], "accel_long": [...] },
      "reference": { "accel_lat": [...], "accel_long": [...] }
    }
  }
}
```

**Implementation:**
1. Fetch raw lap data for both sessions using existing query functions from `data_v2.py` (same SQL that feeds speed-trace, gps-trace, gg-data endpoints).
2. Build common distance axis: use the shorter lap's distance range, resample to max 500 points.
3. Interpolate both datasets onto the common axis using `np.interp()` — same strategy as the existing compare endpoint (data_v2.py ~line 3744).
4. Compute cumulative time delta (`delta_s`): integrate speed difference over distance.
5. Return all three data types in one response.

**Validation:** Both sessions must exist and belong to the user's workspace. Both must be on the same track (guard against cross-track comparison which would be meaningless). Returns 404 if either session/lap not found, 400 if tracks don't match.

## Frontend: ReferenceOverlayProvider

A React context provider that manages reference overlay state and distributes data to all child charts.

### Interface

```typescript
interface ReferenceData {
  primary: { session_id: string; lap_number: number; lap_time_s: number };
  reference: {
    session_id: string; lap_number: number; lap_time_s: number;
    driver_name: string; session_date: string;
  };
  distances: number[];
  speed: { primary: number[]; reference: number[]; delta_s: number[] };
  gps: {
    primary: { latitudes: number[]; longitudes: number[] };
    reference: { latitudes: number[]; longitudes: number[] };
  };
  gg: {
    primary: { accel_lat: number[]; accel_long: number[] };
    reference: { accel_lat: number[]; accel_long: number[] };
  };
}

interface ReferenceOverlayContextValue {
  referenceSession: string | null;
  referenceLap: number | null;
  referenceData: ReferenceData | null;
  isLoading: boolean;
  error: string | null;
  setReference: (sessionId: string, lap: number) => void;
  clearReference: () => void;
}
```

### Component tree (session detail page)

```
<ChartSyncProvider syncId="session-detail">
  <ReferenceOverlayProvider sessionId={id} primaryLap={selectedLap}>
    <ReferenceFAB />           // FAB + modal picker
    <SpeedTraceChart />        // Reads referenceData.speed via context
    <TrackMap />               // Reads referenceData.gps via context
    <GGExplorer />             // Reads referenceData.gg via context
  </ReferenceOverlayProvider>
</ChartSyncProvider>
```

### Behaviors

- **Primary lap change:** When user changes the selected lap on the session detail page, the provider re-fetches with the new `primary_lap` to get fresh distance alignment against the reference.
- **Clear reference:** All charts drop the overlay instantly. No fetch.
- **Loading:** Subtle spinner on the FAB pill, not on individual charts. Charts continue to render primary data while reference loads.
- **Error:** Toast notification. Charts continue working without overlay.

## Frontend: Reference Picker (FAB + Modal)

### ReferenceFAB component

A floating action button positioned in the bottom-right of the chart area.

**Idle state:** Purple circle with "+" icon. Positioned `bottom-4 right-4` relative to the chart container.

**Active state (reference selected):** Transforms into a pill showing reference info: "Apr 10 L5 (44.8s)" with an X button to clear. Border in racing-purple.

**Modal (on FAB click):**
1. Fetches `/api/v1/sessions/{id}/reference-candidates` on open.
2. Shows searchable list of same-track sessions, ordered by date descending.
3. Each row shows: date, session type, best lap time, driver name, lap count.
4. Clicking a session defaults to its best lap and closes the modal.
5. Optional: expand a session row to see individual laps for specific lap selection.
6. Search filters by date or driver name (client-side filter on the candidates list).

## Chart Overlay Rendering

All reference data rendered in racing-purple (#8B5CF6).

### Speed Trace Chart

- **Reference line:** Dashed line (`stroke-dasharray: 6,4`) in racing-purple, 70% opacity.
- **Delta bar:** Thin horizontal bar below the speed chart. Green segments where primary is faster, red where slower. Uses `delta_s` from the API.
- **Legend:** Gold solid line "Your lap (45.2s)" + purple dashed line "Reference (44.8s)".
- **Hover tooltip:** Shows both speed values and the delta at the hovered distance.

### Track Map

- **Reference path:** Dashed polyline in racing-purple, 50% opacity, rendered behind the primary path.
- **Primary marker:** Solid gold dot at the hovered distance position.
- **Reference marker:** Hollow purple circle at the hovered distance position on the reference GPS path.

### GG Explorer

- **Reference scatter:** Hollow circles in racing-purple, 40% opacity, rendered behind primary dots.
- **Primary dots:** Filled gold circles (unchanged from current).
- **Hover:** Solid gold dot (primary acceleration) + hollow purple circle (reference acceleration) at the hovered distance.

### Edge case: different lap lengths

If the reference lap is shorter than the primary, the common distance axis ends at the shorter lap's max distance. Beyond that range, only primary data renders (reference markers disappear). The delta bar shows no data beyond the common range.

## Dual Hover Sync

No new store or provider needed. The existing `ChartSyncProvider` broadcasts `hoverDistance` as meters along the lap. Since both primary and reference share the same `distances` array from the composite endpoint, a single distance index maps to both datasets.

**Flow:**
1. User hovers at distance `d` on any chart.
2. `ChartSyncProvider` broadcasts `d` to all charts (existing behavior, unchanged).
3. Each chart finds the index `i` where `distances[i]` is closest to `d`.
4. Reads `primary[i]` and `reference[i]` from the relevant dataset (speed, GPS, or GG).
5. Renders both markers: solid gold (primary) + hollow purple (reference).

## Compare Page Enhancements

The existing compare page at `/app/compare/sessions` already has session pickers and speed comparison.

### Changes

1. **Add TrackMap overlay:** Render a single TrackMap with both GPS paths using the same overlay rendering as the session detail page. Data already available from compare API (`gps_a`, `gps_b`).
2. **Add GGExplorer overlay:** Render a single GG diagram with both scatter datasets. The compare page calls the composite `/reference-data` endpoint to get GG data (which the old compare endpoint doesn't provide).
3. **Wrap in ChartSyncProvider:** All three charts share one sync group. Hovering on speed trace shows dual markers on track map and GG.
4. **Reuse overlay rendering:** Same racing-purple dashed treatment, same dual-marker hover behavior.

### What stays the same
- Session picker UI (already works)
- URL structure (`/app/compare/sessions?a=...&b=...`)
- Speed trace comparison (already works, gains dual-marker hover)

## Files to Create or Modify

### New files
- `lap-website/src/components/app/reference/ReferenceOverlayProvider.tsx` — context provider + hook
- `lap-website/src/components/app/reference/ReferenceFAB.tsx` — FAB + modal picker
- `lap-website/src/components/app/reference/types.ts` — ReferenceData interface

### Modified files
- `telemetry_tool/web/routes/data_v2.py` — two new endpoint functions (reference-candidates, reference-data)
- `lap-website/src/components/shared/charts/SpeedTraceChart.tsx` — consume reference context, render dashed overlay + delta bar
- `lap-website/src/components/shared/charts/TrackMap.tsx` — consume reference context, render dashed GPS path + dual markers
- `lap-website/src/components/shared/charts/GGExplorer.tsx` — consume reference context, render hollow scatter + dual markers
- `lap-website/src/app/app/sessions/[id]/page.tsx` — wrap charts in ReferenceOverlayProvider, add ReferenceFAB
- `lap-website/src/app/app/compare/sessions/page.tsx` — add TrackMap + GGExplorer, wrap in ChartSyncProvider, use overlay rendering

## Testing

### Backend
- Unit tests for reference-candidates endpoint (same-track filter, excludes current session, respects workspace RLS)
- Unit tests for reference-data endpoint (distance alignment, interpolation correctness, cross-track rejection, missing lap 404)
- Integration test: full round-trip with two seeded sessions on the same track

### Frontend
- ReferenceOverlayProvider: mount with mock data, verify context values propagate to children
- ReferenceFAB: open modal, select session, verify setReference called with correct args
- Chart overlays: render with referenceData, verify dashed line/path/scatter elements exist in DOM
- Hover sync: simulate hover, verify both markers rendered on all charts
- Edge case: reference shorter than primary, verify graceful fade-out
