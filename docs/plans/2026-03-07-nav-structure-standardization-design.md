# Navigation & Page Structure Standardization — Design

**Date**: 2026-03-07
**Status**: Approved
**Approach**: Config-Driven (Approach B)
**Branch**: `feat/nav-structure-standardization`

## Goal

Standardize navigation and page structure across marketing and app routes:
- Canonical marketing nav (5 items) with no per-page variants
- Breadcrumbs for subpages
- Consistent page intro and section rhythm
- Correct heading hierarchy (exactly one H1, sequential levels)
- Global skip link + focus styles (already partially present)
- Minimal legal footer on `/app` routes
- Standardized back navigation
- Sticky section tabs for long marketing pages

## Decisions

| Question | Decision |
|----------|----------|
| Nav scope | Marketing top nav only. App sidebar is a separate concern. |
| App footer style | Minimal legal bar: Privacy, Terms, Security, Status |
| SectionTabs initial rollout | All marketing content pages (pricing, product, demo, security, privacy, etc.) |

## Architecture: Route Map Config

Single config file `src/data/route-map.ts` drives breadcrumbs, page intros, and section tabs.

```typescript
export interface RouteEntry {
  path: string;
  title: string;
  subtitle?: string;
  badge?: string;
  eyebrow?: string;
  parent: string | null;        // null = top-level (no breadcrumb)
  sectionAnchors?: { id: string; label: string }[];
}

export const routeMap: Record<string, RouteEntry> = { /* ... */ };
```

**Rules**:
- `parent: null` = top-level page, no breadcrumb shown
- `parent: '/pricing'` = subpage, breadcrumb: Home > Pricing > [page]
- `sectionAnchors` present = SectionTabs rendered
- Every marketing page must have an entry (lint enforced)

## Components

### Breadcrumb (`src/components/ui/Breadcrumb.tsx`)
- Walks `parent` chain in `routeMap` to build trail
- `<nav aria-label="Breadcrumb"><ol>` with `<li>` items, separator `>`
- Last item is plain text (current page), others are links
- Hidden on top-level pages
- `--space-1` vertical padding, `--text-caption` size
- Shared by marketing and app layouts

### PageIntro (`src/components/ui/PageIntro.tsx`)
- Replaces both `PageShell` (marketing) and `PageHeader` (app)
- Props: `title`, `subtitle?`, `eyebrow?`, `badge?`, `actions?` (ReactNode)
- Renders exactly one `<h1>`
- Marketing variant: eyebrow in small-caps above H1
- App variant: actions slot right of title
- `--space-8` bottom margin, `--space-2` between title and subtitle

### Section (`src/components/ui/Section.tsx`)
- Wrapper enforcing consistent section rhythm
- Props: `id?`, `heading?`, `level?: 2 | 3`, `children`
- `--space-8` top padding, `--space-3` gap heading-to-content
- `max-w-[70ch]` on prose children
- Provides anchor `id` for SectionTabs

### AppFooter (`src/components/ui/AppFooter.tsx`)
- Minimal legal bar for `/app` routes
- Single row: Privacy, Terms, Security, Status
- `--text-caption` size, `--color-steel` text, `--space-4` vertical padding
- Bottom of main content area (not sidebar), `mt-auto`

### BackNav (`src/components/ui/BackNav.tsx`)
- Props: `href`, `label?` (defaults to "Back")
- Renders `<- {label}` link, top-left, below breadcrumbs
- `--text-caption` size, focus-visible ring
- Replaces 3 existing ad-hoc back links

### SectionTabs (`src/components/ui/SectionTabs.tsx`)
- Reads `sectionAnchors` from route map for current page
- `<nav aria-label="Page sections">` with anchor links
- Sticky below header with reserved height (no layout shift)
- Active section via `IntersectionObserver`
- Arrow key navigation between tabs
- Only renders if route has `sectionAnchors`

### Layout placement

```
Marketing: SkipLink > SiteHeader > SectionTabs > Breadcrumb > PageIntro > Sections > SiteFooter
App:       SkipLink > Sidebar > [main: Breadcrumb > BackNav > PageIntro > Sections > AppFooter]
```

## Lint Rules

### lint-nav-overrides.mjs
- No page file may define its own primary nav links
- AST-scan `src/app/**/*.tsx` for nav re-declarations
- Allowlist: `SiteHeader.tsx`, `MobileDrawer.tsx`, `navigation.ts`

### lint-heading-hierarchy.mjs
- Exactly one `<h1>` or `<PageIntro>` per page
- No level skips (H1->H3 forbidden)
- Sequential heading levels only
- Allowlist: legal pages may use raw H1

### lint-spacing-tokens.mjs
- H2/H3 elements must not use custom margin/padding outside token system
- Flag `m[tby]-`, `p[tby]-` classes not mapping to `--space-*` tokens
- Warning initially, error after migration complete

### lint-route-map.mjs
- Every `(marketing)/**/page.tsx` and `(free-report)/**/page.tsx` must have `routeMap` entry
- App routes excluded (use PageIntro directly)

CI: all four run as part of `npm run lint`.

## A11y Checks (automated, `e2e/a11y-structure.spec.ts`)

| Check | Tool | Validation |
|-------|------|------------|
| Skip link | axe-core via Playwright | First focusable element, target `#main-content` exists |
| Breadcrumb semantics | axe-core | `nav[aria-label="Breadcrumb"]` contains `<ol>` |
| Heading hierarchy | axe-core `heading-order` | No level skips |
| Single H1 | axe-core `page-has-heading-one` | Exactly one H1 |
| Focus-visible rings | Playwright screenshot | Visible ring on tabbed elements |
| SectionTabs keyboard | Playwright | Arrow keys + Enter/Space |
| Footer links | Playwright assertion | `/app/dashboard` has Privacy/Terms/Security/Status |

Test pages: `/`, `/pricing`, `/pricing/compare`, `/app/dashboard`, `/app/sessions`

## Manual Verification Steps

1. Open 3 marketing pages — nav items identical
2. Navigate to subpage — breadcrumb trail correct
3. Tab on any page — skip link appears, Enter jumps to `#main-content`
4. Tab through nav/buttons/inputs — consistent focus ring
5. Scroll `/pricing` — section tabs stick, active highlights
6. Verify SectionTabs reserved height (no layout shift)
7. Open `/app/dashboard` — legal links at bottom of main content
8. Open `/app/account/profile` — BackNav visible, navigates correctly
9. Inspect any page — exactly one H1, sequential headings
10. Resize to 375px — hamburger drawer, same 5 items, focus trapped

## Rollback

- All work on `feat/nav-structure-standardization` branch
- Components are additive — revert by restoring old `PageShell`/`PageHeader` imports
- `git revert` the merge commit rolls back everything
- Remove 4 lint entries from `package.json`, delete script files
- Delete `route-map.ts` — only new components depend on it
- No database, API, or backend changes — pure frontend

## Deliverables

| Deliverable | Files |
|-------------|-------|
| Route map config | `src/data/route-map.ts` |
| Nav config (clean) | `src/data/navigation.ts` |
| 6 components | `src/components/ui/{Breadcrumb,PageIntro,Section,AppFooter,BackNav,SectionTabs}.tsx` |
| 4 lint scripts | `scripts/lint-{nav-overrides,heading-hierarchy,spacing-tokens,route-map}.mjs` |
| Layout updates | `(marketing)/layout.tsx`, `app/layout.tsx` |
| Page migrations | All marketing pages: PageShell -> PageIntro, Section wrappers, id anchors |
| E2E tests | `e2e/a11y-structure.spec.ts` |
| Focus styles | `src/styles/tokens.css` (focus-visible ring token) |
