# Audit & Parity Plan: Lap Coach SaaS vs Local Telemetry Tool

**Date**: 2026-03-01
**Scope**: Full codebase audit — frontend + backend + data pipeline + infra
**Objective**: Restore feature parity with the LOCAL reference tool while keeping SaaS architecture

---

## Table of Contents

- [Section 0: Executive Summary](#section-0--executive-summary)
- [Section 1: Inventory & Architecture Map](#section-1--inventory--architecture-map)
- [Section 2: Golden Reference — Local Tool Feature Contract](#section-2--golden-reference--local-tool-feature-contract)
- [Section 3: Online SaaS Gap Audit (Parity Matrix)](#section-3--online-saas-gap-audit-parity-matrix)
- [Section 4: Error & Reliability Audit](#section-4--error--reliability-audit)
- [Section 5: Data Model & Entity Population Audit](#section-5--data-model--entity-population-audit)
- [Section 6: Frontend UX/IA Audit](#section-6--frontend-uxia-audit)
- [Section 7: Security/Compliance & SaaS Constraints](#section-7--securitycompliance--saas-constraints)
- [Section 8: Recommended Implementation Plan](#section-8--recommended-implementation-plan)
- [Section 9: Testing Strategy](#section-9--testing-strategy)
- [Decision Log](#decision-log)
- [Evidence Index](#evidence-index)

---

## Section 0 — Executive Summary

### Current System Health

The SaaS ("Lap Coach") is **partially functional but significantly degraded** compared to the LOCAL reference tool ("Telemetry"). Core upload-and-analyze flow works end-to-end: CSV upload triggers the 14-stage pipeline synchronously, persists results to SQLite/PostgreSQL, and the frontend can display session detail with 6 tabs. However, multiple critical gaps prevent production-grade usage:

**Critical Issues:**
- Entity pages show "0 drivers / 0 tracks / 0 karts" because local-tool routes (`/drivers/`, `/tracks/`, `/karts/`) serve HTML templates instead of JSON API responses for the SaaS frontend
- 44 of 63 vanilla JS chart modules are not ported to SaaS (corner replay, consistency heatmap, race strategy, etc.)
- Dev Plans endpoint (`/dev-plans/`) returns HTML, not JSON — frontend gets 404/content-type errors
- Several analytics sub-pages are placeholder scaffolds with no backend API
- No SaaS-specific API endpoints for drivers, tracks, karts, weekends CRUD — only template-rendering routes exist

**Working Flows:**
- Upload CSV → pipeline runs → session stored with laps, GPS traces, scores, corners, theoretical data
- Session list, detail (6 tabs: Overview, Visualize, Corners, Performance, Timeline, Lap Data)
- Speed trace, GPS map, GG explorer charts render correctly via vanilla JS wrappers
- Authentication (register, login, OAuth, 2FA, silent refresh) fully functional
- Multi-tenant workspace isolation with RLS
- Billing/entitlement gating framework in place

### Top 10 Critical Blockers

| # | Blocker | Root Cause | Effort |
|---|---------|-----------|--------|
| 1 | Drivers page shows 0 results | No JSON API endpoint — only HTML template route at `/drivers/` | S |
| 2 | Tracks page shows 0 results | Same — `/tracks/` serves HTML, not JSON | S |
| 3 | Karts page shows 0 results | Same — `/karts/` serves HTML, not JSON | S |
| 4 | Corner replay not functional in SaaS | 4 corner_replay JS modules not ported to `public/js/` | M |
| 5 | Analytics sub-pages all placeholder | No API endpoints for weather, trends, pace predictor, weight sim | L |
| 6 | Weekends page non-functional | `/weekends/` serves HTML; no JSON API for CRUD | M |
| 7 | Dev Plans 404/content error | `/dev-plans/` returns HTML; needs JSON API wrapper | S |
| 8 | Leaderboard non-functional | `/leaderboard/` serves HTML; needs JSON API wrapper | S |
| 9 | 44 chart modules missing in SaaS | Only 19 of 63 local JS modules ported | L |
| 10 | Session metadata editing incomplete | PATCH endpoint exists but frontend edit UI is minimal | S |

### Recommended Phased Plan

| Phase | Scope | Effort | Timeline |
|-------|-------|--------|----------|
| **P0** | Fix 500/404 errors, add JSON API wrappers for entity pages, restore data rendering | S-M | 1-2 weeks |
| **P1** | Entity CRUD (drivers/tracks/karts/weekends), metadata editing, session filtering | M | 2-3 weeks |
| **P2** | Port remaining chart modules, restore full session analysis depth (corner replay, consistency heatmap, sector chart, stint chart) | L | 3-4 weeks |
| **P3** | Analytics sub-pages, leaderboard, dev plans, exports, race strategy integration | L | 4-6 weeks |

### What to Do First (Stop 500s/404s, Restore Data Rendering)

1. Add JSON API endpoints wrapping existing model functions for drivers, tracks, karts, weekends, leaderboard, dev-plans under `/api/v1/` prefix
2. Verify all existing `data_v2.py` endpoints handle edge cases (NULL JSON columns, missing theoretical data) without 500
3. Port `corner_replay.js` + 3 supporting modules to `lap-website/public/js/`
4. Wire frontend entity pages to new API endpoints

---

## Section 1 — Inventory & Architecture Map

### Repository Map

```
V2_claude_ai/
├── telemetry_tool/                    # Backend: Python, Flask, SQLite/PostgreSQL
│   ├── main.py                        # Entry point: Tkinter/CLI/Flask serve
│   ├── pipeline.py                    # 14-stage analysis orchestrator (2,400+ lines)
│   ├── scoring.py                     # 5-pillar scoring engine (2,700 lines)
│   ├── io_racechrono.py              # CSV reader with INGEST_V2 routing
│   ├── track_detection.py            # GPS fingerprint matching (IoU + lap length)
│   ├── corner_detection.py           # Curvature-based corner segmentation
│   ├── resampling.py                 # Distance-uniform interpolation
│   ├── sector_analysis.py            # N-sector split + ideal lap
│   ├── reference_line.py             # Median reference line + curvature profile
│   ├── features.py                   # Lap-level feature extraction
│   ├── derived_channels.py           # Compute accel, yaw rate, etc.
│   ├── development_plan.py           # Dev plan templates + tracking
│   ├── ingest/                        # INGEST_V2 streaming pipeline
│   ├── db/
│   │   ├── schema.py                  # SQLite v27 schema (44 tables, 13 phases)
│   │   ├── sql_compat.py             # SQLite ↔ PostgreSQL auto-translation
│   │   └── migrate.py                # Idempotent schema migration
│   ├── auth/                          # SaaS auth: argon2id, JWT, OAuth, RBAC
│   ├── web/
│   │   ├── app.py                     # Flask factory + blueprint registration
│   │   ├── routes/                    # 28 blueprint files
│   │   │   ├── data_v2.py            # 22+ JSON API endpoints (SaaS)
│   │   │   ├── sessions_v2.py        # POST upload (synchronous pipeline)
│   │   │   ├── auth.py               # Auth routes (register, login, OAuth, 2FA)
│   │   │   ├── drivers.py            # HTML template routes (LOCAL only)
│   │   │   ├── tracks.py             # HTML template routes (LOCAL only)
│   │   │   ├── karts.py              # HTML template routes (LOCAL only)
│   │   │   ├── weekends.py           # HTML template routes (LOCAL only)
│   │   │   ├── leaderboard.py        # HTML template routes (LOCAL only)
│   │   │   ├── dev_plans.py          # HTML template routes (LOCAL only)
│   │   │   └── ... (20+ more)
│   │   ├── middleware/               # auth.py + tenant.py (RLS)
│   │   ├── templates/                # 41 Jinja2 templates (LOCAL UI)
│   │   ├── static/js/               # 63 vanilla JS chart modules (LOCAL)
│   │   └── static/css/              # 10 CSS files (LOCAL)
│   ├── models/tracks.json            # Track fingerprint database
│   ├── alembic/                       # 16+ PostgreSQL migrations
│   └── tests/                         # Backend test suite
├── lap-website/                       # Frontend: Next.js 14, TypeScript, Tailwind
│   ├── src/
│   │   ├── app/                       # App Router (96 pages)
│   │   │   ├── (auth)/               # Login, register, verify-email
│   │   │   ├── (free-report)/        # Free analysis tool
│   │   │   ├── (marketing)/          # 20+ marketing pages
│   │   │   └── app/                   # Authenticated dashboard (60+ pages)
│   │   ├── components/               # 100+ React components
│   │   │   ├── app/charts/           # Chart wrappers (SpeedTraceZoom, GpsTrace, GGExplorer)
│   │   │   ├── shared/charts/        # Shared chart components (CornerReplay, SectorPanel)
│   │   │   ├── auth/                 # AuthGuard, OAuthButtons
│   │   │   ├── billing/             # QuotaCounter, UpgradeBanner
│   │   │   └── rooms/               # Marketing section components
│   │   ├── lib/
│   │   │   ├── api-client.ts         # apiFetch() with auto-refresh + CORS
│   │   │   ├── auth.ts              # Auth functions + token management
│   │   │   ├── auth-store.ts        # In-memory token store + cross-tab sync
│   │   │   ├── chart-hover-store.ts  # Zustand distance-based hover sync
│   │   │   └── entitlements-store.ts # Feature gating + quotas
│   │   ├── stores/                    # Zustand stores
│   │   └── hooks/                     # useAuth, useEntitlements
│   ├── public/js/                     # 19 vanilla JS chart modules (SaaS subset)
│   └── e2e/                           # Playwright E2E tests
├── kart_envelope/                     # Kart-specific 18-step pipeline
└── docs/plans/                        # Design & implementation docs
```

### Data Flow Diagram

```
                              ┌─────────────────────────────┐
                              │  User uploads CSV via SaaS   │
                              │  POST /api/v1/sessions/upload│
                              └──────────────┬──────────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │   pipeline.run_full_analysis()│
                              │   14 stages (synchronous)    │
                              │                              │
                              │ 1. CSV Ingest                │
                              │ 2. GPS Filter                │
                              │ 3. Derived Channels          │
                              │ 4. Session Trim              │
                              │ 5. Track Detection           │
                              │ 6. Corner Detection          │
                              │ 7. Resampling (distance-axis)│
                              │ 8. Features                  │
                              │ 9. Reference Line + Physics  │
                              │ 10. Theoretical Lap          │
                              │ 11. Feature Dataset          │
                              │ 12. ML/Anomaly               │
                              │ 13. Scoring (5 pillars)      │
                              │ 14. Reports (disabled in API)│
                              └──────────────┬──────────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │   Persist to Database        │
                              │                              │
                              │ upsert_driver()              │
                              │ upsert_track()               │
                              │ upsert_session()             │
                              │ insert_laps()                │
                              │ insert_gps_traces()          │
                              │ insert_score_details()       │
                              │ insert_theoretical_data()    │
                              │ insert_corner_metrics()      │
                              │ insert_reference_line()      │
                              │ insert_driving_style()       │
                              │ insert_stint_analysis()      │
                              │ insert_analysis_json()       │
                              └──────────────┬──────────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │   data_v2.py serves data     │
                              │   22+ GET endpoints          │
                              │                              │
                              │ /sessions, /sessions/<id>    │
                              │ /speed-trace, /gps-trace     │
                              │ /gg-data, /scores, /corners  │
                              │ /theoretical, /reference_line│
                              │ /corner-positions, /delta    │
                              │ /fingerprint, /driving-style │
                              │ /lap-distribution, /stints   │
                              └──────────────┬──────────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │  Next.js SaaS Frontend       │
                              │                              │
                              │  api-client.ts → apiFetch()  │
                              │  Vanilla JS chart modules    │
                              │  Distance-based hover sync   │
                              │  Zustand state management    │
                              └─────────────────────────────┘
```

### Auth/Tenant Flow

```
User → login/register → JWT access token (in-memory)
                       → Refresh token (httpOnly cookie)
     → API request → Authorization: Bearer <jwt>
                   → X-Workspace-Id: <wid>
     → Auth middleware → decode JWT → g.current_user_id
     → Tenant middleware → SET LOCAL workspace_id → RLS auto-filter
     → Route handler → response
```

### Module Duplication & Drift

| Category | Local Only | SaaS Only | Both (identical) | Both (diverged) |
|----------|-----------|-----------|-------------------|-----------------|
| **JS chart modules** | 44 (corner replay, race strategy, consistency heatmap, etc.) | 1 (module-shim.js) | 14 (chart_sync, speed_trace_zoom, gps_trace, gg_explorer, etc.) | 1 (fetch_helper.js — SaaS adds auth headers) |
| **Routes** | 9 HTML template routes (drivers, tracks, karts, weekends, leaderboard, dev_plans, dashboard, analytics, data_health) | 5 (auth, workspaces, teams, billing API, sessions_v2) | 0 | 1 (data_v2.py — SaaS-specific API) |
| **Pipeline** | Full 14-stage | Same | Yes | No |
| **Database** | SQLite schema v27 | PostgreSQL + Alembic + RLS | Schema matches | PG adds workspace_id, RLS, users table |

---

## Section 2 — Golden Reference — Local Tool Feature Contract

### 2.1 Session Identity

**Fields & Precedence:**
1. `session_id` — `YYYY-MM-DD_HHmmss` derived from CSV timestamp (primary key)
2. `csv_filename` — original file name (display only, never used as ID)
3. `driver_id` → `drivers.driver_name` (user-specified at upload or "Unknown")
4. `track_id` → `tracks.track_name` (auto-detected via GPS fingerprint)
5. `session_type` — enum: practice, qualifying, race, test, heat, final, sprint_race, feature_race, endurance_stint, endurance_race
6. `track_state` — enum: dry, damp, wet, drying, green, rubbered, dusty, greasy, cold, full_wet

**Evidence:** `telemetry_tool/db/schema.py` (sessions table), `telemetry_tool/session_context.py` (SessionType, TrackState enums)

### 2.2 Lap Detection & Validity

| Rule | Implementation | Evidence |
|------|---------------|----------|
| Lap splitting | By `"Lap #"` column in RaceChrono CSV | `io_racechrono.py` |
| Lap numbering | 1-indexed, sequential | `pipeline.py` |
| Validity check | Outlier detection: >3σ from mean lap time → invalid | `pipeline.py` |
| Incomplete laps | First/last lap marked invalid if <80% of median distance | `session_trimming.py` |
| Best lap | Shortest valid lap time → `is_best=1` | `features.py` |
| Joker lap | Track-configurable: distance/time delta tolerance | `tracks.has_joker`, `tracks.joker_distance_delta_m` |

### 2.3 Distance Axis Generation & Resampling

**File:** `telemetry_tool/resampling.py`

| Step | Detail |
|------|--------|
| Input | Raw `Distance (m)` column (cumulative from lap start) |
| Validation | ≥2 finite points, monotone increasing |
| Grid | `np.linspace(dist_min, dist_max, n_points=1000)` |
| Interpolation | `np.interp()` per numeric channel (piecewise linear, clamped) |
| Output | All channels on uniform 1000-point distance grid |
| Synthetic column | `distance_norm` (0.0–1.0 fractional position) |
| Invariant | Final interpolated time ≈ original lap duration |

### 2.4 Chart Sync Backbone

**Files:** `chart_sync.js`, `gps_trace.js`, `speed_trace_zoom.js`

**Mechanism:** All charts use **distance in meters** as the shared coordinate:
1. Speed chart hover → pixel X → distance → `GpsTrace.updateMarkerByDistance(distM)`
2. Map hover → distance → `ChartSync.updateCrosshair(distM)`
3. Both show tooltip: speed @ distance

**SaaS equivalent:** Zustand store `chart-hover-store.ts` with `setHover(distance, source)` / `clearHover()`. Source tracking prevents echo loops.

**Pages requiring sync:** Session detail (Visualize tab), Compare, Visualize full-screen, Analytics

### 2.5 Sectors Model

**File:** `telemetry_tool/sector_analysis.py`

| Property | Value |
|----------|-------|
| Default sectors | 3 (S1, S2, S3) |
| Split method | Equal distance intervals |
| Ideal lap | Best sector time from each sector across all valid laps |
| Stats per sector | best_time_s, mean_time_s, std_time_s, cv_pct, median_time_s, loss_vs_best_s, weakness_rank |
| Coaching | Text string identifying weakest sector + improvement suggestion |

### 2.6 Corners Model

**File:** `telemetry_tool/corner_detection.py`

| Property | Value |
|----------|-------|
| Method | Curvature κ = yaw_rate / speed (fallback: positional curvature from X/Y) |
| Smoothing | Gaussian-weighted rolling window (half_window=15) |
| Peak threshold | κ > 0.01 1/m (~radius < 100m) |
| Expansion | Down to κ > 0.005 1/m |
| Merge gap | <30m between regions → merge |
| Min length | 20m |
| Direction | Sign of dominant curvature (positive = right) |
| Output | `[{corner_id, s_start, s_end, s_apex, direction}]` |

**Corner Metrics (per-lap, per-corner):** `corner_metrics` table
- brake_point_m, brake_intensity, entry_speed_mps, apex_speed_mps, exit_speed_mps
- throttle_onset_m, exit_accel_mps2, grip_utilization, time_loss_ms, coaching_hint

### 2.7 GG Model

**File:** `gg_explorer.js`, `gg_diagram.js`

| Property | Value |
|----------|-------|
| Channels | `accel_lat` (G), `accel_long` (G) from `gps_traces.accel_lat_json/accel_long_json` |
| maxG | `Math.sqrt(latG² + longG²)` peak magnitude |
| Friction circle | Dashed circle at maxG * 0.95 |
| Axis range | ±3G lateral, -2 to +4G longitudinal (auto-scaled with 15% headroom) |
| Modes | All (density heatmap), Single (one lap), Compare (primary + comparison) |

### 2.8 Score Model

**File:** `telemetry_tool/scoring.py` (2,700 lines)

| Pillar | Max | Weight | Key Metrics |
|--------|-----|--------|------------|
| Pace | 25 | 25% | Best vs theoretical (±2% = full; 12% slower = 0). Blend: 70% percentage + 30% absolute |
| Consistency | 25 | 25% | CV% (dry: 0.6% full, 3% zero; wet: 0.5% full, 5% zero). 75% CV + 25% best-to-median |
| Execution | 20 | 20% | Speed/accel/braking efficiency vs theoretical (90/85/85% = full). 50% speed + 25% accel + 25% braking |
| Robustness | 15 | 15% | Pace retention over stint, lap-to-lap stability |
| Adaptation | 15 | 15% | Improvement tracking across session duration |

**Grade mapping:** S (95-100), A (80-95), B (60-80), C (40-60), D (20-40), F (0-20)

---

## Section 3 — Online SaaS Gap Audit (Parity Matrix)

### Page-by-Page Parity Matrix

| LOCAL Page | ONLINE Equivalent | Status | Root Cause(s) | Evidence |
|-----------|-------------------|--------|---------------|----------|
| **Dashboard** | `/app/dashboard` | **Partial** | Dashboard stats endpoint works; sparklines render. Missing: recent session cards lack click-through to session detail with proper data. | `data_v2.py:122-172`, `lap-website/src/app/app/dashboard/page.tsx` |
| **Session List** | `/app/sessions` | **Working** | List + pagination functional. Missing: filter by driver/track/date/score. | `data_v2.py:180-211`, limited query params (only limit/offset) |
| **Upload/Analyze** | `/app/sessions/upload` | **Working** | Synchronous upload, pipeline runs, results stored. Returns session_id + score. | `sessions_v2.py:199-416` |
| **Session Detail: Overview** | `/app/sessions/[id]` → Overview tab | **Working** | Score bars, grade badge, best lap stats all render. | `page.tsx:310-311` (OverviewTab) |
| **Session Detail: Speed Trace + Map** | `/app/sessions/[id]` → Visualize tab | **Working** | SpeedTraceZoom + GpsTrace + GGExplorer render via vanilla JS wrappers. Hover sync via Zustand. | `page.tsx:313-314` (VisualizeTab), `useVanillaChart.ts` |
| **Session Detail: Corners** | `/app/sessions/[id]` → Corners tab | **Partial** | Corner list renders (name, coaching hint). Missing: corner replay animation, cockpit view, corner mastery chart. | `page.tsx:316`, `data_v2.py:418-437` |
| **Session Detail: Performance** | `/app/sessions/[id]` → Performance tab | **Partial** | Score breakdown renders. Missing: sector chart, fingerprint radar, driving style features display. | `page.tsx:317-319` |
| **Session Detail: Timeline** | `/app/sessions/[id]` → Timeline tab | **Working** | Lap progress chart renders via `lap_progress.js`. Stint analysis data available. | `page.tsx:320`, `data_v2.py` stint endpoints |
| **Session Detail: Lap Data** | `/app/sessions/[id]` → Laps tab | **Working** | Lap table with time, speed, valid/best flags. | `page.tsx:321` |
| **Compare Sessions** | `/app/compare/sessions` | **Partial** | Basic comparison (scores, laps). Missing: speed overlay, delta chart, GPS comparison. | `data_v2.py:483-536`, no delta/overlay data in comparison response |
| **Compare Drivers** | `/app/compare/drivers` | **Placeholder** | (G) | No API endpoint for driver comparison. Frontend page exists but lacks data. |
| **Drivers List** | `/app/drivers` | **Broken** | (A/G) | `routes/drivers.py` serves HTML template at `/drivers/`, not JSON at `/api/v1/drivers`. Frontend calls API, gets 404. |
| **Driver Profile** | `/app/drivers/[id]` | **Broken** | (A/G) | Same — no JSON API. Local has rich profile with progression charts, style history, badges. |
| **Tracks List** | `/app/tracks` | **Broken** | (A/G) | `routes/tracks.py` serves HTML at `/tracks/`, not JSON. Frontend gets 404. |
| **Track Detail** | `/app/tracks/[id]` | **Broken** | (A/G) | No JSON API. Local has records, sectors, S/F editing, dry/wet reference sessions. |
| **Karts List** | `/app/karts` | **Broken** | (A/G) | `routes/karts.py` serves HTML at `/karts/`, not JSON. |
| **Kart Detail** | `/app/karts/[id]` | **Broken** | (A/G) | No JSON API. Local has specs, linked sessions. |
| **Weekends** | `/app/weekends` | **Broken** | (A/G) | `routes/weekends.py` serves HTML, not JSON. |
| **Leaderboard** | `/app/leaderboard` | **Broken** | (A/G) | `routes/leaderboard.py` serves HTML, not JSON. |
| **Dev Plans** | N/A (no SaaS page) | **Missing** | (A/G) | `routes/dev_plans.py` serves HTML. No SaaS page exists. |
| **Analytics: Consistency** | `/app/analytics` | **Placeholder** | (D/G) | No `consistency_heatmap.js` in SaaS. No API for consistency data. |
| **Analytics: Weather** | `/app/analytics/weather` | **Placeholder** | (A/G) | No weather correlation API endpoint. |
| **Analytics: Trends** | `/app/analytics/trends` | **Placeholder** | (A/G) | No performance trend API endpoint. |
| **Analytics: Pace Predictor** | `/app/analytics/pace-predictor` | **Placeholder** | (A/G) | No pace prediction API endpoint. |
| **Analytics: Weight Sim** | `/app/analytics/weight-simulator` | **Placeholder** | (A/G) | No weight simulation API endpoint. |
| **Corner Replay** | `/app/sessions/[id]/corners/[cornerId]` | **Partial** | (D/G) | `CornerReplay.tsx` exists in shared/charts but 4 supporting JS modules not ported. |
| **Visualize Full-screen** | `/app/visualize/[id]` | **Partial** | (G) | Page exists. `focus_mode.js` + `focus_tools.js` ported but missing integration. |
| **Exports** | `/app/exports` | **Placeholder** | (A/G) | Scaffold page only. No export API. |
| **Data Health** | `/app/data-health` | **Placeholder** | (A/G) | `data_health.py` serves HTML. No JSON API. |
| **Race Strategy** | `/app/race-strategy` | **Partial** | (C) | Full API exists (`api_v1_race_strategy.py`, `race_strategy_v2.py`) but complex. `race_strategy.js` + `race_strategy_live.js` not ported. |
| **Annotations** | `/app/annotations` | **Placeholder** | (A/G) | `annotations_routes.py` minimal. No CRUD API. |

### Root Cause Distribution

| Code | Description | Count |
|------|-------------|-------|
| **A** | Endpoint missing (404) | 15 |
| **B** | Endpoint crashes (500) | 0 (fixed by `_safe_api()`) |
| **C** | Data contract mismatch | 1 |
| **D** | Missing artifacts/derived channels | 3 |
| **E** | Tenant/auth scoping bug | 0 |
| **F** | CSP/runtime asset fetch blocked | 0 (Leaflet works) |
| **G** | UI component not implemented | 18 |
| **H** | Feature gated incorrectly | 0 |

**Dominant pattern:** (A) + (G) — the backend has the logic in HTML template routes but no JSON API equivalents for the SaaS frontend. This is the #1 systemic issue.

---

## Section 4 — Error & Reliability Audit

### 4.1 Known Errors

#### `/api/v1/sessions/<id>/corners` → Previously 500, now returns empty

**Status:** Fixed. The endpoint now wraps in `_safe_api()` and returns `{"corners": [], "available": false}` when theoretical data is missing.

**Root cause:** Corner coaching data is stored in `theoretical_data.corner_coaching_json`. If the theoretical engine step failed during pipeline execution (e.g., insufficient data), this column is NULL. The endpoint gracefully returns empty.

**Evidence:** `data_v2.py:418-437` — `theo.get("corner_coaching") if theo else None` returns None safely.

#### `/api/v1/dev-plans` → 404

**Root cause:** `dev_plans.py` registers blueprint at `/dev-plans/` (no `/api/v1/` prefix) and returns HTML via `render_template()`. The SaaS frontend expects JSON at `/api/v1/dev-plans`.

**Evidence:** `dev_plans.py:9` — `url_prefix="/dev-plans"`. No JSON API alternative exists.

**Fix:** Create `api_v1_dev_plans.py` blueprint at `/api/v1/dev-plans` returning JSON.

#### Entity pages (drivers/tracks/karts) → 404 or wrong content-type

**Root cause:** These routes serve Jinja2 HTML templates at non-API paths (`/drivers/`, `/tracks/`, `/karts/`). The Next.js frontend calls `/api/v1/drivers` which doesn't exist.

**Evidence:** `drivers.py:22` — `url_prefix="/drivers"`, line 30: `render_template("driver_list.html")`

#### CSP issues with Leaflet

**Status:** Not blocking. Leaflet tiles load from OpenStreetMap via HTTPS. The Caddy reverse proxy includes appropriate CSP headers. No sourcemap blocking observed in production.

### 4.2 Error Handling Contract

| Status | Policy | Current Implementation |
|--------|--------|----------------------|
| 200 | Success with data | `api_response(data)` → `{"ok": true, "data": {...}, "meta": {"request_id": "..."}}` |
| 200 empty | Success, no data | `api_response({"corners": [], "available": false})` — returns 200 with empty array |
| 400 | Validation error | `api_error(ErrorCode.VALIDATION_ERROR, msg, status=400)` |
| 404 | Resource not found | `api_error(ErrorCode.NOT_FOUND, msg, status=404)` |
| 500 | Unhandled exception | `_safe_api()` catches → logs with request_id → `api_error(ErrorCode.INTERNAL_ERROR)` |

**Recommendation:** Standardize the "empty but valid" pattern — return 200 with empty arrays/objects rather than 404 for missing optional data (e.g., no corners for a session should be 200 + empty, not 404).

### 4.3 Observability Gaps

| Gap | Impact | Fix |
|-----|--------|-----|
| No Sentry integration | Errors only visible in Docker logs | Add `sentry-sdk[flask]` to API |
| No structured logging | Plain text logs, hard to parse | Add `python-json-logger` or `structlog` |
| No request timing | Can't identify slow endpoints | Add middleware to log response time |
| No frontend error tracking | JS errors invisible | Add Sentry JS SDK to Next.js |

---

## Section 5 — Data Model & Entity Population Audit

### 5.1 Why "0 Drivers / 0 Tracks / 0 Karts"

**Root cause:** The SaaS frontend pages at `/app/drivers`, `/app/tracks`, `/app/karts` call the API client (`api.get('/drivers')` → `GET /api/v1/drivers`). This endpoint **does not exist**. The backend only has HTML template routes at `/drivers/`.

**The data IS in the database.** When a session is uploaded:
1. `upsert_driver(conn, driver_name)` creates/updates the driver record (`sessions_v2.py:285`)
2. `upsert_track(conn, track_entry)` creates/updates the track record (`sessions_v2.py:316`)
3. Sessions are linked via `driver_id` and `track_id` foreign keys

**But the SaaS frontend cannot READ this data** because there are no JSON API endpoints for these entities.

### 5.2 Schema Validation

| Table | FK to sessions | Populated during upload? | Notes |
|-------|----------------|------------------------|-------|
| `drivers` | sessions.driver_id → drivers | **Yes** — `upsert_driver()` | driver_name from form field |
| `tracks` | sessions.track_id → tracks | **Yes** — `upsert_track()` | From GPS fingerprint detection |
| `karts` | sessions.kart_id → karts | **No** — always NULL | Kart assignment not in upload flow |
| `weekends` | weekend_sessions.session_id | **No** | Manual weekend creation only |
| `driver_profiles` | driver_profiles.driver_id → drivers | **Auto-created** on driver detail view (LOCAL) | Not triggered in SaaS |

### 5.3 Correction Plan

#### Migrations Needed
None — the schema already has the correct tables and foreign keys. The data IS being stored.

#### API Endpoints Needed

| Endpoint | Method | Purpose | Source Logic |
|----------|--------|---------|-------------|
| `GET /api/v1/drivers` | GET | List all drivers with stats | Port from `drivers.py:get_all_drivers()` |
| `GET /api/v1/drivers/<id>` | GET | Driver profile + sessions | Port from `drivers.py:driver_detail()` |
| `PATCH /api/v1/drivers/<id>` | PATCH | Edit driver profile fields | Port from `drivers.py:edit_profile()` |
| `GET /api/v1/tracks` | GET | List all tracks | Port from `tracks.py:get_all_tracks()` |
| `GET /api/v1/tracks/<id>` | GET | Track detail + sessions | Port from `tracks.py:track_detail()` |
| `PATCH /api/v1/tracks/<id>` | PATCH | Rename track | Port from `tracks.py:rename_track()` |
| `GET /api/v1/karts` | GET | List all karts | Port from `karts.py` |
| `POST /api/v1/karts` | POST | Create kart | Port from `karts.py:create_kart()` |
| `GET /api/v1/weekends` | GET | List weekends | Port from `weekends.py` |
| `POST /api/v1/weekends` | POST | Create weekend | Port from `weekends.py` |
| `GET /api/v1/weekends/<id>` | GET | Weekend detail | Port from `weekends.py` |
| `GET /api/v1/leaderboard` | GET | Driver ranking | Port from `leaderboard.py` |
| `GET /api/v1/dev-plans` | GET | List development plans | Port from `dev_plans.py` |

#### Backfill Jobs Needed
- **Driver profiles:** Run `upsert_driver_profile()` for all existing drivers to compute aggregate stats (total_sessions, total_laps, best_time, etc.)
- **Kart assignment:** Optional — add kart selection to upload form, link via `sessions.kart_id`

---

## Section 6 — Frontend UX/IA Audit

### 6.1 Tab Structure Comparison

| LOCAL Session Detail Tabs | SaaS Session Detail Tabs | Status |
|--------------------------|-------------------------|--------|
| Overview (score, style, debrief, badges) | Overview (score bars, grade) | **Partial** — missing style label, badges, debrief text |
| Corners & Coaching (replay, mastery, coaching) | Corners (list only) | **Partial** — no replay, no mastery chart |
| Timeline (lap progress, stint analysis) | Timeline (lap progress chart) | **Working** |
| Analytics (consistency heatmap, energy, fatigue, weather, sectors) | Performance (score breakdown only) | **Partial** — missing all analytics charts |
| Lap Data (interactive table + overlays) | Lap Data (basic table) | **Working** |
| N/A | Visualize (speed trace + GPS + GG) | **Working** (SaaS-unique combined tab) |

### 6.2 Missing Tabs/Modules

| Module | LOCAL Location | Recommendation for SaaS |
|--------|---------------|------------------------|
| Corner Replay (animated playback) | `corner_replay.js` + 3 supporting modules | Port to `public/js/`, integrate in Corners tab |
| Corner Mastery Chart | `corner_mastery.js` | Port to `public/js/`, add to Corners tab |
| Consistency Heatmap | `consistency_heatmap.js` | Port to `public/js/`, add to Performance tab |
| Sector Chart | `sector_chart.js` | Port to `public/js/`, add to Performance tab (SectorPanel exists) |
| Driving Style Radar | `driving_style.js` + `fingerprint_chart.js` | Already in `public/js/`, wire to Performance tab |
| Energy Balance | `energy_balance.js` | Port to `public/js/`, add to Analytics sub-page |
| Fatigue Chart | `fatigue_chart.js` | Port to `public/js/`, add to Analytics sub-page |
| Stint Chart | `stint_chart.js` | Port to `public/js/`, add to Timeline tab |
| Session Badges | `session_badges.js` | Port to `public/js/`, add to Overview tab |

### 6.3 Chart Sync Bus

**Current state:** Zustand store (`chart-hover-store.ts`) provides distance-based coordination. Vanilla JS modules use `window.ChartSync.updateCrosshair(distM)` and `window.GpsTrace.updateMarkerByDistance(distM)`.

**Pages where sync must work:**
1. Session Detail → Visualize tab (speed trace ↔ GPS map ↔ GG explorer) — **Working**
2. Compare Sessions — **Not yet wired** (comparison doesn't include chart overlays)
3. Visualize full-screen — **Partially working** (focus_mode.js ported)
4. Corner Replay — **Not yet ported**

### 6.4 Format Standards

| Format | Local | SaaS | Match? |
|--------|-------|------|--------|
| Lap time | `M:SS.mmm` or `SS.mmms` | Same via `formatLapTime()` | Yes |
| Speed | km/h (converted from m/s × 3.6) | Same via `mpsToKmh()` | Yes |
| Score rounding | 1 decimal place | Same (`.toFixed(1)`) | Yes |
| Grade badge | Letter in colored box (S/A/B/C/D/F) | Same with Tailwind colors | Yes |
| Best lap badge | Gold highlight | Green text `is_best` | Differs slightly |
| Invalid lap badge | Strikethrough + reason | None shown | Missing |

---

## Section 7 — Security/Compliance & SaaS Constraints

### 7.1 Multi-Tenant Boundaries

| Check | Status | Evidence |
|-------|--------|----------|
| RLS policies on all 44 workspace-scoped tables | **Applied** | Alembic migration 007: SELECT/INSERT/UPDATE/DELETE policies |
| `SET LOCAL` for workspace context | **Working** | `middleware/tenant.py:_set_rls_context()` |
| No cross-user data leakage | **Verified** | RLS auto-filters; workspace_id required on all queries |
| IDOR prevention on team endpoints | **Implemented** | `teams.py` checks user membership before operations |

**Risk:** `SET LOCAL` resets on `conn.commit()`. Current routes don't trigger mid-request commits, but new entity CRUD routes must be careful.

### 7.2 Entitlement Gates

| Feature | Gate | Tier Required |
|---------|------|--------------|
| Session upload | `reportsPerMonth` quota | All tiers |
| Comparison | `comparisonEnabled` | World-Class |
| Visualization | `visualizationEnabled` | Racer+ |
| API access | `apiAccess` | World-Class |
| Race strategy | `raceStrategyLimit` | Racer (3h) / World-Class (full) |
| Live monitoring | `liveMonitoring` | World-Class |

**Evidence:** `entitlements-store.ts`, `LockedSection.tsx`, `UpgradeBanner.tsx`

### 7.3 Data Retention

| Tier | Raw Telemetry | Reports/Artifacts |
|------|--------------|-------------------|
| Demo | 30 days | 30 days |
| Racer | 1 year | Unlimited |
| World-Class | Unlimited | Unlimited |
| B2B | Custom | Custom |

**Implementation:** `telemetryRetentionDays` in entitlements. No automated cleanup job exists yet — needs implementation.

### 7.4 Upload Constraints

| Constraint | Value | Implementation |
|-----------|-------|----------------|
| Max file size | 10GB (INGEST_V2 streaming) | `ingest/config.py` limits |
| Processing timeout | No explicit timeout on sync endpoint | Risk: large files block request thread |
| File types | `.csv`, `.txt` only | `sessions_v2.py:_ALLOWED_EXTENSIONS` |
| Rate limit | 5 tiers via Redis sliding window | `rate_limit.py` |

---

## Section 8 — Recommended Implementation Plan

### Epic 0 (P0): Stop 500s/404s — Restore API Surface

**Objective:** Every frontend page can successfully call its backend endpoint without errors.
**Effort:** S (1-2 weeks)
**Dependencies:** None

**Tasks:**

- [ ] Create `routes/api_v1_entities.py` with JSON endpoints for:
  - `GET /api/v1/drivers` → calls `models.get_all_drivers(conn)`, returns JSON array
  - `GET /api/v1/drivers/<id>` → calls models to build driver profile, returns JSON
  - `GET /api/v1/tracks` → calls `models.get_all_tracks(conn)`, returns JSON array
  - `GET /api/v1/tracks/<id>` → calls models for track detail + sessions, returns JSON
  - `GET /api/v1/karts` → calls models to list karts, returns JSON array
  - `GET /api/v1/karts/<id>` → calls models for kart detail, returns JSON
  - `GET /api/v1/weekends` → calls models, returns JSON array
  - `GET /api/v1/weekends/<id>` → calls models for weekend detail, returns JSON
  - `GET /api/v1/leaderboard` → calls leaderboard logic, returns JSON
  - `GET /api/v1/dev-plans` → calls development_plan logic, returns JSON
  - **Files:** `telemetry_tool/web/routes/api_v1_entities.py` (new), `telemetry_tool/web/app.py` (register blueprint)
  - **Model functions to reuse:** `get_all_drivers()`, `get_driver_profile()`, `get_driver_progression()`, `get_all_tracks()`, `get_track_by_id()`, `get_track_records()` from `web/models.py`

- [ ] Add session list filtering to `GET /api/v1/sessions`:
  - Query params: `driver_id`, `track_id`, `date_from`, `date_to`, `min_score`
  - **File:** `data_v2.py:180-211`

- [ ] Standardize empty-data responses: return 200 + empty array (not 404) for missing optional data
  - **Files:** `data_v2.py` endpoints for corners, scores, theoretical

- [ ] Wire frontend entity pages to new endpoints:
  - **Files:** `lap-website/src/app/app/drivers/page.tsx`, `tracks/page.tsx`, `karts/page.tsx`, etc.

**Acceptance criteria:**
- All frontend pages load without console errors
- Entity pages show correct counts (drivers, tracks, karts)
- No 500 errors in server logs during normal navigation

---

### Epic 1 (P1): Entity CRUD + Metadata Editing

**Objective:** Users can create, edit, and manage all entities (drivers, tracks, karts, weekends) through the SaaS UI.
**Effort:** M (2-3 weeks)
**Dependencies:** Epic 0 (API surface exists)

**Tasks:**

- [ ] Add POST/PATCH/DELETE endpoints for entities:
  - `POST /api/v1/karts` — create kart
  - `PATCH /api/v1/karts/<id>` — edit kart
  - `DELETE /api/v1/karts/<id>` — delete kart
  - `PATCH /api/v1/tracks/<id>` — rename track, update S/F, add/remove sectors
  - `PATCH /api/v1/drivers/<id>` — edit driver profile fields
  - `POST /api/v1/weekends` — create weekend
  - `PATCH /api/v1/weekends/<id>` — edit weekend, add/remove sessions
  - `DELETE /api/v1/weekends/<id>` — delete weekend
  - **Files:** `api_v1_entities.py` (extend)

- [ ] Add kart selection to upload form:
  - Frontend: dropdown on upload page selecting from `GET /api/v1/karts`
  - Backend: accept `kart_id` in upload form fields, set `sessions.kart_id`
  - **Files:** `sessions_v2.py`, `lap-website/src/app/app/sessions/upload/page.tsx`

- [ ] Implement session metadata editing UI:
  - InlineEdit for driver_name, track_state, session_type, notes
  - PATCH calls to `/api/v1/sessions/<id>`
  - **Files:** `lap-website/src/app/app/sessions/[id]/page.tsx`

- [ ] Implement driver profile backfill:
  - Script to compute aggregate stats for all drivers (total_sessions, total_laps, best_time)
  - **File:** `scripts/backfill_driver_profiles.py` (new)

**Acceptance criteria:**
- Can create/edit/delete karts, weekends via UI
- Can rename tracks, edit S/F coordinates
- Upload form includes kart selection
- Session detail shows editable metadata fields

---

### Epic 2 (P2): Full Session Analysis Depth

**Objective:** Restore all analysis modules from the local tool in the SaaS session detail page.
**Effort:** L (3-4 weeks)
**Dependencies:** Epic 0

**Tasks:**

- [ ] Port corner replay modules to SaaS:
  - Copy `corner_replay.js`, `corner_replay_cockpit.js`, `corner_replay_controls.js`, `corner_replay_map.js` to `lap-website/public/js/`
  - Update `module-shim.js` path rewrites for corner data endpoints
  - Wire `CornerReplay.tsx` component to loaded modules
  - **Files:** `telemetry_tool/web/static/js/corner_replay*.js` → `lap-website/public/js/`

- [ ] Port sector chart module:
  - Copy `sector_chart.js` to `public/js/`
  - Wire into Performance tab via `SectorPanel.tsx`
  - Add API endpoint `GET /api/v1/sessions/<id>/sectors` (returns sector timing data)
  - **Files:** `sector_chart.js`, `data_v2.py` (add endpoint using `sector_analysis.py`)

- [ ] Port consistency heatmap module:
  - Copy `consistency_heatmap.js` to `public/js/`
  - Add API endpoint or compute from existing lap data
  - **Files:** `consistency_heatmap.js`

- [ ] Port corner mastery module:
  - Copy `corner_mastery.js`, `corner_picker_map.js` to `public/js/`
  - Wire into Corners tab
  - **Files:** `corner_mastery.js`, `corner_picker_map.js`

- [ ] Wire fingerprint/driving style charts:
  - `driving_style.js` and `fingerprint_chart.js` already in `public/js/`
  - Create React wrapper, wire to Performance tab
  - API endpoints already exist: `GET /api/v1/sessions/<id>/fingerprint`, `/driving-style`
  - **Files:** `lap-website/src/components/shared/charts/` (new wrappers)

- [ ] Port stint chart:
  - Copy `stint_chart.js` to `public/js/`
  - Wire into Timeline tab
  - API endpoint exists: stint data via `data_v2.py`
  - **Files:** `stint_chart.js`

- [ ] Add session badges to Overview tab:
  - Port `session_badges.js` or implement in React
  - Add API endpoint `GET /api/v1/sessions/<id>/badges`
  - **Files:** `session_badges.js`, `data_v2.py`

**Acceptance criteria:**
- Corner replay animates brake → apex → exit for each corner
- Sector timing chart shows S1/S2/S3 bars per lap
- Consistency heatmap renders sector × lap variance matrix
- Driving style radar shows 6-dimension fingerprint
- All charts sync via distance hover

---

### Epic 3 (P3): Secondary Pages & Analytics

**Objective:** Restore remaining local tool features and analytics depth.
**Effort:** L (4-6 weeks)
**Dependencies:** Epics 0-1

**Tasks:**

- [ ] Implement leaderboard page:
  - Frontend: table with ranking, track filter, sort options
  - Backend: `GET /api/v1/leaderboard?track_id=X&sort=best_time`
  - **Files:** `lap-website/src/app/app/leaderboard/page.tsx`, `api_v1_entities.py`

- [ ] Implement analytics: weather correlation:
  - Backend: `GET /api/v1/analytics/weather?driver_id=X` — correlate session_weather with lap times
  - Frontend: scatter plot (temp vs lap time)
  - **Files:** `weather_chart.js` (port), analytics page

- [ ] Implement analytics: trends:
  - Backend: `GET /api/v1/analytics/trends?driver_id=X` — score/time progression over sessions
  - Frontend: line chart (date vs score, date vs best time)
  - **Files:** `trend_analysis.js` (port), analytics page

- [ ] Implement analytics: pace predictor:
  - Backend: `GET /api/v1/analytics/pace-prediction?track_id=X&driver_id=Y` — predict target lap time
  - Frontend: prediction display with confidence interval
  - **Files:** `pace_predictor.js` (port), analytics page

- [ ] Implement development plans:
  - Backend: `GET/POST /api/v1/dev-plans` — list/create plans with templates
  - Frontend: plan editor with drill session linking
  - **Files:** `dev_plans.py` logic → JSON API, new frontend page

- [ ] Implement exports:
  - Backend: `GET /api/v1/exports/sessions/<id>?format=csv|pdf`
  - Frontend: export button with format selection
  - **Files:** new endpoint, export page

- [ ] Remove or feature-gate placeholder pages:
  - Pages with no backend: add `LockedSection` wrapper or "Coming Soon" with feature flag
  - **Files:** All placeholder pages listed in Section 3

**Acceptance criteria:**
- Leaderboard shows ranked drivers with filters
- Analytics pages render interactive charts with real data
- Dev plans can be created and linked to sessions
- No placeholder pages visible without explicit "Coming Soon" label

---

### Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Synchronous upload blocks on large files | Thread exhaustion under load | Move to Celery async for files >50MB (defer to post-parity) |
| RLS SET LOCAL resets on mid-request commit | Cross-tenant data leakage | Audit all new CRUD routes for mid-request commits |
| 63→19 JS module port introduces regressions | Charts break | Port modules unchanged; test with golden fixture |
| Frontend 96 pages, hard to test | Untested paths | Playwright E2E for critical paths; manual QA for secondary |

### Rollback Strategy

Each epic is independently deployable:
- **Epic 0:** New blueprint file — can be removed without affecting existing routes
- **Epic 1:** New endpoints + frontend changes — revert frontend to restore current behavior
- **Epic 2:** New JS files in `public/js/` — simply don't load them to revert
- **Epic 3:** Feature-flagged pages — disable flag to hide

---

## Section 9 — Testing Strategy

### 9.1 Golden Fixture Parity Tests

**Setup:**
1. Use a fixture CSV from `telemetry_tool/tests/` (or the `seeded_db` test fixture)
2. Run local tool: `python telemetry_tool/main.py data/raw/FIXTURE.csv` → capture output artifacts
3. Run SaaS: `POST /api/v1/sessions/upload` with same CSV → capture API responses
4. Compare:
   - `GET /api/v1/sessions/<id>/scores` vs local `score_result`
   - `GET /api/v1/sessions/<id>/laps` vs local lap records
   - `GET /api/v1/sessions/<id>/speed-trace` vs local resampled data
   - `GET /api/v1/sessions/<id>/corners` vs local corner coaching

**Test file:** `telemetry_tool/tests/test_golden_parity.py` (new)

### 9.2 Backend Unit Tests

| Test Area | Existing Tests | Needed Tests |
|----------|---------------|-------------|
| Streaming ingest | 50 tests (`test_streaming_ingest.py`) | None — complete |
| Upload endpoint | `test_upload_sync.py` | Add: kart_id linkage, edge cases |
| Data API | `test_data_api_v2.py` | Add: new entity endpoints, filter params |
| Pipeline correctness | `test_re_port_correctness.py` | None — complete |
| Scoring | Basic coverage | Add: boundary values (0, 100), grade transitions |
| Entity CRUD | None | Add: create/edit/delete for all entities |
| Auth + RBAC | 54 auth tests | None — complete |

### 9.3 Frontend E2E Tests (Playwright)

**Critical path test:**
```
1. Register new account
2. Upload CSV file
3. Wait for processing complete
4. Navigate to session detail
5. Verify all 6 tabs render without console errors
6. Check: score bars, lap table, speed trace canvas, GPS map, GG scatter
7. Navigate to drivers page → verify driver appears
8. Navigate to tracks page → verify track appears
```

**Additional E2E tests:**
- Session list pagination
- Compare two sessions
- Session metadata editing (change driver name)
- Logout → login → session persists via refresh token
- Feature gating (demo tier → comparison locked)

### 9.4 Contract Tests

**API JSON Schema validation:**
- Define JSON schemas for all endpoints in `telemetry_tool/web/schemas/` (Pydantic models already exist for auth)
- Validate responses against schemas in pytest
- Frontend can import TypeScript interfaces from a shared types file

---

## Decision Log

| # | Decision | Tradeoffs | Recommendation |
|---|----------|-----------|----------------|
| 1 | Create new `api_v1_entities.py` vs add JSON mode to existing routes | New file = clean separation; modify existing = less duplication but mixed concerns | **New file** — keeps template routes for local tool, JSON routes for SaaS |
| 2 | Port JS modules unchanged vs rewrite in React | Port = fast, proven; rewrite = better integration but risk | **Port unchanged** — identical code is already proven in local tool |
| 3 | Backfill entities vs create on-demand | Backfill = immediate data; on-demand = gradual | **Backfill** — run script once to populate driver_profiles from existing sessions |
| 4 | Sync upload vs async (Celery) for new entity routes | Sync = simple, current pattern; async = scalable | **Keep sync** for now — entity CRUD is lightweight. Async for file upload deferred. |
| 5 | Feature-flag analytics pages vs hide them | Flag = visible but locked; hide = cleaner | **Feature-flag with LockedSection** — shows value, encourages upgrades |
| 6 | Module-shim path rewriting vs proper API versioning | Shim = works today; proper = long-term clean | **Keep shim** — proven working, port modules unchanged |

---

## Evidence Index

| Evidence | File Path | What It Proves |
|----------|-----------|---------------|
| Pipeline orchestrator | `telemetry_tool/pipeline.py` | 14-stage flow, `_safe_step()` pattern |
| Scoring engine | `telemetry_tool/scoring.py` | 5 pillars, grade mapping, weights |
| Distance resampling | `telemetry_tool/resampling.py` | 1000-point uniform grid, `np.interp()` |
| Track detection | `telemetry_tool/track_detection.py` | IoU + lap length matching |
| Corner detection | `telemetry_tool/corner_detection.py` | Curvature-based segmentation |
| Sector analysis | `telemetry_tool/sector_analysis.py` | N-sector split, ideal lap |
| SaaS data API | `telemetry_tool/web/routes/data_v2.py` | 22+ JSON endpoints, `_safe_api()` |
| SaaS upload | `telemetry_tool/web/routes/sessions_v2.py` | Sync pipeline, entity upsert chain |
| Driver HTML route | `telemetry_tool/web/routes/drivers.py:22-30` | Serves HTML not JSON (root cause) |
| Track HTML route | `telemetry_tool/web/routes/tracks.py:22-30` | Serves HTML not JSON (root cause) |
| Kart HTML route | `telemetry_tool/web/routes/karts.py` | Serves HTML not JSON (root cause) |
| DB schema | `telemetry_tool/db/schema.py` | 44 tables, 13 phases, v27 |
| Chart sync (local) | `telemetry_tool/web/static/js/chart_sync.js` | Distance-based hover backbone |
| Chart sync (SaaS) | `lap-website/src/lib/chart-hover-store.ts` | Zustand distance sync store |
| Module shim | `lap-website/public/js/module-shim.js` | API path rewriting for SaaS |
| Vanilla chart hook | `lap-website/src/components/shared/charts/useVanillaChart.ts` | Script loading + auth header injection |
| Session detail page | `lap-website/src/app/app/sessions/[id]/page.tsx` | 6 tabs, API calls, chart mounting |
| Frontend API client | `lap-website/src/lib/api-client.ts` | Envelope format, auth headers, 401 retry |
| Auth store | `lap-website/src/lib/auth-store.ts` | In-memory tokens, cross-tab sync |
| Entitlements | `lap-website/src/lib/entitlements-store.ts` | Feature gating, tier enforcement |
| Local JS modules | `telemetry_tool/web/static/js/` (63 files) | Full local chart suite |
| SaaS JS modules | `lap-website/public/js/` (19 files) | Curated SaaS subset |
| Corner replay modules | `telemetry_tool/web/static/js/corner_replay*.js` (4 files) | Not ported to SaaS |
| RLS migrations | `telemetry_tool/alembic/versions/007_enable_rls.py` | Workspace isolation policies |
| Tenant middleware | `telemetry_tool/web/middleware/tenant.py` | X-Workspace-Id → SET LOCAL |
