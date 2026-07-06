# Customer-Readiness Hardening — Production Deploy Handoff

Authoritative deploy runbook for the **`feat/customer-readiness`** bundle → the LIVE `lap-coach.racing` platform. Produced from a platform audit + two adversarial review cycles.

> **You run this** — backend `scp` and frontend `wrangler` deploys need your authenticated terminal; a sandboxed agent cannot reach them. Branch is complete + merge-ready at HEAD `cbe90a6` (worktree `C:\Users\Admin\lap_web-wt-readiness`, branch `feat/customer-readiness`).

## What this bundle is
`feat/customer-readiness` = the deployed prod base (`feat/launch-canonical` @ alembic **077**) + the **three conflict-free hardening branches** merged (`webapp-hardening` → `endurance-finish` → `feeling-scoring`) + **8 new fix commits**. It carries a **single alembic head `081_feeling_competition`** (no fork within the branch). Both review cycles' findings are closed; the one critical HIGH (endurance reconciler) was verified directly.

**What ships (customer impact):**
- **Billing IDOR closed** (`b83b894`, frontend) — was: anyone with a customer's email could open their Stripe portal + change their plan unauthenticated. **Highest-priority item.**
- **Billing correctness** — guest-checkout `user_id` binding, case-insensitive webhook email match, orphaned-entitlements sweep (guarded so it never clobbers an active subscription → no double-charge), re-subscriber (past_due/canceled) auto-reactivation, and the reconcile job no longer mass-cancels the subscriber base on a transient Stripe error.
- **Endurance queue isolation + robustness** — own `endurance` queue/worker (can't starve ordinary uploads), explicit hard>soft limits, compute-budget visibility + per-workspace cap, a run-start-anchored stuck-job reconciler, and a bounded redelivery guard.
- **Solver DoS + entitlement** — track-surface + OCP-corner behind feature/quota/rate limits and per-request caps; long-timeout (b2b) pipeline jobs isolated to a `pipeline_long` queue so they can't starve the shared 2-slot pipeline queue.
- **Yaw honesty fix** (`ccca259`) — endurance robustness score no longer bakes in a hardcoded-0 input.
- Plus the merged W1 hardening: admin-route auth, Redis fail-open alerting, resident-storage cap.

## ⚠️ Do first
- **Rotate the leaked Netlify PAT** (theos.eleve) — see the onboarding runbook.
- **Confirm the live frontend commit** before deploying frontend: `wrangler deployments list` for the `lap-website` Worker (its `wrangler.jsonc` carries no VCS binding; the local checkout is stale). The IDOR fix is a *frontend* change — deploy it on top of the actual live commit.
- **Do NOT `make deploy`** (ships only 3 files). Use the explicit `scp` below.
- Two NEW Celery queues have consumers that MUST be running for their traffic: **`-Q endurance`** (`celery-endurance`) and **`-Q pipeline_long`** (`celery-pipeline-long`). Both are defined in `docker-compose.prod.yml`+`.staging.yml`. If the app deploys before these workers are up, endurance/b2b jobs park unconsumed.

VPS = `root@46.225.227.24:/opt/lap-api`.

## Deploy sequence
### 1 — Prod alembic head sanity (read-only)
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
Expect `077_stripe_pending_entitlements` (this branch adds exactly one migration on top: `081_feeling_competition`). **STOP** if prod is off the 077 line — reconcile before proceeding.

### 2 — Ship backend + compose + migrate
```bash
cd /c/Users/Admin/lap_web-wt-readiness
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
scp docker-compose.prod.yml Dockerfile root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api celery-pipeline celery-default celery-beat celery-endurance celery-pipeline-long"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic upgrade head && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
**Gate:** `alembic current` → `081_feeling_competition (head)`. It's `CREATE TABLE`s (reflection + session_competitors) — non-destructive on Postgres 16.
*Rollback (migration):* `alembic downgrade 077_stripe_pending_entitlements`. *Rollback (code):* re-`scp` the prior `telemetry_tool/` + compose, rebuild, `up -d`.

### 3 — Restart workers INCLUDING the two new queue consumers, then verify
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default celery-beat celery-endurance celery-pipeline-long"
ssh root@46.225.227.24 "cd /opt/lap-api && for s in celery-endurance celery-pipeline-long; do echo \"== \$s ==\"; docker compose -f docker-compose.prod.yml logs --tail=40 \$s | grep -i 'queues\|-Q'; done"
```
**Gate:** `celery-endurance` boot log lists `endurance`; `celery-pipeline-long` lists `pipeline_long`. (Same check the onboarding runbook uses for `-Q onboarding` — check the log, not just liveness.)

### 4 — Deploy frontend (closes the IDOR)
After confirming the live commit (Do-first), from `lap-website/` on the customer-readiness tree: `npm run cf:deploy` (opennextjs-cloudflare build + deploy). Backend must be live first (step 3) since the new frontend calls the new/changed billing + scores + endurance API shapes. Then `wrangler deployments list` to confirm the Worker updated.

### 5 — Real-PG smoke (dev had no Postgres — first live-PG exercise of the new SQL)
Trigger a test in each area against a safe PG: a guest-checkout-then-signup (webhook links case-insensitively; sweep does NOT clobber an active sub), an endurance submit (own queue, budget cap), and a track-surface/OCP call as a locked user (rejected). Watch Sentry for `pending entitlement conflict` alerts.

## Accepted / residual risks (carry into on-call)
- **Sentry billing alerts are load-bearing.** A pending-entitlement *conflict* (different active sub already attached) is deliberately held for manual reconcile, not auto-overwritten. On-call must watch `pending entitlement conflict` / `already has a subscription attached`. (Re-alerts are deduped to once/day per row.)
- **`pipeline_long` deploy-ordering** (above) and it's **invisible to the operator queue-depth dashboard** (`admin/metrics_collector.py` only reads `llen('pipeline')`) — the DB-level queue-depth alert still fires; consider adding a `queue_pipeline_long` metric.
- **`celery-pipeline-long --concurrency=1`** serializes two concurrent b2b uploads from the same tenant (~65 min) — bump to 2 if concurrent b2b is expected.
- **OCP-corner concurrency is bounded by the `analyze` rate limit** (5–50/hr), not a hard live concurrency cap — a big improvement over the old 60–300/min, watch a single b2b tenant firing many solve loops.
- **Compute-budget cap is soft (TOCTOU)** — scard→sadd non-atomic; two simultaneous same-workspace submits can both pass. Same semantics as the pre-existing PG soft-caps; single-worker serialization limits real impact.
- **Endurance active-slot** now clears in `finally` (normal exceptions) and the reconciler self-heals SIGKILL cases within one sweep.

## Separate track — Chain A (honesty layer + onboarding), NOT in this bundle
- **#3 racing-line honesty gate (BLOCKER)** — the deployed `/optimal-line` route serves `pipeline.optimal_line` with no trust gate; the fix is the **honesty layer** (`decide_tier`, migrations 078–080), which lives on the separate `feat/geometry-factory`→`feat/honesty-layer`→`feat/track-onboarding-loop` lineage — NOT here. Resolving #3 = deploying that lineage + wiring the route to `decide_tier`.
- **⚠️ `081` migration fork:** Chain A's `081_track_onboarding_requests`/`082` and this bundle's `081_feeling_competition` both branch off `077`. Deploying BOTH to one DB later fails `alembic upgrade head` ("multiple heads"). Before Chain A ships, renumber Chain A's 081/082 → 082/083 (corrected `down_revision`) or add an alembic merge revision. Check prod's real head first.
- The onboarding loop has its own deploy runbook (`docs/runbooks/track-onboarding-deploy.md`).
