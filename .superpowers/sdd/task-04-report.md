# Phase-1 Task 4 report — onboarding/repo.py

## Scope
Read only the "### Task 4" section of
`docs/superpowers/plans/2026-07-06-track-onboarding-loop.md` plus the
"Global Constraints" header, and migration
`telemetry_tool/alembic/versions/081_track_onboarding_requests.py`.

## uuid generation
Followed the exact SQL given in the task brief: `gen_random_uuid()` inside
the `INSERT ... VALUES`. Verified this is consistent with the codebase --
migration 081's `id` column already has `server_default=sa.text("gen_random_uuid()")`,
and migration 051 (`device_pairings`) uses the same `gen_random_uuid()`
server-default pattern, confirming pgcrypto/pg13+ `gen_random_uuid()` is the
established convention for this table family (not Python-side `uuid.uuid4()`,
which is used elsewhere for non-PK ids like job ids / bundle ids).

## Migration column match
Cross-checked every column referenced in repo.py against 081's `upgrade()`:
`id, track_key, track_label, fingerprint, status, bbox, first_session_ref,
session_refs, session_count, draft_status, draft_path, token_jti, error,
created_at, updated_at, emailed_at, blessed_at`. All present, types match
(JSONB for fingerprint/bbox/session_refs, Text for the rest, Integer for
session_count, TIMESTAMP(tz) for created_at/updated_at/emailed_at/blessed_at).
No workspace_id (global table, matches migration docstring / 078/079
precedent).

## SQL shape (upsert_open_request)
Implemented verbatim per the brief:
- `ON CONFLICT (track_key) WHERE status <> 'blessed'` -- predicate restated
  to match the partial unique index `ux_onboarding_open` for Postgres
  conflict-target inference.
- jsonb dedup guard: `session_refs @> to_jsonb(%(session_ref)s::text)` OR
  `jsonb_array_length(...) >= 50` short-circuits the append so a repeated or
  retried `session_ref` never duplicates and the array is capped.
- `RETURNING id, (xmax = 0) AS created` -- `xmax=0` is the loser-vs-winner
  signal: `created=True` only on a genuine insert, `False` when the call
  attached to an existing open row (race-safe by construction, no
  app-level retry/lock needed).

## Functions delivered
- `upsert_open_request(conn, *, track_key, track_label, fingerprint, bbox, session_ref) -> tuple[str, bool]`
- `set_status(conn, request_id, new_status, **fields) -> bool` -- conditional
  `WHERE id=%(id)s AND status <> 'blessed'`; `**fields` restricted to a
  hardcoded whitelist (`_SETTABLE_FIELDS`) of the 081 columns minus
  id/track_key/status/created_at/updated_at; raises `ValueError` on any
  unlisted key so column names are never taken from unchecked input. JSONB
  columns (fingerprint/bbox/session_refs) get `json.dumps` + `::jsonb` cast
  automatically when the caller passes a dict/list.
- `claim_for_drafting(conn, request_id) -> bool` -- compare-and-set
  `status IN ('requested','draft_failed') -> 'drafting'`, `RETURNING id`;
  True iff a row came back.
- `get(conn, request_id) -> dict | None` -- selects all columns, decodes
  JSONB columns from string if the driver didn't auto-decode (mirrors
  `racing_line_repo.get_racing_lines`' dual dict/tuple row handling).

## Tests: ran vs skipped
`python -m pytest tests/test_onboarding/ -q` → **18 passed, 5 skipped**
(0.44s). The 5 skips are all `@_skip_no_pg` (4 in the new `test_repo.py`,
1 pre-existing in `test_migration_081.py`) -- expected, no local Postgres in
this environment.

Capturing-cursor tests (ran, load-bearing here since the race can't be
runtime-validated without PG) assert verbatim:
- `ON CONFLICT (track_key) WHERE status <> 'blessed'`
- the `@>` containment dedup guard + the 50-cap guard
- `(xmax = 0) AS created` / `RETURNING id, (xmax = 0) AS created`
- `set_status` emits `WHERE id = %(id)s AND status <> 'blessed'` and rejects
  an unwhitelisted field with `ValueError`
- `claim_for_drafting` emits `status IN ('requested', 'draft_failed')` and
  `RETURNING id`

PG tests (written, will run against a real scratch DB elsewhere): first
upsert created=True/one row; second upsert same open track_key attaches
(created=False, session_refs has both refs, repeat session_ref doesn't
duplicate, session_count increments correctly); claim_for_drafting True once
then False; set_status to 'blessed' then a later set_status refused
(returns False), row still shows status='blessed'.

Also ran `python -m pytest --collect-only -q` across the whole
`telemetry_tool/` tree to check for collection regressions: 6715 tests
collected with 2 pre-existing, unrelated errors (an assertion failure in
`test_pipeline_physics.py` about a pipeline docstring, and a name collision
between `tests/test_track_surface.py` and `tests/test_track_surface/`) --
both present before this task's changes and untouched by it.

## Concerns
- `set_status`'s whitelist deliberately excludes `session_refs`/
  `session_count` from ad-hoc external combination with `status` changes in
  the same call as the upsert path (those are only ever written by
  `upsert_open_request`'s own SQL) -- included them in the whitelist anyway
  since the interface said "additional SET columns" generically and a later
  task (e.g. reconciliation) may legitimately need to correct them; flagging
  in case a tighter whitelist was intended.
- The brief's Task 4 section (in my prompt) doesn't mention
  `expect_not_blessed` as a `set_status` kwarg (unlike the plan doc's
  slightly fuller Task 4 interface section, which shows
  `set_status(conn, request_id, new_status, *, expect_not_blessed=True, **fields)`).
  I followed the exact signature given in my task brief:
  `set_status(conn, request_id, new_status, **fields) -> bool` with no
  `expect_not_blessed` parameter -- the `WHERE status <> 'blessed'` guard is
  unconditional (matches "conditional UPDATE" wording either way). If a
  later task needs to bypass that guard for some as-yet-unspecified reason,
  this signature would need revisiting; I did not add the extra kwarg since
  it wasn't in my instructions and no caller in this task exercises it.
- PG-path behaviour (real dedup/race/idempotency) is unverified in this
  environment by design (no local Postgres) -- flagged per the task
  instructions as expected, not a gap I introduced.
