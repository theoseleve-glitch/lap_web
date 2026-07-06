# Task 8 report — onboarding/bless_service.py + scripts/bless_gt.py extraction

## Files

- `telemetry_tool/onboarding/bless_service.py` (new, 457 lines)
- `scripts/bless_gt.py` (modified — thin wrapper over the extracted core)
- `telemetry_tool/tests/test_onboarding/test_bless_service.py` (new, 15 tests)

## How the surface for `run_geometry_gates` was built (no GPS needed)

Read `track_surface/builder.py`'s `gt_anchored` branch (lines ~183–349) closely
first: when GT exists, `build_track_surface` derives the Frenet centerline
and `width_left`/`width_right` **entirely from `GroundTruth.gt_centerline_lonlat`
/ `gt_width_left_m` / `gt_width_right_m`** — no GPS lap is touched for
geometry (only elevation/camber/grip need laps, and those stay `None` here).

So `_geojson_to_surface` in `bless_service.py` reuses exactly the same
production primitives `track_surface.gt_loader._load_gt_canonical` uses to
compute those three fields from a gt file's two boundary polylines:

1. `track_surface.medial_axis.build_medial_axis_spine(left, right)` — the
   primary (deterministic) midline+half-width builder.
2. Falls back to `track_surface.gt_loader._compute_cross_section_midline_and_widths`
   on medial-axis failure (annulus topology check fails, degenerate raster,
   etc.) — the same fallback `_load_gt_canonical` uses.
3. Projects the resulting midline to local XY via `gt_loader._local_equirect`,
   using a projection reference derived from the **GT boundaries' own bbox
   centroid** (same internal convention `medial_axis`/cross-section already
   use), not a GPS session mean — there is no GPS session at bless time, and
   arc length, closure error, self-intersection, and width bounds (the gates
   that matter) are invariant to that reference choice.
4. `FrenetFrame.from_centerline(cl_xy)`, then interpolates the GT half-widths
   onto `frenet.s_grid` exactly as `builder.py`'s gt_anchored branch does
   (`np.interp(frenet.s_grid, gt_s_stations, gt_width_*_m)`).
5. Assembles a `TrackSurface(track_id=canonical_id, frenet=..., width_left=...,
   width_right=..., boundary_source="gt_anchored_native", n_laps=0,
   sim_sources=[])` — elevation/camber/grip left `None` (gates don't require
   them; `run_geometry_gates` only checks elevation gates when
   `elevation_m` is not `None`).

Verified end-to-end with a concentric-ring (annulus) fixture (60/52 m radii,
60 pts/boundary — same shape as `tests/test_track_surface/test_gt_validate.py`'s
`_gt()` helper) both standalone and inside the full `bless_geometry` flow:
`run_geometry_gates` returns `passed=True` with zero failures. Degenerate
fixtures (crossing boundaries, <20 pts) never reach this step — they are
rejected by `validate_gt_geojson` first (step 4 in the flow, before step 5's
geometry gates), matching the required test-order semantics. No degradation
was needed; this is a genuine, real geometry-gate evaluation, not a
skipped/stubbed one.

## Extracted `bless_gt` core — exact signature

```python
# telemetry_tool/onboarding/bless_service.py
class InstallError(RuntimeError): ...

def install_gt_geojson(
    geojson_path: Path,
    canonical_id: str,
    *,
    aliases: list[str] | None = None,
    force: bool = False,
    gt_dir: Path,
    aliases_file: Path,
) -> Path:
    """validate_gt_geojson -> (reviewed_by-missing ABSOLUTE refusal, force
    can't override) -> (other validator messages refused unless force) ->
    (duplicate canonical_id refused unless force) -> shutil.copy2 into
    gt_dir/gt_<canonical_id>.geojson -> merge-register canonical_id+aliases
    into aliases_file. Raises InstallError on any refusal."""
```

`scripts/bless_gt.py`'s `bless_gt()` function keeps its **exact original
signature and behavior** (verified by the pre-existing
`tests/test_track_surface/test_gt_validate.py` suite, all 10 tests still
green unmodified) — it is now a 6-line wrapper that resolves the CLI's
default paths and calls `install_gt_geojson(...)`. `BlessError` is
re-exported in `scripts/bless_gt.py` as `from onboarding.bless_service
import InstallError as BlessError`, so `pytest.raises(BlessError, ...)`
call sites are unaffected.

`bless_service.bless_geometry` calls the **same** `install_gt_geojson` with
`force=False` hard-wired (not a parameter of `bless_geometry` at all — it
cannot be passed in from the web path even by accident), targeting
`Path(os.environ["GT_RUNTIME_DIR"])` and
`GT_RUNTIME_DIR/track_aliases.json` (never the baked
`data/ground_truth/`/`track_aliases.json` the CLI defaults to).

## Reject paths install nothing — confirmed

Every one of the 8 flow steps in `bless_geometry`'s docstring returns
through the single `_reject()` helper before any install call is reached:
`unreviewed_draft`, `invalid_reviewer`, `gt_runtime_dir_unset`,
`validate_gt_geojson` (non-empty messages), `surface_build_error`,
`geometry_gates` (any gate failure), `install_refused` (InstallError from
`install_gt_geojson`, e.g. duplicate canonical_id), `internal_error` (any
other exception, fail-closed catch-all), and `malformed_geojson` (load
failure, before the try block even starts). `install_gt_geojson` is only
ever called from inside the `with tempfile.TemporaryDirectory()` block,
strictly after `validate_gt_geojson` and `run_geometry_gates` have both
already passed — so a reject at any earlier step never reaches the
filesystem write. Tests assert `not (GT_RUNTIME_DIR / "gt_<id>.geojson").exists()`
after every reject case, including a duplicate-canonical_id second bless
attempt (which must leave the first-installed file byte-identical, i.e.
`force` truly unreachable from the web path).

Two additional design points worth flagging:

- **Geometry-only draft comparison.** `_geometry_signature()` compares only
  `features` (role + coordinates), deliberately ignoring `properties`
  (`reviewed_by`, `review_source`, etc.). This matters because
  `onboarding/draft.py`'s `gps_only_draft` already stamps its own
  `reviewed_by="auto_draft:gps_only"` sentinel — comparing whole documents
  would make the "operator must actually change something" gate never
  fire once the server overwrites `reviewed_by` anyway. Covered by a
  dedicated test (`test_only_reviewed_by_differs_still_rejected`).
- **`GT_RUNTIME_DIR` unset is fail-closed**, not "fall back to the baked
  corpus" — writing into the repo's baked `data/ground_truth/` would
  require a Docker rebuild+redeploy to ever take effect and is not the
  "runtime" contract Task 2 built; an unset env var rejects with a clear
  message rather than silently no-op-ing into the wrong directory.

## Deviation from the plan snippet (intentional, per explicit task instructions)

The plan's Task 8 "Interfaces" line lists `set_canonical_id` as part of the
flow and orders gates as (surface→gates) before (validate_gt_geojson). The
task brief I was given for this session explicitly overrode both: (a) do
**not** set `tracks.canonical_id` here — Task 9 (`reprocess_after_bless`)
owns that — and (b) run `validate_gt_geojson` (step 4) before
`run_geometry_gates` (step 5), plus two extra checks not in that plan
snippet at all (`unreviewed_draft`, `invalid_reviewer`) ahead of both. I
followed the explicit brief since it was more specific and the two extra
checks are load-bearing security gates. Flagging this in case the plan
document itself needs a follow-up edit for consistency.

## Test summary

`python -m pytest tests/test_onboarding/test_bless_service.py -v` → 15/15
passed. `tests/test_onboarding/ -q` → 80 passed, 5 skipped (skips are
pre-existing, unrelated to Task 8). `tests/test_track_surface/test_gt_validate.py`
(existing CLI tests) → 10/10 passed unmodified. `tests/test_track_surface/`
(full dir) → 68 passed. No DB was needed anywhere — `conn` is a small fake
recording executed SQL + commit calls.
