# Grip Anchor (085) + Driving Events (086) — Production Deploy Runbook

Authoritative deploy procedure for alembic revisions **`085_grip_anchor`** and **`086_driving_events`** (branch `feat/driving-pattern-recognition`, worktree `C:\Users\Admin\lap_web-wt-patterns`) → the LIVE `lap-coach.racing` platform.

**Both revisions ship together and are deployed together.** 086 is a child of 085 and the code that writes to it ships in the same image. Read "085" anywhere below as "the 085→086 pair" unless a step names one specifically.

> **You run this.** The `ssh`, the `scp` and the `docker compose` calls need your authenticated terminal; a sandboxed agent cannot reach the VPS.

VPS = `root@46.225.227.24:/opt/lap-api`.

**This is not a code fix. It is a procedure, and the procedure is the fix.** There is no automation on this platform that makes the ordering below happen by itself, and the failure mode when it does not happen is silent and destructive.

---

## 0 — ⛔ BLOCKING: confirm what production is ACTUALLY at

**Do not start until `alembic current` has been read off the live database with your own eyes.**

Session records indicate production may be at **078**, with **082** and **083 never deployed**. If that is true, 085 does not land on 084 — it lands on top of an unapplied chain, and `alembic upgrade head` will run every intervening revision (079 → 085) in one go, including the two security migrations from the customer-readiness work. That is a materially different deploy from "add four nullable columns", and it must be planned as one.

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T api \
  sh -c 'cd /app/telemetry_tool && alembic current'"
```

Then reconcile against the local chain:

```bash
# every revision between what prod reports and 085
git log --oneline -- telemetry_tool/alembic/versions/ | head -20
```

| `alembic current` reports | What to do |
|---|---|
| `085_grip_anchor` | Already applied. Skip to §4 (verification) — do not re-run. |
| `084_merge_chain_ab` | The clean case this runbook assumes. Proceed to §1. |
| `078` (or anything below 084) | **STOP.** Read every intervening revision before proceeding. This is no longer a four-column deploy. Get explicit sign-off on the whole chain. |
| Empty / error | The `alembic_version` table is missing or unreadable. Do not guess — diagnose first. |

Note: `git log` on the branch tells you what SHOULD be deployed, not what IS. Only the query above is ground truth.

---

## 1 — Why the ordering matters (read before running anything)

`telemetry_tool/db/queries.py:749` and `:756` name the four new columns **unconditionally** in `INSERT_CORNER_METRIC`. There is no feature flag and no conditional column list. So if new code serves before 085 is applied, every corner-metrics write raises:

```
UndefinedColumn: column "grip_anchor_tier" of relation "corner_metrics" does not exist
```

and, before this branch, **all three writers swallowed it**:

| Writer | Behaviour on failure |
|---|---|
| `telemetry_tool/pipeline/stages/s15_persist.py:353` | **SAVEPOINT-contained on this branch** — was: logs a warning, continues (see §1b) |
| `telemetry_tool/tasks/pipeline_tasks.py:1161-1163` | logs a warning, rolls back, continues |
| `telemetry_tool/tasks/endurance_tasks.py:781-782` | **bare `except`, no log at all** |

The session then persists **zero** corner metrics. Not "the grip anchor is missing" — *the whole row is missing*: brake points, entry/apex/exit speeds, throttle onset, exit acceleration, time loss, coaching hints, and the legacy `grip_utilization`. None of it is recoverable without reprocessing the session, and nothing alerts.

⚠ **CORRECTED (2026-08-06). On the `s15_persist` path it is worse than "a session with no corner data" — THERE IS NO SESSION AT ALL.** An earlier revision of this line said the user sees a successful upload missing its corner data. That is true only of the two celery paths, which commit per step. `s15_persist` is ONE transaction, so on PostgreSQL the failed corner-metrics INSERT aborts it and the later `COMMIT` is a silent `ROLLBACK` — laps, GPS traces, score details, condition phases, theoretical data and the session row itself all disappear.

Proven on a real PostgreSQL 16 against the shipped code with 085's four columns dropped: `run_persist_to_db` left `sessions / laps / gps_traces / score_details / condition_phases / driving_events` **all at 0 rows**.

The code-side half is fixed on this branch — `_persist_corner_metrics` now runs inside a SAVEPOINT (`_write_in_savepoint`) so the failure is contained and everything else still commits, and if the savepoint itself cannot be taken the exception is re-raised rather than swallowed, which makes the failure loud instead of silent. **That is a containment, not a licence to deploy out of order:** with the columns missing you still lose every corner metric in the window, unrecoverably without reprocessing.

### 1b — 086 has the SAME ordering hazard, and the SAME blast radius

`086_driving_events` creates a whole TABLE, and `db/queries.py`'s
`INSERT_DRIVING_EVENT` names it unconditionally. Code serving before 086 is
applied therefore raises on every session that produces events:

```
UndefinedTable: relation "driving_events" does not exist
```

**BOTH MIGRATIONS HAVE THE SAME BLAST RADIUS — it is a property of the WRITER, not of which migration is missing.** An earlier revision of this table attributed whole-session loss to 086 alone; that was wrong. What decides the cost is the transaction shape of the path doing the writing:

| Writer | Transaction shape | What a failed 085 **or** 086 write costs |
|---|---|---|
| `pipeline/stages/s15_persist.py` | **ONE** transaction: a single `conn.commit()` at the end, a single `conn.rollback()` in the handler, and psycopg2 does not autocommit | Laps, GPS traces, score details, condition phases, theoretical data, reference line, corner metrics, driving events, driver progression, weather timeline, **and the `sessions` row itself** — all of it |
| `tasks/pipeline_tasks.py` steps 6 / 6b | its own `commit()`/`rollback()` per step | that step's table only |
| `tasks/endurance_tasks.py` steps 6 / 6b | its own `commit()`/`rollback()` per step | that step's table only |

Both s15 child writes are now SAVEPOINT-guarded on this branch, so a failure of either is contained. Note also that under the orchestrator, `pipeline/helpers.py`'s `_safe_step` never re-raises, so even the loud "savepoint unavailable" path does not stop the run — it records a step error and continues. Read the step errors, not just the exit status.

The s15 mechanism: the write fails, PostgreSQL marks the transaction aborted,
the exception is caught and logged as a WARNING, and the later `COMMIT` in an
aborted block is a **silent `ROLLBACK`**. The operator sees one warning line
naming only driving events; the session is empty.

**The code-side half of this is fixed on this branch** —
`_persist_driving_events` now wraps its write in a `SAVEPOINT` and rolls back
to it, so an 086-missing failure can no longer poison the outer transaction
(and if the savepoint itself cannot be taken, the exception is re-raised
rather than swallowed, so the failure is loud instead of silent). **That is a
containment, not a licence to deploy out of order.** Run the migration first
anyway: with 086 missing you still lose every driving event for every session
processed in the window, unrecoverable without reprocessing.

Note `s15_persist` runs under `USE_PG=0` **or** with `force_persist=True` —
which is exactly what the endurance path passes. The single-transaction shape
is therefore reachable in production.

---

### Four things that make a silent partial deploy possible

1. **`init_pg` swallows migration failures.** `telemetry_tool/web/db_pg.py:421-424` catches every exception from `command.upgrade(cfg, "head")` and logs `"Alembic upgrade failed (app continues)"` at WARNING. The API then starts and serves normally against an unmigrated database. **A healthy-looking API is not evidence that 085 applied.**
2. **`docker-compose.prod.yml` has no migration service.** There is no one-shot `migrate` container and no init container. Migrations happen only as a side effect of an API worker booting.
3. **The celery workers never run migrations at all.** `init_pg()` is called from exactly one place — `telemetry_tool/web/app.py:301`, inside `create_app()`. The six celery services run `celery -A telemetry_tool.celery_app worker`, which never constructs the Flask app. And `insert_corner_metrics` (`web/repos/score_repo.py`) is reached from `pipeline_tasks.py` and `endurance_tasks.py` — i.e. **the writes happen in the processes that cannot migrate**.
4. **Up to 8 API workers race the upgrade at boot.** `gunicorn.conf.py:31` sets `preload_app = False`, so each worker builds its own app and each one calls `init_pg()`; `workers` is `min(cpu_count * 2 + 1, 8)` (`gunicorn.conf.py:10`). Concurrent `alembic upgrade head` runs against one database is not a designed path — and per (1), whichever ones lose simply log a warning.

Scaling the workers to zero first is what removes (3) and (4) from the picture. Verifying `alembic current` afterwards is what removes (1) and (2).

---

## 2 — Deploy

### 2.1 Ship the code (do NOT start anything yet)

```bash
# from the worktree
scp -r telemetry_tool root@46.225.227.24:/opt/lap-api/
scp docker-compose.prod.yml root@46.225.227.24:/opt/lap-api/
```

### 2.2 Stop every writer

Both celery worker sets write `corner_metrics` **and `driving_events`**. Stop all six celery services — not just the pipeline ones — so nothing can attempt a write against a half-migrated schema.

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml stop \
  celery-pipeline celery-pipeline-long celery-default celery-onboarding celery-endurance celery-beat"

# confirm they are actually down before continuing
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml ps"
```

Leave `api` running for now if you want uploads to keep queueing; the queued work will drain after §3. If you would rather take a hard window, stop `api` too.

### 2.3 Rebuild every image that carries application code

**Seven services share `build: .`** — `api`, `celery-pipeline`, `celery-pipeline-long`, `celery-default`, `celery-onboarding`, `celery-endurance`, `celery-beat`. A rebuild that misses one leaves that service running the OLD code against the NEW schema, or the new code against the old schema, depending on which side you got wrong. Rebuild them together:

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build \
  api celery-pipeline celery-pipeline-long celery-default celery-onboarding celery-endurance celery-beat"
```

### 2.4 Apply the migration explicitly

Do not rely on `init_pg`. Run it yourself, in the foreground, where a failure is visible:

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml run --rm api \
  sh -c 'cd /app/telemetry_tool && alembic upgrade head'"
```

Read the output. A non-zero exit or a traceback here means **stop** — do not start the workers.

---

## 3 — ⛔ VERIFY BEFORE STARTING ANYTHING

This gate is the entire point of the runbook. Both checks must pass.

```bash
# 1. the revision
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T api \
  sh -c 'cd /app/telemetry_tool && alembic current'"
```

Expected: **`086_driving_events (head)`**. `085_grip_anchor` alone means the chain stopped half way — the corner-metric columns exist but the driving-events table does not, which is exactly §1b's state. Anything else — including an empty line — is a failed deploy.

```bash
# 2. the columns really exist, in the real table
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U telemetry -d telemetry -c \"SELECT column_name, data_type FROM information_schema.columns \
  WHERE table_name='corner_metrics' AND column_name LIKE 'grip_anchor%' ORDER BY column_name;\""
```

Expected: exactly four rows —

| column_name | data_type |
|---|---|
| `grip_anchor_baseline_g` | `double precision` |
| `grip_anchor_pct` | `double precision` |
| `grip_anchor_reason` | `text` |
| `grip_anchor_tier` | `text` |

Fewer than four rows means a partial apply. Do not start the workers.

```bash
# 3. the 086 table exists, with its unique key and its RLS policy
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U telemetry -d telemetry \
  -c \"SELECT to_regclass('public.driving_events') AS tbl;\" \
  -c \"SELECT conname FROM pg_constraint WHERE conrelid='driving_events'::regclass AND contype='u';\" \
  -c \"SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='driving_events';\" \
  -c \"SELECT polname FROM pg_policy WHERE polrelid='driving_events'::regclass;\""
```

Expected, all four: `tbl` = `driving_events` (not NULL);
`uq_driving_events_session_lap_corner_event`; `t | t`;
`driving_events_tenant_isolation`.

A NULL `tbl` is §1b's failure waiting to happen. A missing unique constraint
means every reprocess DOUBLES the table (nothing deletes event rows before
rewriting) and `INSERT OR REPLACE` has no conflict target to translate to on
PostgreSQL. An `f` in either RLS column, or a missing policy, is a **tenancy**
defect — stop and fix before starting the workers.

### Only now, start the workers

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d \
  api celery-pipeline celery-pipeline-long celery-default celery-onboarding celery-endurance celery-beat"
```

---

## 4 — Post-deploy verification

Process one real session and confirm the columns are being written, not merely present.

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U telemetry -d telemetry -c \"SELECT grip_anchor_tier, count(*), \
  round(min(grip_anchor_pct)::numeric,2) AS min_pct, \
  round(max(grip_anchor_pct)::numeric,2) AS max_pct \
  FROM corner_metrics WHERE grip_anchor_tier IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;\""
```

What to expect, and what each outcome means:

| Result | Reading |
|---|---|
| A mix of `session_envelope_ellipse_fitted` and `driver_best_session` | Normal. On the `OK_R4.csv` reference session the split is 57/15. |
| `max_pct` above 100 | **Expected, not a bug.** The baseline is a p95 percentile, so exceedance is normal and diagnostic. The reference session's median is 101.51%. Nothing caps this value and nothing should. |
| Only `refused` | The anchor is degrading on every corner-lap. Query `grip_anchor_reason` — the taxonomy exists precisely so this is diagnosable. Not a rollback trigger on its own. |
| **Zero rows at all** | ⛔ Corner metrics are not being written. Check the celery logs for the swallowed exception described in §1 and re-verify §3. |

And the same for 086 — that events are being WRITTEN, not merely writable:

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U telemetry -d telemetry -c \"SELECT event_type, validity, count(*), \
  round(min(time_cost_s)::numeric,3) AS min_cost, round(max(time_cost_s)::numeric,3) AS max_cost \
  FROM driving_events GROUP BY 1,2 ORDER BY 3 DESC;\""
```

| Result | Reading |
|---|---|
| Four `event_type` values, nearly all `validity='measured'` | Normal. The `OK_R4.csv` reference session gives over_slowing 44 / late_throttle 56 / envelope_under_use 34 / re_braking 5. |
| `envelope_under_use` rows with `validity='not_measurable'` | **Expected, not a bug.** That is the deliberate refusal on a self-referential (tier-2) grip anchor; `reason` names it. |
| `max_cost` above ~1 s on a short circuit | Suspicious — a window/reference defect rather than driving. Not a rollback trigger; investigate. |
| **Zero rows at all** | ⛔ Either 086 is missing (re-check §3) or every detector read `insufficient`. Query `sessions.analysis_json -> 'driving_events_capability'` for the session: it is exactly the record that tells "clean session" apart from "could not measure". |

Also confirm the writes are not silently failing:

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml logs --tail=200 \
  celery-pipeline | grep -i 'corner_metric\|grip_anchor\|driving event\|UndefinedColumn\|UndefinedTable'"
```

---

## 5 — Rollback

085's migration is four **nullable** columns and 086's is a new table, so
both `downgrade`s are clean — but only if the new code is gone first, since it
names the columns and the table unconditionally.

**⚠ 086's `downgrade` DROPS THE TABLE.** Every driving event written since the
deploy is destroyed and recoverable only by reprocessing those sessions.
Decide deliberately which rollback you are doing: code-only (leave the schema
— old code never names either, so both are inert) or schema as well.

```bash
# 1. stop the writers
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml stop \
  celery-pipeline celery-pipeline-long celery-default celery-onboarding celery-endurance celery-beat api"

# 2. restore the previous image/code, THEN
# 3. CODE-ONLY ROLLBACK (preferred): stop here. The schema stays; old code
#    names neither the grip_anchor columns nor driving_events, so both are
#    inert and no data is destroyed.

# 3-alt. SCHEMA ROLLBACK TOO — this DESTROYS every driving_events row:
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml run --rm api \
  sh -c 'cd /app/telemetry_tool && alembic downgrade 084_merge_chain_ab'"
```

Rolling the schema back while the new code is still serving reproduces §1's silent total loss exactly. Order matters in both directions.

---

## 6 — SQLite is a separate fix, already in this branch

`USE_PG` defaults to `"0"` (`telemetry_tool/web/config.py:60`), so the desktop app, the datalogger and local dev all run SQLite, where alembic is not involved at all. Those databases are migrated by `telemetry_tool/db/migrate.py`'s **Phase 37** ALTER block (085's four columns) and by `db/schema.py`'s `PHASE_25_TABLES` `CREATE TABLE IF NOT EXISTS` (086's table), both added on this branch. The split is deliberate and is the lesson 085 paid for: `CREATE TABLE IF NOT EXISTS` in `schema.py` DOES create a new table on an existing database, but it is a **no-op for adding a column to a table that already exists** — which is why 085's columns needed the separate idempotent `ALTER` block in `migrate.py`. A future migration adding a COLUMN must do both; one adding a TABLE needs only `schema.py`. Nothing in this runbook applies to them, and no operator action is needed: `ensure_schema` runs on connection open and the block is idempotent.
