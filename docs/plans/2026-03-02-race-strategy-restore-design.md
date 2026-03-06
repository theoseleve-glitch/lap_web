# Race Strategy: Restore Entitlements, Enrichment & Shared Components

**Date:** 2026-03-02
**Status:** Approved
**Scope:** Backend entitlement fixes, frontend gating, live dashboard enrichment, shared component extraction

## Context

Race Strategy has two fully implemented backend blueprints (HTML/Jinja for desktop, JSON REST API for SaaS) and 6 fully implemented Next.js frontend pages. No "Coming Soon" placeholders or missing JS modules exist. The issues are at integration boundaries:

1. Backend entitlement gates don't resolve correctly — `race_strategy` feature key falls through to "allow by default"
2. `strategy_live` feature key doesn't exist in plan_definitions — blocks go-live for everyone in PG+auth mode
3. Frontend has no `UpgradeBanner` or entitlement enforcement in any race strategy page
4. Live dashboard API endpoint drops weather alerts, race intelligence, and messages rendering
5. `StintTimeline` duplicated 3x, `RaceConfigForm` duplicated 2x
6. `race_alerts` table uses SQLite `datetime()` syntax — silently fails on PG

## Section 1: Backend Entitlement Fixes

### 1a. Fix `race_strategy` feature key resolution

**File:** `telemetry_tool/auth/entitlements.py` — `authorize_feature()` function

The middleware (`entitlements.py`) passes `"race_strategy"` as the feature key for POST/PUT/DELETE on race strategy routes. However, `authorize_feature()` only handles `"race_strategy_full"` explicitly. The `"race_strategy"` key falls through to the catch-all `return True` at line 402 — the gate is open for everyone.

**Fix:** Add a handler for `"race_strategy"` in `authorize_feature()`:
- Check `race_strategy_limit` from entitlements
- If `None` (no plan): deny with upgrade prompt
- If `"limited_3h"` or `"full"`: allow (the 3h duration limit is enforced at create/update time, not at the gate level)

### 1b. Fix `strategy_live` feature key

**File:** `telemetry_tool/web/routes/race_strategy_v2.py` — lines 636, 666

The HTML blueprint uses `@require_feature("strategy_live")` on `go_live()` and `live()` routes. This column doesn't exist in plan_definitions, so `entitlement_snapshot()` returns `False` for everyone.

**Fix:** Change both decorators to `@require_feature("race_strategy")`. Add `"race_strategy"` to the `_BOOLEAN_FEATURES` map or handle it in `require_feature`'s snapshot check.

Actually, the `require_feature` decorator calls `entitlement_snapshot().get(feature_name, False)` which looks up the feature name as a key in the snapshot dict. We need `"race_strategy"` to resolve to `True` in that dict. Since `get_user_entitlements()` returns `race_strategy_limit` (a string, not boolean), we should either:
- Map `"race_strategy"` in the snapshot to `bool(race_strategy_limit)`, OR
- Change decorators to use the existing feature key approach via `authorize_feature()`

Best approach: change the `require_feature` decorator to use `authorize_feature()` instead of the simple snapshot lookup, which handles `race_strategy` correctly after fix 1a.

### 1c. Enforce 3-hour duration limit for DEMO tier

**File:** `telemetry_tool/services/race_strategy.py` — `create_race()` and `update_race()`

Add an optional `max_duration_s` parameter:
- If provided and `race_duration_s > max_duration_s`, raise ValueError or return error dict
- The API route (`api_v1_race_strategy.py`) resolves entitlements and passes `max_duration_s=10800` when `race_strategy_limit == "limited_3h"`

### 1d. Fix `race_alerts` SQLite date syntax on PG

**File:** `telemetry_tool/web/routes/race_strategy_v2.py` — `_check_weather_alerts()` function

Replace `datetime('now', '-30 minutes')` with a conditional:
```python
if USE_PG:
    time_filter = "NOW() - INTERVAL '30 minutes'"
else:
    time_filter = "datetime('now', '-30 minutes')"
```

## Section 2: Frontend Entitlement Wiring

### 2a. List page — UpgradeBanner for DEMO users

**File:** `lap-website/src/app/app/race-strategy/page.tsx`

- Import `UpgradeBanner` and `canUseFeature`
- Render `<UpgradeBanner feature="race_strategy_full" />` above the race list when DEMO
- Add lock icon to "New Race" button when `canUseFeature('race_strategy_full')` returns false
- Button still works (backend enforces limit), but banner educates

### 2b. Create/Edit forms — duration cap

**Files:** `new/page.tsx`, `[id]/edit/page.tsx`

- When `raceStrategyLimit === 'limited_3h'`:
  - Show inline `UpgradeBanner` above duration field: "Demo plan limited to 3-hour races"
  - Cap duration input max at 180 minutes / 3:00 (visual hint)
  - Backend enforces actual limit

### 2c. Detail page — Go-Live lock

**File:** `[id]/page.tsx`

- When DEMO tier: disable "Go Live" button with tooltip "Upgrade to Racer for Live Dashboard"
- Show inline UpgradeBanner if user tries to click

## Section 3: Live Dashboard Enrichment

### 3a. Add weather + intelligence to service layer

**File:** `telemetry_tool/services/race_strategy.py` — `get_live_state()`

Add optional enrichment with graceful degradation:
- Weather alerts from `meteo_service` (if available)
- Race intelligence from `race_intelligence` (if available)
- Both wrapped in try/except with empty fallback

### 3b. Render messages in live dashboard

**File:** `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`

The `messages` array is already fetched but not rendered. Add a `MessageLog` component:
- Scrollable list of messages with author, timestamp, category badge
- Auto-scroll to bottom on new messages

### 3c. Display weather alerts and intelligence

Same file — add optional cards for weather alerts (if present in state) and intelligence insights.

## Section 4: Shared Component Extraction

### 4a. StintTimeline

**New file:** `lap-website/src/components/app/race-strategy/StintTimeline.tsx`

Extract from detail, live, and summary pages. Props:
- `stints`, `drivers`, `raceDurationS` — core data
- `activeStintId?` — for live page ring highlight
- `useActualDurations?` — summary page prefers actual over planned

### 4b. RaceConfigForm

**New file:** `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx`

Extract from new and edit pages. Props:
- `mode: 'create' | 'edit'`
- `initialData?` — pre-populated for edit
- `maxDurationS?` — entitlement-based cap
- `onSubmit`, `isSubmitting`

Includes all sub-forms: drivers, pit windows, fuel/weight config, qualifying.

### 4c. MessageLog

**New file:** `lap-website/src/components/app/race-strategy/MessageLog.tsx`

Small display component for the live dashboard TeamTalk messages.

## Files Changed

| Area | File | Change Type |
|------|------|-------------|
| Backend | `auth/entitlements.py` | Edit — add `race_strategy` handler |
| Backend | `services/race_strategy.py` | Edit — add duration validation, enrichment |
| Backend | `routes/api_v1_race_strategy.py` | Edit — pass entitlement context |
| Backend | `routes/race_strategy_v2.py` | Edit — fix decorator, fix datetime syntax |
| Frontend | `race-strategy/page.tsx` | Edit — add UpgradeBanner |
| Frontend | `race-strategy/new/page.tsx` | Edit — add duration cap, UpgradeBanner, use shared form |
| Frontend | `race-strategy/[id]/edit/page.tsx` | Edit — use shared form |
| Frontend | `race-strategy/[id]/page.tsx` | Edit — lock Go-Live for demo |
| Frontend | `race-strategy/[id]/live/page.tsx` | Edit — render messages/weather/intelligence, use shared timeline |
| Frontend | `race-strategy/[id]/summary/page.tsx` | Edit — use shared timeline |
| Frontend | `components/app/race-strategy/StintTimeline.tsx` | **New** |
| Frontend | `components/app/race-strategy/RaceConfigForm.tsx` | **New** |
| Frontend | `components/app/race-strategy/MessageLog.tsx` | **New** |

## Risk Assessment

- **Low risk:** Entitlement fixes (1a, 1b) — additive, existing tests cover the entitlement pipeline
- **Low risk:** Frontend UpgradeBanner wiring (2a-2c) — additive, no existing behavior changes
- **Medium risk:** Shared component extraction (4a, 4b) — refactor across 5 files, but behavior must be identical
- **Low risk:** Live enrichment (3a-3c) — wrapped in try/except, graceful degradation
- **Low risk:** Duration validation (1c) — additive guard, existing create/update flow unchanged

## Testing

- Backend: Add tests for `authorize_feature("race_strategy")` with each tier
- Backend: Add test for 3h duration enforcement in create_race/update_race
- Frontend: Visual verification of UpgradeBanner on each page
- Frontend: Verify StintTimeline renders identically after extraction
