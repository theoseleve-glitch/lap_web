# Grip Anchor (085) — Production Deploy Runbook

Authoritative deploy procedure for alembic revision **`085_grip_anchor`** (branch `feat/driving-pattern-recognition`, worktree `C:\Users\Admin\lap_web-wt-patterns`) → the LIVE `lap-coach.racing` platform.

> **You run this.** The `ssh`, the `scp` and the `docker compose` calls need your authenticated terminal; a sandboxed agent cannot reach the VPS.

VPS = `root@46.225.227.24:/opt/lap-api`.

**This is not a code fix. It is a procedure, and the procedure is the fix.** There is no automation on this platform that makes the ordering below happen by itself, and the failure mode when it does not happen is silent and destructive.

---

## 0 — ⛔ BLOCKING: confirm what production is ACTUALLY at

**Do not start until `alembic current` has been read off the live database with your own eyes.**

Session records indicate production may be at **078**, with **082** and **083 never deployed**. If that is true, 085 does not land on 084 — it lands on top of an unapplied chain, and `alembic upgrade head` will run every intervening revision (079 → 085) in one go, including the two security migrations from the customer-readiness work. That is a materially different deploy from "add four nullable columns", and it must be planned as one.

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T api \
  alembic -c telemetry_tool/alembic.ini current"
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

and **all three writers swallow it**:

| Writer | Behaviour on failure |
|---|---|
| `telemetry_tool/pipeline/stages/s15_persist.py:243` | logs a warning, continues |
| `telemetry_tool/tasks/pipeline_tasks.py:1161-1163` | logs a warning, rolls back, continues |
| `telemetry_tool/tasks/endurance_tasks.py:781-782` | **bare `except`, no log at all** |

The session then persists **zero** corner metrics. Not "the grip anchor is missing" — *the whole row is missing*: brake points, entry/apex/exit speeds, throttle onset, exit acceleration, time loss, coaching hints, and the legacy `grip_utilization`. None of it is recoverable without reprocessing the session, and nothing alerts. The user sees a session that uploaded successfully and simply has no corner data.

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

Both celery worker sets write `corner_metrics`. Stop all six celery services — not just the pipeline ones — so nothing can attempt a write against a half-migrated schema.

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
  alembic -c telemetry_tool/alembic.ini upgrade head"
```

Read the output. A non-zero exit or a traceback here means **stop** — do not start the workers.

---

## 3 — ⛔ VERIFY BEFORE STARTING ANYTHING

This gate is the entire point of the runbook. Both checks must pass.

```bash
# 1. the revision
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T api \
  alembic -c telemetry_tool/alembic.ini current"
```

Expected: **`085_grip_anchor (head)`**. Anything else — including an empty line — is a failed deploy.

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

Also confirm the writes are not silently failing:

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml logs --tail=200 \
  celery-pipeline | grep -i 'corner_metric\|grip_anchor\|UndefinedColumn'"
```

---

## 5 — Rollback

The migration is four **nullable** columns, so `downgrade` is clean — but only if the new code is gone first, since it names the columns unconditionally.

```bash
# 1. stop the writers
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml stop \
  celery-pipeline celery-pipeline-long celery-default celery-onboarding celery-endurance celery-beat api"

# 2. restore the previous image/code, THEN
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml run --rm api \
  alembic -c telemetry_tool/alembic.ini downgrade 084_merge_chain_ab"
```

Rolling the schema back while the new code is still serving reproduces §1's silent total loss exactly. Order matters in both directions.

---

## 6 — SQLite is a separate fix, already in this branch

`USE_PG` defaults to `"0"` (`telemetry_tool/web/config.py:60`), so the desktop app, the datalogger and local dev all run SQLite, where alembic is not involved at all. Those databases are migrated by `telemetry_tool/db/migrate.py`'s **Phase 37** ALTER block, added on this branch. Nothing in this runbook applies to them, and no operator action is needed: `ensure_schema` runs on connection open and the block is idempotent.
