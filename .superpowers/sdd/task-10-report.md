# Task 10 report — `tasks/onboarding_tasks.py` (Celery `draft_and_notify`)

## What was built

- `telemetry_tool/tasks/onboarding_tasks.py` (new): Celery task `draft_and_notify(request_id)` plus the Celery-free helper `_run_draft_and_notify(request_id, conn)` that holds the real flow.
- `telemetry_tool/tests/test_onboarding/test_onboarding_tasks.py` (new): 7 tests, all mocking `repo`, the `draft` module functions, `tokens`, and `send_email_async` at the `onboarding_tasks` module namespace.

## Celery registration + queue mechanism (copied from `tasks/email_tasks.py`)

Copied the exact guarded-import idiom:

```python
_USE_CELERY = False
try:
    from celery_app import celery as _celery_app
    _USE_CELERY = True
except Exception:
    _celery_app = None

if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(name="tasks.onboarding_tasks.draft_and_notify",
                       queue="onboarding", acks_late=True, max_retries=3)
    def draft_and_notify(request_id): ...
else:
    def draft_and_notify(request_id): ...  # type: ignore[misc]
```

Verified this env actually has Celery importable (`_USE_CELERY` resolves `True` here), so the real decorator path is exercised at import time; the plain-function fallback is exercised whenever Celery/`celery_app` is unavailable (e.g. a leaner test box).

Queue: set directly on the task decorator (`queue="onboarding"`), the same mechanism `tasks/racing_line_tasks.py` uses for its `"pipeline"` queue (a queue set on the task object itself, independent of `celery_app.py`'s `task_routes` dict). **`celery_app.py` was NOT modified** — `tasks.onboarding_tasks` is not added to its `include=[...]` list. This mirrors Task 9 (`onboarding/reprocess.py`, a plain function also left out of that list) and is the narrowest reading of this task's file scope ("Create `telemetry_tool/tasks/onboarding_tasks.py`"). For a real worker process to discover/route this task, `celery_app.py`'s `include` list will need `"tasks.onboarding_tasks"` added eventually — flagging this as a follow-up for whichever task wires worker deployment, since it wasn't in Task 10's stated file list.

## The two idempotency guards (confirmed by test)

1. **Claim gate** — `repo.claim_for_drafting(conn, request_id)` returning `False` is a hard, first-line early return: `TestClaimGate::test_claim_false_returns_early_no_side_effects` asserts zero calls to `repo.get`, `validate_bbox`, `sam2_draft`, `gps_only_draft`, `save_draft`, `tokens.mint`, `send_email_async.delay`, and `repo.set_status`.
2. **Email-once re-check** — right before sending, the row is re-fetched (`repo.get`) and the email is skipped whenever `emailed_at is not None`. Confirmed two ways:
   - `TestEmailedOnceGuard::test_already_emailed_row_is_not_resent` — the second `repo.get()` call (mocked via `side_effect`) returns a row with `emailed_at` already set; asserts `send_email_async.delay` is never called and no `"emailed"` status transition occurs.
   - `TestEmailedOnceGuard::test_run_twice_with_stateful_fake_repo_sends_once` — a stateful fake repo (a mutable dict updated by `set_status`) is run through `_run_draft_and_notify` twice end-to-end; `send_email_async.delay.call_count == 1` after both calls.

## Flow implemented (matches Task 10's step list)

1. `claim_for_drafting` → False = idempotent no-op, return.
2. `repo.get` → `validate_bbox(row["bbox"])`; `DraftError` → `set_status(..., "draft_failed", error=...)`, return.
3. `sam2_draft(bbox, centerline)`; `None` → `gps_only_draft(centerline)`, status `drafted_gps_only`/`draft_status="gps_only"`, else `drafted`/`"sam2"`. Any unexpected exception anywhere in this step → caught, `set_status(..., "draft_failed", error=...)`, return (never propagates — `TestUnexpectedDraftingFailure` confirms).
4. `save_draft` → `set_status(drafted_status, draft_path=..., draft_status=...)`.
5. `tokens.mint(request_id)` → `set_status(drafted_status, token_jti=jti)`.
6. Re-`repo.get`; if `emailed_at is None`: build `url = f"{ANNOTATOR_HOST}/?req={request_id}#token={raw}"` (token strictly after `#`, never in the query string — asserted in `TestHappyPathSam2`), `send_email_async.delay("onboarding_task", operator_email, {...})`, `set_status(..., "emailed", emailed_at=now)`. Else: log-and-skip.

## Reality-vs-plan note (bbox/centerline)

The plan's Task 10 interfaces text says "read its `bbox` (+ any GPS/centerline the row carries)". The actual `track_onboarding_requests` schema (migration 081) / `repo.py` `_ALL_COLUMNS` has **no dedicated GPS/centerline column** — only `bbox` and an opaque `fingerprint` JSONB. Since the trigger hook that populates these rows (Task 13) isn't built yet, I read `fingerprint["centerline"]` defensively (`_centerline_from_row`, falls back to `[]`) as the most plausible carrier, and documented this explicitly in the module docstring/helper so Task 13's implementer knows to either populate `fingerprint["centerline"]` or revisit this helper.

## Verification

```
python -m pytest tests/test_onboarding/test_onboarding_tasks.py -v   → 7 passed
python -m pytest tests/test_onboarding/ -q                           → 107 passed, 5 skipped (pre-existing, unrelated)
```

File size: `onboarding_tasks.py` is well under 500 lines (~215).
