# Testing + CI Discipline, Parity Polish & Ergonomics — Design

**Date:** 2026-03-02
**Status:** Approved
**Scope:** Backend/frontend test coverage, CI pipeline hardening, formatting parity, bulk ops, Focus Mode restoration

## Context

The project has solid but uneven test coverage: ~500+ backend tests, 204 Vitest tests, 205 Playwright specs. However, Playwright E2E never runs in CI, integration tests skip silently (no PG in CI), there's no coverage tooling, and the contract test surface is limited to request schemas only. The SaaS frontend has formatting divergences from the desktop tool (lap times, distances, badges) and missing efficiency features (Select All, working re-analyze, full Focus Mode).

Three parallel workstreams address this: testing infrastructure, parity polish, and ergonomics restoration.

## Section 1: Testing Infrastructure

### 1a. Golden fixture parity tests

**File:** `telemetry_tool/tests/test_golden_parity.py`

Run the full 14-stage pipeline on a checked-in CSV fixture (`telemetry_tool/tests/fixtures/golden_session.csv`). Compare output against a golden JSON baseline (`telemetry_tool/tests/fixtures/golden_baseline.json`) within tolerances:
- Lap times: ±0.5s
- Speeds: ±0.5 m/s
- Scores: ±5 points
- GPS coordinates: ±0.0001° (~11m)

Uses `seeded_db` fixture pattern. Covers the same parity features as `certification-parity.spec.ts` but at the Python level — no network, no browser, deterministic.

### 1b. Lap validity, incomplete, and scoring boundary tests

**File:** `telemetry_tool/tests/test_scoring_boundaries.py`

Test `scoring.py` edge cases:
- Perfect lap (all metrics maxed) → score 100, grade A+
- Zero-length lap → score 0
- Single-lap session → valid scoring (no comparison lap)
- Invalid laps excluded from averages
- Incomplete lap handling (outlap, inlap, short lap)
- Letter grade boundaries: A (90+), B (80+), C (70+), D (60+), F (<60)
- Scoring with NaN/Inf inputs (graceful degradation via `_safe_step`)

### 1c. Sector and corner unit tests

**File:** `telemetry_tool/tests/test_sectors_corners.py`

- Corner detection with known geometry (synthetic oval from `conftest.py`)
- Sector time extraction from lap data
- Corner coaching delta calculations (`corner_coaching.py`)
- Reference line generation for known track shapes

### 1d. Contract tests — response shape assertions

**File:** `telemetry_tool/tests/test_api_contracts.py`

For each endpoint, assert response matches contract:

| Endpoint | Key assertions |
|----------|---------------|
| `GET /api/v1/sessions` | `{ok, data: {sessions: [{session_id: int, ...}]}, meta: {cursor, has_more}}` |
| `GET /api/v1/sessions/{id}` | `{ok, data: {session: {...}, laps: [...], scores: {...}}}` |
| `GET /api/v1/sessions/{id}/laps` | `{ok, data: {laps: [{lap_number: int, lap_time_s: float, ...}]}}` |
| `GET /api/v1/sessions/{id}/speed-trace` | `{ok, data: {traces: [{lap: int, points: [...]}]}}` |
| `GET /api/v1/sessions/{id}/gps-trace` | `{ok, data: {traces: [{lap: int, points: [{lat, lon, ...}]}]}}` |
| `GET /api/v1/sessions/{id}/gg-data` | `{ok, data: {gg: [{lap: int, points: [...]}]}}` |
| `GET /api/v1/sessions/{id}/scores` | `{ok, data: {scores: {total, pace, consistency, execution, robustness}}}` |
| `GET /api/v1/sessions/{id}/corners` | `{ok, data: {corners: [{corner_id: int, ...}]}}` |
| `POST /auth/register` | `{ok, data: {user_id, access_token}}` |
| `POST /auth/login` | `{ok, data: {access_token, user: {...}}}` |
| `GET /api/v1/race-strategy/` | `{ok, data: {races: [...]}}` |
| Error responses | `{ok: false, error: {code: str, message: str}}` |

Uses Flask test client, no network. Validates types with `isinstance` checks, not full Pydantic.

### 1e. Playwright E2E — critical path

**File:** `lap-website/e2e/critical-path.spec.ts`

Against local dev server with seeded SQLite:
1. Navigate to login → enter credentials → verify redirect to dashboard
2. Upload a CSV via `/app/sessions` upload button → wait for pipeline completion
3. Verify session appears in session list with correct name/date
4. Navigate to session detail → verify tabs render (Overview, Laps, Analytics)
5. Verify drivers list populated from uploaded data
6. Verify tracks list populated from uploaded data

### 1f. Playwright E2E — compare flow

**File:** `lap-website/e2e/compare-flow.spec.ts`

1. Navigate to `/app/compare`
2. Select Session A and Session B from dropdowns
3. Verify comparison page renders with score deltas
4. Verify lap-by-lap comparison table has data
5. Verify speed/GPS/GG charts render (check canvas elements exist)

### 1g. Playwright E2E — bulk actions

**File:** `lap-website/e2e/bulk-actions.spec.ts`

1. Navigate to session list with 3+ sessions
2. Select 2 sessions via checkboxes
3. Verify bulk action bar appears with "Delete 2 Sessions" button
4. Test delete flow (confirm dialog → sessions removed from list)
5. Select 2 sessions → verify "Compare" button appears → click navigates to compare page

## Section 2: CI Pipeline

### Current state

```yaml
# ci.yml — 4 jobs
security-headers → test-backend → test-frontend → deploy-api
```

### Target state

```yaml
# ci.yml — 7 jobs
PR checks (parallel):
  - security-headers
  - test-backend (pytest telemetry_tool/tests/ + kart_envelope/tests/)
  - test-frontend (lint + vitest + build)
  - contract-tests (pytest test_api_contracts.py)
  - typecheck (tsc --noEmit)
  - e2e-smoke (critical-path.spec.ts against local dev)

Push to main (sequential, requires all PR checks):
  - deploy-api → parity-smoke-live (certification-parity.spec.ts against live URL)
```

### 2a. Contract tests job

Separate job so contract failures are clearly visible in PR status. Runs `pytest telemetry_tool/tests/test_api_contracts.py -v --tb=short`.

### 2b. TypeScript typecheck job

`cd lap-website && npx tsc --noEmit`. Faster than full build, clearer error messages for type issues.

### 2c. E2E smoke job

Uses `docker-compose` to start Flask + SQLite with seeded data:
```yaml
services:
  api:
    build: .
    environment:
      - USE_PG=0
      - AUTH_REQUIRED=0
    ports: ["5000:5000"]
```
Then runs `npx playwright test e2e/critical-path.spec.ts --project=chromium`.

### 2d. Staging parity gate

After deploy to production, run certification parity specs against live URL. Uses GitHub secrets for test account credentials. If parity smoke fails, the workflow is marked failed (alerting the team). Manual rollback decision.

## Section 3: Parity Polish

### 3a. Unified `formatLapTime()`

Create a shared utility `lap-website/src/lib/format-utils.ts`:
```typescript
export function formatLapTime(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return '—';
  if (seconds >= 60) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds - mins * 60;
    return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
  }
  return `${seconds.toFixed(3)}s`;
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

export function formatDistance(meters: number | null | undefined): string {
  if (meters == null || !isFinite(meters)) return '—';
  return `${Math.round(meters)}`;  // integer, matches desktop
}

export function mpsToKmh(mps: number | null | undefined): string {
  if (mps == null || !isFinite(mps)) return '—';
  return (mps * 3.6).toFixed(1);
}

export function mps2ToG(mps2: number | null | undefined): string {
  if (mps2 == null || !isFinite(mps2)) return '—';
  return (Math.abs(mps2) / 9.81).toFixed(2);
}
```

Replace all per-page formatting functions with imports from this shared module. Pages affected: `sessions/page.tsx`, `sessions/[id]/page.tsx`, `compare/sessions/page.tsx`.

### 3b. Badge parity

Add to session detail and compare pages:
- **Joker badge**: Yellow `J` badge when `lap.is_joker === true`
- **Pit badge**: Distinct amber badge with "Pit" label when `invalid_reason === 'Pitted lap'`
- **Keep SaaS improvements**: "Valid" green badge, separate "Incomplete" yellow badge

Badge priority (highest first): Best > Joker > Pit > Invalid > Incomplete > Valid

### 3c. Date standardization

All pages use `formatDate()` from the shared module. No more raw ISO strings in compare metadata or session detail info cards.

### 3d. Null sentinel standardization

All null/missing values render as `—` (em dash, `\u2014`). No more `--` double hyphen anywhere.

## Section 4: Efficiency Ergonomics

### 4a. Bulk operations completeness

**Session list page** (`sessions/page.tsx`):

1. **Select All** checkbox in table header — toggles all visible sessions (respects current filter)
2. **Wire re-analyze** to `POST /api/v1/sessions/batch-reanalyze` with `{ session_ids: [...] }`:
   - Show progress ("Re-analyzing 3/5...")
   - Update session list on completion
   - Error handling for partial failures ("2 succeeded, 1 failed")
3. **Count badges** on action buttons: "Delete 3 Sessions", "Re-analyze 5 Sessions"
4. **Live status** text during operations (spinner + count)

### 4b. One-click compare

When exactly 2 sessions are selected in bulk, show a "Compare" button in the action bar. Navigates to `/app/compare/sessions?a={id1}&b={id2}`.

### 4c. Focus Mode — full desktop parity

**Architecture:**

```
FocusMode (fullscreen overlay)
├── CornerNavBar (top) — time-loss chips per corner
├── ToolDock (left sidebar) — icon toggles
└── SplitPane (main area) — resizable panels
    ├── Panel 1: [active tool]
    ├── Panel 2: [active tool]
    └── ... (dynamic based on active tools)
```

**Components to build/activate:**

| Component | Status | Work |
|-----------|--------|------|
| `FocusMode.tsx` | Exists, hardcoded | Rewrite to use ToolDock + SplitPane |
| `SplitPane.tsx` | Exists, exported but unused | Activate, add drag handles |
| `ToolDock.tsx` | Exists, exported but unused | Activate, add tool registry |
| `CornerNavBar.tsx` | **New** | Corner time-loss chips, fetches from API |
| `useFocusModeStore.ts` | **New** | Zustand store: active tools, layout, persistence |

**Tool registry:**

```typescript
interface FocusTool {
  id: string;
  icon: React.ComponentType;
  label: string;
  tabs: string[];  // which session tabs this tool appears in
  render: (props: ToolRenderProps) => React.ReactNode;
}
```

Tools to register:
1. GPS Map (`GpsTrace`)
2. Speed Trace (`SpeedTraceZoom`)
3. GG Explorer (`GGExplorer`)
4. Corner Replay (`CornerReplay`)
5. Sector Times (new small component)
6. Lap Distribution (new small component)

**Keyboard shortcuts:**
- `F` — open Focus Mode from any session detail page
- `Escape` — close Focus Mode
- `R` — reset layout to tab defaults
- `S` — toggle sidebar dock
- `1-9` — toggle tools by position in dock

**Layout persistence:**
- Zustand store with `localStorage` middleware
- Key: `focus-layout-{tab}` (e.g. `focus-layout-overview`, `focus-layout-analytics`)
- Stores: which tools are active, SplitPane sizes

**Per-section expand buttons:**
- Add a small expand icon button to each chart section in session detail
- Click opens Focus Mode with that tool as the primary (pre-selected and largest panel)

## Files Changed

| Area | File | Change Type |
|------|------|-------------|
| **Tests** | `telemetry_tool/tests/test_golden_parity.py` | **New** |
| **Tests** | `telemetry_tool/tests/test_scoring_boundaries.py` | **New** |
| **Tests** | `telemetry_tool/tests/test_sectors_corners.py` | **New** |
| **Tests** | `telemetry_tool/tests/test_api_contracts.py` | **New** |
| **Tests** | `telemetry_tool/tests/fixtures/golden_session.csv` | **New** (checked-in fixture) |
| **Tests** | `telemetry_tool/tests/fixtures/golden_baseline.json` | **New** (checked-in baseline) |
| **E2E** | `lap-website/e2e/critical-path.spec.ts` | **New** |
| **E2E** | `lap-website/e2e/compare-flow.spec.ts` | **New** |
| **E2E** | `lap-website/e2e/bulk-actions.spec.ts` | **New** |
| **CI** | `.github/workflows/ci.yml` | Edit — add 3 new jobs + staging gate |
| **CI** | `docker-compose.ci.yml` | **New** (minimal compose for E2E) |
| **Parity** | `lap-website/src/lib/format-utils.ts` | **New** |
| **Parity** | `lap-website/src/app/app/sessions/page.tsx` | Edit — use shared formatters |
| **Parity** | `lap-website/src/app/app/sessions/[id]/page.tsx` | Edit — use shared formatters, add badges |
| **Parity** | `lap-website/src/app/app/compare/sessions/page.tsx` | Edit — use shared formatters, add badges |
| **Ergonomics** | `lap-website/src/app/app/sessions/page.tsx` | Edit — Select All, re-analyze, one-click compare |
| **Ergonomics** | `lap-website/src/components/app/focus-mode/FocusMode.tsx` | Edit — full rewrite |
| **Ergonomics** | `lap-website/src/components/app/focus-mode/CornerNavBar.tsx` | **New** |
| **Ergonomics** | `lap-website/src/components/app/focus-mode/useFocusModeStore.ts` | **New** |
| **Ergonomics** | `lap-website/src/app/app/sessions/[id]/page.tsx` | Edit — expand buttons, keyboard shortcut |

## Risk Assessment

- **Low risk:** Parity polish (3a-3d) — formatting changes only, no logic changes
- **Low risk:** New test files (1a-1g) — additive, no production code changes
- **Medium risk:** CI pipeline changes (2a-2d) — could break deploys if misconfigured
- **Medium risk:** Bulk ops wiring (4a-4b) — touches session list state management
- **High risk:** Focus Mode rewrite (4c) — significant refactor of existing component, multiple new components, keyboard event handling

## Execution Order

Interleaved across all three workstreams:

1. Shared format-utils (foundation for parity + tests)
2. Backend test files (1a-1d) — parallel with frontend parity
3. Frontend parity polish (3a-3d) — parallel with backend tests
4. Bulk ops (4a-4b) — after parity is stable
5. E2E specs (1e-1g) — after bulk ops are wired
6. CI pipeline (2a-2d) — after E2E specs are written
7. Focus Mode (4c) — largest effort, can run in parallel with CI work
