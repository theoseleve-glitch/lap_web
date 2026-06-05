---
name: run-lap-webapp
description: Run, launch, start, and screenshot the LAP V2 webapp (lap_web/lap-website — the authed Next.js /app dashboard, upload, sessions). Drives authed /app pages past login with a Playwright driver and a fully-mocked backend; use to screenshot or visually verify UI changes locally.
---

# Run the LAP V2 webapp (lap_web/lap-website) locally

This is the **production webapp** — Next.js App Router, authed `/app/*`
dashboard/upload/sessions (NOT the marketing Astro site, which is the
hyphen-named `lap-website/` at the Telemetry root). It's driven headless
by a Playwright **driver** (`.claude/skills/run-lap-webapp/driver.mjs`)
that boots the page past the client-side auth guard with the entire
backend mocked at the network layer — nothing touches production.

All paths below are relative to `lap-website/` (the unit). Commands were
run on the Windows dev box (PowerShell + Git Bash; no Docker). Verified
2026-06-05.

## Prerequisites

- Node (v25 on this box) and the webapp's `node_modules`, which already
  include `playwright` 1.60 + a downloaded chromium. **No `apt-get`, no
  `playwright install`** — they're present.
- If `node_modules` is missing: `npm install` (NOT `npm ci` — `ci` fails
  `EBADPLATFORM` on esbuild's foreign-platform optional dep here).

## Run (agent path) — START HERE

Two steps: start a dev server with a **same-origin** API base, then run
the driver.

**1. Dev server (PowerShell), same-origin API URL so mocks need no CORS:**

```powershell
$env:NEXT_PUBLIC_API_URL = "http://localhost:4123"
node_modules\.bin\next.cmd dev -p 4123
```

Use `next dev`, NOT `next start` — the build sets `output: standalone`,
so `next start` refuses (`next start does not work with output: standalone`).

**2. Driver (run from `lap-website/`, screenshots land in `lap-website/_shots/`):**

```powershell
# Default: upload page + the new-entry (new track/kart) modal flow → 3 shots
node .claude\skills\run-lap-webapp\driver.mjs
```

```bash
# Same, from Git Bash (works for the no-arg case):
node .claude/skills/run-lap-webapp/driver.mjs
```

Verified output: `01_upload_form_dropdowns.png` (Track/Kart dropdowns,
"+ New track…" selected, no inline form, generated "Session name (auto)"),
`02_new_entry_modal.png` (the NEW TRACK DETAILS modal that opens AFTER
clicking Upload & Analyze), `03_new_entry_modal_filled.png`.

### Generic page mode

```powershell
node .claude\skills\run-lap-webapp\driver.mjs --path /app/sessions --shot sessions
```

Navigates any authed `/app/*` path and screenshots it. **Caveat:** the
mocks cover what the upload page needs. Data-heavy pages (e.g.
`/app/dashboard` reads session stats/trends) render partial/blank until
you add their endpoint shapes to `setupMocks()` in the driver — extend
it there, don't fight it. Run generic-path invocations via **PowerShell**
(see Git Bash gotcha below).

## Gotchas (the non-obvious traps — read before editing the driver)

- **`bypassCSP: true` is MANDATORY for `next dev`.** The app's CSP is
  `script-src 'self' 'unsafe-inline' https://plausible` — no
  `'unsafe-eval'`. `next dev` HMR uses `eval()`, so without bypassCSP the
  client bundle dies on a CSP `PAGEERROR` and the page hangs forever on
  "Restoring session…" (the `AuthGuard` loading state). Production builds
  don't use eval, so this is dev-only. The driver sets it on the context.
- **Auth is client-side, not middleware.** `src/middleware.ts` is
  marketing-only (no `/app` gate). `AuthGuard` (`src/components/auth/`)
  calls `silentRefresh()` → `POST /auth/refresh` on mount. The driver
  mocks it to return `{ ok:true, data:{ access_token, refresh_token,
  user:{ id, email, display_name:"Demo Driver" } } }`. A **non-empty
  `display_name`** is required or it redirects to `/app/onboarding`.
- **`/account/usage` must return the full `UserPlan` shape.**
  `useUserPlan.ts` does `plan.analyses.limit` (the `.analyses` is NOT
  optional-chained), so an empty `{}`/`[]` → "Cannot read properties of
  undefined (reading 'limit')". The driver returns `{ plan_tier,
  subscription_status, analyses:{used,limit,resets}, features:{} }` with
  `limit:null` = unlimited.
- **All API responses use the envelope `{ ok:true, data, meta }`** with
  `content-type: application/json`. The `data` is unwrapped by
  `parseEnvelopeOrThrow`.
- **Playwright tries the LAST-registered matching route first.** Register
  catch-alls (`/api/v1/`, `/auth/`) FIRST and specific routes LAST, or the
  catch-all shadows `/auth/refresh` and auth silently breaks.
- **Same-origin API base avoids CORS** on `page.fulfill()` — hence
  `NEXT_PUBLIC_API_URL=http://localhost:4123`.
- **Git Bash mangles `/app/...` args** into `C:/Program Files/Git/app/...`
  (MSYS path translation), giving "Cannot navigate to invalid URL". Run
  the driver via **PowerShell** for any `--path /app/...` arg (or set
  `MSYS_NO_PATHCONV=1` in Git Bash). The no-arg default is unaffected.
- **The upload form needs a ≥50-row CSV** — preflight rejects fewer
  (`telemetry_tool/preflight.py:_MIN_DATA_ROWS=50`). The driver generates 60.

## Troubleshooting

- Stuck on "Restoring session…" / blank page → missing `bypassCSP`, or
  `/auth/refresh` not mocked / mocked without `access_token`.
- "Cannot read properties of undefined (reading 'limit')" → `/account/usage`
  not returning the `UserPlan` shape.
- "next start does not work with output: standalone" → use `next dev`.
- "Cannot navigate to invalid URL … C:/Program Files/Git/app/…" → Git Bash
  path mangling; run via PowerShell.

## Human path

`next dev -p 4123`, open `http://localhost:4123` in a browser, log in
against a real backend. Useless headless — use the driver instead.
