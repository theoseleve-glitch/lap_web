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
