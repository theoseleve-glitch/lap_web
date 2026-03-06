/**
 * Single source of truth for brand positioning.
 * Every marketing surface must reference these constants — no hardcoded synonyms.
 */

export const BRAND = {
  /** Legal entity name */
  companyName: 'Lap Coach',

  /** Product name (always uppercase in UI) */
  productName: 'LAP',

  /** 1 sentence. The full positioning statement. */
  positioning:
    'LAP turns raw telemetry into actionable coaching reports in under a minute, giving every kart and car driver access to professional-grade analysis without data science skills or expensive engineers.',

  /** 8–12 words. The elevator pitch. */
  oneLiner: 'Upload your session. Get professional coaching in minutes.',

  /** Ultra-short tagline used in nav, stamps, and compact UI. */
  tagline: 'Find Time.',

  /** Company address (EU/FR legal requirement) */
  address: {
    street: '5 rue Paré',
    city: 'Nantes',
    postalCode: '44000',
    country: 'France',
    full: '5 rue Paré, 44000 Nantes, France',
  },
} as const;

/**
 * Usage spec — maps each brand constant to where it appears.
 * Enforced via lint-duplicate-copy.mjs and code review.
 */
export const BRAND_USAGE = {
  hero: BRAND.tagline,
  metaDescriptionOpening: BRAND.oneLiner,
  pricingIntro: BRAND.oneLiner,
  navTagline: BRAND.tagline,
  ogCardSubtitle: BRAND.oneLiner,
  emailHeaderPreheader: BRAND.oneLiner,
  footerTagline: `${BRAND.productName} // ${BRAND.oneLiner}`,
} as const;

/* ── CTA Dictionary ────────────────────────────────────────── */

/**
 * Canonical CTA labels. Any button/link with CTA role must use one of these.
 * Enforced by lint-copy-standards.mjs.
 */
export const CTA_DICTIONARY = [
  'Start free',
  'See pricing',
  'Request demo',
  'Open app',
  'Contact sales',
  'Sign in',
  'Create account',
  'Join waitlist',
  'Book session',
  'Compare plans',
  'Upgrade',
  'Go World-Class',
  'Send message',
] as const;

export type CtaLabel = (typeof CTA_DICTIONARY)[number];

/* ── Name Tokens ───────────────────────────────────────────── */

/**
 * Canonical product and entity names.
 * - productName: always "LAP" in UI (caps)
 * - entityName: "Lap Coach" for legal/entity contexts only
 * Forbidden variants are caught by lint.
 */
export const NAME_TOKENS = {
  product: 'LAP',
  entity: 'Lap Coach',
  /** Forbidden product name variants (case-insensitive match) */
  forbiddenProductVariants: [
    'Lap Racing',
    'LAP Racing',
    'Lap Technologies',
    'LAP Technologies',
    'LapCoach',
    'lap-coach',
  ],
} as const;

/* ── Plan Naming ───────────────────────────────────────────── */

/** B2C plan names — used on pricing, billing, and driver-facing pages */
export const B2C_PLANS = ['Demo', 'Racer', 'World-Class'] as const;

/** B2B plan names — used on venue/team/enterprise-facing pages */
export const B2B_PLANS = ['Venue Pilot', 'Venue Pro', 'Enterprise'] as const;

/** Pages where B2B plan tokens are allowed */
export const B2B_ALLOWED_PAGES = [
  'contact', 'book', 'pricing', 'billing',
] as const;

/** Pages where B2C plan tokens are allowed */
export const B2C_ALLOWED_PAGES = [
  'pricing', 'billing', 'demo', 'product', 'customers', 'waitlist',
] as const;
