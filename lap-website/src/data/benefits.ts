/**
 * Benefits registry — each benefit bullet has a unique id and allowed pages.
 *
 * Lint rule: a benefit id may only appear on its listed pages.
 * If two pages need a similar benefit, they must use different ids with
 * distinct framing text.
 *
 * Add `framingOverride: true` to allow the same id on multiple pages
 * with explicitly different framing copy.
 */

export interface BenefitBullet {
  id: string;
  text: string;
  /** Pages where this exact benefit text may appear */
  allowedPages: string[];
  /** If true, the same id can appear on multiple pages with different text */
  framingOverride?: boolean;
}

export const benefits: BenefitBullet[] = [
  // ── Scoring & Analysis ──
  {
    id: 'BEN-SCORE-CLEAR',
    text: 'Understand pace, consistency, execution, and confidence at a glance',
    allowedPages: ['home'],
  },
  {
    id: 'BEN-CORNER-TARGETED',
    text: 'Fix the exact corner phase costing your lap time',
    allowedPages: ['home'],
  },
  {
    id: 'BEN-SESSION-READY',
    text: 'Leave with drills you can apply immediately on track',
    allowedPages: ['home'],
  },
  {
    id: 'BEN-DETERMINISTIC',
    text: 'Identical input produces identical output — checksum-verified',
    allowedPages: ['home', 'product', 'customers'],
    framingOverride: true,
  },
  {
    id: 'BEN-PHYSICS-MODEL',
    text: 'Corner expectations derived from vehicle behavior and track geometry',
    allowedPages: ['home', 'product'],
    framingOverride: true,
  },
  {
    id: 'BEN-CONTEXT-AWARE',
    text: 'Condition-aware adjustments keep progress tracking fair across sessions',
    allowedPages: ['home'],
  },

  // ── Speed & Ease ──
  {
    id: 'BEN-UNDER-MINUTE',
    text: 'Actionable scorecard in under a minute',
    allowedPages: ['home', 'pricing'],
    framingOverride: true,
  },
  {
    id: 'BEN-NO-DATA-SKILLS',
    text: 'No data science skills required — upload and get results',
    allowedPages: ['home', 'demo'],
    framingOverride: true,
  },

  // ── Strategy ──
  {
    id: 'BEN-RACE-PLAN',
    text: 'Build stint plans, pit windows, and fuel strategies before the green flag',
    allowedPages: ['home'],
  },
  {
    id: 'BEN-LIVE-PACE',
    text: 'Track every driver\'s pace delta and stint health in real time',
    allowedPages: ['home'],
  },
  {
    id: 'BEN-PIT-CALLS',
    text: 'Data-backed pit decisions with projected outcomes',
    allowedPages: ['home'],
  },

  // ── Trust & Compliance ──
  {
    id: 'BEN-GDPR',
    text: 'GDPR compliant with full data export and deletion',
    allowedPages: ['home', 'security', 'pricing'],
    framingOverride: true,
  },
  {
    id: 'BEN-ENCRYPTION',
    text: 'TLS 1.2+ in transit, AES-256 at rest',
    allowedPages: ['home', 'security'],
    framingOverride: true,
  },
  {
    id: 'BEN-EU-RESIDENCY',
    text: 'EU data residency — hosted on Hetzner DE',
    allowedPages: ['security'],
  },
  {
    id: 'BEN-MONEY-BACK',
    text: '30-day money back guarantee',
    allowedPages: ['home', 'pricing'],
    framingOverride: true,
  },
  {
    id: 'BEN-NO-LOCKIN',
    text: 'Cancel anytime, export everything',
    allowedPages: ['home', 'pricing'],
    framingOverride: true,
  },

  // ── Venue/B2B ──
  {
    id: 'BEN-QR-REPORTS',
    text: 'Autonomous QR recap for every driver',
    allowedPages: ['pricing', 'contact'],
    framingOverride: true,
  },
  {
    id: 'BEN-ZERO-STAFF',
    text: 'Zero staff pain — weekly battery swap only',
    allowedPages: ['pricing'],
  },
];

export function getBenefitById(id: string): BenefitBullet | undefined {
  return benefits.find((b) => b.id === id);
}

export function getBenefitsForPage(page: string): BenefitBullet[] {
  return benefits.filter((b) => b.allowedPages.includes(page));
}
