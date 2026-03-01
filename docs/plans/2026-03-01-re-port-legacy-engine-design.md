# Re-Port of Legacy Telemetry Engine — Design Document

**Date**: 2026-03-01
**Type**: Controlled Recovery / Re-Port Operation
**Status**: Approved

## Context

The current SaaS telemetry system (Flask API + Next.js frontend) is functionally broken across all three layers: processing pipeline, API data endpoints, and frontend rendering. The local/desktop Old Tool (`telemetry_tool/main.py`) works perfectly and produces correct results.

This is a controlled rollback and re-port: we rebuild the SaaS telemetry experience from the ground up using the Old Tool as the authoritative source of truth.

**This is NOT**: a redesign, optimization, aesthetic evolution, or experimentation. It is a recovery to a stable, known-good system.

## Decision Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Visualization source | Both Canvas (primary) + Reports (secondary) | Full parity with local tool |
| Chart porting strategy | Wrap vanilla JS in React | Maximum fidelity, minimal rewrite risk |
| Processing execution | Synchronous (remove Celery for now) | Simplicity over latency. Re-add async later. |
| Pipeline boundary | `run_full_analysis()` + `kart_envelope` as black box | Already isolated. No extraction needed. |
| Approach | Thin Wrapper (Approach A) | Treat engine as black box, build thinnest SaaS wrapper |
| Phase ordering | Gut first, then port | Clean wound before stitching |

## Architecture: Before and After

### Before (Current — Broken)

```
Next.js Frontend (25+ broken chart components, index-based sync)
    ↓ CORS
Flask API (35+ endpoints, inconsistent data format)
    ↓
Celery Workers (unreliable pipeline tasks)
    ↓
Pipeline (diverged from local tool)
    ↓
PostgreSQL (correct schema, wrong data)
```

### After (Target — Recovered)

```
Next.js Frontend (Old Tool's vanilla JS charts wrapped in React, distance-based sync)
    ↓ CORS
Flask API (endpoints serving exactly what Old Tool templates expect)
    ↓ SYNCHRONOUS (no Celery)
run_full_analysis() / kart_envelope pipeline (IDENTICAL to local tool)
    ↓
PostgreSQL (correct schema, correct data)
```

## Core Engine Boundary

### Telemetry Core Engine v1

The engine is two pipelines:

**Pipeline A** — `telemetry_tool/pipeline.py::run_full_analysis()` (14-stage, car+kart)
```
CSV → GPS Filter → Derived Channels → Session Trim → Track Detection
→ Corner Detection → Resampling → Features → Reference Line
→ Physics Models → Theoretical Lap → ML/Anomaly → Scoring → Reports
```

**Pipeline B** — `kart_envelope/pipeline.py` (18-step, kart-specific)
```
CSV → Normalize → Clean → Track Detection → Lap Split → Outlier Filter
→ Resample → Envelope Training → Min-Time Solve → Record Calibrate
→ Delta Map → Corner Coaching → Cause Ranking → Output
```

**Dependencies** (~25 processing modules):
- `io_racechrono.py`, `gps_filtering.py`, `derived_channels.py`, `session_trimming.py`
- `track_detection.py`, `corner_detection.py`, `resampling.py`, `features.py`
- `deltas.py`, `reference_line.py`, `friction_model.py`, `vehicle_model.py`
- `theoretical_engine.py`, `lap_simulation.py`, `scoring.py` (2,700 lines)
- `reporting_html.py`, `reporting_pdf.py`, `feature_builder.py`, `ml_engine.py`
- `condition_tracking.py`, `driver_profile.py`, `debrief_engine.py`, `driving_style.py`
- `corner_analysis.py`
- `kart_envelope/` — full package

**Engine contract**: Takes CSV path + metadata dict → returns rich result dict. Stateless, deterministic, no HTTP/auth/tenant awareness.

**Outside the engine** (SaaS wrapper):
- `web/` — Flask app, routes, middleware, templates
- `tasks/` — Celery (disabled)
- `auth/` — JWT, OAuth, RBAC, workspaces, teams
- `ingest/` — INGEST_V2 streaming reader (still used for memory-efficient CSV reading)
- `db/` — schema, migrations, sql_compat

## Phase 0: Gut Broken Telemetry Code

### Remove from Next.js (`lap-website/src/`)

**Pages** (`app/app/`):
- `sessions/` — all session pages and subpages
- `visualize/` — full-screen visualization workspace
- `compare/` — session and driver comparison
- `analytics/` — trends, weather, pace predictor, weight simulator
- `tracks/` (detail pages — keep track list route shell)
- `leaderboard/` — session rankings

**Components** (`components/app/`):
- `charts/` — all 25+ chart components (SpeedTrace, GGDiagram, TrackMap, LapProgress, Fingerprint, SectorChart, LapDistribution, CornerMastery, BrakeScatter, DrivingStyle, etc.)
- Any telemetry-specific UI components

**Stores/Hooks**:
- `chart-hover-store.ts` (will be replaced with distance-based version)
- `useInteractiveCanvas` hook
- Any telemetry-specific query hooks

### Remove from Flask API (`telemetry_tool/web/routes/`)

- `api_v1_data.py` — all telemetry data endpoints (35+ endpoints)
- `api_data.py` — legacy data endpoints
- `analysis.py` — analysis routes
- `visualize.py` — visualize routes
- `comparisons.py` — comparison routes
- `sessions.py` — session CRUD (will rebuild)
- `batch.py` — batch processing routes
- `exports.py` — export routes

### Keep Intact

- `auth.py`, `api_v1_account.py` — authentication
- `billing.py` — Stripe integration
- `workspaces.py`, `teams.py` — workspace/team management
- `health.py` — health checks
- `ingest.py` — upload endpoint (will rewire)
- `drivers.py`, `karts.py` — entity CRUD
- `tracks.py` — track list endpoints
- All middleware (`auth.py`, `tenant.py`)
- All `(marketing)/` pages
- All `(auth)/` pages
- `(free-report)/` pages
- Dashboard shell (will repopulate with correct data)

## Phase 1: Port Old Tool Backend

### Upload → Process → Persist Flow

```python
@bp.route("/api/v1/sessions/upload", methods=["POST"])
@require_auth
@require_permission("upload_session")
@rate_limit("upload")
def upload_session():
    workspace_id = g.workspace_id
    tier = get_workspace_tier(workspace_id)

    # Tier checks
    if not check_upload_quota(workspace_id, tier):
        return api_error("Upload quota exceeded", 429)
    if not check_file_size(request.content_length, tier):
        return api_error("File too large for your plan", 413)

    # Save upload
    csv_file = request.files["file"]
    csv_path = save_upload_to_temp(csv_file)

    try:
        # Extract metadata from form
        session_meta = extract_session_meta(request.form)

        # SYNCHRONOUS processing — identical to local tool
        conn = get_db()
        result = run_full_analysis(csv_path, session_meta, conn)

        # Results already persisted by pipeline (models.insert_*)
        return api_response({
            "session_id": result["session_id"],
            "summary": extract_summary(result)
        })
    finally:
        # Always clean up temp file
        os.unlink(csv_path)
```

### Data Endpoints (Rebuilt)

New API endpoints that serve exactly what the Old Tool's Flask templates (`session_detail.html`, `visualize.html`) expect. The data format is defined by what `chart_sync.js`, `gps_trace.js`, etc. consume.

Key endpoints to rebuild:
- `GET /api/v1/sessions` — list sessions (paginated, workspace-filtered)
- `GET /api/v1/sessions/{id}` — session detail (metadata, scores, summary)
- `GET /api/v1/sessions/{id}/laps` — lap list with times and metrics
- `GET /api/v1/sessions/{id}/speed-trace` — speed vs distance for selected laps
- `GET /api/v1/sessions/{id}/gps-trace` — GPS coordinates with speed coloring
- `GET /api/v1/sessions/{id}/gg-data` — lateral vs longitudinal G
- `GET /api/v1/sessions/{id}/theoretical` — theoretical lap envelope
- `GET /api/v1/sessions/{id}/delta` — delta curve vs reference lap
- `GET /api/v1/sessions/{id}/corners` — corner metrics and coaching
- `GET /api/v1/sessions/{id}/fingerprint` — corner-by-corner heatmap
- `GET /api/v1/sessions/{id}/reference-line` — track geometry
- `GET /api/v1/sessions/{id}/report` — download HTML/PDF report
- `GET /api/v1/compare/sessions` — head-to-head comparison data
- `DELETE /api/v1/sessions/{id}` — delete session

### Processing Configuration

- **Gunicorn timeout**: 300s (5 minutes) for upload endpoint
- **File size limit**: 200MB (sync processing practical limit)
- **INGEST_V2**: Still active for memory-efficient CSV reading
- **Kart detection**: Pipeline auto-detects kart vs car and routes accordingly
- **Error handling**: `_safe_step()` pattern preserved — partial results returned on stage failure

## Phase 2: Port Old Tool Frontend

### Vanilla JS → React Wrapping

Each Old Tool JS module is wrapped in a React component using `useRef` + `useEffect`:

| Old Tool Module | React Component | Data Source |
|-----------------|-----------------|-------------|
| `chart_sync.js` | `<ChartSync />` | `/sessions/{id}/speed-trace` |
| `gps_trace.js` | `<GpsTrace />` | `/sessions/{id}/gps-trace` |
| `speed_trace_zoom.js` | `<SpeedTraceZoom />` | Speed trace + corners |
| `gg_explorer.js` | `<GGExplorer />` | `/sessions/{id}/gg-data` |
| `corner_replay.js` | `<CornerReplay />` | Corner metrics + GPS |
| `comparison.js` | `<Comparison />` | `/compare/sessions` |
| `chart_frame.js` | `<ChartFrame />` | Container wrapper |
| `focus_mode.js` | `<FocusMode />` | Modal overlay |

### Cross-Chart Synchronization

Replace `window.ModuleManager` with Zustand store using **distance-based** hover:

```typescript
interface ChartHoverState {
  hoverDistance: number | null;  // meters (NOT index)
  hoverSource: string | null;   // 'speed' | 'gps' | 'gg'
  setHover: (distance: number, source: string) => void;
  clearHover: () => void;
}
```

Each wrapped chart module reads `hoverDistance` from the store and updates its hover marker accordingly. This preserves the Old Tool's distance-based sync behavior.

### Page Structure

**Session Detail Page** (`/app/sessions/[id]`):
- Overview tab: metadata + score breakdown (from Old Tool's `session_detail.html`)
- Visualize tab: GPS Map + Speed Trace + GG Diagram (from Old Tool's `visualize.html`)
- Corners tab: corner coaching + per-corner metrics
- Performance tab: consistency, robustness, condition phases
- Lap Data tab: table with all lap times and metrics

**Compare Page** (`/app/compare`):
- Dual session overlay (from Old Tool's `compare_sessions.html`)
- Score comparison + lap-by-lap delta table

### Feature Gating

Auth controls which features are accessible per tier:
- Basic: View sessions, basic charts
- Premium: Compare sessions, corner coaching, export reports
- Elite/B2B: Advanced analytics, team views, API access

## Phase 3: Report Generation

Port `reporting_html.py` and `reporting_pdf.py` as a downloadable export:

- `GET /api/v1/sessions/{id}/report?format=html` — Matplotlib-generated HTML report
- `GET /api/v1/sessions/{id}/report?format=pdf` — PDF via WeasyPrint cascade

Reports are generated on-demand (not pre-computed) from persisted session data.

## Phase 4: Validation

### Test Matrix

| Test | Method | Pass Criteria |
|------|--------|---------------|
| Pipeline correctness | 5 real CSVs, compare output field-by-field | Identical scores, lap times, corners |
| Speed trace rendering | Visual comparison Old Tool vs SaaS | Same chart appearance |
| GPS map sync | Hover on speed trace → map marker | Marker at correct GPS position |
| Distance-based hover | Hover across all synced charts | Consistent distance across charts |
| Zoom/select | Drag on speed trace | Zoom to selected range |
| Compare sessions | Load two sessions | Correct overlay and delta |
| Corner coaching | View corners tab | Same coaching text as local |
| Report download | Export HTML/PDF | Identical to local tool output |
| Auth flow | Register → login → upload → view | Correct auth gating |
| Tier restriction | Free user → premium feature | Correct feature gating |
| Upload quota | Exceed limit | 429 response |
| Workspace isolation | Two workspaces | Sessions isolated |

### Acceptance Criteria

1. Processing a CSV through SaaS produces **identical** scores to local tool (within FP tolerance)
2. All chart types render and sync correctly
3. Report generation produces same output as local tool
4. Auth, billing, and tier restrictions function correctly
5. No regressions in marketing pages, auth flows, or billing

## Phase 5: Cleanup

After validation passes:
- Remove dead code from gutted files
- Remove unused npm packages (old chart libraries)
- Remove unused Python imports
- Remove abandoned Celery task files (keep infrastructure for future)
- Remove stale API route registrations from `app.py`
- Update CLAUDE.md to reflect new architecture

## Constraints

- **Synchronous processing limit**: ~200MB files (5-min timeout with 4 Gunicorn workers)
- **Concurrent uploads**: Max 4 (one per Gunicorn worker)
- **No Celery**: Async processing disabled until sync version is proven stable
- **No UI redesign**: Charts look exactly like the Old Tool
- **No math changes**: Pipeline logic untouched

## Rollback Plan

If the re-port fails:
1. Git revert the branch
2. Redeploy previous Docker image
3. The Old Tool local mode is always available as fallback

## Open Questions

1. Should we keep the `(free-report)/` public analysis tool during the transition?
2. Do we need a migration for existing SaaS sessions (processed by broken pipeline)?
3. Should large file support (>200MB) be a Phase 6 with Celery re-enablement?
