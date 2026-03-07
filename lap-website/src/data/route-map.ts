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
  primaryKeyword?: string;
  metaDescription?: string;
  ogTitle?: string;
  ogDescription?: string;
  jsonLdType?: 'WebPage' | 'FAQPage' | 'Article';
  noIndex?: boolean;
  canonical?: string;
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
      { id: 'coaching', label: 'Coaching' },
      { id: 'strategy', label: 'Strategy' },
      { id: 'connect', label: 'Connect' },
    ],
    primaryKeyword: 'motorsport telemetry platform',
    metaDescription: 'Analyse kart and car telemetry with LAP. Ingest RaceChrono and RaceBox data, detect corners, and generate lap-by-lap coaching insights.',
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
    primaryKeyword: 'telemetry analysis pricing',
    metaDescription: 'Choose the right LAP plan for your racing programme. Compare Performance, Pro Racer, and Circuit tiers with transparent monthly and annual pricing.',
    jsonLdType: 'FAQPage',
  },
  '/pricing/compare': {
    path: '/pricing/compare',
    title: 'Compare Plans',
    parent: '/pricing',
    primaryKeyword: 'compare telemetry plans',
    metaDescription: 'Side-by-side feature comparison of every LAP subscription tier. Find the plan that matches your team size, data volume, and analysis needs.',
  },
  '/demo': {
    path: '/demo',
    title: 'Demo',
    parent: null,
    sectionAnchors: [
      { id: 'b2c', label: 'B2C' },
      { id: 'b2b', label: 'B2B' },
    ],
    primaryKeyword: 'telemetry demo',
    metaDescription: 'See LAP in action. Explore interactive demos for individual drivers and racing teams showing real-time telemetry analysis and coaching workflows.',
  },
  '/contact': {
    path: '/contact',
    title: 'Contact',
    parent: null,
    primaryKeyword: 'contact lap racing',
    metaDescription: 'Get in touch with the LAP team. Reach out for sales enquiries, technical support, partnership opportunities, or general questions about our platform.',
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
    primaryKeyword: 'racing telemetry case studies',
    metaDescription: 'Discover how kart and car racing teams use LAP to shave seconds off their lap times. Read case studies, testimonials, and performance benchmarks.',
  },
  '/changelog': {
    path: '/changelog',
    title: 'Changelog',
    parent: null,
    primaryKeyword: 'lap platform changelog',
    metaDescription: 'Stay up to date with every LAP release. Browse the full changelog for new telemetry features, pipeline improvements, and bug fixes.',
  },
  '/insights': {
    path: '/insights',
    title: 'Insights',
    parent: null,
    primaryKeyword: 'motorsport data insights',
    metaDescription: 'Read expert articles on racing telemetry analysis, driver coaching techniques, data engineering best practices, and performance optimisation strategies.',
  },
  '/waitlist': {
    path: '/waitlist',
    title: 'Waitlist',
    parent: null,
    primaryKeyword: 'lap early access',
    metaDescription: 'Join the LAP waitlist for early access to our motorsport telemetry platform. Be first to try new analysis features and coaching tools.',
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
    primaryKeyword: 'telemetry help centre',
    metaDescription: 'Find answers to common questions about LAP. Browse getting-started guides, FAQs on data import and analysis, and contact our support team.',
    jsonLdType: 'FAQPage',
  },
  '/billing': {
    path: '/billing',
    title: 'Billing',
    parent: null,
    sectionAnchors: [
      { id: 'vat-currency', label: 'VAT & Currency' },
      { id: 'invoice-payment', label: 'Invoice & Payment' },
    ],
    primaryKeyword: 'lap billing and invoices',
    metaDescription: 'Manage your LAP subscription billing. Learn about supported currencies, VAT handling, invoice downloads, and available payment methods.',
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
    primaryKeyword: 'lap service status',
    metaDescription: 'Check real-time LAP platform status, uptime SLA commitments, and incident history. Monitor API, pipeline, and dashboard availability.',
  },
  '/book': {
    path: '/book',
    title: 'Book a Call',
    parent: null,
    primaryKeyword: 'book telemetry consultation',
    metaDescription: 'Schedule a call with the LAP team to discuss your racing telemetry requirements. Get a personalised walkthrough of the platform and integration options.',
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
    primaryKeyword: 'telemetry data security',
    metaDescription: 'Learn how LAP protects your racing data. Encryption at rest and in transit, tenant isolation, data residency controls, and incident response procedures.',
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
    primaryKeyword: 'lap privacy policy',
    metaDescription: 'Read the LAP privacy policy. Understand what personal and telemetry data we collect, how we use it, your rights, and our cookie practices.',
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
    primaryKeyword: 'lap terms of service',
    metaDescription: 'Review the LAP terms of service covering account responsibilities, billing, data ownership, acceptable use policies, and liability limitations.',
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
    primaryKeyword: 'data processing agreement',
    metaDescription: 'Download the LAP data processing agreement. Covers GDPR-compliant data handling, security measures, sub-processor disclosures, and international transfers.',
  },
  '/subprocessors': {
    path: '/subprocessors',
    title: 'Sub-processors',
    parent: null,
    sectionAnchors: [
      { id: 'list', label: 'List' },
      { id: 'residency', label: 'Residency' },
    ],
    primaryKeyword: 'lap sub-processors list',
    metaDescription: 'View the complete list of LAP sub-processors and their data residency locations. Updated whenever a new third-party processor is added or changed.',
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
