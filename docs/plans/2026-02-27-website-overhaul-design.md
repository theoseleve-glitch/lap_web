# Website Overhaul — Design

**Date:** 2026-02-27
**Scope:** Bug fixes, site simplification, i18n/currency, visual upgrades
**Competitor Reference:** stint.fr (kart endurance strategy app)
**Feature Review:** docs/reports/webapp-feature-review.pdf

---

## Context

The LAP webapp has ~10x the feature surface of stint.fr (the primary competitor for race strategy). However, several production issues are blocking the site:

- Auth, demo analysis, and all API-dependent features are broken on production
- Stripe checkout falls through to a booking form for all plans (B2C and B2B)
- The locale/currency switchers exist but do nothing (no translation dictionaries, hardcoded EUR pricing)
- Persona landing pages (/drivers, /circuits, /teams, /endurance) add complexity without conversion value
- The marketing site is English-only; target market is primarily French

### Diagnostic Findings

| Issue | Root Cause | Evidence |
|-------|-----------|----------|
| API healthz | **OK** — db, redis, celery all healthy | `GET /healthz` → `{"status":"ok"}` |
| CORS | **OK** — `Access-Control-Allow-Origin: https://lap-coach.racing`, credentials allowed | OPTIONS preflight test |
| Auth broken | Likely `NEXT_PUBLIC_API_URL` not baked into Cloudflare Workers build, or frontend redeployment needed | API endpoints respond correctly (405 for GET on POST-only routes) |
| Stripe checkout | **Confirmed** — env var name mismatch | `.env.local` has `STRIPE_PRICE_PERFORMANCE_*` / `STRIPE_PRICE_PRO_RACER_*` but code expects `STRIPE_PRICE_RACER_*` / `STRIPE_PRICE_WORLD_CLASS_*` |
| Checkout fallback | B2C plans fall to `/book` form (B2B form) when Stripe fails | `checkout/route.ts:110-117` sends ALL failures to `/book` |
| i18n | Cookie mechanism + LocaleSwitcher exist, zero translation files | `LocaleSwitcher.tsx` sets cookie and reloads, nothing reads translations |
| Currency | Hardcoded EUR in `pricing.ts`, LocaleSwitcher only offers EUR/USD | No price tables for other currencies |

---

## Phase 1 — Fix Production Bugs

### 1.1 Diagnose and Fix Auth/API on Production

**Problem:** Auth, demo analysis, and all API calls fail on `lap-coach.racing`.

**Investigation steps:**
1. Open browser DevTools on `lap-coach.racing/login`, check network tab for the actual API URL being called
2. If calling `localhost:5000` → `NEXT_PUBLIC_API_URL` was not present at build time
3. If calling correct URL → inspect specific error (CORS, 401, 500, cookie issues)

**Fix:**
- Ensure `.env.local` (or `.env.production`) has `NEXT_PUBLIC_API_URL=https://api.lap-coach.racing`
- Rebuild and redeploy: `npm run cf:deploy`
- Verify auth flow works end-to-end

### 1.2 Fix Stripe Checkout

**Problem:** Env var names don't match code expectations.

**Current .env.local:**
```
STRIPE_PRICE_PERFORMANCE_MONTHLY=price_1T5Ijf...
STRIPE_PRICE_PERFORMANCE_ANNUAL=price_1T5IqJ...
STRIPE_PRICE_PRO_RACER_MONTHLY=price_1T5Iod...
STRIPE_PRICE_PRO_RACER_ANNUAL=price_1T5IlE...
```

**Code expects (stripe-billing.ts PRICE_ENV_MAP):**
```
STRIPE_PRICE_RACER_MONTHLY
STRIPE_PRICE_RACER_ANNUAL
STRIPE_PRICE_WORLD_CLASS_MONTHLY
STRIPE_PRICE_WORLD_CLASS_ANNUAL
```

**Fix:** Update `PRICE_ENV_MAP` in `stripe-billing.ts` to match actual env var names:
```typescript
const PRICE_ENV_MAP: Record<string, string> = {
  'RACER:monthly': 'STRIPE_PRICE_PERFORMANCE_MONTHLY',
  'RACER:annual': 'STRIPE_PRICE_PERFORMANCE_ANNUAL',
  'WORLD-CLASS:monthly': 'STRIPE_PRICE_PRO_RACER_MONTHLY',
  'WORLD-CLASS:annual': 'STRIPE_PRICE_PRO_RACER_ANNUAL',
};
```

Also ensure these are set as Cloudflare Workers secrets via wrangler or the dashboard.

### 1.3 Sales Form — B2B Only

**Problem:** When Stripe fails, ALL plans redirect to `/book` (a demo booking form).

**Fix in `checkout/route.ts`:**
- B2C plans with failed Stripe → redirect to `/register?source=upgrade&plan=...` with error messaging
- Only B2B plans (detected by `isB2BPlan()`) → redirect to `/contact?plan=...`
- Remove the generic `/book` fallback for B2C

---

## Phase 2 — Simplify the Site

### 2.1 Remove "Index" Button from Navbar

**Files:**
- `SiteHeader.tsx` — Remove lines 56-65 (the `showIndexToggle` conditional block)
- Remove `showIndexToggle` / `onIndexToggle` props from `SiteHeaderProps` interface
- Update any parent that passes these props (likely the home page layout)

### 2.2 Remove Persona Landing Pages

**Delete routes:**
- `src/app/(marketing)/drivers/`
- `src/app/(marketing)/circuits/`
- `src/app/(marketing)/teams/`
- `src/app/(marketing)/endurance/`

**Delete components/data:**
- `src/components/site/PersonaPage.tsx`
- `src/data/personas.ts`

**Update middleware.ts:**
- Remove `PERSONA_PATHS` object (lines 14-19)
- Remove `detectPersona()` function's path-based logic
- Keep cookie-based persona detection (it's used for A/B experiments)

**Update home page:**
- Remove or replace `S5Personas` room section with a simpler CTA block

### 2.3 Remove "Seats" from Pricing

**In `pricing.ts`:**
- Remove `'Seats': '1'` from DEMO plan features
- Remove `'Seats': '1'` from RACER plan features
- Remove `'Seats': 'Up to 5'` from WORLD-CLASS plan features
- Remove `{ feature: 'Team Seats', group: 'data', ... }` row from `featureEligibilityMatrix`

---

## Phase 3 — i18n + Currency

### 3.1 Translation Infrastructure

**Architecture:** Custom JSON dictionaries + React Context (cookie-based locale)

**Why not next-intl or react-i18next:**
- Route-based locales (/fr/pricing) would break existing URLs and SEO
- The `lap_locale` cookie mechanism already exists
- `LocaleSwitcher` component already handles cookie + reload
- Content is largely static marketing copy (not dynamic pluralization-heavy)

**New files:**
```
src/i18n/
  en.json          # ~300-400 flat key-value pairs
  fr.json          # French translations
  index.ts         # useTranslation() hook + TranslationProvider
```

**Hook API:**
```typescript
function useTranslation(): { t: (key: string, fallback?: string) => string; locale: string }
```

**Integration:**
- Wrap root layout in `TranslationProvider`
- Provider reads `lap_locale` cookie on mount
- `t('nav.product')` → looks up in loaded dictionary → returns translated string
- Fallback: English string if key missing in target locale

### 3.2 Translation Scope

| Category | Estimated Keys | Source Files |
|----------|---------------|-------------|
| Navigation | ~15 | `navigation.ts`, `SiteHeader.tsx` |
| Home page rooms | ~60 | 11 room components |
| Product page | ~20 | `product/page.tsx` |
| Pricing | ~40 | `pricing.ts`, `pricing/page.tsx` |
| Forms (demo, book, contact) | ~30 | `LeadForm.tsx`, form pages |
| Auth (login, register) | ~15 | auth pages |
| App sidebar + labels | ~30 | sidebar component, page titles |
| Workflow modules | ~40 | `workflow-modules.ts` |
| Legal pages | ~20 | privacy, terms, DPA |
| Misc (buttons, errors, status) | ~30 | various |
| **Total** | **~300** | |

### 3.3 Currency Support

**Currencies:** EUR, USD, GBP

**Data structure in `pricing-currencies.ts`:**
```typescript
export const currencyPrices: Record<Currency, PriceSet> = {
  eur: { racer_monthly: '€8.99', racer_annual: '€69', worldClass_monthly: '€13.99', worldClass_annual: '€109' },
  usd: { racer_monthly: '$9.99', racer_annual: '$79', worldClass_monthly: '$15.99', worldClass_annual: '$119' },
  gbp: { racer_monthly: '£7.99', racer_annual: '£59', worldClass_monthly: '£11.99', worldClass_annual: '£99' },
};
```

**Changes:**
- Add `gbp` to `LocaleSwitcher` type union and dropdown
- Update middleware to support `gbp` cookie
- Create `useCurrency()` hook that reads cookie, returns price set
- Update `PricingTable` component to use `useCurrency()` instead of hardcoded EUR
- Stripe checkout already passes `currency` parameter — just wire up the cookie value

---

## Phase 4 — Visual Upgrades

### 4.1 Screenshot Gallery on Product Page

**Current:** Two 2-column grids with small image cards (200px tall, `object-cover`)

**Target:** Full-width interactive screenshot gallery per mode, inspired by stint.fr:
- Hero screenshot: full-width, ~500px tall, `object-contain`
- Thumbnail strip below: 4-6 clickable thumbnails per mode
- Click thumbnail → swap hero image
- Click hero → lightbox modal with zoom
- Need actual app screenshots captured from the production app

**Files changed:**
- `product/page.tsx` — replace card grids with gallery components
- New: `ScreenshotGallery.tsx` component (reusable for both modes)

### 4.2 Throttle Trace Color → Green

**Target:** Make throttle traces render in green instead of current color.

**Files to investigate:**
- `src/components/mechanisms/TelemetryTraces.tsx`
- `src/components/mechanisms/TelemetryTracesCanvas.tsx`
- Any chart config defining channel-to-color mapping

### 4.3 Workflow Coverage Redesign

**Current (`WorkflowCoverage.tsx`):** Grouped card list with numbered steps per module.

**Target (stint.fr-inspired):**
- 3-column layout: Engineer | Strategist | Operations
- Each module as an icon card (not a text list)
- Clicking a module shows a big screenshot of that module's interface
- Feature count badges emphasizing LAP has more features than competitors
- Status indicators (available / enterprise) as subtle badges

**Data notes:**
- LAP has 9 modules (vs stint's 6 components)
- All except "Account and Team" are `available_now`
- Should emphasize breadth advantage

---

## Files Inventory (All Changes)

### Phase 1
- `lap-website/src/lib/stripe-billing.ts` — Fix PRICE_ENV_MAP
- `lap-website/src/app/api/billing/checkout/route.ts` — Fix B2C fallback
- Cloudflare Workers env vars — Add Stripe secrets
- Rebuild + redeploy

### Phase 2
- `lap-website/src/components/site/SiteHeader.tsx` — Remove Index button
- `lap-website/src/app/(marketing)/drivers/` — Delete
- `lap-website/src/app/(marketing)/circuits/` — Delete
- `lap-website/src/app/(marketing)/teams/` — Delete
- `lap-website/src/app/(marketing)/endurance/` — Delete
- `lap-website/src/components/site/PersonaPage.tsx` — Delete
- `lap-website/src/data/personas.ts` — Delete
- `lap-website/src/middleware.ts` — Remove persona paths
- `lap-website/src/components/rooms/S5Personas.tsx` — Remove or replace
- `lap-website/src/data/pricing.ts` — Remove Seats rows

### Phase 3
- `lap-website/src/i18n/en.json` — New: English dictionary
- `lap-website/src/i18n/fr.json` — New: French dictionary
- `lap-website/src/i18n/index.ts` — New: hook + provider
- `lap-website/src/app/layout.tsx` — Wrap in TranslationProvider
- `lap-website/src/components/site/LocaleSwitcher.tsx` — Add GBP
- `lap-website/src/middleware.ts` — Support gbp
- `lap-website/src/data/pricing-currencies.ts` — New: multi-currency prices
- ~30 component files — Replace hardcoded strings with `t()` calls

### Phase 4
- `lap-website/src/app/(marketing)/product/page.tsx` — Gallery redesign
- `lap-website/src/components/site/ScreenshotGallery.tsx` — New component
- `lap-website/src/components/site/WorkflowCoverage.tsx` — Redesign
- `lap-website/src/components/mechanisms/TelemetryTraces*.tsx` — Color change

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Translation quality | Use professional-grade French (user is native speaker, can review) |
| USD/GBP price accuracy | Set competitive prices manually; Stripe handles actual billing |
| Missing app screenshots | Capture from production app after Phase 1 fixes it |
| SEO impact from removing pages | Add redirects from deleted persona pages to / |
| Large blast radius on i18n | Extract strings incrementally; fallback to English for any missing key |
