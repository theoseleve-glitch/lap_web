# Free Report Funnel — Design Document

**Date**: 2026-02-27
**Branch**: feat/v2-experience-kernel (or new branch)
**Status**: Approved

## Goal

Provide a zero-friction free report experience: click CTA → register → upload CSV → view a limited but compelling report — driving upgrades to paid tiers.

## User Flow

```
Homepage "Start Free Report" CTA
  → /register?redirect=/free-report/analyze
  → Auto-login after registration
  → /free-report/analyze (upload + configure + process)
  → /free-report/report/[session_id] (limited report + locked sections)
```

## Architecture

### Route Group: `src/app/(free-report)/`

Isolated Next.js route group with its own layout — no sidebar, no navbar, no access to full app navigation.

**Routes:**
- `/free-report/analyze` — 3-step wizard (upload → configure → process)
- `/free-report/report/[id]` — Limited report with upgrade CTAs

### Layout: `src/app/(free-report)/layout.tsx`

Minimal chrome:
- **Left**: LAP logo (links to homepage)
- **Center**: Step indicator (Upload → Configure → Results)
- **Right**: User display name
- **No sidebar, no navbar, no SiteHeader**
- Full-width content area, dark `asphalt` background
- `QueryProvider` wrapping children

### Register Flow Changes

Modify `src/app/(auth)/register/page.tsx`:
- After successful `register()`, immediately call `login()` with same credentials
- Store tokens (access_token, refresh_token) in localStorage/cookie
- Redirect to URL from `?redirect=` query param (default: `/login?registered=true` for backward compat)

## Free Report Analyze Page

### `/free-report/analyze`

Reuses the 3-step wizard pattern from `/app/analyze` but stripped down:

**Step 1 — Upload Only** (no file browser):
- Drag-drop zone + file picker button
- No `data/raw/` file list (user has no prior files)
- Upload via `POST /api/v1/files/upload`

**Step 2 — Configure**:
- Session Type dropdown (Practice, Qualifying, Race, Test)
- Driver name (text input, not dropdown — new user has no existing drivers)
- Track name (text input with auto-detect, not dropdown)
- No Kart field (keep it simple for free tier)

**Step 3 — Processing**:
- Same polling UI: spinner + progress bar + status messages
- On complete → redirect to `/free-report/report/[session_id]`

### One-Report Limit

- Check on page load: `GET /api/v1/user/free-report-status`
  - Returns `{ used: boolean, session_id?: string }`
- If `used === true`: show message with link to existing report + upgrade CTA
- Backend: flag on user record or a check for sessions created via free-report flow

## Free Report Page

### `/free-report/report/[id]`

**Header**: Track name + driver + date + laps (same as session detail, no PageHeader)

**Visible sections (free):**
1. Score cards row: Best Time, Total Laps, Score /100, Grade
2. Score breakdown row: Pace /25, Consistency /25, Execution /25, Robustness /25
3. Track Map chart (full)
4. Speed Trace chart (full)
5. Top 1 Corner coaching card (most improvable corner with replay)

**Locked sections (blurred + upgrade overlay):**
1. "Full Overview" — GG Diagram + Driving Style placeholders, blurred
2. "Pace Analysis" — LapProgress + SectorChart + LapDistribution + LapOverlay, blurred
3. "Style Analysis" — Fingerprint + ConsistencyHeatmap + BrakeScatter + CornerMastery, blurred
4. "Physics Analysis" — EnergyBalance + FatigueChart + SpeedProfile + ThrottleHeatmap, blurred
5. "All Corners" — remaining corners blurred with count
6. "Full Lap Data" — first 3 rows visible, rest blurred

**Upgrade banner** (sticky or top):
- "You're viewing a free report. Upgrade to Performance for the full analysis."
- CTA button: "Upgrade Now" → `/pricing`
- Accent: `pit-orange` background, `asphalt` text

### `LockedSection` Component

Reusable component:
```tsx
<LockedSection title="Pace Analysis" description="See lap-by-lap progression, sector times, and distribution">
  {/* Blurred placeholder content rendered at reduced opacity */}
</LockedSection>
```
- Renders children with `blur-sm opacity-30 pointer-events-none`
- Overlay with lock icon + title + description + "Unlock with Performance" button
- Button links to `/pricing`

## New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `FreeReportLayout` | `src/app/(free-report)/layout.tsx` | Minimal chrome layout |
| `FreeReportAnalyzePage` | `src/app/(free-report)/free-report/analyze/page.tsx` | Upload wizard |
| `FreeReportPage` | `src/app/(free-report)/free-report/report/[id]/page.tsx` | Limited report |
| `LockedSection` | `src/components/app/LockedSection.tsx` | Blur + upgrade overlay |
| `UpgradeBanner` | `src/components/app/UpgradeBanner.tsx` | Top upgrade CTA bar |

## Modified Files

| File | Change |
|------|--------|
| `src/app/(auth)/register/page.tsx` | Auto-login + redirect param support |
| `src/lib/auth.ts` | Token storage helper (if not already present) |

## Code Reuse

- Chart components: `SpeedTrace`, `TrackMap` from `@/components/app/charts`
- `StatCard`, `DataTable` from `@/components/app`
- `api` client from `@/lib/api-client`
- `register`, `login` from `@/lib/auth`
- Upload logic (FormData POST) from analyze page
- Job polling pattern from analyze page

## Out of Scope

- Backend API changes for free-report-status tracking (can use localStorage initially)
- Email verification requirement for free report
- Rate limiting on uploads
- Analytics/conversion tracking for the funnel
