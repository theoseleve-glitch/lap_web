# SEO + LLM Optimization + App Consumption Tracking

**Date**: 2026-04-10
**Branch**: `feat/seo-consumption-tracking`
**Status**: Approved

## Overview

Three interconnected systems for the LAP webapp:

1. **Server-side consumption tracking** — `app_events` log + `usage_counters` table in PostgreSQL, powering both product-led growth analytics and billing metering.
2. **SEO hardening** — structured data expansion, meta completeness enforcement, breadcrumb JSON-LD, internal linking, self-check health endpoint.
3. **LLM crawler optimization (GEO)** — `llms.txt` + `llms-full.txt`, AI crawler robots.txt directives, triple schema stacking, semantic HTML hardening, content freshness signals.

## Architecture: Hybrid Counters + Event Log

Two tables working together:

- **`usage_counters`** — one row per workspace per billing period. Pre-aggregated numbers for metered actions. O(1) lookup for billing enforcement.
- **`app_events`** — raw event log for engagement analytics. Partitioned monthly, 90-day retention.

Single `/api/v1/events` endpoint handles both: inserts the raw event AND atomically increments the relevant counter when the event type maps to a metered action.

---

## Section 1: Backend Data Model & API

### New Tables (Alembic migration 017)

#### `usage_counters`

| Column | Type | Notes |
|--------|------|-------|
| `workspace_id` | INT NOT NULL | FK → workspaces(id) |
| `period_start` | DATE NOT NULL | First day of billing month |
| `uploads` | INT DEFAULT 0 | |
| `sessions_viewed` | INT DEFAULT 0 | |
| `reports_downloaded` | INT DEFAULT 0 | |
| `comparisons` | INT DEFAULT 0 | |
| `api_calls` | INT DEFAULT 0 | |

- Composite PK: `(workspace_id, period_start)`
- RLS: `workspace_id = current_setting('app.workspace_id')`

#### `app_events`

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | |
| `workspace_id` | INT NOT NULL | |
| `user_id` | INT NOT NULL | |
| `event_type` | TEXT NOT NULL | e.g. `session.view`, `chart.interact` |
| `properties` | JSONB DEFAULT '{}' | |
| `path` | TEXT | e.g. `/app/sessions/42` |
| `created_at` | TIMESTAMPTZ DEFAULT now() | |

- INDEX: `(workspace_id, event_type, created_at)`
- INDEX: `(user_id, created_at)`
- RLS: `workspace_id = current_setting('app.workspace_id')`
- PARTITION BY RANGE `(created_at)` — monthly partitions

### API Endpoints

#### `POST /api/v1/events`

Receives events from the frontend. Auth required (JWT). User + workspace derived from token/middleware.

Request:
```json
{
  "events": [
    {
      "event": "session.view",
      "properties": { "session_id": 42, "tab": "speed_trace" },
      "path": "/app/sessions/42"
    }
  ]
}
```

Response: `{ "ok": true }`

- Accepts batched events (array).
- Inserts into `app_events` AND atomically increments matching `usage_counters` column via `INSERT ... ON CONFLICT DO UPDATE SET uploads = uploads + 1`.
- Fire-and-forget from frontend — no response body needed beyond `{ok: true}`.
- Rate limited: 30 events/min per user (tier 3).

#### `GET /api/v1/usage`

Returns current period counters + plan limits for the workspace.

Response:
```json
{
  "ok": true,
  "data": {
    "period": "2026-04",
    "uploads": 12,
    "sessions_viewed": 47,
    "reports_downloaded": 8,
    "limits": { "uploads": 50, "sessions_viewed": -1, "reports_downloaded": 20 }
  }
}
```

Plan limits from Stripe tier definitions mirrored in a backend config dict (`PLAN_LIMITS` in `web/config.py`), keyed by Stripe product ID → `{uploads: int, sessions_viewed: int, reports_downloaded: int, comparisons: int}`. `-1` = unlimited. Updated when plans change — single source of truth alongside `stripe-billing.ts` on the frontend.

#### `GET /api/v1/analytics/engagement`

Workspace-scoped engagement summary for last 30 days:

```json
{
  "ok": true,
  "data": {
    "active_users": 3,
    "total_events": 412,
    "top_features": [
      { "event": "session.view", "count": 187 },
      { "event": "chart.interact", "count": 94 }
    ],
    "daily_active": [
      { "date": "2026-04-09", "users": 2, "events": 38 }
    ],
    "retention": {
      "week_1": 0.85,
      "week_2": 0.71,
      "week_4": 0.62
    }
  }
}
```

No frontend page in V1 — exposed as API for future dashboard or Plausible integration.

### Retention & Pruning

- Weekly Celery task on `default` queue drops `app_events` partitions older than 90 days.
- Monthly Celery beat task creates next month's partition ahead of time.
- `usage_counters` kept indefinitely (one row per workspace per month — negligible).

---

## Section 2: Frontend Instrumentation

### `useTrackEvent` Hook

Location: `src/hooks/useTrackEvent.ts`

```ts
useTrackEvent(event: string, properties?: Record<string, string | number | boolean>)
```

- Calls `POST /api/v1/events` via `apiFetch()` (reuses auth headers + workspace context).
- Fire-and-forget: `navigator.sendBeacon` with JSON fallback for page-unload events.
- Batches: collects up to 10 events or 5 seconds (whichever first), flushes in single request.
- Deduplicates: same `(event, path)` within 2 seconds dropped (prevents React re-render double-fires).
- Consent-gated: checks `hasAnalyticsConsent()` before sending.

### Event Catalog

| Event | Fires When | Metered Counter |
|-------|-----------|-----------------|
| `session.upload` | Upload completes successfully | `uploads` |
| `session.view` | Session detail page loads | `sessions_viewed` |
| `session.tab_switch` | User switches tab (speed/gg/corners/etc.) | — |
| `chart.interact` | Zoom, pan, hover-lock on any chart | — |
| `chart.focus_mode` | Focus mode activated | — |
| `report.download` | PDF/CSV report downloaded | `reports_downloaded` |
| `compare.run` | Comparison page loads with 2 sessions | `comparisons` |
| `corner.edit` | Corner definition saved | — |
| `track.view` | Track detail page loads | — |
| `weekend.create` | New weekend created | — |
| `search.execute` | Session list filtered/searched | — |
| `export.run` | Data export triggered | — |
| `limit.warning_shown` | 80% threshold warning displayed | — |
| `limit.reached` | User hits the wall on a metered action | — |

### Page View Tracking

`usePageView` hook (wraps `useTrackEvent`) fires `page.view` on every `/app/*` route transition via `usePathname()`. Captures:

- `path` — the route
- `referrer` — previous path (small Zustand slice or `document.referrer`)
- `time_on_page` — duration since last `page.view` (sent on NEXT navigation)

### Usage Gates (Frontend)

Upload page and gated actions call `GET /api/v1/usage` on mount:

- **>80% usage**: Subtle warning bar — `"12 of 15 uploads used this month — Upgrade for unlimited"`
- **At limit**: Upload button disables, shows limit message with link to `/pricing?reason=limit_reached&counter=uploads`.

### Usage Gates (Backend)

`@check_usage_limit(counter='uploads')` decorator on metered endpoints:

1. Read `usage_counters` for current workspace + period.
2. Look up plan limit from Stripe subscription tier.
3. Over limit → `429` with `{error: "upload_limit_reached", limit: 50, used: 50, upgrade_url: "/pricing"}`.
4. Under limit → proceed; event handler increments counter atomically after success.

---

## Section 3: SEO Performance Tracking & On-Page Hardening

### SEO Health Endpoint

`GET /api/v1/seo/health` — lightweight self-check against `routeMap`:

```json
{
  "ok": true,
  "data": {
    "sitemap_routes": 24,
    "routes_with_meta": 22,
    "routes_missing_meta": ["/billing", "/sitemap"],
    "routes_with_structured_data": 3,
    "routes_missing_og": [],
    "robots_txt_valid": true,
    "last_checked": "2026-04-10T14:30:00Z"
  }
}
```

Checks every marketing route has `metaDescription`, `primaryKeyword`, `ogTitle`, `canonical`. Can be called manually or wired into a weekly cron.

### Structured Data Expansion

| Page | Schema Type | Key Properties |
|------|------------|----------------|
| `/pricing` | `FAQPage` + `Product` with `offers` | Wire FAQ items as JSON-LD Question/Answer pairs |
| `/help` | `FAQPage` | FAQ content as structured Question/Answer |
| `/insights/[slug]` | `Article` | `author`, `datePublished`, `dateModified`, `headline` |
| `/customers` | `WebPage` with `Review` | Testimonial quotes as Review schema |
| `/changelog` | `WebPage` with `ItemList` | Release entries as structured list |

### Breadcrumb JSON-LD

New `BreadcrumbJsonLd` component rendering `BreadcrumbList` schema from existing `buildBreadcrumbs()` data. Google shows breadcrumbs in SERPs — free real estate not currently claimed.

### Internal Linking

`RelatedPages` component reads `routeMap` parent/sibling relationships, renders contextual links at bottom of marketing pages. Strengthens link graph for crawlers.

### Meta Completeness

- Ensure every marketing page calls `generateSeoMetadata()` (20 of ~24 currently do — fix remaining 4).
- Verify `<title>` includes `primaryKeyword` naturally.
- Verify `metaDescription` contains keyword within first 120 chars.

---

## Section 4: LLM Crawler Optimization (GEO)

### `llms.txt`

Served as Next.js route handler at `app/llms.txt/route.ts`. Auto-generates from `routeMap` so it stays fresh.

```
# LAP — Motorsport Telemetry Analysis Platform

> Ingests GPS and sensor telemetry from RaceChrono, RaceBox, AiM, and MoTeC.
> Scores driving across four pillars (Pace, Consistency, Execution, Robustness),
> detects corners from GPS data, and generates per-corner coaching insights
> for kart and car drivers.

## About

- **Type**: WebApplication
- **Category**: Motorsport / Telemetry Analysis / Driver Coaching
- **Language**: English
- **Audience**: Kart drivers, car racing teams, track day enthusiasts, racing coaches
- **Pricing**: Free demo, paid plans from €5.75/month
- **Last Updated**: 2026-04

## Key Pages

- [Product](/product): Platform capabilities — data ingestion, corner detection, scoring, coaching
- [Pricing](/pricing): Plan comparison — Performance, Pro Racer, and Circuit tiers
- [Customers](/customers): Case studies and performance benchmarks from racing teams
- [Help](/help): Getting started guides, FAQ, and support contact
- [Insights](/insights): Technical articles on telemetry analysis and driver coaching
- [Compare Tools](/compare-tools): LAP vs spreadsheet-based telemetry analysis
- [Security](/security): Encryption, tenant isolation, data residency, incident response

## Canonical

- **Primary URL**: https://www.lap-coach.racing
- **llms.txt Location**: https://www.lap-coach.racing/llms.txt
- **API**: https://api.lap-coach.racing

## Optional

- [Changelog](/changelog): Release notes and new features
- [Waitlist](/waitlist): Early access signup
- [Contact](/contact): Sales and partnership enquiries
```

### `llms-full.txt`

Route handler at `app/llms-full.txt/route.ts`. Longer version inlining:

- All FAQ answers from `/help`
- Pricing table details with plan names, prices, feature lists
- Feature descriptions from `/product`
- Entity glossary definitions (LAP, telemetry, session, corner, pillar scores)
- Recent changelog entries

Keep under 100KB (soft ceiling before partial indexing). Auto-generated from content data files.

### `robots.txt` — AI Crawler Directives

Update `robots.ts` with explicit tiered directives:

```
# Traditional Search
User-agent: Googlebot
Allow: /

# AI Training Crawlers (future model knowledge, 3-12 month lag)
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Applebot-Extended
Allow: /

User-agent: Meta-ExternalAgent
Allow: /

# AI Retrieval Crawlers (live AI search — blocking = instant disappearance)
User-agent: ChatGPT-User
Allow: /

User-agent: PerplexityBot
Allow: /

# Block data aggregators (no benefit)
User-agent: CCBot
Disallow: /

User-agent: DataForSeoBot
Disallow: /

# Default
User-agent: *
Allow: /
Disallow: /api/
Disallow: /app/
Disallow: /admin/

Sitemap: https://www.lap-coach.racing/sitemap.xml
Host: https://www.lap-coach.racing
```

Key context: ChatGPT-User now crawls 3.6x more than Googlebot. Retrieval crawlers power live AI search results; training crawlers affect future model knowledge.

### JSON-LD Schema Stacking

Triple stacking (Article + ItemList + FAQPage) yields 1.8x more AI citations vs single schema.

- **Root layout**: Keep `SoftwareApplication` + `Organization`. Add `WebSite` with `potentialAction: SearchAction`. Add `featureList` array to `SoftwareApplication`.
- **Pricing**: Stack `FAQPage` + `Product` with `offers` + `ItemList`.
- **Help**: `FAQPage` with actual Question/Answer pairs.
- **Insights**: `Article` + `BreadcrumbList` + author entity.
- **Customers**: `WebPage` with `Review` items.

**Critical**: JSON-LD descriptions must mirror `llms.txt` descriptions exactly. Mismatches reduce AI system confidence in both signals.

### H1 Consistency

Homepage rendered `<h1>` must cross-reference `llms.txt` description. Contain product category + outcome, not just brand name. Verify against `BRAND.tagline`.

### Content Freshness Signals

Content without freshness signals loses AI citation priority after ~14 days:

- `<time datetime>` on all insight articles and changelog entries.
- Visible "Last updated" timestamps on `/product`, `/pricing`, `/help`, `/security`.
- `llms.txt` route handler auto-sets `Last Updated` to current month on each build.

### Server-Side Rendering Verification

AI crawlers cannot execute JavaScript — they only read server-returned HTML:

- Verify marketing page content is SSR (not behind `'use client'` boundaries).
- The interactive rooms (StartGrid, S1Pain, etc.) are client components — ensure core value proposition text exists in server-rendered HTML before the interactive layer.

### Semantic HTML Hardening

- **Section-level answers**: Start each section with a clear direct answer. First 200 words must contain an extractable summary.
- **`<article>`** on insight pages and changelog entries.
- **`<section aria-labelledby>`** on marketing page rooms.
- **`<dl>`** (definition lists) for pricing comparisons and FAQ content.
- **`<time datetime>`** on changelog dates and insight publish dates.
- **`<address>`** wrapping Organization contact info in footer.

### Entity Glossary

Crawlable `<details>` element on `/product` and `/help` pages defining:

- **LAP** — Lap Analysis Platform, the product name
- **Telemetry** — GPS + sensor data from racing data loggers
- **Session** — One continuous recording from a logger device
- **Corner** — Auto-detected turn section of a racing track
- **Pillar scores** — Pace, Consistency, Execution, Robustness — each scored /25, total /100

Prevents LLM hallucination about product capabilities when citing.

---

## Files Changed

### Backend (new)
- `telemetry_tool/web/routes/events.py` — events blueprint (`POST /events`, `GET /usage`, `GET /analytics/engagement`)
- `telemetry_tool/web/routes/seo_health.py` — SEO health endpoint
- `telemetry_tool/tasks/analytics_tasks.py` — partition pruning + creation Celery tasks
- `telemetry_tool/web/middleware/usage.py` — `@check_usage_limit` decorator
- `alembic/versions/017_app_events_usage_counters.py` — migration

### Backend (modified)
- `telemetry_tool/web/app.py` — register events + seo_health blueprints
- `telemetry_tool/tasks/celery_app.py` — register analytics beat schedule

### Frontend (new)
- `src/hooks/useTrackEvent.ts` — batched event hook
- `src/hooks/usePageView.ts` — page view tracking
- `src/components/app/UsageLimitBar.tsx` — usage warning/limit UI
- `src/components/seo/BreadcrumbJsonLd.tsx` — breadcrumb structured data
- `src/components/seo/PageJsonLd.tsx` — per-page schema stacking
- `src/components/seo/RelatedPages.tsx` — internal linking component
- `src/components/seo/EntityGlossary.tsx` — crawlable glossary block
- `src/app/llms.txt/route.ts` — llms.txt route handler
- `src/app/llms-full.txt/route.ts` — llms-full.txt route handler

### Frontend (modified)
- `src/app/robots.ts` — AI crawler directives
- `src/app/layout.tsx` — enhanced JSON-LD graph
- `src/app/app/sessions/[id]/page.tsx` — session.view + tab_switch events
- `src/app/app/sessions/upload/page.tsx` — session.upload event + usage gate
- `src/app/app/compare/sessions/page.tsx` — compare.run event
- `src/app/app/dashboard/page.tsx` — page.view
- `src/app/(marketing)/pricing/page.tsx` — FAQPage + Product schema stacking
- `src/app/(marketing)/help/page.tsx` — FAQPage schema
- `src/app/(marketing)/insights/[slug]/page.tsx` — Article schema
- `src/app/(marketing)/customers/page.tsx` — Review schema
- Marketing pages missing `generateSeoMetadata()` — add calls
- Marketing page sections — `<section aria-labelledby>`, `<time>`, `<dl>` where applicable

---

## Dependencies

- No new npm packages. Uses existing `apiFetch`, consent system, Zustand.
- No new Python packages. Uses existing psycopg2, Celery, Flask decorators.
- Alembic migration 017 must run before events endpoint is deployed.

## Rollout

1. Backend: migration 017 → events blueprint → usage middleware → analytics tasks → deploy.
2. Frontend: hooks → instrumentation → SEO components → LLM files → deploy.
3. Verify: `curl /llms.txt`, `curl -A "GPTBot" /`, SEO health endpoint, submit test event.

## Sources

- [llms.txt specification](https://llmstxt.org/)
- [10 Essential llms.txt Best Practices 2026](https://www.crawleroptic.com/blog/llms-txt-best-practices)
- [Mastering GEO 2026 — Search Engine Land](https://searchengineland.com/mastering-generative-engine-optimization-in-2026-full-guide-469142)
- [Complete Robots.txt Guide for AI Crawlers](https://aicarma.com/blog/robots-txt-for-ai/)
- [ChatGPT Crawls 3.6x More Than Googlebot](https://www.searchenginejournal.com/chatgpt-googlebot-crawl-data-alliai-spa/570885/)
- [GEO: How to Win AI Mentions](https://searchengineland.com/what-is-generative-engine-optimization-geo-444418)
