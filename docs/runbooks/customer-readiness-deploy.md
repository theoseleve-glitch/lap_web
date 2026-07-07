# Customer-Readiness Hardening — Production Deploy Handoff

Authoritative deploy runbook for the **`feat/customer-readiness`** bundle → the LIVE `lap-coach.racing` platform. Produced from a platform audit + two adversarial review cycles.

> **You run this** — backend `scp` and frontend `wrangler` deploys need your authenticated terminal; a sandboxed agent cannot reach them. Branch is complete + merge-ready at HEAD `cbe90a6` (worktree `C:\Users\Admin\lap_web-wt-readiness`, branch `feat/customer-readiness`).

## What this bundle is
`feat/customer-readiness` = the deployed prod base (`feat/launch-canonical` @ alembic **077**) + the **three conflict-free hardening branches** merged (`webapp-hardening` → `endurance-finish` → `feeling-scoring`) + the fix commits from two review cycles + **a full backend security sweep's fixes**. It carries a **single alembic head `083_ingest_policy_missing_ok`** — a linear chain adding exactly THREE migrations on top of prod's 077: `081_feeling_competition` → `082_user_corners_rls` → `083_ingest_policy_missing_ok` (no fork within the branch). Both hardening review cycles' findings are closed (the critical endurance-reconciler HIGH verified directly), and a subsequent exhaustive security sweep + adversarial re-review confirmed all five of its findings closed.

**What ships (customer impact):**
- **Billing IDOR closed** (`b83b894`, frontend) — was: anyone with a customer's email could open their Stripe portal + change their plan unauthenticated. **Highest-priority item.**
- **Billing correctness** — guest-checkout `user_id` binding, case-insensitive webhook email match, orphaned-entitlements sweep (guarded so it never clobbers an active subscription → no double-charge), re-subscriber (past_due/canceled) auto-reactivation, and the reconcile job no longer mass-cancels the subscriber base on a transient Stripe error.
- **Endurance queue isolation + robustness** — own `endurance` queue/worker (can't starve ordinary uploads), explicit hard>soft limits, compute-budget visibility + per-workspace cap, a run-start-anchored stuck-job reconciler, and a bounded redelivery guard.
- **Solver DoS + entitlement** — track-surface + OCP-corner behind feature/quota/rate limits and per-request caps; long-timeout (b2b) pipeline jobs isolated to a `pipeline_long` queue so they can't starve the shared 2-slot pipeline queue.
- **Yaw honesty fix** (`ccca259`) — endurance robustness score no longer bakes in a hardcoded-0 input.
- Plus the merged W1 hardening: admin-route auth, Redis fail-open alerting, resident-storage cap.
- **Backend security sweep fixes (all pre-existing, live-in-prod, now closed):**
  - **Two cross-tenant IDOR blockers** (`a76c7ea`): `/api/v1/sessions/<id>/theoretical*` read another tenant's raw telemetry off disk by session_id (no ownership check); `user_corners` (a fork table that never got RLS) allowed cross-tenant read+write of corner GPS. Fixed with server-side ownership 404 guards **and** RLS migration `082_user_corners_rls` (ENABLE+FORCE+WITH CHECK, fails closed on unset GUC).
  - **`/api/ingest/*` unauth cross-tenant read** (`a0979cf`): dead legacy blueprint (zero callers, superseded by `/api/v1/jobs`), now blocked by `legacy_guard` in prod + auth-middleware coverage + workspace-scoped JobStore + policy migration `083_ingest_policy_missing_ok`.
  - **Auth brute-force / lockout** (`9266a53` + degraded-mode follow-up): rate-limit + lockout no longer fully fail-open on a Redis outage (bounded per-worker throttle); the login-lockout is de-duplicated and IP-scoped so it's no longer a 3-request account-DoS.
- **Frontend readiness fixes (ship with the frontend `cf:deploy`, step 4):** a full read-only frontend sweep found the webapp customer-ready with no blockers (money path correct, billing IDOR fix verified on both handlers, no client secrets/SSRF/XSS). Four non-blocker fixes: open-redirect via `?redirect=` on `/login`+`/register` closed with a same-origin `getSafeRedirect()` (`7e2e9f6`); plan-switch route now returns an honest `501` instead of fake success; the broken orphaned `/billing` page now redirects to the working `/app/account/billing`; dev showcase routes `noindex`ed (`ad9b040`).

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
Expect `077_stripe_pending_entitlements` (this branch adds exactly THREE migrations on top, linear: `081_feeling_competition` → `082_user_corners_rls` → `083_ingest_policy_missing_ok`). **STOP** if prod is off the 077 line — reconcile before proceeding. Also confirm the onboarding branch's competing `081` is NOT being deployed to the same DB concurrently (that forks at 081 — see the Chain A note).

### 2 — Ship backend + compose + migrate
```bash
cd /c/Users/Admin/lap_web-wt-readiness
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
scp docker-compose.prod.yml Dockerfile root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api celery-pipeline celery-default celery-beat celery-endurance celery-pipeline-long"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic upgrade head && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
**Gate:** `alembic current` → `083_ingest_policy_missing_ok (head)`. The three migrations are non-destructive on Postgres 16: `081` = `CREATE TABLE`s (reflection + session_competitors); `082` = enable RLS + policy on the existing `user_corners` table (writes scoped via `sessions.workspace_id`); `083` = replace the `ingestion_jobs` RLS policy with the `missing_ok` GUC form. **After `082`/`083`, run the PG-gated RLS test against the live/disposable PG** (`TELEMETRY_PG_URL_TEST=... pytest -k "user_corners_rls or ingest"`) — dev had no Postgres, so this is the first real exercise of the two new policies; confirm a cross-workspace `user_corners` row is actually blocked (not just the app-level guard).
*Rollback (migration):* `alembic downgrade 077_stripe_pending_entitlements` (each of 083→082→081 has a clean downgrade). *Rollback (code):* re-`scp` the prior `telemetry_tool/` + compose, rebuild, `up -d`.

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
- **⚠️ VERIFY AT DEPLOY — client-IP hop count (`api.lap-coach.racing`).** The auth per-IP rate-limit + (email,IP) lockout depend on `request.remote_addr` being the real client IP. The app sets ProxyFix `x_for=1` (correct for a single client→Caddy→app hop). **If `api.lap-coach.racing` is also Cloudflare orange-clouded (2 hops), `x_for=1` yields a CF edge IP and all customers collapse onto a few shared IP buckets** (cross-customer throttling; per-IP isolation lost). Confirm the real hop count; if CF-proxied, set `x_for=2` or derive the client IP from `CF-Connecting-IP`. A startup log line records the resolved IP source to help verify.
- **Distributed credential-stuffing (accepted, compensated).** The lockout is now IP-scoped (fixes the account-DoS), so there is no hard email-global lock; a many-IP attacker gets a few guesses per IP against one email. Compensating controls: per-IP rate limit, a soft email-scoped **detection alert** (on-call actionable), and the **edge Cloudflare rate-rule on `/auth/login`** (a USER action — add it). A CAPTCHA/step-up flow is the fuller follow-up.
- **Degraded-mode auth throttle is per-worker (accepted).** When Redis is down the bound is ~5/60s *per gunicorn worker*, so the fleet-wide ceiling scales with worker count. By design (no cross-worker coordination during an infra incident); the buckets are size-capped so a Redis outage can't be turned into a memory-exhaustion crash.

## Separate track — Chain A (honesty layer + onboarding), NOT in this bundle
- **#3 racing-line honesty gate (BLOCKER)** — the deployed `/optimal-line` route serves `pipeline.optimal_line` with no trust gate; the fix is the **honesty layer** (`decide_tier`, migrations 078–080), which lives on the separate `feat/geometry-factory`→`feat/honesty-layer`→`feat/track-onboarding-loop` lineage — NOT here. Resolving #3 = deploying that lineage + wiring the route to `decide_tier`.
- **⚠️ `081` migration fork:** Chain A's `081_track_onboarding_requests`/`082` and this bundle's `081_feeling_competition` both branch off `077`. Deploying BOTH to one DB later fails `alembic upgrade head` ("multiple heads"). Before Chain A ships, renumber Chain A's 081/082 → 082/083 (corrected `down_revision`) or add an alembic merge revision. Check prod's real head first.
- The onboarding loop has its own deploy runbook (`docs/runbooks/track-onboarding-deploy.md`).
