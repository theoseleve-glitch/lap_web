# Task 13b — Track Onboarding Loop detection trigger

## GT-miss signal

`session_surface.boundary_source is None` immediately after
`build_track_surface(resampled_laps, track_id, adapter_format)` in
`telemetry_tool/pipeline/stages/s10d_surface.py::run_surface_build`. A GT
hit sets it to `"gt_anchored_native"` (`track_surface/builder.py:342`); the
legacy driven-median path leaves it `None` when no boundary source (neither
`gt_anchored_native` nor a data-derived envelope) resolves (`builder.py:361`).
The hook fires on `boundary_source is None`, which matches "no GT" as
specified.

## `is_operator_run` sourcing

Added `is_operator_run: bool = False` to `PipelineContext`
(`telemetry_tool/pipeline_context.py`) — a real dataclass field, persisted
in `_to_dict()`/`load()` like every other context flag. `PipelineContext.create()`
takes an optional `is_operator_run: bool | None = None` kwarg:

- If explicitly passed `True`/`False` by the caller, that wins.
- If left `None` (the default — every ordinary end-user upload call site:
  `web/routes/jobs.py`, `web/routes/sessions_v2.py`, `web/routes/sync_upload.py`,
  `tasks/batch_tasks.py` — none of these were touched), it falls back to
  `os.environ.get("ONBOARDING_OPERATOR_RUN") == "1"`, i.e. **False** in any
  environment that doesn't explicitly set that env var. This is the
  "conservative env-flag fallback" the task allowed for ops scripts that
  build a `PipelineContext` without threading the new kwarg through.

Two call sites were identified as genuine, already-existing operator
signals and updated to pass `is_operator_run=True` explicitly:

1. `web/routes/admin/jobs.py::retry_job` — gated by `@require_superadmin` +
   `@require_admin_role("root_admin", "sre_admin")`, i.e. an authenticated
   admin action.
2. `onboarding/reprocess.py::_dispatch_build_reprocess` — the bless-reprocess
   dispatcher, whose own docstring already says it "runs from an
   operator/admin-triggered maintenance connection, not a tenant-scoped web
   request." (In practice GT already exists by the time this path runs, so
   the hook is a no-op here — set for correctness/consistency, not because
   it's expected to actually fire.)

**Invariant preserved:** every ordinary end-user upload path is untouched
and defaults to `is_operator_run=False` (no env var set in normal
deployments), so end-user uploads can never trigger onboarding.

Plumbing to the stage: `tasks/pipeline_tasks.py::_build_session_meta` now
sets `meta["is_operator_run"] = bool(getattr(ctx, "is_operator_run", False))`
and `meta["job_id"] = ctx.job_id` on the `session_meta` dict passed into
`run_full_analysis`. Inside `pipeline/orchestrator.py`, `meta` is already in
scope at the step-10d call site (no new orchestrator-level parameter needed
— deliberately NOT reusing the pre-existing `context: Any = None` parameter
threaded through `run_full_analysis`, since that is a different, legacy
`SessionContext` object used only by `s05_track`/CLI callers such as
`main.py`, unrelated to the Celery `PipelineContext`). The orchestrator call
to `s10d_surface.run_surface_build` now passes
`is_operator_run=bool(meta.get("is_operator_run", False))` and
`job_id=meta.get("job_id") or meta.get("session_id")`.

## canonical_id / fingerprint / label / job_id at the stage

- **canonical_id**: `resolve_track_id(track_id) or resolve_canonical_via_pg(track_id)`
  — the exact dual-path resolution `build_track_surface` itself uses
  (`track_surface/builder.py:192`) to load GT, done again inside the new
  `_maybe_trigger_onboarding` helper (lazy import of
  `track_surface.gt_loader`). Using the same resolution guarantees the
  `track_key` passed to `record_missing_geometry` matches whatever key a
  later bless will write GT under.
- **fingerprint**: sourced from step 05's `track_match["fingerprint"]`
  (`s05_track.py` sets `track_info["fingerprint"] = fingerprint.to_dict()`,
  which orchestrator stores as `summary["track_match"]`). Passed into
  `run_surface_build` as a new `fingerprint: dict | None` kwarg.
- **track_label**: `summary["track_match"]["track_name"]`, falling back to
  `meta.get("track_name")`. Passed as a new `track_label: str | None` kwarg.
- **job_id** (used as `session_ref`): `meta["job_id"]` (== `ctx.job_id`,
  set by `_build_session_meta`), falling back to `meta["session_id"]` (by
  the codebase's existing `session_id == job_id` convention, see
  `web/routes/jobs.py`'s `_reconstruct_context_from_db` comment) if the
  former is somehow absent — belt-and-braces, both should always agree.

## bbox / centerline derivation

New helpers in `s10d_surface.py`, both reusing `track_surface/normalizer.py`'s
column-detection convention (`_GPS_LAT_COLS = ("lat_deg", "Latitude (deg)")`,
`_GPS_LON_COLS`, `_find_col`) so they work on both canonical and raw
RaceChrono-header DataFrames:

- `_compute_gps_bbox(resampled_laps)` — concatenates every lap's lat/lon,
  drops non-finite samples, returns
  `{"min_lon", "min_lat", "max_lon", "max_lat"}` (WGS84 degrees), or `None`
  if no lap has usable GPS.
- `_downsample_centerline(resampled_laps, n_points=100)` — picks the
  lowest-numbered lap as a deterministic "representative" lap (this is only
  a draft seed for the annotator-review UI, not final geometry — any single
  clean lap suffices), downsamples it to ≤100 evenly-spaced indices via
  `np.linspace`, returns a list of `[lon, lat]` pairs, or `None`.

## Implementation notes

- All new trigger logic lives in `_maybe_trigger_onboarding` (called from
  `run_surface_build` immediately after `build_track_surface`, before
  `merge_track_model`), fully unit-testable without a DB/broker/pipeline run.
- Refusal order (cheapest first, avoids canonical-id resolution / bbox work
  when we already know we'll refuse): no surface or GT-hit → not operator
  run → no/unknown `track_id` → no `job_id` → (inside try) no canonical id
  → no bbox.
- The entire canonical-id/bbox/centerline/`record_missing_geometry` call is
  wrapped in `try/except Exception: logger.exception(...)` — matches the
  existing `_record_geometry_rejection` best-effort pattern in the same
  file. Never breaks the pipeline.

## Tests

`telemetry_tool/tests/test_onboarding/test_trigger_hook.py` — 15 tests,
covering: GT-miss+operator+confident-track fires once with correct
`track_key`/`session_ref`/`bbox`/`draft_centerline`/`is_operator_run`/
`fingerprint`/`track_label`; refusals for GT-hit, no-surface, operator=False,
unknown/empty `track_id`, no `job_id`, unresolvable canonical id; and
exception-swallowing when `record_missing_geometry` raises.

```
python -m pytest tests/test_onboarding/test_trigger_hook.py -v   # 15 passed
python -m pytest tests/test_onboarding/ -q                        # 154 passed, 5 skipped
python -c "import pipeline.stages.s10d_surface"                   # OK
```

Also ran (pre-existing suites touching edited files, all green):
`tests/test_pipeline_context.py`, `tests/test_custom_corners.py`,
`tests/test_pipeline_racing_line_trigger.py`, `tests/test_admin_jobs_route.py`,
`tests/test_onboarding/test_reprocess.py` — 60 passed total.

## Concerns / follow-ups for reviewer

- The env-var fallback (`ONBOARDING_OPERATOR_RUN=1`) is a conservative
  default for as-yet-unidentified ops/CLI entrypoints (e.g. any future
  standalone reprocess script that builds a bare `PipelineContext`). It is
  off by default and does not affect any code path exercised by tests.
- `onboarding/reprocess.py`'s `is_operator_run=True` is set for
  correctness/consistency but is expected to be a no-op in practice (GT
  already exists by the time a bless-reprocess runs).
- Did not add an `is_operator_run` toggle to the ordinary upload routes
  (`web/routes/jobs.py`, `sessions_v2.py`, `sync_upload.py`,
  `tasks/batch_tasks.py`) — per the task's invariant, these must stay
  `False` and were intentionally left untouched.
