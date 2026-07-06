# Final-review fix pass -- I1 (GT cache staleness) + I2 (vehicle_classes never threaded)

Branch: `feat/track-onboarding-loop`, worktree `C:\Users\Admin\lap_web-wt-onboarding`.

## I1 -- cross-process GT cache staleness

**Chosen approach**: the preferred one from the brief. Added
`track_surface.gt_loader.refresh_runtime_gt_if_configured()` -- a tiny,
unit-testable helper that calls the existing `invalidate_gt_cache()`
whenever `GT_RUNTIME_DIR` is set (no-op otherwise). `track_surface.builder.
build_track_surface` calls it at its own entry (step "0.", before step 1),
so **every** build -- regardless of which process runs it -- re-reads the
runtime GT store instead of trusting its own process's possibly-stale
`lru_cache`.

**Why this over the "don't cache None + watch alias mtime" alternative**:
that alternative needs to track `track_aliases.json`'s mtime as new
process-local state to detect a write from a *different* process, and still
leaves the geojson-miss cache needing the same kind of "did someone else
just write this" check. Unconditionally invalidating at build entry is
fewer moving parts for the same outcome, and the cost is genuinely
negligible: a `build_track_surface` call is heavy-compute (seconds), so
re-parsing one small `track_aliases.json` + (on the next `load_gt`) one gt
geojson is noise by comparison. The existing web-process call inside
`onboarding/bless_service.py::bless_geometry` (`invalidate_gt_cache`
directly) is untouched -- it's still needed for anything in the web process
itself that calls `load_gt` between a bless and the next build (e.g.
diagnostics), it's just no longer the ONLY invalidation point.

Files touched:
- `telemetry_tool/track_surface/gt_loader.py` -- new
  `refresh_runtime_gt_if_configured()` + module-docstring entry.
- `telemetry_tool/track_surface/builder.py` -- imports it, calls it as the
  first statement in `build_track_surface`, before `load_gt` is ever
  reachable (comment explains why).
- `telemetry_tool/tests/test_track_surface/test_gt_runtime_dir.py` -- two
  new tests: `test_cross_process_staleness_fixed_by_entry_hook` (primes a
  stale `None` miss the way the ORIGINAL trigger run would, writes GT+alias
  into `GT_RUNTIME_DIR` without calling `invalidate_gt_cache` directly, then
  calls `refresh_runtime_gt_if_configured()` and asserts the GT is now
  found) and `test_refresh_runtime_gt_is_noop_when_unset` (behavior
  unchanged when `GT_RUNTIME_DIR` is unset).

## I2 -- vehicle_classes never populated

Threaded end-to-end, mirroring the existing `draft_centerline` pattern:

1. **`telemetry_tool/alembic/versions/081_track_onboarding_requests.py`**
   (unapplied, edited in place) -- added `vehicle_classes JSONB` (nullable,
   `server_default='[]'`, matching `session_refs`' spirit but nullable per
   the brief). `tests/test_onboarding/test_migration_081.py` updated
   (column-list assertions, both the structural test and the PG-skip
   test).

2. **`telemetry_tool/onboarding/repo.py`** -- `vehicle_classes` added to
   `_ALL_COLUMNS`/`_JSONB_COLUMNS`; `upsert_open_request` gained a
   `vehicle_classes: list | None = None` kwarg. On INSERT it's
   `COALESCE(%(vehicle_classes)s::jsonb, '[]'::jsonb)`. On CONFLICT it
   merges as a deduped UNION (not a single-value append like
   `session_refs`, since a track can be seen across several vehicle
   classes at once): `jsonb_array_elements_text(existing || incoming)` fed
   through `array_agg(DISTINCT v)`. `tests/test_onboarding/test_repo.py`:
   extended the SQL-shape test with `vehicle_classes` assertions, extended
   `test_get_decodes_jsonb_columns_no_pg`, and added a new real-PG test
   `test_pg_vehicle_classes_dedup_union_across_upserts` (skips without
   `TELEMETRY_PG_URL`) proving three sessions across `gt3`/`gt4`/`gt3`
   again converge to `{"gt3", "gt4"}`.

3. **`telemetry_tool/onboarding/service.py`** -- `record_missing_geometry`
   gained `vehicle_classes: list | None = None`, forwarded verbatim to
   `repo.upsert_open_request`. `tests/test_onboarding/test_service.py`:
   updated the existing `assert_called_once_with` to include
   `vehicle_classes=None` (the new default) and added
   `test_vehicle_classes_forwarded_to_upsert`.

4. **`telemetry_tool/pipeline/stages/s10d_surface.py`** -- confirmed
   `v_class` (from `detect_vehicle_class(vehicle_name)`, always a non-empty
   string -- `"generic"` fallback) is in scope at the
   `_maybe_trigger_onboarding(...)` call site inside `run_surface_build`.
   Added a `vehicle_class: str | None = None` parameter to
   `_maybe_trigger_onboarding`, passed `vehicle_class=v_class` from the
   call site, and forwarded `vehicle_classes=[vehicle_class] if
   vehicle_class else []` into `record_missing_geometry`.
   `tests/test_onboarding/test_trigger_hook.py`: `_call()` now defaults
   `vehicle_class="gt3"`; added
   `test_vehicle_class_forwarded_as_one_element_list` and
   `test_no_vehicle_class_forwards_empty_list`.

5. **`telemetry_tool/web/routes/onboarding_routes.py`** -- already read
   `row.get("vehicle_classes") or []` and forwarded it to
   `reprocess_after_bless` (written ahead of the column landing); no code
   change needed now that the column actually exists end-to-end.
   `tests/test_onboarding/test_routes.py`: added `vehicle_classes` to the
   `_row()` test-fixture default, and two new tests --
   `test_vehicle_classes_row_derived_reach_reprocess_after_bless` (a row
   with `vehicle_classes=["gt3","gt4"]` reaches `reprocess_after_bless`
   unchanged) and `test_missing_vehicle_classes_forwards_empty_list` (a row
   without the key at all still forwards `[]`, not a `KeyError`).

## Test commands + output

```
$ python -m pytest tests/test_onboarding/ -q
........................................................................ [ 39%]
s....................................ssssss............................. [ 79%]
......................................                                   [100%]
175 passed, 7 skipped, 20 warnings in 3.26s

$ python -m pytest tests/test_track_surface/ -q
......................................................................   [100%]
70 passed, 8 warnings in 2.15s

$ python -c "import pipeline.stages.s10d_surface, track_surface.builder"
(no output -- clean import)
```

(warnings are pre-existing shapely/skimage deprecation noise from
`medial_axis.py`, unrelated to this change; PG-gated tests skip since there
is no local Postgres in this environment, as expected.)

## Residual concerns

- `track_surface/gt_loader.py` is 1282 lines -- already well over the
  500-line guideline before this change; out of scope here (only ~30 lines
  were added), but worth a future split.
- I2's vehicle_classes union-dedup SQL (`jsonb_array_elements_text` +
  `array_agg(DISTINCT ...)`) is only exercised end-to-end by the
  `@_skip_no_pg` PG test in this environment (no local Postgres) -- the
  no-PG suite only proves the SQL *shape* (capturing cursor), not that
  Postgres actually executes it as intended. Worth a real-PG run in CI/the
  controller before merge.
- `detect_vehicle_class` never returns empty/`None` (its fallback is
  `"generic"`), so the `if vehicle_class else []` guard in
  `_maybe_trigger_onboarding` is currently dead code on the real call path;
  kept for robustness/defensiveness (and because unit tests call the
  function directly with `vehicle_class=None`), not because it's reachable
  today from `run_surface_build`.
- Migration 081 is still unapplied in this environment (no local PG) --
  structural/regex-based tests pass, but the actual `ON CONFLICT`/dedup
  behavior against real Postgres has not been verified here.
