# Phase 3: Celery + Pipeline — Design Document

**Goal:** Move the 14-stage telemetry pipeline from synchronous Flask execution to asynchronous Celery tasks with Redis broker, enabling multi-worker processing, per-workspace isolation, batch re-analysis, and processing versioning.

**Approach:** Coarse-grained — 3 Celery group tasks chained together, not 15+ fine-grained tasks. Keeps orchestration simple while enabling joker pause/resume at group boundaries.

**Constraints:** SaaS-only (no desktop .exe concern). Redis always available. PostgreSQL for all persistent state.

---

## Section 1: Celery Infrastructure

New module `telemetry_tool/celery_app.py` creates the Celery instance:

- **Broker:** Redis (already in `docker-compose.yml`)
- **Result backend:** Redis with 24-hour TTL
- **Serializer:** JSON (safe serialization only — no unsafe formats)
- **Two queues:**
  - `pipeline` — heavy CPU-bound pipeline tasks, `--concurrency=2`
  - `default` — lightweight API-triggered tasks (batch dispatch, cancellation), `--concurrency=4`
- **Worker config:** `task_acks_late=True`, `task_reject_on_worker_lost=True` for crash safety
- **Config source:** reads from Flask app config (`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`), falls back to `REDIS_URL` env var

Worker launch: `celery -A telemetry_tool.celery_app worker -Q pipeline --concurrency=2`

## Section 2: PipelineContext & Serialization

`telemetry_tool/pipeline_context.py` — a serializable context object passed between Celery groups.

- **Redis key** `pipeline:ctx:{job_id}` stores JSON metadata: job_id, workspace_id, session_id, file_path, current_stage, joker decisions, error list, timestamps
- **Temp directory** `/tmp/pipeline/{job_id}/` stores intermediate DataFrames as Parquet files (one per stage output). Named by stage: `stage_03_session_trim.parquet`
- **Lifecycle:** created at chain start, cleaned up by finalize group (or failure handler). TTL on Redis key = 2 hours (safety net)
- **Progress updates:** each stage writes `stage_name` + `progress_pct` to the `ingestion_jobs` PG row directly (no Redis pub/sub for progress)

## Section 3: Task Chain & Joker Pause/Resume

Three coarse-grained Celery tasks chained:

```
pipeline_ingest (stages 1-4) → pipeline_analyze (stages 5-8j) → pipeline_finalize (stages 9-15)
```

- **`pipeline_ingest`** (queue: `pipeline`): CSV read, GPS filter, derived channels, session trim. Writes intermediate Parquet. Updates `ingestion_jobs.stage_name` as each sub-stage completes.
- **`pipeline_analyze`** (queue: `pipeline`): Track detection, corner detection, resampling, features. If joker blocking is needed (stage 8j), this group writes `status='paused'` + `pause_reason` to `ingestion_jobs` and returns early — does NOT dispatch group 3.
- **`pipeline_finalize`** (queue: `pipeline`): Reference line, physics, theoretical lap, ML/anomaly, scoring, reports, DB persist.

**Joker resume:** `POST /api/v1/jobs/{id}/resume` with joker decision payload. Sets `ingestion_jobs.status='processing'`, stores joker decision in PipelineContext Redis key, dispatches `pipeline_finalize` as a new Celery task.

**Chain construction:**
```python
chain = (pipeline_ingest.s(job_id) | pipeline_analyze.s() | pipeline_finalize.s())
chain.apply_async(queue="pipeline")
```

Each task receives and returns `job_id`. Context read/written via Redis + temp dir.

## Section 4: Error Handling & Retry

Three error classes in `telemetry_tool/pipeline_errors.py`:

- **`TransientError`** — network/Redis blip, temp disk full. Celery `autoretry_for=(TransientError,)` with `max_retries=3`, exponential backoff (10s, 30s, 90s).
- **`FatalError`** — corrupt CSV, impossible data. No retry. Status set to `failed`, error saved to `ingestion_jobs.error_message` + `error_class='fatal'`.
- **`InteractionRequired`** — joker pause. Status set to `paused`. Not an error per se, but stops the chain.

**Worker crash:** `task_acks_late=True` means unacknowledged tasks get redelivered. `task_reject_on_worker_lost=True` ensures a killed worker's task goes back to the queue (not to DLQ).

**`_safe_step()` unchanged inside groups:** Individual stages within a group still use the existing `_safe_step()` wrapper. A stage failure is logged and skipped — the group continues. Only the error classes above stop the entire chain.

**Cleanup on failure:** Failure handler deletes temp dir, clears Redis context key, sets terminal status in PG.

## Section 5: Concurrency & Backpressure

**Per-workspace pipeline lock:** Redis `SETNX` key `pipeline:lock:{workspace_id}` with 30-minute TTL. Prevents two pipelines from writing to the same workspace concurrently. A second upload retries with `countdown=10` up to 3 times, then fails with "workspace busy".

**Queue depth limit:** Before enqueuing, check `llen(pipeline_queue)`. If > 50 pending tasks, reject the upload with HTTP 429.

**Worker memory guard:** After completing a group, check `psutil.Process().memory_info().rss`. If RSS exceeds 1.5 GB, `sys.exit(0)` — supervisor restarts the worker.

**Concurrency settings:** `pipeline` queue workers: `--concurrency=2`. `default` queue workers: `--concurrency=4`. Separate worker processes per queue.

## Section 6: Job Registry (replacing in-memory JobStore)

Replace the in-memory `JobStore` (dual-write dict + SQLite) entirely with PostgreSQL `ingestion_jobs` table. Celery tasks write status updates directly to PG. SSE endpoint reads from PG.

**New columns on `ingestion_jobs`:**
- `celery_task_id TEXT`
- `processing_version INTEGER DEFAULT 1`
- `stage_name TEXT`
- `stage_index INTEGER`
- `stage_total INTEGER`
- `progress_pct REAL`
- `error_class TEXT`
- `pause_reason TEXT`
- `updated_at TIMESTAMP`

**Job lifecycle:**
1. Upload endpoint creates row: `status='pending'`, returns `job_id`
2. Celery task picks up: `status='processing'`, updates `stage_name` per sub-stage
3. Completion: `status='completed'` with `completed_at`
4. Failure: `status='failed'` with `error_message`, `error_class`
5. Joker pause: `status='paused'` with `pause_reason`

**Cancellation:** `POST /api/v1/jobs/{id}/cancel` calls `celery_app.control.revoke(task_id, terminate=True)`, sets `status='cancelled'`.

## Section 7: Progress Streaming (SSE)

SSE endpoint `GET /api/v1/jobs/{id}/stream` polls PostgreSQL every 2 seconds.

**Progress fields updated by Celery tasks:** `stage_name`, `stage_index`, `stage_total`, `progress_pct`, `updated_at`.

**SSE events:** JSON `{status, stage_name, progress_pct, error_message}`. Connection closes on terminal status (`completed`, `failed`, `cancelled`). 30-minute timeout (~900 iterations).

**Staleness detection:** If `updated_at` hasn't changed in 5 minutes while `status='processing'`, emit `stale` event. Frontend shows "Pipeline may be stuck" with cancel option.

**Workspace scoping:** Verifies `job.workspace_id == g.workspace_id` before streaming.

## Section 8: Batch Re-analysis

**New table `batch_jobs`:** id, workspace_id, created_by, status, total_sessions, completed_sessions, failed_sessions, filter_criteria (JSONB), processing_version, created_at, completed_at.

**Flow:**
1. `POST /api/v1/batch-reanalyze` with filter criteria creates `batch_jobs` row + one `ingestion_jobs` row per matched session
2. Celery `dispatch_batch` task iterates sessions, dispatches pipeline chains with staggered `countdown` (0s, 2s, 4s, ...) to avoid thundering herd
3. Each chain's finalize group atomically increments `batch_jobs.completed_sessions`
4. When `completed + failed == total`, batch status changes to `completed`

**Concurrency:** Per-workspace lock means batch sessions execute sequentially within a workspace, but different workspaces run in parallel.

**Cancellation:** `POST /api/v1/batch-jobs/{id}/cancel` revokes all pending tasks, sets remaining jobs to `cancelled`.

## Section 9: Processing Versioning

Constant `PIPELINE_VERSION = 1` in `telemetry_tool/pipeline_version.py`. Bumped manually when pipeline logic changes meaningfully.

**Tracking:** `ingestion_jobs.processing_version` records which version produced results. `sessions.processing_version` column enables direct staleness queries.

**Staleness query:**
```sql
SELECT id FROM sessions WHERE workspace_id = :ws AND processing_version < :current_version
```

**API:** `GET /api/v1/sessions/stale` returns stale sessions. Frontend shows re-analyze banner. No automatic re-analysis on deploy.

## Section 10: Database Changes

**Modified tables:**
- `ingestion_jobs` — add: `celery_task_id TEXT`, `processing_version INTEGER DEFAULT 1`, `stage_name TEXT`, `stage_index INTEGER`, `stage_total INTEGER`, `progress_pct REAL`, `error_class TEXT`, `pause_reason TEXT`, `updated_at TIMESTAMP`
- `sessions` — add: `processing_version INTEGER DEFAULT 1`

**New tables:**
- `batch_jobs` (id, workspace_id, created_by, status, total_sessions, completed_sessions, failed_sessions, filter_criteria JSONB, processing_version, created_at, completed_at)

**New files:**
- `telemetry_tool/celery_app.py` — Celery instance + config
- `telemetry_tool/pipeline_version.py` — PIPELINE_VERSION constant
- `telemetry_tool/tasks/pipeline_tasks.py` — 3 group tasks + chain builder
- `telemetry_tool/tasks/batch_tasks.py` — batch dispatch task
- `telemetry_tool/pipeline_context.py` — PipelineContext serialization
- `telemetry_tool/pipeline_errors.py` — TransientError, FatalError, InteractionRequired

**Single Alembic migration** (009) for all schema changes.

## Section 11: Testing Strategy

**Unit tests** (no Redis/Celery):
- `test_pipeline_context.py` — serialize/deserialize round-trip, temp dir cleanup, mocked Redis
- `test_pipeline_errors.py` — error classification, retry eligibility
- `test_pipeline_version.py` — staleness comparison
- `test_batch_jobs.py` — creation, progress increment, cancellation states

**Integration tests** (mocked Celery, real PG):
- `test_pipeline_tasks.py` — group tasks with `CELERY_ALWAYS_EAGER=True`, DB state transitions
- `test_joker_pause.py` — pause/resume flow
- `test_pipeline_lock.py` — workspace lock contention
- `test_job_cancellation.py` — revoke + status transition + SSE close
- `test_batch_reanalysis.py` — batch creates correct jobs, progress increments, final status

**SSE tests:**
- `test_sse_streaming.py` — event emission, terminal close, staleness detection, workspace scoping

**Migration test:**
- `test_migration_009.py` — columns exist, defaults correct, FK constraints

**CI:** `CELERY_ALWAYS_EAGER=True` for synchronous execution. Real Redis tests run locally with `docker-compose up`.
