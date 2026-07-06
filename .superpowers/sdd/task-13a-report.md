# Task 13a — draft_centerline column, end-to-end thread

## What changed

1. **Migration 081** (`telemetry_tool/alembic/versions/081_track_onboarding_requests.py`)
   edited in place (branch-only, not yet applied anywhere) — added:
   ```python
   sa.Column("draft_centerline", JSONB, nullable=True),
   ```
   placed between `bbox` and `first_session_ref`. Column type is **`JSONB`,
   nullable** — a downsampled `[[lon, lat], ...]` polyline of one driven lap,
   stored as JSON same as `bbox`/`fingerprint`/`session_refs`. No index, no
   default, nothing else touched in the migration.

2. **`onboarding/repo.py`**
   - `_ALL_COLUMNS` and `_JSONB_COLUMNS` both updated to include
     `draft_centerline` (so `repo.get()` returns and JSON-decodes it).
   - `upsert_open_request(...)` gained `draft_centerline: list | None = None`,
     included in the INSERT column/VALUES list (`%(draft_centerline)s::jsonb`).
   - **Conflict behavior**: `ON CONFLICT ... DO UPDATE SET draft_centerline =
     COALESCE(track_onboarding_requests.draft_centerline,
     EXCLUDED.draft_centerline)` — first-non-null-wins. Deliberately different
     from `session_refs` (which accumulates/appends): `draft_centerline` is a
     single representative geometry, so a later attaching session's row never
     clobbers an already-stored centerline, but a first insert (or an existing
     NULL) still gets populated from whichever session supplies one first.

3. **`onboarding/service.py`** — `record_missing_geometry(...)` gained
   `draft_centerline: list | None = None`, forwarded unchanged into
   `repo.upsert_open_request(..., draft_centerline=draft_centerline)`. No
   validation/inspection of the value in this layer.

4. **`tasks/onboarding_tasks.py`** — `_centerline_from_row(row)` rewritten to
   read `row.get("draft_centerline")` (falls back to `[]` if `None` or the
   key is entirely absent — never raises). The old defensive
   `fingerprint["centerline"]` placeholder read is gone. Confirmed
   `_run_draft_and_notify` still handles the "no centerline" case gracefully:
   an empty list flows into `sam2_draft`/`gps_only_draft` exactly as before
   (those functions' contracts are unchanged) — `gps_only_draft` raises
   `DraftError` on empty input, which the existing `except Exception` guard in
   `_run_draft_and_notify` catches and turns into a `draft_failed` status
   write + non-raising return; no crash path was introduced.
   `draft_and_notify` (the public Celery task / `_dispatch` wrapper) now
   reads the real `draft_centerline` column via this updated helper — no
   change needed to `_dispatch`/`draft_and_notify` themselves, only to
   `_centerline_from_row`.

## Tests (strict TDD: tests updated to the new contract first, then code)

- `tests/test_onboarding/test_migration_081.py` — added `"draft_centerline"`
  to both the structural (`inspect.getsource`) column-list assertion and the
  real-PG `expected` column set.
- `tests/test_onboarding/test_repo.py` — `test_upsert_open_request_sql_shape_no_pg`
  now passes `draft_centerline=[[5.0, 45.0], [5.001, 45.0]]` and asserts the
  `COALESCE(track_onboarding_requests.draft_centerline,
  EXCLUDED.draft_centerline)` fragment plus the JSON-encoded param;
  `test_upsert_open_request_created_false_on_attach_no_pg` asserts
  `params["draft_centerline"] is None` when omitted;
  `test_get_decodes_jsonb_columns_no_pg` extended with a `draft_centerline`
  value to prove `repo.get()` decodes it.
- `tests/test_onboarding/test_service.py` — added module-level
  `_DRAFT_CENTERLINE` fixture value, included in `_kwargs()`, and
  `test_new_track_enqueues_once` now asserts
  `upsert_open_request.assert_called_once_with(..., draft_centerline=_DRAFT_CENTERLINE)`
  (was a bare `assert_called_once()`).
- `tests/test_onboarding/test_onboarding_tasks.py` — `_row()` fixture now
  carries `draft_centerline=[[...]]` as a first-class field (fingerprint
  reverted to a plain `{"n_sessions": 1}` placeholder, no more nested
  centerline). Added a new `TestCenterlineFromRow` class with 3 direct unit
  tests of `_centerline_from_row`: reads the column, returns `[]` on `None`,
  returns `[]` when the key is absent entirely (no crash).

## Result

```
python -m pytest tests/test_onboarding/ -q
139 passed, 5 skipped (PG-only tests skip; TELEMETRY_PG_URL unset)
```

No unrelated onboarding test regressed (full `test_onboarding/` directory
run, not just the 4 touched files).

## Constraints honored

- Branch-only; migration 081 edited in place (not superseded by a new
  revision) since it is unapplied everywhere.
- No `git add -A` — commit stages explicit paths only.
- All touched files well under 500 lines (largest is `repo.py` at 244 lines).
- No secrets introduced.
