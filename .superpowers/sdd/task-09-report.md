# Task 9 report — onboarding/reprocess.py

**Status:** DONE

**Commit:** (see below) — feat(onboarding): Task 9 - reprocess_after_bless (F3/F4 upgrade path)

## Entrypoints verified (real names/signatures, not guessed)

**Build/reprocess entrypoint — `tasks.pipeline_tasks.build_pipeline_chain(job_id: str)`**
Returns a Celery `chain(pipeline_ingest.s(job_id), pipeline_analyze.s(), pipeline_finalize.s())`;
caller does `.apply_async()`. This is the ONLY place in the codebase that
re-executes `track_surface.builder.build_track_surface` (via `pipeline/
stages/s10d_surface.py::run_surface_build`, called from the analyze stage) —
verified by grepping every caller of `run_surface_build`/`build_track_surface`
(only `pipeline/orchestrator.py` calls it). There is no lighter "resurface
only" entrypoint. `builder.build_track_surface` itself calls
`resolve_canonical_via_pg(track_id)` then `load_gt(canonical_id)` (lines
~194 of `track_surface/builder.py`) — confirming the GT is consumed at BUILD,
not at racing-line-solve time.

Two real, already-shipped callers of `build_pipeline_chain` were used as the
verified wiring pattern (not invented):
- `ops/reprocess_day13_celery.py` (pre-existing in this repo's git status) —
  manual reprocess of specific sessions: `PipelineContext.create(redis_client,
  job_id, workspace_id, session_id, file_path)` → seed `pipeline:meta:{job_id}`
  in Redis → `build_pipeline_chain(job_id).apply_async()`.
- `web/routes/jobs.py::retry(job_id)` — the **existing "rerun this session
  from scratch" API endpoint**: looks up the original `ingestion_jobs` row
  (`tasks.job_registry.get_job(conn, job_id, workspace_id) → dict`), mints a
  new `job_id = uuid.uuid4().hex`, INSERTs a copied `ingestion_jobs` row
  (required — `pipeline_ingest`'s `_update_job_progress` UPDATEs an existing
  row, it does not upsert), seeds `PipelineContext.create(...)`, copies
  `pipeline:meta:{old}` → `pipeline:meta:{new}`, then dispatches
  `build_pipeline_chain(new_job_id).apply_async()`.

`onboarding/reprocess.py::_dispatch_build_reprocess(conn, session_ref)`
mirrors `retry()` verbatim: `session_ref` is treated as an existing
`ingestion_jobs.job_id` (confirmed: `web/routes/jobs.py::_sanitize_job`'s
comment "`session_id` (equal to `job_id` — set at upload time)" — session_id
and job_id are the same value at upload). It reads `workspace_id`/`file_path`
via a raw `%(name)s`-param SELECT on `ingestion_jobs` (no workspace filter —
this runs off `get_maint_connection`, an admin/operator path, not a
tenant-scoped web request), copies the row under a fresh job_id, seeds
`PipelineContext.create(redis_client=..., job_id=new_job_id, workspace_id=str(...),
session_id=new_job_id, file_path=...)`, copies `pipeline:meta:*` best-effort,
then `build_pipeline_chain(new_job_id).apply_async()`.

**`compute_racing_lines` — verified signature**
`tasks/racing_line_tasks.py:227` — `compute_racing_lines(track_id: str,
vehicle_class: str = "generic") -> dict`, a Celery task (`queue="pipeline"`,
`soft_time_limit=600`). Enqueued via `.apply_async((track_id, vehicle_class),
countdown=...)`.

**`session_ref` → `track_id` resolution**
`sessions.track_id` (the same column every session-scoped repo in this
codebase keys on — `web/repos/session_repo.py`, `db/queries.py`,
`cross_session.py`): `SELECT track_id FROM sessions WHERE session_id =
%(session_id)s`.

**`tracks.canonical_id` — verified column/table**
`track_surface/gt_loader.py::resolve_canonical_via_pg` (the reader half,
migration 060) does `SELECT canonical_id FROM tracks WHERE track_id =
%(t)s`. F4 is the writer half: `UPDATE tracks SET canonical_id =
%(canonical_id)s WHERE track_id = %(track_id)s` — same raw-cursor +
`conn.commit()` pattern as `resolve_canonical_via_pg` and
`onboarding.bless_service._write_audit`. (`web/repos/track_repo.py::
upsert_track` was checked and rejected for this — its SQL param set has no
`canonical_id` column at all; it's for fingerprint-based track creation, not
this bridge.)

## What was built

`telemetry_tool/onboarding/reprocess.py` (374 lines) —
`reprocess_after_bless(*, track_key, canonical_id, session_refs,
vehicle_classes, conn=None) -> None`:

1. **F4** `_apply_canonical_mapping` — per `session_ref`: resolve
   `sessions.track_id`, then idempotent `UPDATE tracks SET canonical_id`.
   Wrapped per-session; a resolve/DB failure for one session is logged and
   does not stop the rest. Not skipped when `track_key == canonical_id` —
   there is no such check at all; the mapping is always attempted per
   session, per the plan's instruction not to short-circuit on that
   comparison.
2. **F3** `_dispatch_builds` → `_dispatch_build_reprocess` per session_ref
   (see entrypoint section above). Wrapped per-session.
3. **Racing lines** `_enqueue_racing_lines` — dedupes `vehicle_classes` into
   a `set`, enqueues exactly one `compute_racing_lines.apply_async((track_key,
   vehicle_class), countdown=_RACING_LINE_REPROCESS_DELAY_S)` per distinct
   class. Uses `track_key` (not `canonical_id`) as the `track_id` arg,
   because `compute_racing_lines`/`load_track_model` key surfaces by the PG
   `track_id` sessions were built under, which is `track_key` here, not the
   GT's `canonical_id` string. Wrapped per-class.

Connection: `conn=None` opens `get_maint_connection()` and returns it in
`finally`; a caller-supplied `conn` is used as-is and never closed here
(verified by a dedicated test).

## Ordering guarantee — what's real vs. deferred

**Actually guaranteed:** F4 (canonical_id mapping) runs synchronously,
in-process, before ANY build is enqueued — so `resolve_canonical_via_pg`
already returns the new `canonical_id` by the time the first build-reprocess
task starts.

**NOT strictly guaranteed:** that every build-reprocess chain (F3, async,
unbounded duration — the verified `ops/reprocess_day13_celery.py` precedent
uses a 900s soft timeout per session) finishes before the racing-line
recompute runs. No chaining primitive spanning N independent, unknown-length
Celery chains was available to use safely: naively concatenating multiple
`build_pipeline_chain(...)` chains with a trailing `compute_racing_lines.si(...)`
risks a later session's `pipeline_ingest.s(job_id)` receiving the prior
chain's return value as a spurious extra positional argument (celery `.s()`
partials + return-value forwarding don't compose safely across
independently-built sub-chains) — untestable against a live broker in this
environment, so deliberately not attempted.

**What's implemented instead:** the racing-line enqueue carries a
30-minute `countdown` (`_RACING_LINE_REPROCESS_DELAY_S`, vs. the existing
`pipeline/orchestrator.py::_RACING_LINE_DEBOUNCE_S = 30` used for the
synchronous single-request pipeline path — 30s would be far too short for
an async multi-minute rebuild chain) — a best-effort head start, not a
guarantee. **Real correctness is backstopped by
`tasks.racing_line_tasks.compute_all_racing_lines`**, the existing nightly
beat task that re-solves every track with surface data and is idempotent
(skips a condition whose grip-snapshot hash hasn't changed) — if the delayed
compute races ahead of a slow build, the next nightly beat run corrects it.
This is explicitly deferred to the deploy gate, per the task brief; it is not
an oversight.

## Tests

`telemetry_tool/tests/test_onboarding/test_reprocess.py` — 9 cases, all
mocked (no live PG/Celery/Redis needed):
- canonical_id UPDATE issued once per session's track, correct params
  (capturing fake connection, no PG).
- session with no resolvable track_id → no UPDATE, no commit.
- a resolve/UPDATE exception for one session is swallowed; the other
  session's UPDATE still lands.
- build-reprocess (`_dispatch_build_reprocess`, mocked) called exactly once
  per session_ref, in order, with `(conn, session_ref)`.
- a build-reprocess exception for one session is swallowed; all three
  sessions are still attempted.
- `compute_racing_lines.apply_async` deduped to exactly one call per
  distinct `(track_key, vehicle_class)` even with repeated classes across
  sessions; correct `countdown`.
- a `compute_racing_lines.apply_async` exception for one class is swallowed;
  the other class is still enqueued.
- `conn=None` → `get_maint_connection()`/`return_pg_connection()` used,
  connection returned exactly once.
- caller-supplied `conn` is never passed to `return_pg_connection`.

`python -m pytest tests/test_onboarding/test_reprocess.py -v` → **9 passed**.
`python -m pytest tests/test_onboarding/ -q` → **100 passed, 5 skipped**
(skips are the pre-existing real-PG tests from Tasks 4/5, gated on
`TELEMETRY_PG_URL`, unset here — no regression).

## Concerns / notes for later tasks

- `_dispatch_build_reprocess`'s real DB/Redis/Celery wiring (the
  `ingestion_jobs` lookup + row copy, `PipelineContext.create`,
  `build_pipeline_chain(...).apply_async()`) is verified by code-reading
  against `web/routes/jobs.py::retry()` and `ops/reprocess_day13_celery.py`,
  but has NOT been exercised against a live Postgres/Redis/Celery broker —
  per the task brief, that's deferred to the deploy gate. In particular:
  confirm in a real environment that `session_ref` values produced by the
  onboarding trigger (Task 13, not yet built) really are `ingestion_jobs.
  job_id` values (this holds for normal uploads per `_sanitize_job`'s
  documented invariant, but Task 13's actual call site should be checked
  once written).
- The 30-minute racing-line delay is a guess tuned to the ops-script's
  900s-per-session soft timeout with margin for multiple sessions; if the
  real deploy-gate run shows builds routinely taking longer, raise
  `_RACING_LINE_REPROCESS_DELAY_S` accordingly, or wire an explicit
  "all builds acked" signal instead.
- `reprocess.py` is 374 lines, well under the 500-line cap.
