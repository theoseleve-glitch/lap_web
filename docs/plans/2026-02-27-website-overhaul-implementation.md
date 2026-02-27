# Website Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix production bugs, simplify the marketing site, add bilingual FR/EN + multi-currency support, and upgrade visual presentation to compete with stint.fr.

**Architecture:** 4 incremental phases — each independently deployable. i18n uses custom JSON dictionaries + React Context (cookie-based). Currency uses static price tables. Visual upgrades follow stint.fr's screenshot-driven approach.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, Cloudflare Workers, Stripe API

---

## Phase 1 — Fix Production Bugs

### Task 1: Fix Stripe Price ID Mapping

**Files:**
- Modify: `lap-website/src/lib/stripe-billing.ts:5-10`

**Step 1: Update PRICE_ENV_MAP to match actual env var names**

The `.env.local` uses `STRIPE_PRICE_PERFORMANCE_*` and `STRIPE_PRICE_PRO_RACER_*` but the code expects `STRIPE_PRICE_RACER_*` and `STRIPE_PRICE_WORLD_CLASS_*`.

In `lap-website/src/lib/stripe-billing.ts`, replace lines 5-10:

```typescript
const PRICE_ENV_MAP: Record<string, string> = {
  'RACER:monthly': 'STRIPE_PRICE_PERFORMANCE_MONTHLY',
  'RACER:annual': 'STRIPE_PRICE_PERFORMANCE_ANNUAL',
  'WORLD-CLASS:monthly': 'STRIPE_PRICE_PRO_RACER_MONTHLY',
  'WORLD-CLASS:annual': 'STRIPE_PRICE_PRO_RACER_ANNUAL',
};
```

**Step 2: Verify the fix**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no type errors.

**Step 3: Commit**

```bash
git add lap-website/src/lib/stripe-billing.ts
git commit -m "fix: align Stripe price env var names with actual .env.local keys"
```

---

### Task 2: Fix Checkout B2C Fallback

**Files:**
- Modify: `lap-website/src/app/api/billing/checkout/route.ts:109-117`

**Step 1: Replace the generic `/book` fallback with B2C-appropriate redirect**

Currently lines 110-117 send ALL failed Stripe checkouts to `/book` (a B2B demo booking form). B2C plans should redirect to `/pricing` with an error message instead.

Replace lines 109-117 of `checkout/route.ts` with:

```typescript
  // B2C fallback: Stripe not configured or failed — redirect to pricing with error
  return NextResponse.json({
    ok: true,
    checkoutUrl: `/pricing?checkout=error&plan=${encodeURIComponent(body.plan)}`,
    mode: 'fallback',
  });
```

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add lap-website/src/app/api/billing/checkout/route.ts
git commit -m "fix: B2C checkout fallback redirects to pricing, not B2B booking form"
```

---

### Task 3: Diagnose and Fix Production Auth

**Files:**
- No code changes expected — this is a deployment/config task

**Step 1: Check what URL the frontend calls in production**

Open `https://lap-coach.racing/login` in browser DevTools → Network tab → attempt login → check the request URL. If it calls `http://localhost:5000/auth/login`, the `NEXT_PUBLIC_API_URL` was not baked into the build.

**Step 2: Rebuild and redeploy with correct env vars**

Ensure `.env.local` exists in `lap-website/` with:
```
NEXT_PUBLIC_API_URL=https://api.lap-coach.racing
```

Then rebuild and deploy:
```bash
cd lap-website && npm run cf:deploy
```

**Step 3: Set Stripe env vars on Cloudflare Workers**

Via Cloudflare dashboard or wrangler CLI, set:
- `STRIPE_SECRET_KEY`
- `STRIPE_PRICE_PERFORMANCE_MONTHLY`
- `STRIPE_PRICE_PERFORMANCE_ANNUAL`
- `STRIPE_PRICE_PRO_RACER_MONTHLY`
- `STRIPE_PRICE_PRO_RACER_ANNUAL`

**Step 4: Verify end-to-end**

1. Visit `https://lap-coach.racing/register` → create test account → should succeed
2. Visit `https://lap-coach.racing/login` → login → should succeed
3. Visit `https://lap-coach.racing/pricing` → click "Upgrade" on RACER plan → should redirect to Stripe checkout (not `/book`)

**Step 5: Commit any config changes**

```bash
git commit -m "fix: redeploy with correct NEXT_PUBLIC_API_URL for production"
```

---

## Phase 2 — Simplify the Site

### Task 4: Remove "Index" Button from Navbar

**Files:**
- Modify: `lap-website/src/components/site/SiteHeader.tsx:10-13, 15, 56-65`

**Step 1: Remove the showIndexToggle prop and button**

In `SiteHeader.tsx`:
1. Remove lines 10-13 (the `SiteHeaderProps` interface — replace with empty or remove)
2. Change line 15 to: `export function SiteHeader() {`
3. Remove lines 56-65 (the `{showIndexToggle && onIndexToggle && (...)}` block)

The component should have no props at all.

**Step 2: Remove callers of showIndexToggle**

Search for any component passing `showIndexToggle` or `onIndexToggle` props to `SiteHeader` and remove those props.

Run: `grep -r "showIndexToggle\|onIndexToggle" lap-website/src/`

Update all matches.

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add -A
git commit -m "fix: remove Index toggle button from site header"
```

---

### Task 5: Remove Persona Landing Pages

**Files:**
- Delete: `lap-website/src/app/(marketing)/drivers/page.tsx`
- Delete: `lap-website/src/app/(marketing)/circuits/page.tsx`
- Delete: `lap-website/src/app/(marketing)/teams/page.tsx`
- Delete: `lap-website/src/app/(marketing)/endurance/page.tsx`
- Delete: `lap-website/src/components/site/PersonaPage.tsx`
- Delete: `lap-website/src/data/personas.ts`
- Modify: `lap-website/src/middleware.ts:14-19, 32-44`
- Modify: `lap-website/src/app/(marketing)/page.tsx:10` (S5Personas import)
- Modify: `lap-website/src/components/rooms/S5Personas.tsx` (or delete)

**Step 1: Delete persona route files**

```bash
rm lap-website/src/app/\(marketing\)/drivers/page.tsx
rm lap-website/src/app/\(marketing\)/circuits/page.tsx
rm lap-website/src/app/\(marketing\)/teams/page.tsx
rm lap-website/src/app/\(marketing\)/endurance/page.tsx
```

Also delete the directories if they only contain page.tsx.

**Step 2: Delete persona data and component**

```bash
rm lap-website/src/data/personas.ts
rm lap-website/src/components/site/PersonaPage.tsx
```

**Step 3: Clean up middleware.ts**

Remove `PERSONA_PATHS` (lines 14-19). Simplify `detectPersona()` (lines 32-44) to:

```typescript
function detectPersona(request: NextRequest): string {
  const explicitPersona = request.nextUrl.searchParams.get('persona');
  if (explicitPersona) return explicitPersona;
  return request.cookies.get('lap_persona')?.value ?? 'drivers';
}
```

**Step 4: Remove S5Personas from home page**

In `lap-website/src/app/(marketing)/page.tsx`, remove the `S5Personas` import (line 10) and the `<S5Personas />` usage (line 24 or similar).

Delete `lap-website/src/components/rooms/S5Personas.tsx`.

**Step 5: Check for other persona imports**

Run: `grep -r "personaPages\|PersonaPage\|S5Personas\|personas" lap-website/src/ --include="*.ts" --include="*.tsx"`

Fix any remaining imports.

**Step 6: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 7: Commit**

```bash
git add -A
git commit -m "feat: remove persona landing pages and S5Personas section"
```

---

### Task 6: Remove "Seats" from Pricing

**Files:**
- Modify: `lap-website/src/data/pricing.ts:44, 73, 103, 157`

**Step 1: Remove Seats from plan features**

In `pricing.ts`:
- Remove `'Seats': '1',` from DEMO plan features (line 44)
- Remove `'Seats': '1',` from RACER plan features (line 73)
- Remove `'Seats': 'Up to 5',` from WORLD-CLASS plan features (line 103)

**Step 2: Remove Team Seats from eligibility matrix**

Remove line 157: `{ feature: 'Team Seats', group: 'data', demo: '1', racer: '1', worldClass: 'Up to 5' },`

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add lap-website/src/data/pricing.ts
git commit -m "feat: remove Seats from pricing plans and eligibility matrix"
```

---

## Phase 3 — i18n + Currency

### Task 7: Create Translation Infrastructure

**Files:**
- Create: `lap-website/src/i18n/en.json`
- Create: `lap-website/src/i18n/fr.json`
- Create: `lap-website/src/i18n/index.ts`
- Create: `lap-website/src/i18n/TranslationProvider.tsx`

**Step 1: Create the hook and provider**

Create `lap-website/src/i18n/index.ts`:

```typescript
'use client';

import { createContext, useContext } from 'react';
import en from './en.json';
import fr from './fr.json';

export type Locale = 'en' | 'fr';

const dictionaries: Record<Locale, Record<string, string>> = { en, fr };

interface TranslationContext {
  locale: Locale;
  t: (key: string, fallback?: string) => string;
}

export const I18nContext = createContext<TranslationContext>({
  locale: 'en',
  t: (key: string, fallback?: string) => fallback ?? key,
});

export function useTranslation() {
  return useContext(I18nContext);
}

export function getTranslator(locale: Locale) {
  const dict = dictionaries[locale] ?? dictionaries.en;
  const enDict = dictionaries.en;
  return (key: string, fallback?: string): string =>
    dict[key] ?? enDict[key] ?? fallback ?? key;
}

export { dictionaries };
```

**Step 2: Create the TranslationProvider**

Create `lap-website/src/i18n/TranslationProvider.tsx`:

```typescript
'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { I18nContext, getTranslator, type Locale } from './index';

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split(';')
    .map((p) => p.trim())
    .find((p) => p.startsWith(`${name}=`));
  return raw ? raw.split('=').slice(1).join('=') : undefined;
}

export function TranslationProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>('en');

  useEffect(() => {
    const cookie = getCookie('lap_locale');
    if (cookie === 'fr' || cookie === 'en') setLocale(cookie);
  }, []);

  const t = getTranslator(locale);

  return (
    <I18nContext.Provider value={{ locale, t }}>
      {children}
    </I18nContext.Provider>
  );
}
```

**Step 3: Create initial en.json with core keys**

Create `lap-website/src/i18n/en.json` — start with navigation, header, and common UI strings (~50 keys). Structure:

```json
{
  "nav.product": "Product",
  "nav.pricing": "Pricing",
  "nav.demo": "Demo",
  "nav.contact": "Contact",
  "nav.login": "Log In",
  "nav.signup": "Sign Up",
  "pricing.free": "Free",
  "pricing.monthly": "/ mo",
  "pricing.annual": "/ yr",
  "pricing.save": "Save",
  "cta.startFree": "Start Free",
  "cta.upgrade": "Upgrade",
  "cta.goWorldClass": "Go World-Class",
  "cta.contactSales": "Contact Sales",
  "cta.tryDemo": "Try Demo",
  "cta.comparePlans": "Compare Plans"
}
```

**Step 4: Create fr.json with French translations**

Create `lap-website/src/i18n/fr.json` with matching keys in French:

```json
{
  "nav.product": "Produit",
  "nav.pricing": "Tarifs",
  "nav.demo": "Démo",
  "nav.contact": "Contact",
  "nav.login": "Connexion",
  "nav.signup": "S'inscrire",
  "pricing.free": "Gratuit",
  "pricing.monthly": "/ mois",
  "pricing.annual": "/ an",
  "pricing.save": "Économisez",
  "cta.startFree": "Commencer gratuitement",
  "cta.upgrade": "Passer au supérieur",
  "cta.goWorldClass": "Passer au World-Class",
  "cta.contactSales": "Contacter l'équipe commerciale",
  "cta.tryDemo": "Essayer la démo",
  "cta.comparePlans": "Comparer les offres"
}
```

**Step 5: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 6: Commit**

```bash
git add lap-website/src/i18n/
git commit -m "feat: add i18n translation infrastructure with EN/FR dictionaries"
```

---

### Task 8: Wire TranslationProvider into Root Layout

**Files:**
- Modify: `lap-website/src/app/layout.tsx:35-61`

**Step 1: Wrap children in TranslationProvider**

In `layout.tsx`, add import at top:
```typescript
import { TranslationProvider } from '@/i18n/TranslationProvider';
```

Wrap `{children}` in the body:
```tsx
<body className="relative bg-asphalt text-chalk texture-grain">
  <TranslationProvider>
    {children}
  </TranslationProvider>
  ...
</body>
```

**Step 2: Make the html lang attribute dynamic**

This requires a client component wrapper or reading the cookie server-side. For now, keep `lang="en"` as default — the locale switcher already handles the user-facing language.

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add lap-website/src/app/layout.tsx
git commit -m "feat: wire TranslationProvider into root layout"
```

---

### Task 9: Translate Navigation and SiteHeader

**Files:**
- Modify: `lap-website/src/components/site/SiteHeader.tsx`
- Modify: `lap-website/src/data/navigation.ts`

**Step 1: Convert SiteHeader hardcoded text to t() calls**

In `SiteHeader.tsx`:
1. Add `import { useTranslation } from '@/i18n';` at top
2. Inside the component: `const { t } = useTranslation();`
3. Replace `"Log In"` (line 96) with `{t('nav.login')}`
4. Replace `"Sign Up"` (line 102) with `{t('nav.signup')}`
5. For nav links from `topNavLinks`, use `t(\`nav.${link.label.toLowerCase()}\`)` — or store translation keys in the data

**Step 2: Add nav translation keys to en.json and fr.json**

Ensure both dictionaries have all the nav keys.

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds. EN locale shows English text, FR locale shows French.

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: translate navigation and site header to FR/EN"
```

---

### Task 10: Add Full French Translations (All Marketing Content)

**Files:**
- Modify: `lap-website/src/i18n/en.json` — expand to ~300 keys
- Modify: `lap-website/src/i18n/fr.json` — full French translations
- Modify: ~20 component files to use `t()` calls

**Step 1: Extract all hardcoded strings from marketing pages**

Work through each marketing page systematically:
1. Home page rooms (StartGrid, S1Pain, S1DeepSculpture, S2Pipeline, S2Proof, S3Product, S4WorkflowCoverage, PitStop, Garage, Podium)
2. Product page
3. Pricing page
4. Demo page
5. Contact page
6. Auth pages (login, register)
7. Free report pages
8. Legal pages (privacy, terms, DPA)

For each component:
- Replace hardcoded English strings with `t('section.key')` calls
- Add both EN and FR translations to the JSON files
- Group keys by section: `home.pain.title`, `product.engineer.title`, `pricing.demo.name`, etc.

**Step 2: Translate workflow modules data**

In `workflow-modules.ts`, replace static strings with translation key lookups. Since this is a data file (not a component), convert the module titles/summaries/steps to use translation keys that the component can resolve via `t()`.

**Step 3: Translate pricing data**

In `pricing.ts`, feature names need to use translation keys since they appear in the UI.

**Step 4: Verify build and visual check**

Run: `cd lap-website && npm run build && npm run dev`
Expected: Build succeeds. Switch to FR locale in the header → all marketing content shows in French.

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: complete FR/EN translations for all marketing content (~300 keys)"
```

---

### Task 11: Add Multi-Currency Pricing (EUR, USD, GBP)

**Files:**
- Create: `lap-website/src/data/pricing-currencies.ts`
- Modify: `lap-website/src/components/site/LocaleSwitcher.tsx`
- Modify: `lap-website/src/middleware.ts`
- Modify: pricing page component to use dynamic prices

**Step 1: Create multi-currency price table**

Create `lap-website/src/data/pricing-currencies.ts`:

```typescript
export type Currency = 'eur' | 'usd' | 'gbp';

export interface PriceSet {
  symbol: string;
  racer_monthly: string;
  racer_annual: string;
  racer_annual_per_month: string;
  racer_annual_total: string;
  racer_savings: string;
  worldClass_monthly: string;
  worldClass_annual: string;
  worldClass_annual_per_month: string;
  worldClass_annual_total: string;
  worldClass_savings: string;
}

export const currencyPrices: Record<Currency, PriceSet> = {
  eur: {
    symbol: '€',
    racer_monthly: '€8.99',
    racer_annual: '€69',
    racer_annual_per_month: '€5.75',
    racer_annual_total: '€69/yr',
    racer_savings: '36',
    worldClass_monthly: '€13.99',
    worldClass_annual: '€109',
    worldClass_annual_per_month: '€9.08',
    worldClass_annual_total: '€109/yr',
    worldClass_savings: '35',
  },
  usd: {
    symbol: '$',
    racer_monthly: '$9.99',
    racer_annual: '$79',
    racer_annual_per_month: '$6.58',
    racer_annual_total: '$79/yr',
    racer_savings: '34',
    worldClass_monthly: '$15.99',
    worldClass_annual: '$119',
    worldClass_annual_per_month: '$9.92',
    worldClass_annual_total: '$119/yr',
    worldClass_savings: '38',
  },
  gbp: {
    symbol: '£',
    racer_monthly: '£7.99',
    racer_annual: '£59',
    racer_annual_per_month: '£4.92',
    racer_annual_total: '£59/yr',
    racer_savings: '38',
    worldClass_monthly: '£11.99',
    worldClass_annual: '£99',
    worldClass_annual_per_month: '£8.25',
    worldClass_annual_total: '£99/yr',
    worldClass_savings: '31',
  },
};
```

**Step 2: Create useCurrency hook**

Add to the same file or create `lap-website/src/hooks/useCurrency.ts`:

```typescript
'use client';

import { useEffect, useState } from 'react';
import { currencyPrices, type Currency, type PriceSet } from '@/data/pricing-currencies';

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split(';')
    .map((p) => p.trim())
    .find((p) => p.startsWith(`${name}=`));
  return raw ? raw.split('=').slice(1).join('=') : undefined;
}

export function useCurrency(): { currency: Currency; prices: PriceSet } {
  const [currency, setCurrency] = useState<Currency>('eur');

  useEffect(() => {
    const cookie = getCookie('lap_currency');
    if (cookie === 'eur' || cookie === 'usd' || cookie === 'gbp') {
      setCurrency(cookie);
    }
  }, []);

  return { currency, prices: currencyPrices[currency] };
}
```

**Step 3: Add GBP to LocaleSwitcher**

In `LocaleSwitcher.tsx`:
1. Change type: `type Currency = 'eur' | 'usd' | 'gbp';`
2. Update the cookie check: `if (cookieCurrency === 'usd' || cookieCurrency === 'eur' || cookieCurrency === 'gbp') setCurrency(cookieCurrency);`
3. Add GBP option: `<option value="gbp">GBP</option>`

**Step 4: Update middleware to support GBP cookie value**

No code change needed — the middleware already accepts any string value for `lap_currency`. The cookie will just have `gbp` as a value.

**Step 5: Wire pricing page to use useCurrency**

Update the pricing page component to use `useCurrency()` hook instead of hardcoded EUR values from `pricing.ts`. The `b2cPlans` array price fields should be replaced with values from the `PriceSet`.

**Step 6: Wire currency into Stripe checkout**

The checkout route already passes `body.currency` to Stripe (line 60-62 of `checkout/route.ts`). The pricing page just needs to include the currency in the checkout POST body — read it from the `lap_currency` cookie.

**Step 7: Verify**

Run: `cd lap-website && npm run build && npm run dev`
Expected: Switch currency in header → pricing page updates to show USD/GBP/EUR prices.

**Step 8: Commit**

```bash
git add -A
git commit -m "feat: add EUR/USD/GBP multi-currency pricing with useCurrency hook"
```

---

## Phase 4 — Visual Upgrades

### Task 12: Add Throttle Trace (Green) to Telemetry Canvas

**Files:**
- Modify: `lap-website/src/components/mechanisms/TelemetryTracesCanvas.tsx:37-41`

**Step 1: Add throttle trace generator**

Add after the `generateSteeringTrace` function (after line 35):

```typescript
function generateThrottleTrace(steps: number): number[] {
  return Array.from({ length: steps }, (_, i) => {
    const t = i / steps;
    return 0.7 + 0.25 * Math.sin(t * Math.PI * 5) - 0.15 * Math.abs(Math.sin(t * Math.PI * 8));
  });
}
```

**Step 2: Add throttle to TRACES array**

Update the TRACES array (lines 37-41) to include throttle in green:

```typescript
const TRACES = [
  { name: 'speed', color: colors.chalk, data: generateSpeedTrace(200), width: 3 },
  { name: 'throttle', color: colors.acidGreen, data: generateThrottleTrace(200), width: 2.5 },
  { name: 'brake', color: colors.safetyRed, data: generateBrakeTrace(200), width: 2.5 },
  { name: 'steering', color: colors.steel, data: generateSteeringTrace(200), width: 2 },
];
```

**Step 3: Update the aria-label**

Change the canvas aria-label (line 103) to include throttle:
```
"Telemetry traces visualization — speed, throttle, brake, and steering data"
```

**Step 4: Verify visually**

Run: `cd lap-website && npm run dev`
Expected: The telemetry canvas now shows 4 traces including a green throttle trace.

**Step 5: Commit**

```bash
git add lap-website/src/components/mechanisms/TelemetryTracesCanvas.tsx
git commit -m "feat: add green throttle trace to telemetry canvas visualization"
```

---

### Task 13: Build Screenshot Gallery Component

**Files:**
- Create: `lap-website/src/components/site/ScreenshotGallery.tsx`

**Step 1: Create the reusable gallery component**

Create `lap-website/src/components/site/ScreenshotGallery.tsx`:

```typescript
'use client';

import { useState } from 'react';

interface ScreenshotItem {
  title: string;
  description: string;
  src: string;
}

interface ScreenshotGalleryProps {
  items: ScreenshotItem[];
  accentColor?: string;
}

export function ScreenshotGallery({ items, accentColor = 'var(--color-acid-green)' }: ScreenshotGalleryProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  if (items.length === 0) return null;
  const active = items[activeIndex];

  return (
    <div className="space-y-4">
      {/* Hero screenshot */}
      <button
        type="button"
        className="relative w-full border border-steel/20 bg-concrete/30 overflow-hidden group cursor-zoom-in"
        onClick={() => setLightboxOpen(true)}
      >
        <img
          src={active.src}
          alt={active.title}
          className="w-full h-[400px] md:h-[500px] object-contain bg-asphalt"
        />
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-asphalt/90 to-transparent p-4">
          <h3 className="font-monument text-lg" style={{ color: accentColor }}>{active.title}</h3>
          <p className="text-steel text-sm">{active.description}</p>
        </div>
      </button>

      {/* Thumbnail strip */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        {items.map((item, i) => (
          <button
            key={item.title}
            type="button"
            className={`flex-shrink-0 border-2 transition-colors ${
              i === activeIndex ? 'border-current' : 'border-steel/20 hover:border-steel/50'
            }`}
            style={i === activeIndex ? { borderColor: accentColor } : undefined}
            onClick={() => setActiveIndex(i)}
          >
            <img
              src={item.src}
              alt={item.title}
              className="w-24 h-16 md:w-32 md:h-20 object-cover"
            />
          </button>
        ))}
      </div>

      {/* Lightbox modal */}
      {lightboxOpen && (
        <div
          className="fixed inset-0 z-[999] bg-asphalt/95 flex items-center justify-center p-4"
          onClick={() => setLightboxOpen(false)}
          role="dialog"
          aria-modal="true"
        >
          <button
            type="button"
            className="absolute top-4 right-4 text-steel hover:text-chalk text-2xl"
            onClick={() => setLightboxOpen(false)}
            aria-label="Close"
          >
            &times;
          </button>
          <img
            src={active.src}
            alt={active.title}
            className="max-w-full max-h-[90vh] object-contain"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add lap-website/src/components/site/ScreenshotGallery.tsx
git commit -m "feat: add reusable ScreenshotGallery component with lightbox"
```

---

### Task 14: Redesign Product Page with Screenshot Gallery

**Files:**
- Modify: `lap-website/src/app/(marketing)/product/page.tsx`

**Step 1: Replace image card grids with ScreenshotGallery**

Replace the `engineerViews` and `strategistViews` arrays with more screenshots (4-6 per mode), then use the `ScreenshotGallery` component:

```typescript
import { ScreenshotGallery } from '@/components/site/ScreenshotGallery';

const engineerScreenshots = [
  { title: 'Score Overview', description: 'Pace, Consistency, Execution, Robustness — each scored /25.', src: '/images/screenshots/score-overview.png' },
  { title: 'Corner Replay', description: 'Entry, apex, and exit traces to spot where the lap was won or lost.', src: '/images/screenshots/corner-replay.png' },
  { title: 'Session Intelligence', description: 'Overview, Corners, Timeline, Analytics, and Lap Data tabs.', src: '/images/screenshots/session-detail.png' },
  { title: 'Comparison Suite', description: 'Session-vs-session and driver-vs-driver overlays.', src: '/images/screenshots/comparison.png' },
];

const strategistScreenshots = [
  { title: 'Race Strategy Dashboard', description: 'Live operational board for stint calls and pit-window decisions.', src: '/images/screenshots/dashboard-hero.png' },
  { title: 'Live Monitoring', description: 'Real-time pace deltas and stint progress.', src: '/images/screenshots/live-monitoring.png' },
  { title: 'Pit Stop Planning', description: 'Plan pit windows based on fuel, tire, and driver rotation.', src: '/images/screenshots/pit-planning.png' },
  { title: 'Lap Analysis Table', description: 'Detailed lap-by-lap data with sector splits.', src: '/images/screenshots/lap-table.png' },
];
```

Then in the JSX, replace the card grids with:
```tsx
<section className="mb-10">
  <h2 className="font-monument text-[var(--text-h2)] mb-2 text-acid-green">Engineer Mode</h2>
  <p className="text-steel mb-4">Upload. Score. Coach. Compare. Visualize.</p>
  <ScreenshotGallery items={engineerScreenshots} accentColor="var(--color-acid-green)" />
</section>

<section className="mb-10">
  <h2 className="font-monument text-[var(--text-h2)] mb-2 text-pit-orange">Strategist Mode</h2>
  <p className="text-steel mb-4">Control Room. Live Monitoring. Pit Planning. Incidents.</p>
  <ScreenshotGallery items={strategistScreenshots} accentColor="var(--color-pit-orange)" />
</section>
```

**Step 2: Verify visually**

Run: `cd lap-website && npm run dev` → visit `/product`
Expected: Full-width screenshot galleries for each mode with thumbnail strips and lightbox zoom.

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: redesign product page with full-width screenshot galleries"
```

---

### Task 15: Redesign Workflow Coverage Component

**Files:**
- Modify: `lap-website/src/components/site/WorkflowCoverage.tsx`

**Step 1: Redesign to icon-card grid with screenshot panel**

Replace the current vertical list with a stint.fr-inspired layout:
- 3-column header: ENGINEER | STRATEGIST | OPERATIONS
- Module cards arranged in their group columns
- Active module shows a screenshot preview below
- Feature count badges

```typescript
'use client';

import { useState } from 'react';
import { workflowModules } from '@/data/workflow-modules';
import { StatusPill } from '@/components/site/StatusPill';
import { useTranslation } from '@/i18n';

const GROUP_LABELS = {
  engineer: { label: 'Engineer', color: 'text-acid-green', border: 'border-acid-green/30' },
  strategist: { label: 'Strategist', color: 'text-pit-orange', border: 'border-pit-orange/30' },
  operations: { label: 'Operations', color: 'text-steel', border: 'border-steel/30' },
} as const;

const groups = ['engineer', 'strategist', 'operations'] as const;

export function WorkflowCoverage() {
  const { t } = useTranslation();
  const [activeModule, setActiveModule] = useState(workflowModules[0].id);
  const active = workflowModules.find((m) => m.id === activeModule) ?? workflowModules[0];

  return (
    <div className="space-y-6">
      {/* Module count badge */}
      <div className="flex items-center gap-3 mb-4">
        <span className="font-monument text-[var(--text-h3)]">{workflowModules.length}</span>
        <span className="text-steel text-sm">{t('workflow.moduleCount', 'workflow modules')}</span>
      </div>

      {/* 3-column group grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {groups.map((group) => {
          const meta = GROUP_LABELS[group];
          const modules = workflowModules.filter((m) => m.group === group);
          return (
            <div key={group}>
              <h3 className={`font-monument text-sm uppercase tracking-[0.15em] mb-3 ${meta.color}`}>
                {meta.label}
              </h3>
              <div className="space-y-2">
                {modules.map((mod) => (
                  <button
                    key={mod.id}
                    type="button"
                    className={`w-full text-left px-3 py-2 border transition-colors ${
                      activeModule === mod.id
                        ? `${meta.border} bg-concrete/50`
                        : 'border-steel/20 hover:border-steel/40'
                    }`}
                    onClick={() => setActiveModule(mod.id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-chalk">{mod.title}</span>
                      <StatusPill status={mod.status} />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Active module detail */}
      <div className="border border-steel/20 bg-concrete/30 p-5">
        <h3 className="font-monument text-[var(--text-h3)] mb-2">{active.title}</h3>
        <p className="text-steel mb-4">{active.summary}</p>
        <ol className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {active.steps.map((step, i) => (
            <li key={step} className="border border-steel/20 bg-asphalt/40 px-3 py-2 text-sm text-chalk">
              <span className="font-telemetry text-steel mr-2">{String(i + 1).padStart(2, '0')}</span>
              {step}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
```

**Step 2: Verify visually**

Run: `cd lap-website && npm run dev` → visit `/product`
Expected: 3-column workflow grid with clickable modules and detail panel below.

**Step 3: Commit**

```bash
git add lap-website/src/components/site/WorkflowCoverage.tsx
git commit -m "feat: redesign WorkflowCoverage with stint-inspired 3-column grid layout"
```

---

### Task 16: Final Build Verification and Deploy

**Step 1: Full lint and build check**

```bash
cd lap-website && npm run lint && npm run build
```

Expected: No errors.

**Step 2: Run tests**

```bash
cd lap-website && npm run test
```

Expected: All tests pass (some may need updates if they reference deleted persona pages).

**Step 3: Visual smoke test**

Run `npm run dev` and check:
1. Home page — no S5Personas, no Index button
2. Product page — screenshot galleries working
3. Pricing page — no Seats, currency switcher changes prices
4. Locale switcher — FR shows French text
5. `/drivers` → should 404 (persona pages removed)
6. Login/register → should reach the API

**Step 4: Deploy to production**

```bash
cd lap-website && npm run cf:deploy
```

**Step 5: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final verification and deploy for website overhaul"
```

---

## Summary

| Task | Phase | Description | Est. Complexity |
|------|-------|-------------|----------------|
| 1 | P1 | Fix Stripe price ID mapping | Simple |
| 2 | P1 | Fix B2C checkout fallback | Simple |
| 3 | P1 | Diagnose/fix production auth | Config |
| 4 | P2 | Remove Index button | Simple |
| 5 | P2 | Remove persona pages | Medium |
| 6 | P2 | Remove Seats from pricing | Simple |
| 7 | P3 | i18n infrastructure | Medium |
| 8 | P3 | Wire TranslationProvider | Simple |
| 9 | P3 | Translate nav + header | Simple |
| 10 | P3 | Full FR translations (~300 keys) | Large |
| 11 | P3 | Multi-currency EUR/USD/GBP | Medium |
| 12 | P4 | Add green throttle trace | Simple |
| 13 | P4 | Build ScreenshotGallery component | Medium |
| 14 | P4 | Redesign product page | Medium |
| 15 | P4 | Redesign WorkflowCoverage | Medium |
| 16 | P4 | Final verification + deploy | Config |
