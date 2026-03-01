# RaceControl Monitoring — Design

## Goal

Add two new panels to the Race Control admin dashboard: (1) a Training Status panel with full control over the weekly training pipeline, and (2) a User Resources panel that tracks storage and computing time per user with time-series charts.

## Problem

The weekly training pipeline runs autonomously but admins have no visibility into its status, no way to trigger manual runs, and no way to adjust parameters. Additionally, there is no per-user view of resource consumption — admins cannot see which users consume the most storage or compute time.

## Architecture

### New Backend Blueprints

Two new sub-blueprints in `telemetry_tool/web/routes/admin/`:

| File | Endpoints | Purpose |
|------|-----------|---------|
| `training.py` | `GET /admin/training/status` | Latest training run results (from audit manifest JSON) |
| | `GET /admin/training/history` | List of past training runs (all manifests) |
| | `POST /admin/training/trigger` | Manually dispatch `weekly_retrain_and_reprocess` |
| | `GET /admin/training/config` | Current training parameters (from Redis, fallback to defaults) |
| | `PUT /admin/training/config` | Update training config (Redis hash + audit log) |
| `monitoring.py` | `GET /admin/monitoring/users` | Per-user storage + compute aggregation |
| | `GET /admin/monitoring/users/<id>/timeseries` | Daily usage time series for a specific user |
| | `GET /admin/monitoring/totals` | System-wide totals (storage, compute, user count) |

All endpoints protected by `@require_superadmin` + `@require_admin_role("root_admin", "sre_admin")`.

### New Frontend Pages

Two new pages under `lap-website/src/app/app/race-control/monitoring/`:

| Page | Content |
|------|---------|
| `training/page.tsx` | Status cards (last run, next scheduled, tier results), history table, trigger button, config editor panel |
| `resources/page.tsx` | Summary table (per-user storage + compute, sorted), system totals MetricCards, time series chart (daily usage for selected user) |

New sidebar section "MONITORING" in `layout.tsx` with items: "Training" and "User Resources".

### Data Sources

**Training status**: Reads audit manifest JSON files from `/data/models/kart_envelope/audit/training_YYYYMMDD.json` (shared Docker volume). No new DB tables.

**Training config**: Redis hash `lap:training:config` with keys:
- `schedule_day_of_week` (default: 0, Sunday)
- `schedule_hour` (default: 0)
- `schedule_minute` (default: 0)
- `min_sessions_per_group` (default: 3)
- `reprocess_batch_size` (default: 10)
- `reprocess_pause_s` (default: 5)

Training task reads these at startup instead of hardcoded constants.

**User monitoring**: SQL aggregation over existing tables:
```sql
SELECT u.id, u.email, u.display_name,
       COUNT(DISTINCT s.session_id) AS session_count,
       COALESCE(SUM(j.file_size), 0) AS total_storage_bytes,
       COALESCE(SUM(EXTRACT(EPOCH FROM (j.completed_at - j.created_at))), 0) AS total_compute_seconds,
       MAX(j.created_at) AS last_upload
FROM users u
LEFT JOIN sessions s ON s.driver_id = u.id
LEFT JOIN ingestion_jobs j ON j.session_id = s.session_id
GROUP BY u.id, u.email, u.display_name
ORDER BY total_storage_bytes DESC
```

Time series: `GROUP BY date_trunc('day', j.created_at)` for daily aggregation.

## Error Handling

- **No training runs yet**: Return `{"last_run": null, "status": "never_run"}`. Frontend shows fallback message.
- **Redis unavailable**: Config endpoints fall back to hardcoded defaults. Manual trigger returns 503.
- **Empty monitoring data**: Users with no sessions show 0 storage, 0 compute.
- **Training already running**: `POST /admin/training/trigger` checks Celery task state first. Returns 409 CONFLICT if already in progress.
- **All mutations audited**: `log_admin_action()` on config changes, trigger, etc.

## Implementation Scope

| Piece | File | Lines |
|-------|------|-------|
| Training admin blueprint | `web/routes/admin/training.py` (new) | ~150 |
| Monitoring admin blueprint | `web/routes/admin/monitoring.py` (new) | ~120 |
| Register blueprints | `web/routes/admin/__init__.py` | ~5 |
| Admin API client methods | `lap-website/src/lib/admin-api.ts` | ~40 |
| Sidebar nav update | `lap-website/src/app/app/race-control/layout.tsx` | ~8 |
| Training page | `lap-website/src/app/app/race-control/monitoring/training/page.tsx` (new) | ~200 |
| Resources page | `lap-website/src/app/app/race-control/monitoring/resources/page.tsx` (new) | ~200 |
| Training task config read | `telemetry_tool/tasks/training_tasks.py` | ~20 |
| Backend tests | `telemetry_tool/tests/test_admin_training.py` + `test_admin_monitoring.py` (new) | ~200 |

Total: ~950 lines across 9 files (5 new, 4 modified).

## Success Criteria

1. Admin can see training status, tier results, and error details on the Training page
2. Admin can trigger a manual training run and see it dispatched
3. Admin can view and update training parameters (min sessions, schedule, throttle)
4. Admin can see per-user storage and compute usage sorted by consumption
5. Admin can view daily usage time series for any user
6. All admin actions are audit-logged
7. All endpoints require superadmin + root_admin/sre_admin role
