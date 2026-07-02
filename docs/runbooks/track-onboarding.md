# Track Onboarding Runbook — Track Geometry Factory

## Overview

End-to-end operator procedure for onboarding a new track's ground-truth (GT)
boundary geometry: from a raw driving session to a canonical, gated,
solver-ready track surface in production. Everything this runbook documents
was built across Tasks 1-6 of the Track Geometry Factory (branch
`feat/geometry-factory`, worktree `C:\Users\Admin\lap_web-wt-race-brief`); this
document is Task 7, the final task.

Two machines/checkouts are involved:

- **Operator-local machine** running `Analysis/trackreco-main` (satellite
  draft generation + the review annotator).
- **This repo (`lap_web`)** for blessing the reviewed export, committing, and
  deploying.

## Prerequisites

- `Analysis/trackreco-main` checked out. Task 3 confirmed there is **no
  dedicated venv** — system Python (`trackreco` is pip-installed editable,
  importable as `trackreco_platform`) works directly with no PYTHONPATH hack,
  run from the `trackreco-main` root. SAM2 weights are only required when
  *not* passing `--skip-build` (Step 1).
- `lap_web` (this repo), on a branch that will carry the new GT file, with
  `telemetry_tool` importable (run commands from the repo root or from
  `telemetry_tool/`, matching the existing test convention).
- Prod SSH access for Steps 5-6 (`root@46.225.227.24:/opt/lap-api`, per
  `docs/launch-deploy-runbook.md`) — only needed once a real track reaches
  deploy. **Every deploy to that host needs explicit user confirmation before
  it runs — see Step 5.**

## Operator steps

### Step 1 — Generate the draft (operator-local, trackreco-main)

Run from `Analysis/trackreco-main`, on the machine with SAM2 weights:

```bash
python scripts/lap_track_to_draft.py --name <slug> --session-csv <file> --zoom 19 --backend auto
```

- `<slug>` — canonical track id: lowercase letters/digits/`_`/`-`, must match
  `[a-z0-9][a-z0-9_-]{0,63}` (validated up front; anything else is a hard
  `SystemExit` before any file is touched).
- `<file>` — a LAP session CSV (RaceChrono-style lat/lon columns). The parser
  auto-detects the real header row (skips a RaceChrono metadata preamble) and,
  when the file has multiple laps, picks the fastest non-partial lap.
- Add `--skip-build` to stop after producing `web_build/<slug>/track_model.geojson`
  and registering `<slug>` in `netlify-annotator/tracks.json`, without invoking
  the satellite-boundary builder — useful to sanity-check the extracted
  centerline first, or when SAM2/imagery isn't available on this run.
- Without `--skip-build` (the normal path), the command chains into
  `scripts/build_satellite_gt.py --track <slug> --build-dir web_build/<slug> --zoom 19 --backend auto`,
  which produces, under `data/satellite_gt/<slug>/`:
  - `gt_<slug>.geojson` — the boundary **draft** (`properties.source ==
    "satellite_v1"`; roles `left_boundary_gt`/`right_boundary_gt`).
  - `confidence_report.json` (`schema: satellite_gt_confidence_v1`) with a
    **verdict**: `accept` (proceed to Step 2) or `fallback_hand_tracing` (see
    Failure modes below).
- On success the CLI prints the next step itself: "DRAFT ready under
  `data/satellite_gt/<slug>/` — review it in the annotator, then bless with
  `lap_web/scripts/bless_gt.py`. The draft is NOT ground truth until a human
  reviews it."

### Step 2 — Review in the annotator (operator-local, trackreco-main)

```bash
cd Analysis/trackreco-main/netlify-annotator
python -m http.server 8123
```

Open `http://localhost:8123`:

1. Load the draft geojson (`data/satellite_gt/<slug>/gt_<slug>.geojson`) via
   the file input ("Load Existing GT"). Because it carries
   `properties.source == "satellite_v1"`, the annotator flags it internally as
   a draft; both boundaries load pre-populated and every vertex is a
   draggable marker.
2. Correct the boundaries by dragging vertices (click-to-draw and Ctrl+Z undo
   still work for anything missing or wrong).
3. Export. The tool prompts once for a reviewer name (cached in
   `localStorage` after the first prompt) and stamps the export with
   `reviewed_by: <name>` and `review_source: satellite_draft` (or
   `hand_traced` if you started from a blank track instead of a draft).
   **`reviewed_by` is mandatory** — Step 3 refuses a file without it,
   unconditionally, even with `--force`.

### Step 3 — Bless (lap_web root)

```bash
python scripts/bless_gt.py <exported.geojson> --canonical-id <slug> [--alias <name> ...]
```

Validates via `track_surface.gt_validate.validate_gt_geojson`, in order of how
strictly each is enforced:

- **Always refused, `--force` cannot override:** missing/blank `reviewed_by`.
- **Refused unless `--force`:** schema tag, both `left_boundary_gt` /
  `right_boundary_gt` present with ≥20 points each, per-boundary closure gap
  ≤25 m, no left/right intersection, finite in-world coordinates.
- **Refused unless `--force`:** `--canonical-id` already exists in the alias
  registry (a forced re-bless merges into the existing entry rather than
  replacing it — other keys like `country`/`notes` survive).

On success it: copies the file to `data/ground_truth/gt_<slug>.geojson`;
registers `<slug>` (+ any `--alias` values) into
`telemetry_tool/track_surface/track_aliases.json` atomically (`os.replace`,
preserves existing key order); prints the
`UPDATE tracks SET canonical_id = ...` SQL (template `<TRACK_UUID>`
placeholder — substitute the real row) for Step 6; and prints the Step 5
deploy reminder (ground truth is baked into the backend Docker image at build
time).

### Step 4 — Commit

```bash
git add data/ground_truth/gt_<slug>.geojson telemetry_tool/track_surface/track_aliases.json
git commit -m "feat(geometry-factory): bless <slug> ground truth"
```

These two paths are the only ones Step 3 touches — commit exactly those,
never `git add -A`.

### Step 5 — Deploy — REQUIRES USER CONFIRMATION

This is a standard backend container rebuild (same shape as
`docs/launch-deploy-runbook.md` Phase 3). **Per the standing rule, a
behavior-changing deploy to the live, traffic-collecting prod endpoint always
needs explicit user confirmation first — do not run this unattended, even
with a green build.**

```bash
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose build api celery-pipeline celery-default celery-beat && docker compose up -d api celery-pipeline celery-default celery-beat"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose exec -T -w /app/telemetry_tool api alembic upgrade head && docker compose exec -T -w /app/telemetry_tool api alembic current"
```

**Gate:** `alembic current` reaches `079_track_geometry_audit (head)`;
`curl -s https://api.lap-coach.racing/healthz` → `{"status":"ok"...}`.

### Step 6 — Point the track row at the new canonical id

Run the SQL Step 3 printed, with the real `track_id` substituted:

```bash
ssh root@46.225.227.24 "docker exec -i lap-api-postgres-1 psql -U telemetry -d telemetry -c \"UPDATE tracks SET canonical_id='<slug>' WHERE id='<TRACK_UUID>';\" "
```

### Step 7 — Verify end-to-end

Trigger a session upload (or reprocess an existing one) for that track and
confirm:

- The rebuilt surface's provenance shows `boundary_source=gt_anchored_native` (real
  GT, not a predicted/heuristic boundary).
- The geometry gates pass at persistence (`merge_track_model` — arc ≥100 m,
  monotonic s, closure ≤5 m, no self-intersection, widths [0.5, 30] m,
  elevation range ≤100 m / step ≤2 m, all-finite); no new row appears in
  `track_geometry_audit` for this track.
- `compute_racing_lines` (Celery) emits a racing line for the track instead
  of degrading gracefully.

## Failure modes

| Symptom | What it means | What to do |
|---|---|---|
| Step 1 `confidence_report.json` verdict = `fallback_hand_tracing` | Satellite/SAM2 boundary confidence too low to trust as a draft | There is no usable draft. Open the same annotator (Step 2) with a **blank** track and hand-trace both boundaries from scratch instead of correcting a draft; `review_source` will be `hand_traced`. |
| Step 1 raises `no latitude/longitude columns` / `fewer than 10 valid GPS points` | Session CSV doesn't parse as expected | Confirm the CSV has recognizable lat/lon columns. Known gap (Task 3): a **raw, uncleaned RaceChrono Pro export** whose header row itself contains a literal `#` (e.g. `Lap #`) breaks parsing — `pd.read_csv(..., comment="#")` truncates that header line at the `#`, discarding every column after it. Pre-clean the CSV (rename `Lap #` → `Lap`, etc.) before retrying. |
| Step 3 (`bless_gt.py`) refuses, exit 1, message mentions `reviewed_by` | Export wasn't produced through the annotator's export flow (or the field is blank) | Re-export from the annotator so the reviewer prompt fires. There is no override, `--force` included. |
| Step 3 refuses for another validator reason (point count, closure, intersection, schema) | Geometry itself is bad | Fix it in the annotator and re-export, or pass `--force` only after manually confirming the geometry is acceptable despite the warning. |
| Step 7: surface geometry silently unchanged after a new session | Gates rejected the merge | The geometry write was withheld — **grip still accumulates independently**, the pipeline is not blocked. A row is written to `track_geometry_audit`. Inspect with `python scripts/audit_track_geometry.py` (add `--sidecar-root`, `--quarantine`, `--json` as needed) or query directly: `SELECT * FROM track_geometry_audit WHERE track_id = '<id>' ORDER BY created_at DESC;` |
| Solver / `compute_racing_lines` reports `status=failed` | Existing graceful degradation — geometry too degenerate to optimize (predates this factory; not a new failure mode) | Run the audit script to confirm the underlying centerline fails a gate (e.g. `self_intersection`, `arc_length`). If so, the track needs re-onboarding (back to Step 1/2), not a solver fix. |

---

## Appendix: acceptance evidence

### A. Geometry audit over local sidecars

Command run from the `lap_web` worktree root
(`C:\Users\Admin\lap_web-wt-race-brief`), 2026-07-02:

```
$ python scripts/audit_track_geometry.py
0ec6b076-dba6-4517-a231-fe27aea36ade: FAIL self_intersection
403ae76f-4293-4c70-894b-103fdc456a5f: PASS

1 passed, 1 failed, 2 total
```

Exit code: `2` (contract: any-fail → 2).

**Note on this specific FAIL:** both track ids are pre-existing local
`data/sidecars/` debris in this worktree (`telemetry_tool/models/tracks.json`
names both "Unknown Track", synthetic-looking fingerprints) — Task 6
confirmed these are inert test data, not real MKR/KCT geometry, and they are
**not** the same tracks as the two real prod ids flagged for quarantine in
section D below. The audit script itself is working correctly (independently
cross-checked against `run_geometry_gates` directly in Task 6); this is a
genuine finding on throwaway local data, not a script defect.
`data/sidecars/` is gitignored.

### B. Store-gating / geometry-factory test suite

Command run from `telemetry_tool/`, 2026-07-02:

```
$ python -m pytest tests/test_track_surface/ -q
.............................                                            [100%]
29 passed in 1.12s
```

Covers: 14 geometry-gate tests (`test_geometry_gates.py`), 2
persistence-gating tests (`test_store_gating.py` — confirms grip still
accumulates when geometry is rejected), 10 GT-validator/bless tests
(`test_gt_validate.py`), 3 audit/quarantine-script tests
(`test_audit_script.py`).

### C. Annotator browser checklist — PENDING HUMAN

Copied verbatim from `Telemetry/.superpowers/sdd/task-4-report.md` (Step 4,
outside this repo — the Task 4 build's own record). A Node-harness logic
simulation covered the state/export logic against real data, but nobody has
driven the real browser yet:

- [ ] PENDING-HUMAN: `python -m http.server 8123` in `netlify-annotator/`,
      open `http://localhost:8123`, visually confirm the page loads with no
      console errors.
- [ ] PENDING-HUMAN: Load a real draft geojson via "Load Existing GT" →
      visually confirm boundaries appear on the map and small colored vertex
      dots are visible and look draggable (cursor: grab).
- [ ] PENDING-HUMAN: Actually drag one vertex ≥10m with the mouse; confirm
      the polyline visually updates live at drag-end and the point count in
      the sidebar stays the same (move, not add/remove).
- [ ] PENDING-HUMAN: Click Export; confirm the browser's `prompt()` dialog
      actually appears (first time) and a real file download occurs; open the
      downloaded file and eyeball the changed vertex.
- [ ] PENDING-HUMAN: Reload the exported file via "Load Existing GT" again;
      visually confirm it looks identical to before export (round-trip).
- [ ] PENDING-HUMAN: General click-to-draw and Ctrl+Z undo still behave as
      before (not changed by Task 4, but no visual regression check was
      performed).

### D. Pending prod window — needs user deploy confirmation (NOT DONE)

None of the following have happened yet. Listed here explicitly so this
appendix cannot be misread as claiming otherwise:

- [ ] **NOT DONE** — apply migration `079_track_geometry_audit` on prod
      (`alembic upgrade head`, per Step 5).
- [ ] **NOT DONE** — deploy the gated persistence code (container rebuild,
      per Step 5) — prod is currently running pre-gate code.
- [ ] **NOT DONE** — run `scripts/audit_track_geometry.py` against prod
      sidecars (needs `--sidecar-root` pointed at the prod mount, or run
      directly on the VPS).
- [ ] **NOT DONE** — quarantine the two known-degenerate prod tracks:
      `6e862d59-34ed-4b20-b096-01d06748acac` and `4c067d03` (id as recorded
      in the source task — confirm the full UUID before running the
      quarantine) — both flagged as grip present, ~zero-length centerline.
- [ ] **NOT DONE** — carry one real track through this entire runbook
      end-to-end (draft → review → bless → deploy → gates pass → solver
      emits a line) as a live proof, not just unit/local evidence.
