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
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api celery-pipeline celery-default celery-beat celery-onboarding"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic upgrade head && docker compose -f docker-compose.prod.yml exec -T -w /app/telemetry_tool api alembic current"
```
**Gate:** `alembic current` → `082_onboarding_email_count (head)`. Migrations are non-destructive (082's `ADD COLUMN NOT NULL DEFAULT 0` is metadata-only on Postgres 16). Alembic reads `TELEMETRY_PG_MIGRATION_URL` (falls back to `TELEMETRY_PG_URL`).
*Rollback (migrations):* `… alembic downgrade 080_racing_line_honesty` (both 081/082 have real `downgrade()` bodies; `track_onboarding_requests` is dropped).
*Rollback (code/config):* `git checkout <prior-sha> -- telemetry_tool docker-compose.prod.yml Dockerfile` in the worktree, re-`scp`, rebuild, `up -d` the five services.

## Step 4 — Restart api + workers + beat, verify the onboarding consumer
> **`celery-onboarding` is a NEW dedicated queue consumer** (HIGH graceful-degradation fix: `onboarding` used to share `celery-default`'s queue and its 900s hard `--time-limit`, which equaled `onboarding/draft.py`'s own SAM2 subprocess timeout at the time — Celery's uncatchable SIGKILL reliably won that race before the subprocess's own catchable `TimeoutExpired` could fire, so the documented "falls back to GPS-only within 15 min" behavior below never actually happened). It runs `-Q onboarding` with its own `--soft-time-limit=1500/--time-limit=1800` (mirrors `celery-endurance`/`celery-pipeline-long`'s isolation pattern) — you must restart/verify it exactly like those two, not just `celery-default`.
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default celery-beat celery-onboarding"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml logs --tail=80 celery-onboarding | grep -i 'queues\|-Q'"
```
**Gate (B1):** the `celery-onboarding` boot log must list `onboarding` in its `[queues]` line — check the log, not just that the process is up. (`celery-default`'s own `[queues]` line should list only `default` now.) *Rollback: as Step 3 code rollback.*

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
| `ONBOARDING_TRACKRECO_DIR` | *(leave unset)* | Unset = safe GPS-only drafts. SAM2-in-prod is a fast-follow -- see the dedicated section below if/when you provision it. |
| `ONBOARDING_TRACKRECO_PYTHON` | *(leave unset)* | Same as above -- part of the optional SAM2 provisioning, not required for this deploy. |
```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default celery-beat celery-onboarding"
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

## Optional — Provisioning SAM2 satellite drafting in prod (fast-follow, not required to ship the loop)

By default `celery-onboarding` (the dedicated onboarding worker — see Step 4) only ever runs `gps_only_draft` (`telemetry_tool/onboarding/draft.py`) — `sam2_draft` needs a SAM2-capable Python environment this worker's own lean image does NOT ship (no torch, no imagery/segmentation deps — see `Dockerfile`). This section wires that up. It is entirely optional and additive: skip it and the loop keeps working exactly as documented above (GPS-only drafts, human-reviewed in the annotator either way — review is mandatory regardless of draft source, see the honesty note below).

**Read the log first.** `sam2_draft` calls `_sam2_preflight()` on every single attempt and logs one of:
- `SAM2 draft skipped: <reason>` — the reason names exactly which of the 3 requirements below is missing (dir/script/interpreter), so you never have to guess why a track got a GPS-only draft.
- `SAM2 draft attempting (trackreco_dir=..., interpreter=...)` — config looks complete; a subsequent `sam2_draft: lap_track_to_draft.py exited N: ...` line or a timeout (`_SAM2_TIMEOUT_S=1200` — a catchable `subprocess.TimeoutExpired`, comfortably below `celery-onboarding`'s own 1500s soft time limit, see the HIGH graceful-degradation fix noted in Step 4) means the trackreco side itself failed — inspect that log line / the trackreco-main repo, not this one.

**1. Clone + build the trackreco-main venv (on the VPS, once)**
```bash
ssh root@46.225.227.24
mkdir -p /opt/trackreco-main && cd /opt/trackreco-main
git clone <trackreco-main remote> .          # or scp/rsync an existing checkout across
git checkout <sha that has scripts/lap_track_to_draft.py>
python3.11 -m venv .venv
.venv/bin/pip install -e '.[sam]'
```
`pyproject.toml`'s `[project.optional-dependencies].sam` extra (`segment-anything @ git+https://github.com/facebookresearch/segment-anything.git`) transitively pulls in torch — expect a sizeable (several-hundred-MB), slow install. This venv is intentionally kept OUT of the `lap_web` worker image (see the honesty note below on why this stays worker-external).

**2. Obtain the SAM2 checkpoint weights**
NOT committed to any repo (a multi-hundred-MB to multi-GB binary — do not `git add` it anywhere). Download the official Meta-published checkpoint (e.g. `sam_vit_h_4b8939.pth` for ViT-H) from the `segment-anything` project's release assets into a directory of your choosing, e.g. `/opt/trackreco-main/checkpoints/sam2/`. Confirm against trackreco-main's own config/code (`scripts/build_satellite_gt.py` / `trackreco_platform/satellite_gt/segmentation.py`) exactly which checkpoint filename/path it expects — that detail lives in the sibling repo, out of scope here.

**3. Set the env vars — SAME absolute path in both `/opt/lap-api/.env.production` (container-side; the app reads these) and `/opt/lap-api/.env` (compose-side; only needed if you use the templated mount lines in step 4)**:
```
ONBOARDING_TRACKRECO_DIR=/opt/trackreco-main
ONBOARDING_TRACKRECO_PYTHON=/opt/trackreco-main/.venv/bin/python
# only if you keep weights outside the checkout:
ONBOARDING_TRACKRECO_WEIGHTS_DIR=/opt/trackreco-main/checkpoints/sam2
```

**4. Mount into the worker and restart**
Uncomment the two `# -` volume lines already present (commented, inert) under `celery-onboarding` in `docker-compose.prod.yml`, then:
```bash
docker compose -f docker-compose.prod.yml up -d celery-onboarding
docker compose -f docker-compose.prod.yml logs --tail=40 celery-onboarding | grep -i "SAM2 draft"
```
Trigger a real onboarding draft (Post-deploy verification, step 1, above) and confirm the log now reads `SAM2 draft attempting` instead of `SAM2 draft skipped`. *Rollback: re-comment the two mount lines and `up -d celery-onboarding` again — the app tolerates the mount vanishing exactly like it tolerates it never having existed (preflight fails closed to GPS-only, nothing crashes).*

**Honesty note — GPU/CPU and review stay mandatory.** SAM2/segment-anything is a vision transformer that wants a GPU; this VPS is CPU-only, so a SAM2 attempt is considerably slower than the GPS-only path (seconds vs. potentially ~20 minutes — `_SAM2_TIMEOUT_S=1200` gives it 20 minutes before giving up and falling back to GPS-only, well inside `celery-onboarding`'s own 25-minute soft / 30-minute hard time limit — see the HIGH graceful-degradation fix noted in Step 4). That is acceptable for how this feature is actually used — an operator manually triggering onboarding for one unrecognized track at a time, not a hot path — but do not expect it to be fast, and do not provision a GPU for this alone without a separate cost/benefit conversation. **Human review in the annotator stays MANDATORY regardless of draft source** (SAM2's own measured accuracy against held-out ground truth was ~1.9 m MAE vs. a 1.0 m target in the geometry-factory work) — a SAM2 draft is a better STARTING POINT for the annotator to correct, never a bypass of review. GPS-only remains the permanent, zero-dependency default and is never removed by provisioning the above.

## Accepted known-limitations (non-blocking)
- **SAM2 satellite drafting disabled by default in prod** (`ONBOARDING_TRACKRECO_DIR`/`ONBOARDING_TRACKRECO_PYTHON` unset) → `drafted_gps_only` (loop still completes; rougher centerline). See "Optional — Provisioning SAM2 satellite drafting in prod" above to enable it.
- **Auto-resend may spend one email slot without sending** if the broker enqueue fails after `claim_resend` commits (biases toward *less* nagging, never double-send; `MAX_EMAILS=4`; recovery = `UPDATE … SET email_count=0`).
- **Rate limiter fails open on a Redis outage** on the two public routes — pre-existing app-wide behavior; the HMAC one-shot token is the real auth boundary, so this removes throttling only, not access.
- **Blessed GT lives only in the runtime volume until reconciled to git** (`data/ground_truth/`). A lost/reprovisioned volume before reconcile silently reverts corrections — do the periodic reconcile-to-git step.
