import type { CapabilityStatus } from '@/data/claim-registry';

// June-8 model: one membership, monthly only. No annual cycle.
export type BillingCycle = 'monthly';

export interface Plan {
  name: string;
  slug: string;
  /** Standard price, e.g. '€19.90 / mo'. */
  priceMonthly: string;
  /** Discounted price for the first `foundingLimit` members, e.g. '€14.90 / mo'. */
  foundingPriceMonthly: string;
  foundingLimit: number;
  trialDays: number;
  features: Record<string, string>;
  cta: string;
  highlighted?: boolean;
  availability: CapabilityStatus;
}

export const MEMBERSHIP_SLUG = 'membership';

/**
 * One membership. €19.90/mo, €14.90/mo for the first 50 (Founding-50), 30-day
 * free trial, no free tier. The real price is in Stripe (backend selects
 * founding vs standard at checkout); these strings are display only.
 */
export const plans: Plan[] = [
  {
    name: 'LAP COACH',
    slug: MEMBERSHIP_SLUG,
    priceMonthly: '€19.90 / mo',
    foundingPriceMonthly: '€14.90 / mo',
    foundingLimit: 50,
    trialDays: 30,
    features: {
      'Session analysis': 'Unlimited',
      'Race strategy': 'Unlimited — all optimizer modes',
      'Visualization & comparison': 'Full',
      'Coaching plans & drills': 'Full',
      'Gamification & achievements': 'Full',
      'Live pace & stint monitoring': 'Full',
      'PDF reports & API access': 'Full',
      'Logger auto-sync': 'Upload + auto-analyze',
      'Linked devices': '3',
      'Raw telemetry retention': '12 months',
      'Report retention': '5 years',
    },
    cta: 'Start 30-day free trial',
    highlighted: true,
    availability: 'available_now',
  },
];

/** @deprecated Use `plans` instead. */
export const b2cPlans = plans;

// Single "what you get" list — one membership unlocks everything (no per-tier matrix).
export interface EligibilityRow {
  feature: string;
  group: 'coaching' | 'strategy' | 'data';
  value: string;
}

export const featureEligibilityMatrix: EligibilityRow[] = [
  { feature: 'Upload & Analyze', group: 'coaching', value: 'Unlimited' },
  { feature: 'Badge & Share Card', group: 'coaching', value: 'Full' },
  { feature: 'Visualization Workspace', group: 'coaching', value: 'Full' },
  { feature: 'Gamification & Achievements', group: 'coaching', value: 'Full' },
  { feature: 'Comparison & Progress', group: 'coaching', value: 'Full' },
  { feature: 'Coaching Plans & Drills', group: 'coaching', value: 'Full' },
  { feature: 'Race Strategy Dashboard', group: 'strategy', value: 'Unlimited duration & parameters' },
  { feature: 'Optimizer Modes', group: 'strategy', value: 'All modes' },
  { feature: 'Live Pace & Stint Monitoring', group: 'strategy', value: 'Full' },
  { feature: 'Pit Stop Planning', group: 'strategy', value: 'Full' },
  { feature: 'PDF Reports', group: 'data', value: 'Full' },
  { feature: 'API Access', group: 'data', value: 'Full' },
  { feature: 'Logger Auto-Sync', group: 'data', value: 'Upload + Auto-Analyze' },
  { feature: 'Linked Devices', group: 'data', value: '3' },
  { feature: 'Raw Telemetry Retention', group: 'data', value: '12 months' },
  { feature: 'Report Retention', group: 'data', value: '5 years' },
];

export interface DataLifecycleItem {
  category: string;
  description: string;
  value: string;
  note: string;
}

export const dataLifecycle: DataLifecycleItem[] = [
  {
    category: 'RAW TELEMETRY',
    description: 'Your uploaded session files',
    value: 'Kept 12 months, then auto-deleted',
    note: "Raw files are large. After expiry they're automatically deleted — export before then, it's always yours.",
  },
  {
    category: 'PROCESSED REPORTS',
    description: '1–5 MB analysis reports',
    value: 'Kept 5 years',
    note: 'Reports are your permanent record. Lightweight, no extra cost.',
  },
  {
    category: 'LIVE EVENT DATA',
    description: 'High-frequency telemetry',
    value: 'Raw stream temporary; summaries + leaderboard persist',
    note: 'Real-time data serves the moment. Summaries last.',
  },
];
