# Chain A Consolidated — Production Deploy Handoff (honesty layer + onboarding + racing-line gate)

Authoritative umbrella runbook for the **`feat/chain-a-consolidated`** branch (worktree `C:\Users\Admin\lap_web-wt-chain-a`). This is the migration-safe consolidation that lets the honesty/onboarding lineage ship without the `081` fork breaking `alembic upgrade head`.

> **You run this** — backend `scp` + `alembic` and the Netlify annotator publish need your authenticated terminal.

## What this branch is
`feat/chain-a-consolidated` = the deployed prod base (`feat/launch-canonical` @ 077) + **all of Chain B** (`feat/customer-readiness`: billing/endurance/solver hardening + the backend security sweep + frontend fixes) + **Chain A** merged on top:
- **Honesty layer** — migrations `078_track_racing_lines`, `079_track_geometry_audit`, `080_racing_line_honesty`; `track_surface/honesty.py` `decide_tier`, geometry gates, GT validation.
- **Track-onboarding loop** — migrations `081_track_onboarding_requests`, `082_onboarding_email_count`; `telemetry_tool/onboarding/*`, `tasks/onboarding_tasks.py`, `web/routes/onboarding_routes`, the `onboarding` Celery queue.
- **#3 racing-line honesty gate** — `web/routes/data_v2.py::get_optimal_line` now returns a drawable line only when `is_drawable_as_line(tier)`; degrades otherwise (fail-safe).
- **`084_merge_chain_ab`** — the empty merge revision that joins the two heads.

Integration commits: `fe29383` (onboarding merge) → `7d69120` (#3 merge) → `b414d43` (084). Merge tests green (onboarding 202, #3 9, honesty 13, Chain B sanity 41 — the one `test_rate_limit` failure is pre-existing, reproduced on the pre-merge commit).

## The migration reconciliation (the whole point)
The fork was at **077**, which had two children: `081_feeling_competition` (Chain B) and `078_track_racing_lines` (Chain A). Deploying both to one DB without a join makes `alembic upgrade head` fail *"multiple heads."* Because the two chains are **table-disjoint** (Chain B: feeling/competition, user_corners RLS, ingest policy; Chain A: racing-lines/geometry/onboarding), the fix is a single **empty merge revision** `084_merge_chain_ab` with `down_revision = ("083_ingest_policy_missing_ok", "082_onboarding_email_count")`. No existing migration was edited. Validated: with all migration files present, `alembic heads` → exactly `084_merge_chain_ab`; history shows the `(mergepoint)`.

**Full linear resolution `alembic upgrade head` produces from 077:**
`077 → 081_feeling → 082_user_corners → 083_ingest → 078_racing_lines → 079_geom_audit → 080_honesty → 081_onboarding → 082_onboarding → 084_merge` (single head). The numeric prefixes are out of order after 083 — that is cosmetic; alembic follows the `down_revision` DAG, not the filename.

## Deploy-order: this branch is a SUPERSET of Chain B
It carries **both** chains' migrations + the merge, so it resolves to the single head `084` from **either** starting point:
- **Recommended (matches the stated sequence):** deploy **Chain B first** (`feat/customer-readiness` — it carries the urgent live security fixes: 3 cross-tenant IDOR closures) so those ship without waiting on onboarding operational readiness. Prod goes to `083`. **Later**, when the honesty/onboarding pieces are operationally ready (annotator published, review gates cleared), deploy THIS branch — `alembic upgrade head` applies `078→082_onboarding` + `084`. `docker-compose` here is a superset, so re-shipping it is safe.
- **Alternative (one shot):** if honesty+onboarding are ready at the same time, deploy this branch directly from prod `077` — it applies everything to `084` in one migrate. Not recommended, because it delays the urgent security fixes behind onboarding readiness.

**Do NOT** deploy Chain A off the *separate* `feat/track-onboarding-loop` branch — that one lacks the `084` merge revision and Chain B's migrations, so it forks. Deploy Chain A **only** from this consolidated branch.

## ⚠️ Do first
- Everything in `docs/runbooks/customer-readiness-deploy.md` §"Do first" still applies (rotate the Netlify PAT, confirm the live frontend commit, NOT `make deploy`).
- **Rotate the leaked Netlify PAT** (theos.eleve) if not already done for Chain B.
- These honesty/onboarding features were built **branch-only and are gated on your review** (per the optimizer-program automation verdict: auto-draft + MANDATORY human review, SAM2 MAE 1.91 m vs 1.0 m target). Confirm you've cleared that gate before customer-facing exposure.

## Deploy sequence (when shipping Chain A from this branch)
### 1 — Prod head sanity (read-only)
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
Expect `083_ingest_policy_missing_ok` (if Chain B already deployed) or `077_stripe_pending_entitlements` (one-shot). Either resolves cleanly to `084`.

### 2 — Ship backend + compose + migrate
```bash
cd /c/Users/Admin/lap_web-wt-chain-a
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
scp docker-compose.prod.yml Dockerfile root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api celery-pipeline celery-default celery-beat celery-endurance celery-pipeline-long celery-onboarding"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic upgrade head && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
**Gate:** `alembic current` → `084_merge_chain_ab (head)`. Migrations 078–082_onboarding are `CREATE TABLE` + RLS on new tables (racing-lines, geometry-audit, onboarding-requests) — non-destructive. If Chain B wasn't deployed yet, 081_feeling/082_user_corners/083_ingest also apply (see the Chain B runbook for those). **Run the PG-gated RLS tests** for user_corners + ingest (from the Chain B runbook) AND any onboarding/honesty RLS test against the disposable PG — first real-PG exercise of all of it.
*Rollback:* `alembic downgrade 083_ingest_policy_missing_ok` (drops 084 + the Chain A branch) or `...077...` for a full unwind; each revision has a clean downgrade.

### 3 — Restart workers INCLUDING the dedicated `celery-onboarding` consumer, then verify
> **`celery-onboarding` is a NEW dedicated queue consumer**, not just `-Q onboarding` tacked onto `celery-default` (HIGH graceful-degradation fix, see `telemetry_tool/onboarding/draft.py`'s `_SAM2_TIMEOUT_S` and `telemetry_tool/tasks/onboarding_tasks.py`'s `_ONBOARDING_SOFT_TIME_LIMIT_S`/`_ONBOARDING_HARD_TIME_LIMIT_S`: onboarding used to share `celery-default`'s queue and its 900s hard `--time-limit`, which equaled the SAM2 subprocess's own timeout at the time, so Celery's uncatchable SIGKILL reliably won the race before the subprocess's own catchable `TimeoutExpired` could fire and trigger the `gps_only_draft` fallback). It runs `-Q onboarding` with its own `--soft-time-limit=1500/--time-limit=1800`, mirroring `celery-endurance`/`celery-pipeline-long`'s isolation pattern below — restart/verify it the same way.
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default celery-beat celery-endurance celery-pipeline-long celery-onboarding"
ssh root@46.225.227.24 "cd /opt/lap-api && for s in celery-default celery-endurance celery-pipeline-long celery-onboarding; do echo == \$s ==; docker compose -f docker-compose.prod.yml logs --tail=40 \$s | grep -i 'queues\|-Q'; done"
```
**Gate:** `celery-default` lists `default` only; `celery-endurance` lists `endurance`; `celery-pipeline-long` lists `pipeline_long`; `celery-onboarding` lists `onboarding`. A missing `onboarding` consumer parks onboarding jobs unconsumed. The durable volumes `gt_runtime_data` (/data/gt_runtime) + `onboarding_draft_data` (/data/onboarding_drafts) must be mounted on api + celery-onboarding (they're in this compose).

### 4 — Env for the onboarding loop
Set on the API + celery-onboarding services (see `.env.example` / `docs/runbooks/track-onboarding-deploy.md`): `CORS_ALLOWED_ORIGINS` **must include the annotator origin**, `ANNOTATOR_HOST`, and (optional, for SAM2 satellite drafts) `ONBOARDING_TRACKRECO_DIR` + weights in the worker image. GPS-only drafts work without SAM2.

### 5 — Publish the annotator (separate repo)
The web annotator is `Analysis/trackreco-main` branch `feat/onboarding-annotator` (`netlify-annotator/index.html`) — publish to Netlify per `docs/runbooks/track-onboarding-deploy.md`. Its origin must match `CORS_ALLOWED_ORIGINS`/`ANNOTATOR_HOST`.

### 6 — Frontend (if not already shipped with Chain B)
`/optimal-line` now returns the honesty-gated shape; the frontend consumer (`useTrackSurfaceData.ts`) already respects `drawable`/`tier`. `showOptimalLine` is currently hardcoded `false`, so no fabricated line is drawn regardless. Deploy the frontend per the Chain B runbook §4.

## Detailed sub-runbooks (all on this branch)
- `docs/runbooks/track-onboarding-deploy.md` — the full onboarding deploy (env, annotator, smoke).
- `docs/runbooks/track-onboarding.md` — operating the loop.
- `docs/runbooks/track-geometry-factory-bless.md` — the GT bless/audit workflow.
- `docs/runbooks/racing-line-release.md` — racing-line/honesty release notes.
- `docs/runbooks/customer-readiness-deploy.md` — the Chain B (hardening + security) deploy this sits on top of.

## Honesty-safety (why this is safe to ship)
The whole point of the honesty layer: a bad or absent GT never yields a wrong `optimal_line` — `decide_tier` refuses (returns `speed_profile_only`/`refused`), and #3 makes the route emit a drawable line ONLY for `tier == optimal_line`. Onboarding is superadmin-gated (`is_operator_run`, customers never trigger it). So even with imperfect GT, customers see "not yet optimal," never a fabricated line.
