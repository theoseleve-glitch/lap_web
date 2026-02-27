# Duality Repositioning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reframe the entire Lap Coach website, pricing, and app around the Engineer/Strategist duality with 3 B2C tiers (Demo, Racer, World-Class) + 1 B2B card.

**Architecture:** Data-first approach — rewrite pricing/claim/navigation/workflow data files, then update components that consume them, then pages, then app sidebar. Each task is self-contained and testable.

**Tech Stack:** Next.js 14 (App Router), TypeScript, Tailwind CSS, Vitest

---

### Task 1: Rewrite `pricing.ts` — New tiers, remove addons, new matrix

**Files:**
- Modify: `lap-website/src/data/pricing.ts`

**Step 1: Replace the entire pricing data file**

Replace `pricing.ts` with new Plan interface (adds `slug`, `priceAnnualPerMonth`, `annualTotal`, `savingsPercent`), 3 B2C plans:
- **DEMO** (Free) — 1 report, limited strategy (3h), 1mo retention
- **RACER** (EUR 8.99/mo, EUR 5.75/mo annual) — 10 reports, full strategy, 3mo retention
- **WORLD-CLASS** (EUR 13.99/mo, EUR 9.08/mo annual) — unlimited, comparison, API, 5 seats, 12mo retention

Remove `b2bPlans` array (3 tiers) and replace with single `B2BCard` interface and `b2bCard` object (Contact Sales).

Remove `Addon` interface and `addons` array entirely.

Replace `EligibilityRow` with new shape: `feature, group ('engineer'|'strategist'|'data'), demo, racer, worldClass` — 17 rows grouped by duality.

Add new `DataLifecycleItem` interface and `dataLifecycle` array (3 items: Raw Telemetry, Processed Reports, Live Event Data).

**Step 2: Run tests to check for breakage**

Run: `cd lap-website && npx vitest run src/__tests__/data.test.ts`
Expected: FAIL — tests expect old plan names (STARTER, PERFORMANCE, PRO RACER), old addon count, old matrix shape.

**Step 3: Commit**

```bash
git add lap-website/src/data/pricing.ts
git commit -m "feat(pricing): rewrite pricing data for duality repositioning"
```

---

### Task 2: Update `claim-registry.ts`

**Files:**
- Modify: `lap-website/src/data/claim-registry.ts`

**Step 1: Remove `webhooks_tiering` claim, update `race_strategy` status**

In the `capabilityClaims` array:
- Remove the object with `id: 'webhooks_tiering'` entirely
- Change `race_strategy` status from `'enterprise_on_request'` to `'available_now'`

**Step 2: Run tests**

Run: `cd lap-website && npx vitest run src/__tests__/claims.test.ts`

**Step 3: Commit**

```bash
git add lap-website/src/data/claim-registry.ts
git commit -m "feat(claims): remove webhooks_tiering, mark race_strategy available"
```

---

### Task 3: Update `navigation.ts`, `workflow-modules.ts`, `copy.ts`

**Files:**
- Modify: `lap-website/src/data/navigation.ts`
- Modify: `lap-website/src/data/workflow-modules.ts`
- Modify: `lap-website/src/data/copy.ts`

**Step 1: Update navigation — remove Features link**

Remove `{ label: 'Features', href: '/drivers' }` from `topNavLinks`. Result: Product, Pricing, Demo, Contact.

**Step 2: Add `group` field to workflow modules**

Add `group: 'engineer' | 'strategist' | 'operations'` to `WorkflowModule` interface and each module:
- engineer: upload-analyze, session-intelligence, comparison-progress, coaching-plans, visualization-workspace
- strategist: strategy-control-room
- operations: data-management, account-team, data-rights

**Step 3: Reframe S3 copy for duality**

Replace `s3Product` — remove `b2c`/`b2b` keys, add `engineer`/`strategist` keys:
- engineer: subhead "ENGINEER MODE", tagline "Post-session. Find where you lost time.", 3 tiles
- strategist: subhead "STRATEGIST MODE", tagline "Pre-event. Plan how you'll gain it back.", 3 new tiles (Race Plan, Live Pace, Pit Calls)

**Step 4: Commit**

```bash
git add lap-website/src/data/navigation.ts lap-website/src/data/workflow-modules.ts lap-website/src/data/copy.ts
git commit -m "feat(data): navigation, workflow groups, S3 duality copy"
```

---

### Task 4: Update `stripe-billing.ts`

**Files:**
- Modify: `lap-website/src/lib/stripe-billing.ts`

**Step 1: Rename plan IDs**

- `B2B_PLANS` set: replace 3 old names with `'FOR TEAMS & CIRCUITS'`
- `PRICE_ENV_MAP`: replace `PERFORMANCE`/`PRO RACER` with `RACER`/`WORLD-CLASS` (env vars: `STRIPE_PRICE_RACER_MONTHLY`, `STRIPE_PRICE_RACER_ANNUAL`, `STRIPE_PRICE_WORLD_CLASS_MONTHLY`, `STRIPE_PRICE_WORLD_CLASS_ANNUAL`)

**Step 2: Commit**

```bash
git add lap-website/src/lib/stripe-billing.ts
git commit -m "feat(billing): rename plan IDs to RACER and WORLD-CLASS"
```

---

### Task 5: Update checkout route + BillingLifecyclePanel

**Files:**
- Modify: `lap-website/src/app/api/billing/checkout/route.ts`
- Modify: `lap-website/src/components/site/BillingLifecyclePanel.tsx`

**Step 1: Update checkout route**

- `body.plan.toUpperCase() === 'STARTER'` -> `'DEMO'`
- redirect from `'/register?source=starter'` -> `'/register?source=demo'`

**Step 2: Update BillingLifecyclePanel**

- Default plan: `'PERFORMANCE'` -> `'RACER'`
- Default next plan: `'PRO RACER'` -> `'WORLD-CLASS'`
- Filter: `item.name !== 'STARTER'` -> `item.name !== 'DEMO'`

**Step 3: Commit**

```bash
git add lap-website/src/app/api/billing/checkout/route.ts lap-website/src/components/site/BillingLifecyclePanel.tsx
git commit -m "feat(billing): update checkout + panel for new plan names"
```

---

### Task 6: Rewrite `PricingTable.tsx` — annual-as-monthly display

**Files:**
- Modify: `lap-website/src/components/ui/PricingTable.tsx`

**Step 1: Rewrite PricingTable**

Key changes:
- When billing=annual, show `priceAnnualPerMonth` as the large price, with `annualTotal` + savings badge below
- Remove currency conversion logic (EUR only for now)
- Dim features with value `'—'` using `text-steel/40`
- Keep PitButton for highlighted plan, StampButton for others

**Step 2: Commit**

```bash
git add lap-website/src/components/ui/PricingTable.tsx
git commit -m "feat(PricingTable): annual-as-monthly display with savings badge"
```

---

### Task 7: Rewrite `PitStop.tsx` — remove audience toggle, remove addons

**Files:**
- Modify: `lap-website/src/components/rooms/PitStop.tsx`

**Step 1: Rewrite PitStop**

Key changes:
- Remove audience toggle (B2C/B2B buttons) and `audience` state
- Remove addons section and `addonsOpen` state
- Remove claim registry mapping at bottom
- Remove imports: `addons` from pricing, `getClaimsForSurface`, `trackAddonExpand`, `StatusPill`
- Keep billing toggle (monthly/annual), default annual
- Layout: `grid-cols-[3fr_1fr]` — PricingTable (3 B2C plans) + B2B card beside
- Replace subhead with "CHOOSE YOUR DEPTH"
- B2B card: title, feature bullets, Contact Sales StampButton
- CTAs: "START FREE REPORT" + "TALK TO SALES" (remove sim waitlist CTA)

**Step 2: Commit**

```bash
git add lap-website/src/components/rooms/PitStop.tsx
git commit -m "feat(PitStop): remove audience toggle and addons, add B2B card beside B2C"
```

---

### Task 8: Rewrite `S3Product.tsx` — Engineer/Strategist duality

**Files:**
- Modify: `lap-website/src/components/rooms/S3Product.tsx`

**Step 1: Replace with duality layout**

Key changes:
- Remove `ModeSelector`, `Placard`, `StampButton` imports and B2C/B2B mode state
- Remove `trackS3ModeSelect` analytics call
- Layout: `lg:grid-cols-2` — Engineer left, Strategist right
- Engineer side: acid-green header, tagline, ReportScrubber, 3 tiles
- Strategist side: pit-orange header, tagline, 3 tiles
- Each tile: `bg-asphalt/40 p-4 border border-steel/10`

**Step 2: Commit**

```bash
git add lap-website/src/components/rooms/S3Product.tsx
git commit -m "feat(S3): duality layout — Engineer left, Strategist right"
```

---

### Task 9: Update `S4WorkflowCoverage.tsx` — grouped by pillar

**Files:**
- Modify: `lap-website/src/components/rooms/S4WorkflowCoverage.tsx`

**Step 1: Group workflow modules by pillar**

Key changes:
- Iterate over groups `['engineer', 'strategist', 'operations']` instead of flat list
- Each group gets a colored header: ENGINEER (acid-green), STRATEGIST (pit-orange), OPERATIONS (steel)
- Filter `workflowModules` by `m.group === group`
- Keep existing module card layout within each group

**Step 2: Commit**

```bash
git add lap-website/src/components/rooms/S4WorkflowCoverage.tsx
git commit -m "feat(S4): group workflow modules by Engineer/Strategist/Operations"
```

---

### Task 10: Rewrite `pricing/page.tsx` — data lifecycle, new matrix

**Files:**
- Modify: `lap-website/src/app/(marketing)/pricing/page.tsx`

**Step 1: Full rewrite**

Key changes:
- Remove audience toggle, A/B experiment variant, addons section, old claim registry columns
- New imports: `b2cPlans`, `b2bCard`, `featureEligibilityMatrix`, `dataLifecycle` from pricing
- Title: "Choose Your Depth"
- Billing toggle (monthly/annual), default annual
- `grid-cols-[3fr_1fr]` layout: PricingTable + B2B card
- Feature Eligibility Matrix: 4-column table (Feature, Demo, Racer, World-Class) with group header rows (ENGINEER, STRATEGIST, DATA & OPS)
- Data Lifecycle Transparency block: 3-column grid of dataLifecycle items
- Keep JSON-LD structured data (hardcoded, no user input)

**Step 2: Commit**

```bash
git add lap-website/src/app/(marketing)/pricing/page.tsx
git commit -m "feat(pricing-page): duality matrix, data lifecycle, no addons"
```

---

### Task 11: Update `product/page.tsx` + `waitlist/page.tsx`

**Files:**
- Modify: `lap-website/src/app/(marketing)/product/page.tsx`
- Modify: `lap-website/src/app/(marketing)/waitlist/page.tsx`

**Step 1: Update product page — duality structure**

Key changes:
- Title: "Two Modes. One System."
- Two sections: ENGINEER MODE (acid-green, 2 views) + STRATEGIST MODE (pit-orange, 2 views)
- Split `featuredViews` into `engineerViews` (Corner Replay, Analysis Mode) and `strategistViews` (Dashboard, Track Map)
- Add "How They Connect" section explaining data flow
- Remove old claim registry columns
- Keep WorkflowCoverage component + Next Actions links

**Step 2: Update waitlist page**

- Remove "Webhook tiering by plan" from roadmap items list
- Add "Multisource import" to roadmap items list
- Update description text accordingly

**Step 3: Commit**

```bash
git add lap-website/src/app/(marketing)/product/page.tsx lap-website/src/app/(marketing)/waitlist/page.tsx
git commit -m "feat(pages): product duality structure, waitlist remove webhooks add multisource"
```

---

### Task 12: Update app sidebar + fix `data.test.ts`

**Files:**
- Modify: `lap-website/src/app/app/layout.tsx`
- Modify: `lap-website/src/__tests__/data.test.ts`

**Step 1: Group sidebar into Engineer/Strategist/Operations**

Replace flat `navItems` array with `navGroups: NavGroup[]`:
- ENGINEER: Dashboard, Sessions, Analyze, Compare, Coaching Plans, Visualization
- STRATEGIST: Race Strategy, Leaderboard
- OPERATIONS: Tracks, Drivers, Karts, Weekends, Exports, Data Health

Render with group label headers (font-telemetry, 10px, uppercase, steel/60 color).
Remove `annotations` link (fold into coaching plans).

**Step 2: Fix `data.test.ts`**

Update test expectations:
- B2C: 3 plans named DEMO, RACER, WORLD-CLASS; `b2cPlans[1].highlighted === true`; `ctaHref` starts with `/register?source=demo`
- B2B: assert `b2bCard.name === 'FOR TEAMS & CIRCUITS'`, features length >= 4
- Matrix: assert length >= 15, groups contain engineer/strategist/data
- Data lifecycle: assert 3 items, first is 'RAW TELEMETRY'
- Copy: assert `s3Product.engineer.tiles` has length 3 (replace old `b2b.placards` assertion)
- Remove addons assertion entirely

**Step 3: Run all tests**

Run: `cd lap-website && npx vitest run`
Expected: ALL PASS

**Step 4: Run build**

Run: `cd lap-website && npm run build`
Expected: No TypeScript errors

**Step 5: Commit**

```bash
git add lap-website/src/app/app/layout.tsx lap-website/src/__tests__/data.test.ts
git commit -m "feat(app): grouped sidebar + fix tests for duality data"
```

---

## Verification Checklist

After all 12 tasks:

1. `cd lap-website && npm run build` — no TypeScript errors
2. `cd lap-website && npx vitest run` — all tests pass
3. Manual check: homepage S3 shows Engineer/Strategist duality
4. Manual check: homepage S4 groups modules by pillar
5. Manual check: PitStop shows 3 B2C + 1 B2B card, no audience toggle, no addons
6. Manual check: `/pricing` page shows new matrix + data lifecycle
7. Manual check: `/product` page has two-pillar structure
8. Manual check: `/waitlist` shows sim racing + multisource (no webhooks)
9. Manual check: App sidebar shows Engineer/Strategist/Operations groups
10. Manual check: nav bar has Product, Pricing, Demo, Contact (no Features)
