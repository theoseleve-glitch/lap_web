# Final-review fix batch B — M1/M2/M3 (Track Onboarding Loop)

Worktree: `C:\Users\Admin\lap_web-wt-onboarding` (branch `feat/track-onboarding-loop`).
Base HEAD: `7363f9e`.

All three fixes followed strict TDD: test added first (confirmed red), then
the minimal implementation, then confirmed green.

## M1 — operator-run env fallback removed

**File**: `telemetry_tool/pipeline_context.py`

`PipelineContext.create`'s `is_operator_run` resolution used to fall back to
`os.environ.get("ONBOARDING_OPERATOR_RUN") == "1"` whenever the caller left
the kwarg `None`. On a shared Celery worker that also processes end-user
uploads, that env var being set would silently turn EVERY upload into an
operator run, defeating the operator-only invariant by config.

Fix: removed the env-var fallback entirely. `is_operator_run` now comes
*only* from the explicit `create(...)` argument, defaulting to `False`
(changed the parameter type from `Optional[bool] = None` to `bool = False`
since there is no more `None`-resolution branch). Removed the now-unused
`import os`. Updated the attribute/parameter docstrings to state there is no
env fallback and name the two legitimate `True` call sites
(`web/routes/admin/jobs.py`'s admin-retry route, `onboarding/reprocess.py`'s
bless-reprocess dispatcher).

No test previously exercised `ONBOARDING_OPERATOR_RUN` (grepped — the only
hit was the implementation itself), so no test needed updating for the
removal.

**New tests** — `telemetry_tool/tests/test_pipeline_context.py`,
`TestPipelineContextIsOperatorRunEnvFallbackRemoved`:
- `test_unset_env_no_explicit_flag_is_false`
- `test_env_var_set_does_not_make_it_true` (sets `ONBOARDING_OPERATOR_RUN=1`,
  asserts `is_operator_run` is still `False` — this is the one that failed
  red before the fix)
- `test_explicit_true_still_works`

**Docs**: `docs/runbooks/track-onboarding.md` — removed the
`ONBOARDING_OPERATOR_RUN` row from the §2 env table; reworded §6 (Operator
gating) to state `is_operator_run` has no env-var opt-in and is produced
ONLY by the superadmin admin-retry route and the internal bless-reprocess
dispatcher.

## M2 — "never raises" overclaim on missing env fixed

**File**: `telemetry_tool/tasks/onboarding_tasks.py::_run_draft_and_notify`

Previously, `os.environ["ANNOTATOR_HOST"]` / `os.environ["ONBOARDING_OPERATOR_EMAIL"]`
were read unguarded, and `tokens.mint(...)` was called outside any try —
either raising (`KeyError` or `tokens.TokenError`) would propagate out of the
task, contradicting the module's "never raises / best-effort" docstring:
Celery would retry then dead-letter, leaving the request stuck in
`drafting` forever.

Fix:
- Wrapped `tokens.mint(request_id)` in `try/except tokens.TokenError`; on
  failure, `repo.set_status(..., "draft_failed", error=...)` and return
  `{"ok": False, "error": "mint_failed"}` — no raise.
- Wrapped the `ANNOTATOR_HOST`/`ONBOARDING_OPERATOR_EMAIL` env reads (still
  only evaluated when about to build/send the email, i.e. inside the
  `emailed_at is None` branch) in `try/except KeyError`; on failure, same
  `draft_failed` treatment, `{"ok": False, "error": "missing_env"}`, and
  `send_email_async` is never called.
- Happy path and the email-once idempotency guard (`emailed_at IS NULL`
  re-check) are untouched.
- Softened the function docstring: it no longer claims "Never raises" for
  *everything* — it now lists the specific known failure modes handled
  (claim race, invalid bbox, drafting error, mint/TokenError failure,
  missing annotator env) and explicitly notes this does NOT cover
  infrastructure-level exceptions from `repo.*`/`save_draft`, which can
  still raise into Celery's normal retry path.

**New tests** — `telemetry_tool/tests/test_onboarding/test_onboarding_tasks.py`:
- `TestMissingRequiredEnvAtEmailTimeMarksDraftFailed`:
  - `test_missing_operator_email_marks_draft_failed_no_send`
  - `test_missing_annotator_host_marks_draft_failed_no_send`
- `TestMintFailureMarksDraftFailed`:
  - `test_missing_token_secret_marks_draft_failed_no_email` (uses the REAL
    `onboarding.tokens.mint`, not the mocked fixture, so a genuine
    `TokenError` is exercised)

All three assert `result == {"ok": False, "error": ...}`, the final
`repo.set_status` call is `"draft_failed"`, and `send_email_async.delay` is
never called. Confirmed red (real `KeyError`/`TokenError` propagating out of
`_run_draft_and_notify`) before the fix.

**Docs**: `docs/runbooks/track-onboarding.md` §2 — updated the
`ONBOARDING_OPERATOR_EMAIL`/`ANNOTATOR_HOST` rows: `_run_draft_and_notify`
now transitions to `draft_failed` instead of raising a `KeyError`; noted the
`/save` route (`web/routes/onboarding_routes.py`) still reads
`ONBOARDING_OPERATOR_EMAIL` unguarded and can still `KeyError` there (out of
scope for this fix — M2 was scoped to `_run_draft_and_notify` only).

## M3 — alias-registry read-modify-write race fixed

**New file**: `telemetry_tool/onboarding/gt_install.py`
**Modified**: `telemetry_tool/onboarding/bless_service.py` (499 -> 393 lines)

`install_gt_geojson` (plus `_load_aliases_registry`/`_save_aliases_registry`/
`_check_canonical_id_format`/`InstallError`) were extracted out of
`bless_service.py` — which was at its 500-line file-size budget — into a new
module, `onboarding/gt_install.py`. `bless_service.py` re-imports
`InstallError`/`install_gt_geojson`/`_check_canonical_id_format` from there
(still exported in its own `__all__`), so **no external call site needed to
change** — `scripts/bless_gt.py`'s `from onboarding.bless_service import
InstallError as BlessError` / `install_gt_geojson` still resolves to the
exact same function object (verified: `onboarding.bless_service.install_gt_geojson
is scripts.bless_gt.install_gt_geojson` -> `True`).

**Lock primitive chosen**: no `filelock`/`portalocker` dependency exists
anywhere in this codebase (grepped). This codebase already has a proven,
in-house cross-process file lock for exactly this class of problem —
`parquet_manager._FileLock`, using `os.open(path, O_CREAT | O_EXCL | O_WRONLY)`
in a spin-with-timeout loop, lock released in `__exit__` (also on exception).
Rather than import that *private*, underscore-prefixed class across
unrelated modules (fragile if `parquet_manager` ever refactors it away),
`gt_install.py` implements the same small (~30-line), well-understood idiom
locally as `_RegistryFileLock` (default timeout 30s, 50ms poll interval),
guarding a sibling `<aliases_file>.lock` file (e.g. `track_aliases.json.lock`).

`install_gt_geojson` now wraps the alias-registry load -> duplicate-id check
-> geojson copy -> mutate -> save as ONE critical section inside
`with _RegistryFileLock(aliases_file): ...` — exactly the load->mutate->save
sequence the finding called out, plus the geojson copy (safe to include:
`dest` is unique per `canonical_id`, and it keeps the copy and the registry
write from ever landing in an inconsistent order relative to a concurrent
bless of a different track).

**New tests** — `telemetry_tool/tests/test_onboarding/test_gt_install.py`:
- `TestTwoSequentialInstallsDifferentTracksBothSurvive`:
  - `test_both_aliases_present_after_two_installs` — installs `track_a` then
    `track_b` into the same `aliases_file`; asserts both entries present
    (the scenario the race would have corrupted).
  - `test_no_leftover_lock_file_and_second_install_still_succeeds` — asserts
    the sibling `.lock` file is gone after a successful install (proving
    release-on-success, not just acquire), and that a second install
    immediately afterward still succeeds (proving the lock isn't left
    stuck).
- `TestRegistryFileLockPrimitive` (direct test of the primitive itself, since
  true multi-process concurrency isn't practical to simulate in-process):
  - `test_lock_acquired_then_released` — lock file exists inside the `with`
    block, gone after.
  - `test_held_lock_blocks_a_second_acquire_until_timeout` — pre-creates the
    lock file (simulating another process holding it) and asserts a second
    acquire raises `_RegistryLockTimeout` after a short (0.2s) timeout.

## Test commands + output

```
cd telemetry_tool
python -m pytest tests/test_onboarding/ -q
# 182 passed, 7 skipped (7 skips are the pre-existing PG-gated tests,
# @pytest.mark.skipif on TELEMETRY_PG_URL being unset -- unrelated to this fix)

python -m pytest tests/test_track_surface/test_gt_validate.py -q
# 10 passed (CLI bless_gt.py behavior unchanged)

python -m pytest tests/test_onboarding/ tests/test_pipeline_context.py tests/test_track_surface/test_gt_validate.py -q
# 211 passed, 7 skipped

python -c "import onboarding.bless_service, scripts.bless_gt"
# (run from repo root with telemetry_tool/ and repo root both on sys.path,
# matching scripts/bless_gt.py's own sys.path setup) -- clean import, no error
```

A full `telemetry_tool/` suite run (`python -m pytest tests/ -q`) was also
kicked off to confirm nothing else regressed; `tests/test_track_surface.py`
(a file, distinct from the `tests/test_track_surface/` directory) hits a
pre-existing, unrelated pytest module-name collision after a stale
`__pycache__` — not caused by this change (confirmed by grepping: neither
file references `pipeline_context`, `onboarding_tasks`, `bless_service`, or
`gt_install`).

## Residual concerns

- M2 only fixed `_run_draft_and_notify`. `web/routes/onboarding_routes.py`'s
  `/save` route still reads `os.environ['ONBOARDING_OPERATOR_EMAIL']`
  unguarded (bare `KeyError` possible) — flagged in the runbook, out of
  scope for this batch (task only named `_run_draft_and_notify`).
- M3's lock is advisory (cooperative) — it only protects code paths that go
  through `install_gt_geojson`. A process editing `track_aliases.json`
  directly (e.g. a manual operator edit) would not be serialized against
  it. This matches the finding's scope (the bless install path only).
- M3's lock primitive is a small, deliberately independent re-implementation
  of `parquet_manager._FileLock`'s idiom rather than a shared import — two
  near-identical ~30-line lock classes now exist in the codebase. Consider
  a future consolidation into one shared utility if a third call site for
  this pattern appears.
