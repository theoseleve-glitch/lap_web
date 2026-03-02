# Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the telemetry SaaS with async upload processing, tiered retention enforcement, composite DB indexes with rollup tables, and full-stack Sentry observability.

**Architecture:** Convert synchronous upload to Celery dispatch with per-stage progress callbacks. Add composite indexes and app-level rollup tables for workspace-scoped queries. Integrate Sentry across Flask, Celery workers, and Next.js client. Enforce JSON logging in production.

**Tech Stack:** Python/Flask, Celery, PostgreSQL 16, Alembic, Next.js 14, @sentry/nextjs, @sentry/browser, Zustand, TanStack Query

---

## Phase 1: Async Processing & Progress Reporting

### Task 1: Add progress_callback to pipeline.py

**Files:**
- Modify: `telemetry_tool/pipeline.py:243` (`_safe_step`), `telemetry_tool/pipeline.py:475` (`run_full_analysis`)

**Context:** `_safe_step()` at line 243 wraps every pipeline stage. `run_full_analysis()` at line 475 is the 14-stage orchestrator with 44 `_safe_step()` calls. The pipeline already has a `_record()` helper that tracks `steps_ok` / `steps_failed`. We need to add an optional callback that fires after each major stage so Celery tasks can write progress to `ingestion_jobs`.

**Step 1: Add `progress_callback` parameter to `run_full_analysis()`**

At line 475, add to the function signature after `joker_callback`:
```python
def run_full_analysis(
    csv_path: str | Path,
    session_meta: dict[str, Any],
    *,
    enable_ml: bool = True,
    enable_report: bool = True,
    output_dir: Optional[str | Path] = None,
    n_resample_points: int = 1000,
    lap_range: Optional[tuple[int, int]] = None,
    context: Any = None,
    driver_tag: Optional[str] = None,
    corner_callback: Optional[Any] = None,
    joker_callback: Optional[Any] = None,
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
) -> dict[str, Any]:
```

The callback signature is `(stage_index, stage_total, stage_name, status)` where status is `"running"` or `"done"`.

**Step 2: Define stage map and fire callbacks**

After the `summary` dict initialisation (~line 548), add:
```python
# Stage progress tracking
_STAGE_MAP: list[tuple[str, str]] = [
    ("01_ingest",           "Ingesting CSV"),
    ("02_filter",           "GPS Filtering"),
    ("03_derived_channels", "Derived Channels"),
    ("04_trim_session",     "Session Trim"),
    ("05_detect_track",     "Track Detection"),
    ("06_segment_laps",     "Lap Segmentation"),
    ("06b_detect_corners",  "Corner Detection"),
    ("08_compute_metrics",  "Computing Metrics"),
    ("09a_reference_line",  "Reference Line"),
    ("09_compute_deltas",   "Physics Models"),
    ("10_theoretical",      "Theoretical Lap"),
    ("11_build_features",   "Feature Engineering"),
    ("13_score_session",    "Scoring"),
    ("15_persist_db",       "Saving Results"),
]
_STAGE_TOTAL = len(_STAGE_MAP)  # 14
_STAGE_LOOKUP = {name: (i + 1, label) for i, (name, label) in enumerate(_STAGE_MAP)}

def _fire_progress(step_name: str, status: str = "done") -> None:
    if progress_callback and step_name in _STAGE_LOOKUP:
        idx, label = _STAGE_LOOKUP[step_name]
        try:
            progress_callback(idx, _STAGE_TOTAL, label, status)
        except Exception:
            pass  # Never let progress reporting crash the pipeline
```

**Step 3: Insert `_fire_progress()` calls after each major `_safe_step()` call**

After each `_safe_step()` call for the 14 major stages, add a `_fire_progress()` call. For example, after line 629 (`01_ingest`):
```python
result, err = _safe_step("01_ingest", _ingest, csv_path, ...)
_record("01_ingest", result, err)
_fire_progress("01_ingest")
```

And similarly after lines: 648 (`02_filter`), 671 (`03_derived_channels`), 691 (`04_trim_session`), 716 (`05_detect_track`), 760 (`06_segment_laps`), 800 (`06b_detect_corners`), 840 (`08_compute_metrics`), 1251 (`09a_reference_line`), 1495 (`09_compute_deltas`), 1786 (`10_theoretical`), 2025 (`11_build_features`), 2129 (`13_score_session`), 2547 (`15_persist_db`).

**Step 4: Verify pipeline still works**

Run: `pytest telemetry_tool/tests/test_re_port_correctness.py -v`
Expected: All tests pass (callback is optional, defaults to None).

**Step 5: Commit**
```bash
git add telemetry_tool/pipeline.py
git commit -m "feat: add progress_callback to run_full_analysis for per-stage reporting"
```

---

### Task 2: Wire progress callbacks into Celery pipeline tasks

**Files:**
- Modify: `telemetry_tool/tasks/pipeline_tasks.py:91` (`_update_job_progress`), `:401` (`pipeline_ingest`), `:472` (`pipeline_analyze`), `:533` (`pipeline_finalize`)

**Context:** `_update_job_progress()` at line 91 already writes `stage_name`, `stage_index`, `stage_total` to `ingestion_jobs`. The 3 Celery tasks (`pipeline_ingest`, `pipeline_analyze`, `pipeline_finalize`) call `run_full_analysis()` but don't pass a `progress_callback`. Each task loads a `PipelineContext` from Redis.

**Step 1: Create a progress callback factory**

After `_update_job_progress()` (after line 133), add:
```python
def _make_progress_callback(job_id: str, conn=None):
    """Return a callback compatible with pipeline.run_full_analysis(progress_callback=...)."""
    def _cb(stage_index: int, stage_total: int, stage_name: str, status: str) -> None:
        _update_job_progress(
            job_id,
            status="processing",
            stage_name=stage_name,
            stage_index=stage_index,
            stage_total=stage_total,
            conn=conn,
        )
    return _cb
```

**Step 2: Pass callback in each Celery task**

In `pipeline_ingest` (line 401), find the `run_full_analysis()` call and add `progress_callback=_make_progress_callback(job_id, conn)`.

Do the same for `pipeline_analyze` (line 472) and `pipeline_finalize` (line 533). Note: each task has its own DB connection from context. If the task calls `run_full_analysis()` directly, pass the callback. If it calls sub-functions, pass the callback through.

**Step 3: Commit**
```bash
git add telemetry_tool/tasks/pipeline_tasks.py
git commit -m "feat: wire per-stage progress callback into Celery pipeline tasks"
```

---

### Task 3: Convert upload route to async Celery dispatch

**Files:**
- Modify: `telemetry_tool/web/routes/sessions_v2.py:199` (`upload_session`)

**Context:** The upload endpoint at line 199 currently calls `run_full_analysis()` synchronously at line 278, blocking the HTTP request for the entire pipeline duration. The `build_pipeline_chain()` function at `pipeline_tasks.py:621` already constructs the Celery chain. We need to:
1. Save the file to a persistent location (not temp dir that gets cleaned up)
2. Create an `ingestion_jobs` row
3. Dispatch the Celery chain
4. Return HTTP 202 with `{job_id, status: 'pending'}`

**Step 1: Add imports at top of sessions_v2.py**

```python
import uuid
from telemetry_tool.tasks.pipeline_tasks import build_pipeline_chain
```

**Step 2: Replace synchronous pipeline call with async dispatch**

Replace the section from line 278 (the `run_full_analysis()` call) through line 413 (the return) with:

```python
# ── Create job record ──────────────────────────────────
job_id = uuid.uuid4().hex
conn = _get_conn()
conn.execute(
    """INSERT INTO ingestion_jobs
       (job_id, workspace_id, user_id, file_name, file_path,
        status, stage_name, stage_index, stage_total, created_at)
       VALUES (%(job_id)s, %(ws)s, %(uid)s, %(fname)s, %(fpath)s,
               'pending', 'Queued', 0, 14, NOW())""",
    {
        "job_id": job_id,
        "ws": g.workspace_id,
        "uid": g.user_id,
        "fname": safe_name,
        "fpath": str(tmp_path),
    },
)
conn.commit()

# ── Dispatch Celery chain ──────────────────────────────
build_pipeline_chain(job_id).apply_async()

return api_response(
    {"job_id": job_id, "status": "pending"},
    status=202,
    message="Upload accepted. Processing started.",
)
```

**Step 3: Remove the `finally: shutil.rmtree()` cleanup**

The temp file must persist until the Celery task completes. Move cleanup into the Celery finalize task instead. Change the `finally` block at line 423 from `shutil.rmtree(tmp_dir, ignore_errors=True)` to a comment: `# Cleanup handled by Celery finalize task`.

**Step 4: Ensure PipelineContext is seeded in Redis**

Check `pipeline_tasks.py` — `pipeline_ingest` loads `PipelineContext.load(redis, job_id)`. This context must be created before dispatching. Add before the `apply_async()` call:

```python
from telemetry_tool.tasks.pipeline_tasks import PipelineContext
ctx = PipelineContext(
    job_id=job_id,
    workspace_id=str(g.workspace_id),
    user_id=str(g.user_id),
    csv_path=str(tmp_path),
    session_meta=session_meta,
)
ctx.save()
```

**Step 5: Verify the old synchronous tests still make sense**

Run: `pytest telemetry_tool/tests/test_upload_sync.py -v`
These tests will need updating since the endpoint now returns 202 instead of 200 with session data. Update assertions to check for `job_id` and `status: 'pending'` in the response.

**Step 6: Commit**
```bash
git add telemetry_tool/web/routes/sessions_v2.py
git commit -m "feat: convert upload endpoint to async Celery dispatch (HTTP 202)"
```

---

### Task 4: Add tier-based file size and session count limits

**Files:**
- Modify: `telemetry_tool/web/routes/sessions_v2.py` (add validation before file save)
- Modify: `telemetry_tool/web/config.py:184` (keep global max, add tier lookup)

**Context:** Current global limit is 12 GB at `config.py:184`. We need per-tier enforcement.

**Step 1: Add tier limits lookup**

In `sessions_v2.py`, after the file extension check (~line 245), add:

```python
# ── Tier-based limits ──────────────────────────────────
_TIER_LIMITS = {
    "free":        {"max_bytes": 50 * 1024 * 1024,   "max_sessions": 10},
    "performance": {"max_bytes": 500 * 1024 * 1024,  "max_sessions": None},
    "pro_racer":   {"max_bytes": 2 * 1024**3,        "max_sessions": None},
    "b2b":         {"max_bytes": 12 * 1024**3,        "max_sessions": None},
}

def _check_tier_limits(f, conn, workspace_id: str, plan_tier: str) -> Optional[str]:
    """Return error message if limit exceeded, else None."""
    limits = _TIER_LIMITS.get(plan_tier, _TIER_LIMITS["free"])

    # File size check
    f.seek(0, 2)  # seek to end
    file_size = f.tell()
    f.seek(0)     # reset
    max_bytes = limits["max_bytes"]
    if file_size > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        return f"File size ({file_size // (1024*1024)} MB) exceeds your plan limit ({max_mb} MB). Upgrade for larger uploads."

    # Session count check
    max_sessions = limits.get("max_sessions")
    if max_sessions is not None:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM sessions WHERE workspace_id = %(ws)s",
            {"ws": workspace_id},
        ).fetchone()
        count = row["cnt"] if row else 0
        if count >= max_sessions:
            return f"Session limit reached ({max_sessions}). Upgrade your plan for more sessions."

    return None
```

**Step 2: Call the check in the upload handler**

After file validation, before saving:
```python
plan_tier = getattr(g, "plan_tier", "free")
limit_err = _check_tier_limits(f, _get_conn(), str(g.workspace_id), plan_tier)
if limit_err:
    return api_error(limit_err, status=402)
```

**Step 3: Add Celery timeout per tier**

In the async dispatch section (from Task 3), set `soft_time_limit` based on tier:
```python
_TIER_TIMEOUTS = {"free": 120, "performance": 600, "pro_racer": 1800, "b2b": 3600}
timeout = _TIER_TIMEOUTS.get(plan_tier, 120)
build_pipeline_chain(job_id).apply_async(soft_time_limit=timeout)
```

**Step 4: Commit**
```bash
git add telemetry_tool/web/routes/sessions_v2.py telemetry_tool/web/config.py
git commit -m "feat: add tier-based file size, session count, and timeout limits"
```

---

### Task 5: Update frontend upload page for async flow

**Files:**
- Modify: `lap-website/src/app/app/sessions/upload/page.tsx:44` (`uploadSession`), `:12` (`UploadResponse`), `:158` (`handleSubmit`)

**Context:** The upload page at `sessions/upload/page.tsx` uses raw `fetch()` at line 66 (not `apiFetch`, because multipart needs automatic Content-Type). On success, it gets back `{session_id, grade, total_score}` and redirects to the session page after 800ms. Now the API returns `{job_id, status: 'pending'}` with HTTP 202. The frontend should redirect to the existing jobs page (`/app/jobs`) or show inline progress.

**Step 1: Update `UploadResponse` type (line 12)**

```typescript
interface UploadResponse {
  job_id: string;
  status: string;
}
```

**Step 2: Update submit handler (line 158)**

Change the success path (lines 182-187) from:
```typescript
setStatus('success');
const sid = result.session_id;
setTimeout(() => router.push(`/app/sessions/${sid}`), 800);
```
to:
```typescript
setStatus('success');
router.push(`/app/jobs`);
```

**Step 3: Update success message (lines 427-439)**

Change from "Analysis complete. Redirecting to session..." to "Upload accepted. Redirecting to job monitor...".

**Step 4: Verify build**

Run: `cd lap-website && npx tsc --noEmit 2>&1 | grep -v __tests__`
Expected: No errors.

**Step 5: Commit**
```bash
git add lap-website/src/app/app/sessions/upload/page.tsx
git commit -m "feat: update upload page for async flow — redirect to jobs monitor"
```

---

## Phase 2: Retention & Cleanup

### Task 6: Schedule tiered retention in Celery beat

**Files:**
- Modify: `telemetry_tool/tasks/celery_app.py:71-127` (beat_schedule dict)

**Context:** The beat_schedule at lines 71-127 has 11 entries. `enforce_raw_data_retention` from `gdpr_tasks` runs at 02:15 UTC. The richer `enforce_telemetry_retention` from `retention_tasks.py` (which implements per-tier resolution, warning emails, and `retention_expired` flag) is NOT scheduled.

**Step 1: Add the tiered retention task to beat_schedule**

After the last entry (`weekly-retrain-and-reprocess` at line 122), add:

```python
"enforce-tiered-retention": {
    "task": "tasks.retention_tasks.enforce_telemetry_retention",
    "schedule": crontab(hour=3, minute=0),  # Daily 03:00 UTC
    "options": {"queue": "default"},
},
```

**Step 2: Commit**
```bash
git add telemetry_tool/tasks/celery_app.py
git commit -m "feat: schedule tiered retention task in Celery beat (daily 03:00 UTC)"
```

---

### Task 7: Add audit logging to session delete

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:670` (`delete_session`)

**Context:** The delete endpoint at line 670 iterates `_DELETE_RELATED_TABLES`, deletes related rows, then deletes the session. It commits at line 697 and logs at INFO level but does NOT call `log_event()`. The `log_event()` function is in `telemetry_tool/admin/audit.py:28` and accepts `request_id`.

**Step 1: Add import**

At the top of `data_v2.py`, add:
```python
from telemetry_tool.admin.audit import log_event
```

**Step 2: Add audit log call before commit**

Before `conn.commit()` at line 697, add:
```python
log_event(
    conn=conn,
    action="session.delete",
    user_id=str(g.user_id),
    workspace_id=str(g.workspace_id),
    resource_type="session",
    resource_id=session_id,
    request_id=g.get("request_id"),
    details={"tables_cleaned": list(_DELETE_RELATED_TABLES)},
)
```

**Step 3: Commit**
```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat: add audit log on session delete via log_event()"
```

---

## Phase 3: Database Performance & Rollups

### Task 8: Migration 027 — composite indexes

**Files:**
- Create: `telemetry_tool/alembic/versions/027_composite_indexes.py`

**Context:** Current migrations go up to 026 (exports). Single-column `idx_{table}_workspace` indexes exist on all 44 tables (from migration 005). We need composite indexes for the most common query patterns.

**Step 1: Create the migration file**

```python
"""027 – composite indexes for workspace-scoped queries."""

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sessions: the #1 query — list by workspace sorted by date
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_ws_date "
        "ON sessions (workspace_id, session_date DESC)"
    )
    # Sessions filtered by driver within a workspace
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_ws_driver "
        "ON sessions (workspace_id, driver_id)"
    )
    # Sessions filtered by track within a workspace
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_ws_track "
        "ON sessions (workspace_id, track_id)"
    )
    # Laps: lookup by session + lap number (speed trace, GPS trace endpoints)
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_laps_session_lap "
        "ON laps (session_id, lap_number)"
    )
    # GPS traces: same pattern
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_gps_session_lap "
        "ON gps_traces (session_id, lap_number)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sessions_ws_date")
    op.execute("DROP INDEX IF EXISTS idx_sessions_ws_driver")
    op.execute("DROP INDEX IF EXISTS idx_sessions_ws_track")
    op.execute("DROP INDEX IF EXISTS idx_laps_session_lap")
    op.execute("DROP INDEX IF EXISTS idx_gps_session_lap")
```

**Step 2: Commit**
```bash
git add telemetry_tool/alembic/versions/027_composite_indexes.py
git commit -m "feat: migration 027 — composite indexes for workspace-scoped queries"
```

---

### Task 9: Migration 028 — rollup tables

**Files:**
- Create: `telemetry_tool/alembic/versions/028_rollup_tables.py`

**Context:** No materialized views or rollup tables exist. Leaderboard and driver stats pages scan raw laps/scores on every request. We need app-level rollup tables with RLS.

**Step 1: Create the migration file**

```python
"""028 – rollup tables for driver and track aggregate stats."""

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS driver_stats_rollup (
            workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
            driver_id     INTEGER NOT NULL REFERENCES drivers(id),
            session_count INTEGER NOT NULL DEFAULT 0,
            total_laps    INTEGER NOT NULL DEFAULT 0,
            best_time_s   DOUBLE PRECISION,
            avg_score     DOUBLE PRECISION,
            avg_consistency DOUBLE PRECISION,
            last_session_date DATE,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, driver_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS track_stats_rollup (
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
            track_id        INTEGER NOT NULL REFERENCES tracks(id),
            session_count   INTEGER NOT NULL DEFAULT 0,
            best_time_s     DOUBLE PRECISION,
            avg_score       DOUBLE PRECISION,
            last_session_date DATE,
            unique_drivers  INTEGER NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, track_id)
        )
    """)

    # RLS policies
    op.execute("ALTER TABLE driver_stats_rollup ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY driver_stats_rollup_workspace ON driver_stats_rollup
        USING (workspace_id = current_setting('app.current_workspace_id')::int)
    """)
    op.execute("ALTER TABLE track_stats_rollup ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY track_stats_rollup_workspace ON track_stats_rollup
        USING (workspace_id = current_setting('app.current_workspace_id')::int)
    """)

    # Indexes for quick lookups
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_driver_rollup_ws "
        "ON driver_stats_rollup (workspace_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_track_rollup_ws "
        "ON track_stats_rollup (workspace_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS track_stats_rollup CASCADE")
    op.execute("DROP TABLE IF EXISTS driver_stats_rollup CASCADE")
```

**Step 2: Commit**
```bash
git add telemetry_tool/alembic/versions/028_rollup_tables.py
git commit -m "feat: migration 028 — driver and track stats rollup tables with RLS"
```

---

### Task 10: Rollup refresh function + wiring

**Files:**
- Create: `telemetry_tool/web/rollups.py`
- Modify: `telemetry_tool/tasks/pipeline_tasks.py` (call refresh after finalize)
- Modify: `telemetry_tool/web/routes/data_v2.py` (call refresh after delete)
- Modify: `telemetry_tool/tasks/celery_app.py` (add daily safety-net beat)

**Step 1: Create `rollups.py`**

```python
"""Refresh driver_stats_rollup and track_stats_rollup for a workspace."""

import logging

logger = logging.getLogger(__name__)


def refresh_driver_rollup(conn, workspace_id: int) -> None:
    """Recompute driver_stats_rollup for one workspace."""
    conn.execute(
        """
        DELETE FROM driver_stats_rollup WHERE workspace_id = %(ws)s
        """,
        {"ws": workspace_id},
    )
    conn.execute(
        """
        INSERT INTO driver_stats_rollup
            (workspace_id, driver_id, session_count, total_laps,
             best_time_s, avg_score, avg_consistency, last_session_date)
        SELECT
            s.workspace_id,
            s.driver_id,
            COUNT(DISTINCT s.id),
            COALESCE(SUM(s.lap_count), 0),
            MIN(s.best_lap_time_s),
            AVG(sd.total_score),
            AVG(sd.consistency_score),
            MAX(s.session_date)
        FROM sessions s
        LEFT JOIN score_details sd ON sd.session_id = s.id
        WHERE s.workspace_id = %(ws)s
          AND s.driver_id IS NOT NULL
        GROUP BY s.workspace_id, s.driver_id
        """,
        {"ws": workspace_id},
    )


def refresh_track_rollup(conn, workspace_id: int) -> None:
    """Recompute track_stats_rollup for one workspace."""
    conn.execute(
        """
        DELETE FROM track_stats_rollup WHERE workspace_id = %(ws)s
        """,
        {"ws": workspace_id},
    )
    conn.execute(
        """
        INSERT INTO track_stats_rollup
            (workspace_id, track_id, session_count, best_time_s,
             avg_score, last_session_date, unique_drivers)
        SELECT
            s.workspace_id,
            s.track_id,
            COUNT(DISTINCT s.id),
            MIN(s.best_lap_time_s),
            AVG(sd.total_score),
            MAX(s.session_date),
            COUNT(DISTINCT s.driver_id)
        FROM sessions s
        LEFT JOIN score_details sd ON sd.session_id = s.id
        WHERE s.workspace_id = %(ws)s
          AND s.track_id IS NOT NULL
        GROUP BY s.workspace_id, s.track_id
        """,
        {"ws": workspace_id},
    )


def refresh_rollups(conn, workspace_id: int) -> None:
    """Refresh all rollup tables for a workspace. Safe to call anytime."""
    try:
        refresh_driver_rollup(conn, workspace_id)
        refresh_track_rollup(conn, workspace_id)
        logger.info("Refreshed rollups for workspace %s", workspace_id)
    except Exception:
        logger.exception("Failed to refresh rollups for workspace %s", workspace_id)
```

**Step 2: Wire into Celery finalize task**

In `pipeline_tasks.py`, in the `pipeline_finalize` task (line 533), after the pipeline completes successfully and before `ctx.cleanup()`, add:
```python
from telemetry_tool.web.rollups import refresh_rollups
refresh_rollups(conn, int(ctx.workspace_id))
```

**Step 3: Wire into session delete**

In `data_v2.py`, after the `conn.commit()` at line 697 (after audit log from Task 7), add:
```python
from telemetry_tool.web.rollups import refresh_rollups
refresh_rollups(conn, int(g.workspace_id))
```

**Step 4: Add daily safety-net to Celery beat**

In `celery_app.py` beat_schedule, add:
```python
"refresh-all-rollups": {
    "task": "tasks.rollup_tasks.refresh_all_rollups",
    "schedule": crontab(hour=4, minute=0),  # Daily 04:00 UTC
    "options": {"queue": "default"},
},
```

Create `telemetry_tool/tasks/rollup_tasks.py`:
```python
"""Celery task: refresh rollup tables for all workspaces."""

from telemetry_tool.tasks.celery_app import celery
from telemetry_tool.web.rollups import refresh_rollups
import logging

logger = logging.getLogger(__name__)


@celery.task(name="tasks.rollup_tasks.refresh_all_rollups", queue="default")
def refresh_all_rollups():
    """Safety-net: recompute rollups for every workspace."""
    from telemetry_tool.web.db_pg import get_pg_conn
    conn = get_pg_conn()
    try:
        rows = conn.execute("SELECT id FROM workspaces").fetchall()
        for row in rows:
            ws_id = row["id"] if isinstance(row, dict) else row[0]
            refresh_rollups(conn, ws_id)
        conn.commit()
        logger.info("Refreshed rollups for %d workspaces", len(rows))
    except Exception:
        logger.exception("Failed to refresh all rollups")
    finally:
        conn.close()
```

**Step 5: Commit**
```bash
git add telemetry_tool/web/rollups.py telemetry_tool/tasks/rollup_tasks.py telemetry_tool/tasks/pipeline_tasks.py telemetry_tool/web/routes/data_v2.py telemetry_tool/tasks/celery_app.py
git commit -m "feat: rollup refresh function wired to upload, delete, and daily beat"
```

---

## Phase 4: Observability

### Task 11: Enforce JSON logs and root logger filter

**Files:**
- Modify: `telemetry_tool/web/logging_setup.py:91` (`setup_logging`)
- Modify: `docker-compose.prod.yml` (add env var)

**Context:** JSON logging exists but is opt-in (`TELEMETRY_LOG_FORMAT=json`). The `RequestIdFilter` is only attached to 3 named loggers (app, web, telemetry_tool) — third-party loggers (celery, psycopg2) don't get `request_id`.

**Step 1: Attach RequestIdFilter to root logger**

In `setup_logging()`, after attaching filters to the 3 named loggers (~line 117), add:
```python
# Also attach to root logger so third-party libs get request_id
logging.getLogger().addFilter(request_filter)
```

**Step 2: Set JSON format in production Docker config**

In `docker-compose.prod.yml`, in the `api` service `environment` section, add:
```yaml
TELEMETRY_LOG_FORMAT: json
```

**Step 3: Commit**
```bash
git add telemetry_tool/web/logging_setup.py docker-compose.prod.yml
git commit -m "feat: enforce JSON logs in production, attach RequestIdFilter to root logger"
```

---

### Task 12: Sentry backend — Flask + Celery

**Files:**
- Modify: `telemetry_tool/web/app.py:82` (`create_app`) — init Sentry for Flask
- Modify: `telemetry_tool/tasks/celery_app.py` — init Sentry for Celery workers
- Modify: `requirements.txt` — add `sentry-sdk[flask,celery]`

**Context:** No Sentry integration exists. The Flask app creates request IDs in `api_utils.py`. Celery tasks have job_id context. We need 2 separate inits: one for Flask (API requests), one for Celery (background tasks). Both can use the same DSN or separate DSNs.

**Step 1: Add sentry-sdk to requirements**

Add to `requirements.txt`:
```
sentry-sdk[flask,celery]>=2.0,<3.0
```

**Step 2: Init Sentry in Flask app**

In `app.py`, after imports (around line 20), add:
```python
import sentry_sdk
```

In `create_app()`, before `setup_logging(app)` (before line 137), add:
```python
# ── Sentry error tracking ──────────────────────────
sentry_dsn = os.environ.get("SENTRY_DSN_API")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE"),
        integrations=[],  # flask integration auto-detected
        before_send=_sentry_before_send,
    )
```

Add the filter function before `create_app()`:
```python
def _sentry_before_send(event, hint):
    """Attach request_id and workspace context to Sentry events."""
    try:
        from flask import g
        if hasattr(g, "request_id"):
            event.setdefault("tags", {})["request_id"] = g.request_id
        if hasattr(g, "workspace_id"):
            event.setdefault("user", {})["workspace_id"] = str(g.workspace_id)
        if hasattr(g, "user_id"):
            event.setdefault("user", {})["id"] = str(g.user_id)
    except RuntimeError:
        pass  # Outside request context
    return event
```

**Step 3: Init Sentry in Celery**

In `celery_app.py`, after the celery app creation (around line 20), add:
```python
import sentry_sdk

_worker_dsn = os.environ.get("SENTRY_DSN_WORKER")
if _worker_dsn:
    sentry_sdk.init(
        dsn=_worker_dsn,
        traces_sample_rate=0.1,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        integrations=[],  # celery integration auto-detected
    )
```

**Step 4: Add env vars to docker-compose.prod.yml**

```yaml
SENTRY_DSN_API: ${SENTRY_DSN_API}
SENTRY_DSN_WORKER: ${SENTRY_DSN_WORKER}
SENTRY_ENVIRONMENT: production
```

**Step 5: Commit**
```bash
git add telemetry_tool/web/app.py telemetry_tool/tasks/celery_app.py requirements.txt docker-compose.prod.yml
git commit -m "feat: integrate Sentry for Flask API and Celery workers"
```

---

### Task 13: Sentry frontend — Next.js client-side

**Files:**
- Create: `lap-website/sentry.client.config.ts`
- Modify: `lap-website/src/app/error.tsx` — report to Sentry
- Modify: `lap-website/src/app/layout.tsx` — init Sentry
- Modify: `lap-website/next.config.mjs` — add Sentry `connect-src` to CSP
- Modify: `lap-website/package.json` — add `@sentry/browser`

**Context:** The app runs on Cloudflare Workers via OpenNext. The full `@sentry/nextjs` package has edge-runtime complications with OpenNext. Use `@sentry/browser` directly for client-side error capture — simpler and fully compatible.

**Step 1: Install dependency**

```bash
cd lap-website && npm install @sentry/browser
```

**Step 2: Create `sentry.client.config.ts`**

```typescript
import * as Sentry from '@sentry/browser';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV,
    tracesSampleRate: 0.1,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
  });
}

export { Sentry };
```

**Step 3: Init in root layout**

In `lap-website/src/app/layout.tsx`, add at the top:
```typescript
import '@/../../sentry.client.config';
```

Or more cleanly, create `lap-website/src/lib/sentry.ts`:
```typescript
'use client';
import * as Sentry from '@sentry/browser';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
let initialized = false;

export function initSentry() {
  if (initialized || !dsn || typeof window === 'undefined') return;
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV,
    tracesSampleRate: 0.1,
  });
  initialized = true;
}

export { Sentry };
```

Then in a client component provider (e.g. `Providers.tsx`), call `initSentry()` on mount.

**Step 4: Update `error.tsx` to report to Sentry**

Replace the `console.error` at line 14 with:
```typescript
import { Sentry } from '@/lib/sentry';
// ...
useEffect(() => {
  console.error('Unhandled error:', error);
  Sentry?.captureException(error);
}, [error]);
```

**Step 5: Update CSP in `next.config.mjs`**

In the `connect-src` directive (line 28), add the Sentry ingest domain:
```
connect-src 'self' https://api.lap-coach.racing https://plausible.io https://*.ingest.sentry.io
```

**Step 6: Commit**
```bash
git add lap-website/src/lib/sentry.ts lap-website/src/app/error.tsx lap-website/next.config.mjs lap-website/package.json lap-website/package-lock.json
git commit -m "feat: add Sentry client-side error reporting for Next.js"
```

---

### Task 14: Error boundaries — global-error.tsx + ChartErrorBoundary

**Files:**
- Create: `lap-website/src/app/global-error.tsx`
- Create: `lap-website/src/components/shared/ChartErrorBoundary.tsx`

**Context:** `error.tsx` catches route-segment errors but not root layout errors. No React error boundary wraps chart components — a chart crash takes down the whole page.

**Step 1: Create `global-error.tsx`**

```typescript
'use client';

import { Sentry } from '@/lib/sentry';
import { useEffect } from 'react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Global error:', error);
    Sentry?.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body className="bg-asphalt text-chalk min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md px-4">
          <h1 className="text-4xl font-bold text-safety-red mb-3">Something went wrong</h1>
          <p className="text-steel mb-6">A critical error occurred. Please try refreshing the page.</p>
          {error.digest && (
            <p className="text-steel/50 text-xs mb-6">Ref: {error.digest}</p>
          )}
          <button
            onClick={reset}
            className="px-6 py-2 bg-acid-green text-asphalt font-bold rounded hover:bg-acid-green/90"
          >
            Try Again
          </button>
        </div>
      </body>
    </html>
  );
}
```

**Step 2: Create `ChartErrorBoundary.tsx`**

```typescript
'use client';

import { Component, type ReactNode } from 'react';
import { Sentry } from '@/lib/sentry';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  chartName?: string;
}

interface State {
  hasError: boolean;
}

export class ChartErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.error(`Chart error (${this.props.chartName ?? 'unknown'}):`, error);
    Sentry?.captureException(error, {
      tags: { component: 'chart', chart_name: this.props.chartName },
    });
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 text-center">
          <p className="text-steel text-sm">
            Chart failed to render.{' '}
            <button
              onClick={() => this.setState({ hasError: false })}
              className="text-pit-orange hover:underline"
            >
              Retry
            </button>
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
```

**Step 3: Commit**
```bash
git add lap-website/src/app/global-error.tsx lap-website/src/components/shared/ChartErrorBoundary.tsx
git commit -m "feat: add global-error.tsx and ChartErrorBoundary for resilient rendering"
```

---

### Task 15: Frontend diagnostics overlay (dev-only)

**Files:**
- Create: `lap-website/src/components/dev/DiagnosticsOverlay.tsx`
- Modify: `lap-website/src/app/app/layout.tsx` — mount overlay in dev

**Context:** Dev-only panel showing API latency, request_id, SSE status, React Query cache stats. Toggled by Ctrl+Shift+D. Only renders when `NODE_ENV === 'development'`.

**Step 1: Create `DiagnosticsOverlay.tsx`**

```typescript
'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

export function DiagnosticsOverlay() {
  const [visible, setVisible] = useState(false);
  const queryClient = useQueryClient();

  const toggle = useCallback((e: KeyboardEvent) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'D') {
      e.preventDefault();
      setVisible((v) => !v);
    }
  }, []);

  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    window.addEventListener('keydown', toggle);
    return () => window.removeEventListener('keydown', toggle);
  }, [toggle]);

  if (process.env.NODE_ENV !== 'development' || !visible) return null;

  const cache = queryClient.getQueryCache();
  const queries = cache.getAll();
  const fresh = queries.filter((q) => q.state.status === 'success').length;
  const stale = queries.filter((q) => q.isStale()).length;
  const fetching = queries.filter((q) => q.state.fetchStatus === 'fetching').length;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] bg-asphalt/95 border border-steel/30 rounded-lg p-4 text-xs font-telemetry text-steel shadow-lg max-w-xs">
      <div className="flex justify-between items-center mb-2">
        <span className="text-acid-green font-bold">Diagnostics</span>
        <button onClick={() => setVisible(false)} className="text-steel hover:text-chalk">×</button>
      </div>
      <div className="space-y-1">
        <div>Queries: {queries.length} total, {fresh} fresh, {stale} stale, {fetching} fetching</div>
        <div>ENV: {process.env.NODE_ENV}</div>
        <div>API: {process.env.NEXT_PUBLIC_API_URL || 'localhost:5000'}</div>
      </div>
    </div>
  );
}
```

**Step 2: Mount in app layout**

In `lap-website/src/app/app/layout.tsx`, add the overlay inside the layout JSX (only in dev):
```typescript
import { DiagnosticsOverlay } from '@/components/dev/DiagnosticsOverlay';

// Inside the return, at the end of the layout children:
{process.env.NODE_ENV === 'development' && <DiagnosticsOverlay />}
```

**Step 3: Verify build**

Run: `cd lap-website && npx tsc --noEmit 2>&1 | grep -v __tests__`
Expected: No new errors.

**Step 4: Commit**
```bash
git add lap-website/src/components/dev/DiagnosticsOverlay.tsx lap-website/src/app/app/layout.tsx
git commit -m "feat: add dev-only DiagnosticsOverlay toggled by Ctrl+Shift+D"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| 1. Async Processing | 1-5 | Uploads return job_id immediately, 14-stage progress visible in jobs page, tier-based limits |
| 2. Retention | 6-7 | Tiered retention scheduled, audit log on session delete |
| 3. DB Performance | 8-10 | 5 composite indexes, 2 rollup tables, auto-refresh on upload/delete |
| 4. Observability | 11-15 | JSON logs enforced, Sentry on Flask+Celery+frontend, error boundaries, dev diagnostics |

Total: **15 tasks**, estimated **38 files** touched across backend and frontend.
