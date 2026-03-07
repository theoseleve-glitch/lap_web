# Navigation & Page Structure Standardization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize navigation, page intros, heading hierarchy, breadcrumbs, section tabs, and footer across all marketing + app routes using a config-driven approach.

**Architecture:** A single `route-map.ts` config drives breadcrumbs, PageIntro, and SectionTabs. Six new UI components replace ad-hoc patterns. Four lint scripts enforce rules in CI. All work is pure frontend — no backend changes.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, Vitest (unit), Playwright (E2E), axe-core (a11y)

**Design doc:** `docs/plans/2026-03-07-nav-structure-standardization-design.md`

---

## Existing Code Reference

- **Nav config**: `src/data/navigation.ts` — `topNavLinks` (5 items), `footerLinks` (13 items)
- **Marketing page intro**: `src/components/site/PageShell.tsx` — eyebrow + h1 + description wrapper, used by 16/18 pages
- **App page intro**: `src/components/app/PageHeader.tsx` — h1 + subtitle + actions, used by app pages
- **Marketing layout**: `src/app/(marketing)/layout.tsx` — ChromeLayout (SiteHeader + SiteFooter)
- **App layout**: `src/app/app/layout.tsx` — collapsible sidebar with hardcoded `navGroups`, skip link, no footer
- **Tokens**: `src/lib/tokens.ts` (JS), `src/styles/tokens.css` (CSS variables) — spacing 8px baseline, focus ring vars exist
- **Lint pattern**: `scripts/lint-design-tokens.mjs` — recursive walk, exemption list, per-line rules, budget-based exit

---

### Task 1: Route Map Config

**Files:**
- Create: `lap-website/src/data/route-map.ts`
- Test: `lap-website/src/__tests__/route-map.test.ts`

**Step 1: Write the test**

```typescript
// lap-website/src/__tests__/route-map.test.ts
import { describe, it, expect } from 'vitest';
import { routeMap, buildBreadcrumbs, type RouteEntry } from '@/data/route-map';

describe('routeMap', () => {
  it('has an entry for /', () => {
    expect(routeMap['/']).toBeDefined();
    expect(routeMap['/'].parent).toBeNull();
  });

  it('every entry has required fields', () => {
    for (const [path, entry] of Object.entries(routeMap)) {
      expect(entry.path).toBe(path);
      expect(typeof entry.title).toBe('string');
      expect(entry.title.length).toBeGreaterThan(0);
    }
  });

  it('parent references exist in the map', () => {
    for (const [path, entry] of Object.entries(routeMap)) {
      if (entry.parent !== null) {
        expect(routeMap[entry.parent]).toBeDefined();
      }
    }
  });

  it('no circular parent references', () => {
    for (const [path, entry] of Object.entries(routeMap)) {
      const visited = new Set<string>();
      let current: RouteEntry | undefined = entry;
      while (current?.parent) {
        expect(visited.has(current.path)).toBe(false);
        visited.add(current.path);
        current = routeMap[current.parent];
      }
    }
  });
});

describe('buildBreadcrumbs', () => {
  it('returns empty for top-level pages', () => {
    expect(buildBreadcrumbs('/')).toEqual([]);
    expect(buildBreadcrumbs('/pricing')).toEqual([]);
  });

  it('returns trail for subpages', () => {
    const crumbs = buildBreadcrumbs('/pricing/compare');
    expect(crumbs.length).toBeGreaterThanOrEqual(1);
    expect(crumbs[0]).toEqual({ label: expect.any(String), href: expect.any(String) });
  });

  it('returns empty for unknown paths', () => {
    expect(buildBreadcrumbs('/does-not-exist')).toEqual([]);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd lap-website && npx vitest run src/__tests__/route-map.test.ts`
Expected: FAIL — module not found

**Step 3: Create route-map.ts**

```typescript
// lap-website/src/data/route-map.ts

export interface SectionAnchor {
  id: string;
  label: string;
}

export interface RouteEntry {
  path: string;
  title: string;
  subtitle?: string;
  badge?: string;
  eyebrow?: string;
  /** null = top-level (no breadcrumb). String = parent path. */
  parent: string | null;
  sectionAnchors?: SectionAnchor[];
}

export const routeMap: Record<string, RouteEntry> = {
  '/': { path: '/', title: 'LAP', parent: null },

  // -- Marketing --
  '/product': {
    path: '/product',
    title: 'The Platform',
    subtitle: 'From raw telemetry to race-winning insights.',
    eyebrow: 'Product',
    parent: null,
    sectionAnchors: [
      { id: 'workflows', label: 'Workflows' },
      { id: 'engineer', label: 'Engineer' },
      { id: 'strategist', label: 'Strategist' },
      { id: 'connect', label: 'Connect' },
    ],
  },
  '/pricing': {
    path: '/pricing',
    title: 'Pricing',
    subtitle: 'Transparent plans for every level.',
    eyebrow: 'Plans',
    parent: null,
    sectionAnchors: [
      { id: 'plans', label: 'Plans' },
      { id: 'features', label: 'Features' },
      { id: 'lifecycle', label: 'Data Lifecycle' },
    ],
  },
  '/pricing/compare': {
    path: '/pricing/compare',
    title: 'Compare Plans',
    parent: '/pricing',
  },
  '/demo': {
    path: '/demo',
    title: 'Demo',
    subtitle: 'See LAP in action.',
    eyebrow: 'Demo',
    parent: null,
    sectionAnchors: [
      { id: 'b2c', label: 'Drivers' },
      { id: 'b2b', label: 'Venues' },
    ],
  },
  '/contact': {
    path: '/contact',
    title: 'Contact',
    subtitle: 'Get in touch with the LAP team.',
    eyebrow: 'Contact',
    parent: null,
  },
  '/customers': {
    path: '/customers',
    title: 'Customers',
    subtitle: 'Teams using LAP.',
    eyebrow: 'Customers',
    parent: null,
    sectionAnchors: [
      { id: 'case-studies', label: 'Case Studies' },
      { id: 'testimonials', label: 'Testimonials' },
      { id: 'benchmarks', label: 'Benchmarks' },
    ],
  },
  '/changelog': {
    path: '/changelog',
    title: 'Changelog',
    subtitle: 'What we shipped.',
    eyebrow: 'Changelog',
    parent: null,
  },
  '/insights': {
    path: '/insights',
    title: 'Insights',
    subtitle: 'Telemetry knowledge base.',
    eyebrow: 'Insights',
    parent: null,
  },
  '/waitlist': {
    path: '/waitlist',
    title: 'Waitlist',
    subtitle: 'Join the waitlist.',
    eyebrow: 'Waitlist',
    parent: null,
  },
  '/help': {
    path: '/help',
    title: 'Help',
    subtitle: 'Guides and support.',
    eyebrow: 'Help',
    parent: null,
    sectionAnchors: [
      { id: 'getting-started', label: 'Getting Started' },
      { id: 'faq', label: 'FAQ' },
      { id: 'contact-support', label: 'Support' },
    ],
  },
  '/billing': {
    path: '/billing',
    title: 'Billing',
    subtitle: 'Invoicing, VAT, and payment details.',
    eyebrow: 'Billing',
    parent: null,
    sectionAnchors: [
      { id: 'vat-currency', label: 'VAT & Currency' },
      { id: 'invoice-payment', label: 'Invoices' },
    ],
  },
  '/status': {
    path: '/status',
    title: 'Status',
    subtitle: 'Live platform health.',
    eyebrow: 'Status',
    parent: null,
    sectionAnchors: [
      { id: 'live-status', label: 'Live Status' },
      { id: 'sla', label: 'SLA' },
      { id: 'audit', label: 'Auditability' },
    ],
  },
  '/book': {
    path: '/book',
    title: 'Book a Call',
    subtitle: 'Schedule a demo with our team.',
    eyebrow: 'Book',
    parent: null,
  },

  // -- Legal / Document pages --
  '/security': {
    path: '/security',
    title: 'Security',
    subtitle: 'How we protect your data.',
    eyebrow: 'Security',
    parent: null,
    sectionAnchors: [
      { id: 'encryption', label: 'Encryption' },
      { id: 'isolation', label: 'Isolation' },
      { id: 'residency', label: 'Residency' },
      { id: 'retention', label: 'Retention' },
      { id: 'incident', label: 'Incidents' },
      { id: 'disclosure', label: 'Disclosure' },
      { id: 'audit', label: 'Audit' },
    ],
  },
  '/privacy': {
    path: '/privacy',
    title: 'Privacy Policy',
    eyebrow: 'Privacy',
    parent: null,
    sectionAnchors: [
      { id: 'data-collect', label: 'Collection' },
      { id: 'data-use', label: 'Usage' },
      { id: 'retention', label: 'Retention' },
      { id: 'processors', label: 'Processors' },
      { id: 'rights', label: 'Your Rights' },
      { id: 'cookies', label: 'Cookies' },
    ],
  },
  '/terms': {
    path: '/terms',
    title: 'Terms of Service',
    eyebrow: 'Terms',
    parent: null,
    sectionAnchors: [
      { id: 'account', label: 'Account' },
      { id: 'billing', label: 'Billing' },
      { id: 'data-ownership', label: 'Data' },
      { id: 'acceptable-use', label: 'Use' },
      { id: 'liability', label: 'Liability' },
    ],
  },
  '/dpa': {
    path: '/dpa',
    title: 'Data Processing Agreement',
    eyebrow: 'DPA',
    parent: null,
    sectionAnchors: [
      { id: 'definitions', label: 'Definitions' },
      { id: 'subject-matter', label: 'Subject' },
      { id: 'security', label: 'Security' },
      { id: 'sub-processors', label: 'Sub-processors' },
      { id: 'transfers', label: 'Transfers' },
    ],
  },
  '/subprocessors': {
    path: '/subprocessors',
    title: 'Sub-processors',
    eyebrow: 'Sub-processors',
    parent: null,
    sectionAnchors: [
      { id: 'list', label: 'Current List' },
      { id: 'residency', label: 'Residency' },
    ],
  },
  '/sitemap': {
    path: '/sitemap',
    title: 'Sitemap',
    parent: null,
  },
};

/** Build breadcrumb trail for a given path. Returns empty for top-level or unknown. */
export function buildBreadcrumbs(pathname: string): { label: string; href: string }[] {
  const entry = routeMap[pathname];
  if (!entry || entry.parent === null) return [];

  const crumbs: { label: string; href: string }[] = [];
  let current = routeMap[entry.parent];
  while (current) {
    crumbs.unshift({ label: current.title, href: current.path });
    current = current.parent ? routeMap[current.parent] : undefined;
  }
  return crumbs;
}
```

**Step 4: Run test to verify it passes**

Run: `cd lap-website && npx vitest run src/__tests__/route-map.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add src/data/route-map.ts src/__tests__/route-map.test.ts
git commit -m "feat(nav): add route-map config with breadcrumb builder"
```

---

### Task 2: Breadcrumb Component

**Files:**
- Create: `lap-website/src/components/ui/Breadcrumb.tsx`
- Test: `lap-website/src/__tests__/breadcrumb.test.tsx`

**Step 1: Write the test**

```typescript
// lap-website/src/__tests__/breadcrumb.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Breadcrumb } from '@/components/ui/Breadcrumb';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(),
}));

import { usePathname } from 'next/navigation';
const mockUsePathname = vi.mocked(usePathname);

describe('Breadcrumb', () => {
  it('renders nothing for top-level pages', () => {
    mockUsePathname.mockReturnValue('/pricing');
    const { container } = render(<Breadcrumb />);
    expect(container.innerHTML).toBe('');
  });

  it('renders breadcrumb trail for subpages', () => {
    mockUsePathname.mockReturnValue('/pricing/compare');
    render(<Breadcrumb />);
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(nav).toBeInTheDocument();
    const list = nav.querySelector('ol');
    expect(list).toBeInTheDocument();
    const links = nav.querySelectorAll('a');
    expect(links.length).toBeGreaterThanOrEqual(1);
  });

  it('renders nothing for unknown paths', () => {
    mockUsePathname.mockReturnValue('/nonexistent/path');
    const { container } = render(<Breadcrumb />);
    expect(container.innerHTML).toBe('');
  });
});
```

**Step 2: Run test — expect FAIL**

Run: `cd lap-website && npx vitest run src/__tests__/breadcrumb.test.tsx`

**Step 3: Create Breadcrumb component**

```tsx
// lap-website/src/components/ui/Breadcrumb.tsx
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { buildBreadcrumbs, routeMap } from '@/data/route-map';

export function Breadcrumb() {
  const pathname = usePathname();
  const crumbs = buildBreadcrumbs(pathname);

  if (crumbs.length === 0) return null;

  const current = routeMap[pathname];

  return (
    <nav aria-label="Breadcrumb" className="mb-[var(--space-1)]">
      <ol className="flex items-center gap-1.5 font-telemetry text-[var(--text-caption)] text-steel">
        {crumbs.map((crumb) => (
          <li key={crumb.href} className="flex items-center gap-1.5">
            <Link href={crumb.href} className="hover:text-chalk transition-colors">
              {crumb.label}
            </Link>
            <span aria-hidden="true" className="text-steel/40">
              &rsaquo;
            </span>
          </li>
        ))}
        {current && (
          <li aria-current="page" className="text-chalk">
            {current.title}
          </li>
        )}
      </ol>
    </nav>
  );
}
```

**Step 4: Run test — expect PASS**

Run: `cd lap-website && npx vitest run src/__tests__/breadcrumb.test.tsx`

**Step 5: Commit**

```bash
git add src/components/ui/Breadcrumb.tsx src/__tests__/breadcrumb.test.tsx
git commit -m "feat(nav): add Breadcrumb component driven by route-map"
```

---

### Task 3: PageIntro Component

**Files:**
- Create: `lap-website/src/components/ui/PageIntro.tsx`
- Test: `lap-website/src/__tests__/page-intro.test.tsx`

**Step 1: Write the test**

```typescript
// lap-website/src/__tests__/page-intro.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PageIntro } from '@/components/ui/PageIntro';

describe('PageIntro', () => {
  it('renders exactly one h1', () => {
    render(<PageIntro title="Test Title" />);
    const headings = screen.getAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent('Test Title');
  });

  it('renders subtitle when provided', () => {
    render(<PageIntro title="Title" subtitle="A subtitle" />);
    expect(screen.getByText('A subtitle')).toBeInTheDocument();
  });

  it('renders eyebrow when provided', () => {
    render(<PageIntro title="Title" eyebrow="Plans" />);
    expect(screen.getByText('Plans')).toBeInTheDocument();
  });

  it('renders badge when provided', () => {
    render(<PageIntro title="Title" badge="Beta" />);
    expect(screen.getByText('Beta')).toBeInTheDocument();
  });

  it('renders actions slot', () => {
    render(<PageIntro title="Title" actions={<button>Upload</button>} />);
    expect(screen.getByRole('button', { name: 'Upload' })).toBeInTheDocument();
  });

  it('does not render eyebrow/subtitle when omitted', () => {
    const { container } = render(<PageIntro title="Title" />);
    expect(container.querySelectorAll('p')).toHaveLength(0);
  });
});
```

**Step 2: Run test — expect FAIL**

Run: `cd lap-website && npx vitest run src/__tests__/page-intro.test.tsx`

**Step 3: Create PageIntro component**

```tsx
// lap-website/src/components/ui/PageIntro.tsx
import type { ReactNode } from 'react';

interface PageIntroProps {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  badge?: string;
  actions?: ReactNode;
}

export function PageIntro({ title, subtitle, eyebrow, badge, actions }: PageIntroProps) {
  return (
    <div className="mb-[var(--space-8)]">
      <div className="flex items-start justify-between">
        <div>
          {eyebrow && (
            <p className="font-telemetry text-steel text-[11px] tracking-[0.12em] uppercase mb-3">
              {eyebrow}
            </p>
          )}
          <h1 className="font-monument text-[var(--text-h1)] leading-[var(--lh-heading)] tracking-[var(--ls-display)]">
            {title}
            {badge && (
              <span className="ml-3 align-middle inline-block text-xs font-telemetry tracking-[0.12em] uppercase border border-pit-orange/40 text-pit-orange px-2 py-0.5 rounded">
                {badge}
              </span>
            )}
          </h1>
          {subtitle && (
            <p className="mt-[var(--space-2)] max-w-3xl text-steel text-lg font-body leading-[var(--lh-body)]">
              {subtitle}
            </p>
          )}
        </div>
        {actions && <div className="flex items-center gap-3 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
```

**Step 4: Run test — expect PASS**

Run: `cd lap-website && npx vitest run src/__tests__/page-intro.test.tsx`

**Step 5: Commit**

```bash
git add src/components/ui/PageIntro.tsx src/__tests__/page-intro.test.tsx
git commit -m "feat(nav): add PageIntro component (replaces PageShell + PageHeader)"
```

---

### Task 4: Section Component

**Files:**
- Create: `lap-website/src/components/ui/Section.tsx`
- Test: `lap-website/src/__tests__/section.test.tsx`

**Step 1: Write the test**

```typescript
// lap-website/src/__tests__/section.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Section } from '@/components/ui/Section';

describe('Section', () => {
  it('renders children', () => {
    render(<Section><p>Content here</p></Section>);
    expect(screen.getByText('Content here')).toBeInTheDocument();
  });

  it('renders h2 heading by default', () => {
    render(<Section heading="Features"><p>content</p></Section>);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Features');
  });

  it('renders h3 when level=3', () => {
    render(<Section heading="Sub Feature" level={3}><p>content</p></Section>);
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Sub Feature');
  });

  it('sets id on wrapper for anchor linking', () => {
    const { container } = render(<Section id="features" heading="Features"><p>x</p></Section>);
    expect(container.querySelector('#features')).toBeInTheDocument();
  });

  it('does not render heading when omitted', () => {
    render(<Section><p>No heading</p></Section>);
    expect(screen.queryByRole('heading')).toBeNull();
  });
});
```

**Step 2: Run test — expect FAIL**

Run: `cd lap-website && npx vitest run src/__tests__/section.test.tsx`

**Step 3: Create Section component**

```tsx
// lap-website/src/components/ui/Section.tsx
import type { ReactNode } from 'react';

interface SectionProps {
  id?: string;
  heading?: string;
  level?: 2 | 3;
  children: ReactNode;
}

export function Section({ id, heading, level = 2, children }: SectionProps) {
  const Tag = `h${level}` as const;

  return (
    <section id={id} className="pt-[var(--space-8)]">
      {heading && (
        <Tag className="font-monument text-[var(--text-h2)] leading-[var(--lh-heading)] tracking-[var(--ls-display)] mb-[var(--space-3)]">
          {heading}
        </Tag>
      )}
      <div className="max-w-[70ch]">{children}</div>
    </section>
  );
}
```

**Step 4: Run test — expect PASS**

Run: `cd lap-website && npx vitest run src/__tests__/section.test.tsx`

**Step 5: Commit**

```bash
git add src/components/ui/Section.tsx src/__tests__/section.test.tsx
git commit -m "feat(nav): add Section component for consistent content rhythm"
```

---

### Task 5: AppFooter Component

**Files:**
- Create: `lap-website/src/components/ui/AppFooter.tsx`
- Test: `lap-website/src/__tests__/app-footer.test.tsx`

**Step 1: Write the test**

```typescript
// lap-website/src/__tests__/app-footer.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppFooter } from '@/components/ui/AppFooter';

describe('AppFooter', () => {
  it('renders all four legal links', () => {
    render(<AppFooter />);
    expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/privacy');
    expect(screen.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
    expect(screen.getByRole('link', { name: 'Security' })).toHaveAttribute('href', '/security');
    expect(screen.getByRole('link', { name: 'Status' })).toHaveAttribute('href', '/status');
  });

  it('renders as a footer element', () => {
    render(<AppFooter />);
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });
});
```

**Step 2: Run test — expect FAIL**

Run: `cd lap-website && npx vitest run src/__tests__/app-footer.test.tsx`

**Step 3: Create AppFooter component**

```tsx
// lap-website/src/components/ui/AppFooter.tsx
import Link from 'next/link';

const legalLinks = [
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
  { label: 'Security', href: '/security' },
  { label: 'Status', href: '/status' },
];

export function AppFooter() {
  return (
    <footer className="mt-auto border-t border-steel/10 py-[var(--space-4)] px-6">
      <nav aria-label="Legal">
        <ul className="flex items-center gap-4">
          {legalLinks.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="font-telemetry text-[var(--text-caption)] text-steel hover:text-chalk transition-colors"
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </footer>
  );
}
```

**Step 4: Run test — expect PASS**

Run: `cd lap-website && npx vitest run src/__tests__/app-footer.test.tsx`

**Step 5: Commit**

```bash
git add src/components/ui/AppFooter.tsx src/__tests__/app-footer.test.tsx
git commit -m "feat(nav): add AppFooter with minimal legal links"
```

---

### Task 6: BackNav Component

**Files:**
- Create: `lap-website/src/components/ui/BackNav.tsx`
- Test: `lap-website/src/__tests__/back-nav.test.tsx`

**Step 1: Write the test**

```typescript
// lap-website/src/__tests__/back-nav.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BackNav } from '@/components/ui/BackNav';

describe('BackNav', () => {
  it('renders link with default label', () => {
    render(<BackNav href="/app/dashboard" />);
    const link = screen.getByRole('link', { name: /back/i });
    expect(link).toHaveAttribute('href', '/app/dashboard');
    expect(link).toHaveTextContent('Back');
  });

  it('renders custom label', () => {
    render(<BackNav href="/app" label="Back to App" />);
    expect(screen.getByRole('link', { name: /back to app/i })).toBeInTheDocument();
  });
});
```

**Step 2: Run test — expect FAIL**

Run: `cd lap-website && npx vitest run src/__tests__/back-nav.test.tsx`

**Step 3: Create BackNav component**

```tsx
// lap-website/src/components/ui/BackNav.tsx
import Link from 'next/link';

interface BackNavProps {
  href: string;
  label?: string;
}

export function BackNav({ href, label = 'Back' }: BackNavProps) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 font-telemetry text-[var(--text-caption)] text-steel hover:text-chalk transition-colors mb-[var(--space-1)]"
    >
      <span aria-hidden="true">&larr;</span>
      {label}
    </Link>
  );
}
```

**Step 4: Run test — expect PASS**

Run: `cd lap-website && npx vitest run src/__tests__/back-nav.test.tsx`

**Step 5: Commit**

```bash
git add src/components/ui/BackNav.tsx src/__tests__/back-nav.test.tsx
git commit -m "feat(nav): add BackNav component"
```

---

### Task 7: SectionTabs Component

**Files:**
- Create: `lap-website/src/components/ui/SectionTabs.tsx`
- Test: `lap-website/src/__tests__/section-tabs.test.tsx`

**Step 1: Write the test**

```typescript
// lap-website/src/__tests__/section-tabs.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SectionTabs } from '@/components/ui/SectionTabs';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(),
}));

import { usePathname } from 'next/navigation';
const mockUsePathname = vi.mocked(usePathname);

describe('SectionTabs', () => {
  it('renders nothing when route has no sectionAnchors', () => {
    mockUsePathname.mockReturnValue('/contact');
    const { container } = render(<SectionTabs />);
    expect(container.querySelector('nav')).toBeNull();
  });

  it('renders tabs for routes with sectionAnchors', () => {
    mockUsePathname.mockReturnValue('/pricing');
    render(<SectionTabs />);
    const nav = screen.getByRole('navigation', { name: /page sections/i });
    expect(nav).toBeInTheDocument();
    const links = nav.querySelectorAll('a');
    expect(links.length).toBeGreaterThanOrEqual(2);
  });

  it('renders nothing for unknown routes', () => {
    mockUsePathname.mockReturnValue('/nonexistent');
    const { container } = render(<SectionTabs />);
    expect(container.querySelector('nav')).toBeNull();
  });

  it('each tab links to anchor', () => {
    mockUsePathname.mockReturnValue('/pricing');
    render(<SectionTabs />);
    const nav = screen.getByRole('navigation', { name: /page sections/i });
    const links = nav.querySelectorAll('a');
    for (const link of links) {
      expect(link.getAttribute('href')).toMatch(/^#/);
    }
  });
});
```

**Step 2: Run test — expect FAIL**

Run: `cd lap-website && npx vitest run src/__tests__/section-tabs.test.tsx`

**Step 3: Create SectionTabs component**

```tsx
// lap-website/src/components/ui/SectionTabs.tsx
'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { routeMap } from '@/data/route-map';

export function SectionTabs() {
  const pathname = usePathname();
  const entry = routeMap[pathname];
  const anchors = entry?.sectionAnchors;
  const [activeId, setActiveId] = useState<string | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    if (!anchors?.length) return;

    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setActiveId(e.target.id);
          }
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    );

    for (const anchor of anchors) {
      const el = document.getElementById(anchor.id);
      if (el) observerRef.current.observe(el);
    }

    return () => observerRef.current?.disconnect();
  }, [anchors]);

  if (!anchors?.length) return null;

  return (
    <nav
      aria-label="Page sections"
      className="sticky top-0 z-[var(--z-nav)] bg-asphalt/95 backdrop-blur border-b border-steel/10"
      style={{ minHeight: '44px' }}
    >
      <div className="mx-auto max-w-6xl px-4 flex items-center gap-1 overflow-x-auto h-11">
        {anchors.map((anchor) => (
          <a
            key={anchor.id}
            href={`#${anchor.id}`}
            className={`font-telemetry text-[11px] tracking-[0.12em] uppercase px-3 py-2 whitespace-nowrap transition-colors ${
              activeId === anchor.id
                ? 'text-chalk border-b-2 border-acid-green'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {anchor.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
```

**Step 4: Run test — expect PASS**

Run: `cd lap-website && npx vitest run src/__tests__/section-tabs.test.tsx`

**Step 5: Commit**

```bash
git add src/components/ui/SectionTabs.tsx src/__tests__/section-tabs.test.tsx
git commit -m "feat(nav): add SectionTabs with IntersectionObserver active tracking"
```

---

### Task 8: Focus Ring Token + Global Styles

**Files:**
- Modify: `lap-website/src/styles/tokens.css` (add focus-visible utility)

**Step 1: Read current tokens.css to find the focus section**

Read `lap-website/src/styles/tokens.css` and locate `--focus-ring-*` variables (around line 152-155).

**Step 2: Add global focus-visible rule after the existing focus ring variables**

Add below the existing `--focus-ring-color` declaration:

```css
/* -- Global Focus Visible -- */
*:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus-ring-color);
  outline-offset: var(--focus-ring-offset);
}
```

**Step 3: Verify build**

Run: `cd lap-website && npx next build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add src/styles/tokens.css
git commit -m "feat(a11y): add global focus-visible ring using design tokens"
```

---

### Task 9: Layout Updates

**Files:**
- Modify: `lap-website/src/components/chrome/ChromeLayout.tsx` (add SectionTabs)
- Modify: `lap-website/src/app/app/layout.tsx` (add AppFooter, remove ad-hoc back link)

**Step 1: Read ChromeLayout.tsx**

Read `lap-website/src/components/chrome/ChromeLayout.tsx` to understand current structure.

**Step 2: Add SectionTabs to ChromeLayout**

After `<SiteHeader />`, add `<SectionTabs />`:

```tsx
import { SectionTabs } from '@/components/ui/SectionTabs';

// In the non-home return:
return (
  <PerformanceProvider>
    <GsapProvider>
      <SiteHeader />
      <SectionTabs />
      {children}
      <SiteFooter />
    </GsapProvider>
  </PerformanceProvider>
);
```

**Step 3: Update app layout**

In `lap-website/src/app/app/layout.tsx`:

1. Add import: `import { AppFooter } from '@/components/ui/AppFooter';`

2. Change `<main>` to flex column and add AppFooter after children:

```tsx
<main id="main-content" className="flex-1 flex flex-col overflow-y-auto bg-asphalt">
  <OfflineBanner />
  <div className="max-w-7xl mx-auto px-6 py-6 flex-1">
    <BillingStateBanner />
    {children}
  </div>
  <AppFooter />
</main>
```

3. Remove the ad-hoc back link block (the `{!collapsed && (<div className="p-4 border-t...">` block at lines 157-165 containing "Back to lap-coach.racing").

**Step 4: Verify dev server renders correctly**

Run: `cd lap-website && npm run dev`
Check: `/pricing` shows SectionTabs below header. `/app/dashboard` shows legal footer at bottom.

**Step 5: Commit**

```bash
git add src/components/chrome/ChromeLayout.tsx src/app/app/layout.tsx
git commit -m "feat(nav): integrate SectionTabs in marketing, AppFooter in app layout"
```

---

### Task 10: Page Migrations — Replace PageShell with PageIntro

**Files:**
- Modify: All 16 marketing pages using `PageShell`
- Modify: 2 pages using raw `<h1>` (`/subprocessors`, `/sitemap`)
- Modify: App pages using `PageHeader`

**Migration pattern for each marketing page:**

Before:
```tsx
import { PageShell } from '@/components/site/PageShell';
export default function Page() {
  return (
    <PageShell eyebrow="Plans" title="Pricing" description="...">
      {/* sections */}
    </PageShell>
  );
}
```

After:
```tsx
import { PageIntro } from '@/components/ui/PageIntro';
export default function Page() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro eyebrow="Plans" title="Pricing" subtitle="..." />
      {/* sections - add id attributes for SectionTabs anchors */}
    </main>
  );
}
```

Key mapping:
- `PageShell.description` -> `PageIntro.subtitle`
- `PageShell.tone="document"` -> use `max-w-4xl` on the `<main>` wrapper
- `PageShell` wraps children in `<main>` — `PageIntro` does not, so add `<main>` wrapper

For app pages:
- `PageHeader.title` -> `PageIntro.title`
- `PageHeader.subtitle` -> `PageIntro.subtitle`
- `PageHeader.actions` -> `PageIntro.actions`

**Step 1: Migrate pricing page as proof**

Read and update `src/app/(marketing)/pricing/page.tsx`. Add `id` attributes to H2 sections matching `routeMap['/pricing'].sectionAnchors`.

**Step 2: Verify pricing page renders**

Run dev server, check `/pricing` — PageIntro renders, SectionTabs highlight active sections on scroll.

**Step 3: Migrate remaining 15 marketing pages + 2 raw-h1 pages**

Apply same pattern to each. For legal pages with `tone="document"`, use `max-w-4xl`.

**Step 4: Migrate app pages using PageHeader**

Replace `PageHeader` imports with `PageIntro`. Files to check:
- `src/app/app/dashboard/page.tsx`
- `src/app/app/sessions/page.tsx`
- Any other app page importing `PageHeader`

**Step 5: Delete old components**

Once all imports are migrated:
- Delete `src/components/site/PageShell.tsx`
- Delete `src/components/app/PageHeader.tsx`

**Step 6: Run full test suite**

Run: `cd lap-website && npm run test`
Expected: All pass. Fix any tests that imported PageShell/PageHeader.

**Step 7: Commit**

```bash
git add -A
git commit -m "feat(nav): migrate all pages from PageShell/PageHeader to PageIntro"
```

---

### Task 11: Lint Script — Nav Overrides

**Files:**
- Create: `lap-website/scripts/lint-nav-overrides.mjs`
- Modify: `lap-website/package.json` (add script)

**Step 1: Create the lint script**

Follow the pattern from `lint-design-tokens.mjs`: recursive walk, exemption list, per-line rules, exit codes.

```javascript
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [path.resolve(process.cwd(), 'src/app')];
const EXEMPT_PATHS = [
  'src/components/site/SiteHeader.tsx',
  'src/components/site/MobileDrawer.tsx',
  'src/data/navigation.ts',
  'src/data/route-map.ts',
];

function walk(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|ts|jsx)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

function isExempt(filePath) {
  const r = rel(filePath);
  return EXEMPT_PATHS.some((e) => r.endsWith(e));
}

const NAV_PATTERNS = [
  { re: /topNavLinks\s*[:=]/, rule: 'nav-override:topNavLinks-redeclared' },
  { re: /aria-label=["']Primary["']/, rule: 'nav-override:inline-primary-nav' },
];

const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    if (isExempt(filePath)) continue;
    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.trimStart().startsWith('//')) continue;
      for (const pat of NAV_PATTERNS) {
        if (pat.re.test(line)) {
          violations.push({
            file: rel(filePath),
            line: i + 1,
            rule: pat.rule,
            context: line.trim().substring(0, 80),
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-nav-overrides: No violations. All clear.');
  process.exit(0);
}

console.error(`lint-nav-overrides: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.error(`  ${v.file}:${v.line} -- ${v.rule} -- ${v.context}`);
}
process.exit(1);
```

**Step 2: Add to package.json**

Add: `"lint:nav": "node scripts/lint-nav-overrides.mjs"`

**Step 3: Run**

Run: `cd lap-website && npm run lint:nav`
Expected: 0 violations

**Step 4: Commit**

```bash
git add scripts/lint-nav-overrides.mjs package.json
git commit -m "feat(lint): add nav-overrides linter"
```

---

### Task 12: Lint Script — Heading Hierarchy

**Files:**
- Create: `lap-website/scripts/lint-heading-hierarchy.mjs`
- Modify: `lap-website/package.json`

**Step 1: Create the lint script**

```javascript
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [path.resolve(process.cwd(), 'src/app')];

function walk(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (entry.name === 'page.tsx') results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

const PAGE_INTRO_RE = /<PageIntro[\s/]/g;
const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    const source = fs.readFileSync(filePath, 'utf-8');
    const file = rel(filePath);

    // Count H1s + PageIntro usage
    const h1Matches = [...source.matchAll(/<h1[\s>]/g)];
    const pageIntroMatches = [...source.matchAll(/<PageIntro[\s/]/g)];
    const h1Count = h1Matches.length + pageIntroMatches.length;

    if (h1Count === 0) {
      violations.push({ file, line: 1, rule: 'heading:missing-h1', context: 'No <h1> or <PageIntro>' });
    } else if (h1Count > 1) {
      violations.push({ file, line: 1, rule: 'heading:multiple-h1', context: `Found ${h1Count} H1-level elements` });
    }

    // Check sequential levels
    const headings = [];
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineHRe = /<h([1-6])[\s>]/g;
      let match;
      while ((match = lineHRe.exec(line)) !== null) {
        headings.push({ level: parseInt(match[1], 10), line: i + 1 });
      }
      if (/<PageIntro[\s/]/.test(line)) {
        headings.push({ level: 1, line: i + 1 });
      }
    }

    for (let i = 1; i < headings.length; i++) {
      const gap = headings[i].level - headings[i - 1].level;
      if (gap > 1) {
        violations.push({
          file,
          line: headings[i].line,
          rule: 'heading:level-skip',
          context: `h${headings[i - 1].level} -> h${headings[i].level} (skipped ${gap - 1} level(s))`,
        });
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-heading-hierarchy: No violations. All clear.');
  process.exit(0);
}

const BUDGET = 10;
console.warn(`lint-heading-hierarchy: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.warn(`  ${v.file}:${v.line} -- ${v.rule} -- ${v.context}`);
}

if (violations.length > BUDGET) {
  console.error(`\n  FAIL: ${violations.length} exceeds budget of ${BUDGET}`);
  process.exit(1);
} else {
  console.warn(`\n  OK: within budget (${BUDGET - violations.length} remaining)`);
  process.exit(0);
}
```

**Step 2: Add to package.json**

Add: `"lint:headings": "node scripts/lint-heading-hierarchy.mjs"`

**Step 3: Run**

Run: `cd lap-website && npm run lint:headings`

**Step 4: Commit**

```bash
git add scripts/lint-heading-hierarchy.mjs package.json
git commit -m "feat(lint): add heading-hierarchy linter"
```

---

### Task 13: Lint Script — Spacing Tokens

**Files:**
- Create: `lap-website/scripts/lint-spacing-tokens.mjs`
- Modify: `lap-website/package.json`

**Step 1: Create the lint script**

```javascript
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app'),
  path.resolve(process.cwd(), 'src/components'),
];
const EXEMPT_PATHS = ['src/components/ui/Section.tsx', 'src/components/ui/PageIntro.tsx'];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|jsx)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

function isExempt(filePath) {
  const r = rel(filePath);
  return EXEMPT_PATHS.some((e) => r.endsWith(e));
}

const HEADING_WITH_CLASS_RE = /<h[23]\s[^>]*className="([^"]*)"/;
const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    if (isExempt(filePath)) continue;
    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.includes('// token-ok')) continue;
      const headingMatch = HEADING_WITH_CLASS_RE.exec(line);
      if (!headingMatch) continue;
      const classStr = headingMatch[1];
      const re = /\b[mp][tbylrx]?-(\[.+?\])/g;
      let spacingMatch;
      while ((spacingMatch = re.exec(classStr)) !== null) {
        const value = spacingMatch[1];
        if (!value.includes('var(--space')) {
          violations.push({
            file: rel(filePath),
            line: i + 1,
            rule: 'spacing:non-token-heading',
            context: `${spacingMatch[0]} -- use Section component or --space-* token`,
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-spacing-tokens: No violations. All clear.');
  process.exit(0);
}

const BUDGET = 20;
console.warn(`lint-spacing-tokens: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.warn(`  ${v.file}:${v.line} -- ${v.rule} -- ${v.context}`);
}

if (violations.length > BUDGET) {
  console.error(`\n  FAIL: ${violations.length} exceeds budget of ${BUDGET}`);
  process.exit(1);
} else {
  console.warn(`\n  OK: within budget (${BUDGET - violations.length} remaining)`);
  process.exit(0);
}
```

**Step 2: Add to package.json**

Add: `"lint:spacing": "node scripts/lint-spacing-tokens.mjs"`

**Step 3: Run and commit**

```bash
cd lap-website && npm run lint:spacing
git add scripts/lint-spacing-tokens.mjs package.json
git commit -m "feat(lint): add spacing-tokens linter for headings"
```

---

### Task 14: Lint Script — Route Map Completeness

**Files:**
- Create: `lap-website/scripts/lint-route-map.mjs`
- Modify: `lap-website/package.json`

**Step 1: Create the lint script**

```javascript
#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');

// Parse route-map.ts for registered paths (avoids TS import)
const routeMapSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/data/route-map.ts'),
  'utf-8',
);
const PATH_KEY_RE = /'([^']+)':\s*\{/g;
const registeredPaths = new Set();
let match;
while ((match = PATH_KEY_RE.exec(routeMapSource)) !== null) {
  registeredPaths.add(match[1]);
}

function findPages(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...findPages(full));
    else if (entry.name === 'page.tsx') results.push(full);
  }
  return results;
}

const violations = [];

for (const pageFile of findPages(MARKETING_DIR)) {
  const relative = path.relative(MARKETING_DIR, path.dirname(pageFile)).replace(/\\/g, '/');
  const routePath = relative ? `/${relative}` : '/';
  // Skip the root marketing page (it maps to '/' which is home)
  if (!registeredPaths.has(routePath) && routePath !== '/') {
    violations.push({
      file: path.relative(process.cwd(), pageFile).replace(/\\/g, '/'),
      path: routePath,
    });
  }
}

if (violations.length === 0) {
  console.log('lint-route-map: All marketing pages have route-map entries. All clear.');
  process.exit(0);
}

console.error(`lint-route-map: ${violations.length} page(s) missing from route-map:\n`);
for (const v of violations) {
  console.error(`  ${v.file} -> expected routeMap['${v.path}']`);
}
process.exit(1);
```

**Step 2: Add to package.json**

Add: `"lint:routes": "node scripts/lint-route-map.mjs"`

**Step 3: Run and commit**

```bash
cd lap-website && npm run lint:routes
git add scripts/lint-route-map.mjs package.json
git commit -m "feat(lint): add route-map completeness linter"
```

---

### Task 15: Update CI Script

**Files:**
- Modify: `lap-website/package.json` (append 4 linters to `ci` script)

**Step 1: Update the `ci` script**

Add `&& npm run lint:nav && npm run lint:headings && npm run lint:spacing && npm run lint:routes` before `&& npm run ci:assert-site-url` in the ci script chain.

**Step 2: Run full CI locally**

Run: `cd lap-website && npm run ci`
Expected: All checks pass

**Step 3: Commit**

```bash
git add package.json
git commit -m "ci: add nav/heading/spacing/route linters to CI pipeline"
```

---

### Task 16: E2E Accessibility Tests

**Files:**
- Create: `lap-website/e2e/a11y-structure.spec.ts`

**Step 1: Create E2E test file**

```typescript
import { test, expect } from '@playwright/test';

test.describe('Navigation & Page Structure A11y', () => {
  test('marketing page has skip link targeting #main-content', async ({ page }) => {
    await page.goto('/pricing');
    const skipLink = page.locator('a[href="#main-content"]');
    await expect(skipLink).toBeAttached();
    await page.keyboard.press('Tab');
    await expect(skipLink).toBeFocused();
    await expect(page.locator('#main-content')).toBeAttached();
  });

  test('app page has skip link targeting #main-content', async ({ page }) => {
    await page.goto('/app/dashboard');
    const skipLink = page.locator('a[href="#main-content"]');
    await expect(skipLink).toBeAttached();
    await expect(page.locator('#main-content')).toBeAttached();
  });

  test('pricing page has SectionTabs with correct semantics', async ({ page }) => {
    await page.goto('/pricing');
    const nav = page.locator('nav[aria-label="Page sections"]');
    await expect(nav).toBeVisible();
    const links = nav.locator('a');
    expect(await links.count()).toBeGreaterThanOrEqual(2);
    for (const link of await links.all()) {
      const href = await link.getAttribute('href');
      expect(href).toMatch(/^#/);
    }
  });

  test('pricing page has exactly one h1', async ({ page }) => {
    await page.goto('/pricing');
    const h1s = page.locator('h1');
    expect(await h1s.count()).toBe(1);
  });

  test('subpage has breadcrumb with correct semantics', async ({ page }) => {
    const response = await page.goto('/pricing/compare');
    if (response && response.status() === 200) {
      const nav = page.locator('nav[aria-label="Breadcrumb"]');
      await expect(nav).toBeVisible();
      const ol = nav.locator('ol');
      await expect(ol).toBeAttached();
      const current = nav.locator('[aria-current="page"]');
      await expect(current).toBeAttached();
    }
  });

  test('app dashboard has legal footer links', async ({ page }) => {
    await page.goto('/app/dashboard');
    const footer = page.locator('footer');
    await expect(footer).toBeAttached();
    await expect(page.locator('footer a[href="/privacy"]')).toBeAttached();
    await expect(page.locator('footer a[href="/terms"]')).toBeAttached();
    await expect(page.locator('footer a[href="/security"]')).toBeAttached();
    await expect(page.locator('footer a[href="/status"]')).toBeAttached();
  });

  test('SectionTabs keyboard navigation works', async ({ page }) => {
    await page.goto('/pricing');
    const nav = page.locator('nav[aria-label="Page sections"]');
    const firstTab = nav.locator('a').first();
    await firstTab.focus();
    await expect(firstTab).toBeFocused();
  });
});
```

**Step 2: Commit**

```bash
git add e2e/a11y-structure.spec.ts
git commit -m "test(e2e): add a11y structure tests for nav, breadcrumbs, headings, footer"
```

---

### Task 17: Final Verification

**Step 1: Run unit tests**
```bash
cd lap-website && npm run test
```

**Step 2: Run all new linters**
```bash
npm run lint:nav && npm run lint:headings && npm run lint:spacing && npm run lint:routes
```

**Step 3: Run build**
```bash
npm run build
```

**Step 4: Run full CI**
```bash
npm run ci
```

**Step 5: Manual checks (from design doc)**
1. Open 3 marketing pages — nav items identical
2. Navigate to subpage — breadcrumb trail correct
3. Tab on any page — skip link visible, Enter jumps to main
4. Tab through interactive elements — consistent focus ring
5. Scroll `/pricing` — section tabs stick, active highlights
6. Open `/app/dashboard` — legal links at bottom
7. Inspect heading hierarchy in DevTools

**Step 6: Final commit**
```bash
git add -A
git commit -m "feat(nav): navigation & page structure standardization complete"
```

---

## File Summary

| Action | File |
|--------|------|
| Create | `src/data/route-map.ts` |
| Create | `src/components/ui/Breadcrumb.tsx` |
| Create | `src/components/ui/PageIntro.tsx` |
| Create | `src/components/ui/Section.tsx` |
| Create | `src/components/ui/AppFooter.tsx` |
| Create | `src/components/ui/BackNav.tsx` |
| Create | `src/components/ui/SectionTabs.tsx` |
| Create | `scripts/lint-nav-overrides.mjs` |
| Create | `scripts/lint-heading-hierarchy.mjs` |
| Create | `scripts/lint-spacing-tokens.mjs` |
| Create | `scripts/lint-route-map.mjs` |
| Create | `e2e/a11y-structure.spec.ts` |
| Create | `src/__tests__/route-map.test.ts` |
| Create | `src/__tests__/breadcrumb.test.tsx` |
| Create | `src/__tests__/page-intro.test.tsx` |
| Create | `src/__tests__/section.test.tsx` |
| Create | `src/__tests__/app-footer.test.tsx` |
| Create | `src/__tests__/back-nav.test.tsx` |
| Create | `src/__tests__/section-tabs.test.tsx` |
| Modify | `src/styles/tokens.css` (focus-visible rule) |
| Modify | `src/components/chrome/ChromeLayout.tsx` (add SectionTabs) |
| Modify | `src/app/app/layout.tsx` (add AppFooter, remove back link) |
| Modify | `src/app/(marketing)/*/page.tsx` (PageShell to PageIntro, 18 files) |
| Modify | `src/app/app/*/page.tsx` (PageHeader to PageIntro) |
| Delete | `src/components/site/PageShell.tsx` |
| Delete | `src/components/app/PageHeader.tsx` |
| Modify | `package.json` (4 lint scripts + CI update) |
