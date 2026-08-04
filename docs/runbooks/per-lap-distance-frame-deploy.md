# Per-Lap Distance Frame Fix — Production Deploy Runbook

Authoritative deploy procedure for branch **`fix/per-lap-distance-frame`** (worktree `C:\Users\Admin\lap_web-wt-distframe`) → the LIVE `lap-coach.racing` platform.

> **You run this.** The backend `scp` and the frontend `cf:deploy` need your authenticated terminal; a sandboxed agent cannot reach either.

VPS = `root@46.225.227.24:/opt/lap-api`.

## What this branch changes

`resampling.resample_lap_by_distance` now rebases every lap to a **0-based per-lap distance frame**. RaceChrono exports *cumulative session* distance, so lap 5 of a ten-lap session arrived starting near 5 km. Corners are detected on one lap only and carried that lap's absolute span, so the ubiquitous `(dist >= s_start) & (dist <= s_end)` mask returned **empty on every other lap** — silently. Measured on `OK_R4.csv`: 9 of 10 laps produced **zero** corner samples before the fix, 10 of 10 produce 272–309 after.

`PIPELINE_VERSION` is bumped to **3**, so every pre-fix session now reports itself stale via `GET /sessions/stale`.

**Nothing here is a schema migration.** There are no new alembic revisions on this branch. The whole risk surface is *data already written in the old frame*, which is what the rest of this document is about.

---

## 1 — PRE-DEPLOY BLOCKING DECISION: `user_corners` ⛔

**Do not deploy until this is decided.** Rows in `user_corners` are stored in the **old absolute frame** and the table has **no frame column**, so nothing can tell old rows from new ones after the deploy.

### Why the blast radius is larger than "one override"

`run_track_decomposition_v2` (`telemetry_tool/pipeline/stages/s10b_corners.py:614-619`) documents its own priority order:

```
1. User-defined corners from ``user_corners`` table
2. Autonomous ``decompose_track()``
3. Fallback: convert step-06b corners into v2 sections
```

The `user_corners` branch **returns early** — `s10b_corners.py:634` is `return _user_corners_to_sections(rows, best_lap_df, td_mod)`, so the autonomous `decompose_track(best_lap_df)` at `:650` never runs. One stale row set does not merely override a corner list; it **replaces the entire v2 section list**, which is the input to:

- MRP detection (`run_mrp_detection_v2`)
- the 17-detector handling ensemble (`run_handling_analysis_v2`)
- coaching v2 (`run_coaching_v2`)
- `GET /sessions/<id>/corners`

Downstream of that, `_build_corner_perfs_from_user_corners` (`telemetry_tool/pipeline/orchestrator.py:~90-120`) masks the best lap with `(d >= row["s_entry"]) & (d <= row["s_exit"])` and requires `mask.sum() > 5`. With old-frame spans against a 0-based lap the mask is **empty**, so the function keeps its seeded placeholders:

```python
"braking_decel_mps2": 6.0,
"cornering_accel_mps2": 5.0,
"exit_accel_mps2": 3.0,
```

Result: **every corner reports identical, fabricated physics** — and it looks like real output. Ignoring this makes exactly the sessions an operator took the trouble to inspect get *worse* than untouched ones.

### How many rows are actually out there

The only in-repo writer is `lap-website/src/components/app/charts/CornerDefiner.tsx`. It is exported at `lap-website/src/components/app/charts/index.ts:12` and **mounted nowhere** — no route or page imports it. The prod population is therefore most likely operator-created only, and may well be empty.

### Do this

```bash
# Count first. Do not guess.
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U lap -d lap -c 'SELECT workspace_id, count(*) FROM user_corners GROUP BY 1 ORDER BY 2 DESC;'"
```

- **Zero rows** → nothing to do. Record the count in the deploy log and continue.
- **A handful of rows** → `TRUNCATE user_corners;` is the honest option. The data is unrecoverable in the new frame without knowing each row's originating lap offset, and losing a few operator annotations beats serving fabricated physics.
- **A meaningful population** → do NOT truncate. Add a `frame` column defaulting to `'legacy_absolute'`, have new writes stamp `'per_lap_zero'`, and normalise (or skip) legacy rows on read in `_user_corners_to_sections`. That is a separate change with its own migration and review — hold this deploy until it lands.

---

## 2 — Drain in-flight pipeline state

Jobs paused at `awaiting_corner_selection` hold old-frame corners in Redis (7200 s TTL). A mid-deploy resume mixes frames with no marker anywhere.

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T redis \
  sh -c 'for p in \"pipeline:corners:*\" \"pipeline:layout:*\" \"pipeline:ctx:*\"; do redis-cli --scan --pattern \"\$p\" | xargs -r redis-cli DEL; done'"
```

All **three** patterns matter:

- `pipeline:corners:*` and `pipeline:layout:*` — the paused-job corner/layout payloads.
- `pipeline:ctx:*` — **easy to miss.** The serialised `PipelineContext` carries `ctx.custom_corners` / `ctx.selected_corner_ids`, and the intermediate-state-expired fallback at `telemetry_tool/tasks/pipeline_tasks.py:993-1002` feeds them straight back into a **full re-run** as `_fallback_corners`. That path would inject old-frame user spans into a brand-new-frame analysis.

Confirm the queues are idle before deploying:

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T redis redis-cli LLEN pipeline"
```

---

## 3 — Deploy backend: REBUILD **ALL** SERVICES ⚠️

`docker-compose.prod.yml` has **seven** services built from the repo image, not one:

| Service | compose line |
|---|---|
| `api` | 5 |
| `celery-pipeline` | 92 |
| `celery-default` | 129 |
| `celery-onboarding` | 174 |
| `celery-endurance` | 230 |
| `celery-pipeline-long` | 278 |
| `celery-beat` | 314 |

**Rebuilding only `api` is the trap.** The resampler runs in the *workers*, not the API. Rebuild `api` alone and every worker keeps executing the OLD `resample_lap_by_distance`: new uploads keep producing old-frame data, and the mass reprocess in step 5 would run the **old** resampler — quietly reproducing the exact bug you just deployed a fix for, on your whole corpus.

Source is `COPY`'d into the image, so **`restart` alone changes nothing**. You must `build`.

```bash
cd /c/Users/Admin/lap_web-wt-distframe
scp -r telemetry_tool docker-compose.prod.yml root@46.225.227.24:/opt/lap-api/

ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build \
  api celery-pipeline celery-pipeline-long celery-default celery-onboarding celery-endurance celery-beat"

ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d \
  api celery-pipeline celery-pipeline-long celery-default celery-onboarding celery-endurance celery-beat"
```

Verify:

```bash
curl -fsS https://api.lap-coach.racing/healthz
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml ps"
```

Every worker must show a fresh `Up` timestamp. A worker still showing its pre-deploy uptime did not rebuild — go back.

---

## 4 — Deploy frontend (⚠️ ordering constraint)

```bash
cd /c/Users/Admin/lap_web-wt-distframe/lap-website && npm run cf:deploy
```

**Read this before you run it.**

Task 9 deleted `lapOffset` from `TheoreticalBestPanel.tsx` and the modulo wrap from `TrackMapView.tsx`. Those compensations were no-ops for correctly-framed data, which is why deleting them is right — a guarded no-op hides the next regression.

But **legacy persisted data is not merely offset, it is negative.** Legacy `theoretical_data.corner_coaching` spans were written through the `theo_d0` rebase (deleted in Task 5), which subtracted the **median lap's** absolute start from every span. For a corner belonging to an earlier lap that subtraction goes past zero, so persisted legacy `s_start` values are typically **negative**. With `lapOffset` gone, `clampedEnd < clampedStart` and **the driver's speed line vanishes from the corner panel** on any session that has not been reprocessed.

So either:

- **Preferred:** run step 5 (reprocess) immediately after — or before — the frontend deploy, keeping the window minutes rather than days; or
- **Accept the gap** knowingly, and tell support that un-reprocessed sessions render an empty corner speed trace until their reprocess lands.

There is no third option that keeps the compensation, because keeping it is what would hide the next frame regression.

---

## 5 — Reprocess

Use **`telemetry_tool/onboarding/reprocess.py`**. Its `_dispatch_build_reprocess(conn, session_ref)` (`:278`) is the verified single-session entrypoint: it mirrors `web/routes/jobs.py::retry(job_id)` — look up the original job's `workspace_id`/`file_path`, mint a fresh `job_id`, copy the `ingestion_jobs` row, seed a `PipelineContext`, then dispatch `tasks.pipeline_tasks.build_pipeline_chain(new_job_id).apply_async()`. That is the full ingest → analyze → finalize chain, which is the only thing that re-runs the resampler. `_dispatch_builds(conn, session_refs=[...])` (`:339`) wraps it per-session and swallows+logs individual failures.

Drive it from the stale list (`PIPELINE_VERSION` is now 3, so pre-fix sessions self-identify):

```bash
# Workspace-scoped (web/routes/versioning.py:43, filters on g.workspace_id),
# so run it per workspace with that workspace's token.
curl -fsS -H "Authorization: Bearer $TOKEN" \
  https://api.lap-coach.racing/api/v1/sessions/stale | jq '{current_version, count}'
```

Expect `current_version: 3` and a `count` covering every session processed before this deploy.

Reprocess in workspace-sized batches and watch the `pipeline` queue depth; a full-corpus dispatch will starve ordinary uploads.

> ### 🚫 Do NOT use `scripts/reprocess_theoretical.py`
> It imports `build_curvature_from_laps` from `pipeline.helpers` (`scripts/reprocess_theoretical.py:99`) — **that symbol does not exist in the tree** (verified: `hasattr(pipeline.helpers, "build_curvature_from_laps") is False`). The import is inside a `try`, so the script does not crash; it **no-ops on every session** and reports success. Running it will make you believe the corpus was repaired when nothing happened.

---

## 6 — What reprocessing repairs, and what it does NOT

### Repaired by reprocessing ✅

These are *corrupted*, not merely offset — a number-shifting migration would leave them wrong while making them look repaired.

- **`grip_map.distance_bins` + `bin_stats`** — under the old frame, laps 2..N were `np.clip`'d into the **terminal bin**, so the last bin held a whole session's samples and the rest held one lap's. Reprocessing rebuilds the bins from scratch.
- **`reference_lines`** — `_build_common_grid` medianed the per-lap starts/ends, producing a window belonging to the *middle* lap; `_interpolate_lap_onto_grid`'s `left=nan/right=nan` then NaN'd nine laps entirely, so a "10-lap median reference line" was **one lap**.
- **`corner_metrics` for laps 2..N** — `throttle_onset_m`, `brake_intensity`, `exit_accel_mps2` are NULL because the mask was empty.

### NOT repaired by reprocessing ❌

**`track_surfaces` / `track_surfaces_global`.** Their upserts merge on the exact rounded distance:

```sql
ON CONFLICT (track_id, distance_m, vehicle_class, condition, workspace_id)   -- persistence.py:155
ON CONFLICT (track_id, distance_m, vehicle_class, condition)                 -- persistence.py:281
```

`distance_m` is part of the merge key, so **old absolute bins and new 0-based bins do not collide — they coexist permanently** as two disjoint bin grids in one table. Reprocessing adds the new grid; it never removes the old one.

The read path does not error on this. `AggregateGrip.mu_at` (`telemetry_tool/track_surface/persistence.py:45-51`) is `np.interp(d, self.distance_bins, arr)`, and `np.interp` **clamps** outside the data range rather than raising — so a query against a table containing both grids returns a **flat μ** for every distance, indistinguishable from a legitimately uniform surface.

Fixing this requires **destructive re-aggregation**: delete the affected `(track_id, vehicle_class, condition)` rows and rebuild from reprocessed sessions. Plan it as separate work.

> **Read-path status:** this consumer is currently **dormant** — the unified optimal solver is gated behind `OPTIMAL_V2` (`telemetry_tool/pipeline/stages/s10_theoretical.py:516`), which is **not set in `docker-compose.prod.yml`**. So nothing reads the corrupted grid today. **The WRITE side is corrupting the table right now, though**, and it will keep doing so, so this cannot be deferred indefinitely — it must be resolved *before* `OPTIMAL_V2` is ever switched on.

---

## 7 — Do NOT bother flushing `chart:*`

Stated explicitly so nobody draws false confidence from an empty `DEL`:

**There is no chart cache.** `chart_cached`'s write path has never written anything. Every decorated endpoint returns via `api_utils.api_response`, which returns `(jsonify(body), status)` — a Flask **`Response`**, not a dict. `chart_cache.py`'s write branch only `json.dumps` a `dict`, so it hands the `Response` object straight to `redis.setex`, which rejects it, and the failure is swallowed at `logger.debug`. Nothing has ever been cached.

`chart:*` in prod Redis is therefore **empty**, and flushing it proves nothing about whether stale frames are being served. (The invalidation added by Task 10 is genuinely wired now — `_get_redis` was also fixed to work without a Flask app context, which Celery workers do not have — but it currently deletes an empty key space.)

Repairing the write path would **start** caching live endpoints, which is a behaviour change and deliberately out of scope for this correctness branch. It is documented in place at `telemetry_tool/web/chart_cache.py`.

---

## 8 — Verification

Pick **three** prod sessions that have completed reprocessing — ideally one kart, one car, one from a different track.

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  https://api.lap-coach.racing/api/v1/sessions/<SESSION_ID>/corners | jq '.data[] | {corner_id, s_start, s_end}'
```

**Pass criteria:**

1. Every `s_start` is `>= 0` and **below the lap length** (a kart lap is ~1.2 km; anything near 5 km is a lap-5 absolute span that did not get rebased). No negative values.
2. Per-lap corner metrics are populated **for laps 2..N**, not just lap 1:

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U lap -d lap -c \"SELECT lap_number, count(*), count(throttle_onset_m) FROM corner_metrics \
  WHERE session_id='<SESSION_ID>' GROUP BY 1 ORDER BY 1;\""
```

A row per lap with non-zero counts across the board. Lap 1 populated and laps 2..N empty is the pre-fix signature — if you see it, the worker running that session did not rebuild (go back to step 3).

3. Worker logs must be **quiet**: `grip_map: dropping N/M samples` should not appear on a healthy session. Its threshold is 5% of a lap's samples, so a real frame regression (~100% of a lap) is loud and ordinary lap-length variation is silent.

---

## 9 — CI note

`pytest telemetry_tool/tests/` **cannot complete** without `--continue-on-collection-errors`:

```bash
python -m pytest telemetry_tool/tests/ -q --continue-on-collection-errors
```

There are **11 pre-existing collection errors** in the tree (a missing `gamification` import, and a `test_track_surface` `__pycache__` basename collision). They are **unrelated to this branch** — they predate it and are untouched by it — but without the flag pytest aborts the whole run and CI will look broken for the wrong reason.

The branch's own suites run clean:

```bash
python -m pytest telemetry_tool/tests/test_distance_frame.py \
                 telemetry_tool/tests/test_distance_quality_gate_fence.py \
                 telemetry_tool/tests/test_grip_map.py \
                 telemetry_tool/tests/test_grip_pipeline.py -v --continue-on-collection-errors
```

There are also **4 pre-existing test failures** in the wider tree, all verified against the branch base and none caused by this work: `TestTheoreticalEndpoint::test_returns_theoretical_data`, `TestCornerPositionsEndpoint::test_returns_from_theoretical`, `test_phase3_integration.py::TestPipelineChainFlow::test_full_chain_happy_path` ("Worker entitlement denied"), and `test_post_launch_regression.py::TestEntitlements::test_free_plan_has_limited_analyses`.

---

## Known NOT fixed by this deploy

State these so nobody assumes otherwise:

- **The wrap-around corner stays broken in every frame.** `corner_detection.py:657-661` emits one merged region per closed circuit with `s_start > s_end`, so its `(d >= s_start) & (d <= s_end)` mask is empty regardless of frame. One corner per circuit remains dead.
- **Corners are still detected from one lap.** The prize is that the *choice* of lap stops mattering for coordinates; a lap-1 anomaly still defines the session's corner set. Consensus detection is separate work.
- **The `gate_advanced` distance-quality gate stays dead** — deliberately fenced by `telemetry_tool/tests/test_distance_quality_gate_fence.py`. Repairing it would start suppressing theoretical laps and coaching on sessions that currently emit them.
- **`apply_kart_traction_floor`'s dropped return** (`s09_physics.py:269`) is untouched — fixing it would raise the grip envelope on every kart session.
- **Track-surface `s` is not reconcilable by any rebase.** It is centreline arc length over the GT centreline; RaceChrono distance is GPS path length along the *driven* line. Different totals, different origins, error accumulating along `s`. That needs an explicit `s↔s` mapping, not an offset.
