# Task 13c — Worker discovery, queue routing, reconcile beat

## Discovery mechanism: explicit `include=[...]` (not autodiscover)

`telemetry_tool/celery_app.py`'s `make_celery()` builds `Celery("telemetry_tool", ...,
include=[...])` with an explicit, hand-maintained list of task modules (`tasks.pipeline_tasks`,
`tasks.batch_tasks`, ... `tasks.racing_line_tasks`, `admin.metrics_collector`). There is no
`celery.autodiscover_tasks()` call anywhere in this codebase — every task module must be added to
this list by hand or a real worker process never imports it and `draft_and_notify` (and now
`reconcile_onboarding`) stay invisible to `celery -A telemetry_tool.celery_app worker`, even though
they run fine directly under pytest (which imports the module explicitly).

Added `"tasks.onboarding_tasks"` to that list, alongside its sibling `"tasks.racing_line_tasks"`.

## Queue routing: dual registration (task-level `queue=` kwarg **and** `task_routes`)

`tasks/onboarding_tasks.py`'s `draft_and_notify` already had `queue="onboarding"` set directly on
its `@_celery_app.task(...)` decorator (from Task 10). Inspecting `celery_app.py`'s existing
`task_routes` dict showed the codebase does **not** rely purely on that per-task kwarg + a worker's
`-Q` flag: `tasks.racing_line_tasks.*` — which *also* sets `queue="pipeline"` on its own decorator
— is additionally listed in `task_routes` as `{"queue": "pipeline"}`. That is the established
"belt-and-braces" pattern for every custom (non-`"default"`) queue in this codebase, so I mirrored
it exactly rather than inventing a new mechanism:

```python
"tasks.onboarding_tasks.*": {"queue": "onboarding"},
```

added next to the `tasks.racing_line_tasks.*` entry. `reconcile_onboarding`'s beat entry also pins
`"options": {"queue": "onboarding"}` for the same reason `nightly-racing-lines` pins
`"options": {"queue": "pipeline"}`.

**Operational note**: a real worker still needs `-Q onboarding,default,pipeline,...` (or whatever
superset is already run) to actually *consume* from the `onboarding` queue — routing only decides
which queue a task's messages land in, not who drains it. This is unchanged worker-deployment
plumbing, called out here per the Task 10 report's original punt.

## Reconcile beat: `reconcile_onboarding`, every 30 minutes

New task `tasks.onboarding_tasks.reconcile_onboarding` (registered with the same
try-Celery-else-plain-function idiom as `draft_and_notify`, `queue="onboarding"`, `acks_late=True`).
Registered in `celery_app.py`'s `beat_schedule` as `"reconcile-onboarding"` with `"schedule": 1800`
(30 minutes in seconds — same units `nightly-racing-lines`/`biweekly-retrain-and-reprocess` etc.
use for their `crontab`/integer schedules) and `"options": {"queue": "onboarding"}`.

### Guards (why a stuck row can never be double-driven or clobber a finished one)

Two new `onboarding/repo.py` functions, both following the existing whitelisted-column /
parameterized-SQL conventions in that file:

- **`find_stale_unemailed(conn, older_than_minutes=60)`** — `SELECT id ... WHERE status <>
  'blessed' AND emailed_at IS NULL AND updated_at < now() - (%(mins)s || ' minutes')::interval`.
  Handles both dict-keyed rows (tests) and tuple rows (`PgConnectionWrapper`), matching
  `_row_to_dict`'s dual-shape handling elsewhere in the file.
- **`reset_for_retry(conn, request_id)`** — `UPDATE ... SET status='requested',
  draft_status=NULL, draft_path=NULL, token_jti=NULL, updated_at=now() WHERE id=%(id)s AND
  status <> 'blessed' AND emailed_at IS NULL`. The `WHERE` clause is the load-bearing guard: a
  blessed row, or one that raced ahead and got emailed between `find_stale_unemailed` and this
  call, matches zero rows (`rowcount == 0` → returns `False`) and is left untouched — never
  silently reset out from under a request that already finished.

`reconcile_onboarding`'s logic (`_run_reconcile_onboarding`, the plain Celery-free helper): for each
stale id, `reset_for_retry` then `draft_and_notify.delay(id)` **only if** the reset actually
happened. Each id is wrapped in its own `try/except Exception: logger.exception(...)` so one id's
failure (bad row, broker hiccup on `.delay`) can never abort the rest of the batch — mirrors the
"never raises into the pipeline" contract `_run_draft_and_notify` already documents. Returns
`{"ok": True, "found": <n>, "reset": <n>}`.

## Tests

- `tests/test_onboarding/test_repo.py` — capturing-cursor SQL-shape tests for both new repo
  functions (`status <> 'blessed'`, `emailed_at IS NULL`, the interval expression, params; the
  `UPDATE ... SET ... WHERE ... status <> 'blessed' AND emailed_at IS NULL` shape and NULL-outs;
  both dict-row and tuple-row `find_stale_unemailed` decoding; rowcount=0 → False). Also added one
  real-PG round-trip test (`test_pg_find_stale_unemailed_and_reset_for_retry`, `@_skip_no_pg`) that
  backdates `updated_at`, confirms staleness detection + reset, then blesses the row and confirms
  `reset_for_retry` refuses it. Extended the shared `_CapturingCursor`/`_CapturingConn` fakes with
  `fetchall_result` support (backward compatible — existing tests only used `fetchone`).
- `tests/test_onboarding/test_reconcile.py` (new) — mocks `onboarding_tasks.repo` and
  `onboarding_tasks.draft_and_notify`, calls `_run_reconcile_onboarding(conn)` directly. Covers: 2
  stale ids reset + re-driven; custom `older_than_minutes` forwarded; no stale ids is a no-op; a
  `reset_for_retry` `False` result skips the enqueue; an exception from `reset_for_retry` on one id
  doesn't stop the others; an exception from `draft_and_notify.delay` itself also doesn't stop the
  others. A `TestCeleryAppWiring` class asserts directly against `make_celery()`'s built config
  (building the app has no live-broker side effects, so no need for a lighter proxy check): the
  `include` list contains `"tasks.onboarding_tasks"`, `task_routes` has the `onboarding` queue
  entry, `beat_schedule["reconcile-onboarding"]` has task name / 1800s schedule / queue option, and
  — importing the real `tasks.onboarding_tasks` module against the real module-level `celery_app.celery`
  app — both `draft_and_notify` and `reconcile_onboarding` show up in `celery_app.celery.tasks`,
  confirming discovery actually works end-to-end (not just that the include list has the string in
  it).

## Verification

```
python -m pytest tests/test_onboarding/ tests/test_celery_app.py -q
# 190 passed, 6 skipped (all PG-gated) in ~3.3s
python -c "import tasks.onboarding_tasks"   # imports cleanly
```

Also ran `pytest -q -k "celery or racing_line_tasks or onboarding"` (ignoring two pre-existing,
unrelated collection failures in `test_pipeline_physics.py` and `tests/test_track_surface.py` —
confirmed via `git stash` that both fail identically on the pre-Task-13c HEAD, i.e. they are not a
regression from this change): 218 passed, 8 skipped, 0 failed.

## Concerns / follow-ups (not in scope here)

- The `-Q` flag(s) actually passed to the deployed Celery worker process are outside this repo (ops
  config) — confirm the worker's `-Q` includes `onboarding` before this ships, or routed messages
  will queue forever unconsumed. Same caveat already existed for `draft_and_notify` since Task 10;
  this task doesn't change or fix that, just documents it clearly at the routing site.
- `_STALE_AFTER_MINUTES = 60` is a reasonable default given the beat runs every 30 minutes (so a
  row gets at most ~2 reconcile passes before being eligible), but wasn't specified by the task
  description as configurable via env var — left as a module constant, easy to promote to an env
  var later if ops wants to tune it without a redeploy.
