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

/* ── Numbers Policy ────────────────────────────────────────── */

/**
 * Formatting rules for numbers in marketing content.
 * Enforced by lint-copy-standards.mjs + src/lib/format-numbers.ts helper.
 */
export const NUMBERS_POLICY = {
  speed: 'km/h (not kph/kmh/KPH). No space before unit.',
  lapTime: '1:23.45 (mm:ss.cc) for display; 83.45s for inline prose.',
  deltas: '+0.32s or -0.15s (always sign, 2 decimal places, 0.01s precision).',
  percentages: 'No decimal unless < 1%. E.g., 36%, 0.8%.',
  grip: '1% increments. E.g., 87%.',
  currency: 'EUR with symbol prefix. E.g., \u20ac8.99.',
  decimalSeparator: '"." for EN, "," for FR. Enforced per page locale.',
  thousandsSeparator: 'None for < 10,000. Thin space (\u2009) for >= 10,000.',
  marketingRule: 'Max 2 decimal places for time/speed. 0 decimals for percentages.',
  msRule: '"ms" only in engineering/sub-second contexts. Marketing uses "seconds".',
} as const;

/* ── Tone Policy ──────────────────────────────────────────── */

/**
 * Default voice: single professional tone across all pages.
 * Per-persona tone variants allowed ONLY when:
 *  1. Persona has a distinct buying context AND
 *  2. Copy differs meaningfully (not synonyms)
 * Max 2 tone variants per page. Designated pages only.
 */
export const TONE_POLICY = {
  defaultVoice: 'professional-technical' as const,
  maxVariantsPerPage: 2,
  /** Pages allowed to have persona-specific tone variants */
  variantPages: ['pricing', 'product', 'demo'] as const,
  /** Persona tone descriptions (for copywriters, not runtime) */
  personaTones: {
    driver: 'Direct, performance-focused. "Your lap time. Your improvement."',
    venue: 'Operational, ROI-focused. "Revenue per session. Zero staff pain."',
    coach: 'Technical, collaborative. "Coaching data your drivers trust."',
  },
} as const;
