# Full Parity Restoration & Hardening Design

**Source of Truth:** `docs/report 1_2.pdf` (23-page audit comparing local tool vs SaaS)

**Goal:** Achieve measurable parity between the local desktop telemetry tool and the SaaS platform, closing all conflict points identified in the audit report, and hardening the system for production.

**Approach:** 7 sequential checkpoints, each verified by truth dashboard probes before proceeding. Checkpoint #7 (parity harness) runs first to establish the measurement baseline.

---

## What's Already Shipped

These items from the checklist are complete and deployed:

| Item | Commit | Evidence |
|------|--------|----------|
| Bulk ops (Select All, re-analyze, one-click compare) | `a762d1b` | Sessions list page |
| Focus Mode full desktop parity | `b0678ce` | ToolDock, SplitPane, F-key, corner nav |
| 5-tab session detail | tab-parity series | Overview, Corners, Timeline, Analytics, Laps |
| Driving Style radar + Session Debrief + Badges | tab-parity series | Overview tab sections |
| 37 data endpoints + 23 entity endpoints | `api_v1_entities.py`, `data_v2.py` | Full API surface |
| Session metadata PATCH | `data_v2.py` | display_name, driver_id, track_id, etc. |
| Shared format-utils + unified formatters | `77d34d2`, `b8ce896`, `1a4d9f9` | Sub-60s lap times, distances |
| Error boundaries + global error page | `c554424` | React ErrorBoundary |
| JSON structured logging | `02e7eec` | Production JSON logs |
| Sentry backend integration | `187d77d` | Error tracking |
| Tiered retention policy | `0cbb119` | Celery Beat daily 03:00 UTC |
| Audit logging | `715a351` | Session delete audit trail |
| Composite indexes + rollup tables | `72c213e` | Migrations 027-028 |
| Golden fixture parity tests | testing-ci series | CSV fixture + baseline comparison |
| Scoring boundary tests (45) | `e3b1227` | Grade thresholds, edge cases |
| API contract tests (94) | `8bb528d` | Response shape assertions |
| E2E specs (critical path, compare, bulk) | `3debdcd` | Playwright |
| CI pipeline (4 new jobs) | `ee805f1` | contract-tests, typecheck, e2e-smoke, parity |
| Joker/Pit badge types | `1305aee` | Full desktop badge parity |

---

## Checkpoint #7 — Parity Harness (Run First)

**Purpose:** Lock the baseline and make parity measurable.

### 7.1 Golden Fixture Storage
- Copy the exact CSV used for report screenshots to `fixtures/golden/OK_R3.csv`
- Mark as read-only, committed to repo
- Create `fixtures/golden/manifest.json`:
  ```json
  {
    "local_tool_commit": "<hash>",
    "saas_commit": "<hash>",
    "deployed_build_id": "<cloudflare-version>",
    "environment": "production",
    "fixture_file": "OK_R3.csv",
    "fixture_sha256": "<hash>",
    "created_at": "2026-03-02"
  }
  ```

### 7.2 Parity Harness Script
- `scripts/parity_harness.py --session-id <ID> --api-url <URL>`
- Runs analysis on the fixture (local pipeline)
- Calls SaaS endpoints for the produced session
- Dumps JSON responses to `fixtures/golden/baseline/`:
  - `scores.json`, `laps.json`, `speed_trace.json`, `gps_trace.json`
  - `corners.json`, `sectors.json`, `gg_data.json`, `driving_style.json`
- Compares with tolerance rules

### 7.3 Tolerance Rules (agreed, never handwaved)
| Metric | Tolerance | Comparison Method |
|--------|-----------|-------------------|
| Lap times | ±5ms numeric | `abs(local - saas) <= 0.005` |
| Best lap selection | Exact same index | `local_best_idx == saas_best_idx` |
| Score + pillar scores | ±0.1 | `abs(local - saas) <= 0.1` |
| Sector times | ±0.001s | `abs(local - saas) <= 0.001` |
| Corner boundaries (s_start/s_end/s_apex) | ±1m | `abs(local - saas) <= 1.0` |
| Missing data online | Structured response | `available == false` + `reason_code` present |

### 7.4 Enhanced Truth Dashboard Probes

**Existing 6 conflict probes** (from `docs/audit-truth-dashboard.html`):
1. Session identity (title/driver/track/date)
2. Visualize renders (speed trace + GPS trace)
3. Timeline tab (lap progress + stint analysis)
4. Analytics tab (sectors + GG + scores)
5. Corners/coaching (coaching text present)
6. CSP violations

**New probes — Entity Population:**
7. Drivers count > 0 after golden fixture upload
8. Tracks count > 0 with resolved track name
9. Karts list endpoint returns 200
10. Weekends endpoint returns 200 (no error state)

**New probes — Chart Data Completeness:**
11. Speed trace: non-empty `speeds[]` and `distances[]`
12. GPS trace: non-empty `latitudes[]` and `longitudes[]`
13. GG data: non-empty `accel_lat[]` and `accel_long[]`
14. Sectors: sector times present with numeric values
15. Corners: coaching text on each corner

**New probes — UI Rendering (Playwright):**
16. Each of 5 tabs renders without console errors
17. No blank canvases (canvas elements have pixel content)
18. No stuck "Loading..." states after 5 seconds

---

## Checkpoint #1 — API Hardening + Session Identity (Bullets 1-5)

### 1.1 JSON Guard Middleware
- Flask `after_request` hook on all `/api/*` routes
- If Content-Type is `text/html` or body starts with `<!DOCTYPE`/`<html`:
  - Return `{ok: false, error: {code: "API_HTML_RESPONSE", message: "Endpoint returned HTML"}, meta: {request_id}}`
- Acceptance: frontend never fails due to "Unexpected token <"

### 1.2 Graceful Degradation for Optional Data
- All data endpoints that can return empty results:
  - Return `200 + {available: false, reason_code: "..."}` instead of 500
  - Reason codes: `no_corners`, `no_theoretical`, `no_sectors`, `no_gg_data`, `no_driving_style`, `pipeline_step_failed`
- Include `request_id` on every response (already in `api_utils.py` envelope)
- Frontend: surface `request_id` in error boundaries

### 1.3 Session Identity Fix
- `session.display_name` defaults to filename stem (strip path, strip extension)
- API returns `display_name`, `source_filename` (traceability), never `source_path`
- Session header: title uses `display_name`, subtitle shows driver/track/date only if resolved

### 1.4 Session Date from Telemetry
- During pipeline ingestion: derive `session_date` from first telemetry timestamp
- Store upload timestamp as `created_at` (separate field)
- All UI uses `session_date` for display and sorting

### 1.5 Driver/Track Resolution
- Driver precedence: upload selection > file metadata > "Unknown"
- Ensure workspace-scoped (no cross-workspace fallback)
- Track: GPS fingerprint detection → `track_id` → resolve `track_name`
- Manual override via session edit UI for detection failures

### Checkpoint #1 Pass Conditions
- No HTML responses to `/api/*`
- No 500s for optional data endpoints
- Session header identity probes PASS (title/driver/track/date match local)

---

## Checkpoint #2 — Editable Session Info + Entity Verification (Bullets 6-10)

### 2.1 Editable Session Info Block
- Inline edit UI with save/cancel for: Date, Driver, Track, Type, Condition, Kart
- Single "Edit session info" entry point
- Uses existing PATCH endpoint

### 2.2 PATCH Endpoint Hardening
- Validate: workspace ownership, enum correctness, kart belongs to workspace
- Response returns resolved names (driver_name, track_name, kart_name)

### 2.3 Kart Field
- Upload flow: optional kart dropdown from existing karts
- Session header: display kart, allow editing
- Persist `session.kart_id`, affect kart rollups

### 2.4 Entity Page Verification
- Drivers/Tracks/Karts: show real counts after golden fixture upload
- Weekends: clean empty-state (no error)
- Leaderboard: real table with data
- Dev Plans: templates visible, plan creation works

### Checkpoint #2 Pass Conditions
- Session metadata edits persist and reflect everywhere
- Drivers/Tracks/Karts/Weekends probes PASS (non-empty where expected)
- No 404s for entity endpoints

---

## Checkpoint #3 — Sessions List + Dashboard + Visualize (Bullets 11-15)

### 3.1 Sessions List Parity
- Restore columns: Type, Condition, Mean Lap
- Multi-select checkboxes (already shipped)
- Bulk actions (already shipped)
- Context menu: Open Session, Open in Visualize, Copy Session ID, Delete

### 3.2 Filters + Time Formatting
- Filters: driver, track, date range, min score, type, condition
- Backend already supports query params
- Canonical time format using shared `formatLapTime()`
- Stable sorting

### 3.3 Dashboard Fixes
- Click-through to correct session
- Reconcile columns (Type)
- "Personal Best" card correctness
- Optional: scroll-to-top, footer

### 3.4 Visualize Rendering
- Verify non-empty arrays for track polyline, speed trace, lap selection
- If resampling fails: `available=false + reason_code`
- GG: explain missing accel, render derived channels properly

### 3.5 Distance-Based Chart Sync
- Verify Zustand hover-sync works across:
  - Session Visualize tab
  - Compare charts
  - Focus Mode
  - Corner replay
- Speed trace hover → map marker by distance
- Map hover → chart crosshair by nearest distance

### Checkpoint #3 Pass Conditions
- Visualize probes PASS (map + trace not empty)
- Hover sync probes PASS (marker/crosshair sync)
- Sessions list probes PASS (columns, bulk actions reachable)

---

## Checkpoint #4 — Tab Depth (Bullets 16-20)

### 4.1 Overview Depth
- Score Breakdown subtitle text per pillar
- Score denominator formatting (clean integers)
- Adaptation score rounding alignment with local
- Strengths section (rule-based from best pillar)
- Areas to Improve section (weakest pillar + coaching)

### 4.2 Corners & Coaching Modules
- Data contract: corner segmentation C1-C5, per-corner metrics
- If theoretical fails: return corners list + per-corner `available=false`
- Port corner_replay.js + supporting modules → React wrapper
- Corner selection checkboxes + save
- Placeholder skeletons for: brake precision, throttle onset, consistency heatmap, corner mastery

### 4.3 Analytics Phase 1 Modules
- Track Map advanced (lap selector, all-laps toggle, corner markers, zoom)
- Sector Performance (ideal lap, potential gain)
- Lap Speed Comparison (multi-lap overlay + checkboxes)
- G-G Explorer (All/Single/Compare) — already shipped

### 4.4 Analytics Phase 2 Modules (feature-flagged)
- Lap Time Distribution
- Lap Progress Tracker (already in Timeline)
- Session Comparison Matrix
- Cross-session summary + speed overlay
- Suggested development drills

### 4.5 Lap Data Parity
- Performance Summary: 8 stat cards (Best, Mean, StdDev, Consistency%, BestVsMean, Top25%, Improvement, ValidLaps)
- Lap Times chart (bars + mean line + best highlight)
- Missing columns: Max braking (G), Max accel (G), Line (m), Phase
- Lap status: Best badge, Incomplete, Invalid with reason
- Track Condition Phases section

### Checkpoint #4 Pass Conditions
- Overview probes PASS (style/debrief/badges present)
- Corners probes PASS (not empty, replay loads)
- Analytics probes PASS (Phase 1 modules show real data)
- Lap Data probes PASS (summary + chart + correct badges)

---

## Checkpoint #5 — Compare + Secondary Pages + Exports (Bullets 21-25)

### 5.1 Compare Flows
- Restore immediate usability (dropdowns on landing page OR one-click to form)
- Session compare outputs:
  - Speed overlay (distance-based)
  - Delta trace (distance-based)
  - GPS overlay comparison
  - Sector delta
  - Corner-by-corner time loss
- Driver compare: trends, style, consistency
- Chart sync across compare views

### 5.2 Secondary Pages
- Weekends: full CRUD + session attachment + weekend summaries
- Leaderboard: full table with filters/sorting, style/trend indicators
- Development Plans: driver selector + template grid + plan CRUD + progress
- Analytics sub-pages: "Coming soon" feature-flag (no failing API calls)

### 5.3 Exports
- Backend export job runner (Celery task) + job history + signed download links
- Formats: CSV, JSON, PDF, PARQUET
- Entitlement gating

### 5.4 Race Strategy
- Restore import if supported
- Port race_strategy.js + race_strategy_live.js
- Verify entitlements show locked (not broken)

### 5.5 Remove Placeholders
- Replace all "re-port in progress" with working pages or "Coming soon" feature flags

### Checkpoint #5 Pass Conditions
- Compare probes PASS (speed + delta overlay exist)
- Weekends/Leaderboard/DevPlans probes PASS (no placeholders, no errors)
- Exports probes PASS (job created + appears in history)

---

## Checkpoint #6 — Hardening (Bullets 26-30)

### 6.1 Async Processing
- Move large-file analysis to Celery workers
- Job status endpoint + progress per pipeline stage (1-14)
- Timeouts and file size enforcement by tier

### 6.2 Database Performance
- Verify indexes for workspace-scoped lists (already have migrations 027-028)
- Materialized rollups (already have driver_stats_rollup, track_stats_rollup)
- RLS context preserved across all CRUD operations

### 6.3 Observability
- Request timing middleware (response time logging)
- Frontend Sentry JS SDK
- Frontend diagnostics mode (dev-only) logging status + content-type + request_id

### 6.4 Security & UX Hardening
- RLS coverage on new tables (exports, rollups)
- IDOR protections on entity details
- Entitlements return 403 + UI shows LockedSection
- Global "data unavailable" component: reason_code + actionable steps
- No chart silently renders blank

### Checkpoint #6 Pass Conditions
- No long-running uploads block request threads
- Retention probes show scheduled cleanup
- Observability probes PASS (request_id traceable end-to-end)

---

## Final Parity Verification (Checkpoint #7 redux)

After all checkpoints:
- Run full parity harness on golden fixture
- All truth dashboard probes PASS
- No console errors on critical flows
- Parity thresholds met within defined tolerances
- Normalize formatting differences (time display, unit display, badge semantics)

---

## Task Estimate

| Checkpoint | Tasks | Est. Effort |
|-----------|-------|-------------|
| #7 Parity Harness | 5 | Foundation |
| #1 API Hardening + Identity | 6 | Session 1 |
| #2 Editable Info + Entities | 5 | Session 1 |
| #3 Sessions List + Dashboard + Viz | 6 | Session 2 |
| #4 Tab Depth | 8 | Session 2-3 |
| #5 Compare + Secondary | 7 | Session 3 |
| #6 Hardening | 5 | Session 3 |
| **Total** | **42** | **3-4 sessions** |
