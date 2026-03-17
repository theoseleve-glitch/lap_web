import type { CapabilityStatus } from '@/data/claim-registry';

export type BillingCycle = 'monthly' | 'annual';

export interface Plan {
  name: string;
  slug: string;
  priceMonthly: string;
  priceAnnual: string;
  priceAnnualPerMonth: string;
  annualTotal: string;
  savingsPercent: string;
  features: Record<string, string>;
  cta: string;
  ctaHref: string;
  highlighted?: boolean;
  availability: CapabilityStatus;
}

/** Individual driver plans */
export const plans: Plan[] = [
  {
    name: 'DEMO',
    slug: 'demo',
    priceMonthly: 'Free',
    priceAnnual: 'Free',
    priceAnnualPerMonth: 'Free',
    annualTotal: '',
    savingsPercent: '',
    features: {
      'Session Upload': '1 session (150 MB max)',
      'Race Strategy': 'Up to 4h, basic parameters',
      'Badge & Share Card': 'Full',
      'Visualization': '—',
      'Gamification': '—',
      'Comparison & Progress': '—',
      'Coaching Plans': '—',
      'Live Monitoring': '—',
      'Pit Stop Planning': '—',
      'Raw Telemetry Retention': '1 month',
    },
    cta: 'Start Free',
    ctaHref: '/register?source=demo',
    availability: 'available_now',
  },
  {
    name: 'RACER',
    slug: 'racer',
    priceMonthly: '€9 / mo',
    priceAnnual: '€72 / yr',
    priceAnnualPerMonth: '€6.00 / mo',
    annualTotal: '€72/yr',
    savingsPercent: '33',
    features: {
      'Analysis Reports': '10 / month (2.5 GB max)',
      'Race Strategy': 'Up to 24h, complex parameters',
      'Optimizer': 'Equal-time only',
      'Visualization': 'Full',
      'Gamification': 'Full',
      'Badge & Share Card': 'Full',
      'Comparison & Progress': '—',
      'Coaching Plans': 'Full',
      'Live Monitoring': 'Full',
      'Pit Stop Planning': 'Full',
      'Raw Telemetry Retention': '3 months',
    },
    cta: 'Upgrade',
    ctaHref: '/billing?plan=RACER&billing=annual',
    highlighted: true,
    availability: 'available_now',
  },
  {
    name: 'WORLD-CLASS',
    slug: 'world-class',
    priceMonthly: '€14 / mo',
    priceAnnual: '€108 / yr',
    priceAnnualPerMonth: '€9.00 / mo',
    annualTotal: '€108/yr',
    savingsPercent: '36',
    features: {
      'Analysis Reports': 'Unlimited',
      'Race Strategy': 'Unlimited duration',
      'Optimizer': 'All modes (equal + performance)',
      'Visualization': 'Full',
      'Gamification': 'Full',
      'Badge & Share Card': 'Full',
      'Comparison & Progress': 'Full',
      'Coaching Plans': 'Full',
      'Live Monitoring': 'Full',
      'Pit Stop Planning': 'Full',
      'Raw Telemetry Retention': '12 months',
    },
    cta: 'Go World-Class',
    ctaHref: '/billing?plan=WORLD-CLASS&billing=annual',
    availability: 'available_now',
  },
];

export interface B2BCard {
  name: string;
  features: string[];
  cta: string;
  ctaHref: string;
}

export const venueCard: B2BCard = {
  name: 'FOR VENUES & TEAMS',
  features: [
    'Hardware for data logging',
    'Live telemetry software',
    'Branded driver reports',
    'Custom retention & compliance',
    'Dedicated onboarding',
  ],
  cta: 'Contact Sales',
  ctaHref: '/contact?plan=venues',
};

/** @deprecated Use `plans` instead */
export const b2cPlans = plans;

/** @deprecated Use `venueCard` instead */
export const b2bCard = venueCard;

export interface EligibilityRow {
  feature: string;
  group: 'coaching' | 'strategy' | 'data';
  demo: string;
  racer: string;
  worldClass: string;
}

export const featureEligibilityMatrix: EligibilityRow[] = [
  // COACHING
  { feature: 'Upload & Analyze', group: 'coaching', demo: '1 session (150 MB)', racer: '10/mo (2.5 GB)', worldClass: 'Unlimited' },
  { feature: 'Badge & Share Card', group: 'coaching', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { feature: 'Visualization Workspace', group: 'coaching', demo: '—', racer: 'Full', worldClass: 'Full' },
  { feature: 'Gamification & Achievements', group: 'coaching', demo: '—', racer: 'Full', worldClass: 'Full' },
  { feature: 'Comparison & Progress', group: 'coaching', demo: '—', racer: '—', worldClass: 'Full' },
  { feature: 'Coaching Plans & Drills', group: 'coaching', demo: '—', racer: 'Full', worldClass: 'Full' },
  // STRATEGY
  { feature: 'Race Strategy Dashboard', group: 'strategy', demo: '4h, basic params', racer: '24h, complex params', worldClass: 'Unlimited' },
  { feature: 'Optimizer Modes', group: 'strategy', demo: 'Equal-time', racer: 'Equal-time', worldClass: 'All modes' },
  { feature: 'Live Pace & Stint Monitoring', group: 'strategy', demo: '—', racer: 'Full', worldClass: 'Full' },
  { feature: 'Pit Stop Planning', group: 'strategy', demo: '—', racer: 'Full', worldClass: 'Full' },
  // DATA & OPS
  { feature: 'PDF Reports', group: 'data', demo: '—', racer: 'Full', worldClass: 'Full' },
  { feature: 'API Access', group: 'data', demo: '—', racer: '—', worldClass: 'Full' },
  { feature: 'Raw Telemetry Retention', group: 'data', demo: '1 month', racer: '3 months', worldClass: '12 months' },
  { feature: 'Report Retention', group: 'data', demo: 'Indefinite', racer: 'Indefinite', worldClass: 'Indefinite' },
];

export interface DataLifecycleItem {
  category: string;
  description: string;
  tiers: { label: string; value: string }[];
  note: string;
}

export const dataLifecycle: DataLifecycleItem[] = [
  {
    category: 'RAW TELEMETRY',
    description: 'Up to 150 MB (Demo) / 2.5 GB (Racer) / unlimited (World-Class)',
    tiers: [
      { label: 'Demo', value: '1 session, 1 month → auto-deleted' },
      { label: 'Racer', value: '10/mo, 3 months → auto-deleted' },
      { label: 'World-Class', value: 'Unlimited, 12 months → auto-deleted' },
    ],
    note: 'Raw files are large. After expiry, they\'re automatically deleted. Export before expiry — it\'s always yours.',
  },
  {
    category: 'PROCESSED REPORTS',
    description: '1–5MB',
    tiers: [
      { label: 'All plans', value: 'Stored indefinitely' },
      { label: 'Venues & Teams', value: '2 years' },
    ],
    note: 'Reports are your permanent record. Lightweight. No extra cost.',
  },
  {
    category: 'LIVE EVENT DATA',
    description: 'High-frequency telemetry',
    tiers: [
      { label: 'Raw stream', value: 'Temporary (flushed after event)' },
      { label: 'Summaries + leaderboard', value: 'Persist' },
    ],
    note: 'Real-time data serves the moment. Summaries last.',
  },
];
