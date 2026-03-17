# Endurance Stint Persist Fix — TODO

## Problem
`s15_persist.run_persist_to_db()` with `force_persist=True` still fails because it uses SQLite-specific functions (e.g., `ensure_schema()`, `_connect()`) that don't exist in PG mode. The session/laps/GPS data for per-stint sessions is never written to PostgreSQL.

## What Works
- Endurance upload form (detect, stint config, driver assignment)
- Per-stint pipeline processing via Celery (runs full analysis per stint)
- Master endurance session persists to PG (sessions list shows it)
- Endurance tab renders team report, driver report from analysis_json
- Traffic time loss detection works
- Pit efficiency grading works

## What Doesn't Work
- Per-stint sessions don't persist to PG (s15_persist skips or crashes)
- Clicking a stint card shows simplified report instead of full session page
- Stint `session_id` is always `None` in the report data

## Root Cause
`s15_persist` was designed for SQLite. In PG mode, persistence is handled by `pipeline_finalize` Celery task which uses `PipelineContext` (Redis-based). When we call `run_full_analysis()` directly (not through the Celery chain), `pipeline_finalize` never runs.

## Fix Required
Instead of calling `s15_persist`, replicate what `pipeline_finalize` does for PG:

1. Look at `tasks/pipeline_tasks.py:_run_finalize_stages()` → it calls `run_full_analysis()` with `resume_from_step8=True` which re-runs stages 8-14 and then persists via the web models layer.

2. The actual PG persist happens in the web models layer (`web/repos/session_repo.py`, `web/repos/lap_repo.py`, etc.) which are called by the pipeline stages during `run_full_analysis`.

3. The key insight: `run_full_analysis` already persists to PG when called from the finalize task because the pipeline stages write directly via `get_db_connection()` which returns PG connection.

4. The `s15_persist` step is specifically for SQLite (desktop mode). In PG mode, each pipeline stage writes its own data via the repos layer.

5. **The session IS being created in PG** — but laps/GPS/scores aren't written because the pipeline's internal persist code (in stages like `s13_scoring`, `s10_theoretical`) writes to PG but `s15_persist` (which creates the session row and links everything) is skipped.

## Simplest Fix
Call `web.repos.session_repo.insert_session()` + `web.repos.lap_repo.persist_laps_and_scores()` + `web.repos.analysis_repo.insert_stint_analysis()` directly from `_process_single_stint`, passing the summary data. This is what `pipeline_finalize` does internally.

OR: Run the Celery pipeline chain (`build_pipeline_chain(job_id)`) for each stint instead of `run_full_analysis()`. This uses the existing finalize flow that works in PG.
