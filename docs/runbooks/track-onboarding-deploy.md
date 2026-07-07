# Track Onboarding Loop — Production Deploy Sequence

Authoritative, execute-from-top runbook for shipping the Track Onboarding Loop to the **live** platform `lap-coach.racing`. Produced from the audited deploy-readiness review (branch `feat/track-onboarding-loop`).

> **Verdict going in:** zero application-code correctness blockers (regression, migration chain 077→082, fail-closed security, and loop-closure/honesty all confirmed). The pre-deploy ops-config fixes (F1–F5: onboarding queue consumer + durable `gt_runtime`/`onboarding_drafts` volumes + `.env.example` + runbook) are **already committed on this branch**. What remains is the operator-run deploy below.
>
> **You run this** — prod pushes need your authenticated `ssh`/`netlify` session; a sandboxed agent cannot. Commands assume Git-Bash on Windows.

## ⚠️ Do first
- **Rotate the Netlify personal-access-token** for `theos.eleve@gmail.com` (Netlify → User settings → Applications → Personal access tokens). One was echoed into a review transcript.
- **Do NOT use `make deploy`** — it `scp`s only 3 files and rebuilds only `api`, shipping **zero** new code to the Celery workers. Use the explicit `scp` in Step 3.
- No `git merge`/`rebase` needed: this worktree's HEAD carries the full 077→082 lineage (`feat/honesty-layer` is a strict ancestor; `main` is stale at alembic 060).

VPS = `root@46.225.227.24:/opt/lap-api`. Compose file on the box = `docker-compose.prod.yml`.

---

## Step 1 — Confirm prod's current alembic head (read-only)
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
Expect something on the `078…080` chain (`080_racing_line_honesty` = head is fine; Step 3 walks the rest to `082`). **STOP and investigate** if it shows anything off the 077→082 chain (prod diverged). *Rollback: none (read-only).*

## Step 2 — Publish the annotator to Netlify (resolves B3; produces the URL Steps 3+ need)
```bash
cd /c/Users/Admin/Documents/Telemetry/Analysis/trackreco-main
git checkout feat/onboarding-annotator      # commit a4e03517
netlify init                                 # first time only — creates/links the site; NOTE the printed URL
netlify deploy --dir=netlify-annotator --prod
```
`netlify-annotator/index.html` is a single static file with `API_BASE` already defaulting to `https://api.lap-coach.racing` — no build step. Record the printed origin as **`<ANNOTATOR_ORIGIN>`** (e.g. `https://lap-onboarding-annotator.netlify.app`); it feeds `ANNOTATOR_HOST` and `CORS_ALLOWED_ORIGINS` in Step 5. *Rollback: `netlify rollback`; no server state, low risk.*

## Step 3 — Ship code + ops-config, apply migrations 081+082
```bash
cd /c/Users/Admin/lap_web-wt-onboarding
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
scp docker-compose.prod.yml Dockerfile root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api celery-pipeline celery-default celery-beat"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic upgrade head && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
**Gate:** `alembic current` → `082_onboarding_email_count (head)`. Migrations are non-destructive (082's `ADD COLUMN NOT NULL DEFAULT 0` is metadata-only on Postgres 16). Alembic reads `TELEMETRY_PG_MIGRATION_URL` (falls back to `TELEMETRY_PG_URL`).
*Rollback (migrations):* `… alembic downgrade 080_racing_line_honesty` (both 081/082 have real `downgrade()` bodies; `track_onboarding_requests` is dropped).
*Rollback (code/config):* `git checkout <prior-sha> -- telemetry_tool docker-compose.prod.yml Dockerfile` in the worktree, re-`scp`, rebuild, `up -d` the four services.

## Step 4 — Restart api + workers + beat, verify the onboarding consumer
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default celery-beat"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml logs --tail=80 celery-default | grep -i onboarding"
```
**Gate (B1):** the `celery-default` boot log must list `onboarding` in its `[queues]` line — check the log, not just that the process is up. *Rollback: as Step 3 code rollback.*

## Step 5 — Set env secrets in `/opt/lap-api/.env.production` (never commit values), then restart to re-read
| Var | Value | Note |
|---|---|---|
| `ONBOARDING_TOKEN_SECRET` | `<openssl rand -hex 32>` | Fail-closed if unset; never reuse another secret. |
| `ONBOARDING_OPERATOR_EMAIL` | `<real operator inbox>` | Missing → `draft_failed` + `/save` 503. |
| `ANNOTATOR_HOST` | `<ANNOTATOR_ORIGIN from Step 2>` | Embedded in every emailed link. |
| `GT_RUNTIME_DIR` | `/data/gt_runtime` | Matches the F2 volume mount. |
| `ONBOARDING_DRAFT_DIR` | `/data/onboarding_drafts` | Set **explicitly** (F3) — do not rely on the `..` fallback. |
| `CORS_ALLOWED_ORIGINS` | `https://www.lap-coach.racing,https://lap-coach.racing,<ANNOTATOR_ORIGIN>` | **Required.** App-wide allowlist (no route-scoping). Without the annotator origin, its `fetch()` fails CORS as a silent "network error". |
| `ONBOARDING_TOKEN_TTL_HOURS` | *(leave unset → 72h)* | Optional. |
| `ONBOARDING_TRACKRECO_DIR` | *(leave unset)* | Unset = safe GPS-only drafts. SAM2-in-prod is a fast-follow. |
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default celery-beat"
```
*Rollback:* revert the added `.env.production` lines, restart. Removing `ONBOARDING_TOKEN_SECRET` fails the whole feature closed (safe).

## Step 6 — Real-PG test pass (first real-Postgres validation of the dedup/CAS SQL — do not skip)
```bash
cd /c/Users/Admin/lap_web-wt-onboarding/telemetry_tool
TELEMETRY_PG_URL=<staging-or-safe-PG-url> python -m pytest tests/test_onboarding -q
```
Expect the ~6 `skipif`-gated PG tests (dedup-race, CAS claim, blessed-write refusal, stale-reset) to **run and pass**. Prefer a staging PG so no test rows land in prod. *Rollback: none (test-only).*

---

## Post-deploy verification (prove the loop end-to-end)
1. **Trigger** (onboarding only fires on `is_operator_run=True`, set only by the superadmin admin-retry route). Pick a real ingested session whose track lacks GT:
   ```bash
   curl -X POST https://api.lap-coach.racing/admin/jobs/<job_id>/retry -H "Authorization: Bearer <superadmin-jwt>"
   ```
2. **Draft → email** — poll the row; expect `requested → drafting → drafted_gps_only → emailed`, and the operator inbox gets the link:
   ```sql
   SELECT id, status, draft_status, emailed_at, error FROM track_onboarding_requests WHERE track_key = '<track_key>';
   ```
3. **Annotate → bless** — open the emailed link (exercises the annotator + CORS), correct the boundary, Save → HTTP 200; expect `status='blessed'`. A "network error" on load/save is almost always CORS (recheck Step 5), not the backend.
4. **Reprocess → optimal_line** — confirm `gt_<canonical_id>.geojson` landed in `GT_RUNTIME_DIR`, waiting sessions rebuilt with `boundary_source='gt_anchored_native'`, and `optimal_line` appears within ~30 min (or by the next 03:30 UTC nightly `compute_all_racing_lines` — the honesty-safe delay; a missing line for a few hours is intended, not a bug).
5. **Durability** — restart `api`/`celery-pipeline`, confirm the blessed GT survives (proves the F2 volume is real).

**Un-bless (if ever needed):** remove `gt_<canonical_id>.geojson` + its `track_aliases.json` entry from `GT_RUNTIME_DIR`, `invalidate_gt_cache(canonical_id)` (or restart), and reset the row's `status` from `blessed` in SQL (the app refuses to mutate a `blessed` row by design).

## Accepted known-limitations (non-blocking)
- **SAM2 satellite drafting unavailable in prod** (`ONBOARDING_TRACKRECO_DIR` unset) → `drafted_gps_only` (loop still completes; rougher centerline). Wiring SAM2 into the worker image is a fast-follow.
- **Auto-resend may spend one email slot without sending** if the broker enqueue fails after `claim_resend` commits (biases toward *less* nagging, never double-send; `MAX_EMAILS=4`; recovery = `UPDATE … SET email_count=0`).
- **Rate limiter fails open on a Redis outage** on the two public routes — pre-existing app-wide behavior; the HMAC one-shot token is the real auth boundary, so this removes throttling only, not access.
- **Blessed GT lives only in the runtime volume until reconciled to git** (`data/ground_truth/`). A lost/reprovisioned volume before reconcile silently reverts corrections — do the periodic reconcile-to-git step.
