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
  parent: string | null;
  sectionAnchors?: SectionAnchor[];
}

export const routeMap: Record<string, RouteEntry> = {
  '/': {
    path: '/',
    title: 'LAP',
    parent: null,
  },
  '/product': {
    path: '/product',
    title: 'The Platform',
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
    eyebrow: 'Plans',
    parent: null,
    sectionAnchors: [
      { id: 'plans', label: 'Plans' },
      { id: 'features', label: 'Features' },
      { id: 'lifecycle', label: 'Lifecycle' },
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
    parent: null,
    sectionAnchors: [
      { id: 'b2c', label: 'B2C' },
      { id: 'b2b', label: 'B2B' },
    ],
  },
  '/contact': {
    path: '/contact',
    title: 'Contact',
    parent: null,
  },
  '/customers': {
    path: '/customers',
    title: 'Customers',
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
    parent: null,
  },
  '/insights': {
    path: '/insights',
    title: 'Insights',
    parent: null,
  },
  '/waitlist': {
    path: '/waitlist',
    title: 'Waitlist',
    parent: null,
  },
  '/help': {
    path: '/help',
    title: 'Help',
    parent: null,
    sectionAnchors: [
      { id: 'getting-started', label: 'Getting Started' },
      { id: 'faq', label: 'FAQ' },
      { id: 'contact-support', label: 'Contact Support' },
    ],
  },
  '/billing': {
    path: '/billing',
    title: 'Billing',
    parent: null,
    sectionAnchors: [
      { id: 'vat-currency', label: 'VAT & Currency' },
      { id: 'invoice-payment', label: 'Invoice & Payment' },
    ],
  },
  '/status': {
    path: '/status',
    title: 'Status',
    parent: null,
    sectionAnchors: [
      { id: 'live-status', label: 'Live Status' },
      { id: 'sla', label: 'SLA' },
      { id: 'audit', label: 'Audit' },
    ],
  },
  '/book': {
    path: '/book',
    title: 'Book a Call',
    parent: null,
  },
  '/security': {
    path: '/security',
    title: 'Security',
    parent: null,
    sectionAnchors: [
      { id: 'encryption', label: 'Encryption' },
      { id: 'isolation', label: 'Isolation' },
      { id: 'residency', label: 'Residency' },
      { id: 'retention', label: 'Retention' },
      { id: 'incident', label: 'Incident' },
      { id: 'disclosure', label: 'Disclosure' },
      { id: 'audit', label: 'Audit' },
    ],
  },
  '/privacy': {
    path: '/privacy',
    title: 'Privacy Policy',
    parent: null,
    sectionAnchors: [
      { id: 'data-collect', label: 'Data Collection' },
      { id: 'data-use', label: 'Data Use' },
      { id: 'retention', label: 'Retention' },
      { id: 'processors', label: 'Processors' },
      { id: 'rights', label: 'Rights' },
      { id: 'cookies', label: 'Cookies' },
    ],
  },
  '/terms': {
    path: '/terms',
    title: 'Terms of Service',
    parent: null,
    sectionAnchors: [
      { id: 'account', label: 'Account' },
      { id: 'billing', label: 'Billing' },
      { id: 'data-ownership', label: 'Data Ownership' },
      { id: 'acceptable-use', label: 'Acceptable Use' },
      { id: 'liability', label: 'Liability' },
    ],
  },
  '/dpa': {
    path: '/dpa',
    title: 'Data Processing Agreement',
    parent: null,
    sectionAnchors: [
      { id: 'definitions', label: 'Definitions' },
      { id: 'subject-matter', label: 'Subject Matter' },
      { id: 'security', label: 'Security' },
      { id: 'sub-processors', label: 'Sub-processors' },
      { id: 'transfers', label: 'Transfers' },
    ],
  },
  '/subprocessors': {
    path: '/subprocessors',
    title: 'Sub-processors',
    parent: null,
    sectionAnchors: [
      { id: 'list', label: 'List' },
      { id: 'residency', label: 'Residency' },
    ],
  },
  '/sitemap': {
    path: '/sitemap',
    title: 'Sitemap',
    parent: null,
  },
};

export interface Breadcrumb {
  label: string;
  href: string;
}

export function buildBreadcrumbs(pathname: string): Breadcrumb[] {
  const entry = routeMap[pathname];
  if (!entry || entry.parent === null) {
    return [];
  }

  const crumbs: Breadcrumb[] = [];
  let current: string | null = entry.parent;
  const visited = new Set<string>();

  while (current !== null && !visited.has(current)) {
    visited.add(current);
    const parentEntry = routeMap[current];
    if (!parentEntry) break;
    crumbs.unshift({ label: parentEntry.title, href: parentEntry.path });
    current = parentEntry.parent;
  }

  return crumbs;
}
