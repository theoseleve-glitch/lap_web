# Hardening Design: Async Processing, Retention, DB Performance, Observability

**Date**: 2026-03-02
**Status**: Approved

## Context

The telemetry SaaS platform runs uploads synchronously (blocking HTTP requests for minutes on large files), lacks enforced retention scheduling, has no composite DB indexes for common query patterns, and has no error tracking service. Most infrastructure already exists but is not wired up.

## Decisions

| Area | Decision | Rationale |
|------|----------|-----------|
| Upload mode | Always async | Every upload returns job_id immediately. Simplest model, no size-detection branching. |
| Progress granularity | Per-stage (14 steps) | Add progress_callback to pipeline.py. Frontend shows "Stage 7 of 14: Corner Detection". |
| Sentry scope | Backend + frontend + Celery worker | 3 DSN configurations for full coverage with request_id correlation. |
| Rollup strategy | App-level rollup tables | New tables refreshed by post-upload hook and daily safety-net task. |

---

## 1. Async Processing & Progress Reporting

### 1.1 Upload Route Goes Async

`sessions_v2.py` changes from synchronous pipeline execution to:
1. Save uploaded file to temp storage
2. Create `ingestion_jobs` row with `status='pending'`
3. Dispatch `build_pipeline_chain(job_id)` to Celery
4. Return HTTP 202 with `{job_id, status: 'pending'}`

The existing `jobs.py` SSE/polling endpoints handle progress delivery to the frontend.

### 1.2 Per-Stage Progress Callbacks

Add `progress_callback` parameter to `run_full_analysis()` in `pipeline.py`. Each `_safe_step()` invocation fires the callback with `(stage_number, stage_name, status)`. The Celery tasks in `pipeline_tasks.py` pass a callback that writes to `ingestion_jobs.progress_json`.

Stage names for the 14-stage pipeline:
1. GPS Filter
2. Derived Channels
3. Session Trim
4. Track Detection
5. Corner Detection
6. Resampling
7. Features
8. Reference Line
9. Physics Models
10. Theoretical Lap
11. ML/Anomaly
12. Scoring
13. Reports
14. Finalize

### 1.3 Tier-Based File Size Limits

Enforce in `sessions_v2.py` before saving, using entitlements:

| Tier | Max file size | Max sessions |
|------|--------------|-------------|
| Free | 50 MB | 10 |
| Performance | 500 MB | unlimited |
| Pro Racer | 2 GB | unlimited |
| B2B | 12 GB | unlimited |

### 1.4 Timeout Enforcement

Per-tier Celery `soft_time_limit` values: Free=120s, Performance=600s, Pro=1800s, B2B=3600s.

### 1.5 Frontend Upload Flow

`sessions/upload/page.tsx` changes: POST upload → receive job_id → redirect to `/app/jobs/{job_id}` or show inline progress bar → poll/SSE `jobs/{id}/status` showing stage-level progress.

---

## 2. Retention & Cleanup

### 2.1 Schedule Tiered Retention

Add `enforce_telemetry_retention` from `retention_tasks.py` to Celery beat schedule at 03:00 UTC daily. This already implements per-workspace tier resolution, warning emails, and the `retention_expired` flag.

Keep `enforce_raw_data_retention` from `gdpr_tasks.py` at 02:15 UTC as a raw-file safety net.

### 2.2 Session Count Cap

Check against tier limits on upload:
- Free: 10 sessions
- Performance: 100 sessions
- Pro Racer: unlimited
- B2B: unlimited

Reject with HTTP 402 if exceeded.

### 2.3 Audit Log Enforcement

Ensure every deletion path calls `log_event()`:
- Retention task (already does this)
- GDPR purge (already does this)
- Manual session delete in `data_v2.py` (verify/add)
- Export cleanup (add)

---

## 3. Database Performance & Rollups

### 3.1 Composite Indexes (Migration 027)

```sql
CREATE INDEX CONCURRENTLY idx_sessions_ws_date ON sessions(workspace_id, session_date DESC);
CREATE INDEX CONCURRENTLY idx_sessions_ws_driver ON sessions(workspace_id, driver_id);
CREATE INDEX CONCURRENTLY idx_sessions_ws_track ON sessions(workspace_id, track_id);
CREATE INDEX CONCURRENTLY idx_laps_session_lap ON laps(session_id, lap_number);
CREATE INDEX CONCURRENTLY idx_gps_session_lap ON gps_traces(session_id, lap_number);
```

### 3.2 Rollup Tables (Migration 028)

**driver_stats_rollup**: `(workspace_id, driver_id)` → session_count, best_time_s, avg_score, avg_consistency, last_session_date, total_laps

**track_stats_rollup**: `(workspace_id, track_id)` → session_count, best_time_s, avg_score, last_session_date, unique_drivers

Both have RLS policies matching the standard workspace pattern.

### 3.3 Rollup Refresh

`refresh_rollups(conn, workspace_id)` function called:
- After upload completes (Celery finalize task)
- After session delete
- Daily at 04:00 UTC via Celery beat (safety net)

Uses `SET LOCAL` for RLS compliance.

### 3.4 RLS Preservation

No CRUD path should call `conn.commit()` mid-request. Add a comment guard in `db_pg.py`.

---

## 4. Observability

### 4.1 Enforce JSON Logs

Set `TELEMETRY_LOG_FORMAT=json` in production Docker config. Attach `RequestIdFilter` to root logger so third-party library logs include `request_id`.

### 4.2 Sentry Integration (3 DSNs)

**Backend (Flask)**: `sentry-sdk[flask]` init in `app.py`. Captures unhandled exceptions. Tags: `request_id`, `workspace_id`, `user_id`.

**Celery workers**: `sentry-sdk[celery]` init in `celery_app.py`. Captures task failures. Tags: `job_id`, `workspace_id`.

**Frontend (Next.js)**: `@sentry/nextjs`. Config files: `sentry.client.config.ts`, `sentry.server.config.ts`. Wraps `error.tsx` to report. Adds `request_id` from API `X-Request-Id` header as breadcrumb.

Env vars: `SENTRY_DSN_API`, `SENTRY_DSN_WORKER`, `NEXT_PUBLIC_SENTRY_DSN`.

### 4.3 Frontend Diagnostics Mode

Dev-only `DiagnosticsOverlay` toggled by `Ctrl+Shift+D`. Shows: last API latency, request_id, SSE connection status, React Query cache stats. Only renders when `NODE_ENV === 'development'`.

### 4.4 Error Boundaries

- `global-error.tsx` to catch root layout errors
- `ChartErrorBoundary` wrapper for canvas-based components so chart crashes don't take down the page

---

## Files Affected

### Backend (Python)
- `telemetry_tool/pipeline.py` — add progress_callback to run_full_analysis and _safe_step
- `telemetry_tool/web/routes/sessions_v2.py` — async dispatch, tier limits, session count check
- `telemetry_tool/tasks/pipeline_tasks.py` — wire progress_callback into Celery tasks
- `telemetry_tool/tasks/celery_app.py` — add retention task to beat schedule, Sentry init
- `telemetry_tool/web/app.py` — Sentry Flask init
- `telemetry_tool/web/logging_setup.py` — root logger filter
- `telemetry_tool/web/routes/data_v2.py` — audit log on delete, rollup refresh
- `telemetry_tool/alembic/versions/027_composite_indexes.py` — new migration
- `telemetry_tool/alembic/versions/028_rollup_tables.py` — new migration
- `telemetry_tool/web/rollups.py` — new: refresh_rollups function

### Frontend (Next.js)
- `lap-website/src/app/app/sessions/upload/page.tsx` — async upload flow with progress
- `lap-website/src/app/error.tsx` — Sentry reporting
- `lap-website/src/app/global-error.tsx` — new: root error boundary
- `lap-website/src/components/shared/ChartErrorBoundary.tsx` — new
- `lap-website/src/components/dev/DiagnosticsOverlay.tsx` — new
- `lap-website/sentry.client.config.ts` — new
- `lap-website/sentry.server.config.ts` — new
- `lap-website/next.config.mjs` — Sentry webpack plugin

### Infrastructure
- `docker-compose.prod.yml` — TELEMETRY_LOG_FORMAT=json, SENTRY_DSN_* env vars
- `.env.production` — Sentry DSN values
