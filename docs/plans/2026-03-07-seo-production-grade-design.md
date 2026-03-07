# SEO Production-Grade Implementation — Design Document

> **Date**: 2026-03-07
> **Branch**: `feat/seo-production-grade`
> **Goal**: Make Lap's marketing SEO production-grade with config-driven metadata, OG images, structured data, and CI enforcement.

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Registry architecture | Extend `route-map.ts` | Single source of truth, one file per page, no drift |
| OG image generation | On-demand Cloudflare Worker | Dynamic, no rebuild needed, cacheable |
| JSON-LD schemas | Minimal + BreadcrumbList | Highest ROI: WebPage, FAQPage, Article, BreadcrumbList |
| Canonical domain | `www.lap-coach.racing` | Already used in metadataBase/sitemap; 301 from `lap.racing` |

---

## 1. Routes Registry SEO Fields

Extend `RouteEntry` in `src/data/route-map.ts`:

```ts
interface RouteEntry {
  // existing
  path: string; title: string; subtitle?: string; eyebrow?: string;
  badge?: string; parent?: string; sectionAnchors?: SectionAnchor[];

  // SEO fields
  primaryKeyword?: string;
  metaDescription?: string;       // 80-160 chars, unique per page
  ogTitle?: string;               // defaults to title if omitted
  ogDescription?: string;         // defaults to metaDescription if omitted
  jsonLdType?: 'WebPage' | 'FAQPage' | 'Article';  // defaults to 'WebPage'
  noIndex?: boolean;              // defaults to false
  canonical?: string;             // override canonical URL (rare)
}
```

CI linter `lint-seo-fields.mjs` enforces: every entry has `primaryKeyword` + `metaDescription`, description is 80-160 chars, no two pages share the same `primaryKeyword` or `metaDescription`.

## 2. SEO Metadata Helper

`src/lib/seo.ts` exports `generateSeoMetadata(pathname, overrides?)`:

- Looks up route-map entry by pathname
- Returns Next.js `Metadata` object: title, description, openGraph (title, description, url, images), twitter card, alternates.canonical, robots
- OG image URL points to the OG worker: `https://og.lap-coach.racing/og?title=...&eyebrow=...`
- Canonical defaults to `https://www.lap-coach.racing${pathname}`
- `noIndex: true` → `robots: { index: false }`

Usage in marketing pages:
```ts
import { generateSeoMetadata } from '@/lib/seo';
export const metadata = generateSeoMetadata('/pricing');
```

Dynamic routes (e.g., `/insights/[slug]`) use overrides:
```ts
export function generateMetadata({ params }) {
  return generateSeoMetadata('/insights', {
    title: article.title,
    metaDescription: article.summary,
  });
}
```

`/app` layout gets blanket `robots: { index: false, follow: false }`.

## 3. OG Image Worker

Standalone Cloudflare Worker at `og.lap-coach.racing`.

**Endpoint**: `GET /og?title=...&eyebrow=...&template=default`

**Templates**:
- `default` — Brand gradient, title + eyebrow, Lap logo
- `article` — Title + author + date (for `/insights/*`)
- `pricing` — Plan name highlight

**Tech**: `satori` (JSX → SVG) + `resvg-wasm` (SVG → PNG).

**Caching**: `Cache-Control: public, max-age=86400, s-maxage=604800`.

**Deployment**: Separate project `lap-og-worker/`, independent deploy cycle.

## 4. JSON-LD Structured Data

`src/lib/seo.ts` also exports `generateJsonLd(pathname, data?)`.

| jsonLdType | Schemas generated | Data source |
|---|---|---|
| `WebPage` (default) | `WebPage` + `BreadcrumbList` | route-map title + breadcrumbs |
| `FAQPage` | `FAQPage` + `BreadcrumbList` | FAQ data from page + breadcrumbs |
| `Article` | `Article` + `BreadcrumbList` | insights-cms entry + breadcrumbs |

`BreadcrumbList` auto-generated via `buildBreadcrumbs(pathname)` from route-map.

Root-level `SoftwareApplication` + `Organization` schemas stay in `layout.tsx` but prices pulled from `stripe-billing.ts`.

Rendered via `<JsonLd pathname="/pricing" />` component in page body.

## 5. Sitemap, Canonical & Robots

**Sitemap** (`src/app/sitemap.ts`):
- Read `lastModified` from git file mtime
- Set `changeFrequency`/`priority` by route depth (root=1.0, depth-1=0.8, depth-2=0.6)
- Exclude routes with `noIndex: true`

**Canonical policy**:
- Primary: `https://www.lap-coach.racing`
- Remove/deprecate `site-origin.ts` — single `site-url.ts` as source of truth
- Trailing-slash-free paths
- Cloudflare redirect: `lap.racing/*` → 301 `www.lap-coach.racing/$1`

**Robots** (`src/app/robots.ts`):
- Existing: blocks `/api/`, `/app/`, `/admin/`
- Add: `sitemap: https://www.lap-coach.racing/sitemap.xml`

**/app noindex**: `robots: { index: false, follow: false }` in `src/app/app/layout.tsx` metadata.

## 6. CI Lint Scripts

| Script | Checks | Gate |
|---|---|---|
| `lint-seo-fields.mjs` | Every route-map entry has primaryKeyword + metaDescription; 80-160 chars; no duplicates | Hard fail |
| `lint-canonical.mjs` | No hardcoded domain strings outside `site-url.ts` | Hard fail |
| `lint-noindex.mjs` | `/app` layout has noindex; no marketing pages have accidental noindex | Hard fail |

## 7. Quarterly Audit

`scripts/seo-audit.mjs` — manual or CI script that:
- Checks all route-map entries have SEO fields filled
- Verifies sitemap includes all non-noindex routes
- Flags identical/near-identical meta descriptions
- Reports missing OG images (hits the worker URL, checks for 200)

Run: `npm run audit:seo`

## 8. Rollback

- SEO fields in route-map are additive — removing them leaves nav/breadcrumbs intact
- `generateSeoMetadata()` falls back to title-only metadata if no SEO fields present
- OG worker is independent — disabling it just removes og:image tags
- JSON-LD component is opt-in per page — removing imports reverts to root-level only
- Lint scripts can be removed from CI command without code changes
