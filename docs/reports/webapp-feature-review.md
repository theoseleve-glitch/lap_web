# LAP Webapp Feature Review

Date: 2026-02-27  
Source: Repository inspection of `lap-website` (routes, app navigation, workflow definitions, API handlers, and E2E coverage).

Companion export: `docs/reports/webapp-feature-review.pdf`

## Executive Summary

The webapp is organized into five product surfaces:
1. **Marketing and acquisition site** (`/(marketing)` routes).
2. **Authentication and account onboarding** (`/(auth)` routes).
3. **Free-report funnel** (`/(free-report)` routes).
4. **Core telemetry application** (`/app/*` routes).
5. **Backend-facing web APIs** (`/api/*` routes) for leads, conversion tracking, billing, and public status.

---

## 1) Marketing + Conversion Features

### Public marketing pages
- Landing and product messaging (`/`, `/product`, `/pricing`, `/demo`, `/book`).
- Persona pages (`/drivers`, `/circuits`, `/teams`, `/endurance`).
- Trust and policy pages (`/security`, `/status`, `/privacy`, `/terms`, `/dpa`).
- Proof/SEO pages (`/customers`, `/insights`, `/insights/[slug]`).
- Lead-capture support pages (`/contact`, `/waitlist`, `/thank-you/[form]`, `/billing`).

### Navigation model
- **Top navigation**: Product, Pricing, Drivers, Circuits, Teams, Endurance, Customers, Security, Insights.
- **Footer navigation**: Contact, Book, Waitlist, Billing, Status, Privacy, Terms, DPA.

### Conversion mechanics
- Lead forms are validated and forwarded to CRM/email webhook targets.
- Attribution + session IDs can be carried from cookies into lead payloads.
- Server-side conversion events are emitted for analytics pipelines.

---

## 2) Auth + User Access Features

- `/login` for sign-in.
- `/register` for account creation.
- `/verify-email` flow for email verification.
- Billing API paths enforce auth for sensitive actions (portal and plan switch), with optional guest mode based on billing auth policy.

---

## 3) Free Report Funnel Features

- `/free-report/analyze`: upload and trigger a free telemetry analysis flow.
- `/free-report/report/[id]`: view generated free report result page by report/session id.

---

## 4) Core App Feature Review (`/app`)

The in-product sidebar exposes these primary modules:
- Dashboard
- Sessions
- Tracks
- Drivers
- Analyze
- Compare
- Strategy
- Leaderboard
- Analytics
- Karts
- Weekends
- Annotations
- Dev Plans
- Exports
- Data Health

### 4.1 Dashboard
- Portfolio-level telemetry overview with key stats:
  - total sessions
  - personal best time
  - average score
  - total drivers
- Sparkline trend cards (recent score trend and lap-time trend).
- Recent sessions data table with click-through into session detail.

### 4.2 Session Intelligence
- Session list (`/app/sessions`) and session detail (`/app/sessions/[id]`).
- Corner-level drilldown (`/app/sessions/[id]/corners/[cornerId]`).
- Workflow module definitions reference dedicated views across overview/corners/timeline/analytics/lap-data style analysis surfaces.

### 4.3 Track Intelligence
- Track directory (`/app/tracks`).
- Track detail pages (`/app/tracks/[id]`).
- Track evolution history view (`/app/tracks/[id]/evolution`).

### 4.4 Driver Management + Progression
- Driver roster (`/app/drivers`).
- Driver profile (`/app/drivers/[id]`).
- Driver progression timeline (`/app/drivers/[id]/progression`).

### 4.5 Data Capture and Analysis
- New analysis workflow (`/app/analyze`) for ingest/processing.
- Setup tracker (`/app/setup-tracker`) for setup configuration records.
- Annotation workspace (`/app/annotations`) for contextual notes.

### 4.6 Comparison Suite
- Comparison home (`/app/compare`).
- Session-vs-session comparison (`/app/compare/sessions`).
- Driver-vs-driver comparison (`/app/compare/drivers`).

### 4.7 Strategy Control Room
- Strategy index (`/app/race-strategy`).
- Create strategy plan (`/app/race-strategy/new`).
- Strategy detail (`/app/race-strategy/[id]`).
- Live strategy mode (`/app/race-strategy/[id]/live`).
- Strategy summary/report (`/app/race-strategy/[id]/summary`).

### 4.8 Performance Ranking + Analytics
- Leaderboard (`/app/leaderboard`).
- Analytics hub (`/app/analytics`) and focused tools:
  - Performance trends (`/app/analytics/trends`)
  - Weather analysis (`/app/analytics/weather`)
  - Meteo correlation (`/app/analytics/meteo`)
  - Pace predictor (`/app/analytics/pace-predictor`)
  - Weight simulator (`/app/analytics/weight-simulator`)

### 4.9 Entity Management and Operations
- Kart list/create/detail (`/app/karts`, `/app/karts/new`, `/app/karts/[id]`).
- Weekend list/create/detail (`/app/weekends`, `/app/weekends/new`, `/app/weekends/[id]`).
- Export center (`/app/exports`).
- Data health queue/list (`/app/data-health`) + job detail (`/app/data-health/[id]`).
- Dev plans list/detail (`/app/dev-plans`, `/app/dev-plans/[id]`).
- Visualization workspace (`/app/visualize/[id]`).

---

## 5) API Feature Review

### Lead + conversion APIs
- `POST /api/leads`
  - validates payload fields
  - enriches UTM/session attribution from cookies
  - forwards to CRM + email delivery targets
  - emits `lead_submitted` conversion event
  - returns fallback success messaging if integrations are not configured
- `POST /api/conversions`
  - records server-side conversion events for specified event names

### Billing APIs
- `POST /api/billing/checkout`
  - supports starter redirect, B2B contact-only mode, Stripe checkout, provider webhook fallback, and local fallback URLs
- `POST /api/billing/portal`
  - authenticated billing portal access via Stripe when available, with provider/fallback options
- `POST /api/billing/switch`
  - authenticated subscription plan change path via Stripe, provider webhook, or fallback record mode

### Status API
- `GET /api/status`
  - pulls public operational status from status endpoints
  - gracefully returns fallback "Operational" payload when upstream endpoints are unavailable

---

## 6) Workflow Capability Matrix (as declared in data model)

Declared product workflow modules include:
- Upload and Analyze
- Session Intelligence
- Comparison and Progress
- Data Management
- Visualization Workspace
- Race Strategy Control Room
- Coaching Plans
- Account and Team
- Data Rights

Most are marked **available_now**, while strategy control room and account/team are marked **enterprise_on_request**.

---

## 7) QA and Test Surface (Webapp)

The webapp includes E2E specs covering key journeys:
- auth
- marketing
- upload
- sessions
- tracks
- compare
- strategy
- exports

This indicates automated coverage around both acquisition pages and core telemetry workflows.

---

## 8) Notes / Limitations of This Review

- This review is code- and route-driven from the repository rather than runtime UX validation.
- Some pages are scaffolded with placeholder/demo data patterns; exact production behavior depends on backend availability and environment configuration.
- Capability tags in workflow data represent declared product intent and may differ by deployment tier.
