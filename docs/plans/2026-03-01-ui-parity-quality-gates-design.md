# UI Parity + Quality Gates Design

**Date:** 2026-03-01
**Status:** Approved
**Goal:** Extract reusable chart components from session-detail, add SectorPanel + CornerReplay, add seeded API contract tests, E2E smoke test, and structured observability.

---

## Workstream 1: Shared Chart Component Library

### Problem

The 3 existing chart wrappers (SpeedTraceZoom, GpsTrace, GGExplorer) are hardwired to a single session in `src/components/app/charts/`. Compare, Weekends, Analytics, and Report pages can't reuse them without duplicating code. SectorPanel and CornerReplay don't exist as React components yet.

### Approach: Dual-Mode Props

Extract components to `src/components/shared/charts/`. Each accepts either a `sessionId` (self-fetching via API) OR pre-fetched `data` props. This lets single-session pages keep the simple sessionId API while Compare/Analytics pages pass pre-fetched or merged data.

### Components

#### TrackMap (refactored from GpsTrace.tsx)

Props:
```typescript
interface TrackMapProps {
  sessionId?: string;
  lap?: number;
  data?: { latitudes: number[]; longitudes: number[]; distances: number[]; speeds?: number[] };
  corners?: { corner_id: number; lat: number; lon: number; label?: string }[];
  markerDistance?: number;          // External hover control
  onHoverDistance?: (d: number) => void;  // Emit distance on hover
  className?: string;
}
```

Behavior: Leaflet polyline colored by speed. Corner markers. Animated dot follows `markerDistance`. Emits distance on polyline hover. When `data` is provided, renders immediately; when `sessionId` is given, fetches from `/gps-trace?lap=N`.

#### SpeedTraceChart (refactored from SpeedTraceZoom.tsx)

Props:
```typescript
interface SpeedTraceChartProps {
  sessionId?: string;
  lap?: number;
  data?: { distances: number[]; speeds: number[]; ref_speeds?: number[] };
  refLap?: number;                 // Fetch ref overlay from API
  markerDistance?: number;
  onHoverDistance?: (d: number) => void;
  className?: string;
}
```

Behavior: Canvas speed-vs-distance chart. Drag-to-zoom. Optional reference lap overlay (dotted line). Crosshair follows `markerDistance`. Emits distance on hover.

#### GGExplorer (refactored from GGExplorer.tsx)

Props:
```typescript
interface GGExplorerProps {
  sessionId?: string;
  lap?: number;
  data?: { accel_lat: number[]; accel_long: number[] };
  mode?: 'all' | 'single' | 'compare';
  className?: string;
}
```

Behavior: Scatter plot of lateral vs longitudinal acceleration. Density heatmap option. Mini track map inset. Mode buttons for All/Single/Compare views.

#### ChartSyncProvider (new)

```typescript
interface ChartSyncProviderProps {
  children: React.ReactNode;
  syncId?: string;  // Isolates sync groups (e.g., "compare-left" vs "compare-right")
}
```

Wraps chart groups. Any chart inside participates in distance-based hover sync. Different `syncId` values create independent sync buses. Uses React context backed by the existing `useChartHoverStore` Zustand store.

#### SectorPanel (new)

Data source: `GET /sessions/{id}/sectors`

```
┌─────────────────────────────────────────────┐
│ Ideal Lap: 58.234s  (sum of best sectors)   │
│                                             │
│  S1      S2      S3      S4                 │
│ ┌──────┬──────┬──────┬──────┐               │
│ │ 14.2 │ 15.1 │ 13.8 │ 15.1 │  Best        │
│ │ 14.5 │ 15.3 │ 14.0 │ 15.2 │  Mean        │
│ │ 0.3  │ 0.2  │ 0.2  │ 0.1  │  Gap         │
│ └──────┴──────┴──────┴──────┘               │
│                                             │
│ ████████ ██████ ████████ ██████  Heatmap    │
│ (green=close to best, red=far from best)    │
│                                             │
│ Insight: Sector 3 lowest variance (0.8%)    │
│          Sector 2 highest time loss (0.2s)  │
└─────────────────────────────────────────────┘
```

Props:
```typescript
interface SectorPanelProps {
  sessionId: string;
  data?: SectorAnalysisResult;  // Pre-fetched override
  className?: string;
}
```

Implementation: Pure React + Tailwind. No vanilla JS. Sector gap cells colored green-to-red based on time delta. Coaching insights auto-generated from sector stats.

#### CornerReplay (new)

Data sources: `/corner-positions`, `/corner-metrics`, `/gps-trace?lap=N`

```
┌─────────────────────────────────────────────────────┐
│ Corner: [C1 ▼]   Laps: [Best ▼] vs [Lap 5 ▼]      │
│                                                     │
│ ┌──────────────────────┬──────────────────────┐     │
│ │   Mini track map     │   Mini track map     │     │
│ │   (lap A, corner     │   (lap B, corner     │     │
│ │    segment only)     │    segment only)     │     │
│ │   + animated dot     │   + animated dot     │     │
│ └──────────────────────┴──────────────────────┘     │
│                                                     │
│  ◀◀  ▶/❚❚  ▶▶   ──●────────────── 45%              │
│                                                     │
│ ┌─────────────────────────────────────────────┐     │
│ │ Speed profile through corner (both laps)    │     │
│ │ Entry: 85 km/h vs 82 km/h                  │     │
│ │ Apex:  62 km/h vs 65 km/h                  │     │
│ │ Exit:  78 km/h vs 75 km/h                  │     │
│ │ Brake: 45.5m vs 48.2m                      │     │
│ │ Loss:  +0.087s vs +0.142s                  │     │
│ └─────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

Props:
```typescript
interface CornerReplayProps {
  sessionId: string;
  initialCorner?: number;
  className?: string;
}
```

Implementation:
- **Corner segmentation**: Extract GPS points between `s_start` and `s_end` from full lap trace. Binary search on `distances[]` to find array indices.
- **Playback**: `requestAnimationFrame` loop advances distance cursor through corner segment. Animated dot follows on mini Leaflet map.
- **Split compare**: Two side-by-side mini maps, synchronized playback. Same distance cursor drives both dots.
- **Speed profile**: Canvas chart showing speed-vs-distance through corner for both laps overlaid.
- **Controls**: Play/pause, step forward/back, scrub slider. Speed multiplier (0.5x/1x/2x).

### File Structure

```
src/components/shared/charts/
├── TrackMap.tsx
├── SpeedTraceChart.tsx
├── GGExplorer.tsx
├── SectorPanel.tsx
├── CornerReplay.tsx
├── ChartSyncProvider.tsx
├── useVanillaChart.ts          (moved from app/charts/)
├── useChartData.ts             (new: shared data-fetching hook)
└── index.ts                    (barrel export)
```

Original `src/components/app/charts/` components become thin wrappers that import from shared.

---

## Workstream 2: Quality Gates

### A. Backend API Contract Tests

**File:** `telemetry_tool/tests/test_api_contracts.py`

Uses `seeded_db` fixture (real SQLite with sample data) — NOT mocks. Verifies every endpoint returns correct response shapes with real data.

```python
@pytest.mark.parametrize("path,expected_keys", [
    ("/sessions/{sid}/speed-trace?lap=1", {"distances", "speeds", "lap_number"}),
    ("/sessions/{sid}/gps-trace?lap=1", {"latitudes", "longitudes", "distances", "speeds", "lap_number"}),
    ("/sessions/{sid}/gg-data?lap=1", {"accel_lat", "accel_long", "lap_number"}),
    ("/sessions/{sid}/corner-positions", {"corners"}),
    ("/sessions/{sid}/track-map?lap=best", {"laps", "best_lap", "corners"}),
    ("/sessions/{sid}/sectors", ...),
    ("/sessions/{sid}/compare?sessionKeyB=...", ...),
    # ... all 30+ endpoints
])
def test_endpoint_contract(seeded_client, path, expected_keys):
    resp = seeded_client.get(path.format(sid=SEEDED_SESSION_ID))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "request_id" in body.get("meta", {})
    assert set(body["data"].keys()) >= expected_keys
```

Additional checks:
- Array length parity (all trace arrays same length)
- Distance axis monotonically increasing
- No NaN/Infinity in JSON (handled by `_NaNSafeJSONProvider`)
- `request_id` present in every response meta

### B. Playwright E2E Smoke Test

**File:** `lap-website/e2e/smoke-flow.spec.ts`

One critical user journey, end-to-end:

```
1. Upload CSV fixture (checked into repo at e2e/fixtures/test-session.csv)
2. Verify session appears in session list
3. Open session detail page
4. Visualize tab:
   - Map has Leaflet polyline (not empty container)
   - Speed trace canvas has drawn content
   - GG explorer scatter has data points
5. Corners tab: corner list loads with coaching text
6. Navigate to Analytics page: verify it loads without errors
```

Runs against dev server (localhost:5000 + localhost:3000). Uses Playwright `page.waitForSelector()` to verify real DOM content, not just element existence.

### C. CI Integration

```bash
# Backend
pytest telemetry_tool/tests/test_api_contracts.py -v

# Frontend
npx playwright test e2e/smoke-flow.spec.ts
```

---

## Workstream 3: Observability

### A. X-Request-Id Response Header

In `telemetry_tool/web/api_utils.py`, `init_request_id()` `after_request`:

```python
response.headers["X-Request-Id"] = g.request_id
```

Frontend can surface this in error toasts for support debugging.

### B. Structured JSON Logging

**File:** `telemetry_tool/web/json_logger.py`

```python
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add request context when available
        try:
            from flask import g, request
            log_entry["request_id"] = getattr(g, "request_id", None)
            log_entry["method"] = request.method
            log_entry["path"] = request.path
        except RuntimeError:
            pass  # Outside request context
        # Add extras
        for key in ("status_code", "duration_ms"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry, default=str)
```

Wire into `setup_logging()`: use JSONFormatter when `TELEMETRY_LOG_FORMAT=json` (default in Docker), human-readable otherwise.

### C. Request Timing

In `init_request_id()`:

```python
@app.before_request
def before_req():
    g.request_id = str(uuid4())
    g.request_start = time.monotonic()

@app.after_request
def after_req(response):
    duration_ms = round((time.monotonic() - g.request_start) * 1000, 1)
    response.headers["X-Request-Id"] = g.request_id
    logger.info(
        "%s %s %d (%.1fms)",
        request.method, request.path, response.status_code, duration_ms,
        extra={"status_code": response.status_code, "duration_ms": duration_ms},
    )
    return response
```

---

## Files Modified/Created

| File | Changes |
|------|---------|
| `lap-website/src/components/shared/charts/TrackMap.tsx` | New: refactored from GpsTrace |
| `lap-website/src/components/shared/charts/SpeedTraceChart.tsx` | New: refactored from SpeedTraceZoom |
| `lap-website/src/components/shared/charts/GGExplorer.tsx` | New: refactored from GGExplorer |
| `lap-website/src/components/shared/charts/SectorPanel.tsx` | New |
| `lap-website/src/components/shared/charts/CornerReplay.tsx` | New |
| `lap-website/src/components/shared/charts/ChartSyncProvider.tsx` | New |
| `lap-website/src/components/shared/charts/useVanillaChart.ts` | Moved from app/charts/ |
| `lap-website/src/components/shared/charts/useChartData.ts` | New: shared data-fetching hook |
| `lap-website/src/components/shared/charts/index.ts` | New: barrel export |
| `lap-website/src/components/app/charts/*.tsx` | Updated: import from shared |
| `telemetry_tool/tests/test_api_contracts.py` | New: seeded contract tests |
| `lap-website/e2e/smoke-flow.spec.ts` | New: full-flow E2E smoke |
| `lap-website/e2e/fixtures/test-session.csv` | New: test fixture CSV |
| `telemetry_tool/web/api_utils.py` | Add X-Request-Id header + timing |
| `telemetry_tool/web/json_logger.py` | New: JSON log formatter |
| `telemetry_tool/web/logging_setup.py` | Wire JSON formatter |

### Execution Order

```
Workstream 3 (observability — backend only, independent)
  → Workstream 2A (contract tests — needs observability for request_id checks)
  → Workstream 1 (shared components — largest, needs stable API contracts)
  → Workstream 2B (E2E smoke — needs components deployed)
```

Workstream 3 is small and independent. Workstream 1 is the bulk of work.
