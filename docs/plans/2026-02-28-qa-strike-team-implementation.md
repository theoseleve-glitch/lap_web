# QA Strike Team Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate 100% of bugs across the Lap Coach ecosystem (500 errors, CORS failures, chart crashes, auth instability, entitlement bypasses) and restore critical missing features, verified with automated tests.

**Architecture:** Fix inside-out: backend infrastructure (CORS, auth, entitlements) first, then backend data endpoints (500 guards, shape fixes), then frontend hardening (chart guards, error boundaries), then missing features, then E2E regression suite.

**Tech Stack:** Python Flask (backend), Next.js 14 + TypeScript (frontend), PostgreSQL 16, Redis 7, Playwright (E2E), pytest (backend), Vitest (frontend unit)

**Source documents:**
- `docs/plans/2026-02-28-qa-failure-matrix.md` (Agent A)
- `docs/plans/2026-02-28-qa-backend-fix-catalog.md` (Agent B)
- `docs/plans/2026-02-28-qa-user-journey-map.md` (Agent C)

---

## Phase 1: Backend Infrastructure (CORS + Auth + Entitlements)

These are system-wide issues that block ALL frontend functionality. Fix first.

### Task 1: Fix CORS Allow-Headers (CORS-FIX-001)

**Files:**
- Modify: `telemetry_tool/web/app.py:150-152`
- Test: `telemetry_tool/tests/test_cors.py`

**Step 1: Write the failing test**

```python
# In test_cors.py
def test_cors_allows_custom_headers(client):
    """CORS preflight must allow X-Workspace-Id, Idempotency-Key, X-CSRF-Token."""
    resp = client.options("/api/v1/sessions", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization,X-Workspace-Id,Idempotency-Key,X-CSRF-Token"
    })
    assert resp.status_code in (200, 204)
    allowed = resp.headers.get("Access-Control-Allow-Headers", "")
    for h in ["X-Workspace-Id", "Idempotency-Key", "X-CSRF-Token"]:
        assert h.lower() in allowed.lower(), f"Missing {h} in CORS Allow-Headers"

def test_cors_exposes_response_headers(client):
    """Frontend JS must be able to read X-Request-Id and Retry-After."""
    resp = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    exposed = resp.headers.get("Access-Control-Expose-Headers", "")
    assert "X-Request-Id" in exposed or "x-request-id" in exposed.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_cors.py -k "test_cors_allows_custom_headers or test_cors_exposes_response_headers" -v`
Expected: FAIL — custom headers not in allow list

**Step 3: Write minimal implementation**

In `telemetry_tool/web/app.py`, change the CORS init from:
```python
CORS(app, origins=origins, supports_credentials=True)
```
to:
```python
CORS(app, origins=origins, supports_credentials=True,
     allow_headers=["Authorization", "Content-Type", "X-Workspace-Id",
                    "Idempotency-Key", "X-CSRF-Token", "X-Request-Id"],
     expose_headers=["X-Request-Id", "Retry-After"])
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_cors.py -k "test_cors_allows_custom_headers or test_cors_exposes_response_headers" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/app.py telemetry_tool/tests/test_cors.py
git commit -m "fix(cors): add custom headers to CORS allow-headers and expose-headers"
```

---

### Task 2: Fix Entitlement Gate Path Mismatches (3 gates bypassed)

**Files:**
- Modify: `telemetry_tool/web/middleware/entitlements.py`
- Test: `telemetry_tool/tests/test_entitlement_middleware.py`

**Step 1: Write the failing tests**

```python
def test_comparison_gate_blocks_demo_on_v1_path(client_demo):
    """Demo user cannot access /api/v1/compare/sessions."""
    resp = client_demo.get("/api/v1/compare/sessions?a=1&b=2")
    assert resp.status_code == 403

def test_visualization_gate_blocks_demo_on_v1_path(client_demo):
    """Demo user cannot access /api/v1/sessions/{id}/visualize."""
    resp = client_demo.get("/api/v1/sessions/test-session/visualize")
    assert resp.status_code == 403

def test_upload_quota_enforced_on_v1_path(client_demo_exhausted_uploads):
    """Demo user with exhausted uploads gets 429 on /api/v1/files/upload."""
    resp = client_demo_exhausted_uploads.post("/api/v1/files/upload")
    assert resp.status_code in (429, 413)  # quota exceeded or size limit
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_entitlement_middleware.py -k "test_comparison_gate_blocks_demo_on_v1 or test_visualization_gate or test_upload_quota_enforced_on_v1" -v`
Expected: FAIL — gates don't match v1 paths

**Step 3: Fix the gate path prefixes**

In `_FEATURE_GATES`, add/fix these entries:
```python
# Comparison — add v1 path
("GET", "/api/v1/compare/"): "comparison",

# Visualization — add session visualize path
("GET", "/api/v1/sessions/", "visualize"): "visualization",  # or use startswith + endswith check

# Upload quota — add v1 file upload path
```

In `_QUOTA_GATES`, add:
```python
("POST", "/api/v1/files/upload"): ("uploads", 1),
```

Note: The middleware matching logic uses `request.path.startswith(prefix)`. For visualization, we need to handle the pattern `/api/v1/sessions/{id}/visualize` — this may require a regex or suffix check. Read the middleware matching code to determine the best approach.

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_entitlement_middleware.py -v`
Expected: All PASS including new tests

**Step 5: Commit**

```bash
git add telemetry_tool/web/middleware/entitlements.py telemetry_tool/tests/test_entitlement_middleware.py
git commit -m "fix(entitlements): fix 3 gate path mismatches allowing demo bypass on v1 routes"
```

---

### Task 3: Add X-Workspace-Id to Frontend API Client (AUTH-FIX-002)

**Files:**
- Modify: `lap-website/src/lib/api-client.ts`
- Modify: `lap-website/src/lib/workspace-store.ts` (create if needed)
- Test: `lap-website/src/__tests__/api-client-workspace.test.ts`

**Step 1: Write the failing test**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('API client workspace header', () => {
  it('includes X-Workspace-Id when workspace is set', async () => {
    // Mock fetch to capture headers
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: () => Promise.resolve({ ok: true, data: {} })
    });
    global.fetch = mockFetch;

    // Set workspace ID in store
    setWorkspaceId('ws-123');

    await api.get('/sessions');

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers['X-Workspace-Id']).toBe('ws-123');
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/api-client-workspace.test.ts`
Expected: FAIL — no X-Workspace-Id header sent

**Step 3: Implement workspace header injection**

Read `api-client.ts` `buildHeaders()` function. Add workspace ID from a Zustand store or module-level variable. The workspace ID should come from the user's default workspace (returned on login) or from workspace selection UI.

**Step 4: Run test to verify it passes**

Run: `cd lap-website && npx vitest run src/__tests__/api-client-workspace.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add lap-website/src/lib/api-client.ts lap-website/src/lib/workspace-store.ts lap-website/src/__tests__/api-client-workspace.test.ts
git commit -m "fix(auth): add X-Workspace-Id header to frontend API client for multi-tenancy"
```

---

### Task 4: Fix Multi-Tab Refresh Token Race (AUTH-FIX-001)

**Files:**
- Modify: `lap-website/src/lib/auth.ts`
- Test: `lap-website/src/__tests__/auth-multi-tab.test.ts`

**Step 1: Write the failing test**

```typescript
describe('Multi-tab token refresh', () => {
  it('broadcasts new access token via BroadcastChannel', async () => {
    const channel = new BroadcastChannel('lap-auth');
    const received: string[] = [];
    channel.onmessage = (e) => received.push(e.data.accessToken);

    await silentRefresh(); // mock backend returns new token

    // Wait for broadcast
    await new Promise(r => setTimeout(r, 50));
    expect(received.length).toBe(1);
    channel.close();
  });
});
```

**Step 2: Implement BroadcastChannel coordination**

In `auth.ts`, after a successful refresh:
1. Broadcast the new access token to other tabs via `BroadcastChannel('lap-auth')`
2. Listen for broadcasts from other tabs and update the in-memory token
3. When receiving a broadcast, skip the next refresh attempt (token already fresh)

**Step 3: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/auth-multi-tab.test.ts`
Expected: PASS

**Step 4: Commit**

```bash
git add lap-website/src/lib/auth.ts lap-website/src/__tests__/auth-multi-tab.test.ts
git commit -m "fix(auth): add BroadcastChannel coordination for multi-tab token refresh"
```

---

## Phase 2: Backend 500 Error Fixes

Fix all 11 genuine crash risks identified in the backend fix catalog. Each fix follows the same pattern: write failing test → fix → verify.

### Task 5: Fix best_lap_number lookup in /energy and /workload (FIX-001, FIX-002)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:1211` and `:3251`
- Test: `telemetry_tool/tests/test_api_v1_data.py`

**Step 1: Write failing tests**

```python
def test_energy_endpoint_finds_best_lap_from_laps_table(seeded_db, client):
    """Energy endpoint should find best lap from laps table, not session dict."""
    resp = client.get(f"/api/v1/sessions/{SESSION_ID}/energy")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "distances" in data

def test_workload_endpoint_finds_best_lap_from_laps_table(seeded_db, client):
    """Workload endpoint should find best lap from laps table, not session dict."""
    resp = client.get(f"/api/v1/sessions/{SESSION_ID}/workload")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "timestamps" in data
```

**Step 2: Fix both endpoints**

Replace `session.get("best_lap_number", 1)` with the laps-table lookup pattern used by `v1_speed_trace` (lines 112-123):
```python
laps = get_laps_for_session(conn, session_id)
best_lap = next((l for l in laps if l.get("is_best")), laps[0] if laps else None)
if not best_lap:
    return jsonify({"ok": True, "data": {"distances": [], ...}})
best_lap_number = best_lap["lap_number"]
```

**Step 3: Run tests and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -k "test_energy_endpoint or test_workload_endpoint" -v
git commit -m "fix(api): use laps-table best-lap lookup in /energy and /workload endpoints"
```

---

### Task 6: Fix division-by-zero in /fatigue (FIX-003)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:417`
- Test: `telemetry_tool/tests/test_api_v1_data.py`

**Step 1: Write failing test**

```python
def test_fatigue_with_zero_lap_times_returns_empty(seeded_db, client):
    """Fatigue endpoint should not crash when all lap times are 0."""
    # Seed a session where all lap_time_s = 0
    resp = client.get(f"/api/v1/sessions/{ZERO_TIMES_SESSION}/fatigue")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["laps"] == [] or all(f == 0 for f in data["fatigue_index"])
```

**Step 2: Fix**

Change line 417 from:
```python
mean_time = sum(times) / len(times) if times else 1
```
to:
```python
mean_time = sum(times) / len(times) if times and sum(times) > 0 else 1
```

**Step 3: Run test and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -k "test_fatigue_with_zero" -v
git commit -m "fix(api): guard division-by-zero in /fatigue when all lap times are 0"
```

---

### Task 7: Fix missing table guards (FIX-005, FIX-006, FIX-010)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:1018`, `:1053`, `:967`
- Test: `telemetry_tool/tests/test_api_v1_data.py`

**Step 1: Write failing tests**

```python
def test_corner_coaching_returns_200_when_best_practices_table_missing(client):
    resp = client.get(f"/api/v1/sessions/{SESSION_ID}/corner-coaching")
    assert resp.status_code == 200

def test_badges_returns_200_when_driver_badges_table_missing(client):
    resp = client.get(f"/api/v1/sessions/{SESSION_ID}/badges")
    assert resp.status_code == 200

def test_corner_metrics_returns_200_when_table_missing(client):
    resp = client.get(f"/api/v1/sessions/{SESSION_ID}/corner-metrics")
    assert resp.status_code == 200
```

**Step 2: Wrap each query in try/except**

```python
# corner_best_practices (line 1018)
try:
    conn.execute("SELECT ... FROM corner_best_practices ...", ...)
    bp_row = conn.fetchone()
except Exception:
    bp_row = None

# driver_badges (line 1053)
try:
    conn.execute("SELECT ... FROM driver_badges ...", ...)
    badge_rows = conn.fetchall()
except Exception:
    badge_rows = []

# corner_metrics (line 967) — same pattern
```

**Step 3: Run tests and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -k "corner_coaching or badges or corner_metrics" -v
git commit -m "fix(api): add try/except guards for optional tables in corner-coaching, badges, corner-metrics"
```

---

### Task 8: Fix KeyError on session["driver_id"] (FIX-007, FIX-008)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:819` and `:1058`

**Step 1: Fix**

Replace `session["driver_id"]` with `session.get("driver_id")` and add guard:
```python
driver_id = session.get("driver_id")
if not driver_id:
    return jsonify({"ok": True, "data": {"comparisons": []}})
```

**Step 2: Run tests and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -v
git commit -m "fix(api): use .get() for driver_id in /cross-session and /badges"
```

---

### Task 9: Fix integer-indexed row access in /weather (FIX-009)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:3231-3234`

**Step 1: Fix**

Replace:
```python
row[0], row[2], row[3]
```
with:
```python
row["air_temp_c"], row["humidity_pct"], row["wind_speed_mps"]
```

Or if column names are uncertain, use the query's column aliases.

**Step 2: Run tests and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -k "weather" -v
git commit -m "fix(api): use column names instead of integer indexes in /weather endpoint"
```

---

### Task 10: Fix ILIKE in /sessions/browse (FIX-011)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:1516-1524`

**Step 1: Fix**

Replace `ILIKE` with `LIKE` (SQLite LIKE is already case-insensitive for ASCII). Or use `sql_compat` to translate:
```python
# Use LOWER() for cross-DB compatibility
"WHERE LOWER(track_name) LIKE LOWER(:q) OR LOWER(driver_name) LIKE LOWER(:q)"
```

**Step 2: Run tests and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -k "browse" -v
git commit -m "fix(api): replace PG-only ILIKE with cross-DB LOWER()+LIKE in /sessions/browse"
```

---

### Task 11: Fix raw %s params in weekends POST (FIX-015)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:3007-3009`

**Step 1: Fix**

Replace positional `%s` with named params:
```python
conn.execute(
    "INSERT INTO race_weekends (name, track_id, start_date, end_date, ...) "
    "VALUES (%(name)s, %(track_id)s, %(start_date)s, %(end_date)s, ...)",
    {"name": name, "track_id": track_id, ...}
)
```

**Step 2: Run tests and commit**

```bash
pytest telemetry_tool/tests/ -k "weekend" -v
git commit -m "fix(api): use named params in weekends POST for PG compatibility"
```

---

### Task 12: Fix division-by-zero in /tyre-data (found by Agent A)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:3180`

**Step 1: Fix**

Guard the division:
```python
best = min(times) if times else 1
degradation = [((t - best) / best * 100) if best > 0 else 0 for t in times]
```

**Step 2: Run tests and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -k "tyre" -v
git commit -m "fix(api): guard division-by-zero in /tyre-data when best lap time is 0"
```

---

### Task 13: Fix energy endpoint speed unit mismatch (Agent A finding)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:1198-1234`

**Step 1: Investigate**

The endpoint divides GPS speeds by 3.6 (assuming km/h→m/s), but RaceChrono exports speeds in m/s already. This produces energies that are wrong by a factor of ~13.

**Step 2: Fix**

Remove the `/ 3.6` conversion — speeds from `get_gps_trace()` are already in m/s.

**Step 3: Run tests and commit**

```bash
pytest telemetry_tool/tests/test_api_v1_data.py -k "energy" -v
git commit -m "fix(api): remove incorrect km/h-to-m/s conversion in /energy (GPS speeds already m/s)"
```

---

### Task 14: Fix consistency endpoint synthetic data (Agent A finding)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:1242-1277`

**Step 1: Investigate**

The endpoint generates fake heatmap data from a hash formula instead of real sector times. If real sector timing data exists in the DB (from `session_sectors` or `sector_times`), use it. If not, return empty data rather than fake data.

**Step 2: Fix**

Replace the synthetic generation with real sector delta query, or return empty:
```python
# If no real sector timing data exists
return jsonify({"ok": True, "data": {"laps": [], "sectors": [], "deltas": []}})
```

**Step 3: Run tests and commit**

```bash
git commit -m "fix(api): replace synthetic consistency heatmap with real sector data or empty response"
```

---

## Phase 3: Response Shape Fixes + Missing Endpoints

### Task 15: Fix corner mastery score scale (SHAPE-008)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:1350-1363`

**Step 1: Fix**

Normalize score to 0-1 range:
```python
"score": round(mastery_score / 100, 3),  # Frontend expects 0-1
```

**Step 2: Run tests and commit**

---

### Task 16: Fix session details missing fields (SHAPE-010)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:1412-1438`

**Step 1: Fix**

Add missing fields to the response dict:
```python
"condition": session.get("track_state"),
"kart_name": session.get("kart_name"),
```

**Step 2: Run tests and commit**

---

### Task 17: Create 6 missing endpoints (MISSING-001 through MISSING-006)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py`
- Test: `telemetry_tool/tests/test_api_v1_data.py`

For each missing endpoint, create a minimal handler that returns the expected shape with data from existing DB tables. If no data exists, return empty arrays:

1. `GET /api/v1/sessions/<id>/pit-window` → `{current_lap, window_open, window_close, optimal_lap, time_loss_per_lap}` or empty
2. `GET /api/v1/sessions/<id>/rival-gap` → `{lap_numbers: [], gap_seconds: []}` or empty
3. `GET /api/v1/sessions/<id>/corners` → `{corners: [{corner_id, name, entry_speed, apex_speed, exit_speed}]}` from `corner_metrics`
4. `GET /api/v1/sessions/<id>/corner-replay` → frame data from GPS traces filtered by corner boundaries
5. `GET /api/v1/setup/status` → `{steps: [{id, status}]}` computed from session/track/driver counts
6. `GET /api/v1/data-health/jobs/<job_id>` → single job detail from `ingestion_jobs`

Each endpoint: write test first, implement minimal handler, verify, commit.

---

## Phase 4: Frontend Chart Hardening

### Task 18: Add defensive guards to 10 medium-risk charts

**Files:**
- Modify: 10 chart components in `lap-website/src/components/app/charts/`

For each chart (DrivingStyle, EnergyBalance, FatigueChart, WorkloadChart, WeatherChart, TyreChart, ComparisonMatrix, TrendChart, PitWindowChart, RivalChart):

1. Add `Math.max(denominator, 0.001)` guards before any division
2. Add `isFinite(value) ? value : 0` guards on computed values
3. Add `Math.max(0, radius)` guards on any arc/circle drawing
4. Clamp extreme values to reasonable plot ranges

Pattern for each chart:
```typescript
// Before any division
const maxVal = Math.max(...values, 0.001); // never zero
const normalized = value / maxVal;

// Before any canvas arc
const safeRadius = Math.max(0.5, radius);
ctx.arc(x, y, safeRadius, 0, Math.PI * 2);

// Filter NaN/Infinity
const clean = values.map(v => isFinite(v) ? v : 0);
```

**Step 1: Write tests**

```typescript
// For each chart:
it('renders without crash when data contains extreme values', () => {
  render(<FatigueChart data={{ laps: [1,2], fatigue_index: [Infinity, -1e20], reaction_time: [NaN, 0] }} />);
  // Should not throw
});

it('renders without crash when data arrays are empty', () => {
  render(<FatigueChart data={{ laps: [], fatigue_index: [], reaction_time: [] }} />);
  // Should render empty state
});
```

**Step 2: Implement guards in each chart**

**Step 3: Run all chart tests and commit**

```bash
cd lap-website && npx vitest run src/__tests__/charts/
git commit -m "fix(charts): add defensive guards for division-by-zero, NaN, and extreme values in 10 charts"
```

---

### Task 19: Fix CornerReplayCockpit negative radius (from exploration)

**Files:**
- Modify: `lap-website/src/components/app/corner-replay/CornerReplayCockpit.tsx:56,71,82`

**Step 1: Fix**

```typescript
const speedR = Math.max(20, Math.min(w * 0.22, h * 0.32)); // min 20px
const tickR = Math.max(0, speedR - 4);
const innerR = Math.max(0, isMajor ? tickR - 8 : tickR - 4);
```

**Step 2: Run tests and commit**

---

## Phase 5: Auth Stability & Rate Limiting

### Task 20: Add rate limiting to /auth/refresh (AUTH-FIX-003)

**Files:**
- Modify: `telemetry_tool/web/routes/auth.py:297`

**Step 1: Add `@rate_limit(tier="auth")` decorator**

**Step 2: Run tests and commit**

---

## Phase 6: Missing Feature Stubs (Critical CRUD)

### Task 21: Add session delete to frontend

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`
- Backend: `DELETE /api/v1/sessions/{id}` already exists (api_v1_data.py:744)

Add a delete button with confirmation dialog. The backend endpoint already exists and is working.

### Task 22: Add session inline editing to frontend

**Files:**
- Create: `lap-website/src/components/app/InlineEdit.tsx`
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`
- Backend: Need `PATCH /api/v1/sessions/{id}` endpoint (create if missing)

Add inline-editable fields for: driver, track, session type, condition, notes. With debounced auto-save pattern matching old tool.

### Task 23: Verify chart-map hover sync

**Files:**
- Read: `lap-website/src/components/app/charts/SpeedTrace.tsx`
- Read: `lap-website/src/components/app/charts/TrackMap.tsx`
- Read: `lap-website/src/app/app/sessions/[id]/page.tsx`

Check if the session detail page passes shared hover state between SpeedTrace and TrackMap. If not, implement shared hover context:
```typescript
// Shared hover state via Zustand or React context
const useChartSync = create<{ hoverIndex: number | null }>(...);
```

---

## Phase 7: E2E Regression Suite

### Task 24: Backend API contract tests

**Files:**
- Create: `telemetry_tool/tests/test_api_contracts.py`

Write tests that verify every data endpoint returns the correct shape:
```python
@pytest.mark.parametrize("endpoint,expected_keys", [
    ("/api/v1/sessions/{id}/gg-data", ["lat_g", "lon_g"]),
    ("/api/v1/sessions/{id}/speed-trace", ["distances", "speeds"]),
    ("/api/v1/sessions/{id}/fingerprint", ["metrics"]),
    # ... all 76 data endpoints
])
def test_endpoint_returns_correct_shape(seeded_db, client, endpoint, expected_keys):
    resp = client.get(endpoint.format(id=SESSION_ID))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    for key in expected_keys:
        assert key in data["data"], f"Missing key {key} in {endpoint}"
```

### Task 25: Playwright E2E for critical journeys

**Files:**
- Modify: `lap-website/e2e/certification-live.spec.ts` (or create new spec)

Test the 6 critical user journeys with real API calls against the test accounts:
1. Login → Dashboard → Verify stat cards render
2. Navigate to sessions → Click first session → Verify all 5 tabs render
3. Upload a test file → Wait for processing → Verify session created
4. Compare two sessions → Verify comparison renders
5. Account → Profile → Verify profile loads
6. Account → Billing → Verify subscription info

---

## Phase 8: Production Deployment & Smoke Test

### Task 26: Deploy backend fixes

```bash
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose build api && docker compose up -d api"
```

### Task 27: Deploy frontend fixes

```bash
cd lap-website && npm run cf:deploy
```

### Task 28: Run production smoke tests

```bash
./scripts/verify_production.sh
```

Verify:
- [ ] /healthz returns 200
- [ ] CORS preflight includes custom headers
- [ ] Login with each test account works
- [ ] Session list loads
- [ ] Session detail renders all tabs
- [ ] No 500 errors in API logs
- [ ] No CORS errors in browser console

---

## Summary

| Phase | Tasks | Priority | Estimated Effort |
|-------|-------|----------|-----------------|
| 1: Infrastructure | 4 tasks (CORS, entitlements, workspace header, multi-tab auth) | P0 | 1 session |
| 2: 500 Fixes | 10 tasks (all crash risks in api_v1_data.py) | P0 | 1 session |
| 3: Shape + Missing | 3 tasks (scale fix, missing fields, 6 new endpoints) | P1 | 1 session |
| 4: Chart Hardening | 2 tasks (10 charts + cockpit) | P1 | 1 session |
| 5: Auth Stability | 1 task (rate limiting) | P1 | 0.5 session |
| 6: Missing Features | 3 tasks (delete, inline edit, hover sync) | P0 | 1-2 sessions |
| 7: E2E Suite | 2 tasks (contract tests + Playwright) | P1 | 1 session |
| 8: Deployment | 3 tasks (deploy + smoke) | P0 | 0.5 session |

**Total: 28 tasks across 8 phases, ~6-8 sessions**

Critical path: Phase 1 → Phase 2 → Phase 8 (deploy) → Phase 3-7 (can parallelize)
