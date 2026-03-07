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
      'Analysis Reports': '1 full report',
      '4-Pillar Scoring': 'Full',
      'Corner Coaching': 'Full',
      'Session Intelligence': 'Full',
      'Comparison & Progress': '—',
      'Coaching Plans': '—',
      'Visualization': '—',
      'Race Strategy Dashboard': 'Limited (3h races)',
      'Live Monitoring': '—',
      'Pit Stop Planning': '—',
      'Incident Queue': '—',
      'Raw Telemetry Retention': '1 month',
      'Report Retention': 'Indefinite',
      'Exports': 'CSV',
    },
    cta: 'Start Free',
    ctaHref: '/register?source=demo',
    availability: 'available_now',
  },
  {
    name: 'RACER',
    slug: 'racer',
    priceMonthly: '€8.99 / mo',
    priceAnnual: '€69 / yr',
    priceAnnualPerMonth: '€5.75 / mo',
    annualTotal: '€69/yr',
    savingsPercent: '36',
    features: {
      'Analysis Reports': '10 / month',
      '4-Pillar Scoring': 'Full',
      'Corner Coaching': 'Full',
      'Session Intelligence': 'Full',
      'Comparison & Progress': '—',
      'Coaching Plans': 'Full',
      'Visualization': 'Full',
      'Race Strategy Dashboard': 'Full',
      'Live Monitoring': 'Full',
      'Pit Stop Planning': 'Full',
      'Incident Queue': 'Full',
      'Raw Telemetry Retention': '3 months',
      'Report Retention': 'Indefinite',
      'Exports': 'PDF + CSV',
    },
    cta: 'Upgrade',
    ctaHref: '/billing?plan=RACER&billing=annual',
    highlighted: true,
    availability: 'available_now',
  },
  {
    name: 'WORLD-CLASS',
    slug: 'world-class',
    priceMonthly: '€13.99 / mo',
    priceAnnual: '€108 / yr',
    priceAnnualPerMonth: '€9.00 / mo',
    annualTotal: '€108/yr',
    savingsPercent: '36',
    features: {
      'Analysis Reports': 'Unlimited',
      '4-Pillar Scoring': 'Full',
      'Corner Coaching': 'Full',
      'Session Intelligence': 'Full',
      'Comparison & Progress': 'Full',
      'Coaching Plans': 'Full',
      'Visualization': 'Full',
      'Race Strategy Dashboard': 'Full',
      'Live Monitoring': 'Full',
      'Pit Stop Planning': 'Full',
      'Incident Queue': 'Full',
      'Raw Telemetry Retention': '12 months',
      'Report Retention': 'Indefinite',
      'Exports': 'PDF + CSV + API',
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
  { feature: 'Upload & Analyze', group: 'coaching', demo: '1 report', racer: '10/mo', worldClass: 'Unlimited' },
  { feature: '4-Pillar Scoring', group: 'coaching', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { feature: 'Corner-by-Corner Coaching', group: 'coaching', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { feature: 'Session Intelligence Tabs', group: 'coaching', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { feature: 'Comparison & Progress', group: 'coaching', demo: '—', racer: '—', worldClass: 'Full' },
  { feature: 'Coaching Plans & Drills', group: 'coaching', demo: '—', racer: 'Full', worldClass: 'Full' },
  { feature: 'Visualization Workspace', group: 'coaching', demo: '—', racer: 'Full', worldClass: 'Full' },
  // STRATEGY
  { feature: 'Race Strategy Dashboard', group: 'strategy', demo: '3h limit', racer: 'Full', worldClass: 'Full' },
  { feature: 'Live Pace & Stint Monitoring', group: 'strategy', demo: '—', racer: 'Full', worldClass: 'Full' },
  { feature: 'Pit Stop Planning', group: 'strategy', demo: '—', racer: 'Full', worldClass: 'Full' },
  { feature: 'Incident & Alert Queue', group: 'strategy', demo: '—', racer: 'Full', worldClass: 'Full' },
  // DATA & OPS
  { feature: 'Track/Driver/Kart Management', group: 'data', demo: 'Basic', racer: 'Full', worldClass: 'Full' },
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
    description: '100MB–8GB per session',
    tiers: [
      { label: 'Demo', value: '1 month → auto-deleted' },
      { label: 'Racer', value: '3 months → auto-deleted' },
      { label: 'World-Class', value: '12 months → auto-deleted' },
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
