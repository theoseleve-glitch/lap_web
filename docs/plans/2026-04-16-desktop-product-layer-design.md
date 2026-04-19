# Desktop Product Layer — Auth, Entitlements, Sync UX

**Date**: 2026-04-16
**Status**: Design — ready to implement

---

## A. Architecture

### One paragraph

The desktop app authenticates via the **existing DeviceToken system** (already in
`web/middleware/device_auth.py` + `device_pairings` table). Pairing is a one-time
browser-redirect flow. Entitlements are fetched from `GET /api/v1/me` at app start
and cached for 1 hour. The sync policy (auto-upload on/off) is **server-determined
by plan tier**, not locally configurable. The SyncWorker uses the stored device
token for upload auth. Desktop UI is a Tkinter panel showing per-session sync
status with action buttons.

### Flow diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  DESKTOP APP                                                     │
│                                                                  │
│  Startup                                                         │
│    │                                                             │
│    ├── Load device_token from ~/.lap/config.json                 │
│    │   ├── exists + valid → fetch_entitlements()                 │
│    │   └── missing → show "Connect Account" prompt              │
│    │                                                             │
│    ├── fetch_entitlements()                                      │
│    │   GET /api/v1/me  (Authorization: DeviceToken <token>)      │
│    │   ├── 200 → cache plan_tier, entitlements (1h TTL)          │
│    │   ├── 401 → clear token, show "Re-connect Account"         │
│    │   └── network error → use last-known cached entitlements    │
│    │                                                             │
│    └── Start SyncWorker if plan allows                           │
│                                                                  │
│  Session finalize                                                │
│    │                                                             │
│    ├── build_session_bundle()                                    │
│    ├── enqueue(auto_upload = entitlements.auto_sync_enabled)     │
│    └── SyncWorker.drain() uses device_token for POST /bundles    │
│                                                                  │
│  UI: Sync Panel (Tkinter)                                        │
│    ├── Account: "user@email.com (World Class)"                   │
│    ├── Session list: status badges (local/queued/uploaded/etc.)   │
│    ├── [Upload] button (Racer: per-session)                      │
│    ├── [Retry] button (on failed items)                          │
│    └── [View in Browser] link (on analyzed items)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## B. Files to Add / Modify

### New files (5)

```
telemetry_tool/desktop_sync/
├── auth.py                # DeviceAuth: token storage, pairing flow, entitlement cache
├── entitlements.py        # CachedEntitlements: plan tier, feature flags, TTL
└── ui_sync_panel.py       # Tkinter SyncPanel (beta — alpha is console-only)

telemetry_tool/tests/test_desktop_sync/
├── test_auth.py           # pairing mock, token refresh, expiry behavior
└── test_entitlements.py   # cache TTL, offline fallback, plan→policy mapping
```

### Modified files (3)

| File | Change |
|------|--------|
| `desktop_sync/config.py` | Add `device_token`, `device_id`, `cached_plan_tier`, `entitlements_fetched_at` fields |
| `desktop_sync/hooks.py` | Resolve `auto_upload` from server entitlements (not local config alone) |
| `desktop_sync/worker.py` | Pass device_token as auth header on upload requests |

### No backend changes needed

The required endpoints already exist:
- `POST /api/v1/devices/pair` — device pairing (already implemented)
- `GET /api/v1/me` — returns `plan_tier` + `entitlements`
- `POST /api/v1/bundles` — accepts `Authorization: DeviceToken <token>`

---

## C. API Contract Additions

**None required.** All endpoints exist. The only consideration:

| Endpoint | Used for | Auth method | Already works? |
|----------|----------|-------------|----------------|
| `POST /api/v1/devices/pair` | One-time pairing | No auth (pairing code) | Yes |
| `GET /api/v1/me` | Entitlement fetch | `DeviceToken` header | Yes |
| `POST /api/v1/bundles` | Upload | `DeviceToken` header | Yes (device_auth middleware) |
| `POST /api/v1/bundles/<id>/analyze` | Trigger analysis | `DeviceToken` header | Yes |

If the entitlements response doesn't include `auto_sync_enabled` specifically,
we derive it: `plan_tier == "world_class"` → `auto_sync_enabled = true`.

---

## D. Desktop UI Flow

### D.1 First-time pairing (one-time)

```
┌────────────────────────────────────────────────┐
│                                                │
│  Connect your Lap account                      │
│                                                │
│  1. Click the button below                     │
│  2. Log in on the webpage that opens           │
│  3. Confirm the device pairing                 │
│                                                │
│  [Connect Account]                             │
│                                                │
│  Status: Waiting for confirmation...           │
│                                                │
└────────────────────────────────────────────────┘

Flow:
  1. Desktop generates a random pairing_code (32 hex chars)
  2. Opens browser: https://lap-coach.racing/app/account/devices?pair=<code>
  3. User logs in (if not already) → sees "Confirm device pairing?"
  4. User clicks "Confirm"
  5. Desktop polls GET /api/v1/devices/<device_id>/status every 3s
  6. When status=confirmed → store device_token in ~/.lap/config.json
  7. Fetch entitlements → show account info
```

### D.2 Sync panel (post-pairing, v1 console / v2 Tkinter)

**Alpha (console output — already shipped):**
```
[SYNC] Connected: user@email.com (World Class)
[SYNC] Auto-upload: enabled
[SYNC] Bundle built: daytona_road_course_mx5.zip (18.2 MB)
[SYNC] Uploading... done (bundle_id: 4b9d1f8c)
[SYNC] Session synced to cloud.
```

**Beta (Tkinter panel — new `ui_sync_panel.py`):**

```
┌─ Cloud Analysis ──────────────────────────────┐
│                                                │
│  Account: user@email.com                       │
│  Plan: World Class  ✓ Auto-sync enabled        │
│                                                │
│  Sessions:                                     │
│  ──────────────────────────────────────────     │
│  ● Daytona MX-5    Apr 16   ✓ Analyzed [View]  │
│  ● Spa MX-5        Apr 15   ↑ Uploading...     │
│  ○ Laguna Seca     Apr 14   ─ Local only [↑]   │
│  ✗ Monza GT4       Apr 13   ✗ Failed   [Retry] │
│                                                │
│  [Disconnect]                                  │
└────────────────────────────────────────────────┘

Legend:
  ● = synced      ○ = local only     ↑ = uploading
  ✓ = analyzed    ✗ = failed         ─ = skipped
```

### D.3 Per-session status model

```
local_only    → user hasn't uploaded (Racer default)
queued        → enqueued, waiting for worker
uploading     → POST in flight
uploaded      → 201/202 received, no analysis yet
analyzing     → analysis run queued/running (polled from backend)
analyzed      → analysis complete (tier A/B/C)
refused       → analysis complete but tier D
failed_upload → upload failed after max retries
failed_analysis → analysis run failed on backend
```

### D.4 Actions per state

| Status | Racer actions | World Class actions |
|--------|---------------|---------------------|
| `local_only` | [Upload] | (auto-uploaded) |
| `queued` | — | — |
| `uploading` | — | — |
| `uploaded` | [View in Browser] | [View in Browser] |
| `analyzing` | — | — |
| `analyzed` | [View Results] | [View Results] |
| `refused` | [View Details] | [View Details] |
| `failed_upload` | [Retry] | [Retry] |
| `failed_analysis` | [Retry Analysis] | [Retry Analysis] |

---

## E. Security / Auth Model

### E.1 Token storage

| Item | Location | Protection |
|------|----------|------------|
| Device token | `~/.lap/config.json:device_token` | File permissions (0600). NOT encrypted in v1 — same threat model as SSH keys, git credentials. |
| Device ID | `~/.lap/config.json:device_id` | Public identifier, not secret |
| Cached entitlements | `~/.lap/config.json:cached_entitlements` | Informational only — server re-validates on every upload |

### E.2 Trust model

**Server-authoritative for all paid features.** The desktop config caches the
plan tier for UX purposes (show/hide buttons), but every upload hits the
server's entitlement middleware. A user who edits their local config to
`"auto_upload": true` while on the free plan will get a 403 from the server
when the upload exceeds their quota.

### E.3 Token lifecycle

```
Pairing → device_token (never expires; revocable from webapp)
  │
  ├── GET /api/v1/me → 200 → entitlements cached (1h TTL)
  ├── GET /api/v1/me → 401 → token revoked/invalid → clear + re-pair
  ├── POST /bundles  → 401 → clear + prompt re-pair
  └── POST /bundles  → 403 → quota exceeded → show user message
```

### E.4 Logout / account switch

Desktop: "Disconnect" button → clears `device_token` + `device_id` from config →
stops SyncWorker → shows "Connect Account" prompt again. Previous bundles stay on
disk (immutable). Re-pairing with a different account is supported — new uploads go
to the new account's workspace.

### E.5 What we do NOT do in v1

- No token encryption at rest (same as every desktop app — Chrome, VS Code, etc.)
- No certificate pinning (stdlib TLS is sufficient)
- No refresh token rotation (device tokens are long-lived, revocable from webapp)
- No local-only mode for paid features (all analysis requires cloud — the research
  pipeline runs server-side)

---

## F. Error Model — User-Facing Messages

| Error | Backend code | Desktop message |
|-------|-------------|-----------------|
| Token revoked/expired | 401 from any endpoint | "Your account connection has expired. Please reconnect." + [Connect Account] |
| Quota exceeded | 403 QUOTA_EXCEEDED | "You've reached your upload limit this month. Upgrade to upload more sessions." |
| Feature locked (free trying to upload) | 403 PLAN_REQUIRED | "Cloud analysis requires a Racer or World Class plan. [Upgrade]" |
| Duplicate upload | 409 BUNDLE_DUPLICATE | (silent — mark as uploaded, show existing cloud link) |
| Degraded bundle | 202 from intake | "Session uploaded with incomplete data. Some analysis features may be limited." |
| Unsupported session (tier D) | Analysis returns tier D | "This sim/vehicle/track combination isn't supported for analysis yet." |
| Analysis failed | Analysis run status=failed | "Analysis encountered an error. [Retry Analysis]" |
| Network unreachable | Connection error | "No internet connection. Session saved locally. Will sync when online." |
| Bundle build failed | Local exception | "Could not create upload package. Check disk space and try again." |

---

## G. Entitlement → Policy Mapping

```python
def resolve_sync_policy(entitlements: dict) -> dict:
    plan = entitlements.get("plan_tier", "free")
    return {
        "can_upload": plan in ("racer", "world_class"),
        "auto_upload": plan == "world_class",
        "auto_analyze": plan == "world_class",
        "manual_upload": plan == "racer",
        "max_uploads_month": entitlements.get("analyses_per_month", 0),
    }
```

| Plan | Can upload | Auto upload | Auto analyze | Manual upload |
|------|-----------|-------------|-------------|---------------|
| Free | No | No | No | No |
| Racer | Yes | No | No | Yes (button) |
| World Class | Yes | Yes | Yes | Yes (redundant) |

---

## H. Auto-Analysis Policy

**Decision: World Class auto-triggers analysis on upload. Racer does not.**

Rationale: World Class users are paying for a hands-off experience. Racer users
may want to review which sessions are worth analyzing (they have a monthly quota).

Implementation: after `SyncWorker` gets a 201/202 from POST /bundles, it checks
the sync policy:
- `auto_analyze=true` → immediately POST `/bundles/<id>/analyze`
- `auto_analyze=false` → stop at "uploaded" status, user triggers from desktop or webapp

---

## I. Rollout Plan

### Phase 1: Internal Alpha (week 1)

- Auth: Device token pairing via CLI (`python -m desktop_sync pair`)
- Entitlements: fetched + cached, console output only
- Sync: existing auto/manual upload with device token auth
- UI: console log lines (already shipped)
- Gate: internal team + 3 beta testers with World Class accounts
- Rollback: remove `desktop_sync` from PyInstaller spec

### Phase 2: Public Beta (week 2-3)

- Auth: Tkinter pairing dialog (browser redirect + polling)
- UI: Tkinter SyncPanel with session list + status badges + action buttons
- Auto-analysis: enabled for World Class
- Error messages: all 9 error states mapped to user-facing text
- Gate: all World Class subscribers, opt-in for Racer
- Rollback: `auto_upload=false` in config, sync panel hidden

### Phase 3: GA (week 4+)

- Racer self-service upload from desktop UI
- Usage tracking (show "3 of 10 uploads used this month")
- "Open in webapp" deep-link for analyzed sessions
- Desktop notification on analysis complete

---

## J. Implementation Order

| # | Step | Files | Phase |
|---|------|-------|-------|
| 1 | `desktop_sync/auth.py` — DeviceAuth class (store/load token, pair CLI, fetch entitlements) | New | Alpha |
| 2 | `desktop_sync/entitlements.py` — CachedEntitlements (TTL cache, plan→policy) | New | Alpha |
| 3 | Update `hooks.py` — resolve auto_upload from server entitlements | Modify | Alpha |
| 4 | Update `worker.py` — use device_token header | Modify | Alpha |
| 5 | Update `config.py` — add device_token/device_id/cached fields | Modify | Alpha |
| 6 | `desktop_sync/__main__.py` — add `pair` + `whoami` CLI commands | Modify | Alpha |
| 7 | Tests for auth + entitlements | New | Alpha |
| 8 | `desktop_sync/ui_sync_panel.py` — Tkinter panel | New | Beta |
| 9 | Auto-analyze after upload | Modify worker.py | Beta |
| 10 | Deep-link "View in Browser" | Modify UI | GA |

**Alpha deliverable: steps 1–7.** Console-only, device token auth, server-trusted entitlements. ~300 lines of new code + ~150 lines of tests.
