# Track Onboarding Loop — Ops Runbook

Automated version of "onboard a new track." When a session's pipeline can't
find ground-truth (GT) boundary geometry for its track, the loop auto-drafts
a boundary (SAM2 satellite pass, falling back to a GPS-derived centerline),
emails an operator a one-shot annotator link, and — once the operator
corrects and submits the draft — blesses the correction into the runtime GT
store and re-drives the sessions that were waiting on it.

This is a different (and complementary) path from
`docs/runbooks/track-geometry-factory-bless.md`, which documents the
original manual operator-local `trackreco-main` → `bless_gt.py` flow. That
manual flow still exists and still works; this loop automates the
trigger → draft → notify half of it and reuses the same fail-closed
validation gates (`bless_geometry`, `run_geometry_gates`) for the actual
install.

## 1. What the loop does

A pipeline build that can't resolve GT for its track (`pipeline/stages/
s10d_surface.py`, gated on `is_operator_run=True` — see §6) calls
`onboarding.service.record_missing_geometry`, which upserts a row in
`track_onboarding_requests` (migration `081_track_onboarding_requests`) and
enqueues `tasks.onboarding_tasks.draft_and_notify` on the `onboarding` Celery
queue. That task drafts a boundary, saves it, mints a signed one-shot token,
and emails the operator an annotator link. The operator corrects the draft
in the annotator UI and submits; `POST /api/v1/onboarding/save` runs the
submission through `onboarding.bless_service.bless_geometry` and, on
success, kicks off reprocessing (§7).

**State machine** (`track_onboarding_requests.status`):

```
requested → drafting → drafted / drafted_gps_only → emailed → blessed
                ↕ (validation/exception)
           draft_failed
```

- `requested` — row created (or an additional session attached to an
  already-open request); not yet claimed for drafting.
- `drafting` — claimed by a worker (`repo.claim_for_drafting`, a
  compare-and-set: only fires from `requested` or `draft_failed`).
- `drafted` — SAM2 satellite draft succeeded and was saved.
- `drafted_gps_only` — SAM2 draft unavailable/failed; fell back to the
  GPS-derived centerline draft (`draft.gps_only_draft`).
- `draft_failed` — bbox invalid or drafting raised; `error` column set;
  reclaimable from this state.
- `emailed` — operator notification sent (`emailed_at` set); only reached
  once, guarded by `emailed_at IS NULL` so a request is never re-emailed.
- `blessed` — terminal. `repo.set_status`/`claim_for_drafting`/
  `reset_for_retry` all refuse to touch a row once `status = 'blessed'`
  (`WHERE status <> 'blessed'` on every write).
- **Reconcile path**: `reconcile_onboarding` (§3) resets a stale,
  never-emailed row (`emailed_at IS NULL`, untouched 60+ minutes) back to
  `requested` and re-enqueues `draft_and_notify` — the only place
  `draft_failed`/stuck-`drafting` rows get auto-retried.

A track can only be re-onboarded (a fresh `requested` row) once its prior
request reaches `blessed` — enforced by the partial unique index
`ux_onboarding_open(track_key) WHERE status <> 'blessed'`.

## 2. Required env / config

| Var | Purpose | If unset |
|---|---|---|
| `ONBOARDING_TOKEN_SECRET` | HMAC-SHA256 secret signing the one-shot annotator token (`onboarding.tokens`). | **Fails closed**: `tokens.mint`/`tokens.verify` both raise `TokenError` immediately — no draft email can ever go out, and no `/save` can ever be authorized. Never falls back to a default secret. |
| `ONBOARDING_TOKEN_TTL_HOURS` | Token lifetime in hours. | Falls back to a **default of 72 hours** (`tokens._DEFAULT_TTL_HOURS`); also falls back on an unparseable value. |
| `ONBOARDING_OPERATOR_EMAIL` | Recipient of the draft-ready notification and the `reviewed_by` identity stamped by the web `/save` route (`onboarding:<email>`). | `KeyError` inside `draft_and_notify` / the `/save` route — read via `os.environ[...]` (no default), so drafting/blessing via the web path breaks hard if unset. |
| `ANNOTATOR_HOST` | Base URL of the annotator webapp; the emailed link is `{ANNOTATOR_HOST}/?req=<id>#token=<raw_token>`. | Same as above — `KeyError` inside `draft_and_notify`, read with no default. |
| `GT_RUNTIME_DIR` | Durable, writable directory for blessed runtime GT (see §4). | `bless_geometry` explicitly refuses and returns a `gt_runtime_dir_unset` rejection ("refusing to install (fail-closed)") — no install happens. |
| `ONBOARDING_DRAFT_DIR` | Where auto-drafted (pre-bless) geojson files are written/read (`draft.save_draft`/`load_draft`). | Falls back to `{GT_RUNTIME_DIR}/../onboarding_drafts` if `GT_RUNTIME_DIR` is set, else the OS temp dir (`lap_onboarding_drafts`) — i.e. drafts land somewhere non-durable unless one of the two is set. |
| `ONBOARDING_TRACKRECO_DIR` | Path override for the sibling `trackreco-main` checkout (SAM2 draft script location). | Falls back to a hardcoded local path (`C:\Users\Admin\Documents\Telemetry\Analysis\trackreco-main`) that only exists on the dev machine; on any other host, `sam2_draft` logs "trackreco-main checkout not found" and returns `None`, so drafting degrades to GPS-only (never raises). |
| `ONBOARDING_OPERATOR_RUN` | Fallback operator signal for `PipelineContext.create` when its `is_operator_run` kwarg isn't threaded through explicitly (ad-hoc ops scripts/CLIs). `"1"` → `True`. | Defaults to unset → `False`; a normal end-user upload never resolves to operator-run on its own (see §6). |

None of these have secret values documented here — reference names only;
set actual values via the deploy environment / secrets manager.

## 3. Celery topology

- **Queue**: `onboarding`, both via the task decorator (`queue="onboarding"`
  on `draft_and_notify` and `reconcile_onboarding` in
  `telemetry_tool/tasks/onboarding_tasks.py`) and belt-and-braces via
  `task_routes` in `telemetry_tool/celery_app.py`
  (`"tasks.onboarding_tasks.*": {"queue": "onboarding"}`).
- **The worker MUST consume this queue explicitly** — it is not part of the
  `default` or `pipeline` queues any other worker pool already listens on:
  ```bash
  celery -A <app> worker -Q onboarding,pipeline,default
  ```
  If no worker consumes `onboarding`, `draft_and_notify` and
  `reconcile_onboarding` messages sit unconsumed forever — no draft, no
  email, no reconcile.
- **Beat**: `reconcile-onboarding` in `celery_app.py`'s `beat_schedule`,
  cadence **every 1800s (30 minutes)**, dispatched onto the `onboarding`
  queue. It calls `repo.find_stale_unemailed` (rows: `status <> 'blessed'`,
  `emailed_at IS NULL`, `updated_at` older than `_STALE_AFTER_MINUTES = 60`
  minutes) and, for each, `repo.reset_for_retry` (back to `requested`,
  clearing `draft_status`/`draft_path`/`token_jti`) then re-enqueues
  `draft_and_notify`. Per-id failures are caught and logged so one bad row
  never blocks the batch.
  - **Scope note**: this backstop only covers requests stuck *before* the
    first email goes out (worker crash between the `drafted`/`token_jti`
    write and the `emailed` write). It does **not** cover an
    already-emailed request whose token later expires — see §8.
- **SAM2 worker runtime contract**: `onboarding.draft.sam2_draft` shells out
  to `Analysis/trackreco-main/scripts/lap_track_to_draft.py` in a
  subprocess (`sys.executable`, so it must be runnable from the worker's own
  Python — the trackreco checkout is a sibling repo, not a package
  dependency of `lap_web`). It needs: the `trackreco-main` checkout present
  at `ONBOARDING_TRACKRECO_DIR` (or the hardcoded dev-machine fallback), that
  checkout's own dependencies (SAM2 weights/checkpoint, `trackreco_platform`
  importable) installed for whatever Python `sys.executable` resolves to on
  the worker host, and at least 10 GPS points in the session.
  **Absence degrades gracefully**: any failure mode here — missing
  checkout, missing deps, timeout, non-zero exit, unreadable/malformed
  output — is caught inside `sam2_draft` (never raises) and falls through
  to `gps_only_draft`, landing the request in `drafted_gps_only` instead of
  `drafted`. The loop still completes end-to-end; the draft is just a
  rougher, GPS-only centerline for the operator to correct instead of a
  SAM2 satellite trace.

## 4. Durable GT store

- `GT_RUNTIME_DIR` **must be a persistent, writable volume** — not
  ephemeral container storage. `bless_geometry` writes the corrected
  geojson there (`install_gt_geojson`) and then calls
  `track_surface.gt_loader.invalidate_gt_cache(canonical_id)`, so the new
  GT is picked up by the next `load_gt(...)` call **immediately, with no
  redeploy** (`gt_loader` consults `GT_RUNTIME_DIR` first, falling back to
  the git-baked `data/ground_truth/` corpus).
- **A redeploy re-seeds the baked GT corpus from the git image.**
  `GT_RUNTIME_DIR` content is runtime-only state — blessed geometry living
  there is **not** automatically committed to git. If the volume is lost
  (or a redeploy wipes/reprovisions it) before someone reconciles, blessed
  corrections silently revert to whatever (or nothing) is baked in git.
- **Manual reconcile-to-git step (must be done periodically by an
  operator)**: copy each blessed `gt_<canonical_id>.geojson` (and any
  `track_aliases.json` merge) out of `GT_RUNTIME_DIR` into the versioned
  corpus (`data/ground_truth/`) and commit, mirroring what
  `scripts/bless_gt.py` does for the manual flow
  (`docs/runbooks/track-geometry-factory-bless.md` Step 3-4). This gives
  the correction code-review + durability across redeploys instead of
  living only in the runtime volume.

## 5. Deploy-gate checklist

The dev environment for this feature had **no Postgres** — the checklist
below is where DB behavior gets validated for the first time. Do these in
order:

1. Apply migration `081_track_onboarding_requests` on prod: `alembic
   upgrade head`; confirm `alembic current` reaches
   `081_track_onboarding_requests (head)`.
2. Set `TELEMETRY_PG_URL` and run the PG-gated onboarding tests:
   ```bash
   cd telemetry_tool
   TELEMETRY_PG_URL=<prod-or-staging-pg-url> python -m pytest tests/test_onboarding -q
   ```
   Six tests are `@pytest.mark.skipif` guarded on `TELEMETRY_PG_URL` being
   unset and only run against a real PG: `test_repo.py`'s
   `test_pg_first_upsert_creates_one_row`,
   `test_pg_second_upsert_same_open_track_attaches_no_dup_refs` (the
   dedup-race coverage for `ux_onboarding_open`),
   `test_pg_claim_for_drafting_true_once_then_false`,
   `test_pg_find_stale_unemailed_and_reset_for_retry`,
   `test_pg_set_status_blessed_then_further_writes_refused`, plus one
   migration-shape check in `test_migration_081.py`. These exercise the
   real dedup/CAS SQL against actual PG, not mocks — do not skip this step.
3. Confirm the Celery worker pool is started with `-Q onboarding,...` (§3)
   — check worker startup logs/args, not just that *a* worker is running.
4. Set every env var in §2 in the deploy environment.
5. Confirm the `GT_RUNTIME_DIR` volume is mounted and persistent (survives
   a container restart/redeploy) — see §4.

## 6. Operator gating

Onboarding only ever triggers when `is_operator_run=True` is threaded down
to `pipeline/stages/s10d_surface.py`'s GT-miss hook
(`PipelineContext.is_operator_run`, default `False`). The only call sites
that set it `True` are:

- `POST /admin/jobs/<job_id>/retry` (`web/routes/admin/jobs.py`), gated by
  `@require_superadmin` + `@require_admin_role("root_admin", "sre_admin")`
  — a genuine authenticated-operator retry of an existing job.
- `onboarding.reprocess._dispatch_builds`'s internal bless-reprocess
  dispatcher (`reprocess.py`), which re-runs sessions that were waiting on
  a track that has just been blessed — GT already exists by then, so the
  hook is a no-op there; set for consistency, not because it's expected to
  fire.

Ordinary end-user session uploads never set it, so ordinary uploads never
trigger onboarding, even if their track has no GT. **To onboard a track
that genuinely lacks GT**, an operator/admin must retry an affected
session via the superadmin admin-retry route above (or run an ad-hoc script
with `ONBOARDING_OPERATOR_RUN=1`, §2) so the hook has a chance to fire.

## 7. Reprocessing / racing lines after a bless

`POST /api/v1/onboarding/save` → `bless_geometry` (success) →
`onboarding.reprocess.reprocess_after_bless`, which (best-effort, one
session's failure never aborts the rest):

1. Updates `tracks.canonical_id` for every waiting `session_ref`.
2. Re-dispatches the full ingest → analyze → finalize pipeline chain per
   session (`tasks.pipeline_tasks.build_pipeline_chain(...).apply_async()`
   — the same entrypoint `web/routes/jobs.py`'s manual `retry()` uses),
   which is the only place `build_track_surface`/`load_gt` re-executes and
   re-anchors the session onto the newly-blessed GT.
3. Enqueues exactly one `tasks.racing_line_tasks.compute_racing_lines` per
   distinct `(track_key, vehicle_class)`, delayed by
   `_RACING_LINE_REPROCESS_DELAY_S = 1800` (30 minutes) so the builds above
   get a head start before the racing-line solve reads their sidecars.

This 30-minute delay is a **heuristic, not a guarantee** — if a build takes
longer, the racing-line solve can still run against a stale sidecar. It's
backstopped by the nightly `nightly-racing-lines` beat
(`tasks.racing_line_tasks.compute_all_racing_lines`, daily 03:30 UTC on the
`pipeline` queue), so a session's `optimal_line` may not appear until that
next nightly run. This delay is **honesty-safe by design**: the tier system
refuses to emit `optimal_line` rather than serve one solved against
not-yet-anchored geometry — a missing line for a few hours is the intended
behavior, not a bug.

## 8. Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Operator never received the draft-ready email | Request's `status`/`draft_status`/`emailed_at`: `SELECT status, draft_status, error, emailed_at, updated_at FROM track_onboarding_requests WHERE id = '<request_id>';` (or filter by `track_key`) | If stuck pre-email (`emailed_at IS NULL`) and `updated_at` is 60+ minutes old, the next `reconcile_onboarding` beat tick (≤30 min) auto-resets and re-drives it — confirm the `onboarding` queue actually has a consuming worker (§3), since reconcile's re-enqueue is also a message on that queue. |
| Row stuck in `draft_failed` | Check the `error` column for the exception message. | Common cause: invalid `bbox`. Once the underlying issue is fixed, either wait for reconcile (only fires if also `emailed_at IS NULL` and stale) or manually re-drive: `repo.claim_for_drafting` requires status in `('requested','draft_failed')`, so calling `tasks.onboarding_tasks.draft_and_notify.delay(request_id)` again is safe and idempotent. |
| Row stuck in `drafting` indefinitely (worker died mid-task) | `updated_at` age vs the 60-minute reconcile threshold. | Same reconcile path as above once it crosses the threshold; `emailed_at` must still be `NULL` (it always is at this stage) for `reset_for_retry` to touch it. |
| Annotator link returns "Invalid or expired onboarding link" (generic 401 by design — never reveals which check failed) | Token TTL (`ONBOARDING_TOKEN_TTL_HOURS`, default 72h) vs `emailed_at`; whether the link was already used (`/save` revokes the `jti` on success, one-shot). | **There is no built-in resend/rotate endpoint for an already-emailed request** — `reconcile_onboarding`/`reset_for_retry` only ever touch rows where `emailed_at IS NULL`, so a request that was already emailed is never auto-reset just because its token later expired. To manually issue a fresh link: in a DB/python shell, clear `emailed_at` (`UPDATE track_onboarding_requests SET emailed_at = NULL, token_jti = NULL WHERE id = '<request_id>' AND status <> 'blessed';`) so the row is eligible for `repo.reset_for_retry`, then call `reset_for_retry` + `tasks.onboarding_tasks.draft_and_notify.delay(request_id)` (or wait for the next reconcile tick to pick it up). This is a manual DB operation today, not a self-service admin action — flagged as a gap, not a documented feature. |
| Bless succeeds but the correction "disappears" after a later deploy | `GT_RUNTIME_DIR` volume was not persistent, or the manual reconcile-to-git step (§4) was never done. | Re-bless from the operator's last-known-good export (if retained), or re-run the loop for that track; going forward, do the §4 reconcile-to-git step regularly so blessed corrections survive a redeploy. |
| `optimal_line` missing right after a bless | Reprocessing timeline (§7): builds take time, racing-line solve is delayed 30 min and may still race a slow build; full backstop is the next 03:30 UTC nightly `compute_all_racing_lines` run. | Not a bug by itself — check `track_geometry_audit` / the session's rebuilt sidecar `boundary_source` first to confirm the rebuild actually landed before assuming the solver is broken. |
