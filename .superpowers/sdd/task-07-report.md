# Task 7 report — onboarding/draft.py

**Status:** DONE

## What was built

`telemetry_tool/onboarding/draft.py` (465 lines):

- `DraftError(Exception)`.
- `DEFAULT_HALF_WIDTH_M = 4.0`, `MAX_BBOX_SPAN_DEG = 0.2`.
- `validate_bbox(bbox: dict) -> None` — real shape confirmed against
  `onboarding/repo.py`/`service.py` usage:
  `{"min_lat","max_lat","min_lon","max_lon"}` (not a 4-tuple). Raises
  `DraftError` on missing keys, non-numeric/non-finite values, lat outside
  [-90,90], lon outside [-180,180], `min>=max` on either axis, or either
  span > `MAX_BBOX_SPAN_DEG`.
- `gps_only_draft(centerline_lonlat, half_width_m=DEFAULT_HALF_WIDTH_M) -> dict`
  — no heavy dependency (numpy only, already a hard dep). Projects to local
  metres at the centroid (`x=(lon-lon0)*cos(lat0)*111320`,
  `y=(lat-lat0)*110540`), dedupes/closes the ring, resamples to
  `>= MIN_BOUNDARY_POINTS + 5` points via arc-length interpolation, offsets
  ±half_width along wraparound-tangent normals, closes each boundary by
  repeating vertex 0 (closure gap = exactly 0), then checks both
  self-intersection (reused `track_surface.geometry_gates._has_self_intersection`)
  and cross-boundary intersection (local brute-force helper using the same
  module's `_segments_intersect`) — raises `DraftError` rather than emit
  invalid geometry if either check fails.
- `sam2_draft(bbox, session_gps) -> dict | None` — never raises. Validates
  bbox, requires >= 10 GPS points, locates
  `Analysis/trackreco-main/scripts/lap_track_to_draft.py` via
  `_trackreco_script()` (see "SAM2 invocation" below), writes a temp
  `latitude,longitude` CSV, shells `lap_track_to_draft.py --name <slug>
  --session-csv <csv> --zoom 19 --backend auto` with a 900s timeout, then
  reads `data/satellite_gt/<slug>/gt_<slug>.geojson` (traced through
  `build_satellite_gt.py`'s `write_satellite_gt`). Any failure anywhere
  (bad bbox, absent checkout, missing heavy deps in the child process,
  timeout, non-zero exit, missing/malformed output) is caught and returns
  `None`.
- `save_draft(request_id, geojson) -> str` / `load_draft(request_id) -> dict`
  — directory from `ONBOARDING_DRAFT_DIR` env, else
  `GT_RUNTIME_DIR/../onboarding_drafts`, else a temp-dir fallback.
  `request_id` is validated against `^[A-Za-z0-9_-]{1,128}$` (stricter than
  "no separators" — no dots at all), raising `DraftError` on any other
  value including `..`, `/`, `\`, or empty.

## Validator requirements verified against the real `gt_validate.py`

Read `track_surface/gt_validate.py` before implementing; corrected two
assumptions from the plan text:

1. `validate_gt_geojson(path) -> list[str]` — **not** an object with
   `.ok`. Empty list == valid; a non-empty list is human-readable failure
   messages. Tests assert `messages == []`, not `res.ok`.
2. `schema`/`reviewed_by` are read from the **top-level** `properties`
   dict (`data.get("properties")`), while `role` is read from each
   **feature's** `properties`. Roles required: `left_boundary_gt`,
   `right_boundary_gt`, each >= `MIN_BOUNDARY_POINTS` (20) points. Closure
   gap (equirectangular, radius 6,371,000 m) must be <= `MAX_CLOSURE_GAP_M`
   (25 m) — satisfied trivially here since we duplicate vertex 0 as the
   closing point. Boundaries must not properly cross (reused
   `geometry_gates._segments_intersect`).
3. **Honesty-layer tension, flagged for Task 8's reviewer:**
   `validate_gt_geojson` requires a non-empty `reviewed_by` — its "a human
   looked at this" gate. `gps_only_draft` is machine-generated, not
   human-reviewed, yet Task 7's acceptance test requires the raw output to
   pass the validator outright. Resolved by stamping a clearly-synthetic
   sentinel (`reviewed_by="auto_draft:gps_only"`,
   `review_source="gps_only_draft"`) rather than a real name — grep-able as
   unreviewed. This relies on `bless_service` (Task 8, per the plan's
   global constraint) refusing to bless a submission whose geometry does
   not *differ* from the stored auto-draft, i.e. enforcing that a human
   actually edited it, rather than trusting `reviewed_by` alone.
   `sam2_draft`'s output is NOT stamped this way — it's `write_satellite_gt`'s
   raw, un-reviewed output (confirmed by reading `emit.py`), so it fails
   `validate_gt_geojson` until a human reviews it in the annotator, same as
   any other draft.

## SAM2 invocation (verified against the real scripts)

Read `Analysis/trackreco-main/scripts/lap_track_to_draft.py` and
`build_satellite_gt.py`. `lap_track_to_draft.py --name <slug>
--session-csv <csv.csv> [--zoom N] [--backend auto|sam2|sam1|heuristic]`
thins the CSV's lat/lon trace, writes `web_build/<slug>/track_model.geojson`,
registers the track in the annotator's `tracks.json`, then (unless
`--skip-build`) shells `build_satellite_gt.py --track <slug> --build-dir
web_build/<slug>` (cwd = the trackreco-main repo root), which writes the
final `trackreco_ground_truth_v1` geojson to
`data/satellite_gt/<slug>/gt_<slug>.geojson` via `emit.write_satellite_gt`.

Important repo-layout finding: `Analysis/trackreco-main` is a **sibling**
repo to `lap_web`, not a subpath of it — and this task's worktree
(`C:\Users\Admin\lap_web-wt-onboarding`) is NOT under
`C:\Users\Admin\Documents\Telemetry\`, so no fixed relative walk from
`draft.py`'s `__file__` can reach it from every worktree. `_trackreco_script()`
resolves the path via `ONBOARDING_TRACKRECO_DIR` env override, falling back
to this machine's known absolute layout
(`C:\Users\Admin\Documents\Telemetry\Analysis\trackreco-main`) — noted as a
machine-specific default consistent with this repo's existing
Windows-specific conventions (see root `CLAUDE.md`), overridable per-deploy.

## Tests

`telemetry_tool/tests/test_onboarding/test_draft.py` — 30 tests, all passing:

- **Key test** `test_gps_only_draft_passes_gt_validator`: builds a 30-point
  closed oval centerline, calls `gps_only_draft`, writes it to a temp file,
  and asserts the real `validate_gt_geojson(path) == []`.
- `gps_only_draft` shape/closure/point-count assertions; rejects too-short
  and non-finite centerlines; rejects non-positive `half_width_m`; rejects
  self-intersection — note: a smooth ellipse and a stadium/hairpin shape
  were both tried first and did NOT trigger self-intersection (piecewise-
  or slowly-varying curvature offsets cleanly even past the local radius —
  verified empirically by direct computation), so the self-intersection
  test uses a 5-lobed rose curve (`r = r0 + r1*cos(5*theta)`), confirmed by
  direct experimentation to self-intersect at `half_width_m >= 2`, well
  under the 4 m default.
- `validate_bbox` parametrized rejection cases (NaN, lat=200, lon=999,
  `min>=max`, 0.5° span) + missing-keys case; one accept case.
- `sam2_draft` returns `None` (never raises) when: the trackreco checkout
  is absent (monkeypatched `_trackreco_script`), `subprocess.run` raises,
  `subprocess.run` returns a non-zero exit code, the bbox is invalid, or
  there are too few session GPS points.
- `save_draft`/`load_draft` round-trip via `ONBOARDING_DRAFT_DIR`; both
  reject request_ids containing `..`, `/`, `\`, or empty string.

`python -m pytest tests/test_onboarding/test_draft.py -v` → **30 passed**.
`python -m pytest tests/test_onboarding/ -q` → **65 passed, 5 skipped**
(pre-existing skips from earlier tasks, unrelated to this one).
`python -m pytest tests/test_track_surface -q` → **68 passed** (no
regression from the `geometry_gates`/`gt_validate` imports this task adds).

## Constraints followed

- Branch-only; no `git add -A` (staged explicit paths).
- File is 465 lines (< 500).
- No secrets; `ONBOARDING_TRACKRECO_DIR`/`ONBOARDING_DRAFT_DIR`/
  `GT_RUNTIME_DIR` are the only env dependencies, all optional with safe
  fallbacks.

## Concerns for later tasks

- Task 8 (`bless_service.py`) must actually implement the
  diff-from-stored-auto-draft check discussed above — without it, the
  `reviewed_by` sentinel this task stamps would let an unreviewed
  `gps_only_draft` slip through `validate_gt_geojson` and get blessed
  as-is. This task only produces the draft; it does not gate blessing.
- `_trackreco_script()`'s fallback path is machine-specific
  (`C:\Users\Admin\...`); fine for this single-operator setup per the
  existing root `CLAUDE.md` conventions, but should move to a required env
  var if this ever runs on a second machine/CI.
- `sam2_draft` was not exercised against a real trackreco-main checkout
  (no GPU/SAM2 env in this worktree) — only the failure paths are tested,
  per the task brief. The happy path (parsing a real produced geojson) is
  untested end-to-end.
