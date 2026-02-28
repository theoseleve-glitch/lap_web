# Ingestion Repair — Redis-backed Job Store

**Date**: 2026-02-28
**Status**: Approved
**Scope**: Fix 404s on `/api/v1/ingest/status/<job_id>` in production

## Problem

The analysis pipeline works correctly (INGEST_V2 streaming, 14-stage pipeline, DB persistence). The bug is in **job state visibility**: the `_jobs` dict in `analysis.py` is per-process memory. Gunicorn runs 4 workers (separate processes), so status polling hits a different worker ~75% of the time → 404.

Secondary issue: frontend expects status values `complete`/`failed`/`processing` but backend sends `done`/`error`/`running` → polling loop never terminates on success.

## Solution

### 1. Redis-backed job store (analysis.py)

Replace `_jobs` dict with Redis hashes. Key: `analysis:job:{job_id}`, TTL: 2h.

Functions changed:
- `_create_job()` → `redis.hset()` + `expire(7200)`
- `_update_job()` → `redis.hset()` (merge)
- `_get_job()` → `redis.hgetall()` + deserialize
- Remove `_jobs_lock`, `_evict_old_jobs()`

### 2. Joker Event isolation

`threading.Event` is per-process (cannot share via Redis). Keep `_joker_events` as a small in-memory dict. Joker confirm must hit the same worker — add `X-Worker-Id` to start response so frontend can use sticky routing, OR accept that joker confirm has a 75% failure rate and retry. Since joker detection is rare and optional, retry is acceptable.

### 3. Status field translation

Map backend → frontend status values in `_analyze_status_impl()`:
- `queued` → `pending`
- `running` → `processing`
- `done` → `complete`
- `error` → `failed`

Map `stage` → `message` in the response.

### 4. No frontend changes

The existing Next.js page sends correct requests and polls correctly. Only the API response format needs alignment.

## Files Changed

1. `telemetry_tool/web/routes/analysis.py` — Redis job store, status mapping
2. No other files.

## Future: Celery Migration (separate task)

Wire `pipeline_tasks.py` to call `pipeline.run_full_analysis()`. Use PG `ingestion_jobs` table for durable status. Deferred — not part of this fix.
