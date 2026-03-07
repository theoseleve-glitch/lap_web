# SEO Production-Grade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Lap's marketing SEO production-grade with config-driven metadata, OG images, structured data, and CI enforcement.

**Architecture:** Extend the existing `route-map.ts` with SEO fields (primaryKeyword, metaDescription, ogTitle, ogDescription, jsonLdType, noIndex, canonical). A shared `generateSeoMetadata()` helper in `src/lib/seo.ts` reads route-map and returns Next.js Metadata objects. A `<JsonLd>` component renders structured data. An on-demand Cloudflare Worker generates OG images. Three CI lint scripts enforce consistency.

**Tech Stack:** Next.js 14 (App Router metadata API), TypeScript, Vitest, satori + resvg-wasm (OG worker), Cloudflare Workers

---

### Task 1: Extend RouteEntry with SEO fields

**Files:**
- Modify: `lap-website/src/data/route-map.ts:1-14`
- Modify: `lap-website/src/__tests__/route-map.test.ts`

**Step 1: Write the failing tests**

Add to `lap-website/src/__tests__/route-map.test.ts`:

```ts
describe('SEO fields', () => {
  const SEO_EXEMPT = ['/', '/sitemap'];

  it('every non-exempt entry has primaryKeyword', () => {
    for (const [key, entry] of Object.entries(routeMap)) {
      if (SEO_EXEMPT.includes(key)) continue;
      expect(entry.primaryKeyword, `${key} missing primaryKeyword`).toBeDefined();
      expect(entry.primaryKeyword!.length).toBeGreaterThan(0);
    }
  });

  it('every non-exempt entry has metaDescription between 80-160 chars', () => {
    for (const [key, entry] of Object.entries(routeMap)) {
      if (SEO_EXEMPT.includes(key)) continue;
      expect(entry.metaDescription, `${key} missing metaDescription`).toBeDefined();
      const len = entry.metaDescription!.length;
      expect(len, `${key} metaDescription too short (${len})`).toBeGreaterThanOrEqual(80);
      expect(len, `${key} metaDescription too long (${len})`).toBeLessThanOrEqual(160);
    }
  });

  it('no two entries share the same primaryKeyword', () => {
    const seen = new Map<string, string>();
    for (const [key, entry] of Object.entries(routeMap)) {
      if (!entry.primaryKeyword) continue;
      const kw = entry.primaryKeyword.toLowerCase();
      expect(seen.has(kw), `${key} and ${seen.get(kw)} share keyword "${kw}"`).toBe(false);
      seen.set(kw, key);
    }
  });

  it('no two entries share the same metaDescription', () => {
    const seen = new Map<string, string>();
    for (const [key, entry] of Object.entries(routeMap)) {
      if (!entry.metaDescription) continue;
      expect(seen.has(entry.metaDescription), `${key} and ${seen.get(entry.metaDescription)} share description`).toBe(false);
      seen.set(entry.metaDescription, key);
    }
  });
});
```

**Step 2: Run tests to verify they fail**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/route-map.test.ts`
Expected: FAIL with "primaryKeyword" undefined

**Step 3: Add SEO fields to RouteEntry interface**

In `lap-website/src/data/route-map.ts`, update the `RouteEntry` interface (lines 6-14):

```ts
export interface RouteEntry {
  path: string;
  title: string;
  subtitle?: string;
  badge?: string;
  eyebrow?: string;
  parent: string | null;
  sectionAnchors?: SectionAnchor[];
  primaryKeyword?: string;
  metaDescription?: string;
  ogTitle?: string;
  ogDescription?: string;
  jsonLdType?: 'WebPage' | 'FAQPage' | 'Article';
  noIndex?: boolean;
  canonical?: string;
}
```

**Step 4: Populate SEO fields on all 18 non-exempt route-map entries**

Add `primaryKeyword` and `metaDescription` to every entry except `/` and `/sitemap`. Each metaDescription must be 80-160 chars and unique. Set `jsonLdType: 'FAQPage'` on `/pricing` and `/help`.

Example for `/pricing`:

```ts
'/pricing': {
  path: '/pricing',
  title: 'Pricing',
  eyebrow: 'Plans',
  parent: null,
  primaryKeyword: 'motorsport telemetry pricing',
  metaDescription: 'Compare LAP plans for kart and car drivers. Free demo, Racer, and World-Class tiers with annual savings. Start analyzing telemetry today.',
  jsonLdType: 'FAQPage',
  sectionAnchors: [
    { id: 'plans', label: 'Plans' },
    { id: 'features', label: 'Features' },
    { id: 'lifecycle', label: 'Lifecycle' },
  ],
},
```

Write unique, accurate descriptions for all 18 entries.

**Step 5: Run tests to verify they pass**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/route-map.test.ts`
Expected: PASS

**Step 6: Commit**

```bash
git add lap-website/src/data/route-map.ts lap-website/src/__tests__/route-map.test.ts
git commit -m "feat(seo): extend route-map with SEO fields for all marketing pages"
```

---

### Task 2: Create generateSeoMetadata helper

**Files:**
- Create: `lap-website/src/lib/seo.ts`
- Create: `lap-website/src/__tests__/seo.test.ts`

**Step 1: Write the failing tests**

Create `lap-website/src/__tests__/seo.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { generateSeoMetadata } from '@/lib/seo';

describe('generateSeoMetadata', () => {
  it('returns metadata for a known route', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.title).toBe('Pricing');
    expect(meta.description).toBeDefined();
    expect(meta.description!.length).toBeGreaterThanOrEqual(80);
  });

  it('includes openGraph fields', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.openGraph).toBeDefined();
    expect(meta.openGraph!.title).toBeDefined();
    expect(meta.openGraph!.description).toBeDefined();
    expect(meta.openGraph!.url).toContain('/pricing');
    expect(meta.openGraph!.images).toBeDefined();
  });

  it('includes twitter card', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.twitter).toBeDefined();
    expect(meta.twitter!.card).toBe('summary_large_image');
  });

  it('includes canonical URL', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.alternates).toBeDefined();
    expect(meta.alternates!.canonical).toBe('https://www.lap-coach.racing/pricing');
  });

  it('returns empty metadata for unknown routes', () => {
    const meta = generateSeoMetadata('/nonexistent');
    expect(meta.title).toBeUndefined();
    expect(meta.openGraph).toBeUndefined();
  });

  it('applies overrides for dynamic routes', () => {
    const meta = generateSeoMetadata('/insights', {
      title: 'Custom Article Title',
      metaDescription: 'A custom description that is long enough to pass the minimum character length requirement for meta descriptions.',
    });
    expect(meta.title).toBe('Custom Article Title');
    expect(meta.description).toContain('custom description');
  });

  it('sets noindex when overrides specify noIndex', () => {
    const meta = generateSeoMetadata('/pricing', { noIndex: true });
    expect(meta.robots).toEqual({ index: false, follow: false });
  });
});
```

**Step 2: Run tests to verify they fail**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/seo.test.ts`
Expected: FAIL — module not found

**Step 3: Implement generateSeoMetadata**

Create `lap-website/src/lib/seo.ts`:

```ts
import type { Metadata } from 'next';
import { routeMap } from '@/data/route-map';
import { getSiteUrl } from '@/lib/site-url';

const OG_WORKER_ORIGIN = 'https://og.lap-coach.racing';

interface SeoOverrides {
  title?: string;
  metaDescription?: string;
  ogTitle?: string;
  ogDescription?: string;
  noIndex?: boolean;
  canonical?: string;
}

function buildOgImageUrl(title: string, eyebrow?: string): string {
  const params = new URLSearchParams({ title });
  if (eyebrow) params.set('eyebrow', eyebrow);
  return `${OG_WORKER_ORIGIN}/og?${params.toString()}`;
}

export function generateSeoMetadata(
  pathname: string,
  overrides?: SeoOverrides,
): Metadata {
  const entry = routeMap[pathname];
  if (!entry && !overrides) return {};

  const siteUrl = getSiteUrl();
  const title = overrides?.title ?? entry?.title;
  const description = overrides?.metaDescription ?? entry?.metaDescription;
  const ogTitle = overrides?.ogTitle ?? entry?.ogTitle ?? title;
  const ogDescription = overrides?.ogDescription ?? entry?.ogDescription ?? description;
  const noIndex = overrides?.noIndex ?? entry?.noIndex ?? false;
  const canonical = overrides?.canonical ?? entry?.canonical ?? `${siteUrl}${pathname}`;
  const eyebrow = entry?.eyebrow;

  const meta: Metadata = {};

  if (title) meta.title = title;
  if (description) meta.description = description;

  if (ogTitle && ogDescription) {
    meta.openGraph = {
      title: ogTitle,
      description: ogDescription,
      url: `${siteUrl}${pathname}`,
      images: [buildOgImageUrl(ogTitle, eyebrow)],
    };
    meta.twitter = {
      card: 'summary_large_image',
      title: ogTitle,
      description: ogDescription,
    };
  }

  meta.alternates = { canonical };

  if (noIndex) {
    meta.robots = { index: false, follow: false };
  }

  return meta;
}
```

**Step 4: Run tests to verify they pass**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/seo.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add lap-website/src/lib/seo.ts lap-website/src/__tests__/seo.test.ts
git commit -m "feat(seo): add generateSeoMetadata helper with OG, twitter, canonical"
```

---

### Task 3: Create JsonLd component

**Files:**
- Create: `lap-website/src/components/seo/JsonLd.tsx`
- Create: `lap-website/src/__tests__/json-ld.test.tsx`

**Step 1: Write the failing tests**

Create `lap-website/src/__tests__/json-ld.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { JsonLd } from '@/components/seo/JsonLd';

describe('JsonLd', () => {
  it('renders WebPage schema for a standard page', () => {
    const { container } = render(<JsonLd pathname="/product" />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    const data = JSON.parse(script!.textContent!);
    expect(data['@graph'].some((s: any) => s['@type'] === 'WebPage')).toBe(true);
  });

  it('renders BreadcrumbList for subpages', () => {
    const { container } = render(<JsonLd pathname="/pricing/compare" />);
    const data = JSON.parse(
      container.querySelector('script[type="application/ld+json"]')!.textContent!,
    );
    expect(data['@graph'].some((s: any) => s['@type'] === 'BreadcrumbList')).toBe(true);
  });

  it('renders FAQPage schema when faqItems provided', () => {
    const { container } = render(
      <JsonLd pathname="/pricing" faqItems={[{ question: 'Q?', answer: 'A.' }]} />,
    );
    const data = JSON.parse(
      container.querySelector('script[type="application/ld+json"]')!.textContent!,
    );
    expect(data['@graph'].some((s: any) => s['@type'] === 'FAQPage')).toBe(true);
  });

  it('renders Article schema with article data', () => {
    const { container } = render(
      <JsonLd
        pathname="/insights"
        article={{ title: 'Test Article', datePublished: '2026-01-01', summary: 'Summary text' }}
      />,
    );
    const data = JSON.parse(
      container.querySelector('script[type="application/ld+json"]')!.textContent!,
    );
    expect(data['@graph'].some((s: any) => s['@type'] === 'Article')).toBe(true);
  });

  it('returns null for unknown paths', () => {
    const { container } = render(<JsonLd pathname="/nonexistent" />);
    expect(container.querySelector('script[type="application/ld+json"]')).toBeNull();
  });
});
```

**Step 2: Run tests to verify they fail**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/json-ld.test.tsx`
Expected: FAIL — module not found

**Step 3: Implement JsonLd component**

Create `lap-website/src/components/seo/JsonLd.tsx`:

```tsx
import { routeMap, buildBreadcrumbs } from '@/data/route-map';
import { getSiteUrl } from '@/lib/site-url';

interface FaqItem {
  question: string;
  answer: string;
}

interface ArticleData {
  title: string;
  datePublished: string;
  summary: string;
}

interface JsonLdProps {
  pathname: string;
  faqItems?: FaqItem[];
  article?: ArticleData;
}

function buildBreadcrumbSchema(pathname: string, siteUrl: string) {
  const crumbs = buildBreadcrumbs(pathname);
  const entry = routeMap[pathname];
  if (!entry || crumbs.length === 0) return null;

  return {
    '@type': 'BreadcrumbList',
    itemListElement: [
      ...crumbs.map((c, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: c.label,
        item: `${siteUrl}${c.href}`,
      })),
      {
        '@type': 'ListItem',
        position: crumbs.length + 1,
        name: entry.title,
        item: `${siteUrl}${pathname}`,
      },
    ],
  };
}

export function JsonLd({ pathname, faqItems, article }: JsonLdProps) {
  const entry = routeMap[pathname];
  if (!entry && !article) return null;

  const siteUrl = getSiteUrl();
  const jsonLdType = entry?.jsonLdType ?? 'WebPage';
  const graph: Record<string, unknown>[] = [];

  if (article) {
    graph.push({
      '@type': 'Article',
      headline: article.title,
      datePublished: article.datePublished,
      description: article.summary,
      publisher: { '@type': 'Organization', name: 'Lap Coach' },
    });
  } else if (jsonLdType === 'FAQPage' && faqItems?.length) {
    graph.push({
      '@type': 'FAQPage',
      mainEntity: faqItems.map((item) => ({
        '@type': 'Question',
        name: item.question,
        acceptedAnswer: { '@type': 'Answer', text: item.answer },
      })),
    });
  } else {
    graph.push({
      '@type': 'WebPage',
      name: entry?.title,
      url: `${siteUrl}${pathname}`,
    });
  }

  const breadcrumbSchema = buildBreadcrumbSchema(pathname, siteUrl);
  if (breadcrumbSchema) graph.push(breadcrumbSchema);

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }) }}
    />
  );
}
```

**Step 4: Run tests to verify they pass**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/json-ld.test.tsx`
Expected: PASS

**Step 5: Commit**

```bash
git add lap-website/src/components/seo/JsonLd.tsx lap-website/src/__tests__/json-ld.test.tsx
git commit -m "feat(seo): add JsonLd component with WebPage, FAQPage, Article, BreadcrumbList"
```

---

### Task 4: Add noindex to /app layout

**Files:**
- Rename: `lap-website/src/app/app/layout.tsx` to `lap-website/src/app/app/AppShell.tsx`
- Create: `lap-website/src/app/app/layout.tsx` (new server component)

The current `/app` layout is `'use client'` — client components cannot export `metadata`. Solution: extract the client layout to `AppShell.tsx`, create a new server layout that exports metadata and renders `<AppShell>`.

**Step 1: Rename current layout to AppShell**

Copy `lap-website/src/app/app/layout.tsx` to `lap-website/src/app/app/AppShell.tsx`.

In `AppShell.tsx`:
- Keep `'use client'` directive
- Change `export default function AppLayout` to `export function AppShell`

**Step 2: Create new server layout**

Create `lap-website/src/app/app/layout.tsx`:

```tsx
import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { AppShell } from './AppShell';

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
```

**Step 3: Verify tests still pass**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run`
Expected: PASS

**Step 4: Commit**

```bash
git add lap-website/src/app/app/layout.tsx lap-website/src/app/app/AppShell.tsx
git commit -m "feat(seo): add robots noindex to /app layout via server component wrapper"
```

---

### Task 5: Enhance sitemap with route-map priority

**Files:**
- Modify: `lap-website/src/app/sitemap.ts`

**Step 1: Update sitemap.ts to use route-map for priority and noIndex filtering**

Replace `lap-website/src/app/sitemap.ts` with:

```ts
import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/site-url';
import { insightEntries } from '@/data/insights-cms';
import { routeMap } from '@/data/route-map';
import { collectMarketingSitemapRoutes } from '@/lib/sitemap-routes.mjs';

const extraRoutes = ['/free-report/analyze'];

function getRoutePriority(route: string): number {
  if (route === '') return 1;
  const segments = route.split('/').filter(Boolean).length;
  if (segments === 1) return 0.8;
  return 0.6;
}

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const siteUrl = getSiteUrl();

  const marketingRoutes = collectMarketingSitemapRoutes();
  const discovered = marketingRoutes.map((r: string) => (r === '/' ? '' : r));
  const allRoutes = ['', ...discovered.filter((r: string) => r !== ''), ...extraRoutes]
    .filter((route) => {
      const entry = routeMap[route || '/'];
      return !entry?.noIndex;
    });

  const pages: MetadataRoute.Sitemap = allRoutes.map((route) => ({
    url: `${siteUrl}${route}`,
    lastModified: now,
    changeFrequency: route === '' ? ('weekly' as const) : ('monthly' as const),
    priority: getRoutePriority(route),
  }));

  for (const entry of insightEntries) {
    pages.push({
      url: `${siteUrl}/insights/${entry.slug}`,
      lastModified: now,
      changeFrequency: 'monthly',
      priority: 0.6,
    });
  }

  return pages;
}
```

**Step 2: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/route-map.test.ts`
Expected: PASS

**Step 3: Commit**

```bash
git add lap-website/src/app/sitemap.ts
git commit -m "feat(seo): enhance sitemap with route-map priority and noIndex filtering"
```

---

### Task 6: Deprecate site-origin.ts

**Files:**
- Delete: `lap-website/src/lib/site-origin.ts`
- Modify: any files importing from `site-origin`

**Step 1: Find all imports of site-origin**

Search for `site-origin` in `lap-website/src/`. Replace each import of `getValidatedSiteOrigin` with `getSiteUrl` from `@/lib/site-url`.

**Step 2: Delete site-origin.ts**

Remove `lap-website/src/lib/site-origin.ts`.

**Step 3: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run`
Expected: PASS

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor(seo): remove site-origin.ts, consolidate on site-url.ts"
```

---

### Task 7: Migrate marketing pages to generateSeoMetadata

**Files:**
- Modify: All 21 marketing page files in `lap-website/src/app/(marketing)/`

Pages with existing metadata (11): customers, dpa, waitlist, security, help, terms, changelog, sitemap, thank-you/[form], subprocessors, privacy

Pages missing metadata (10): home, status, contact, pricing, insights/[slug], insights, book, demo, product, billing

**Step 1: Replace inline metadata with generateSeoMetadata on pages that have it**

For each of the 11 pages, replace the inline `export const metadata = { ... }` with:

```ts
import { generateSeoMetadata } from '@/lib/seo';
export const metadata = generateSeoMetadata('/customers');  // use actual path
```

**Step 2: Add generateSeoMetadata to pages missing it**

For each of the 10 pages, add the import and export at the top of the file.

**Step 3: Handle insights/[slug] dynamically**

For `insights/[slug]/page.tsx`, use `generateMetadata`:

```ts
import { generateSeoMetadata } from '@/lib/seo';
import { insightEntries } from '@/data/insights-cms';

export function generateMetadata({ params }: { params: { slug: string } }) {
  const entry = insightEntries.find((e) => e.slug === params.slug);
  if (!entry) return generateSeoMetadata('/insights');
  return generateSeoMetadata('/insights', {
    title: entry.title,
    metaDescription: entry.summary.length >= 80
      ? entry.summary
      : `${entry.summary} Learn more about ${entry.tags.join(', ')} in motorsport telemetry analysis with LAP.`,
  });
}
```

**Step 4: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run`
Expected: PASS

**Step 5: Commit**

```bash
git add lap-website/src/app/\(marketing\)/
git commit -m "feat(seo): migrate all marketing pages to generateSeoMetadata"
```

---

### Task 8: Add JsonLd to marketing pages

**Files:**
- Modify: Marketing page files

**Step 1: Add JsonLd import to each page**

For each marketing page, add `<JsonLd pathname="/path" />` at the top of the returned JSX. For pages with `jsonLdType: 'FAQPage'` (pricing, help), pass `faqItems` with actual FAQ content from the page.

For insights/[slug], pass `article` data:

```tsx
<JsonLd
  pathname="/insights"
  article={{ title: entry.title, datePublished: '2026-01-01', summary: entry.summary }}
/>
```

**Step 2: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run`
Expected: PASS

**Step 3: Commit**

```bash
git add lap-website/src/app/\(marketing\)/
git commit -m "feat(seo): add JsonLd structured data to marketing pages"
```

---

### Task 9: Create lint-seo-fields.mjs

**Files:**
- Create: `lap-website/scripts/lint-seo-fields.mjs`
- Modify: `lap-website/package.json`

**Step 1: Write the lint script**

Create `lap-website/scripts/lint-seo-fields.mjs`:

```js
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const routeMapSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/data/route-map.ts'),
  'utf-8',
);

const SEO_EXEMPT = new Set(['/', '/sitemap']);
const violations = [];
const keywords = new Map();
const descriptions = new Map();

// Extract entries and their bodies
const ENTRY_RE = /'([^']+)':\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}/g;
let match;
while ((match = ENTRY_RE.exec(routeMapSource)) !== null) {
  const routePath = match[1];
  const body = match[2];

  if (SEO_EXEMPT.has(routePath)) continue;

  const kwMatch = body.match(/primaryKeyword:\s*'([^']*)'/);
  if (!kwMatch) {
    violations.push({ path: routePath, rule: 'missing-keyword', detail: 'No primaryKeyword' });
  } else {
    const kw = kwMatch[1].toLowerCase();
    if (keywords.has(kw)) {
      violations.push({
        path: routePath,
        rule: 'duplicate-keyword',
        detail: `Shares keyword "${kw}" with ${keywords.get(kw)}`,
      });
    } else {
      keywords.set(kw, routePath);
    }
  }

  const descMatch = body.match(/metaDescription:\s*'([^']*)'/);
  if (!descMatch) {
    violations.push({ path: routePath, rule: 'missing-description', detail: 'No metaDescription' });
  } else {
    const desc = descMatch[1];
    if (desc.length < 80) {
      violations.push({
        path: routePath,
        rule: 'short-description',
        detail: `metaDescription is ${desc.length} chars (min 80)`,
      });
    }
    if (desc.length > 160) {
      violations.push({
        path: routePath,
        rule: 'long-description',
        detail: `metaDescription is ${desc.length} chars (max 160)`,
      });
    }
    if (descriptions.has(desc)) {
      violations.push({
        path: routePath,
        rule: 'duplicate-description',
        detail: `Shares description with ${descriptions.get(desc)}`,
      });
    } else {
      descriptions.set(desc, routePath);
    }
  }
}

if (violations.length === 0) {
  console.log('lint-seo-fields: All SEO fields valid. All clear.');
  process.exit(0);
}

console.error(`lint-seo-fields: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.error(`  ${v.path} -- ${v.rule} -- ${v.detail}`);
}
process.exit(1);
```

**Step 2: Add to package.json scripts**

```json
"lint:seo": "node scripts/lint-seo-fields.mjs"
```

**Step 3: Run the linter**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run lint:seo`
Expected: All clear

**Step 4: Commit**

```bash
git add lap-website/scripts/lint-seo-fields.mjs lap-website/package.json
git commit -m "feat(seo): add lint-seo-fields CI linter"
```

---

### Task 10: Create lint-canonical.mjs

**Files:**
- Create: `lap-website/scripts/lint-canonical.mjs`
- Modify: `lap-website/package.json`

**Step 1: Write the lint script**

Create `lap-website/scripts/lint-canonical.mjs`:

```js
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIR = path.resolve(process.cwd(), 'src');
const EXEMPT_FILES = new Set([
  'src/lib/site-url.ts',
]);

const DOMAIN_RE = /https?:\/\/(?:www\.)?lap-coach\.racing|https?:\/\/lap\.racing/g;

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.next') continue;
      results.push(...walk(full));
    } else if (/\.(ts|tsx|js|mjs)$/.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

const violations = [];

for (const filePath of walk(SCAN_DIR)) {
  const relative = path.relative(process.cwd(), filePath).replace(/\\/g, '/');
  if (EXEMPT_FILES.has(relative)) continue;

  const source = fs.readFileSync(filePath, 'utf-8');
  const lines = source.split('\n');

  for (let i = 0; i < lines.length; i++) {
    const matches = lines[i].match(DOMAIN_RE);
    if (matches) {
      for (const m of matches) {
        violations.push({ file: relative, line: i + 1, match: m });
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-canonical: No hardcoded domain references outside site-url.ts. All clear.');
  process.exit(0);
}

console.error(`lint-canonical: ${violations.length} hardcoded domain reference(s):\n`);
for (const v of violations) {
  console.error(`  ${v.file}:${v.line} -- ${v.match}`);
}
console.error('\n  Use getSiteUrl() from @/lib/site-url instead.');
process.exit(1);
```

**Step 2: Add to package.json scripts**

```json
"lint:canonical": "node scripts/lint-canonical.mjs"
```

**Step 3: Run the linter and fix violations**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run lint:canonical`

If there are violations in files like `brand.ts`, `seo.ts` (OG worker URL), or test files, add them to `EXEMPT_FILES`. The OG worker URL (`og.lap-coach.racing`) is a different subdomain so it may not match, but verify.

**Step 4: Commit**

```bash
git add lap-website/scripts/lint-canonical.mjs lap-website/package.json
git commit -m "feat(seo): add lint-canonical CI linter"
```

---

### Task 11: Create lint-noindex.mjs

**Files:**
- Create: `lap-website/scripts/lint-noindex.mjs`
- Modify: `lap-website/package.json`

**Step 1: Write the lint script**

Create `lap-website/scripts/lint-noindex.mjs`:

```js
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const violations = [];

// Check 1: /app layout has noindex
const appLayoutPath = path.resolve(process.cwd(), 'src/app/app/layout.tsx');
if (fs.existsSync(appLayoutPath)) {
  const source = fs.readFileSync(appLayoutPath, 'utf-8');
  if (!source.includes('index: false')) {
    violations.push({
      file: 'src/app/app/layout.tsx',
      rule: 'missing-app-noindex',
      detail: 'App layout must have robots: { index: false }',
    });
  }
}

// Check 2: No marketing pages have inline noindex
const marketingDir = path.resolve(process.cwd(), 'src/app/(marketing)');
function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (entry.name === 'page.tsx') results.push(full);
  }
  return results;
}

for (const filePath of walk(marketingDir)) {
  const source = fs.readFileSync(filePath, 'utf-8');
  const relative = path.relative(process.cwd(), filePath).replace(/\\/g, '/');
  if (source.includes('index: false') && !source.includes('generateSeoMetadata')) {
    violations.push({
      file: relative,
      rule: 'marketing-noindex',
      detail: 'Marketing page has inline noindex',
    });
  }
}

if (violations.length === 0) {
  console.log('lint-noindex: App noindex present, no accidental marketing noindex. All clear.');
  process.exit(0);
}

console.error(`lint-noindex: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.error(`  ${v.file} -- ${v.rule} -- ${v.detail}`);
}
process.exit(1);
```

**Step 2: Add to package.json scripts**

```json
"lint:noindex": "node scripts/lint-noindex.mjs"
```

**Step 3: Run the linter**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run lint:noindex`
Expected: All clear

**Step 4: Commit**

```bash
git add lap-website/scripts/lint-noindex.mjs lap-website/package.json
git commit -m "feat(seo): add lint-noindex CI linter"
```

---

### Task 12: Wire SEO linters into CI

**Files:**
- Modify: `lap-website/package.json:43`

**Step 1: Add lint:seo, lint:canonical, lint:noindex to the CI script**

In the `ci` script in `package.json`, add before `ci:assert-site-url`:

```
&& npm run lint:seo && npm run lint:canonical && npm run lint:noindex
```

**Step 2: Run all three to verify**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run lint:seo && npm run lint:canonical && npm run lint:noindex`
Expected: All clear

**Step 3: Commit**

```bash
git add lap-website/package.json
git commit -m "ci(seo): wire SEO linters into CI pipeline"
```

---

### Task 13: Create quarterly SEO audit script

**Files:**
- Create: `lap-website/scripts/seo-audit.mjs`
- Modify: `lap-website/package.json`

**Step 1: Write the audit script**

Create `lap-website/scripts/seo-audit.mjs`:

```js
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

console.log('=== SEO Quarterly Audit ===\n');

const routeMapSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/data/route-map.ts'),
  'utf-8',
);

// 1. Count entries with SEO fields
const ENTRY_RE = /'([^']+)':\s*\{/g;
const entries = [];
let match;
while ((match = ENTRY_RE.exec(routeMapSource)) !== null) {
  entries.push(match[1]);
}

const withKeyword = entries.filter((p) =>
  new RegExp(`'${p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}'[^}]*primaryKeyword`).test(routeMapSource),
);

console.log(`1. Route entries: ${entries.length} total, ${withKeyword.length} with primaryKeyword`);

// 2. Sitemap coverage
const { collectMarketingSitemapRoutes } = await import(
  path.resolve(process.cwd(), 'src/lib/sitemap-routes.mjs')
);
const sitemapRoutes = collectMarketingSitemapRoutes();
const routeMapPaths = new Set(entries);
const notInRouteMap = sitemapRoutes.filter((r) => !routeMapPaths.has(r) && r !== '/');

console.log(`\n2. Sitemap: ${sitemapRoutes.length} routes`);
if (notInRouteMap.length > 0) {
  console.warn(`   WARN: Not in route-map: ${notInRouteMap.join(', ')}`);
} else {
  console.log('   OK: All covered');
}

// 3. Description uniqueness
const DESC_RE = /metaDescription:\s*'([^']*)'/g;
const descriptions = [];
let descMatch;
while ((descMatch = DESC_RE.exec(routeMapSource)) !== null) {
  descriptions.push(descMatch[1]);
}

let dupeCount = 0;
for (let i = 0; i < descriptions.length; i++) {
  for (let j = i + 1; j < descriptions.length; j++) {
    const words1 = new Set(descriptions[i].toLowerCase().split(/\s+/));
    const words2 = new Set(descriptions[j].toLowerCase().split(/\s+/));
    const overlap = [...words1].filter((w) => words2.has(w)).length;
    const similarity = overlap / Math.max(words1.size, words2.size);
    if (similarity > 0.7) dupeCount++;
  }
}

console.log(`\n3. Descriptions: ${descriptions.length} total, ${dupeCount} near-duplicates`);

console.log('\n=== Audit complete ===');
```

**Step 2: Add to package.json scripts**

```json
"audit:seo": "node scripts/seo-audit.mjs"
```

**Step 3: Run it**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run audit:seo`
Expected: Report with no critical issues

**Step 4: Commit**

```bash
git add lap-website/scripts/seo-audit.mjs lap-website/package.json
git commit -m "feat(seo): add quarterly SEO audit script"
```

---

### Task 14: Scaffold OG image worker

**Files:**
- Create: `lap-og-worker/package.json`
- Create: `lap-og-worker/src/index.tsx`
- Create: `lap-og-worker/wrangler.toml`

**Step 1: Create worker directory and files**

Create `lap-og-worker/package.json`:

```json
{
  "name": "lap-og-worker",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy"
  },
  "devDependencies": {
    "wrangler": "^4.69.0"
  }
}
```

Create `lap-og-worker/wrangler.toml`:

```toml
name = "lap-og-worker"
main = "src/index.tsx"
compatibility_date = "2024-01-01"
```

Create `lap-og-worker/src/index.tsx`:

```tsx
export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname !== '/og') {
      return new Response('Not found', { status: 404 });
    }

    const title = url.searchParams.get('title') || 'LAP';
    const eyebrow = url.searchParams.get('eyebrow') || '';

    // Placeholder SVG - replace with satori + resvg-wasm for PNG output
    const svg = `<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg">
      <rect width="1200" height="630" fill="#000"/>
      <text x="64" y="200" font-size="24" fill="#888">${escapeXml(eyebrow)}</text>
      <text x="64" y="300" font-size="64" fill="#F0EDE5" font-family="sans-serif">${escapeXml(title)}</text>
      <text x="64" y="580" font-size="20" fill="#C9A84C">LAP — Find Time.</text>
    </svg>`;

    return new Response(svg, {
      headers: {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 'public, max-age=86400, s-maxage=604800',
      },
    });
  },
};

function escapeXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
```

**Step 2: Commit**

```bash
git add lap-og-worker/
git commit -m "feat(seo): scaffold OG image Cloudflare Worker with SVG placeholder"
```

---

### Task 15: Add E2E SEO tests

**Files:**
- Create: `lap-website/e2e/seo.spec.ts`

**Step 1: Write E2E tests**

Create `lap-website/e2e/seo.spec.ts`:

```ts
import { test, expect } from '@playwright/test';

test.describe('SEO meta tags', () => {
  test('pricing page has meta description', async ({ page }) => {
    await page.goto('/pricing');
    const desc = page.locator('meta[name="description"]');
    await expect(desc).toBeAttached();
    const content = await desc.getAttribute('content');
    expect(content!.length).toBeGreaterThanOrEqual(80);
  });

  test('pricing page has og:title and og:description', async ({ page }) => {
    await page.goto('/pricing');
    await expect(page.locator('meta[property="og:title"]')).toBeAttached();
    await expect(page.locator('meta[property="og:description"]')).toBeAttached();
  });

  test('pricing page has og:image', async ({ page }) => {
    await page.goto('/pricing');
    const ogImage = page.locator('meta[property="og:image"]');
    await expect(ogImage).toBeAttached();
    const url = await ogImage.getAttribute('content');
    expect(url).toContain('og');
  });

  test('pricing page has canonical URL', async ({ page }) => {
    await page.goto('/pricing');
    const canonical = page.locator('link[rel="canonical"]');
    await expect(canonical).toBeAttached();
    const href = await canonical.getAttribute('href');
    expect(href).toContain('/pricing');
  });

  test('pricing page has JSON-LD structured data', async ({ page }) => {
    await page.goto('/pricing');
    const scripts = page.locator('script[type="application/ld+json"]');
    expect(await scripts.count()).toBeGreaterThanOrEqual(1);
  });

  test('app dashboard has noindex', async ({ page }) => {
    await page.goto('/app/dashboard');
    const robots = page.locator('meta[name="robots"]');
    await expect(robots).toBeAttached();
    const content = await robots.getAttribute('content');
    expect(content).toContain('noindex');
  });

  test('product page has meta description', async ({ page }) => {
    await page.goto('/product');
    const desc = page.locator('meta[name="description"]');
    await expect(desc).toBeAttached();
  });
});
```

**Step 2: Commit**

```bash
git add lap-website/e2e/seo.spec.ts
git commit -m "test(seo): add E2E tests for meta tags, OG, canonical, JSON-LD, noindex"
```

---

### Task 16: Final verification

**Step 1: Run all unit tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run`
Expected: All tests pass

**Step 2: Run all SEO linters**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run lint:seo && npm run lint:canonical && npm run lint:noindex`
Expected: All clear

**Step 3: Run existing linters**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run lint:nav && npm run lint:headings && npm run lint:spacing && npm run lint:routes`
Expected: All pass

**Step 4: Run SEO audit**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run audit:seo`
Expected: Report with no critical issues
